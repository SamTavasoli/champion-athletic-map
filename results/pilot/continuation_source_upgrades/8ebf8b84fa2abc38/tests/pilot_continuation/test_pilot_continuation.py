"""Use synthetic saved supports and real trace safeguards for the amendment."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


def module(name):
    path = ROOT / "src/champion_athletic_map" / (name + ".py")
    spec = importlib.util.spec_from_file_location("continuation_test_" + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


continuation, tracing = module("pilot_continuation"), module("pilot_trace")
SOURCE_LOADER = continuation._source


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(continuation.canonical(value) + b"\n")


def report(candidate_id="candidate_1", status="unknown"):
    return {"execution_status": "completed", "candidate_id": candidate_id, "checks": [{
        "check_id": "retained_required_check", "candidate_id": candidate_id, "status": status,
        "required": True, "reason": "The independent resource evidence remains unresolved.", "observed": None}]}


def candidate():
    value = {"response_type": "plan", "explanation": "A synthetic saved development candidate."}
    return {"status": "returned", "completion_valid": True, "format_valid": True,
        "response_type": "plan", "response": {"model_output": {
            "parsed_object": value, "raw_text": json.dumps(value)}}}


class Leaf:
    def __init__(self, root, state):
        self.root, self.state = root, state

    def generate(self, *args, **kwargs):
        raise AssertionError("Only the two declared role methods may run.")

    def _http(self, endpoint, payload=None, timeout=8, raw_path=None):
        self.state["http"].append((endpoint, deepcopy(payload)))
        if self.state.get("timeout") and endpoint == "/api/chat" and not payload.get("_debug_render_only"):
            raise TimeoutError("A simulated generation outcome is uncertain.")
        result = {"done": True, "model": "offline-test-double", "message": {"content": "{}"}}
        if raw_path is not None:
            write(Path(raw_path), result)
        return result


class Roles:
    def __init__(self, root, state, client):
        self.root, self.state, self.client = root, state, client

    def _http(self, *args, **kwargs):
        return self.client._http(*args, **kwargs)

    def generate(self, public, packet, instructions, call_id, *, stage, specialist_notes, output_tokens, **kwargs):
        folder = self.root / "results/integration/model_calls" / call_id
        request = {"public": public, "packet": packet, "instructions": instructions,
            "stage": stage, "envelope": specialist_notes, "output_tokens": output_tokens}
        request_sha = continuation.sha(continuation.canonical(request))
        if (folder / "result.json").exists():
            result = json.loads((folder / "result.json").read_bytes())
            assert result["request_sha256"] == request_sha
            return {**result, "cached": True}
        self.state["roles"].append((stage, call_id, output_tokens, deepcopy(specialist_notes)))
        folder.mkdir(parents=True, exist_ok=False)
        write(folder / "request.json", {"request": request})
        active = folder.parent / "active_call"
        active.mkdir()
        write(active / "owner.json", {"call_id": call_id})
        try:
            self._http("/api/version")
            self._http("/api/chat", {**request, "_debug_render_only": True}, 60, folder / "render_response.json")
            self._http("/api/chat", request, 120, folder / "backend_response.json")
            result = candidate() if stage == "revision" else {"completion_valid": True, "format_valid": True,
                "response": {"model_output": {"parsed_object": {"assessment_complete": True, "issues": []}}}}
            result.update(status="returned", call_id=call_id, request_sha256=request_sha, cached=False, usage={"eval_count": 20})
            if self.state.get("weak_revision") and stage == "revision":
                result.update(status="failed", completion_valid=False, format_valid=False, error="The saved revision did not complete.")
        except TimeoutError as error:
            result = {"status": "unresolved", "completion_valid": False, "format_valid": False,
                "call_id": call_id, "request_sha256": request_sha, "error": str(error), "cached": False}
        write(folder / "result.json", result)
        if result["status"] != "unresolved":
            (active / "owner.json").unlink()
            active.rmdir()
        return result


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    # Discovery of the prior real run is replaced by explicit synthetic supports;
    # saved-evidence binding, model-role tracing and execution gates remain real.
    root, state = tmp_path, {"roles": [], "http": [], "runtime_builds": 0}
    for relative in ("src/champion_athletic_map/planners/evaluated_specialists.py", "src/champion_athletic_map/context_encoding.py"):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    for name in ("pilot_continuation", "pilot_trace"):
        destination = root / "src/champion_athletic_map" / (name + ".py")
        shutil.copyfile(Path(module(name).__file__), destination)
    api = continuation.module(root, "src/champion_athletic_map/planners/evaluated_specialists.py", "saved_envelope_functions")
    public = {"profile_id": "fictional-support", "schema_version": "athlete-profile-input-2", "input": {"age": 13}}
    packet = {"packet_id": "saved-test-packet", "payload": {"references": [], "food_lookup": []}}
    notes = [{"role": "training", "contribution": {"rationale": "Keep this entire saved contribution."}}]
    assessment = {"assessment_complete": True, "issues": [{"category": "scope", "problem": "A retained model concern."}]}
    current = {"candidate_id": "candidate_1", "candidate": candidate(), "check_report": report(),
        "evaluator_result": {"completion_valid": True, "format_valid": True}}
    folder = root / "results/pilot/probes/source-probe"
    folder.mkdir(parents=True)
    write(folder / "source_fixture.json", {"fixture_only": True})
    (folder / "stage_events.jsonl").write_bytes(b"")
    summary_path, setup_path = root / "results/step31_first_probe_summary.json", folder / "setup/original.json"
    setup = {"runtime_manifest": {"fixture_only": True, "effective_reference_policy": {"source": "unchanged"}}}
    write(summary_path, {"fixture_only": True})
    write(setup_path, setup)
    config_path, schema_path = "artifacts/test/config.json", "artifacts/test/schema.json"
    write(root / config_path, {"fixture_only": True})
    write(root / schema_path, {"type": "object"})
    manifest_path = "artifacts/test/source_manifest.json"
    write(root / manifest_path, {"fixture_only": True})
    pointer = {"manifest_path": manifest_path}
    write(root / "results/pilot/probes/first_operational_probe.json", pointer)
    bindings = {path: continuation.sha((root / path).read_bytes()) for path in (config_path, schema_path)}
    source = {"probe_id": "source-probe", "manifest_id": "source-identity", "public_record": public,
        "module_and_config_sha256": {}, "case_review_files": bindings,
        "case_review_config_path": config_path, "public_schema_path": schema_path}
    blocked_user = {"athlete_input": public["input"], "reference_data": packet["payload"], "specialist_notes": notes,
        "candidate": api.candidate_view(current["candidate"], "candidate_1"),
        "check_results": api.model_check_view(current["check_report"]), "evaluator_assessment": assessment}
    bundle = {"source": source, "folder": folder, "old": {"fixture_only": True}, "current": current,
        "notes": notes, "assessment": assessment, "reference": {"packet": packet},
        "blocked_request": {"messages": [{"content": "unchanged test system"}, {"content": json.dumps(blocked_user)}]},
        "source_setup": setup, "source_setup_path": setup_path, "summary_path": summary_path, "pointer": pointer}
    monkeypatch.setattr(continuation, "_source", lambda *args, **kwargs: bundle)
    manifest = continuation.prepare_continuation(root, component_paths=["src/champion_athletic_map/pilot_continuation.py"])
    def runtime_factory(project, config, schema):
        state["runtime_builds"] += 1
        client = Leaf(project, state)
        roles = Roles(project, state, client)
        policy = {"expected_check_ids": ["retained_required_check"], "required_check_ids": ["retained_required_check"],
            "blocking_evaluator_categories": ["scope"], "allowed_evaluator_categories": ["scope"]}
        checker = SimpleNamespace(check=lambda public, result, packet, candidate_id: report(candidate_id))
        engine = SimpleNamespace(instructions="Our unchanged task", prompts={"revision": "Revise.", "evaluator": "Review."},
            evaluator_schema={"type": "object"}, policy=policy)
        return SimpleNamespace(engine=engine, roles=roles, checker=checker, client=client, manifest={"fixture_only": True})
    def execute(factory=runtime_factory):
        return continuation.execute_continuation(root, manifest, runtime_factory=factory, trace_module=tracing, emit=lambda value: None)
    return SimpleNamespace(root=root, state=state, bundle=bundle, manifest=manifest, execute=execute)


def no_runtime(*args, **kwargs):
    raise AssertionError("A completed continuation must be reused without any runtime construction.")


def test_only_final_revision_and_evaluator_run_with_unchanged_saved_supports(prepared):
    result = prepared.execute()
    calls = prepared.state["roles"]
    assert [(stage, limit) for stage, _, limit, _ in calls] == [("revision", 2048), ("evaluator", 768)]
    assert all(call_id.startswith(prepared.manifest["call_prefix"]) for _, call_id, _, _ in calls)
    assert calls[0][3]["notes"] == prepared.bundle["notes"]
    assert calls[0][3]["evaluator_assessment"] == prepared.bundle["assessment"]
    assert result["new_generation_submissions_this_execution"] == result["amended_generation_submissions_total"] == 2
    assert result["original_plus_amended_generation_submissions"] == 15
    assert result["terminal_state"] == "revision_limit_reached" and not result["internally_accepted"]
    assert result["acceptance"]["blocking_check_ids"] == ["retained_required_check"]
    assert result["selected_candidate_id"] == "candidate_2" and result["new_reference_encoder_processes"] == 0
    assert result["new_reference_tool_calls"] == result["old_role_submissions"] == 0
    assert not result["protocol_frozen"] and result["independent_quality_assessment"] == "pending"


def test_completed_continuation_and_outcome_recovery_make_no_new_calls(prepared):
    prepared.execute()
    before = deepcopy(prepared.state)
    reused = prepared.execute(no_runtime)
    assert reused["saved_execution_reused"] and reused["new_generation_submissions_this_execution"] == 0
    folder = prepared.root / "results/pilot/continuations" / prepared.manifest["amendment_id"]
    (folder / "completed.json").unlink()
    recovered = prepared.execute(no_runtime)
    assert recovered["recovered_saved_outcome"] and prepared.state == before


def test_completed_weak_revision_is_retained_without_evaluator_or_retry(prepared):
    prepared.state["weak_revision"] = True
    result = prepared.execute()
    assert result["terminal_state"] == "execution_error" and result["selected_candidate_id"] is None
    assert result["failed_stage"] == "revision2" and len(prepared.state["roles"]) == 1
    assert not result["earlier_candidates_returned_as_fallback"]
    before = deepcopy(prepared.state)
    assert prepared.execute(no_runtime)["saved_execution_reused"] and prepared.state == before


def test_uncertain_revision_stops_and_preserves_shared_markers(prepared):
    prepared.state["timeout"] = True
    result = prepared.execute()
    assert result["result"]["status"] == "unresolved" and len(prepared.state["roles"]) == 1
    assert result["new_generation_submissions_this_execution"] == 1
    assert all((prepared.root / relative).exists() for relative in tracing._GATE_MARKERS)
    before = deepcopy(prepared.state)
    with pytest.raises(tracing.UncertainProbe):
        prepared.execute(no_runtime)
    assert prepared.state == before


@pytest.mark.parametrize("target", ["source", "component", "outcome"])
def test_changed_bound_source_component_or_completed_outcome_is_preserved(prepared, target):
    if target == "outcome":
        prepared.execute()
        path = prepared.root / "results/pilot/continuations" / prepared.manifest["amendment_id"] / "outcome.json"
    elif target == "source":
        path = prepared.root / next(iter(prepared.manifest["source_bindings"]))
    else:
        path = prepared.root / next(iter(prepared.manifest["amendment_component_sha256"]))
    path.write_bytes(path.read_bytes() + b" \n")
    changed, before = path.read_bytes(), deepcopy(prepared.state)
    with pytest.raises(ValueError, match="changed"):
        prepared.execute(no_runtime)
    assert path.read_bytes() == changed and prepared.state == before


def test_envelope_change_is_rejected_before_any_role_or_runtime(prepared):
    prepared.bundle["assessment"]["issues"].append({"category": "scope", "problem": "An undeclared change."})
    with pytest.raises(ValueError, match="envelope differs"):
        prepared.execute(no_runtime)
    assert not prepared.state["http"] and not prepared.state["roles"]


def test_preparation_reuses_same_identity_and_refuses_silent_component_amendment(prepared):
    paths = ["src/champion_athletic_map/pilot_continuation.py"]
    assert continuation.prepare_continuation(prepared.root, component_paths=paths) == prepared.manifest
    path = prepared.root / paths[0]
    path.write_bytes(path.read_bytes() + b"\n# Different explicit component version.\n")
    with pytest.raises(ValueError, match="amendment is already recorded"):
        continuation.prepare_continuation(prepared.root, component_paths=paths)


@pytest.fixture
def source_guard(prepared, monkeypatch):
    """Build explicit synthetic native/journal evidence for real source discovery."""
    root, bundle = prepared.root, prepared.bundle
    source = deepcopy(bundle["source"])
    jobs = [{"planner_version": version, "job_id": "source_v" + str(version)} for version in range(1, 5)]
    identity = {key: value for key, value in source.items() if key not in
        {"probe_id", "manifest_id", "case_review_config_path", "public_schema_path", "jobs"}}
    source["manifest_id"] = continuation.sha(continuation.canonical(identity))
    source["jobs"] = jobs
    pointer = {"manifest_id": source["manifest_id"], "manifest_path": bundle["pointer"]["manifest_path"]}
    write(root / "results/pilot/probes/first_operational_probe.json", pointer)
    write(root / pointer["manifest_path"], source)
    write(bundle["summary_path"], {"manifest_id": source["manifest_id"], "setup_this_execution": bundle["source_setup"]})
    stages, http = [], []
    folder = bundle["folder"]
    def windows(path):
        return path.relative_to(root).as_posix().replace("/", "\\")
    def add_role(call_id, result, generation):
        native = root / "results/integration/model_calls" / call_id / "result.json"
        snapshot = folder / "stage_results" / (call_id + ".json")
        write(native, result)
        write(snapshot, result)
        stages.append({"event": "stage_finished", "call_id": call_id,
            "result_snapshot": windows(snapshot), "result_snapshot_sha256": continuation.sha(snapshot.read_bytes()),
            "saved_result_sha256": continuation.sha(native.read_bytes()), "unresolved": False})
        http_id = "http_" + call_id
        request_path, raw_path = folder / "http_requests" / (http_id + ".json"), folder / "http_responses" / (http_id + ".json")
        request = {"fixture_only": True} if generation else bundle["blocked_request"]
        write(request_path, request)
        write(raw_path, {"done": True} if generation else {"_debug_info": {"rendered_template": "synthetic render"}})
        common = {"call_id": call_id, "http_id": http_id, "phase": "generation" if generation else "render",
            "request_path": windows(request_path), "request_sha256": continuation.sha(request_path.read_bytes()),
            "raw_path": windows(raw_path)}
        http.extend([{**common, "event": "http_started"}, {**common, "event": "http_finished",
            "backend_done": generation, "raw_response_sha256": continuation.sha(raw_path.read_bytes())}])
    for index in range(13):
        add_role("source_generated_" + str(index), {"status": "returned", "fixture_only": True}, True)
    blocked_id = "source_v4_revision2"
    failed = {"call_id": blocked_id, "status": "failed", "completion_valid": False,
        "context": {"status": "context_overflow", "output_reserve": 2048, "configured_context_tokens": 8192,
            "local_input_tokens_with_boundary_reserve": 5986, "input_ceiling_after_output_and_margin": 5888}}
    add_role(blocked_id, failed, False)
    write_lines = lambda path, rows: path.write_bytes(b"".join(continuation.canonical(row) + b"\n" for row in rows))
    write_lines(folder / "stage_events.jsonl", stages)
    write_lines(folder / "http_events.jsonl", http)
    current = deepcopy(bundle["current"])
    current["evaluator_result"]["response"] = {"model_output": {"parsed_object": bundle["assessment"]}}
    old = {"failed_stage": "revision", "terminal_state": "execution_error", "revisions_used": 2,
        "roles": [{"stage": "revision", "result": failed}],
        "history": [{"candidate_id": "candidate_0"}, current], "draft_result": {"specialist_notes": bundle["notes"]}}
    calls = []
    def verify_job(project, manifest, job, work, record):
        calls.append(job["planner_version"])
        return old if job["planner_version"] == 4 else {"status": "returned", "fixture_only": True}
    for job in jobs:
        write(folder / "jobs" / job["job_id"] / "job_record.json", {"fixture_only": True})
    previous = continuation.module
    def load(project, relative, name):
        if relative == "src/champion_athletic_map/pilot_probe.py":
            return SimpleNamespace(verify_job=verify_job, saved_references=lambda *args: bundle["reference"])
        return previous(project, relative, name)
    monkeypatch.setattr(continuation, "module", load)
    monkeypatch.setattr(continuation, "_source", SOURCE_LOADER)
    return SimpleNamespace(root=root, bundle=bundle, folder=folder, http=http, stages=stages,
        old=old, calls=calls, blocked_id=blocked_id, write_lines=write_lines)


def test_source_loader_accepts_exact_conclusive_supports_and_windows_paths(source_guard):
    loaded = continuation._source(source_guard.root)
    assert loaded["source_generation_submissions"] == 13
    assert loaded["blocked_request"] == source_guard.bundle["blocked_request"]
    assert loaded["notes"] == source_guard.bundle["notes"]
    assert source_guard.calls == [1, 2, 3, 4]
    assert loaded["source_setup_path"] == source_guard.bundle["source_setup_path"]


@pytest.mark.parametrize("change", ["generation_already_submitted", "native", "snapshot", "unresolved", "request", "raw_response", "missing_http_terminal"])
def test_source_loader_rejects_changed_or_uncertain_prior_attempts(source_guard, change):
    item, root = source_guard, source_guard.root
    if change == "generation_already_submitted":
        start = deepcopy(next(row for row in item.http if row["event"] == "http_started"))
        start.update(call_id=item.blocked_id, http_id="unexpected_generation")
        item.http.append(start)
        item.write_lines(item.folder / "http_events.jsonl", item.http)
    elif change == "unresolved":
        item.http[0]["unresolved"] = True
        item.write_lines(item.folder / "http_events.jsonl", item.http)
    elif change == "missing_http_terminal":
        # Drop a render terminal while preserving all thirteen completed generations.
        item.http = [row for row in item.http if not (row["event"] == "http_finished" and row["call_id"] == item.blocked_id)]
        item.write_lines(item.folder / "http_events.jsonl", item.http)
    else:
        if change == "native":
            path = root / "results/integration/model_calls/source_generated_0/result.json"
        elif change == "snapshot":
            path = continuation.project_path(root, item.stages[0]["result_snapshot"])
        elif change == "request":
            path = continuation.project_path(root, item.http[0]["request_path"])
        else:
            path = continuation.project_path(root, item.http[1]["raw_path"])
        path.write_bytes(path.read_bytes() + b" \n")
        changed = path.read_bytes()
    with pytest.raises(ValueError):
        continuation._source(root)
    if change in {"native", "snapshot", "request", "raw_response"}:
        assert path.read_bytes() == changed


pytestmark = pytest.mark.requirement("31:bounded-final-revision-continuation")
