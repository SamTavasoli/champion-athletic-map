"""Run one prospective development probe under common, recorded task guidance."""

import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path


VERSION = "shared-task-development-probe-1"
PROFILE_ID = "athlete:98b22068f2e17e075063759c"
POINTER = "results/pilot/shared_guidance/development_probe.json"
SUMMARY = "results/step31_shared_guidance_summary.json"
GENERATION_SUMMARY = "results/pilot/shared_guidance/generation_summary.json"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def module(root, name):
    path = root / "src/champion_athletic_map" / (name + ".py")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("shared_guidance_" + name, path))
    result.__spec__.loader.exec_module(result)
    return result


def verify(root, bindings):
    for relative, expected in bindings.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError("A saved development-probe dependency changed: " + relative)


def prepare(root, *, environment_record=None):
    root = Path(root).resolve()
    prior_path = root / "results/step31_independent_checks_summary.json"
    prior = read(prior_path)
    if (prior.get("original_outcomes_assessed") != 4 or prior.get("amended_outcomes_assessed") != 1
            or prior.get("assessment_execution_errors") != 0 or prior.get("injected_test_dependencies") is not False
            or prior.get("software_evidence", {}).get("status") != "passed"):
        raise ValueError("Step 31-5 must contain its completed independent development checks.")
    verify(root, {**prior["input_sha256"], **prior["component_sha256"],
        prior["assessment_file"]: prior["assessment_file_sha256"], **prior["software_evidence"]["files"]})
    # This loader verifies the original and amended outcomes; none becomes a new input.
    module(root, "independent_assessment_run").load_saved_cases(root)
    probe = module(root, "pilot_probe")
    source_pointer = read(root / "results/pilot/probes/first_operational_probe.json")
    source_manifest = read(root / source_pointer["manifest_path"])
    files = source_manifest["case_review_files"]
    verify(root, files)
    profiles_path = next(name for name in files if name.endswith("/public_profiles.jsonl"))
    profiles = [json.loads(line) for line in (root / profiles_path).read_bytes().splitlines() if line.strip()]
    selected = [item for item in profiles if item["profile_id"] == PROFILE_ID]
    if len(selected) != 1 or selected[0]["profile_id"] == source_manifest["public_record"]["profile_id"]:
        raise ValueError("The prospectively selected fresh development case is unavailable.")
    public = selected[0]
    facts = public["input"]
    target, _ = module(root, "independent_plan_assessment").requested_count(facts)
    if (facts.get("age") != 15 or target != 2 or len(facts.get("availability") or []) != 3
            or (facts.get("time_limits") or {}).get("max_additional_sessions_per_week") != 3
            or not facts.get("food_question")):
        raise ValueError("The selected public case no longer has the recorded diagnostic features.")
    config_path = source_manifest["case_review_config_path"]
    review = read(root / config_path)
    verify(root, review["parent_preparation_files"])
    jobs_path = next(name for name in review["parent_preparation_files"] if name.endswith("/planned_pilot_jobs.csv"))
    jobs = [item for item in csv.DictReader(io.StringIO((root / jobs_path).read_text(encoding="utf-8")))
        if item["profile_id"] == PROFILE_ID]
    jobs.sort(key=lambda item: int(item["position_in_case"]))
    if len(jobs) != 4 or {int(item["planner_version"]) for item in jobs} != {1, 2, 3, 4}:
        raise ValueError("The selected case needs its original four balanced workflow positions.")
    bindings = dict(source_manifest["module_and_config_sha256"])
    for path in sorted((root / "src/champion_athletic_map").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        digest = sha(path.read_bytes())
        if relative in bindings and bindings[relative] != digest:
            raise ValueError("An original workflow source changed: " + relative)
        bindings[relative] = digest
    for relative in ("docs/prompts/shared_task_addendum_candidate.txt", "docs/shared_guidance_development_probe.md"):
        bindings[relative] = sha((root / relative).read_bytes())
    parent_bindings = {prior_path.relative_to(root).as_posix(): sha(prior_path.read_bytes()),
        source_pointer["manifest_path"]: sha((root / source_pointer["manifest_path"]).read_bytes())}
    identity = {"schema_version": VERSION, "mode": "new_prospective_unscored_development_probe",
        "parent_probe_id": source_manifest["probe_id"], "parent_assessment_id": prior["assessment_id"],
        "parent_files": parent_bindings, "case_review_id": source_manifest["case_review_id"],
        "case_review_files": files, "public_record": public, "public_record_sha256": sha(canonical(public)),
        "selection_policy": "fixed_new_age15_shooting_case_with_two_requested_three_available_and_food_question",
        "prepared_jobs": jobs, "module_and_config_sha256": bindings,
        "model_configuration": source_manifest["model_configuration"],
        "environment": environment_record if environment_record is not None else probe.environment(),
        "limits": source_manifest["limits"], "timing_policy": source_manifest["timing_policy"],
        "active_guidance_scope": "this_new_development_probe_only_all_four_workflows",
        "original_results_replaced": False, "output_repairs": 0, "automatic_retries": 0,
        "accepted_study_profiles": 0, "protocol_frozen": False}
    digest = sha(canonical(identity))
    probe_id = "guidance_" + digest[:20]
    manifest = {**identity, "probe_id": probe_id, "manifest_id": digest,
        "case_review_config_path": config_path, "public_schema_path": source_manifest["public_schema_path"],
        "jobs": [{"job_id": "p31g_" + digest[:16] + "_v" + item["planner_version"],
            "call_id": "p31g_" + digest[:16] + "_v" + item["planner_version"],
            "planner_version": int(item["planner_version"]), "position_in_case": int(item["position_in_case"]),
            "parent_prepared_job_id": item["job_id"]} for item in jobs]}
    pointer = root / POINTER
    if pointer.exists() and read(pointer).get("manifest_id") != digest:
        raise ValueError("The prospective probe already has another configuration; its results were preserved.")
    path = root / "artifacts/pilot/shared_guidance" / probe_id / "probe_manifest.json"
    probe.save(path, manifest, immutable=True)
    probe.save(pointer, {"manifest_id": digest, "manifest_path": path.relative_to(root).as_posix()}, immutable=True)
    return manifest


def execute(root, manifest, *, software_evidence, runtime_factory=None, references_factory=None,
            trace_module=None, assessor_factory=None, emit=print):
    root = Path(root).resolve()
    if (software_evidence.get("status") != "passed" or software_evidence.get("passed", 0) <= 0
            or not software_evidence.get("files")):
        raise ValueError("The prospective probe needs completed software checks.")
    verify(root, software_evidence["files"])
    identity = {key: value for key, value in manifest.items() if key not in
        ("probe_id", "manifest_id", "case_review_config_path", "public_schema_path", "jobs")}
    expected_path = "artifacts/pilot/shared_guidance/" + manifest["probe_id"] + "/probe_manifest.json"
    pointer = read(root / POINTER)
    if (sha(canonical(identity)) != manifest["manifest_id"]
            or sha(canonical(manifest["public_record"])) != manifest["public_record_sha256"]
            or pointer != {"manifest_id": manifest["manifest_id"], "manifest_path": expected_path}
            or canonical(read(root / expected_path)) != canonical(manifest)):
        raise ValueError("The prospective probe differs from its recorded manifest.")
    verify(root, manifest["parent_files"])
    probe = module(root, "pilot_probe")
    save = probe.save
    # Reuse the tested runner in a private module instance, directing its one summary
    # write to this experiment. Its old summary and every old job stay unchanged.
    original_summary = root / "results/step31_first_probe_summary.json"
    def new_summary(path, value, **kwargs):
        target = root / GENERATION_SUMMARY if Path(path).resolve() == original_summary else path
        return save(target, value, **kwargs)
    probe.save = new_summary
    factory = runtime_factory or module(root, "shared_guidance_runtime").build_runtime
    generated = probe.execute_probe(root, manifest, runtime_factory=factory, references_factory=references_factory,
        trace_module=trace_module, software_evidence=software_evidence, emit=lambda message: None)
    folder = root / "results/pilot/probes" / manifest["probe_id"]
    packets, outcomes = [], []
    for job in manifest["jobs"]:
        work = folder / "jobs" / job["job_id"]
        if not (work / "job_record.json").is_file():
            continue
        record = read(work / "job_record.json")
        outcome = probe.verify_job(root, manifest, job, work, record)
        outcomes.append((job, outcome, record))
        if job["planner_version"] != 1:
            prepared = probe.saved_references(root, folder / "references" / job["job_id"], manifest)
            if prepared is not None:
                packets.append(prepared["packet"])
    complete = (len(outcomes) == 4 and len(packets) == 3
        and all(canonical(item) == canonical(packets[0]) for item in packets[1:]))
    reports = []
    if complete:
        assessor = (assessor_factory or module(root, "independent_plan_assessment").IndependentAssessor)(
            root, read(root / manifest["public_schema_path"]))
        for job, outcome, record in outcomes:
            assessment = assessor.assess(manifest["public_record"], outcome, packets[0],
                assessment_id=job["job_id"])
            reports.append({"planner_version": job["planner_version"], "job_id": job["job_id"],
                "outcome": record["outcome"], "assessment": assessment,
                "outcome_path": (folder / "jobs" / job["job_id"] / "outcome.json").relative_to(root).as_posix()})
        save(folder / "independent_assessments.json", reports, immutable=True)
    summary = {"schema_version": VERSION, "probe_id": manifest["probe_id"], "manifest_id": manifest["manifest_id"],
        "profile_id": manifest["public_record"]["profile_id"], "recorded_jobs": generated["recorded_probe_jobs"],
        "new_model_submissions": generated["new_generation_transport_attempts"],
        "saved_jobs_reused": generated["whole_jobs_reused_this_execution"],
        "generation_summary_path": GENERATION_SUMMARY, "generation_summary_sha256": sha((root / GENERATION_SUMMARY).read_bytes()),
        "independent_assessment_completed": complete and len(reports) == 4
            and all(item["assessment"]["assessment_execution"] == "completed" for item in reports),
        "reports": reports, "stop_reason": generated["stop_reason"],
        "new_reference_encoder_processes": generated["new_reference_encoder_processes"],
        "old_results_changed": False, "representative_pilot_completed": False, "final_scores_computed": False,
        "protocol_frozen": False, "app_generation_enabled": False, "accepted_study_profiles": 0,
        "injected_test_dependencies": any(item is not None for item in
            (runtime_factory, references_factory, trace_module, assessor_factory)),
        "software_evidence": software_evidence}
    save(root / SUMMARY, summary)
    print_summary(summary, emit=emit)
    return summary


def print_summary(summary, *, emit=print):
    for item in sorted(summary["reports"], key=lambda value: value["planner_version"]):
        by_id = {check["check_id"]: check for check in item["assessment"]["checks"]}
        def label(identifier):
            result = by_id.get(identifier) or {}
            return {"met": "met", "violated": "needs review", "unknown": "unverified",
                "not_applicable": "not needed"}.get(result.get("status"), "not completed")
        completeness = (by_id.get("food_answer_completeness") or {}).get("status")
        food = ("missing" if completeness == "violated" else "not requested" if completeness == "not_applicable"
            else {"met": "checked", "violated": "incorrect", "unknown": "unverified"}.get(
                (by_id.get("food_numeric_correctness") or {}).get("status"), "not completed"))
        emit("Planner " + str(item["planner_version"]) + " — " + str(item["outcome"].get("response_type") or "unavailable")
            + " | Format: " + ("valid" if item["outcome"]["format_valid"] else "needs review")
            + " | Sessions: " + label("requested_session_count") + " | Food: " + food
            + " | Resources: " + label("resource_requirements_evidence"))
    if not summary["independent_assessment_completed"]:
        emit("Independent checks: not completed" + (" — " + summary["stop_reason"] if summary["stop_reason"] else ""))
    emit("New model submissions: " + str(summary["new_model_submissions"]) + " | Saved jobs reused: " + str(summary["saved_jobs_reused"]))
    emit("Full pilot and final scoring: pending")
    emit("Saved: " + SUMMARY)
