"""Export the existing comparison and separate masked review packets offline."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import html
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
from unittest.mock import patch
import zipfile

VERSION = "final-saved-results-export-1"
FORBIDDEN_SOURCE_KEYS = {"profile_id", "planner_version", "job_id", "case_category", "family_id",
    "case_index", "private_expected_behavior", "packet_id", "packet_path", "configuration_id"}


def require(value, message):
    if not value:
        raise ValueError(message)


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def module(root, name):
    path = Path(root) / "src/champion_athletic_map" / (name + ".py")
    spec = importlib.util.spec_from_file_location("final_export_" + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@contextmanager
def offline_only():
    def blocked(*_args, **_kwargs):
        raise RuntimeError("The saved-results export does not make network requests.")
    with patch("socket.create_connection", blocked), patch("socket.socket.connect", blocked), patch("socket.socket.connect_ex", blocked):
        yield


def zip_bytes(files):
    """Make repeatable archives with relative names and no machine paths."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            path = PurePosixPath(name)
            require(isinstance(name, str) and name and not path.is_absolute()
                and not set(path.parts) & {"..", "."} and "\\" not in name and ":" not in name
                and path.as_posix() == name, "An export archive name leaves its folder.")
            require(isinstance(data, bytes), "An export archive entry must have explicit bytes.")
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data, compresslevel=9)
    return buffer.getvalue()


def source_keys_are_neutral(value):
    if isinstance(value, dict):
        require(not set(value) & FORBIDDEN_SOURCE_KEYS,
                "A neutral source record contains a case or workflow mapping.")
        for item in value.values():
            source_keys_are_neutral(item)
    elif isinstance(value, list):
        for item in value:
            source_keys_are_neutral(item)


def prepare_neutral_sources(root, data):
    """Copy full adopted records and de-identified delivered source records only."""
    reader = module(root, "final_saved_results")
    pointer_path = reader.checked(root, "artifacts/language_model/active_resource_release.json")
    pointer = reader.strict_json(pointer_path.read_bytes())
    directory = pointer["release_directory"]
    manifest_path = reader.checked(root, directory + "/manifest.json")
    require(sha(manifest_path.read_bytes()) == pointer["manifest_sha256"], "The adopted reference release changed.")
    manifest = reader.strict_json(manifest_path.read_bytes())
    files, bindings = {}, {pointer_path.relative_to(root).as_posix(): sha(pointer_path.read_bytes()),
                            manifest_path.relative_to(root).as_posix(): sha(manifest_path.read_bytes())}
    for name, output in (("adopted_drills.json", "approved_activities.json"),
                         ("adopted_rules.json", "adopted_guidance.json")):
        source = reader.checked(root, directory + "/" + name)
        raw = source.read_bytes()
        require(sha(raw) == manifest["file_hashes"][name], "An adopted source record file changed.")
        files["neutral_references/" + output] = raw
        bindings[source.relative_to(root).as_posix()] = sha(raw)
    references, foods = {}, {}
    for packet in data["reference_packets"]:
        payload = packet.get("payload") or {}
        for reference in payload.get("references") or []:
            require(isinstance(reference, dict), "A delivered reference is not a complete source object.")
            source_keys_are_neutral(reference)
            references[sha(canonical(reference))] = deepcopy(reference)
        for lookup in payload.get("food_lookup") or []:
            require(isinstance(lookup, dict), "A delivered food lookup is not a source object.")
            value = {key: deepcopy(lookup[key]) for key in ("status", "data", "source_refs", "reason") if key in lookup}
            source_keys_are_neutral(value)
            foods[sha(canonical(value))] = value
    files["neutral_references/provided_reference_units.json"] = packed([references[key] for key in sorted(references)])
    files["neutral_references/provided_food_records.json"] = packed([foods[key] for key in sorted(foods)])
    links = [("approved_activities.json", "Approved basketball activities and warm-ups"),
             ("adopted_guidance.json", "Adopted youth participation guidance"),
             ("provided_reference_units.json", "Complete reference units provided during the comparison"),
             ("provided_food_records.json", "Source-linked recorded food lookups provided during the comparison")]
    items = "".join('<li><a href="' + html.escape(name, quote=True) + '">' + html.escape(label) + '</a></li>' for name, label in links)
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        '<title>Team review references</title><style>body{font:17px/1.6 system-ui;max-width:900px;margin:36px auto;padding:0 24px}li{margin:14px 0}</style>'
        '<h1>Team review references</h1><p>We use these neutral source records to check substantive claims. '
        'Source identity alone does not establish support for a particular claim. Missing citations do not prevent checking a fact.</p>'
        '<p>The provided food records retain their source qualifications and recorded values. They are not dietary prescriptions. '
        'The complete source tables remain in the local project if a value needs further checking.</p><ul>' + items + '</ul></html>')
    files["neutral_references/index.html"] = page.encode("utf-8")
    return {"files": files, "source_file_sha256": bindings,
        "counts": {"provided_reference_units": len(references), "provided_food_lookups": len(foods)}}


def save_once(path, data):
    if path.exists():
        require(path.read_bytes() == data, "An earlier saved-results export differs and was preserved: " + path.name)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)


def export(root, *, software_evidence, expected_manifest_id, software_fixture=False,
           summary_path="results/step33_final_comparison_summary.json",
           setup_path="results/step33_final_run_setup_summary.json"):
    root = Path(root).resolve()
    require(type(software_fixture) is bool, "The saved export scope must be explicit.")
    if software_fixture:
        require(summary_path.startswith("results/testing/") and setup_path.startswith("results/testing/"),
                "Software exports must use the separate testing namespace.")
    reader = module(root, "final_saved_results")
    require(software_evidence.get("status") == "passed" and software_evidence.get("passed", 0) > 0
            and software_evidence.get("failed") == 0, "The saved-results software checks must pass.")
    for relative, digest in software_evidence["files"].items():
        require(sha(reader.checked(root, relative).read_bytes()) == digest,
                "A tested saved-results export source changed: " + relative)
    with offline_only():
        data = reader.load_saved_comparison(root, summary_path=summary_path, software_fixture=software_fixture)
        require(data["manifest"]["manifest_id"] == expected_manifest_id,
                "The saved comparison belongs to another final run.")
        runner = module(root, "final_comparison_runner")
        setup = reader.strict_json(reader.checked(root, setup_path).read_bytes())
        summary_api = module(root, "final_results_summary")
        comparison = summary_api.summarize(data["rows"],
            cumulative_model_submissions=data["cumulative_model_submissions"], manifest_id=expected_manifest_id)
        if software_fixture:
            comparison["submission_count_scope"] = "Explicit software-fixture receipts only; no native model submission observed."
        table = summary_api.render_comparison(comparison)
        review = module(root, "final_review_packets").prepare_review_packets(root, data["manifest"], setup,
            data["rows"], source_bindings=data["manifest"]["protocol"]["review_source_sha256"],
            software_fixture=software_fixture)
        neutral = prepare_neutral_sources(root, data)
    public = {**review["public_files"], **neutral["files"]}
    private = {"comparison_summary.json": packed(comparison), "comparison_table.md": table.encode("utf-8"),
        "saved_outcomes.jsonl": b"".join(canonical(row) + b"\n" for row in data["rows"]),
        "saved_ledger.jsonl": b"".join(canonical(row) + b"\n" for row in data["ledger"]),
        "verification.json": packed(data["verification"]),
        "source_file_sha256.json": packed({**data["source_file_sha256"], **neutral["source_file_sha256"]}),
        "frozen_comparison_protocol.json": packed(data["manifest"]["protocol"]),
        **{"private_review_binding/" + name: value for name, value in review["private_files"].items()}}
    private["README.md"] = ("# Saved comparison results\n\nWe verified the original 800 designated outcomes and saved assessments without generating or rescoring replies. "
        "This archive contains workflow mappings and automatic findings for results analysis. It is separate from the masked team-review packet. "
        "The primary full-verification result is limited by unimplemented goal verification. Required unknowns are not known violations. "
        "The cumulative model-submission count comes from native transport journals; the last-batch count is not substituted. "
        "Team ratings and paired statistical intervals are not supplied by this export.\n").encode("utf-8")
    identity = {"schema_version": VERSION, "manifest_id": expected_manifest_id,
        "software_fixture": software_fixture,
        "comparison_sha256": sha(packed(comparison)), "software_evidence": software_evidence,
        "source_file_sha256": {**data["source_file_sha256"], **neutral["source_file_sha256"]},
        "public_files": {name: sha(value) for name, value in public.items()},
        "private_files": {name: sha(value) for name, value in private.items()}}
    export_id = sha(packed(identity))
    relative = data["manifest"]["package_directory"] + "/saved_review_" + export_id[:20]
    folder = root / relative
    private_zip, public_zip = zip_bytes(private), zip_bytes(public)
    for name, content in {**{"analysis/" + k: v for k, v in private.items()},
                          **{"team_review/" + k: v for k, v in public.items()}}.items():
        save_once(folder / name, content)
    save_once(folder / "export_manifest.json", packed(identity))
    save_once(folder / "saved_results_review.zip", private_zip)
    save_once(folder / "team_review_packets.zip", public_zip)
    output_prefix = "results/testing/step33_10_" if software_fixture else "results/step33_"
    summary = {"schema_version": VERSION, "export_id": export_id, "manifest_id": expected_manifest_id,
        "software_fixture": software_fixture,
        "package_directory": relative, "cases_verified": 200, "outcomes_verified": 800,
        "cumulative_model_submissions": data["cumulative_model_submissions"],
        "last_batch_model_submissions": data["last_batch_model_submissions"],
        "comparison": comparison, "team_review": review["summary"],
        "review_packet_directory": relative + "/team_review",
        "private_review_archive": output_prefix + "saved_results_review.zip",
        "private_review_archive_sha256": sha(private_zip),
        "team_review_archive": output_prefix + "team_review_packets.zip",
        "team_review_archive_sha256": sha(public_zip), "model_calls": 0,
        "new_query_encodings": 0, "saved_responses_or_assessments_changed": False,
        "summary_path": output_prefix + "saved_results_comparison_summary.json"}
    save_once(folder / "summary.json", packed(summary))
    runner.replace_progress(root / summary["private_review_archive"], private_zip)
    runner.replace_progress(root / summary["team_review_archive"], public_zip)
    runner.replace_progress(root / summary["summary_path"], packed(summary))
    return {"summary": summary, "comparison_table": table}
