"""Run the fixed twenty-case development pilot in resumable, bounded batches."""

from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker


VERSION = "resumable-development-pilot-1"
POINTER = "results/pilot/development_batches/development_pilot.json"
SUMMARY = "results/step31_development_pilot_summary.json"
DOCUMENT = "docs/development_pilot_batches.md"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def module(root, name):
    path = root / "src/champion_athletic_map" / (name + ".py")
    value = importlib.util.module_from_spec(importlib.util.spec_from_file_location("development_pilot_" + name, path))
    value.__spec__.loader.exec_module(value)
    return value


def verify(root, bindings):
    for relative, expected in bindings.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError("A frozen development-pilot dependency changed: " + relative)


def save_once(path, value):
    data = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("An earlier development-pilot file differs and was preserved: " + path.name)
    else:
        with path.open("xb") as handle:
            handle.write(data)


def manifest_path(manifest):
    return "artifacts/pilot/development_runs/" + manifest["pilot_id"] + "/manifest.json"


def child_manifest(root, manifest, case):
    record = manifest["case_roster"][case["case_index"] - 1]
    identity = {"schema_version": VERSION, "mode": "provisional_development_pilot_case",
        "overall_manifest_id": manifest["manifest_id"], "case_index": case["case_index"],
        "parent_files": {manifest_path(manifest): sha((root / manifest_path(manifest)).read_bytes())},
        "case_review_id": manifest["case_review_id"], "case_review_files": manifest["case_review_files"],
        "public_record": record["public_record"], "public_record_sha256": sha(canonical(record["public_record"])),
        "prepared_jobs": record["prepared_jobs"], "module_and_config_sha256": manifest["module_and_config_sha256"],
        "model_configuration": manifest["model_configuration"], "environment": manifest["environment"],
        "limits": manifest["per_case_limits"], "timing_policy": manifest["timing_policy"],
        "original_results_replaced": False, "output_repairs": 0, "automatic_retries": 0,
        "accepted_study_profiles": 0, "protocol_frozen": False}
    return {**identity, "manifest_id": sha(canonical(identity)), "probe_id": case["probe_id"],
        "case_review_config_path": manifest["case_review_config_path"], "public_schema_path": manifest["public_schema_path"],
        "jobs": [{"job_id": case["call_prefix"] + item["planner_version"],
            "call_id": case["call_prefix"] + item["planner_version"], "planner_version": int(item["planner_version"]),
            "position_in_case": int(item["position_in_case"]), "parent_prepared_job_id": item["job_id"]}
            for item in record["prepared_jobs"]]}


def prepare(root, *, environment_record=None):
    root = Path(root).resolve()
    parent_path = "results/step31_operational_corrections_summary.json"
    parent = read(root / parent_path)
    evidence = parent.get("software_evidence") or {}
    if (parent.get("candidate_only") is not True or parent.get("new_runtime_executed") is not False
            or parent.get("new_model_calls") != 0 or evidence.get("status") != "passed" or evidence.get("passed", 0) <= 0
            or not evidence.get("files") or not parent.get("candidate_files")):
        raise ValueError("Step 31-9 must contain its completed prospective operational checks.")
    parent_files = {parent_path: sha((root / parent_path).read_bytes()), **parent["input_sha256"],
        **parent["component_sha256"], **parent["candidate_files"], **evidence["files"]}
    verify(root, parent_files)
    original_pointer = "results/pilot/probes/first_operational_probe.json"
    pointer = read(root / original_pointer)
    source = read(root / pointer["manifest_path"])
    body = {key: value for key, value in source.items() if key not in
        ("probe_id", "manifest_id", "case_review_config_path", "public_schema_path", "jobs")}
    if pointer.get("manifest_id") != source["manifest_id"] or sha(canonical(body)) != source["manifest_id"]:
        raise ValueError("The original development-case manifest changed.")
    verify(root, {**source["case_review_files"], **source["module_and_config_sha256"]})
    review = read(root / source["case_review_config_path"])
    verify(root, review["parent_preparation_files"])
    profiles_path = next(name for name in source["case_review_files"] if name.endswith("/public_profiles.jsonl"))
    publics = [json.loads(line) for line in (root / profiles_path).read_bytes().splitlines() if line.strip()]
    indexed = {item["profile_id"]: item for item in publics}
    legacy_path = next(name for name in review["parent_preparation_files"] if name.endswith("/public_profiles.jsonl"))
    originals = {item["profile_id"]: item for item in
        (json.loads(line) for line in (root / legacy_path).read_bytes().splitlines() if line.strip())}
    jobs_path = next(name for name in review["parent_preparation_files"] if name.endswith("/planned_pilot_jobs.csv"))
    with (root / jobs_path).open(encoding="utf-8", newline="") as handle:
        jobs = list(csv.DictReader(handle))
    if (len(publics) != 20 or len(indexed) != 20 or set(indexed) != set(originals) or len(jobs) != 80
            or len({item["job_id"] for item in jobs}) != 80
            or sorted(int(item["scheduled_index"]) for item in jobs) != list(range(1, 81))):
        raise ValueError("The pilot needs the original twenty public cases and eighty prepared jobs.")
    validator = Draft202012Validator(read(root / source["public_schema_path"]), format_checker=FormatChecker())
    roster = []
    for number in range(1, 21):
        selected = sorted([item for item in jobs if int(item["pilot_index"]) == number], key=lambda item: int(item["position_in_case"]))
        if (len(selected) != 4 or {int(item["planner_version"]) for item in selected} != {1, 2, 3, 4}
                or [int(item["position_in_case"]) for item in selected] != [1, 2, 3, 4]
                or [int(item["scheduled_index"]) for item in selected] != list(range(number * 4 - 3, number * 4 + 1))
                or len({item["profile_id"] for item in selected}) != 1):
            raise ValueError("A case lost its original balanced job order.")
        public = indexed[selected[0]["profile_id"]]
        validator.validate(public)
        original = originals[public["profile_id"]]
        unchanged = deepcopy(public)
        unchanged["input"].pop("schedule_coverage", None)
        unchanged["schema_version"] = original["schema_version"]
        if unchanged != original or any(item["public_record_sha256"] != sha(canonical(original)) for item in selected):
            raise ValueError("The authored schedule-coverage version lost its unchanged public-source lineage.")
        roster.append({"case_index": number, "public_record": public, "prepared_jobs": selected})
    if len({row["public_record"]["profile_id"] for row in roster}) != 20:
        raise ValueError("Each prepared development case must occur once.")
    bindings = {**source["module_and_config_sha256"], **parent["component_sha256"]}
    for path in sorted((root / "src/champion_athletic_map").rglob("*.py")):
        relative, digest = path.relative_to(root).as_posix(), sha(path.read_bytes())
        if relative in bindings and bindings[relative] != digest:
            raise ValueError("A saved workflow source changed: " + relative)
        bindings[relative] = digest
    bindings[DOCUMENT] = sha((root / DOCUMENT).read_bytes())
    parent_files.update({name: sha((root / name).read_bytes()) for name in (original_pointer, pointer["manifest_path"])})
    parent_files.update(review["parent_preparation_files"])
    if source["limits"].get("maximum_generation_submissions") != 15 or source["limits"].get("maximum_revisions_v4") != 2:
        raise ValueError("The saved per-case generation and revision limits changed.")
    identity = {"schema_version": VERSION, "mode": "fixed_provisional_development_pilot",
        "parent_operational_configuration_id": parent["configuration_id"], "parent_files": parent_files,
        "case_review_id": source["case_review_id"], "case_review_files": source["case_review_files"],
        "case_review_config_path": source["case_review_config_path"], "public_schema_path": source["public_schema_path"],
        "case_roster": roster, "module_and_config_sha256": bindings, "model_configuration": source["model_configuration"],
        "environment": environment_record if environment_record is not None else module(root, "pilot_probe").environment(),
        "per_case_limits": source["limits"], "limits": {"cases": 20, "jobs": 80, "new_cases_per_batch": 5,
            "maximum_generation_submissions_per_case": 15, "maximum_generation_submissions_total": 300},
        "timing_policy": source["timing_policy"], "runtime_factory": "operational_runtime.build_runtime",
        "assessment_factory": "food_answer_audit.make_assessor", "accepted_study_profiles": 0,
        "final_scores_computed": False, "protocol_frozen": False, "app_generation_enabled": False}
    digest = sha(canonical(identity))
    pilot_id = "development_" + digest[:20]
    cases = []
    for number in range(1, 21):
        folder = "results/pilot/development_batches/" + pilot_id + "/cases/case_" + str(number).zfill(2)
        probe_id = "pilotcase_" + digest[:16] + "_c" + str(number).zfill(2)
        cases.append({"case_index": number, "probe_id": probe_id, "folder": folder,
            "manifest_path": "artifacts/pilot/shared_guidance/" + probe_id + "/probe_manifest.json",
            "pointer": folder + "/pointer.json", "summary": folder + "/summary.json",
            "generation_summary": folder + "/generation_summary.json", "completed": folder + "/completed.json",
            "call_prefix": "p31d_" + digest[:16] + "_c" + str(number).zfill(2) + "_v"})
    manifest = {**identity, "manifest_id": digest, "pilot_id": pilot_id, "cases": cases}
    path = manifest_path(manifest)
    if (root / POINTER).exists() and read(root / POINTER) != {"manifest_id": digest, "manifest_path": path}:
        raise ValueError("The pilot already has another frozen configuration; its results were preserved.")
    save_once(root / path, manifest)
    save_once(root / POINTER, {"manifest_id": digest, "manifest_path": path})
    for case in cases:
        child = child_manifest(root, manifest, case)
        save_once(root / case["manifest_path"], child)
        save_once(root / case["pointer"], {"manifest_id": child["manifest_id"], "manifest_path": case["manifest_path"]})
    return manifest


@contextmanager
def batch_lock(root, manifest):
    path = root / "results/pilot/development_batches" / manifest["pilot_id"] / "batch.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
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
            raise RuntimeError("Another development-pilot batch is running.") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def validate_manifest(root, manifest):
    identity = {key: value for key, value in manifest.items() if key not in ("manifest_id", "pilot_id", "cases")}
    if (sha(canonical(identity)) != manifest["manifest_id"] or read(root / manifest_path(manifest)) != manifest
            or read(root / POINTER) != {"manifest_id": manifest["manifest_id"], "manifest_path": manifest_path(manifest)}):
        raise ValueError("The frozen development pilot differs from its recorded manifest.")
    verify(root, {**manifest["parent_files"], **manifest["case_review_files"], **manifest["module_and_config_sha256"]})
    for case in manifest["cases"]:
        child = child_manifest(root, manifest, case)
        if (read(root / case["manifest_path"]) != child
                or read(root / case["pointer"]) != {"manifest_id": child["manifest_id"], "manifest_path": case["manifest_path"]}):
            raise ValueError("A development case manifest or pointer changed.")


def case_state(root, manifest, case, *, seal=False):
    child = child_manifest(root, manifest, case)
    mode_path = root / case["folder"] / "execution_mode.json"
    mode = read(mode_path) if mode_path.exists() else None
    if mode and (mode.get("manifest_id") != child["manifest_id"] or type(mode.get("injected_test_dependencies")) is not bool):
        raise ValueError("A case execution mode differs from its recorded manifest.")
    receipt = root / case["completed"]
    if receipt.exists():
        value = read(receipt)
        if value.get("manifest_id") != child["manifest_id"]:
            raise ValueError("A completed development case belongs to another manifest.")
        verify(root, value["files"])
    probe = module(root, "pilot_probe")
    folder = root / "results/pilot/probes" / child["probe_id"]
    outcomes, packets = [], []
    for job in child["jobs"]:
        work = folder / "jobs" / job["job_id"]
        if (work / "job_record.json").exists():
            record = read(work / "job_record.json")
            outcome = probe.verify_job(root, child, job, work, record)
            supplied = (outcome.get("response") or {}).get("authoritative_public_input")
            if supplied is not None and canonical(supplied) != canonical(child["public_record"]["input"]):
                raise ValueError("A development outcome contains a different authoritative public input.")
            if job["planner_version"] != 1 and record.get("reference_record"):
                packets.append(record["reference_record"]["packet"])
            outcomes.append({"job": job, "outcome": record["outcome"], "designated_outcome_sha256": sha(canonical(outcome))})
    summary = read(root / case["summary"]) if (root / case["summary"]).exists() else None
    complete = bool(summary and summary.get("manifest_id") == child["manifest_id"] and summary.get("recorded_jobs") == 4
        and summary.get("independent_assessment_completed") is True and not summary.get("stop_reason") and len(outcomes) == 4)
    if complete:
        reports = summary.get("reports") or []
        by_job = {item["job"]["job_id"]: item for item in outcomes}
        if (type(summary.get("injected_test_dependencies")) is not bool
                or mode and mode["injected_test_dependencies"] != summary["injected_test_dependencies"]
                or len(packets) != 3 or any(canonical(packet) != canonical(packets[0]) for packet in packets[1:])
                or len(reports) != 4 or {item["job_id"] for item in reports} != set(by_job)
                or any(item["assessment"].get("assessment_execution") != "completed"
                    or item["planner_version"] != by_job[item["job_id"]]["job"]["planner_version"]
                    or item["outcome"] != by_job[item["job_id"]]["outcome"]
                    or item["outcome_path"] != (folder / "jobs" / item["job_id"] / "outcome.json").relative_to(root).as_posix()
                    or item["assessment"].get("designated_outcome_sha256") != by_job[item["job_id"]]["designated_outcome_sha256"] for item in reports)):
            raise ValueError("A completed case lost its designated independent assessments.")
        if seal and not receipt.exists():
            paths = [p for base in (root / case["folder"], folder) for p in base.rglob("*") if p.is_file()]
            native = root / "results/integration/model_calls"
            paths += [p for base in native.glob(case["call_prefix"] + "*") if base.is_dir() for p in base.rglob("*") if p.is_file()]
            paths += [root / name for name in summary["software_evidence"]["files"]]
            save_once(receipt, {"manifest_id": child["manifest_id"], "case_index": case["case_index"],
                "files": {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in paths if p != receipt}})
    if receipt.exists() and not complete:
        raise ValueError("A sealed development case no longer contains four assessed outcomes.")
    stopped = read(root / case["folder"] / "stopped.json") if (root / case["folder"] / "stopped.json").exists() else None
    stop = (summary or {}).get("stop_reason") or (stopped or {}).get("reason")
    if not complete and not stop:
        events = folder / "http_events.jsonl"
        if events.is_file() and any(item.get("unresolved") is True for item in module(root, "pilot_trace")._read_events(events)):
            stop = "unresolved_backend_outcome"
    return {"case_index": case["case_index"], "profile_id": child["public_record"]["profile_id"],
        "state": "completed" if complete else "stopped_for_review" if stop else "partially_recorded" if outcomes else "not_started",
        "stop_reason": stop, "outcomes": outcomes, "summary_path": case["summary"] if summary else None,
        "reports": (summary or {}).get("reports", []),
        "injected_test_dependencies": bool((mode or summary or {}).get("injected_test_dependencies"))}


def submissions(root, manifest):
    total = 0
    trace = module(root, "pilot_trace")
    for case in manifest["cases"]:
        path = root / "results/pilot/probes" / case["probe_id"] / "http_events.jsonl"
        rows = trace._read_events(path) if path.exists() else []
        count = sum(row.get("event") == "http_started" and row.get("phase") == "generation" for row in rows)
        if count > 15:
            raise ValueError("A development case exceeded its frozen generation budget.")
        total += count
    if total > 300:
        raise ValueError("The development pilot exceeded its frozen generation budget.")
    return total


def run_next_batch(root, manifest, *, software_evidence, max_cases=5, runtime_factory=None,
                   references_factory=None, trace_module=None, assessor_factory=None, emit=print):
    root = Path(root).resolve()
    if type(max_cases) is not int or not 1 <= max_cases <= 5:
        raise ValueError("Each batch may start between one and five development cases.")
    if (software_evidence.get("status") != "passed" or software_evidence.get("passed", 0) <= 0 or not software_evidence.get("files")):
        raise ValueError("The development-pilot software checks must pass first.")
    verify(root, software_evidence["files"])
    validate_manifest(root, manifest)
    injected = any(value is not None for value in (runtime_factory, references_factory, trace_module, assessor_factory))
    with batch_lock(root, manifest):
        states = [case_state(root, manifest, case, seal=True) for case in manifest["cases"]]
        if not injected and any(item["injected_test_dependencies"] for item in states):
            raise ValueError("Saved injected test dependencies cannot be reused as production observations.")
        reused = sum(item["state"] == "completed" for item in states)
        before, started, stop, exception = submissions(root, manifest), 0, None, None
        blocked = next((item for item in states if item["state"] == "stopped_for_review"), None)
        if blocked:
            stop = blocked["stop_reason"]
        for case, state in zip(manifest["cases"], states):
            if stop or started >= max_cases:
                break
            if state["state"] == "completed":
                continue
            started += 1
            emit("Case " + str(case["case_index"]) + "/20 — running")
            previous = module(root, "shared_guidance_probe")
            previous.VERSION, previous.POINTER, previous.SUMMARY, previous.GENERATION_SUMMARY = VERSION, case["pointer"], case["summary"], case["generation_summary"]
            original_module = previous.module
            public = manifest["case_roster"][case["case_index"] - 1]["public_record"]
            def router(project, name):
                if name == "shared_guidance_runtime":
                    return SimpleNamespace(build_runtime=lambda root, review, schema:
                        module(root, "operational_runtime").build_runtime(root, review, schema, public_record=public))
                if name == "independent_plan_assessment":
                    return SimpleNamespace(IndependentAssessor=module(project, "food_answer_audit").make_assessor)
                return original_module(project, name)
            previous.module = router
            save_once(root / case["folder"] / "execution_mode.json", {
                "manifest_id": child_manifest(root, manifest, case)["manifest_id"], "injected_test_dependencies": injected})
            captured = io.StringIO()
            try:
                with redirect_stdout(captured):
                    result = previous.execute(root, child_manifest(root, manifest, case), software_evidence=software_evidence,
                        runtime_factory=runtime_factory, references_factory=references_factory, trace_module=trace_module,
                        assessor_factory=assessor_factory, emit=lambda text: None)
                stop = result.get("stop_reason")
                if not result.get("independent_assessment_completed") and not stop:
                    stop = "independent_assessment_not_completed"
            except Exception as error:
                stop, exception = "development_execution_needs_review", error
            finally:
                folder = root / case["folder"]
                folder.mkdir(parents=True, exist_ok=True)
                (folder / ("console_" + uuid4().hex[:12] + ".log")).write_text(captured.getvalue(), encoding="utf-8")
            if stop:
                save_once(root / case["folder"] / "stopped.json", {"reason": stop,
                    "error": type(exception).__name__ + ": " + str(exception) if exception else None,
                    "model_requests_automatically_repeated": False})
            states[case["case_index"] - 1] = case_state(root, manifest, case, seal=True)
        total = submissions(root, manifest)
        completed = sum(item["state"] == "completed" for item in states)
        by_job = {item["job"]["job_id"]: item for state in states for item in state["outcomes"]}
        roster = [{"case_index": case["case_index"], "profile_id": state["profile_id"], "job_id": job["job_id"],
            "planner_version": job["planner_version"], "position_in_case": job["position_in_case"],
            "state": "independently_assessed" if state["state"] == "completed" else "terminal_recorded" if job["job_id"] in by_job else "not_started",
            "outcome": (by_job.get(job["job_id"]) or {}).get("outcome")}
            for case, state in zip(manifest["cases"], states) for job in child_manifest(root, manifest, case)["jobs"]]
        summary = {"schema_version": VERSION, "pilot_id": manifest["pilot_id"], "manifest_id": manifest["manifest_id"],
            "status": "stopped_for_review" if stop else "development_pilot_recorded" if completed == 20 else "next_batch_ready",
            "completed_cases": completed, "planned_cases": 20, "recorded_jobs": len(by_job), "planned_jobs": 80,
            "new_cases_attempted_this_batch": started, "saved_completed_cases_reused": reused,
            "new_model_submissions": total - before, "cumulative_model_submissions": total,
            "stop_reason": stop, "cases": states, "jobs": roster, "software_evidence": software_evidence,
            "development_pilot_completed": completed == 20, "accepted_study_profiles": 0, "human_reviews_claimed": 0,
            "final_scores_computed": False, "protocol_frozen": False, "app_generation_enabled": False,
            "required_unknowns_waived": False, "old_probe_results_replaced": False,
            "injected_test_dependencies": injected or any(item["injected_test_dependencies"] for item in states)}
        module(root, "pilot_probe").save(root / SUMMARY, summary)
        emit("Cases complete: " + str(completed) + "/20 | Outcomes saved: " + str(len(by_job)) + "/80")
        emit("New model submissions: " + str(total - before) + " | " + ("Stopped for review: " + stop if stop else "Final scoring: pending" if completed == 20 else "Rerun this cell for the next batch"))
        emit("Saved: " + SUMMARY)
        if exception:
            raise exception
        return summary
