"""Confirm five candidate renders, then continue only the saved case-13 V4 draft."""

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid4


VERSION = "saved-case13-bounded-continuation-1"
PARENT = "results/step31_offline_corrections_summary.json"
SUMMARY = "results/step31_backend_continuation_summary.json"
POINTERS = {"production": "results/pilot/saved_continuation/selected_case13.json",
            "injected_test": "results/pilot/saved_continuation/injected_case13.json"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def checked(root, relative):
    path = (root / str(relative).replace("\\", "/")).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("A saved continuation source is unavailable: " + str(relative))
    return path


def module(root, name):
    relative = name if name.endswith(".py") else "src/champion_athletic_map/" + name + ".py"
    path = checked(root, relative)
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("saved_continuation_" + path.stem, path))
    result.__spec__.loader.exec_module(result)
    return result


def verify(root, bindings):
    for name, expected in bindings.items():
        if sha(checked(root, name).read_bytes()) != expected:
            raise ValueError("A frozen continuation source changed: " + name)


def save_once(path, value):
    data = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("An existing continuation record differs and was preserved: " + path.name)
    else:
        with path.open("xb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())


def _load_source(root):
    parent = read(checked(root, PARENT))
    if (parent.get("schema_version") != "saved-reviewed-probe-offline-corrections-1"
            or parent.get("candidate_only") is not True or parent.get("saved_outcomes_checked") != 16
            or parent.get("saved_revision_requests_checked") != 5
            or parent.get("candidate_revision_requests_fitting_locally") != 5
            or parent.get("new_model_calls") != 0 or parent.get("jobs_started") != 0
            or parent.get("software_evidence", {}).get("status") != "passed"
            or parent.get("software_evidence", {}).get("passed", 0) < 89):
        raise ValueError("The completed five-request Step 31-15 offline correction is required.")
    manifest_path = checked(root, parent["manifest_path"])
    candidate_manifest = read(manifest_path)
    fields = ("schema_version", "source_probe_id", "source_summary_sha256", "input_sha256", "component_sha256",
              "budget_policy", "candidate_only", "revision_omission", "entrypoints")
    if (sha(canonical({k: candidate_manifest[k] for k in fields})) != parent["manifest_id"]
            or candidate_manifest["manifest_id"] != parent["manifest_id"]
            or candidate_manifest["component_sha256"] != parent["component_sha256"]
            or candidate_manifest["input_sha256"] != parent["input_sha256"]):
        raise ValueError("The saved offline correction no longer matches its source manifest.")
    bindings = {**parent["input_sha256"], **parent["component_sha256"],
                manifest_path.relative_to(root).as_posix(): sha(manifest_path.read_bytes())}
    verify(root, bindings)
    source_api = module(root, "offline_corrections")
    probe_summary, rows, original_bindings = source_api.load_saved(root)
    bindings.update(original_bindings)
    counter, assets = module(root, "reviewed_preparation").pinned_counter(root)
    bindings.update(assets)
    rebuilt = source_api._revision_requests(root, rows, counter, module(root, "bounded_revision"), bindings)
    rebuilt_by_call = {row["call_id"]: row for row in rebuilt}
    selected = [r for r in rows if r["case_index"] == 13 and r["report"]["planner_version"] == 4]
    if len(selected) != 1:
        raise ValueError("The saved case-13 V4 outcome is unavailable.")
    selected = selected[0]
    old = selected["outcome"]
    blocked = [r["result"] for r in old.get("roles", []) if r["stage"] == "revision"]
    if (old.get("terminal_state") != "execution_error" or old.get("failed_stage") != "revision"
            or old.get("revisions_used") != 1 or len(blocked) != 1
            or blocked[0].get("context", {}).get("status") != "context_overflow"
            or len(old.get("history") or []) != 1 or old["history"][0]["candidate_id"] != "candidate_0"):
        raise ValueError("Only the saved, ungenerated case-13 first revision may continue.")
    event_path = selected["probe_folder"] / "http_events.jsonl"
    events = [json.loads(line) for line in event_path.read_bytes().splitlines()]
    starts = [e for e in events if e.get("event") == "http_started" and e.get("phase") == "generation"]
    terminal = {e["http_id"]: e for e in events if e.get("event") == "http_finished"}
    if (not starts or len(starts) + 4 > 15
            or any(e["http_id"] not in terminal or terminal[e["http_id"]].get("backend_done") is not True for e in starts)
            or any(e.get("unresolved") is True or e.get("event") == "http_exception" for e in events)
            or any(e.get("call_id") == blocked[0]["call_id"] for e in starts)):
        raise ValueError("The selected source has unresolved requests or lacks four remaining original-budget slots.")
    current = old["history"][0]
    evaluator = current["evaluator_result"]
    assessment = ((evaluator.get("response") or {}).get("model_output") or {}).get("parsed_object")
    if (not evaluator.get("completion_valid") or not evaluator.get("format_valid")
            or not isinstance(assessment, dict) or assessment.get("assessment_complete") is not True):
        raise ValueError("The original candidate must retain its completed evaluator assessment.")
    setups = []
    for path in (selected["probe_folder"] / "setup").glob("*.json"):
        value = read(path).get("runtime_manifest") or {}
        if value.get("public_input_sha256") == sha(canonical(selected["public"])):
            setups.append((path, value))
    if not setups or any(s[1]["effective_reference_policy"] != setups[0][1]["effective_reference_policy"] for s in setups):
        raise ValueError("The saved runtime's historical reference policy is unavailable or ambiguous.")
    setup_path, source_runtime = setups[0]
    bindings[setup_path.relative_to(root).as_posix()] = sha(setup_path.read_bytes())
    policy = source_runtime["effective_reference_policy"]
    if selected["packet"]["preparation"]["source_configuration_sha256"] != policy["source_configuration_sha256"]:
        raise ValueError("The historical packet and its saved preparation policy differ.")
    candidates = []
    for path in (root / "artifacts/pilot/shared_guidance").glob("*/probe_manifest.json"):
        value = read(path)
        if canonical(value.get("public_record")) != canonical(selected["public_record"]):
            continue
        config_path, schema_path = value.get("case_review_config_path"), value.get("public_schema_path")
        if config_path and schema_path and (root / config_path).is_file() and (root / schema_path).is_file():
            packed = lambda obj: (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
            config, schema = read(root / config_path), read(root / schema_path)
            if sha(packed(config)) == source_runtime["review_config_sha256"] and sha(packed(schema)) == source_runtime["public_schema_sha256"]:
                candidates.append((path, config_path, schema_path))
    if not candidates or len({(x[1], x[2]) for x in candidates}) != 1:
        raise ValueError("The original case manifest does not identify one unchanged schema/configuration pair.")
    source_manifest_path, config_path, schema_path = candidates[0]
    for path in (source_manifest_path, root / config_path, root / schema_path):
        bindings[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    backend = module(root, "backend_confirmation")
    bounded = module(root, "bounded_revision")
    requests, initial = [], None
    for index, row in enumerate(parent["revision_measurements"], 1):
        path, measurement_path = checked(root, row["candidate_request_path"]), checked(root, row["measurement_path"])
        request, measurement = read(path), read(measurement_path)
        expected = rebuilt_by_call.get(row["call_id"])
        if (expected is None or canonical(measurement) != canonical(expected)
                or canonical(request) != canonical(expected["new_candidate_request"])
                or any(row.get(key) != expected[key] for key in
                       ("case_index", "new_body_tokens", "new_input_tokens_including_boundary", "old_body_tokens"))):
            raise ValueError("A saved candidate request differs from its complete offline measurement.")
        rendered = bounded.recorded_render(request)
        entry = {"request_id": "saved_revision_" + str(index), "call_id": row["call_id"], "payload": request,
            "predicted_body_tokens": row["new_body_tokens"], "predicted_input_tokens": row["new_input_tokens_including_boundary"],
            "predicted_render_sha256": sha(rendered.encode("utf-8")), "source_path": path.relative_to(root).as_posix(),
            "source_sha256": sha(path.read_bytes())}
        requests.append(entry)
        for p in (path, measurement_path):
            bindings[p.relative_to(root).as_posix()] = sha(p.read_bytes())
        if row["case_index"] == 13:
            if initial is not None:
                raise ValueError("The source contains more than one case-13 first revision.")
            initial = measurement
    if len(requests) != 5 or initial is None:
        raise ValueError("All five measured requests and the selected first revision must be retained.")
    descriptors = backend.request_descriptors(requests)
    return {"parent": parent, "bindings": bindings, "observation_bindings": {PARENT: sha((root / PARENT).read_bytes())},
        "rows": rows, "selected": selected, "old": old, "current": current, "assessment": assessment,
        "source_runtime": source_runtime, "historical_reference_policy": policy,
        "requests": requests, "descriptors": descriptors, "initial": initial,
        "case_review_config_path": config_path, "public_schema_path": schema_path,
        "source_probe_id": probe_summary["probe_id"], "source_case_generation_submissions": len(starts)}


def manifest_path(manifest):
    return "artifacts/pilot/saved_continuation/" + manifest["continuation_id"] + "/manifest.json"


def prepare(root, *, execution_mode="production"):
    root = Path(root).resolve()
    if execution_mode not in POINTERS:
        raise ValueError("The continuation execution mode is invalid.")
    pointer = root / POINTERS[execution_mode]
    if pointer.exists():
        recorded = read(root / read(pointer)["manifest_path"])
        validate_manifest(root, recorded)
        return recorded
    source = _load_source(root)
    components = {"src/champion_athletic_map/" + name + ".py": sha((root / "src/champion_athletic_map" / (name + ".py")).read_bytes())
                  for name in ("saved_continuation", "backend_confirmation", "corrected_runtime", "pilot_trace",
                               "planners/evaluated_specialists")}
    identity = {"schema_version": VERSION, "execution_mode": execution_mode,
        "injected_test_dependencies": execution_mode == "injected_test",
        "source_correction_manifest_id": source["parent"]["manifest_id"], "source_probe_id": source["source_probe_id"],
        "source_bindings": source["bindings"], "component_sha256": components,
        "public_record": source["selected"]["public_record"], "reference_packet": source["selected"]["packet"],
        "historical_reference_policy": source["historical_reference_policy"],
        "case_review_config_path": source["case_review_config_path"], "public_schema_path": source["public_schema_path"],
        "backend_confirmation_requests": source["descriptors"], "maximum_generation_submissions": 4,
        "source_case_generation_submissions": source["source_case_generation_submissions"],
        "maximum_original_plus_amended_case_submissions": 15,
        "maximum_revision_ordinal": 2, "output_tokens": {"revision": 2048, "evaluator": 768},
        "first_revision_payload_canonical_sha256": sha(canonical(source["initial"]["new_candidate_request"])),
        "original_outcomes_replaced": False, "automatic_uncertain_retries": 0,
        "accepted_study_profiles": 0, "human_ratings_created": 0, "final_scores_created": False}
    digest = sha(canonical(identity))
    manifest = {**identity, "manifest_id": digest, "continuation_id": "saved_" + digest[:20],
                "call_prefix": "p31s_" + digest[:16], "source_observation_bindings": source["observation_bindings"]}
    save_once(root / manifest_path(manifest), manifest)
    save_once(pointer, {"manifest_id": digest, "manifest_path": manifest_path(manifest)})
    return manifest


def validate_manifest(root, manifest):
    identity = {k: v for k, v in manifest.items() if k not in ("manifest_id", "continuation_id", "call_prefix", "source_observation_bindings")}
    if (sha(canonical(identity)) != manifest["manifest_id"] or read(root / manifest_path(manifest)) != manifest
            or read(root / POINTERS[manifest["execution_mode"]]) != {"manifest_id": manifest["manifest_id"], "manifest_path": manifest_path(manifest)}):
        raise ValueError("The frozen saved continuation changed.")
    verify(root, {**manifest["source_bindings"], **manifest["component_sha256"]})
    try:
        verify(root, manifest["source_observation_bindings"])
    except ValueError:
        raise ValueError("The saved Step 31-15 observation changed; no new continuation or requests were started.") from None


def _rebind_historical_policy(runtime, manifest):
    """Keep historical packet preparation identity distinct from the new runtime."""
    engine = runtime.planners[4].planner
    nodes = [runtime.planners[v] for v in range(1, 5)] + [engine, engine.drafting]
    before, policy = deepcopy(runtime.manifest), deepcopy(manifest["historical_reference_policy"])
    if any(node.client.input_schema != engine.client.input_schema for node in nodes):
        raise ValueError("The continuation runtime public schema differs across nodes.")
    for node in nodes:
        node.config = deepcopy(node.config)
        if "reference_policy" in node.config:
            node.config["reference_policy"] = deepcopy(policy)
        if hasattr(node, "roles"):
            node.roles.reference_policy = deepcopy(policy)
    runtime.reference_policy = deepcopy(policy)
    identity_api = module(engine.root, "operational_runtime") if hasattr(engine, "root") else None
    stable_base = identity_api.identity_view(before) if identity_api is not None else before
    identity = {"runtime_version": VERSION, "constructed_corrected_runtime": stable_base,
        "historical_reference_policy": policy, "historical_packet_id": manifest["reference_packet"]["packet_id"],
        "historical_packet_sha256": sha(canonical(manifest["reference_packet"])),
        "continuation_manifest_id": manifest["manifest_id"]}
    runtime.manifest = {"runtime_version": VERSION, "continuation_runtime_identity": identity,
        "continuation_runtime_sha256": sha(canonical(identity)), "effective_reference_policy": policy,
        "base_corrected_runtime_manifest": before, "historical_reference_hash_relabelled_as_new_runtime": False,
        "budget_guards_changed": False, "input_or_reference_facts_changed": False}
    return engine


def _seal(root, folder, manifest):
    files = {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in folder.rglob("*")
             if p.is_file() and p.name != "completed.json"}
    native = root / "results/integration/model_calls"
    for base in native.glob(manifest["call_prefix"] + "*"):
        if base.is_dir():
            files.update({p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in base.rglob("*") if p.is_file()})
    save_once(folder / "completed.json", {"manifest_id": manifest["manifest_id"], "files": files})


def _quality(assessment):
    checks = {q["check_id"]: q["status"] for q in (assessment or {}).get("checks", [])}
    return {"overall": (assessment or {}).get("overall", "pending"),
        "sessions": checks.get("requested_session_count", "unknown"),
        "food_complete": checks.get("food_answer_completeness", "unknown"),
        "resources": checks.get("resource_requirements_evidence", "unknown")}


def _verified_terminal(summary, manifest):
    expected = ("revision1", "evaluator1", "revision2", "evaluator2")
    roles = summary.get("roles") or []
    if (summary.get("manifest_id") != manifest["manifest_id"]
            or summary.get("continuation_id") != manifest["continuation_id"] or len(roles) > 4
            or [r.get("stage") for r in roles] != list(expected[:len(roles)])
            or any(r["result"].get("call_id") != manifest["call_prefix"] + "_" + r["stage"] for r in roles)
            or summary.get("amended_model_submissions_total", 5) > 4
            or summary.get("original_plus_amended_model_submissions", 16) > 15
            or roles and summary.get("backend_requests_confirmed") != 5):
        raise ValueError("A terminal continuation has invalid role, request or manifest evidence.")


def _partial_confirmation_count(folder, manifest):
    expected = {d["request_id"]: d for d in manifest["backend_confirmation_requests"]}
    confirmed = set()
    for path in (folder / "backend_confirmation").glob("*/confirmed.json"):
        value = read(path)
        descriptor = expected.get(value.get("request_id"))
        if (descriptor and value.get("new_backend_render_confirmed") is True
                and value.get("payload_canonical_sha256") == descriptor["payload_canonical_sha256"]
                and value.get("rendered_prompt_sha256") == descriptor["predicted_render_sha256"]
                and value.get("local_input_tokens_with_boundary_reserve") == descriptor["predicted_input_tokens"]
                and value.get("generation_requests_submitted") == 0):
            confirmed.add(value["request_id"])
    return len(confirmed)


def execute(root, *, software_evidence=None, emit=print, runtime_factory=None,
            confirmation_api=None, trace_module=None, assessor_factory=None):
    root = Path(root).resolve()
    injected = any(value is not None for value in (runtime_factory, confirmation_api, trace_module, assessor_factory))
    evidence = deepcopy(software_evidence)
    if not isinstance(evidence, dict) or evidence.get("status") != "passed" or evidence.get("passed", 0) <= 0 or not evidence.get("files"):
        raise ValueError("The continuation software checks must pass first.")
    verify(root, evidence["files"])
    manifest = prepare(root, execution_mode="injected_test" if injected else "production")
    validate_manifest(root, manifest)
    folder = root / "results/pilot/saved_continuation" / manifest["continuation_id"]
    completed, outcome_path, stopped = folder / "completed.json", folder / "outcome.json", folder / "stopped.json"
    if completed.exists():
        receipt = read(completed)
        if receipt.get("manifest_id") != manifest["manifest_id"]:
            raise ValueError("The completed continuation belongs to another manifest.")
        verify(root, receipt["files"])
        summary = read(outcome_path)
        _verified_terminal(summary, manifest)
        return {**summary, "saved_execution_reused": True, "new_model_submissions": 0,
                "saved_roles_reused": len(summary.get("roles", [])), "new_backend_confirmation_renders": 0}
    if stopped.exists():
        stop = read(stopped)
        if (stop.get("manifest_id") != manifest["manifest_id"]
                or not outcome_path.is_file() or stop.get("outcome_sha256") != sha(outcome_path.read_bytes())):
            raise ValueError("The stopped continuation or its saved outcome changed; no requests were repeated.")
        summary = read(outcome_path)
        _verified_terminal(summary, manifest)
        return {**summary, "saved_execution_reused": True, "new_model_submissions": 0,
                "new_backend_confirmation_renders": 0}
    source = _load_source(root)
    trace_api = trace_module or module(root, "pilot_trace")
    trace = trace_api.PilotTrace(root, folder, manifest_id=manifest["manifest_id"], max_generation_submissions=4)
    trace.assert_safe()
    if outcome_path.exists():
        raise ValueError("A saved terminal outcome has no verified receipt; it was preserved without repeating requests.")
    before = trace.summary()
    engine_api = module(root, "src/champion_athletic_map/planners/evaluated_specialists.py")
    corrected = module(root, "corrected_runtime")
    factory, backend = runtime_factory or corrected.build_runtime, confirmation_api or module(root, "backend_confirmation")
    public, packet = manifest["public_record"], manifest["reference_packet"]
    current = source["current"]
    envelope = {"notes": deepcopy(source["initial"]["removed_generated_notes"]),
        "candidate": engine_api.candidate_view(current["candidate"], "candidate_0"),
        "check_results": engine_api.model_check_view(current["check_report"]),
        "evaluator_assessment": deepcopy(source["assessment"])}
    roles, history, final, acceptance = [], [], None, None
    confirmations, independent, failed_stage, error = None, None, "runtime_setup", None
    terminal_state, selected_id = "execution_error", None
    started = perf_counter()
    with trace_api.execution_gate(root, manifest["continuation_id"], manifest_sha256=manifest["manifest_id"], trace=trace):
        try:
            runtime = factory(root, read(root / manifest["case_review_config_path"]),
                              read(root / manifest["public_schema_path"]), public_record=deepcopy(public))
            engine = _rebind_historical_policy(runtime, manifest)
            stable = module(root, "operational_runtime").identity_view(runtime.manifest)
            save_once(folder / "runtime_manifest.json", stable)
            original_prepare = engine.roles.prepare_request
            first_pending = {"value": True}
            def guarded_prepare(*args, **kwargs):
                prepared, payload, config = original_prepare(*args, **kwargs)
                if kwargs.get("stage") == "revision" and first_pending["value"]:
                    if sha(canonical(payload)) != manifest["first_revision_payload_canonical_sha256"]:
                        raise ValueError("The first prepared revision differs from the saved corrected case-13 request.")
                return prepared, payload, config
            engine.roles.prepare_request = guarded_prepare
            role_kwargs = {"stage": "revision", "output_schema": None, "output_tokens": 2048,
                           "specialist_notes": envelope, "planner_version": 4}
            engine.roles.prepare_request(public, packet, engine.instructions + "\n\n" + engine.prompts["revision"], **role_kwargs)
            failed_stage = "backend_confirmation"
            emit("Confirming the five saved request sizes with the local backend…")
            confirmations = backend.confirm_requests(root, manifest, source["requests"], role=engine.roles, trace=trace,
                output_dir=folder / "backend_confirmation", emit=None)
            if (confirmations.get("all_five_confirmed") is not True
                    or confirmations.get("generation_requests_submitted", 0) != 0
                    or confirmations.get("generation_requests", 0) != 0):
                raise ValueError("All five backend confirmations must succeed before generation.")
            emit("Continuing the saved case-13 draft…")
            with trace.instrument(engine, manifest["continuation_id"], 4):
                for ordinal in (1, 2):
                    failed_stage = "revision" + str(ordinal)
                    revision = engine.roles.generate(public, packet, engine.instructions + "\n\n" + engine.prompts["revision"],
                        manifest["call_prefix"] + "_revision" + str(ordinal), stage="revision", output_schema=None,
                        output_tokens=2048, specialist_notes=envelope, planner_version=4)
                    roles.append({"stage": failed_stage, "result": revision})
                    first_pending["value"] = False
                    if not revision.get("completion_valid"):
                        raise ValueError(revision.get("error") or "The revised response did not complete.")
                    candidate_id = "candidate_" + str(ordinal)
                    failed_stage = "checker" + str(ordinal)
                    report = engine.checker.check(public, revision, packet, candidate_id=candidate_id)
                    if not engine_api._coverage(report, engine.policy):
                        raise ValueError(report.get("error") or "The complete required checker coverage is unavailable.")
                    evaluator_envelope = {"notes": deepcopy(source["initial"]["removed_generated_notes"]),
                        "candidate": engine_api.candidate_view(revision, candidate_id),
                        "check_results": engine_api.model_check_view(report)}
                    failed_stage = "evaluator" + str(ordinal)
                    evaluator = engine.roles.generate(public, packet, engine.instructions + "\n\n" + engine.prompts["evaluator"],
                        manifest["call_prefix"] + "_evaluator" + str(ordinal), stage="evaluator",
                        output_schema=engine.evaluator_schema, output_tokens=768,
                        specialist_notes=evaluator_envelope, planner_version=4)
                    roles.append({"stage": failed_stage, "result": evaluator})
                    if not evaluator.get("completion_valid") or not evaluator.get("format_valid"):
                        raise ValueError(evaluator.get("error") or "The evaluator did not complete and validate.")
                    assessment = evaluator["response"]["model_output"]["parsed_object"]
                    acceptance = engine_api.assess_acceptance(report, assessment, engine.policy)
                    history.append({"candidate_id": candidate_id, "candidate": revision, "check_report": report,
                                    "evaluator_result": evaluator, "acceptance": acceptance})
                    if not acceptance["evaluator_valid"]:
                        raise ValueError("The evaluator did not provide a complete assessment.")
                    if acceptance["accepted"] or ordinal == 2:
                        final, selected_id = revision, candidate_id
                        terminal_state = "internally_accepted" if acceptance["accepted"] else "revision_limit_reached"
                        failed_stage = None
                        break
                    envelope = {**evaluator_envelope, "evaluator_assessment": assessment}
        except Exception as failure:
            error = type(failure).__name__ + ": " + str(failure)
        uncertain = trace.is_uncertain() or any(r["result"].get("status") == "unresolved" for r in roles)
        after = trace.summary()
        if after["generation_transport_attempts"] > 4 or manifest["source_case_generation_submissions"] + after["generation_transport_attempts"] > 15:
            raise RuntimeError("The continuation exceeded its original case generation budget.")
        result = final or {"status": "unresolved" if uncertain else "failed", "completion_valid": False,
                           "format_valid": False, "response_type": None, "response": None, "error": error}
        if confirmations is not None and confirmations.get("all_five_confirmed") and not uncertain:
            try:
                assessor = (assessor_factory or corrected.make_assessor)(root, read(root / manifest["public_schema_path"]))
                independent = assessor.assess(public, result, packet, assessment_id=manifest["continuation_id"])
            except Exception as failure:
                independent = {"assessment_execution": "error", "error": type(failure).__name__ + ": " + str(failure)}
        summary = {"schema_version": VERSION, "manifest_id": manifest["manifest_id"], "continuation_id": manifest["continuation_id"],
            "source_probe_id": manifest["source_probe_id"], "source_correction_manifest_id": manifest["source_correction_manifest_id"],
            "backend_requests_confirmed": 5 if confirmations and confirmations.get("all_five_confirmed") else _partial_confirmation_count(folder, manifest),
            "total_render_candidates": 5, "backend_confirmation": confirmations,
            "new_backend_confirmation_renders": (confirmations or {}).get("new_render_requests", 0),
            "terminal_state": terminal_state, "result": result, "response_type": result.get("response_type"),
            "format_valid": result.get("format_valid") is True,
            "internal_review": "passed" if terminal_state == "internally_accepted" else "needs review" if final else "not completed",
            "selected_candidate_id": selected_id, "roles": roles, "history": history, "acceptance": acceptance,
            "amended_independent_assessment": independent, "quality": _quality(independent),
            "new_model_submissions": after["generation_transport_attempts"] - before["generation_transport_attempts"],
            "amended_model_submissions_total": after["generation_transport_attempts"],
            "original_case_model_submissions": manifest["source_case_generation_submissions"],
            "original_plus_amended_model_submissions": manifest["source_case_generation_submissions"] + after["generation_transport_attempts"],
            "saved_roles_reused": sum(r["result"].get("cached") is True for r in roles),
            "failed_stage": failed_stage, "error": error, "trace": after, "elapsed_seconds": perf_counter() - started,
            "saved_execution_reused": False, "injected_test_dependencies": injected,
            "original_results_changed": False, "earlier_drafts_returned_as_fallback": False,
            "new_reference_encodings": 0, "new_reference_tool_calls": 0, "old_draft_roles_submitted": 0,
            "backend_token_count_agreement_verified": False, "operational_generation_ready": False,
            "human_ratings_created": 0, "final_scores_created": False, "app_generation_enabled": False,
            "software_evidence": evidence}
        save_once(outcome_path, summary)
        if uncertain:
            save_once(stopped, {"manifest_id": manifest["manifest_id"], "outcome_sha256": sha(outcome_path.read_bytes()),
                "reason": "uncertain_backend_outcome_preserved_without_retry"})
        else:
            _seal(root, folder, manifest)
    target_name = SUMMARY if not injected else "results/pilot/saved_continuation/injected_test_summary.json"
    target = root / target_name
    data = canonical(summary) + b"\n"
    if not target.exists() or target.read_bytes() != data:
        temporary = target.with_name(target.name + ".tmp_" + uuid4().hex[:12])
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(data); os.replace(temporary, target)
    return summary
