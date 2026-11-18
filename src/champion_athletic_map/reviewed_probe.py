"""Run the fixed four-case reviewed-workflow probe with saved-job continuation."""

from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


VERSION = "reviewed-four-case-live-probe-1"
SUMMARY = "results/step31_reviewed_probe_summary.json"
PARENT = "results/step31_reviewed_workflow_preparation_summary.json"
CASE_INDICES = (13, 3, 4, 12)
_MODE_NAMES = {"production": "probe.json", "injected_test": "injected_test_probe.json"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def module(root, name):
    path = root / "src/champion_athletic_map" / (name + ".py")
    value = importlib.util.module_from_spec(importlib.util.spec_from_file_location("reviewed_probe_" + name, path))
    value.__spec__.loader.exec_module(value)
    return value


def verify(root, bindings):
    for relative, expected in bindings.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError("A frozen reviewed-probe dependency changed: " + relative)


def save_once(path, value):
    data = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("An earlier reviewed-probe file differs and was preserved: " + path.name)
    else:
        with path.open("xb") as handle:
            handle.write(data)


def pointer_path(mode):
    if mode not in _MODE_NAMES:
        raise ValueError("The probe execution mode must be production or injected_test.")
    return "results/pilot/reviewed_probe/" + _MODE_NAMES[mode]


def manifest_path(manifest):
    return "artifacts/pilot/reviewed_probe/" + manifest["probe_id"] + "/manifest.json"


def _parent(root, mode):
    parent = read(root / PARENT)
    evidence = parent.get("software_evidence") or {}
    if (parent.get("schema_version") != "reviewed-workflow-offline-preparation-1"
            or parent.get("status") != "reviewed_inputs_prepared_offline"
            or parent.get("candidate_only") is not True or parent.get("cases_prepared") != 20
            or parent.get("all_packet_budgets_fit_locally") is not True
            or parent.get("original_packet_counts_reproduced") != 20
            or parent.get("new_model_calls") != 0 or parent.get("query_encoder_processes") != 0
            or evidence.get("status") != "passed" or evidence.get("passed", 0) < 131
            or not evidence.get("files")
            or mode == "production" and parent.get("injected_test_dependencies") is not False):
        raise ValueError("The completed production Step 31-13 preparation and its software evidence are required.")
    bindings = {PARENT: sha((root / PARENT).read_bytes()), **parent["input_sha256"],
        **parent["component_sha256"], **evidence["files"]}
    candidate_name = parent["manifest_path"]
    candidate = read(root / candidate_name)
    if (candidate.get("manifest_id") != parent["manifest_id"] or candidate.get("workflow_id") != parent["workflow_id"]
            or candidate.get("candidate_only") is not True
            or candidate.get("future_case_indices") != list(CASE_INDICES)
            or candidate.get("injected_test_dependencies") is not parent.get("injected_test_dependencies")):
        raise ValueError("The reviewed workflow differs from its saved candidate manifest.")
    bindings[candidate_name] = sha((root / candidate_name).read_bytes())
    verify(root, bindings)
    v1 = read(root / "artifacts/planners/version1_config.json")
    dataset = v1["dataset"]
    if set(dataset["file_sha256"]) != {"champions_unified_dataset.csv", "dataset_manifest.json", "load_unified_dataset.py", "READ_ME_FIRST.txt"}:
        raise ValueError("The reviewed probe needs the unchanged four-file unified release.")
    for name, expected in dataset["file_sha256"].items():
        relative = dataset["relative_directory"] + "/" + name
        if bindings.get(relative) != expected:
            raise ValueError("The production preparation did not bind the unified dataset: " + name)
    return parent, candidate, bindings


def child_manifest(root, manifest, case):
    source = next(row for row in manifest["case_roster"] if row["case_index"] == case["case_index"])
    identity = {"schema_version": VERSION, "mode": "reviewed_development_probe_case",
        "overall_manifest_id": manifest["manifest_id"], "case_index": case["case_index"],
        "parent_files": {manifest_path(manifest): sha((root / manifest_path(manifest)).read_bytes())},
        "execution_mode": manifest["execution_mode"], "case_review_id": source["case_review_id"],
        "case_review_files": source["case_review_files"], "public_record": source["public_record"],
        "public_record_sha256": sha(canonical(source["public_record"])), "prepared_jobs": source["prepared_jobs"],
        "module_and_config_sha256": manifest["module_and_config_sha256"],
        "model_configuration": manifest["model_configuration"], "environment": manifest["environment"],
        "limits": manifest["per_case_limits"], "timing_policy": manifest["timing_policy"],
        "original_results_replaced": False, "output_repairs": 0, "automatic_retries": 0,
        "accepted_study_profiles": 0, "protocol_frozen": False}
    jobs = []
    for old in source["original_jobs"]:
        name = case["call_prefix"] + str(old["planner_version"])
        jobs.append({"job_id": name, "call_id": name, "planner_version": old["planner_version"],
            "position_in_case": old["position_in_case"], "parent_prepared_job_id": old["job_id"]})
    return {**identity, "manifest_id": sha(canonical(identity)), "probe_id": case["probe_id"],
        "case_review_config_path": source["case_review_config_path"], "public_schema_path": source["public_schema_path"], "jobs": jobs}


def prepare(root, *, environment_record=None, execution_mode="production"):
    """Freeze the selected public cases, order and source files before any call."""
    root = Path(root).resolve()
    pointer = pointer_path(execution_mode)
    parent, candidate, bindings = _parent(root, execution_mode)
    old_name = "results/step31_development_pilot_summary.json"
    old = read(root / old_name)
    if (old.get("development_pilot_completed") is not True or old.get("recorded_jobs") != 80
            or old.get("injected_test_dependencies") is not False
            or len(old.get("cases") or []) != 20):
        raise ValueError("The complete original development pilot is required for the fixed case roster.")
    bindings[old_name] = sha((root / old_name).read_bytes())
    roster, originals = [], []
    for index in CASE_INDICES:
        selected = [row for row in old["cases"] if row["case_index"] == index]
        if len(selected) != 1 or len(selected[0]["reports"]) != 4:
            raise ValueError("A selected original case is missing or duplicated.")
        first = selected[0]["reports"][0]
        parts = Path(first["outcome_path"]).parts
        if len(parts) < 7 or parts[:3] != ("results", "pilot", "probes"):
            raise ValueError("The selected original outcome leaves its pilot tree.")
        source_name = "artifacts/pilot/shared_guidance/" + parts[3] + "/probe_manifest.json"
        source = read(root / source_name)
        jobs = sorted(source["jobs"], key=lambda job: job["position_in_case"])
        if (source["public_record"]["profile_id"] != selected[0]["profile_id"]
                or sha(canonical(source["public_record"])) != source["public_record_sha256"]
                or len(jobs) != 4 or {j["planner_version"] for j in jobs} != {1, 2, 3, 4}
                or [j["position_in_case"] for j in jobs] != [1, 2, 3, 4]
                or source["limits"].get("maximum_generation_submissions") != 15
                or source["limits"].get("maximum_revisions_v4") != 2):
            raise ValueError("A selected case lost its original public facts, balanced order or limits.")
        verify(root, {**source["case_review_files"], **source["module_and_config_sha256"]})
        bindings[source_name] = sha((root / source_name).read_bytes())
        bindings.update(source["case_review_files"])
        originals.append(source)
        roster.append({"case_index": index, "profile_id": selected[0]["profile_id"],
            "public_record": deepcopy(source["public_record"]), "original_jobs": jobs,
            "prepared_jobs": deepcopy(source["prepared_jobs"]),
            **{k: deepcopy(source[k]) for k in ("case_review_id", "case_review_files", "case_review_config_path", "public_schema_path")}})
    if any(source["model_configuration"] != originals[0]["model_configuration"]
           or source["limits"] != originals[0]["limits"] or source["timing_policy"] != originals[0]["timing_policy"] for source in originals[1:]):
        raise ValueError("The selected original cases do not share one model and execution policy.")
    if any(sorted(job["position_in_case"] for row in roster for job in row["original_jobs"]
                  if job["planner_version"] == version) != [1, 2, 3, 4] for version in range(1, 5)):
        raise ValueError("The fixed four-case roster must place every planner in every position once.")
    sources = dict(parent["component_sha256"])
    for name in ("reviewed_probe", "live_reviewed_runtime", "pilot_probe", "pilot_trace", "shared_guidance_probe", "development_pilot"):
        relative = "src/champion_athletic_map/" + name + ".py"
        digest = sha((root / relative).read_bytes())
        if relative in sources and sources[relative] != digest:
            raise ValueError("An existing reviewed source changed: " + relative)
        sources[relative] = digest
    identity = {"schema_version": VERSION, "execution_mode": execution_mode,
        "parent_workflow_id": parent["workflow_id"], "parent_files": bindings,
        "case_roster": roster, "module_and_config_sha256": sources,
        "model_configuration": originals[0]["model_configuration"], "per_case_limits": originals[0]["limits"],
        "timing_policy": originals[0]["timing_policy"],
        "environment": environment_record if environment_record is not None else module(root, "pilot_probe").environment(),
        "limits": {"cases": 4, "jobs": 16, "maximum_generation_submissions_per_case": 15,
                   "maximum_generation_submissions_total": 60, "maximum_revisions_v4": 2},
        "factories": {"runtime": "live_reviewed_runtime.build_runtime",
                      "references": "live_reviewed_runtime.build_reference_preparer",
                      "assessor": "live_reviewed_runtime.make_assessor"},
        "offline_candidate_packets_reused_for_generation": False,
        "automatic_retries": 0, "output_repairs": 0, "accepted_study_profiles": 0,
        "human_reviews_claimed": 0, "final_scores_computed": False,
        "protocol_frozen": False, "app_generation_enabled": False}
    digest = sha(canonical(identity))
    probe_id = "reviewed_" + digest[:20]
    cases = []
    for position, index in enumerate(CASE_INDICES, 1):
        folder = "results/pilot/reviewed_probe/" + probe_id + "/cases/case_" + str(index).zfill(2)
        child_id = "reviewedcase_" + digest[:16] + "_c" + str(index).zfill(2)
        cases.append({"case_index": index, "execution_position": position, "probe_id": child_id, "folder": folder,
            "manifest_path": "artifacts/pilot/shared_guidance/" + child_id + "/probe_manifest.json",
            "pointer": folder + "/pointer.json", "summary": folder + "/summary.json",
            "generation_summary": folder + "/generation_summary.json", "completed": folder + "/completed.json",
            "call_prefix": "p31r_" + digest[:16] + "_c" + str(index).zfill(2) + "_v"})
    manifest = {**identity, "manifest_id": digest, "probe_id": probe_id, "cases": cases}
    expected_pointer = {"manifest_id": digest, "manifest_path": manifest_path(manifest)}
    if (root / pointer).exists() and read(root / pointer) != expected_pointer:
        raise ValueError("This probe already has a different frozen configuration; earlier files were preserved.")
    save_once(root / manifest_path(manifest), manifest)
    save_once(root / pointer, expected_pointer)
    for case in cases:
        child = child_manifest(root, manifest, case)
        save_once(root / case["manifest_path"], child)
        save_once(root / case["pointer"], {"manifest_id": child["manifest_id"], "manifest_path": case["manifest_path"]})
    return manifest


def validate_manifest(root, manifest):
    identity = {k: v for k, v in manifest.items() if k not in ("manifest_id", "probe_id", "cases")}
    if (sha(canonical(identity)) != manifest["manifest_id"]
            or read(root / manifest_path(manifest)) != manifest
            or read(root / pointer_path(manifest["execution_mode"])) != {
                "manifest_id": manifest["manifest_id"], "manifest_path": manifest_path(manifest)}
            or [c["case_index"] for c in manifest["cases"]] != list(CASE_INDICES)
            or manifest["limits"] != {"cases": 4, "jobs": 16, "maximum_generation_submissions_per_case": 15,
                                     "maximum_generation_submissions_total": 60, "maximum_revisions_v4": 2}):
        raise ValueError("The frozen four-case probe changed.")
    verify(root, {**manifest["parent_files"], **manifest["module_and_config_sha256"]})
    for case in manifest["cases"]:
        child = child_manifest(root, manifest, case)
        if (read(root / case["manifest_path"]) != child
                or read(root / case["pointer"]) != {"manifest_id": child["manifest_id"], "manifest_path": case["manifest_path"]}):
            raise ValueError("A frozen reviewed case manifest or pointer changed.")


@contextmanager
def probe_lock(root, manifest):
    path = root / "results/pilot/reviewed_probe" / manifest["probe_id"] / "probe.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"\0"); handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Another reviewed probe is running.") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def submissions(root, manifest):
    trace = module(root, "pilot_trace")
    total = 0
    for case in manifest["cases"]:
        path = root / "results/pilot/probes" / case["probe_id"] / "http_events.jsonl"
        events = trace._read_events(path) if path.exists() else []
        count = sum(r.get("event") == "http_started" and r.get("phase") == "generation" for r in events)
        if count > 15:
            raise ValueError("A reviewed case exceeded its 15-request limit.")
        total += count
    if total > 60:
        raise ValueError("The reviewed probe exceeded its 60-request limit.")
    return total


def _state_api(root):
    api = module(root, "development_pilot")
    api.child_manifest = child_manifest
    return api


def execute(root, manifest=None, *, software_evidence, max_cases=4, runtime_factory=None,
            references_factory=None, assessor_factory=None, trace_module=None, emit=print):
    """Run or resume at most four frozen cases; never repeat uncertain outcomes."""
    root = Path(root).resolve()
    injected = any(value is not None for value in (runtime_factory, references_factory, assessor_factory, trace_module))
    mode = "injected_test" if injected else "production"
    if type(max_cases) is not int or not 1 <= max_cases <= 4:
        raise ValueError("The small probe may start one to four cases per execution.")
    if (software_evidence.get("status") != "passed" or software_evidence.get("passed", 0) <= 0
            or not software_evidence.get("files")):
        raise ValueError("The reviewed-probe software checks must pass first.")
    verify(root, software_evidence["files"])
    if manifest is None:
        pointer = read(root / pointer_path(mode))
        manifest = read(root / pointer["manifest_path"])
    if manifest["execution_mode"] != mode:
        raise ValueError("Injected observations and production observations cannot share a probe.")
    validate_manifest(root, manifest)
    state_api = _state_api(root)
    with probe_lock(root, manifest):
        states = [state_api.case_state(root, manifest, case, seal=True) for case in manifest["cases"]]
        if any(state["injected_test_dependencies"] != injected and state["state"] != "not_started" for state in states):
            raise ValueError("A saved case was executed in a different dependency mode.")
        before, started = submissions(root, manifest), 0
        reused = sum(s["state"] == "completed" for s in states)
        blocked = next((s for s in states if s["state"] == "stopped_for_review"), None)
        stop, failure = (blocked["stop_reason"] if blocked else None), None
        for position, (case, state) in enumerate(zip(manifest["cases"], states)):
            if stop or started >= max_cases:
                break
            if state["state"] == "completed":
                continue
            started += 1
            child = child_manifest(root, manifest, case)
            emit("Case " + str(case["case_index"]) + " — running (" + str(position + 1) + "/4)")
            previous = module(root, "shared_guidance_probe")
            previous.VERSION, previous.POINTER, previous.SUMMARY, previous.GENERATION_SUMMARY = (
                VERSION, case["pointer"], case["summary"], case["generation_summary"])
            original_module = previous.module
            live = module(root, "live_reviewed_runtime")
            def router(project, name):
                if name == "shared_guidance_runtime":
                    return SimpleNamespace(build_runtime=lambda r, review, schema:
                        live.build_runtime(r, review, schema, public_record=child["public_record"]))
                if name == "independent_plan_assessment":
                    return SimpleNamespace(IndependentAssessor=live.make_assessor)
                value = original_module(project, name)
                if name == "pilot_probe":
                    original_execute = value.execute_probe
                    def reviewed_execute(*args, **kwargs):
                        if kwargs.get("references_factory") is None:
                            kwargs["references_factory"] = live.build_reference_preparer
                        return original_execute(*args, **kwargs)
                    value.execute_probe = reviewed_execute
                return value
            previous.module = router
            save_once(root / case["folder"] / "execution_mode.json", {
                "manifest_id": child["manifest_id"], "injected_test_dependencies": injected})
            captured = io.StringIO()
            try:
                with redirect_stdout(captured):
                    result = previous.execute(root, child, software_evidence=software_evidence,
                        runtime_factory=runtime_factory, references_factory=references_factory,
                        assessor_factory=assessor_factory, trace_module=trace_module, emit=lambda message: None)
                stop = result.get("stop_reason")
                if not result.get("independent_assessment_completed") and not stop:
                    stop = "independent_assessment_not_completed"
            except Exception as error:
                stop, failure = "reviewed_probe_execution_needs_review", error
            finally:
                folder = root / case["folder"]
                folder.mkdir(parents=True, exist_ok=True)
                (folder / ("console_" + uuid4().hex[:12] + ".log")).write_text(captured.getvalue(), encoding="utf-8")
            if stop:
                save_once(root / case["folder"] / "stopped.json", {"reason": stop,
                    "error": type(failure).__name__ + ": " + str(failure) if failure else None,
                    "model_requests_automatically_repeated": False})
            states[position] = state_api.case_state(root, manifest, case, seal=True)
            for report in sorted(states[position]["reports"], key=lambda r: r["planner_version"]):
                outcome = report["outcome"]
                emit("  Planner " + str(report["planner_version"]) + ": " + str(outcome.get("response_type") or outcome.get("status") or "unavailable")
                     + " | Contract: " + ("valid" if outcome.get("format_valid") else "needs review"))
        total = submissions(root, manifest)
        completed = sum(s["state"] == "completed" for s in states)
        jobs = [{"case_index": s["case_index"], "profile_id": s["profile_id"], **o}
                for s in states for o in s["outcomes"]]
        summary = {"schema_version": VERSION, "probe_id": manifest["probe_id"], "manifest_id": manifest["manifest_id"],
            "status": "stopped_for_review" if stop else "reviewed_probe_recorded" if completed == 4 else "next_case_ready",
            "completed_cases": completed, "planned_cases": 4, "recorded_jobs": len(jobs), "planned_jobs": 16,
            "new_cases_attempted": started, "saved_completed_cases_reused": reused,
            "new_model_submissions": total - before, "cumulative_model_submissions": total,
            "stop_reason": stop, "cases": states, "jobs": jobs, "software_evidence": deepcopy(software_evidence),
            "reviewed_probe_completed": completed == 4, "original_results_replaced": False,
            "accepted_study_profiles": 0, "human_reviews_claimed": 0, "final_scores_computed": False,
            "protocol_frozen": False, "app_generation_enabled": False,
            "required_unknowns_waived": False, "operational_generation_ready": False,
            "injected_test_dependencies": injected}
        summary_name = SUMMARY if not injected else "results/pilot/reviewed_probe/injected_test_summary.json"
        module(root, "pilot_probe").save(root / summary_name, summary)
        emit("Cases complete: " + str(completed) + "/4 | Outcomes saved: " + str(len(jobs)) + "/16")
        emit("New model submissions: " + str(total - before) + " | " + ("Stopped for review: " + stop if stop else "Final scoring: pending"))
        emit("Saved: " + summary_name)
        if failure:
            raise failure
        return summary
