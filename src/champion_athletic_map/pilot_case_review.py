"""Save a versioned development case review without running any planner."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path


REVIEW_VERSION = "pilot-case-review-1"


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_module(root, name):
    path = root / "src/champion_athletic_map" / (name + ".py")
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location("champion_" + name, path))
    module.__spec__.loader.exec_module(module)
    return module


def read_bound(root, relative, expected):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or sha(path.read_bytes()) != expected:
        raise ValueError("A saved pilot input differs and was preserved: " + relative)
    return path.read_bytes()


def prepare(root, *, software_evidence=None):
    root = Path(root).resolve()
    if software_evidence is not None:
        if software_evidence.get("status") != "passed" or software_evidence.get("passed", 0) <= 0 or not software_evidence.get("files"):
            raise ValueError("The software evidence needs a completed positive test count and its saved reports.")
        for relative, expected in software_evidence["files"].items():
            read_bound(root, relative, expected)
    selection = load_module(root, "pilot_selection")
    previous = load_module(root, "pilot_preparation")
    schedule = load_module(root, "pilot_schedule")
    summary_path = root / "results/step31_pilot_preparation_summary.json"
    previous_bytes = summary_path.read_bytes()
    previous_summary = json.loads(previous_bytes)
    if (previous_summary.get("selected_drafts") != 20 or previous_summary.get("planned_jobs") != 80
            or previous_summary.get("local_model_status") != "matched_metadata"
            or previous_summary.get("reference_files_status") != "verified"
            or previous_summary.get("pilot_jobs_run") != 0
            or previous_summary.get("protocol_frozen") is not False):
        raise ValueError("Step 31-1 must contain the successful, unexecuted preparation record.")
    bindings = previous_summary["preparation_files"]
    for relative, expected in bindings.items():
        read_bound(root, relative, expected)
    public_path = next(name for name in bindings if name.endswith("/public_profiles.jsonl"))
    config_path = next(name for name in bindings if name.endswith("/preparation_config.json"))
    config = json.loads(read_bound(root, config_path, bindings[config_path]))
    for relative, expected in config["module_sha256"].items():
        read_bound(root, relative, expected)
    originals = [json.loads(line) for line in read_bound(root, public_path, bindings[public_path]).splitlines() if line.strip()]
    pool = selection.load_pool(root)
    chosen = selection.select_pilot(pool["public_records"], pool["metadata"], seed=42)
    if originals != chosen["public_records"] or config["source_provenance"] != pool["provenance"]:
        raise ValueError("The selected public drafts no longer match their recorded development source.")
    jobs = selection.assign_jobs(chosen, seed=42)
    identity_input = {"configuration": config, "public_records": originals, "jobs": jobs}
    if previous_summary["preparation_id"] != "pilot-preparation:" + sha(previous.packed(identity_input)):
        raise ValueError("The preparation identity does not match its selected inputs and planned jobs.")
    jobs_path = next(name for name in bindings if name.endswith("/planned_pilot_jobs.csv"))
    if read_bound(root, jobs_path, bindings[jobs_path]) != previous.csv_bytes(jobs):
        raise ValueError("The original planned job order changed.")

    source = root / "artifacts/pilot/case_review_source_v1.json"
    review = json.loads(source.read_bytes())
    rows = review["rows"]
    indexed = {row["profile_id"]: row for row in rows}
    if len(rows) != 20 or len(indexed) != 20 or set(indexed) != {row["profile_id"] for row in originals}:
        raise ValueError("Every selected draft needs its own separate case-review record.")
    authoring = review["public_authoring_decisions"]
    if set(authoring) != set(indexed) or any(type(row.get("existing_commitments_complete")) is not bool for row in authoring.values()):
        raise ValueError("Every fictional public amendment needs an explicit authoring decision.")
    for record in originals:
        row = indexed[record["profile_id"]]
        if row["source_public_canonical_sha256"] != sha(selection._canonical(record)):
            raise ValueError("A case review does not match its original public draft.")

    pointer = json.loads((root / "artifacts/language_model/active_resource_release.json").read_bytes())
    release = json.loads(read_bound(root, pointer["release_directory"] + "/manifest.json", pointer["manifest_sha256"]))
    for filename in ("adopted_drills.json", "adopted_rules.json"):
        read_bound(root, pointer["release_directory"] + "/" + filename, release["file_hashes"][filename])
    if any(review[key] != release["file_hashes"][filename] for key, filename in
            (("adopted_drills_sha256", "adopted_drills.json"), ("adopted_rules_sha256", "adopted_rules.json"))):
        raise ValueError("The case review belongs to a different resource release.")
    drills = json.loads((root / pointer["release_directory"] / "adopted_drills.json").read_bytes())
    drills = {row["catalog_candidate_id"]: row for row in drills["records"]}
    metadata = {row["profile_id"]: row for row in pool["metadata"]}
    for record in originals:
        row = indexed[record["profile_id"]]
        if row["intent"] != metadata[record["profile_id"]]["scenario_intent"] or row["age"] != record["input"]["age"]:
            raise ValueError("A private review label differs from its source metadata.")
        for choice in row["witness"]["source_choices"]:
            source_record = drills.get(choice["catalog_candidate_id"])
            if source_record is None or sha(selection._canonical(source_record)) != choice["record_canonical_sha256"]:
                raise ValueError("A private witness uses a changed or unavailable adopted source record.")

    # These are new facts authored for fictional cases, recorded separately from the originals.
    amended, amendments = [], []
    base_schema = json.loads((root / selection.SCHEMA_PATH).read_bytes())
    schema = schedule.build_input_schema(base_schema)
    from jsonschema import Draft202012Validator, FormatChecker
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for original in originals:
        record = deepcopy(original)
        record["schema_version"] = "athlete-profile-input-2"
        window = record["input"]["planning_window"]
        complete = authoring[record["profile_id"]]["existing_commitments_complete"]
        if complete and record["input"].get("existing_commitments") is None:
            raise ValueError("An unknown existing schedule cannot be declared complete.")
        record["input"]["schedule_coverage"] = {**window, "existing_commitments_complete": complete}
        validator.validate(record)
        changed = deepcopy(record)
        del changed["input"]["schedule_coverage"]
        changed["schema_version"] = original["schema_version"]
        if changed != original:
            raise ValueError("Only the declared schedule-coverage amendment is permitted.")
        amended.append(record)
        amendments.append({"profile_id": record["profile_id"],
            "source_public_record_sha256": sha(selection._canonical(original)),
            "amended_public_record_sha256": sha(selection._canonical(record)),
            "change": "Added explicit fictional weekly schedule coverage; preserved all earlier fields.",
            "author_type": "assistant_under_Sam_delegated_authority",
            "existing_commitments_complete": complete,
            "basis": "New synthetic authoring decision, not an inference from an empty or nonempty list.",
            "meaning": "All existing training and sport activity for this window, including informal sessions, is listed."
                if complete else "Existing weekly commitments remain unknown; no completeness attestation is made."})

    component_paths = ["src/champion_athletic_map/" + name + ".py" for name in
        ("pilot_case_review", "pilot_schedule", "planning_checks", "rule_checks")]
    component_hashes = {name: sha((root / name).read_bytes()) for name in component_paths}
    decision = {"schema_version": REVIEW_VERSION, "parent_preparation_id": previous_summary["preparation_id"],
        "parent_preparation_files": bindings, "source_review_sha256": sha(source.read_bytes()),
        "component_sha256": component_hashes, "resource_release_id": release["release_id"],
        "resource_file_sha256": {name: release["file_hashes"][name] for name in ("adopted_drills.json", "adopted_rules.json")},
        "public_schema_sha256": sha(packed(schema)), "review_type": "assistant_under_Sam_delegated_authority",
        "human_reviews_claimed": 0, "accepted_study_profiles": 0, "adopted_families": 0,
        "original_inputs_preserved": True, "case_review": "development_diagnostic_only",
        "full_resource_verification_ready": False, "independent_scoring_ready": False,
        "common_task_addendum": schedule.COMMON_TASK_ADDENDUM,
        "pilot_jobs_run": 0, "protocol_frozen": False}
    identity = sha(packed({"decision": decision, "amendments": amendments, "public_records": amended}))
    folder = "artifacts/pilot/case_review_" + identity[:16]
    outputs = {
        folder + "/case_review_config.json": packed(decision),
        folder + "/public_profile_schema.json": packed(schema),
        folder + "/public_profiles.jsonl": b"".join(selection._canonical(row) + b"\n" for row in amended),
        folder + "/private_case_review.json": packed(review),
        folder + "/public_amendments.json": packed(amendments),
        folder + "/common_task_addendum.txt": (schedule.COMMON_TASK_ADDENDUM + "\n").encode("utf-8"),
    }
    for relative, data in outputs.items():
        previous.save(root, relative, data, immutable=True)
    unresolved = [row["profile_id"] for row in rows
        if row["intent"] == "feasible" and row["witness"].get("full_week_feasibility_certified") is not True]
    result = {"schema_version": REVIEW_VERSION, "status": "development_cases_reviewed_with_retained_limitations",
        "case_review_id": "pilot-case-review:" + identity, "source_preparation_id": previous_summary["preparation_id"],
        "reviewed_cases": 20, "public_profiles_versioned": 20,
        "complete_schedule_fictional_cases": sum(row["existing_commitments_complete"] for row in amendments),
        "unknown_existing_schedule_cases": sum(not row["existing_commitments_complete"] for row in amendments),
        "unresolved_feasibility_witness_ids": unresolved,
        "case_review_type": decision["review_type"], "human_reviews_claimed": 0,
        "accepted_study_profiles": 0, "adopted_families": 0,
        "schedule_check_software_version": schedule.CHECKER_VERSION,
        "software_evidence": software_evidence or {"status": "not_recorded_by_this_invocation"},
        "original_inputs_preserved": True, "earlier_results_regraded": False,
        "complete_resource_checks": "pending", "independent_scoring_ready": False,
        "pilot_jobs_run": 0, "model_generation_calls": 0, "http_requests": 0,
        "query_encoder_processes": 0, "protocol_frozen": False,
        "review_files": {name: sha(data) for name, data in outputs.items()},
        "source_preparation_summary_sha256": sha(previous_bytes),
        "next_action": "Run a separately recorded bounded operational probe; resolve retained semantic/resource and human-review requirements before freezing."}
    previous.save(root, "results/step31_case_review_summary.json", packed(result))
    return result


def print_summary(summary):
    print("Cases reviewed:", summary["reviewed_cases"], "| Versioned fictional profiles:", summary["public_profiles_versioned"])
    checked = "passed" if summary["software_evidence"]["status"] == "passed" else "not recorded"
    print("Weekly schedule software checks:", checked, "| New model calls: 0")
    print("Complete feasibility checks and independent scoring: pending | Pilot jobs run: 0")
    print("Saved: results/step31_case_review_summary.json")
