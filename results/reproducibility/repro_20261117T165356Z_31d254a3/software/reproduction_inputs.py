"""Verify and stage the selected Step 35 evidence, without running its software.

Only standard-library modules are imported. Saved classifier payloads are hashed
as opaque bytes; they are never deserialized. Staging copies the recorded inputs
and the review loader's untracked manifest, rather than copying a repository,
an environment, or every historical path mentioned in a provenance inventory.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from zipfile import ZipFile


SUMMARY = "results/step35_statistical_analysis_summary.json"
ARCHIVE = "results/step33_saved_results_review.zip"
REVIEW_SUMMARY = "results/step34_team_review_summary.json"
DIMENSIONS = {"response_suitability", "profile_fit", "practicality_completeness",
              "evidence_accuracy", "clarity"}
CATEGORIES = {"feasible": 150, "missing_information": 20,
              "conflicting_constraints": 15, "outside_scope": 15}
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    prefix + str(i) for prefix in ("COM", "LPT") for i in range(1, 10)}


class ReproductionInputError(ValueError):
    """The saved evidence or requested staging destination is invalid."""


class MissingReproductionInput(ReproductionInputError):
    """Required evidence is absent; rebuilding or generation is not attempted."""


def _require(condition, reason):
    if not condition:
        raise ReproductionInputError(reason)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate JSON key: " + key)
        result[key] = value
    return result


def _json(raw):
    def nonfinite(value):
        raise ReproductionInputError("Nonfinite JSON number: " + value)
    try:
        return json.loads(raw, object_pairs_hook=_unique, parse_constant=nonfinite)
    except (ValueError, UnicodeError) as exc:
        raise ReproductionInputError("Invalid saved JSON: " + str(exc)) from exc


def portable_relative(name):
    """Return one canonical POSIX path also representable safely on Windows."""
    _require(isinstance(name, str) and bool(name), "Empty or non-string evidence path.")
    _require(not any(c in name for c in '\\:<>"|?*')
             and not any(ord(c) < 32 for c in name), "Nonportable evidence path: " + name)
    p = PurePosixPath(name)
    _require(not p.is_absolute() and p.as_posix() == name
             and not set(p.parts) & {".", ".."}, "Unsafe evidence path: " + name)
    for part in p.parts:
        _require(not part.endswith((" ", "."))
                 and part.split(".", 1)[0].upper() not in _RESERVED,
                 "Windows-ambiguous evidence path: " + name)
    return p


def safe_path(root, name):
    relative = portable_relative(name)
    root = Path(root).resolve()
    path = root.joinpath(*relative.parts)
    _require(path.resolve() == path and path.is_relative_to(root),
             "Linked or escaping evidence path: " + name)
    return path


def _hashes(mapping, label):
    _require(isinstance(mapping, dict) and bool(mapping), label + " is empty or invalid.")
    folded = {}
    for name, digest in mapping.items():
        portable_relative(name)
        _require(isinstance(digest, str) and _HEX.fullmatch(digest),
                 "Invalid SHA256 in " + label + ": " + name)
        parts = PurePosixPath(name).parts
        # Check ancestor spelling too: A/file and a/other collide on Windows.
        for i in range(1, len(parts) + 1):
            prefix = "/".join(parts[:i])
            key = prefix.casefold()
            _require(key not in folded or folded[key] == prefix,
                     "Case-colliding evidence paths in " + label + ": " + name)
            folded[key] = prefix
    return mapping


class _Reader:
    def __init__(self, root):
        self.root = Path(root).resolve()
        _require(self.root.is_dir(), "Project root is not a directory: " + str(self.root))
        self.hashes = {}
        self.sizes = {}

    def raw(self, name, expected=None):
        path = safe_path(self.root, name)
        if not path.is_file():
            raise MissingReproductionInput("Missing saved reproduction input: " + name
                                           + ". No automatic rebuild is performed.")
        _require(stat.S_ISREG(path.stat().st_mode), "Evidence is not a regular file: " + name)
        raw = path.read_bytes()
        actual = sha256(raw)
        _require(expected is None or actual == expected, "Input SHA256 differs: " + name)
        _require(name not in self.hashes or self.hashes[name] == actual,
                 "An input changed while being inspected: " + name)
        self.hashes[name], self.sizes[name] = actual, len(raw)
        return raw

    def json(self, name, expected=None):
        return _json(self.raw(name, expected))


def _rows(raw):
    _require(bool(raw.strip()), "An expected saved-record collection is empty.")
    return [_json(line) for line in raw.splitlines() if line.strip()]


def _by_id(rows, field, expected, label):
    _require(isinstance(rows, list) and all(isinstance(row, dict)
             and isinstance(row.get(field), str) and row[field] for row in rows),
             "Invalid identifiers in " + label)
    result = {row[field]: row for row in rows}
    _require(len(rows) == len(result) == expected, "Incomplete or duplicate " + label)
    return result


def _check_planners(reader, identity):
    raw = reader.raw(ARCHIVE, identity["input_sha256"][ARCHIVE])
    members = _hashes(identity["source_member_sha256"], "Step 33 member inventory")
    required = {"saved_outcomes.jsonl", "saved_ledger.jsonl", "source_file_sha256.json",
                "frozen_comparison_protocol.json", "comparison_summary.json",
                "private_review_binding/private_bound_response_key.jsonl"}
    _require(required <= set(members), "The source inventory omits required Step 33 members.")
    import io
    with ZipFile(io.BytesIO(raw)) as source:
        names = source.namelist()
        _require(len(names) == len(set(names)), "Duplicate members in Step 33 export.")
        _require(set(members) <= set(names), "A required Step 33 archive member is missing.")
        contents = {name: source.read(name) for name in members}
    for name, expected in members.items():
        _require(sha256(contents[name]) == expected, "Saved Step 33 member differs: " + name)
    rows = _rows(contents["saved_outcomes.jsonl"])
    by_job = _by_id(rows, "job_id", 800, "designated planner outcomes")
    ledger = _by_id(_rows(contents["saved_ledger.jsonl"]), "job_id", 800, "planner assessments")
    _require(set(by_job) == set(ledger), "Planner outcomes and assessments have different jobs.")
    sources = _hashes(_json(contents["source_file_sha256.json"]), "Step 33 source-file inventory")
    for row in rows:
        entry = ledger[row["job_id"]]
        _require(entry.get("execution_state") == "terminal"
                 and entry.get("assessment_execution") == "completed"
                 and entry.get("metric_state") == "assessed", "An incomplete planner job is present.")
        for key in ("profile_id", "family_id", "planner_version", "case_category",
                    "public_record_sha256", "designated_outcome_sha256", "assessment_sha256"):
            _require(row[key] == entry[key], "A planner outcome/assessment binding differs: " + key)
        for key in ("strict_format_valid", "designated_workflow_completed", "automated_declared_checks_pass",
                    "complete_request_fulfillment_verified", "category_response_success"):
            _require(type(row["final_metrics"][key]) is bool, "A planner metric is missing or invalid.")
        _require(all(entry.get(k) == v for k, v in row["final_metrics"].items()
                     if k != "applicable_category"), "Planner assessment metrics disagree.")
        primary = row["final_metrics"]["automated_feasible_plan_success"]
        _require(type(primary) is bool if row["case_category"] == "feasible" else primary is None,
                 "Planner metric applicability differs.")
        text = row["raw_text"]
        _require(text is None or isinstance(text, str), "Invalid saved planner reply text.")
        _require(row["raw_text_sha256"] == (None if text is None else sha256(text.encode("utf-8"))),
                 "Saved planner reply text differs from its binding.")
        _require(row["assessment_path"] in sources
                 and sources.get(row["transport_record_path"]) == row["transport_record_sha256"],
                 "A designated planner source-file binding is missing.")
    paired = {(row["profile_id"], row["planner_version"]): row for row in rows}
    profiles = {row["profile_id"] for row in rows}
    _require(len(profiles) == 200 and len(paired) == 800
             and all((p, v) in paired for p in profiles for v in range(1, 5)),
             "The frozen four-planner population is incomplete.")
    _require(Counter(paired[p, 1]["case_category"] for p in profiles) == CATEGORIES,
             "The original planner population denominators differ.")
    for profile in profiles:
        for key in ("family_id", "case_category", "public_record_sha256"):
            _require(len({paired[profile, v][key] for v in range(1, 5)}) == 1,
                     "Paired planner profile metadata differs.")
    protocol = _json(contents["frozen_comparison_protocol.json"])
    _require(protocol["metric_definitions"]["paired"]["contrasts"] == ["V2-V1", "V3-V2", "V4-V3", "V4-V1"],
             "The frozen planner comparison directions differ.")
    return {"paired": paired, "contents": contents, "source_file_sha256": sources,
            "planner_jobs": 800, "planner_profiles": 200}


def _check_review(reader, identity, planners):
    summary = reader.json(REVIEW_SUMMARY, identity["input_sha256"][REVIEW_SUMMARY])
    _require(summary["review_id"] == identity["review_id"], "Selected review identity differs.")
    folder = portable_relative(summary["review_folder"]).as_posix()
    _require(folder == "results/team_review/review_" + identity["review_id"][:20],
             "Review summary selects a noncanonical review folder.")
    manifest_name = folder + "/review_manifest.json"
    manifest = reader.json(manifest_name)
    _require(manifest["review_id"] == identity["review_id"], "Review manifest identity differs.")
    _hashes(manifest["files"], "locked review manifest")
    for name, expected in manifest["files"].items():
        relative = folder + "/" + name
        _require(identity["input_sha256"].get(relative) == expected,
                 "Review file is not bound in the selected analysis: " + relative)
        reader.raw(relative, expected)
    _require(all(identity["source_member_sha256"].get(name) == expected
                 for name, expected in manifest["source_member_sha256"].items()),
             "The locked review refers to another saved planner export.")
    locked = reader.json(folder + "/rating_lock.json")
    raw = reader.raw(folder + "/ratings.jsonl")
    _require(locked["ratings_sha256"] == sha256(raw), "Ratings differ from their original lock.")
    ratings = _by_id(_rows(raw), "response_id", 160, "locked review replies")
    bindings = _by_id(reader.json(folder + "/private_response_binding.json"),
                      "response_id", 160, "locked response bindings")
    original = _by_id(_rows(planners["contents"]["private_review_binding/private_bound_response_key.jsonl"]),
                      "response_id", 160, "pre-output review selection")
    _require(set(ratings) == set(bindings) and bindings == original,
             "The reviewed responses differ from the locked original sample.")
    profiles = set()
    for response, review in ratings.items():
        binding = bindings[response]
        profiles.add(binding["profile_id"])
        row = planners["paired"].get((binding["profile_id"], binding["planner_version"]))
        _require(row is not None and binding["designated_outcome_sha256"] == row["designated_outcome_sha256"]
                 and binding["response_text_sha256"] == row["raw_text_sha256"]
                 and binding.get("job_id") == row["job_id"]
                 and binding.get("public_record_sha256") == row["public_record_sha256"],
                 "A locked rating is bound to another response version.")
        _require(set(review["ratings"]) == DIMENSIONS, "A locked rating dimension is missing.")
        for dimension, rating in review["ratings"].items():
            _require((rating["status"] == "rated" and type(rating["score"]) is int
                      and rating["score"] in (0, 1, 2))
                     or (dimension == "evidence_accuracy" and rating["status"] == "not_applicable"
                         and rating["score"] is None and bool(rating["rationale"])),
                     "A locked review contains an unfinished or invalid rating.")
    _require(len(profiles) == 40 and summary["independent_teammate_ratings_collected"] == 0
             and summary["reviewer_agreement"]["computed"] is False,
             "The recorded supplementary review population or method differs.")
    return manifest_name


def inspect_inputs(root, expected_software_sha256):
    """Validate the current selected Step 35 result and return a portable inventory.

    Required missing files raise MissingReproductionInput. This function does not
    select another analysis, repair evidence, import Step 35, or create any files.
    ``expected_software_sha256`` must come from the delivered, hash-verified Step 35
    module sources, not from trusting the selected input manifest itself.
    """
    reader = _Reader(root)
    pointer = reader.raw(SUMMARY)
    summary = _json(pointer)
    analysis_id = summary.get("analysis_id")
    _require(isinstance(analysis_id, str) and _HEX.fullmatch(analysis_id), "Invalid Step 35 analysis identity.")
    folder = "results/statistical_analysis/analysis_" + analysis_id[:20]
    _require(summary.get("schema_version") == "step35-statistical-analysis-1"
             and summary.get("analysis_folder") == folder, "Step 35 summary selects another analysis folder.")
    _require(reader.raw(folder + "/analysis_summary.json") == pointer,
             "Current Step 35 summary differs from its own analysis summary.")
    raw_identity = reader.raw(folder + "/analysis_input_manifest.json")
    identity = _json(raw_identity)
    _require(sha256(raw_identity) == sha256(packed(identity)) == analysis_id
             == summary.get("input_manifest_sha256"), "Step 35 identity or input manifest SHA256 differs.")
    _require(isinstance(expected_software_sha256, dict) and expected_software_sha256
             and all(isinstance(v, str) and _HEX.fullmatch(v) for v in expected_software_sha256.values())
             and identity.get("software_sha256") == expected_software_sha256,
             "Selected Step 35 software differs from the delivered sources.")
    for key, value in (("classifier", identity["classifier_status"]),
                       ("native_runtime_status", identity["native_runtime_status"])):
        _require(summary.get(key) == value, "Step 35 summary/manifest status differs: " + key)
    if "status" in summary.get("retrieval", {}):
        _require(summary["retrieval"]["status"] == identity["retrieval_status"],
                 "Step 35 retrieval status differs from its identity.")
    inputs = dict(_hashes(identity["input_sha256"], "Step 35 input inventory"))
    _require({ARCHIVE, REVIEW_SUMMARY} <= set(inputs), "Required planner/review source bindings are missing.")
    for name, expected in inputs.items():
        reader.raw(name, expected)
    output_manifest = reader.json(folder + "/output_manifest.json")
    _require(output_manifest.get("schema_version") == "step35-analysis-output-manifest-1"
             and output_manifest.get("analysis_id") == analysis_id, "Step 35 output manifest identity differs.")
    outputs = _hashes(output_manifest["files"], "Step 35 output inventory")
    _require({"analysis_summary.json", "analysis_input_manifest.json", "bootstrap_draws.npz",
              "analysis_populations.csv", "bootstrap_settings.json", "retrieval_analysis_status.json",
              "native_runtime_summary.json", "statistical_analysis_findings.md"} <= set(outputs),
             "Step 35 output manifest omits required comparison evidence.")
    baseline = {SUMMARY: reader.hashes[SUMMARY], folder + "/output_manifest.json": reader.hashes[folder + "/output_manifest.json"]}
    for name, expected in outputs.items():
        relative = folder + "/" + name
        reader.raw(relative, expected)
        baseline[relative] = expected
    _require(reader.json(folder + "/retrieval_analysis_status.json")["status"] == identity["retrieval_status"],
             "Saved retrieval analysis status differs from its identity.")
    _require(reader.json(folder + "/native_runtime_summary.json")["status"] == identity["native_runtime_status"],
             "Saved native runtime status differs from its identity.")
    planners = _check_planners(reader, identity)
    support_name = _check_review(reader, identity, planners)
    support = {support_name: reader.hashes[support_name]}
    stage = dict(inputs)
    stage.update(support)
    _hashes(stage, "complete staging inventory")
    doc = "docs/statistical_analysis_findings.md"
    if safe_path(root, doc).exists():
        _require(reader.raw(doc) == reader.raw(folder + "/statistical_analysis_findings.md"),
                 "Current statistical findings documentation differs from the selected analysis.")
        baseline[doc] = reader.hashes[doc]
    # Re-read after relationship checks: an actively changing experiment is blocked.
    protected = dict(sorted(reader.hashes.items()))
    _hashes(protected, "protected-input inventory")
    for name, expected in protected.items():
        reader.raw(name, expected)
    inventory = {"schema_version": "step36-reproduction-inputs-1", "analysis_id": analysis_id,
        "analysis_folder": folder, "summary": summary, "identity": identity,
        "input_sha256": dict(sorted(inputs.items())), "support_sha256": support,
        "stage_files": dict(sorted(stage.items())), "files": dict(sorted(stage.items())),
        "baseline_sha256": dict(sorted(baseline.items())), "protected_sha256": protected,
        "file_sizes": dict(sorted(reader.sizes.items())), "file_count": len(stage),
        "total_bytes": sum(reader.sizes[p] for p in stage), "protected_file_count": len(protected),
        "protected_bytes": sum(reader.sizes[p] for p in protected),
        "zip_member_sha256": identity["source_member_sha256"],
        "relationship_checks": {"planner_jobs": 800, "planner_profiles": 200,
            "locked_review_responses": 160, "locked_review_dimensions": 800,
            "selected_analysis_identity": "verified", "all_recorded_file_bytes": "verified"}}
    inventory["inventory_sha256"] = sha256(packed(inventory))
    return inventory


def verify_protected_inputs(root, inventory):
    """Return every preservation check; the caller decides how to report failure."""
    checks = []
    for name, expected in sorted(_hashes(inventory["protected_sha256"], "protected-input inventory").items()):
        error = None
        try:
            path = safe_path(root, name)
            actual = sha256(path.read_bytes()) if path.is_file() else None
        except (ReproductionInputError, OSError) as exc:
            actual, error = None, str(exc)
        row = {"path": name, "sha256_before": expected, "sha256_after": actual,
               "unchanged": actual == expected}
        if error is not None:
            row["error"] = error
        checks.append(row)
    return checks


def stage_inputs(root, copyroot, inventory):
    """Copy the exact recorded input bytes into a fresh independent project root.

    Copied files have read-only permission bits and different inodes. No original
    permissions are changed. Baseline analysis outputs remain outside the child
    project, so its calculations write a separate result. Filesystem permissions
    are defense in depth; source hashes must still be checked after execution.
    """
    unsigned = {k: v for k, v in inventory.items() if k != "inventory_sha256"}
    _require(inventory.get("inventory_sha256") == sha256(packed(unsigned)), "Staging inventory changed after inspection.")
    stage = _hashes(inventory["stage_files"], "staging inventory")
    _require(stage == inventory["files"], "Staging inventory aliases disagree.")
    source_root = Path(root).resolve()
    requested = Path(copyroot).absolute()
    _require(requested.resolve() == requested, "Staging root uses linked or noncanonical ancestors.")
    destination = requested.resolve()
    _require(destination != source_root and not source_root.is_relative_to(destination),
             "Staging root overlaps or contains the original project.")
    if destination.exists():
        _require(destination.is_dir() and not any(destination.iterdir()), "Staging root must be new or empty.")
    checks = verify_protected_inputs(source_root, inventory)
    _require(all(row["unchanged"] for row in checks), "Protected evidence changed before staging.")
    destination.mkdir(parents=True, exist_ok=True)
    staged = {}
    for name, expected in sorted(stage.items()):
        source = safe_path(source_root, name)
        target = safe_path(destination, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        with source.open("rb") as incoming, target.open("xb") as outgoing:
            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
                outgoing.write(block)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        _require(digest.hexdigest() == expected and size == inventory["file_sizes"][name],
                 "An input changed during staging: " + name)
        target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        _require(not os.path.samefile(source, target), "A staged input aliases its original: " + name)
        staged[name] = expected
    for name, expected in staged.items():
        _require(sha256(safe_path(destination, name).read_bytes()) == expected,
                 "Staged copy SHA256 differs: " + name)
    checks = verify_protected_inputs(source_root, inventory)
    _require(all(row["unchanged"] for row in checks), "Protected evidence changed while staging.")
    return {"schema_version": "step36-input-staging-1", "status": "staged_and_verified",
            "analysis_id": inventory["analysis_id"], "file_count": len(staged),
            "total_bytes": inventory["total_bytes"], "files": staged,
            "read_only_permission_bits": True, "independent_file_copies": True,
            "protected_inputs_unchanged": True}
