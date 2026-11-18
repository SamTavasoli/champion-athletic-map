"""Continue only the final render-blocked revision under an explicit amendment."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from time import perf_counter


VERSION = "step31-blocked-revision-continuation-1"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def project_path(root, relative):
    path = (root / str(relative).replace("\\", "/")).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Continuation evidence must remain inside the project.")
    return path


def module(root, relative, name):
    path = project_path(root, relative)
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    result.__spec__.loader.exec_module(result)
    return result


def save_once(path, value):
    import os
    data = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Existing continuation evidence differs and was preserved: " + path.name)
        return
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def verify_bindings(root, bindings):
    for relative, expected in bindings.items():
        path = project_path(root, relative)
        if not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError("A continuation source changed: " + relative)


def check_table_rows(table):
    """Compare complete named rows independently of their column layout."""
    if not isinstance(table, dict):
        raise ValueError("A saved check table must be an object.")
    columns, findings = table.get("columns"), table.get("findings")
    if (type(columns) is not list or not columns or any(type(key) is not str for key in columns)
            or len(set(columns)) != len(columns) or type(findings) is not list or not findings
            or any(type(row) is not list or len(row) != len(columns) for row in findings)):
        raise ValueError("A saved check table has invalid columns or row widths.")
    return {"fields": {key: deepcopy(value) for key, value in table.items() if key not in ("columns", "findings")},
        "rows": [dict(zip(columns, deepcopy(row))) for row in findings]}


def verify_saved_envelope(original_user, view, public, packet, candidate_codec):
    expected = {"athlete_input": public["input"], "reference_data": packet["payload"],
        "specialist_notes": view["notes"], "candidate": view["candidate"],
        "check_results": view["check_results"], "evaluator_assessment": view["evaluator_assessment"]}
    if type(original_user) is not dict or set(original_user) != set(expected):
        raise ValueError("The continuation envelope differs from the original blocked revision.")
    actual, wanted = deepcopy(original_user), deepcopy(expected)
    actual["candidate"] = candidate_codec.decode_candidate(actual["candidate"])
    actual["check_results"] = check_table_rows(actual["check_results"])
    wanted["check_results"] = check_table_rows(wanted["check_results"])
    if canonical(actual) != canonical(wanted):
        raise ValueError("The continuation envelope differs from the original blocked revision.")
    # Preserve the exact original model-facing table after proving named-row equality.
    restored = deepcopy(view)
    restored["check_results"] = deepcopy(original_user["check_results"])
    return restored


def _source(root, source_probe_id=None):
    pointer = read(root / "results/pilot/probes/first_operational_probe.json")
    source = read(project_path(root, pointer["manifest_path"]))
    if source_probe_id is not None and source["probe_id"] != source_probe_id:
        raise ValueError("The requested source probe differs from the recorded first probe.")
    if pointer["manifest_id"] != source["manifest_id"]:
        raise ValueError("The source probe identity differs from its pointer.")
    identity = {key: value for key, value in source.items() if key not in
        {"probe_id", "manifest_id", "case_review_config_path", "public_schema_path", "jobs"}}
    if sha(canonical(identity)) != source["manifest_id"]:
        raise ValueError("The source probe manifest identity changed.")
    verify_bindings(root, source["module_and_config_sha256"])
    verify_bindings(root, source["case_review_files"])
    probe = module(root, "src/champion_athletic_map/pilot_probe.py", "continuation_original_probe")
    folder = root / "results/pilot/probes" / source["probe_id"]
    outcomes = {}
    for job in source["jobs"]:
        work = folder / "jobs" / job["job_id"]
        outcomes[job["planner_version"]] = probe.verify_job(root, source, job, work, read(work / "job_record.json"))
    if set(outcomes) != {1, 2, 3, 4}:
        raise ValueError("The source probe must retain all four matched outcomes.")
    http = [json.loads(line) for line in (folder / "http_events.jsonl").read_bytes().splitlines()]
    stages = [json.loads(line) for line in (folder / "stage_events.jsonl").read_bytes().splitlines()]
    starts = [row for row in http if row["event"] == "http_started" and row["phase"] == "generation"]
    finished = {row["http_id"]: row for row in http if row["event"] == "http_finished"}
    completed_roles = {row["call_id"]: row for row in stages if row["event"] == "stage_finished"}
    if (len(starts) != 13 or len({row["call_id"] for row in starts}) != 13
            or any(row.get("unresolved") or row["event"] == "http_exception" for row in http + stages)
            or any(row["http_id"] not in finished or finished[row["http_id"]].get("backend_done") is not True
                   or row["call_id"] not in completed_roles for row in starts)):
        raise ValueError("The source must contain exactly thirteen conclusive generations and no unresolved request.")
    for event in http:
        if event["event"] == "http_started":
            path = project_path(root, event["request_path"])
            if sha(path.read_bytes()) != event["request_sha256"]:
                raise ValueError("A saved source HTTP request differs from its journal hash.")
            terminal = finished.get(event["http_id"])
            if terminal is None:
                raise ValueError("A source HTTP attempt has no conclusive terminal record.")
            if terminal.get("raw_response_sha256") is not None:
                raw_path = project_path(root, terminal["raw_path"])
                if not raw_path.is_file() or sha(raw_path.read_bytes()) != terminal["raw_response_sha256"]:
                    raise ValueError("A saved source HTTP response differs from its journal hash.")
    for event in stages:
        if event["event"] != "stage_finished":
            continue
        snapshot = project_path(root, event["result_snapshot"])
        if sha(snapshot.read_bytes()) != event["result_snapshot_sha256"]:
            raise ValueError("A source role snapshot changed.")
        native = root / "results/integration/model_calls" / event["call_id"] / "result.json"
        if not native.is_file() or sha(native.read_bytes()) != event["saved_result_sha256"]:
            raise ValueError("A native source role result is missing or differs from its recorded snapshot.")
        if read(native).get("status") == "unresolved":
            raise ValueError("A native source role remains unresolved.")
    old = outcomes[4]
    failed = [row["result"] for row in old["roles"] if row["stage"] == "revision"][-1]
    budget = failed.get("context") or {}
    blocked_id = failed.get("call_id")
    blocked_http = [row for row in http if row.get("call_id") == blocked_id and row["event"] == "http_started"]
    renders = [row for row in blocked_http if row["phase"] == "render"]
    if (old.get("failed_stage") != "revision" or old.get("terminal_state") != "execution_error"
            or old.get("revisions_used") != 2 or failed.get("status") != "failed"
            or failed.get("completion_valid") is not False or not str(blocked_id).endswith("_revision2")
            or budget.get("status") != "context_overflow" or budget.get("output_reserve") != 2048
            or budget.get("configured_context_tokens") != 8192
            or budget.get("local_input_tokens_with_boundary_reserve") != 5986
            or budget.get("input_ceiling_after_output_and_margin") != 5888
            or len(renders) != 1 or any(row["phase"] == "generation" for row in blocked_http)):
        raise ValueError("Only the recorded, ungenerated final revision with its original budget may continue.")
    history = old["history"]
    if len(history) != 2 or history[-1]["candidate_id"] != "candidate_1":
        raise ValueError("The saved current candidate history differs from this amendment's scope.")
    current = history[-1]
    evaluator = current["evaluator_result"]
    assessment = evaluator["response"]["model_output"]["parsed_object"]
    if not evaluator.get("completion_valid") or not evaluator.get("format_valid") or assessment.get("assessment_complete") is not True:
        raise ValueError("The preceding evaluator must retain a completed valid assessment.")
    reference_work = folder / "references" / next(job["job_id"] for job in source["jobs"] if job["planner_version"] == 4)
    reference = probe.saved_references(root, reference_work, source)
    if reference is None:
        raise ValueError("The exact original Version 4 reference packet is required.")
    summary_path = root / "results/step31_first_probe_summary.json"
    summary = read(summary_path)
    if summary.get("manifest_id") != source["manifest_id"]:
        raise ValueError("The source summary belongs to another probe.")
    setup = summary.get("setup_this_execution") or {}
    setup_path = None
    if not setup.get("runtime_manifest"):
        for candidate in sorted((folder / "setup").glob("*.json")):
            value = read(candidate)
            if value.get("runtime_manifest"):
                setup, setup_path = value, candidate
                break
    else:
        for candidate in sorted((folder / "setup").glob("*.json")):
            if read(candidate) == setup:
                setup_path = candidate
                break
    if not setup.get("runtime_manifest") or setup_path is None:
        raise ValueError("The exact original runtime setup and its effective reference policy are required.")
    return {"source": source, "folder": folder, "old": old, "current": current,
        "notes": old["draft_result"]["specialist_notes"], "assessment": assessment,
        "reference": reference, "blocked_request": read(project_path(root, renders[0]["request_path"])),
        "source_setup": setup, "source_setup_path": setup_path, "summary_path": summary_path,
        "pointer": pointer, "source_generation_submissions": 13}


def prepare_continuation(root, *, component_paths, source_probe_id=None):
    root = Path(root).resolve()
    bundle = _source(root, source_probe_id)
    source, folder = bundle["source"], bundle["folder"]
    paths = [p for p in folder.rglob("*") if p.is_file()]
    paths += [bundle["summary_path"], bundle["source_setup_path"],
        root / "results/pilot/probes/first_operational_probe.json", project_path(root, bundle["pointer"]["manifest_path"])]
    for event in [json.loads(line) for line in (folder / "stage_events.jsonl").read_bytes().splitlines()]:
        if event["event"] == "stage_finished":
            native = root / "results/integration/model_calls" / event["call_id"]
            paths.extend(p for p in native.rglob("*") if p.is_file())
    bindings = {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in paths}
    bindings.update(source["module_and_config_sha256"])
    bindings.update(source["case_review_files"])
    components = {relative: sha(project_path(root, relative).read_bytes()) for relative in component_paths}
    if not components:
        raise ValueError("Record the continuation and lossless-adapter sources before running.")
    identity = {"schema_version": VERSION, "source_probe_id": source["probe_id"],
        "source_manifest_id": source["manifest_id"], "source_bindings": bindings,
        "amendment_component_sha256": components, "source_generation_submissions": 13,
        "source_setup": bundle["source_setup"], "source_setup_path": bundle["source_setup_path"].relative_to(root).as_posix(),
        "case_review_config_path": source["case_review_config_path"], "public_schema_path": source["public_schema_path"],
        "public_record": source["public_record"], "reference_packet_id": bundle["reference"]["packet"]["packet_id"],
        "scope": "lossless-check-result-encoding; continue only blocked revision2 then evaluator2",
        "maximum_new_generation_submissions": 2, "maximum_total_original_and_amended_submissions": 15,
        "original_context_tokens": 8192, "revision_output_tokens": 2048, "evaluator_output_tokens": 768,
        "maximum_revision_ordinal": 2, "independent_quality_assessment": "pending", "protocol_frozen": False}
    digest = sha(canonical(identity))
    manifest = {**identity, "manifest_id": digest, "amendment_id": "continuation_" + digest[:20],
        "call_prefix": "p31c_" + digest[:16]}
    pointer = root / "results/pilot/continuations/blocked_revision2_amendment.json"
    if pointer.exists() and read(pointer).get("manifest_id") != digest:
        raise ValueError("An amendment is already recorded; preserve it before proposing another configuration.")
    path = root / "artifacts/pilot/continuations" / manifest["amendment_id"] / "manifest.json"
    save_once(path, manifest)
    save_once(pointer, {"manifest_id": digest, "manifest_path": path.relative_to(root).as_posix()})
    return manifest


def execute_continuation(root, manifest, *, runtime_factory, trace_module=None, emit=print, clock=perf_counter):
    root = Path(root).resolve()
    identity = {key: value for key, value in manifest.items() if key not in {"manifest_id", "amendment_id", "call_prefix"}}
    if sha(canonical(identity)) != manifest["manifest_id"]:
        raise ValueError("The continuation manifest identity changed.")
    verify_bindings(root, manifest["source_bindings"])
    verify_bindings(root, manifest["amendment_component_sha256"])
    bundle = _source(root, manifest["source_probe_id"])
    trace_api = trace_module or module(root, "src/champion_athletic_map/pilot_trace.py", "continuation_trace")
    folder = root / "results/pilot/continuations" / manifest["amendment_id"]
    trace = trace_api.PilotTrace(root, folder, manifest_id=manifest["manifest_id"], max_generation_submissions=2)
    trace.assert_safe()
    before = trace.summary()
    outcome_path, completed = folder / "outcome.json", folder / "completed.json"
    if completed.is_file():
        record = read(completed)
        if record.get("manifest_id") != manifest["manifest_id"] or record.get("outcome_sha256") != sha(outcome_path.read_bytes()):
            raise ValueError("The completed continuation outcome changed.")
        summary = read(outcome_path)
        return {**summary, "saved_execution_reused": True, "new_generation_submissions_this_execution": 0}
    recovered = outcome_path.is_file()
    if recovered:
        summary = read(outcome_path)
        if summary.get("manifest_id") != manifest["manifest_id"]:
            raise ValueError("The saved continuation outcome belongs to another amendment.")
        save_once(completed, {"manifest_id": manifest["manifest_id"], "outcome_sha256": sha(outcome_path.read_bytes())})
        return {**summary, "saved_execution_reused": True, "recovered_saved_outcome": True,
            "new_generation_submissions_this_execution": 0}
    engine_api = module(root, "src/champion_athletic_map/planners/evaluated_specialists.py", "continuation_acceptance")
    candidate_codec = module(root, "src/champion_athletic_map/context_encoding.py", "continuation_original_calendar_codec")
    public, packet = manifest["public_record"], bundle["reference"]["packet"]
    view = {"notes": deepcopy(bundle["notes"]), "candidate": engine_api.candidate_view(bundle["current"]["candidate"], "candidate_1"),
        "check_results": engine_api.model_check_view(bundle["current"]["check_report"]),
        "evaluator_assessment": deepcopy(bundle["assessment"])}
    original_user = json.loads(bundle["blocked_request"]["messages"][1]["content"])
    view = verify_saved_envelope(original_user, view, public, packet, candidate_codec)
    interrupted = (folder / "attempt_started.json").exists()
    save_once(folder / "attempt_started.json", {"manifest_id": manifest["manifest_id"]})
    started = clock()
    roles, report, acceptance, final = [], None, None, None
    state, failed_stage, error = "execution_error", None, None
    with trace_api.execution_gate(root, manifest["amendment_id"], manifest_sha256=manifest["manifest_id"], trace=trace):
        runtime = runtime_factory(root, read(project_path(root, manifest["case_review_config_path"])),
            read(project_path(root, manifest["public_schema_path"])))
        engine = runtime.engine
        save_once(folder / "runtime_manifest.json", runtime.manifest)
        with trace.instrument(runtime, manifest["amendment_id"], 4):
            try:
                failed_stage = "revision2"
                revision = runtime.roles.generate(public, packet, engine.instructions + "\n\n" + engine.prompts["revision"],
                    manifest["call_prefix"] + "_revision2", stage="revision", output_schema=None, output_tokens=2048,
                    specialist_notes=view, planner_version=4)
                roles.append({"stage": "revision2", "result": revision})
                if not revision.get("completion_valid"):
                    raise ValueError(revision.get("error") or "The amended final revision did not complete.")
                failed_stage = "checker"
                report = runtime.checker.check(public, revision, packet, candidate_id="candidate_2")
                if not engine_api._coverage(report, engine.policy):
                    raise ValueError(report.get("error") or "The complete original coded coverage did not pass its execution gate.")
                envelope = {"notes": deepcopy(bundle["notes"]), "candidate": engine_api.candidate_view(revision, "candidate_2"),
                    "check_results": engine_api.model_check_view(report)}
                failed_stage = "evaluator2"
                evaluator = runtime.roles.generate(public, packet, engine.instructions + "\n\n" + engine.prompts["evaluator"],
                    manifest["call_prefix"] + "_evaluator2", stage="evaluator", output_schema=engine.evaluator_schema,
                    output_tokens=768, specialist_notes=envelope, planner_version=4)
                roles.append({"stage": "evaluator2", "result": evaluator})
                if not evaluator.get("completion_valid") or not evaluator.get("format_valid"):
                    raise ValueError(evaluator.get("error") or "The final evaluator did not complete and validate.")
                assessment = evaluator["response"]["model_output"]["parsed_object"]
                acceptance = engine_api.assess_acceptance(report, assessment, engine.policy)
                if not acceptance["evaluator_valid"]:
                    raise ValueError("The final assessment is incomplete under the original policy.")
                final = revision
                state = "internally_accepted" if acceptance["accepted"] else "revision_limit_reached"
                failed_stage = None
            except Exception as failure:
                error = type(failure).__name__ + ": " + str(failure)
        uncertain = trace.is_uncertain() or any(row["result"].get("status") == "unresolved" for row in roles)
        after = trace.summary()
        if after["generation_transport_attempts"] > 2:
            raise RuntimeError("The amended continuation exceeded its two-request limit.")
        result = final or {"status": "unresolved" if uncertain else "failed", "completion_valid": False,
            "format_valid": False, "response_type": None, "response": None, "error": error}
        summary = {"schema_version": VERSION, "manifest_id": manifest["manifest_id"], "amendment_id": manifest["amendment_id"],
            "source_probe_id": manifest["source_probe_id"], "source_manifest_id": manifest["source_manifest_id"],
            "source_generation_submissions": 13, "new_generation_submissions_this_execution":
                after["generation_transport_attempts"] - before["generation_transport_attempts"],
            "amended_generation_submissions_total": after["generation_transport_attempts"],
            "original_plus_amended_generation_submissions": 13 + after["generation_transport_attempts"],
            "terminal_state": state, "result": result, "selected_candidate_id": "candidate_2" if final else None,
            "internally_accepted": state == "internally_accepted", "maximum_revision_ordinal": 2,
            "failed_stage": failed_stage, "error": error, "roles": roles, "check_report": report, "acceptance": acceptance,
            "trace": after, "elapsed_seconds": None if interrupted else clock() - started,
            "observed_current_segment_seconds": clock() - started, "timing_scope": "separate amended continuation segment; original probe timings unchanged",
            "interrupted_prior_attempt": interrupted, "saved_execution_reused": False,
            "source_results_changed": False, "earlier_candidates_returned_as_fallback": False,
            "new_reference_encoder_processes": 0, "new_reference_tool_calls": 0, "old_role_submissions": 0,
            "independent_quality_assessment": "pending", "representative_pilot_completed": False,
            "accepted_study_profiles": 0, "protocol_frozen": False, "operational_generation_ready": False}
        save_once(outcome_path, summary)
        save_once(completed, {"manifest_id": manifest["manifest_id"], "outcome_sha256": sha(outcome_path.read_bytes())})
    emit("Planner 4: " + str(summary["terminal_state"]) + " | New model submissions: " + str(summary["new_generation_submissions_this_execution"]))
    return summary
