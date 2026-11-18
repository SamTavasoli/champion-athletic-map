"""Read-only, field-specific comparison of versioned Step 35 analysis outputs.

``compare_outputs`` never writes, imputes, sorts rows, drops fields, or silently
normalizes data.  Rules are declared here before looking at comparison results.
Discrete cells (including numeric IDs, counts and denominators) are exact text;
only listed measurement cells receive rtol=1e-10, atol=1e-12 by default.  Empty
cells remain empty and NaN/Inf are rejected in measurement cells.

Permitted differences are narrowly scoped:
* decoded NPZ members, dtype, shape and values are exact; ZIP metadata is not data;
* two named NumPy version fields may differ (both values are recorded);
* analysis IDs and report locations are independently bound to each run's input
  manifest SHA256; manifest file hashes are checked against that run's files;
* configured root relocations apply only at explicitly named JSON pointers;
* known SVG figures use font-verified labels and source chart geometry when
  presentation differs. If glyph decoding is unavailable, only complete vector
  identity apart from metadata plus passing source comparisons can establish
  reproduction equality; that route is reported without a semantic-decoding claim.

``config`` accepts ``rtol``, ``atol``, ``json_environment_fields`` (mapping of
filename to exact JSON pointers), ``json_path_fields`` (same shape), and
``original_root``/``reproduced_root`` for the named relocatable path fields.
Environment allowances add to the two defaults and apply only to strings; use
them only for actual recorded software/environment version fields, never data.
Every permitted difference is listed in the per-file details.  Unknown config
keys are rejected.  Defaults and ``comparison_policy()`` are JSON serializable.

Team review provenance is preserved verbatim.  A single assisted team review
does not become two independent raters or an agreement calculation.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from fractions import Fraction
from functools import lru_cache
from typing import Any, Mapping
import xml.etree.ElementTree as ET

import numpy as np


# Enumerated measurement columns; all other CSV columns compare exactly.
CSV_MEASUREMENTS = {
    "bootstrap_estimates.csv": ("estimate",),
    "bootstrap_intervals.csv": ("estimate", "lower_95", "upper_95"),
    "planner_summary.csv": ("percent",),
    "paired_comparisons.csv": ("difference_percentage_points",),
    "parent_check_summary.csv": ("coverage",),
    "classifier_per_class_metrics.csv": ("precision", "recall", "f1"),
    "classifier_confusion_matrices.csv": ("row_normalized",),
    "retrieval_summary.csv": ("value",),
    "retrieval_question_analysis.csv": ("recall_at_5", "reciprocal_rank_at_5"),
    "runtime_resource_summary.csv": (
        "mean_seconds", "median_seconds", "p95_seconds", "minimum_seconds", "maximum_seconds"
    ),
    "matched_runtime_comparisons.csv": (
        "mean_paired_difference_seconds", "median_paired_difference_seconds"
    ),
    "native_runtime_by_planner.csv": (
        "observed_first_role_wall_seconds_observed_sum", "observed_first_role_wall_seconds_sum",
        "reference_preparation_seconds_observed_sum", "reference_preparation_seconds_sum"
    ),
    "native_runtime_by_stage.csv": (
        "observed_first_role_wall_seconds_observed_sum", "observed_first_role_wall_seconds_sum",
        "reference_preparation_seconds_observed_sum", "reference_preparation_seconds_sum"
    ),
}

# JSON numeric paths are explicit.  '*' matches exactly one list index or key.
_TIMING_KEYS = ("mean_seconds", "median_seconds", "p95_seconds", "minimum_seconds", "maximum_seconds")
_RETRIEVAL_METRICS = ("mean_recall_at_5", "mrr_at_5", "complete_evidence_set_coverage_rate_at_5")
_CLASSIFIER_METRICS = ("accuracy", "macro_precision", "macro_recall", "macro_f1")
JSON_MEASUREMENTS = {
    "analysis_summary.json": (
        "/headline_planner_rows/*/percent",
        *(f"/timing_all_terminal/*/{key}" for key in _TIMING_KEYS),
        *(f"/retrieval/reported_route_metrics/*/{key}" for key in _RETRIEVAL_METRICS),
        *(f"/classifier/observed/*/{key}" for key in _CLASSIFIER_METRICS),
    ),
    "retrieval_analysis_status.json": tuple(
        f"/summary/reported_route_metrics/*/{key}" for key in _RETRIEVAL_METRICS
    ),
    "classifier_summary.json": tuple(f"/*/{key}" for key in _CLASSIFIER_METRICS),
    "classifier_analysis_status.json": tuple(f"/observed/*/{key}" for key in _CLASSIFIER_METRICS),
    "analysis_input_manifest.json": tuple(
        f"/classifier_status/observed/*/{key}" for key in _CLASSIFIER_METRICS
    ),
}
ENVIRONMENT_FIELDS = {
    "bootstrap_settings.json": ("/numpy_version",),
    "analysis_input_manifest.json": ("/bootstrap_settings/numpy_version",),
}
_SVG = "{http://www.w3.org/2000/svg}"
_XLINK = "{http://www.w3.org/1999/xlink}"
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def comparison_policy() -> dict[str, Any]:
    """Return the predeclared default rules for inclusion in verification config."""
    return {
        "schema_version": "step36-comparison-policy-2",
        "rtol": 1e-10,
        "atol": 1e-12,
        "csv_measurement_columns": {key: list(value) for key, value in CSV_MEASUREMENTS.items()},
        "json_measurement_fields": {key: list(value) for key, value in JSON_MEASUREMENTS.items()},
        "json_environment_fields": {key: list(value) for key, value in ENVIRONMENT_FIELDS.items()},
        "discrete_policy": "Exact paths, CSV schema and row order, labels, statuses, IDs, counts, denominators, memberships and draws; no imputation.",
        "npz_policy": "Exact member names, dtype, shape and array values; ZIP headers/timestamps excluded.",
        "manifest_policy": "Each output manifest hash is validated against its own file; ID binds to input-manifest bytes, and summary locations bind to ID.",
        "svg_policy": "Parse SVG and require matching figure source tables. Verify Unicode/glyph-index references against actual font outlines, labels, populations and chart geometry (bars1e-4 units, classifier CI/points1e-7 units) when presentation differs. If semantic glyph decoding is unavailable, permit only exact complete vector/presentation identity apart from metadata, with passing source comparisons; report equality-only evidence explicitly. Changed vectors cannot use that route.",
        "svg_implementation_correction": "Font-specific glyph indices are not Unicode codepoints. This correction follows the saved Step36 font-decoding failure; numeric tolerances, frozen analysis code and scientific results are unchanged.",
        "review_provenance": "One assisted team review; original independent raters and agreement unavailable. Preserve the recorded status without inventing ratings.",
    }


def _config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    supplied = dict(config or {})
    known = {"rtol", "atol", "json_environment_fields", "json_path_fields", "original_root", "reproduced_root"}
    unknown = set(supplied) - known
    if unknown:
        raise ValueError("Unknown comparison config fields: " + ", ".join(sorted(unknown)))
    result = {"rtol": 1e-10, "atol": 1e-12, **supplied}
    for key in ("rtol", "atol"):
        if isinstance(result[key], bool) or not isinstance(result[key], (int, float)) or not math.isfinite(result[key]) or result[key] < 0:
            raise ValueError(f"{key} must be finite and nonnegative")
    extra_environment = supplied.get("json_environment_fields", {})
    if not isinstance(extra_environment, Mapping):
        raise ValueError("json_environment_fields must be a filename-to-JSON-pointer mapping")
    environment = {key: list(value) for key, value in ENVIRONMENT_FIELDS.items()}
    for filename, pointers in extra_environment.items():
        if not isinstance(pointers, (tuple, list)):
            raise ValueError("json_environment_fields values must be lists of exact JSON pointers")
        environment.setdefault(filename, []).extend(pointers)
    result["json_environment_fields"] = environment
    result.setdefault("json_path_fields", {})
    for mapping_key in ("json_environment_fields", "json_path_fields"):
        if not isinstance(result[mapping_key], Mapping):
            raise ValueError(mapping_key + " must be a filename-to-JSON-pointer mapping")
        for filename, pointers in result[mapping_key].items():
            if not isinstance(filename, str) or not isinstance(pointers, (tuple, list)) or not all(isinstance(p, str) and p.startswith("/") and "*" not in p for p in pointers):
                raise ValueError(mapping_key + " requires exact JSON pointers without wildcards")
    if result["json_path_fields"] and not all(result.get(key) for key in ("original_root", "reproduced_root")):
        raise ValueError("Named relocatable path fields require both roots")
    return result


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _row(name: str, method: str, errors: list[str], notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "filepath": name,
        "method": method,
        "status": "failed" if errors else "passed",
        "details": json.dumps({"errors": errors[:20], "error_count": len(errors), "notes": notes or []}, ensure_ascii=False, sort_keys=True),
    }


def _inventory(folder: Path) -> set[str]:
    if not folder.is_dir():
        raise ValueError(f"Analysis folder is missing: {folder}")
    files = set()
    for path in folder.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Analysis outputs must not contain symlinks: {path.relative_to(folder)}")
        if path.is_file():
            files.add(path.relative_to(folder).as_posix())
    return files


def _json(path: Path) -> Any:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs,
                      parse_constant=lambda token: (_ for _ in ()).throw(ValueError("Nonfinite JSON value: " + token)))


def _pointer(parts: tuple[str, ...]) -> str:
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


def _matches(pattern: str, parts: tuple[str, ...]) -> bool:
    decoded = tuple(p.replace("~1", "/").replace("~0", "~") for p in pattern.split("/")[1:])
    return len(decoded) == len(parts) and all(wanted == "*" or wanted == actual for wanted, actual in zip(decoded, parts))


def _close(a: Any, b: Any, config: dict[str, Any]) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    try:
        left, right = float(a), float(b)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, rel_tol=config["rtol"], abs_tol=config["atol"])


def _relocated(a: str, b: str, config: dict[str, Any]) -> bool:
    # Pure lexical relocation: no resolving arbitrary paths or replacing substrings.
    try:
        left = PurePosixPath(a).relative_to(PurePosixPath(str(config["original_root"])))
        right = PurePosixPath(b).relative_to(PurePosixPath(str(config["reproduced_root"])))
    except (ValueError, KeyError):
        return False
    return left == right and ".." not in left.parts


def _compare_json(a: Any, b: Any, filename: str, config: dict[str, Any], parts: tuple[str, ...] = (), errors: list[str] | None = None, notes: list[str] | None = None):
    errors = [] if errors is None else errors
    notes = [] if notes is None else notes
    pointer = _pointer(parts)
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            errors.append(f"{pointer}: JSON keys differ; missing={sorted(set(a)-set(b))}, unexpected={sorted(set(b)-set(a))}")
        for key in sorted(set(a) & set(b)):
            _compare_json(a[key], b[key], filename, config, parts + (key,), errors, notes)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            errors.append(f"{pointer}: list lengths differ: {len(a)} != {len(b)}")
        for i, (left, right) in enumerate(zip(a, b)):
            _compare_json(left, right, filename, config, parts + (str(i),), errors, notes)
    elif type(a) is type(b) and a == b:
        pass
    elif pointer in config["json_environment_fields"].get(filename, ()):
        if isinstance(a, str) and isinstance(b, str) and a and b:
            notes.append(f"Allowed environment metadata {pointer}: {a!r} -> {b!r}")
        else:
            errors.append(f"{pointer}: environment metadata must remain a nonempty version string")
    elif pointer in config["json_path_fields"].get(filename, ()):
        if isinstance(a, str) and isinstance(b, str) and _relocated(a, b, config):
            notes.append(f"Allowed explicit root relocation {pointer}: {a!r} -> {b!r}")
        else:
            errors.append(f"{pointer}: named path is not an exact root relocation")
    elif any(_matches(pattern, parts) for pattern in JSON_MEASUREMENTS.get(filename, ())) and _close(a, b, config):
        notes.append(f"Within numeric tolerance {pointer}: {a!r} -> {b!r}")
    else:
        errors.append(f"{pointer}: {a!r} != {b!r}")
    return errors, notes


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    if not rows or not rows[0] or len(rows[0]) != len(set(rows[0])):
        raise ValueError("CSV header is absent or duplicated")
    width = len(rows[0])
    if any(len(row) != width for row in rows[1:]):
        raise ValueError("CSV has a row with a different width from its schema")
    return rows[0], rows[1:]


def _compare_csv(left: Path, right: Path, name: str, config: dict[str, Any]):
    headers, a = _read_csv(left)
    other_headers, b = _read_csv(right)
    errors, notes = [], []
    if headers != other_headers:
        return [f"CSV schema/order differs: {headers!r} != {other_headers!r}"], notes
    if len(a) != len(b):
        errors.append(f"Row count differs: {len(a)} != {len(b)}")
    tolerant_cells = 0
    for index, (row_a, row_b) in enumerate(zip(a, b), start=2):
        for field, value_a, value_b in zip(headers, row_a, row_b):
            # Blank vs zero/NA/null and all unlisted columns are deliberately exact.
            if value_a == value_b:
                if field in CSV_MEASUREMENTS.get(name, ()) and value_a and not _close(value_a, value_b, config):
                    errors.append(f"row {index}, {field}: invalid/nonfinite measurement {value_a!r}")
            elif field in CSV_MEASUREMENTS.get(name, ()) and value_a and value_b and _close(value_a, value_b, config):
                tolerant_cells += 1
            else:
                errors.append(f"row {index}, {field}: {value_a!r} != {value_b!r}")
    notes.append(f"Exact CSV schema and row order; {len(a)} original rows; {tolerant_cells} differing measurement cells within rtol={config['rtol']}, atol={config['atol']}")
    return errors, notes


def _compare_npz(left: Path, right: Path):
    errors, notes = [], []
    with np.load(left, allow_pickle=False) as a, np.load(right, allow_pickle=False) as b:
        if len(a.files) != len(set(a.files)) or len(b.files) != len(set(b.files)):
            errors.append("NPZ contains duplicate array member names")
        if set(a.files) != set(b.files):
            errors.append(f"NPZ member names differ: {a.files!r} != {b.files!r}")
        for name in sorted(set(a.files) & set(b.files)):
            x, y = a[name], b[name]
            if x.dtype != y.dtype or x.shape != y.shape or not np.array_equal(x, y):
                errors.append(f"NPZ {name}: dtype/shape/value mismatch ({x.dtype}, {x.shape}) vs ({y.dtype}, {y.shape})")
            else:
                notes.append(f"Exact array {name}: dtype={x.dtype}, shape={list(x.shape)}, elements={x.size}")
    if left.read_bytes() != right.read_bytes() and not errors:
        notes.append("Archive bytes differ; decoded arrays are exactly equal (ZIP container metadata is excluded)")
    return errors, notes


def _manifest_errors(folder: Path, inventory: set[str]) -> tuple[list[str], dict[str, Any] | None]:
    errors = []
    if "output_manifest.json" not in inventory:
        return ["Required output_manifest.json is absent"], None
    document = _json(folder / "output_manifest.json")
    if not isinstance(document, dict) or set(document) != {"schema_version", "analysis_id", "files"}:
        return ["Unexpected output manifest schema"], document
    files = document["files"]
    if not isinstance(files, dict):
        return ["Output manifest files is not a mapping"], document
    expected = set(files) | {"output_manifest.json"}
    if inventory != expected:
        errors.append(f"Manifest inventory mismatch: missing={sorted(expected-inventory)}, unexpected={sorted(inventory-expected)}")
    for name, expected_sha in files.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
            errors.append(f"Unsafe manifest path: {name!r}")
        elif name in inventory and (not isinstance(expected_sha, str) or _sha(folder / name) != expected_sha):
            errors.append(f"Manifest hash mismatch: {name}")
    if "analysis_input_manifest.json" in inventory:
        identity = _sha(folder / "analysis_input_manifest.json")
        if document.get("analysis_id") != identity:
            errors.append("analysis_id is not the SHA256 of analysis_input_manifest.json")
        inputs = _json(folder / "analysis_input_manifest.json")
        # These are duplicated records in Step 35, not independent measurements.
        # Even allowed version metadata must agree inside one analysis run.
        for key, filename in (("bootstrap_settings", "bootstrap_settings.json"),
                              ("method_note", "analysis_method_note.json"),
                              ("classifier_status", "classifier_analysis_status.json")):
            if key in inputs and (filename not in inventory or inputs[key] != _json(folder / filename)):
                errors.append(f"Input manifest /{key} disagrees with {filename}")
    else:
        errors.append("Required analysis_input_manifest.json is absent")
    return errors, document


def _summary_binding(document: dict[str, Any], folder: Path) -> list[str]:
    errors = []
    if not (folder / "analysis_input_manifest.json").is_file():
        return ["Cannot bind summary without analysis_input_manifest.json"]
    identity = _sha(folder / "analysis_input_manifest.json")
    analysis_folder = "results/statistical_analysis/analysis_" + identity[:20]
    expected = {"analysis_id": identity, "input_manifest_sha256": identity, "analysis_folder": analysis_folder,
                "findings_path": analysis_folder + "/statistical_analysis_findings.md",
                "report_path": analysis_folder + "/analysis_report.html"}
    for key, value in expected.items():
        if document.get(key) != value:
            errors.append(f"{key} does not bind to this run's input manifest/analysis ID")
    return errors


def _csv_dicts(folder: Path, name: str) -> list[dict[str, str]]:
    fields, rows = _read_csv(folder / name)
    return [dict(zip(fields, row)) for row in rows]


@lru_cache(maxsize=None)
def _svg_font_path(postscript_name: str) -> str:
    """Locate the installed font named by a Matplotlib glyph ID, fail closed."""
    try:
        from matplotlib import font_manager, ft2font
    except ImportError as exc:
        raise ValueError("Matplotlib is required to verify SVG glyph outlines") from exc
    for entry in font_manager.fontManager.ttflist:
        try:
            font = ft2font.FT2Font(entry.fname)
        except (OSError, RuntimeError):
            continue
        if font.postscript_name == postscript_name:
            return str(entry.fname)
    raise ValueError("Cannot verify SVG glyph font: " + postscript_name)


def _svg_path_signature(path: ET.Element) -> tuple:
    """Compare actual outline coordinates exactly after its uniform scale.

    SVG path whitespace and 64-unit encoding are serialization choices.  No
    coordinate tolerance is used; unsupported glyph presentation fails closed.
    """
    if path.tag != _SVG + "path" or set(path.attrib) - {"id", "d", "transform"}:
        raise ValueError("SVG glyph definition has unsupported presentation")
    transform = path.get("transform", "").strip()
    scale = Fraction(1)
    if transform:
        match = re.fullmatch(r"scale\(\s*(" + _NUMBER + r")\s*\)", transform)
        if not match:
            raise ValueError("SVG glyph definition has unsupported transform")
        scale = Fraction(match.group(1))
        if scale <= 0:
            raise ValueError("SVG glyph definition has nonpositive scale")
    data = path.get("d", "")
    tokens = re.findall(_NUMBER + r"|[MLQCz]", data)
    if re.sub(_NUMBER + r"|[MLQCz]|[\s,]+", "", data):
        raise ValueError("SVG glyph outline has unsupported path commands")
    return tuple(token if token in {"M", "L", "Q", "C", "z"} else Fraction(token)*scale
                 for token in tokens)


@lru_cache(maxsize=None)
def _svg_glyph_candidates(postscript_name: str, suffix: int, signature: tuple) -> frozenset[str]:
    """Bind either historic codepoint IDs or newer glyph-index IDs to outlines.

    An ID suffix and source comment are insufficient evidence: the referenced
    vector outline must equal the named installed font's actual glyph.  The
    inverse cmap also handles glyph-index IDs without assuming an offset.
    """
    from matplotlib import _path, ft2font
    from matplotlib.path import Path as MplPath
    font = ft2font.FT2Font(_svg_font_path(postscript_name))
    font.set_size(100, 72)  # Matplotlib TextToPath.FONT_SCALE and DPI.
    cmap = font.get_charmap()
    possible = {codepoint for codepoint, index in cmap.items() if index == suffix}
    if suffix in cmap:
        possible.add(suffix)
    flags = ft2font.LoadFlags.NO_HINTING if hasattr(ft2font, "LoadFlags") else ft2font.LOAD_NO_HINTING
    candidates = set()
    for codepoint in possible:
        font.load_glyph(cmap[codepoint], flags=flags)
        vertices, codes = font.get_path()
        data = _path.convert_to_string(MplPath(vertices*64, codes), None, None, False, None,
                                       6, [b"M", b"L", b"Q", b"C", b"z"], False).decode("ascii")
        expected = ET.Element(_SVG + "path", d=data, transform="scale(0.015625)")
        if _svg_path_signature(expected) == signature:
            candidates.add(chr(codepoint))
    return frozenset(candidates)


class _SvgGlyphResolver:
    """Document-wide ID lookup, also used when validating an axis/tick subtree."""

    def __init__(self, root: ET.Element):
        self.definitions = {element.get("id"): element for element in root.iter() if element.get("id")}
        self.candidates: dict[str, frozenset[str]] = {}

    def resolve(self, href: str) -> frozenset[str]:
        if href not in self.candidates:
            match = re.fullmatch(r"#([A-Za-z][A-Za-z0-9_\-]*)-([0-9a-fA-F]+)", href)
            definition = self.definitions.get(href[1:])
            if not match or definition is None:
                raise ValueError("Cannot decode an SVG text glyph reference: " + href)
            signature = _svg_path_signature(definition)
            candidates = _svg_glyph_candidates(match.group(1), int(match.group(2), 16), signature)
            if not candidates:
                raise ValueError("SVG text glyph outline does not match its font/codepoint or glyph index: " + href)
            self.candidates[href] = candidates
        return self.candidates[href]


def _svg_labels(root: ET.Element, glyph_resolver: _SvgGlyphResolver | None = None) -> list[str]:
    """Read text or independently verified glyph outlines; cross-check comments."""
    labels = []
    resolver = glyph_resolver or _SvgGlyphResolver(root)
    for element in root.iter():
        if element.tag == _SVG + "text":
            labels.append("".join(element.itertext()))
        elif element.tag == _SVG + "g" and re.fullmatch(r"text_\d+", element.get("id", "")):
            if any(child.tag == _SVG + "text" for child in element.iter()):
                continue
            glyphs = [resolver.resolve(child.get(_XLINK + "href", child.get("href", "")))
                      for child in element.iter(_SVG + "use")]
            comments = [str(child.text).strip() for child in element if child.tag is ET.Comment]
            if comments:
                # A comment can select among true cmap aliases only after each
                # glyph outline has independently established those candidates.
                if len(comments) != 1 or len(comments[0]) != len(glyphs) or any(
                        character not in candidates for character, candidates in zip(comments[0], glyphs)):
                    raise ValueError(f"SVG text comment disagrees with rendered glyphs: {comments!r}")
                rendered = comments[0]
            else:
                if any(len(candidates) != 1 for candidates in glyphs):
                    raise ValueError("SVG glyph outline has ambiguous Unicode mapping")
                rendered = "".join(next(iter(candidates)) for candidates in glyphs)
            if not rendered:
                raise ValueError("SVG text group has no rendered text")
            labels.append(rendered)
    return labels


def _parse_svg(path: Path) -> ET.Element:
    raw = path.read_bytes()
    if re.search(rb"<!ENTITY\b|<script\b|<foreignObject\b|<image\b", raw, re.I):
        raise ValueError("SVG has entity/script/foreign/raster content")
    root = ET.fromstring(raw, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    if root.tag != _SVG + "svg" or next(root.iter(_SVG + "path"), None) is None:
        raise ValueError("Figure is not a populated vector SVG")
    all_ids = [element.get("id") for element in root.iter() if element.get("id")]
    ids = set(all_ids)
    if len(ids) != len(all_ids):
        raise ValueError("SVG has duplicate element IDs")
    for element in root.iter():
        if isinstance(element.tag, str) and element.tag.rsplit("}", 1)[-1].lower() in ("image", "script", "foreignobject"):
            raise ValueError("SVG has script/foreign/raster content")
        for key, value in element.attrib.items():
            if key in ("href", _XLINK + "href") and (not value.startswith("#") or value[1:] not in ids):
                raise ValueError("SVG has an external or unresolved reference")
            if key == "style" and re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:;|$))", value):
                raise ValueError("SVG hides visual content")
    return root


def _single_label(element: ET.Element, glyph_resolver: _SvgGlyphResolver | None = None) -> str:
    values = _svg_labels(element, glyph_resolver)
    if len(values) != 1:
        raise ValueError("Expected exactly one tick label")
    return values[0]


def _bars_from_axis(axis: ET.Element, glyph_resolver: _SvgGlyphResolver | None = None) -> list[float]:
    ticks = []
    for element in axis.iter(_SVG + "g"):
        if re.fullmatch(r"ytick_\d+", element.get("id", "")):
            label = _single_label(element, glyph_resolver).replace("−", "-")
            if not re.fullmatch(_NUMBER, label):
                raise ValueError("Bar chart has a nonnumeric y tick")
            tick_mark = next((use for use in element.iter(_SVG + "use") if "y" in use.attrib), None)
            if tick_mark is None:
                raise ValueError("Bar chart tick has no coordinate")
            ticks.append((float(tick_mark.attrib["y"]), float(label)))
    if len(ticks) < 2 or len({p[0] for p in ticks}) != len(ticks):
        raise ValueError("Bar chart needs distinct calibrated y ticks")
    first, last = ticks[0], ticks[-1]
    slope = (last[1] - first[1]) / (last[0] - first[0])
    intercept = first[1] - first[0] * slope
    if slope >= 0 or any(abs(slope * y + intercept - value) > 1e-4 for y, value in ticks):
        raise ValueError("Bar chart y axis is not the expected linear ascending scale")
    rectangles = []
    for group in axis:
        if group.tag != _SVG + "g" or not re.fullmatch(r"patch_\d+", group.get("id", "")):
            continue
        path = next(group.iter(_SVG + "path"), None)
        if path is None:
            continue
        style = path.get("style", "")
        fill = re.search(r"(?:^|;)\s*fill\s*:\s*([^;]+)", style)
        if not fill or fill.group(1).strip() in ("none", "#ffffff", "white"):
            continue
        commands = re.findall(r"[A-Za-z]", path.get("d", ""))
        values = [float(value) for value in re.findall(_NUMBER, path.get("d", ""))]
        if commands != ["M", "L", "L", "L", "z"] or len(values) != 8:
            raise ValueError("Bar chart patch is not a rectangular bar")
        points = list(zip(values[::2], values[1::2]))
        if len({p[0] for p in points}) != 2 or len({p[1] for p in points}) > 2:
            raise ValueError("Bar chart has a nonrectangular data patch")
        baseline, top = max(p[1] for p in points), min(p[1] for p in points)
        if abs(slope * baseline + intercept) > 1e-4:
            raise ValueError("Bar does not start at zero")
        rectangles.append((min(p[0] for p in points), slope * top + intercept))
    return [value for _, value in sorted(rectangles)]


def _classifier_geometry(axis: ET.Element, selected: list[dict[str, str]], glyph_resolver: _SvgGlyphResolver | None = None) -> list[str]:
    """Calibrate a difference plot from its actual ticks and inspect line/points."""
    errors, ticks, category_positions = [], [], {}
    names = {"logistic_regression_minus_majority": "Logistic − majority",
             "neural_minus_majority": "Neural − majority",
             "neural_minus_logistic_regression": "Neural − logistic"}
    for group in axis.iter(_SVG + "g"):
        identifier = group.get("id", "")
        if re.fullmatch(r"xtick_\d+", identifier):
            label = _single_label(group, glyph_resolver).replace("−", "-")
            tick_mark = next((use for use in group.iter(_SVG + "use") if "x" in use.attrib), None)
            if not re.fullmatch(_NUMBER, label) or tick_mark is None:
                raise ValueError("Classifier difference plot has an uncalibrated x tick")
            ticks.append((float(tick_mark.attrib["x"]), float(label)))
        elif re.fullmatch(r"ytick_\d+", identifier):
            label = _single_label(group, glyph_resolver)
            tick_mark = next((use for use in group.iter(_SVG + "use") if "y" in use.attrib), None)
            if label in category_positions or tick_mark is None:
                raise ValueError("Classifier difference plot has duplicate/unpositioned category ticks")
            category_positions[label] = float(tick_mark.attrib["y"])
    if len(ticks) < 2 or len({x for x, _ in ticks}) != len(ticks):
        raise ValueError("Classifier difference plot needs distinct calibrated x ticks")
    slope = (ticks[-1][1] - ticks[0][1]) / (ticks[-1][0] - ticks[0][0])
    intercept = ticks[0][1] - slope * ticks[0][0]
    if slope <= 0 or any(abs(slope*x + intercept-value) > 1e-7 for x, value in ticks):
        raise ValueError("Classifier plot x ticks do not define the expected linear difference scale")
    if set(category_positions) != set(names.values()):
        raise ValueError("Classifier plot does not have exactly the three prespecified contrast labels")
    # Values below are SVG rounding checks, not a waiver for numeric source data.
    # Source endpoints/estimates separately use the stricter declared tolerance.
    line_values, point_values, zero_lines = {}, {}, 0
    for group in axis:
        if group.tag != _SVG + "g" or not re.fullmatch(r"line2d_\d+", group.get("id", "")):
            continue
        paths = [element for element in group if element.tag == _SVG + "path"]
        uses = [element for element in group.iter(_SVG + "use") if "x" in element.attrib and "y" in element.attrib]
        if paths and uses:
            raise ValueError("Classifier plot has an unexpected mixed line/marker data object")
        if paths:
            if len(paths) != 1:
                raise ValueError("Classifier plot has an unexpected multiple-path data object")
            path = paths[0]
            if re.findall(r"[A-Za-z]", path.get("d", "")) != ["M", "L"]:
                raise ValueError("Classifier plot confidence interval is not a straight line")
            values = [float(number) for number in re.findall(_NUMBER, path.get("d", ""))]
            if len(values) != 4:
                raise ValueError("Classifier plot line has unexpected coordinates")
            x1, y1, x2, y2 = values
            if abs(x1-x2) < 1e-6 and abs(y1-y2) > 1e-6:
                zero_lines += 1
                if abs(slope*x1 + intercept) > 1e-7:
                    errors.append("Classifier difference reference line is not at zero")
                continue
            if abs(y1-y2) > 1e-6:
                raise ValueError("Classifier confidence interval is not horizontal")
            labels = [label for label, y in category_positions.items() if abs(y-y1) < 1e-4]
            if len(labels) != 1 or labels[0] in line_values:
                raise ValueError("Classifier interval is detached from its unique contrast label")
            line_values[labels[0]] = sorted((slope*x1+intercept, slope*x2+intercept))
        elif uses:
            if len(uses) != 1:
                raise ValueError("Classifier plot has an unexpected multiple-marker data object")
            marker = uses[0]
            x, y = float(marker.attrib["x"]), float(marker.attrib["y"])
            labels = [label for label, coordinate in category_positions.items() if abs(coordinate-y) < 1e-4]
            if len(labels) != 1 or labels[0] in point_values:
                raise ValueError("Classifier estimate point is detached from its unique contrast label")
            point_values[labels[0]] = slope*x+intercept
        else:
            raise ValueError("Classifier plot has an empty/unrecognized data object")
    if set(line_values) != set(names.values()) or set(point_values) != set(names.values()) or zero_lines != 1:
        errors.append("Classifier plot must have one interval and estimate per contrast and one zero-reference line")
    for row in selected:
        label = names[row["model_or_contrast"]]
        if label in line_values and any(abs(actual-float(row[key])) > 1e-7 for actual, key in zip(line_values[label], ("lower_95", "upper_95"))):
            errors.append("Classifier CI line geometry differs from source endpoints: " + row["model_or_contrast"])
        if label in point_values and abs(point_values[label]-float(row["estimate"])) > 1e-7:
            errors.append("Classifier point geometry differs from source estimate: " + row["model_or_contrast"])
    return errors


def _validate_known_figure(root: ET.Element, folder: Path, name: str, glyph_resolver: _SvgGlyphResolver | None = None) -> tuple[list[str], list[str]]:
    errors, notes = [], []
    glyph_resolver = glyph_resolver or _SvgGlyphResolver(root)
    labels = _svg_labels(root, glyph_resolver)
    axes = [element for element in root.iter(_SVG + "g") if re.fullmatch(r"axes_\d+", element.get("id", ""))]
    if name == "figures/planner_execution.svg":
        expected_titles = ("Response format", "Workflow completion")
        expected_metrics = ("strict_format_valid", "designated_workflow_completed")
        required = ["Saved comparison: 200 matched profiles, four planners", "Outcomes out of 200", *expected_titles]
        rows = _csv_dicts(folder, "planner_summary.csv")
        if len(axes) != 2:
            return ["Expected two planner execution panels"], notes
        for axis, metric, title in zip(axes, expected_metrics, expected_titles):
            selected = [row for row in rows if row["population"] == "all_planner" and row["metric"] == metric]
            if {row["planner"] for row in selected} != {"1", "2", "3", "4"} or len(selected) != 4 or any(row["denominator"] != "200" or row["families"] != "200" for row in selected):
                errors.append("Execution figure source population/denominators differ from four matched planners with 200 outcomes each")
                continue
            by_planner = {row["planner"]: row for row in selected}
            values = [float(by_planner[str(planner)]["numerator"]) for planner in range(1, 5)]
            bar_values = _bars_from_axis(axis, glyph_resolver)
            if len(bar_values) != 4 or any(abs(a-b) > 1e-4 for a, b in zip(values, bar_values)):
                errors.append(f"{title}: plotted bar geometry differs from exact source counts")
            axis_labels = _svg_labels(axis, glyph_resolver)
            for planner, value in enumerate(values, 1):
                if f"Planner {planner}" not in axis_labels or str(int(value)) not in axis_labels:
                    errors.append(f"{title}: missing rendered planner/count label")
            if title not in axis_labels:
                errors.append(f"Missing panel label: {title}")
        notes.append("Execution panels checked against planner_summary.csv: numerator, denominator=200, family membership population and rendered labels")
    elif name == "figures/planner_runtime.svg":
        required = ["Median end-to-end time (seconds)", "All terminal workflows, including failures (200 per planner)"]
        rows = [row for row in _csv_dicts(folder, "runtime_resource_summary.csv") if row["population"] == "all_terminal"]
        if len(axes) != 1 or len(rows) != 4 or {row["planner"] for row in rows} != {"1", "2", "3", "4"} or any(row["outcomes"] != "200" or row["measured"] != "200" or row["missing"] != "0" for row in rows):
            return ["Runtime figure source population differs from four fully measured all-terminal sets of 200"], notes
        by_planner = {row["planner"]: row for row in rows}
        values = [float(by_planner[str(planner)]["median_seconds"]) for planner in range(1, 5)]
        bar_values = _bars_from_axis(axes[0], glyph_resolver)
        if len(bar_values) != 4 or any(abs(a-b) > 1e-4 for a, b in zip(values, bar_values)):
            errors.append("Runtime plotted bar geometry differs from source medians")
        for planner, value in enumerate(values, 1):
            if f"Planner {planner}" not in labels or f"{value:.2f} s" not in labels:
                errors.append("Runtime figure is missing rendered planner/median labels")
        notes.append("Runtime panel checked against runtime_resource_summary.csv: all_terminal population, measured denominator, medians and rendered labels")
    elif name == "figures/classifier_macro_f1_differences.svg":
        required = ["Macro-F1 difference (0–1 scale)", "Paired exercise-group bootstrap: individual 95% intervals",
                    "Logistic − majority", "Neural − majority", "Neural − logistic"]
        selected = [row for row in _csv_dicts(folder, "bootstrap_intervals.csv")
                    if row["population"] == "classifier_test" and row["metric"] == "macro_f1" and "_minus_" in row["model_or_contrast"]]
        contrasts = {"logistic_regression_minus_majority", "neural_minus_majority", "neural_minus_logistic_regression"}
        population = [row for row in _csv_dicts(folder, "analysis_populations.csv") if row["population"] == "classifier_test"]
        settings = _json(folder / "bootstrap_settings.json")
        groups = settings["groups"]["classifier_test"]
        if len(axes) != 1 or len(selected) != 3 or {row["model_or_contrast"] for row in selected} != contrasts:
            return ["Classifier figure lacks exactly three prespecified macro-F1 contrasts in one panel"], notes
        if not population or len({row["record_id"] for row in population}) != len(population) or any(not row.get("target_label") for row in population):
            errors.append("Classifier figure source population has missing/duplicate record IDs or missing class labels")
        if sorted(set(row["group_id"] for row in population)) != groups:
            errors.append("Classifier plot population group membership differs from bootstrap settings")
        for row in selected:
            if (int(row["profiles"]) != len(population) or int(row["groups"]) != len(groups) or
                    int(row["resamples"]) != settings["resamples"] or row["unit"] != "raw_0_to_1_score_difference" or row["status"] != "computed"):
                errors.append("Classifier interval population/group denominator, resampling or unit differs from source settings")
        errors.extend(_classifier_geometry(axes[0], selected, glyph_resolver))
        notes.append("Classifier CI endpoints and estimate points calibrated from actual SVG axes against bootstrap_intervals.csv; contrast labels, zero-reference, record IDs, class labels and group memberships checked")
    else:
        # Future figure formats need their own semantic validator before layout
        # differences may pass.  The caller only permits exact vector content.
        return [], ["Unrecognized figure: exact SVG content required apart from metadata"]
    for label in required:
        if label not in labels:
            errors.append("Missing required rendered figure label: " + label)
    return errors, notes


def _svg_without_metadata(root: ET.Element):
    def encode(element):
        if element.tag == _SVG + "metadata":
            return None
        return (str(element.tag), tuple(sorted(element.attrib.items())), (element.text or "").strip(),
                tuple(encoded for child in element if (encoded := encode(child)) is not None))
    return encode(root)


def _compare_svg(left: Path, right: Path, name: str, source_status: dict[str, str]):
    a, b = _parse_svg(left), _parse_svg(right)
    errors, notes = [], []
    dependencies = {"figures/planner_execution.svg": ("planner_summary.csv", "analysis_populations.csv"),
                    "figures/planner_runtime.svg": ("runtime_resource_summary.csv", "analysis_populations.csv"),
                    "figures/classifier_macro_f1_differences.svg": ("bootstrap_intervals.csv", "analysis_populations.csv", "bootstrap_settings.json")}
    if name in dependencies:
        for dependency in dependencies[name]:
            if source_status.get(dependency) != "passed":
                errors.append("Figure source did not pass comparison: " + dependency)
    left_glyphs, right_glyphs = _SvgGlyphResolver(a), _SvgGlyphResolver(b)
    try:
        left_labels, right_labels = _svg_labels(a, left_glyphs), _svg_labels(b, right_glyphs)
    except ValueError as exc:
        # A new font/shaper may use glyph IDs or ligatures unavailable locally.
        # Equality of the complete vector tree is independent reproduction
        # evidence; no changed glyph, bar or CI geometry can use this fallback.
        if name in dependencies and not errors and _svg_without_metadata(a) == _svg_without_metadata(b):
            return [], ["Exact vector/presentation content matches the preserved original apart from metadata; all figure source dependencies passed. "
                        "Semantic glyph decoding unavailable: " + str(exc)]
        raise
    if left_labels != right_labels:
        errors.append("Rendered SVG labels/order differ")
    if name in dependencies:
        for label, root, folder, glyphs in (("original", a, left.parent.parent, left_glyphs), ("reproduced", b, right.parent.parent, right_glyphs)):
            validation, evidence = _validate_known_figure(root, folder, name, glyphs)
            errors.extend(f"{label}: {message}" for message in validation)
            notes.extend(f"{label}: {message}" for message in evidence)
        if left.read_bytes() != right.read_bytes() and not errors:
            notes.append("Renderer metadata/layout differs; vector content, actual labels, populations and source plotted values validated")
    elif _svg_without_metadata(a) != _svg_without_metadata(b):
        errors.append("Unrecognized SVG has changed vector/presentation content; semantic validator required")
    return errors, notes


def compare_outputs(original_folder: str | Path, reproduced_folder: str | Path,
                    config: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Compare two analysis folders read-only; return per-file CSV-ready rows.

    Comparison failures are rows with status ``failed``.  Bad config or absent
    folders raise ValueError.  Malformed individual files are reported as failures
    so one bad output does not suppress comparison of the remaining outputs.
    """
    settings = _config(config)
    original, reproduced = Path(original_folder), Path(reproduced_folder)
    inventory_a, inventory_b = _inventory(original), _inventory(reproduced)
    rows, source_status = [], {}
    manifests, manifest_failures = {}, []
    for label, folder, inventory in (("original", original, inventory_a), ("reproduced", reproduced, inventory_b)):
        try:
            errors, manifests[label] = _manifest_errors(folder, inventory)
        except Exception as exc:
            errors, manifests[label] = [f"{type(exc).__name__}: {exc}"], None
        manifest_failures.extend(f"{label}: {error}" for error in errors)
    missing = sorted(inventory_a - inventory_b)
    unexpected = sorted(inventory_b - inventory_a)
    # One explicit row per missing/unexpected file (the exact inventory is data).
    for name in missing:
        rows.append(_row(name, "exact_relative_filepath", ["Required original output is missing from reproduction"]))
        source_status[name] = "failed"
    for name in unexpected:
        rows.append(_row(name, "exact_relative_filepath", ["Unexpected output absent from original inventory"]))
        source_status[name] = "failed"
    common = inventory_a & inventory_b
    for name in sorted(common, key=lambda filename: (filename.endswith(".svg"), filename)):
        left, right = original / name, reproduced / name
        suffix = left.suffix.lower()
        method, errors, notes = "exact_bytes", [], []
        try:
            if name == "output_manifest.json":
                method = "manifest_inventory_and_local_hash_integrity"
                errors.extend(manifest_failures)
                a, b = manifests["original"], manifests["reproduced"]
                if a is not None and b is not None:
                    if a.get("schema_version") != b.get("schema_version"):
                        errors.append("Manifest schema versions differ")
                    if set(a.get("files", {})) != set(b.get("files", {})):
                        errors.append("Output manifest relative filepaths differ")
                notes.append("Per-file hashes checked independently; cross-run hashes are not substituted for semantic comparisons")
            elif suffix == ".csv":
                method = "exact_csv_schema_discrete_and_tolerant_named_measurements"
                errors, notes = _compare_csv(left, right, name, settings)
            elif suffix == ".npz":
                method = "exact_decoded_npz_arrays_dtype_shape_values"
                errors, notes = _compare_npz(left, right)
            elif suffix == ".json":
                method = "json_exact_except_declared_numeric_and_metadata_fields"
                a, b = _json(left), _json(right)
                if name == "analysis_summary.json":
                    errors.extend("original: " + error for error in _summary_binding(a, original))
                    errors.extend("reproduced: " + error for error in _summary_binding(b, reproduced))
                    bound = ("analysis_id", "input_manifest_sha256", "analysis_folder", "report_path", "findings_path")
                    if not errors:
                        for key in bound:
                            if a[key] != b[key]:
                                notes.append(f"Independently validated derived metadata /{key}: {a[key]!r} -> {b[key]!r}")
                        a = {key: value for key, value in a.items() if key not in bound}
                        b = {key: value for key, value in b.items() if key not in bound}
                comparison_errors, comparison_notes = _compare_json(a, b, name, settings)
                errors.extend(comparison_errors)
                notes.extend(comparison_notes)
            elif suffix == ".svg":
                method = "svg_vector_labels_populations_source_values_and_presentation"
                errors, notes = _compare_svg(left, right, name, source_status)
            elif left.read_bytes() != right.read_bytes():
                errors.append("File bytes differ; no normalization allowance is declared for this file")
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        row = _row(name, method, errors, notes)
        rows.append(row)
        source_status[name] = row["status"]
    if "output_manifest.json" not in common:
        rows.append(_row("[manifest_validation]", "manifest_inventory_and_local_hash_integrity", manifest_failures))
    return rows
