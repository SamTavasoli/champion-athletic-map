"""Save separate development findings for four original replies and the amendment."""

import hashlib
import importlib.util
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def module(root, name):
    path = root / "src/champion_athletic_map" / (name + ".py")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("saved_assessment_" + name, path))
    result.__spec__.loader.exec_module(result)
    return result


def read(path):
    return json.loads(path.read_bytes())


def save_once(path, value):
    data = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("An earlier assessment differs and was preserved: " + path.name)
        return
    with path.open("xb") as handle:
        handle.write(data)


def verify(root, bindings):
    for relative, expected in bindings.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError("A saved assessment dependency changed: " + relative)


def load_saved_cases(root):
    root = Path(root).resolve()
    probe = module(root, "pilot_probe")
    pointer = read(root / "results/pilot/probes/first_operational_probe.json")
    manifest_path = root / pointer["manifest_path"]
    manifest = read(manifest_path)
    body = {key: value for key, value in manifest.items() if key not in
        ("probe_id", "manifest_id", "case_review_config_path", "public_schema_path", "jobs")}
    if manifest["manifest_id"] != pointer["manifest_id"] or sha(canonical(body)) != manifest["manifest_id"]:
        raise ValueError("The original probe manifest identity changed.")
    verify(root, manifest["module_and_config_sha256"])
    verify(root, manifest["case_review_files"])
    folder = root / "results/pilot/probes" / manifest["probe_id"]
    inputs = {pointer["manifest_path"]: sha(manifest_path.read_bytes())}
    inputs["results/pilot/probes/first_operational_probe.json"] = sha((root / "results/pilot/probes/first_operational_probe.json").read_bytes())
    cases, packets = [], []
    for job in manifest["jobs"]:
        work = folder / "jobs" / job["job_id"]
        record = read(work / "job_record.json")
        outcome = probe.verify_job(root, manifest, job, work, record)
        for name in ("job_record.json", "outcome.json"):
            inputs[(work / name).relative_to(root).as_posix()] = sha((work / name).read_bytes())
        if job["planner_version"] != 1:
            reference = probe.saved_references(root, folder / "references" / job["job_id"], manifest)
            if reference is None:
                raise ValueError("The original reference preparation is incomplete.")
            packets.append(reference["packet"])
        cases.append({"assessment_id": "original_v" + str(job["planner_version"]),
            "planner_version": job["planner_version"], "record_kind": "original_matched_probe",
            "outcome": outcome, "source_outcome_path": (work / "outcome.json").relative_to(root).as_posix()})
    if (len(cases) != 4 or {item["planner_version"] for item in cases} != {1, 2, 3, 4}
            or len({item["assessment_id"] for item in cases}) != 4
            or len(packets) != 3 or any(canonical(value) != canonical(packets[0]) for value in packets[1:])):
        raise ValueError("The four original cases must use one identical assessment-side reference snapshot.")
    summary_path = root / "results/step31_v4_continuation_summary.json"
    summary = read(summary_path)
    amendment_path = root / "artifacts/pilot/continuations" / summary["amendment_id"] / "manifest.json"
    amendment = read(amendment_path)
    identity = {key: value for key, value in amendment.items() if key not in ("manifest_id", "amendment_id", "call_prefix")}
    if (sha(canonical(identity)) != amendment["manifest_id"] or summary["manifest_id"] != amendment["manifest_id"]
            or amendment["source_manifest_id"] != manifest["manifest_id"] or amendment["source_probe_id"] != manifest["probe_id"]):
        raise ValueError("The amended reply belongs to a different development probe.")
    work = root / "results/pilot/continuations" / summary["amendment_id"]
    complete, stored = read(work / "completed.json"), read(work / "outcome.json")
    if (complete["manifest_id"] != amendment["manifest_id"] or complete["outcome_sha256"] != sha((work / "outcome.json").read_bytes())
            or canonical(stored["result"]) != canonical(summary["result"])):
        raise ValueError("The amended saved response differs from its completed outcome.")
    for path in (summary_path, amendment_path, work / "completed.json", work / "outcome.json"):
        inputs[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    cases.append({"assessment_id": "amended_v4", "planner_version": 4,
        "record_kind": "separate_development_continuation", "outcome": stored["result"],
        "source_outcome_path": (work / "outcome.json").relative_to(root).as_posix()})
    public = manifest["public_record"]
    for case in cases:
        supplied = (case["outcome"].get("response") or {}).get("authoritative_public_input")
        if supplied is not None and canonical(supplied) != canonical(public["input"]):
            raise ValueError("A saved reply was generated from another athlete input.")
    inputs.update(manifest["case_review_files"])
    return {"cases": cases, "public_record": public, "truth_packet": packets[0],
        "public_schema": read(root / manifest["public_schema_path"]), "input_sha256": inputs,
        "source_probe_id": manifest["probe_id"], "amendment_id": summary["amendment_id"]}


def run(root, *, source_loader=None, assessor_factory=None, software_evidence=None):
    root = Path(root).resolve()
    if software_evidence is not None:
        if software_evidence.get("status") != "passed" or software_evidence.get("passed", 0) <= 0:
            raise ValueError("The independent software checks must pass before assessment.")
        verify(root, software_evidence["files"])
    source = (source_loader or load_saved_cases)(root)
    assessor = (assessor_factory or module(root, "independent_plan_assessment").IndependentAssessor)(root, source["public_schema"])
    reports = []
    for case in source["cases"]:
        report = assessor.assess(source["public_record"], case["outcome"], source["truth_packet"], assessment_id=case["assessment_id"])
        reports.append({"assessment_id": case["assessment_id"], "planner_version": case["planner_version"],
            "record_kind": case["record_kind"], "source_outcome_path": case["source_outcome_path"], "assessment": report})
    components = ["src/champion_athletic_map/" + name + ".py" for name in
        ("independent_assessment_run", "independent_plan_assessment", "independent_resources", "independent_food")]
    components += ["artifacts/evaluation/independent_assessment/reviewed_resource_contracts.json",
        "docs/independent_development_assessment_policy.md", "docs/prompts/shared_task_addendum_candidate.txt"]
    source_hashes = {name: sha((root / name).read_bytes()) for name in components}
    source_hashes.update(assessor.dependency_sha256)
    identity = {"schema_version": "saved-independent-development-assessment-1", "source_probe_id": source["source_probe_id"],
        "amendment_id": source["amendment_id"], "input_sha256": source["input_sha256"], "component_sha256": source_hashes,
        "assessment_ids": [item["assessment_id"] for item in reports], "prompt_candidate_activated": False,
        "assessment_environment": getattr(assessor, "environment", {"status": "not_recorded_by_injected_assessor"}),
        "injected_test_dependencies": source_loader is not None or assessor_factory is not None,
        "original_results_regraded_or_changed": False, "final_scores_computed": False, "protocol_frozen": False}
    digest = sha(canonical(identity))
    path = root / "results/pilot/independent_assessment" / ("assessment_" + digest[:20])
    save_once(path / "configuration.json", identity)
    save_once(path / "assessments.json", reports)
    summary = {**identity, "assessment_id": digest, "original_outcomes_assessed": sum(item["record_kind"] == "original_matched_probe" for item in reports),
        "amended_outcomes_assessed": sum(item["record_kind"] != "original_matched_probe" for item in reports),
        "assessment_execution_errors": sum(item["assessment"]["assessment_execution"] != "completed" for item in reports),
        "assessment_file": (path / "assessments.json").relative_to(root).as_posix(),
        "assessment_file_sha256": sha((path / "assessments.json").read_bytes()), "reports": reports,
        "new_model_calls": 0, "http_requests": 0, "query_encodings": 0, "accepted_study_profiles": 0,
        "final_scoring_ready": False, "representative_pilot_completed": False,
        "software_evidence": software_evidence or {"status": "not_recorded_by_this_invocation"},
        "remaining_readiness": ["Review case-specific expectations, families and feasibility evidence.",
            "Calibrate semantic/resource and food parser coverage on development cases.",
            "Complete independent scoring ledger and actual human-review preparations before protocol freeze."]}
    save_once(path / "summary.json", {key: value for key, value in summary.items() if key != "software_evidence"})
    target = root / "results/step31_independent_checks_summary.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical(summary) + b"\n")
    return summary


def print_summary(summary):
    print("Saved outcomes checked:", summary["original_outcomes_assessed"], "original +", summary["amended_outcomes_assessed"], "amended")
    amended = next(item["assessment"] for item in summary["reports"] if item["assessment_id"] == "amended_v4")
    checks = {item["check_id"]: item for item in amended["checks"]}
    session = checks["requested_session_count"]["observed"]
    food_label = {"met": "answered", "violated": "missing", "unknown": "needs review", "not_applicable": "not requested"}[checks["food_answer_completeness"]["status"]]
    resource_label = {"met": "verified", "violated": "conflict", "unknown": "unverified", "not_applicable": "not needed"}[checks["resource_requirements_evidence"]["status"]]
    print("Amended Planner 4 — sessions:", str(session["known_additional_roots"]) + " (requested " + str(session["requested_additional_sessions"]) + ")",
        "| Food answer:", food_label, "| Resource evidence:", resource_label)
    print("New model calls: 0 | Final scoring and larger pilot: pending")
    print("Saved: results/step31_independent_checks_summary.json")
