"""Run the frozen final job roster in serial, resumable case batches.

The existing four-workflow transport engine is reused for one case at a time.
Its development roster and summary are never reused as final observations.
"""

from collections import Counter
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from uuid import uuid4


VERSION = "frozen-final-comparison-runner-1"
CATEGORIES = {"feasible": 150, "missing_information": 20,
              "conflicting_constraints": 15, "outside_scope": 15}


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def checked(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative,
            "A final comparison artifact needs a relative project path.")
    path = root / relative
    require(not Path(relative).is_absolute() and ".." not in Path(relative).parts
            and path.resolve() == path, "A final comparison path leaves the project.")
    return path


def module(root, name):
    path = checked(root, "src/champion_athletic_map/" + name + ".py")
    spec = importlib.util.spec_from_file_location("final_runner_" + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def verify(root, bindings):
    for relative, expected in bindings.items():
        require(sha(checked(root, relative).read_bytes()) == expected,
                "A frozen final comparison dependency changed: " + relative)


def save_once(path, value):
    data = value if isinstance(value, bytes) else canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == data, "An earlier final comparison artifact differs and was preserved: " + path.name)
        return
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def replace_progress(path, value):
    data = value if isinstance(value, bytes) else canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".final-progress-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def validate_roster(profiles, annotations, jobs):
    require(isinstance(profiles, list) and len(profiles) == 200
            and isinstance(annotations, list) and len(annotations) == 200
            and isinstance(jobs, list) and len(jobs) == 800,
            "The final comparison requires the fixed 200 cases and 800 planned jobs.")
    records = {row["profile_id"]: row for row in profiles}
    notes = {row["profile_id"]: row for row in annotations}
    require(len(records) == len(notes) == 200 and records.keys() == notes.keys(),
            "The final public and private case rosters differ.")
    require(Counter(row["case_category"] for row in annotations) == CATEGORIES,
            "The fixed final category denominators changed.")
    require(all(set(row) == {"profile_id", "schema_version", "input"} for row in profiles),
            "Private case metadata cannot enter a planner public record.")
    require(len({row["job_id"] for row in jobs}) == 800,
            "The final planned job identities must be distinct.")
    require(Counter((job["profile_id"], job["planner_version"]) for job in jobs)
            == Counter({(pid, version): 1 for pid in records for version in range(1, 5)}),
            "A paired final workflow is missing or duplicated.")
    require([row["case_sequence"] for row in jobs[::4]] == list(range(1, 201)),
            "The final case sequence changed.")
    for index in range(0, 800, 4):
        selected = jobs[index:index + 4]
        pid = selected[0]["profile_id"]
        require(len({row["profile_id"] for row in selected}) == 1
                and [row["position_in_case"] for row in selected] == [1, 2, 3, 4]
                and all(row["case_sequence"] == index // 4 + 1 for row in selected),
                "The recorded within-case workflow order changed.")
        digest = sha(packed(records[pid]))
        require(notes[pid]["public_record_sha256"] == digest
                and all(row["public_record_sha256"] == digest for row in selected),
                "A planned job refers to an earlier public case version.")
    return records, notes


def prepare_manifest(root, *, freeze, common_summary, review_config_path,
                     public_schema_path, source_sha256, protocol,
                     software_fixture=False, execution_authorized=False):
    """Record a new final runner; preparing it does not execute or authorize jobs."""
    root = Path(root).resolve()
    validate_roster(freeze["profiles"], freeze["annotations"], freeze["jobs"])
    require(common_summary.get("common_checker_software_ready") is True
            and common_summary.get("case_freeze_id") == freeze["summary"]["case_freeze_id"],
            "The final runner needs the common checker bound to this case freeze.")
    require(freeze["summary"].get("software_fixture") is software_fixture,
            "A software fixture cannot stand in for the installed final cases.")
    require(isinstance(protocol, dict) and type(protocol.get("final_protocol_frozen")) is bool,
            "The final comparison protocol status must be recorded explicitly.")
    require(type(execution_authorized) is bool and execution_authorized is False,
            "Preparation does not authorize final model execution.")
    bindings = dict(source_sha256)
    for relative in (review_config_path, public_schema_path):
        bindings[relative] = sha(checked(root, relative).read_bytes())
    verify(root, bindings)
    budgets = freeze["settings"]["budgets"]
    require(budgets.get("maximum_submissions_per_case_without_food") == 13
            and budgets.get("maximum_submissions_per_case_with_food") == 15
            and budgets.get("maximum_configured_completed_submissions_for_200_cases_with_20_food_questions") == 2640,
            "The frozen food and non-food workflow submission bounds changed.")
    identity = {"schema_version": VERSION, "mode": "software_fixture" if software_fixture else "final_planner_comparison",
        "case_freeze_id": freeze["summary"]["case_freeze_id"],
        "case_contracts_id": freeze["contracts"]["contracts_id"],
        "profiles": freeze["profiles"], "annotations": freeze["annotations"],
        "planned_jobs": freeze["jobs"], "case_contracts": freeze["contracts"],
        "comparison_settings": freeze["settings"], "common_check_preparation_id": common_summary["preparation_id"],
        "review_config_path": review_config_path, "public_schema_path": public_schema_path,
        "source_sha256": bindings, "protocol": protocol,
        "software_fixture": software_fixture, "execution_authorized_by_preparation": False,
        "automatic_retries": 0, "output_repairs": 0, "concurrent_model_requests": 1,
        "maximum_generation_submissions_per_case": {"without_food": 13, "with_food": 15},
        "maximum_generation_submissions_total": 2640,
        "timing_policy": freeze["settings"]["timing_policy"]}
    digest = sha(canonical(identity))
    prefix = "software_fixture_final_comparison_" if software_fixture else "final_comparison_"
    relative = freeze["summary"]["package_directory"] + "/" + prefix + digest[:20]
    manifest = {**identity, "manifest_id": digest, "package_directory": relative,
        "manifest_path": relative + "/manifest.json"}
    save_once(checked(root, manifest["manifest_path"]), manifest)
    return manifest


def validate_manifest(root, manifest):
    body = {key: value for key, value in manifest.items()
            if key not in {"manifest_id", "package_directory", "manifest_path"}}
    require(sha(canonical(body)) == manifest.get("manifest_id"), "The final run manifest identity changed.")
    require(read(checked(root, manifest["manifest_path"])) == manifest,
            "The recorded final manifest differs from this run.")
    verify(root, manifest["source_sha256"])
    return validate_roster(manifest["profiles"], manifest["annotations"], manifest["planned_jobs"])


@contextmanager
def batch_lock(root, manifest):
    path = checked(root, manifest["package_directory"] + "/batch.lock")
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
            raise RuntimeError("Another final comparison batch is running.") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def transport_manifest(manifest, case_index):
    selected = manifest["planned_jobs"][(case_index - 1) * 4:case_index * 4]
    record = next(row for row in manifest["profiles"] if row["profile_id"] == selected[0]["profile_id"])
    probe_id = "finalcase_" + manifest["manifest_id"][:16] + "_c" + str(case_index).zfill(3)
    jobs = [{"job_id": "fjob_" + sha(row["job_id"].encode("utf-8"))[:24],
        "call_id": "f33_" + manifest["manifest_id"][:16] + "_c" + str(case_index).zfill(3) + "_v" + str(row["planner_version"]),
        "planner_version": row["planner_version"], "position_in_case": row["position_in_case"],
        "planned_job_id": row["job_id"]} for row in selected]
    identity = {"schema_version": VERSION, "mode": "final_case_transport", "parent_manifest_id": manifest["manifest_id"],
        "case_index": case_index, "public_record": record, "public_record_sha256": sha(canonical(record)),
        "module_and_config_sha256": manifest["source_sha256"], "case_review_files": {},
        "jobs": jobs, "probe_id": probe_id, "case_review_config_path": manifest["review_config_path"],
        "public_schema_path": manifest["public_schema_path"]}
    return {**identity, "manifest_id": sha(canonical(identity))}


def _case_limit(manifest, case_index):
    record = transport_manifest(manifest, case_index)["public_record"]
    question = record["input"].get("food_question")
    with_food = isinstance(question, str) and bool(question.strip())
    key = "maximum_submissions_per_case_with_food" if with_food else "maximum_submissions_per_case_without_food"
    value = manifest["comparison_settings"]["budgets"][key]
    require(value == (15 if with_food else 13), "A case's frozen workflow submission bound changed.")
    return value


def _native_case(root, manifest, case_index, *, software_evidence):
    """Reuse only the verified per-case trace/transport engine in a private instance."""
    require(manifest["software_fixture"] is False, "A fixture cannot invoke the local model runtime.")
    child = transport_manifest(manifest, case_index)
    engine = module(root, "pilot_probe")
    folder = root / "results/pilot/probes" / child["probe_id"]
    # An interrupted invocation without its designated outcome is never resubmitted.
    for job in child["jobs"]:
        work = folder / "jobs" / job["job_id"]
        if work.exists() and not (work / "outcome.json").is_file():
            raise RuntimeError("An earlier final job is incomplete; it was preserved without resubmission.")
    save_original = engine.save
    legacy_summary = root / "results/step31_first_probe_summary.json"
    def isolated_save(path, value, **kwargs):
        target = folder / "transport_engine_summary.json" if Path(path).resolve() == legacy_summary else path
        return save_original(target, value, **kwargs)
    engine.save = isolated_save
    final_runtime = module(root, "final_runtime_setup")
    corrected = module(root, "corrected_runtime")
    original_trace = module(root, "pilot_trace")
    maximum = _case_limit(manifest, case_index)
    class CaseBoundedTrace(original_trace.PilotTrace):
        def __init__(self, *args, max_generation_submissions=15, **kwargs):
            super().__init__(*args, max_generation_submissions=min(max_generation_submissions, maximum), **kwargs)
    trace_api = SimpleNamespace(**{**original_trace.__dict__, "PilotTrace": CaseBoundedTrace})
    def build(project, review, schema):
        return final_runtime.build_runtime(project, review, schema,
            public_record=child["public_record"], case_contracts=manifest["case_contracts"])
    generated = engine.execute_probe(root, child, runtime_factory=build,
        references_factory=corrected.build_reference_preparer,
        trace_module=trace_api, software_evidence=software_evidence, emit=lambda _message: None)
    outcomes = []
    for job in child["jobs"]:
        work = folder / "jobs" / job["job_id"]
        if not (work / "job_record.json").is_file():
            continue
        record = read(work / "job_record.json")
        outcome = engine.verify_job(root, child, job, work, record)
        reference = record.get("reference_record")
        outcomes.append({"planned_job_id": job["planned_job_id"], "planner_version": job["planner_version"],
            "outcome": outcome, "reference_packet": reference["packet"] if reference else None,
            "backend_completion_unresolved": record.get("stop_probe") == "unresolved_backend_outcome"
                or outcome.get("status") == "unresolved",
            "elapsed_seconds": record.get("elapsed_seconds"),
            "transport_record_path": (work / "job_record.json").relative_to(root).as_posix(),
            "transport_record_sha256": sha((work / "job_record.json").read_bytes())})
    return {"outcomes": outcomes, "stop_reason": generated.get("stop_reason"),
        "new_model_submissions": generated["new_generation_transport_attempts"],
        "new_reference_encodings": generated["new_reference_encoder_processes"],
        "transport_summary_path": (folder / "transport_engine_summary.json").relative_to(root).as_posix(),
        "transport_trace_path": (folder / "http_events.jsonl").relative_to(root).as_posix(),
        "transport_engine_labels_are_not_final_study_status": True,
        "software_fixture": False}


def _recover_complete_native_case(root, manifest, case_index):
    """Recover four already-saved terminal results without invoking any runtime."""
    child = transport_manifest(manifest, case_index)
    folder = root / "results/pilot/probes" / child["probe_id"]
    if not all((folder / "jobs" / job["job_id"] / "job_record.json").is_file() for job in child["jobs"]):
        return None
    engine = module(root, "pilot_probe")
    outcomes, stop = [], None
    for job in child["jobs"]:
        work = folder / "jobs" / job["job_id"]
        record = read(work / "job_record.json")
        outcome = engine.verify_job(root, child, job, work, record)
        require(outcome.get("status") != "unresolved" and record.get("stop_probe") != "unresolved_backend_outcome",
                "An unresolved final result cannot be recovered as completed.")
        reference = record.get("reference_record")
        outcomes.append({"planned_job_id": job["planned_job_id"], "planner_version": job["planner_version"],
            "outcome": outcome, "reference_packet": reference["packet"] if reference else None,
            "backend_completion_unresolved": False,
            "elapsed_seconds": record.get("elapsed_seconds"),
            "transport_record_path": (work / "job_record.json").relative_to(root).as_posix(),
            "transport_record_sha256": sha((work / "job_record.json").read_bytes())})
        stop = stop or record.get("stop_probe")
    return {"outcomes": outcomes, "stop_reason": stop, "new_model_submissions": 0,
        "new_reference_encodings": 0, "recovered_without_submission": True,
        "transport_trace_path": (folder / "http_events.jsonl").relative_to(root).as_posix(),
        "software_fixture": False}


def validate_execution(root, manifest, case_index, execution):
    jobs = manifest["planned_jobs"][(case_index - 1) * 4:case_index * 4]
    allowed = {row["job_id"]: row for row in jobs}
    rows = execution.get("outcomes")
    require(isinstance(rows, list) and len({row["planned_job_id"] for row in rows}) == len(rows),
            "A final case repeats a designated outcome.")
    require(execution.get("software_fixture") is manifest["software_fixture"],
            "Fixture observations cannot replace native final results.")
    require(type(execution.get("new_model_submissions")) is int
            and 0 <= execution["new_model_submissions"] <= _case_limit(manifest, case_index),
            "A case exceeded its bounded generation-submission allowance.")
    encodings = execution.get("new_reference_encodings")
    require(encodings is None or type(encodings) is int and 0 <= encodings <= 3,
            "A case has inconsistent fresh reference-encoding counts.")
    packets = []
    for row in rows:
        job = allowed.get(row["planned_job_id"])
        require(job is not None and row["planner_version"] == job["planner_version"] and isinstance(row.get("outcome"), dict),
                "A designated final outcome belongs to a different planned job.")
        if row["planner_version"] == 1:
            require(row.get("reference_packet") is None, "Planner 1 must not receive a reference packet.")
        elif row.get("reference_packet") is not None:
            packets.append(row["reference_packet"])
        elif row["outcome"].get("failed_stage") != "reference_preparation":
            raise ValueError("A reference-enabled outcome lost its reference preparation.")
        if not manifest["software_fixture"]:
            path = checked(root, row["transport_record_path"])
            require(sha(path.read_bytes()) == row["transport_record_sha256"],
                    "A final transport record changed.")
            child = transport_manifest(manifest, case_index)
            transport_job = next(item for item in child["jobs"] if item["planned_job_id"] == row["planned_job_id"])
            work = path.parent
            expected = root / "results/pilot/probes" / child["probe_id"] / "jobs" / transport_job["job_id"] / "job_record.json"
            require(path == expected, "A final outcome refers to a different transport artifact.")
            transport_record = read(path)
            original = module(root, "pilot_probe").verify_job(root, child, transport_job, work, transport_record)
            reference = transport_record.get("reference_record")
            original_packet = reference.get("packet") if reference else None
            require(canonical(original) == canonical(row["outcome"])
                    and canonical(original_packet) == canonical(row.get("reference_packet"))
                    and row.get("elapsed_seconds") == transport_record.get("elapsed_seconds")
                    and row.get("backend_completion_unresolved", False) ==
                        (transport_record.get("stop_probe") == "unresolved_backend_outcome" or original.get("status") == "unresolved"),
                    "A saved final execution differs from its immutable designated transport result.")
            supplied = (original.get("response") or {}).get("authoritative_public_input")
            require(supplied is None or canonical(supplied) == canonical(child["public_record"]["input"]),
                    "The saved final outcome contains different authoritative athlete facts.")
    require(not packets or all(canonical(packet) == canonical(packets[0]) for packet in packets[1:]),
            "Versions 2–4 received different reference packets for the same case.")
    require(len(rows) == 4 or execution.get("stop_reason"), "A partial final case needs a recorded stop reason.")
    return packets[0] if packets else {"payload": {"references": [], "food_lookup": []}}


def _native_submissions(root, manifest):
    trace = module(root, "pilot_trace")
    total = 0
    for case_index in range(1, 201):
        child = transport_manifest(manifest, case_index)
        path = root / "results/pilot/probes" / child["probe_id"] / "http_events.jsonl"
        rows = trace._read_events(path)
        count = sum(row.get("event") == "http_started" and row.get("phase") == "generation" for row in rows)
        require(count <= _case_limit(manifest, case_index), "A final case exceeded its frozen generation-submission allowance.")
        total += count
    require(total <= manifest["maximum_generation_submissions_total"],
            "The final comparison exceeded its frozen total submission allowance.")
    return total


def _assess_saved(assessor, public_record, outcome, truth, *, assessment_id, annotation):
    question = public_record["input"].get("food_question")
    lookups = (truth.get("payload") or {}).get("food_lookup") if isinstance(truth, dict) else None
    found_truth = isinstance(lookups, list) and any(isinstance(row, dict)
        and row.get("status") == "found" and isinstance(row.get("data"), dict)
        and isinstance(row["data"].get("description"), str) and row["data"]["description"].strip()
        for row in lookups)
    if (outcome.get("completion_valid") is True and isinstance(question, str) and question.strip()
            and not found_truth):
        return {"assessment_id": assessment_id, "assessment_execution": "error",
            "error": "External food truth is unavailable for this completed reply; its food answer was not scored.",
            "designated_outcome_sha256": sha(canonical(outcome)),
            "public_record_sha256": sha(packed(public_record)), "final_metrics": None,
            "external_truth_available": False, "model_error_claimed": False}
    return assessor.assess(public_record, outcome, truth, assessment_id=assessment_id, case_annotation=annotation)


def run_next_batch(root, manifest, *, software_evidence, max_cases=5,
                   case_executor=None, assessor_factory=None, emit=print,
                   execution_authorized=False, retry_assessments=False):
    root = Path(root).resolve()
    require(execution_authorized is True and manifest["protocol"].get("final_protocol_frozen") is True,
            "This cell prepares jobs only; final execution needs the recorded frozen protocol and an explicit run call.")
    require(type(max_cases) is int and 1 <= max_cases <= 5, "A final batch starts one to five cases.")
    require(type(retry_assessments) is bool, "Assessment retry mode must be explicit.")
    require(software_evidence.get("status") == "passed" and software_evidence.get("passed", 0) > 0,
            "The final runner software checks must pass before execution.")
    verify(root, software_evidence["files"])
    records, notes = validate_manifest(root, manifest)
    require(manifest["software_fixture"] is (case_executor is not None or assessor_factory is not None),
            "Injected execution dependencies must remain in the software-fixture namespace.")
    ledger_api = module(root, "common_response_preparation")
    assessor = (assessor_factory(root, manifest) if assessor_factory else
        module(root, "final_response_checks").FinalResponseAssessor(root, read(root / manifest["public_schema_path"]), manifest["case_contracts"]))
    ledger = ledger_api.pending_ledger({"annotations": manifest["annotations"], "jobs": manifest["planned_jobs"]})
    by_job = {row["job_id"]: row for row in ledger}
    completed, started, reused, new_calls, new_encodings, stopped = 0, 0, 0, 0, 0, None
    with batch_lock(root, manifest):
        before_submissions = _native_submissions(root, manifest) if not manifest["software_fixture"] else None
        for case_index in range(1, 201):
            relative = manifest["package_directory"] + "/cases/case_" + str(case_index).zfill(3)
            folder = checked(root, relative)
            receipt = folder / "execution.json"
            if receipt.is_file():
                execution = read(receipt)
                reused += 1
            elif (folder / "started.json").exists():
                execution = None if manifest["software_fixture"] else _recover_complete_native_case(root, manifest, case_index)
                if execution is None:
                    stopped = "interrupted_final_case_preserved_without_resubmission"
                    break
                validate_execution(root, manifest, case_index, execution)
                save_once(receipt, execution)
                reused += 1
            elif retry_assessments:
                # An explicit external-assessment retry never starts a new model job.
                continue
            elif started >= max_cases:
                continue
            else:
                started += 1
                emit("Case " + str(case_index) + "/200 — running")
                save_once(folder / "started.json", {"manifest_id": manifest["manifest_id"], "case_index": case_index})
                try:
                    with redirect_stdout(io.StringIO()):
                        execution = (case_executor(root, manifest, case_index) if case_executor else
                            _native_case(root, manifest, case_index, software_evidence=software_evidence))
                    validate_execution(root, manifest, case_index, execution)
                    save_once(receipt, execution)
                except Exception as error:
                    save_once(folder / "stopped.json", {"manifest_id": manifest["manifest_id"],
                        "reason": type(error).__name__ + ": " + str(error), "automatic_resubmission": False})
                    stopped = "final_execution_needs_review"
                    # A raised executor may already have submitted work. Native
                    # counts come from its journal; fixture counts are unavailable.
                    if manifest["software_fixture"]:
                        new_calls = None
                    new_encodings = None
                    break
                new_calls += execution["new_model_submissions"]
                amount = execution.get("new_reference_encodings")
                new_encodings = None if new_encodings is None or amount is None else new_encodings + amount
            truth = validate_execution(root, manifest, case_index, execution)
            for row in execution["outcomes"]:
                planned = by_job[row["planned_job_id"]]
                if row.get("backend_completion_unresolved") is True or row["outcome"].get("status") == "unresolved":
                    observed = deepcopy(planned)
                    observed.update(execution_state="unresolved", metric_state="incomplete",
                        observed_attempt_sha256=sha(canonical(row["outcome"])),
                        designated_outcome_sha256=None, assessment_execution="not_run",
                        unresolved_backend_outcome=True)
                    by_job[row["planned_job_id"]] = observed
                    stopped = "unresolved_backend_outcome"
                    continue
                record = records[planned["profile_id"]]
                path = folder / ("assessment_" + str(row["planner_version"]) + ".json")
                if path.is_file():
                    attempts = [path, *sorted(folder.glob("assessment_" + str(row["planner_version"]) + "_retry_*.json"))]
                    current = planned
                    for attempt in attempts:
                        assessment = read(attempt)
                        current = ledger_api.record_assessment(current, row["outcome"], assessment)
                    if assessment.get("assessment_execution") == "error" and retry_assessments:
                        assessment = _assess_saved(assessor, record, row["outcome"], truth,
                            assessment_id=row["planned_job_id"], annotation=notes[planned["profile_id"]])
                        retry = folder / ("assessment_" + str(row["planner_version"]) + "_retry_" + str(len(attempts)).zfill(4) + ".json")
                        save_once(retry, assessment)
                        current = ledger_api.record_assessment(current, row["outcome"], assessment)
                    by_job[row["planned_job_id"]] = current
                else:
                    assessment = _assess_saved(assessor, record, row["outcome"], truth,
                        assessment_id=row["planned_job_id"], annotation=notes[planned["profile_id"]])
                    save_once(path, assessment)
                    by_job[row["planned_job_id"]] = ledger_api.record_assessment(planned, row["outcome"], assessment)
                if assessment.get("assessment_execution") != "completed":
                    stopped = "external_assessment_needs_review"
            if execution.get("stop_reason"):
                stopped = execution["stop_reason"]
            if len(execution["outcomes"]) == 4 and not stopped:
                completed += 1
            if stopped:
                break
        ledger = [by_job[row["job_id"]] for row in manifest["planned_jobs"]]
        if not manifest["software_fixture"]:
            new_calls = _native_submissions(root, manifest) - before_submissions
        counts = ledger_api.ledger_counts(ledger)
        summary = {"schema_version": VERSION, "manifest_id": manifest["manifest_id"],
            "status": "stopped_for_review" if stopped else "final_jobs_recorded" if completed == 200 else "next_batch_ready",
            "completed_cases": completed, "planned_cases": 200,
            "recorded_jobs": sum(row["execution_state"] in {"terminal", "unresolved"} for row in ledger), "planned_jobs": 800,
            "unresolved_jobs": sum(row["execution_state"] == "unresolved" for row in ledger),
            "assessed_jobs": sum(row["metric_state"] == "assessed" for row in ledger),
            "new_cases_attempted": started, "saved_cases_reused": reused,
            "assessment_only_retry": retry_assessments,
            "new_model_submissions": new_calls, "new_reference_encodings": new_encodings,
            "stop_reason": stopped, "counts": counts, "team_response_ratings_complete": False,
            "software_fixture": manifest["software_fixture"], "earlier_results_replaced": False}
        batch_id = uuid4().hex[:16]
        save_once(checked(root, manifest["package_directory"] + "/batches/" + batch_id + ".json"), summary)
        replace_progress(checked(root, manifest["package_directory"] + "/ledger_latest.jsonl"),
            b"".join(canonical(row) + b"\n" for row in ledger))
        replace_progress(checked(root, manifest["package_directory"] + "/progress_summary.json"), summary)
        emit("Cases complete: " + str(completed) + "/200 | Outcomes saved: " + str(summary["recorded_jobs"]) + "/800")
        emit("New model submissions: " + str(new_calls) + (" | Stopped: " + stopped if stopped else ""))
        return summary
