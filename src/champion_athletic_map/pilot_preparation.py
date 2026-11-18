"""Prepare a provisional development sample and record local prerequisites."""

from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import importlib.util
import io
import json
import os
import tempfile
from uuid import uuid4


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_module(root, name):
    path = root / "src/champion_athletic_map" / (name + ".py")
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location("champion_" + name, path))
    module.__spec__.loader.exec_module(module)
    return module


def csv_bytes(rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: json.dumps(value, ensure_ascii=False, allow_nan=False)
            if isinstance(value, (dict, list)) else value for key, value in row.items()})
    return output.getvalue().encode("utf-8")


def save(root, relative, data, *, immutable=False):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("A pilot preparation output leaves the project.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        if path.read_bytes() != data:
            raise ValueError("An existing pilot preparation file differs and was preserved: " + relative)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".pilot-preparation-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def prepare(root, *, selection_module=None, readiness_module=None, readiness_options=None):
    root = Path(root).resolve()
    selection = selection_module or load_module(root, "pilot_selection")
    readiness = readiness_module or load_module(root, "pilot_readiness")
    step30 = readiness.check_step30(root)
    if any(row["status"] != "passed" for row in step30 if row.get("required")):
        report = {"schema_version": "step31-preparation-1", "status": "step30_prerequisite_needs_attention",
            "checks": step30, "selected_drafts": 0, "planned_jobs": 0, "pilot_jobs_run": 0,
            "model_generation_calls": 0, "query_encoder_processes": 0, "protocol_frozen": False}
        save(root, "results/step31_pilot_preparation_summary.json", packed(report))
        return report

    pool = selection.load_pool(root)
    chosen = selection.select_pilot(pool["public_records"], pool["metadata"], seed=42)
    jobs = selection.assign_jobs(chosen, seed=42)
    if len(chosen["public_records"]) != 20 or len(jobs) != 80:
        raise ValueError("The pilot subset must contain 20 drafts and 80 planned jobs.")
    for record in chosen["public_records"]:
        if set(record) != {"profile_id", "schema_version", "input"}:
            raise ValueError("Private case information cannot enter a public pilot record.")
    helper_hashes = {}
    for name in ("pilot_selection", "pilot_readiness", "pilot_preparation"):
        path = root / "src/champion_athletic_map" / (name + ".py")
        helper_hashes[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    configuration = {"schema_version": "pilot-preparation-config-1", "seed": 42,
        "selection_policy": chosen["selection"], "source_provenance": pool["provenance"],
        "module_sha256": helper_hashes, "sample_size": 20, "planned_jobs": 80,
        "case_status": "provisional_development_drafts", "accepted_study_profiles": 0,
        "adopted_families": 0, "human_reviews_claimed": 0, "model_generation_calls": 0,
        "query_encoder_processes": 0, "protocol_frozen": False}
    identity = sha(packed({"configuration": configuration, "public_records": chosen["public_records"], "jobs": jobs}))
    folder = "artifacts/pilot/preparation_" + identity[:16]
    outputs = {
        folder + "/preparation_config.json": packed(configuration),
        folder + "/public_profiles.jsonl": b"".join(packed(row).replace(b"\n", b" ").rstrip() + b"\n" for row in chosen["public_records"]),
        folder + "/provisional_selection.csv": csv_bytes(chosen["manifest"]),
        folder + "/case_review_queue.csv": csv_bytes(chosen["review_rows"]),
        folder + "/planned_pilot_jobs.csv": csv_bytes(jobs),
    }
    # Public records and private selection/review metadata stay in separate files.
    for relative, data in outputs.items():
        save(root, relative, data, immutable=True)

    run_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:12]
    check_folder = root / "results/pilot/preparation_checks" / run_name
    local = readiness.check_local_readiness(root, check_folder, **(readiness_options or {}))
    checks = list({row["check_id"]: row for row in step30 + local["checks"]}.values())
    checks.extend([
        {"check_id": "pilot_case_review", "status": "pending", "required": True,
         "reason": "Proposed categories, family relationships and feasibility records still need case review.",
         "evidence": folder + "/case_review_queue.csv"},
        {"check_id": "complete_planning_checks", "status": "pending", "required": True,
         "reason": "Complete classified schedule coverage and independent activity/resource evidence remain unresolved.",
         "evidence": "results/step30_testing_summary.json"},
        {"check_id": "independent_scoring", "status": "pending", "required": True,
         "reason": "Accepted case populations, case masks and independent semantic scoring are not established.",
         "evidence": "artifacts/evaluation/scoring_config.json"},
    ])
    save(root, check_folder.relative_to(root).as_posix() + "/prerequisite_checks.csv", csv_bytes(checks))
    food_profiles = sum(bool(str(record["input"].get("food_question") or "").strip()) for record in chosen["public_records"])
    summary = {"schema_version": "step31-preparation-1", "status": "pilot_inputs_prepared_review_pending",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "preparation_id": "pilot-preparation:" + identity,
        "selected_drafts": 20, "planned_jobs": 80, "pilot_jobs_run": 0,
        "food_request_profiles": food_profiles, "source_pool_size": len(pool["public_records"]),
        "source_provenance": pool["provenance"], "selection_policy": chosen["selection"],
        "categories_are_provisional": True, "families_are_proposed": True,
        "accepted_study_profiles": 0, "adopted_families": 0, "human_reviews_claimed": 0,
        "case_review": "pending", "complete_schedule_and_resource_checks": "pending",
        "independent_scoring_ready": False, "representative_pilot_completed": False,
        "operational_generation_ready": False, "protocol_frozen": False,
        "model_generation_calls": local["model_generation_calls"],
        "query_encoder_processes": local["query_encoder_processes"],
        "metadata_requests": local["metadata_requests"], "local_model_status": local["local_model_status"],
        "reference_files_status": local["reference_files_status"], "checks": checks,
        "pending_prerequisites": [row["check_id"] for row in checks if row["status"] != "passed"],
        "preparation_files": {name: sha(data) for name, data in outputs.items()},
        "metadata_evidence_directory": local["metadata_evidence_dir"],
        "logical_generation_budget": {"minimum_completed_workflows": 180 + 2 * food_profiles,
            "maximum_configured_completed_workflows": 260 + 2 * food_profiles,
            "excludes_warmup_and_transport_attempts": True},
        "future_work": ["Review case categories, families and feasibility records.",
            "Complete the remaining schedule/resource checking and independent scoring prerequisites.",
            "Run the selected local workflows and record real context, calls, timing and failures.",
            "Freeze the final protocol only after its required conditions are satisfied."]}
    save(root, "results/step31_pilot_preparation_summary.json", packed(summary))
    return summary


def print_summary(summary):
    print("Selected development drafts:", summary["selected_drafts"], "| Planned jobs:", summary["planned_jobs"])
    model_status = {"matched_metadata": "metadata matched", "blocked": "needs attention"}.get(
        summary.get("local_model_status"), summary.get("local_model_status", "not checked"))
    reference_status = {"blocked": "needs attention"}.get(
        summary.get("reference_files_status"), summary.get("reference_files_status", "not checked"))
    print("Local model:", model_status,
        "| Reference files:", reference_status)
    print("Case review and complete planning checks: pending | Pilot jobs run: 0")
    print("Saved: results/step31_pilot_preparation_summary.json")
