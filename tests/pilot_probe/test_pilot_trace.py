"""Exercise durable counting, actual leaf wrapping and uncertain-request holds."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT = Path(__file__).resolve().parents[2]
PATH = PROJECT / "src/champion_athletic_map/pilot_trace.py"
spec = importlib.util.spec_from_file_location("pilot_trace_under_test", PATH)
trace_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace_module)
PilotTrace, ProbeBlocked, UncertainProbe = trace_module.PilotTrace, trace_module.ProbeBlocked, trace_module.UncertainProbe


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def run_role(owner, payload, call_id, stage):
    """Small saved transport double; all HTTP activity remains inside this test."""
    folder = owner.root / "results/integration/model_calls" / call_id
    request_sha = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if (folder / "result.json").is_file():
        saved = json.loads((folder / "result.json").read_bytes())
        if saved["request_sha256"] != request_sha:
            raise ValueError("Call ID already belongs to a different request")
        return {**saved, "cached": True}
    folder.mkdir(parents=True)
    write(folder / "request.json", {"request": payload})
    active = folder.parent / "active_call"
    active.mkdir()
    write(active / "owner.json", {"call_id": call_id})
    try:
        owner._http("/api/version")
        owner._http("/api/show", {"model": "test-model"})
        owner._http("/api/chat", {**payload, "_debug_render_only": True}, 60, folder / "render_response.json")
        owner._http("/api/chat", payload, 120, folder / "backend_response.json")
        result = {"status": owner.client.final_status if hasattr(owner, "client") else owner.final_status,
            "call_id": call_id, "request_sha256": request_sha, "stage": stage,
            "completion_valid": True, "format_valid": True, "cached": False,
            "usage": {"prompt_eval_count": 100, "eval_count": 20}}
    except TimeoutError:
        result = {"status": "unresolved", "call_id": call_id, "request_sha256": request_sha,
            "completion_valid": False, "format_valid": False, "cached": False, "usage": {}}
    write(folder / "result.json", result)
    if result["status"] != "unresolved":
        (active / "owner.json").unlink()
        active.rmdir()
    return result


class FakeClient:
    def __init__(self, root):
        self.root, self.calls = root, []
        self.final_status, self.timeout_generation = "returned", False

    def _http(self, endpoint, payload=None, timeout=8, raw_path=None):
        self.calls.append((endpoint, payload, timeout, raw_path))
        if self.timeout_generation and endpoint == "/api/chat" and not payload.get("_debug_render_only"):
            raise TimeoutError("Simulated accepted generation timeout")
        value = {"done": True, "model": "test-model", "version": "test", "message": {"content": "{}"}}
        if raw_path is not None:
            write(Path(raw_path), value)
        return value

    def generate(self, public, instructions, call_id, **kwargs):
        return run_role(self, {"model": "test-model", "messages": [public, instructions]}, call_id, "final")


class FakeRoles:
    def __init__(self, client):
        self.client, self.root = client, client.root

    def _http(self, *args, **kwargs):
        return self.client._http(*args, **kwargs)

    def generate(self, public, packet, instructions, call_id, *, stage, **kwargs):
        return run_role(self, {"model": "test-model", "messages": [public, packet, instructions]}, call_id, stage)


def trace(root, **kwargs):
    return PilotTrace(root, "results/pilot/probe/trace", manifest_id="manifest-1", **kwargs)


def test_leaf_requests_and_raw_metadata_are_recorded_without_changing_payloads(tmp_path):
    client, journal = FakeClient(tmp_path), trace(tmp_path)
    original = client._http
    with journal.instrument(SimpleNamespace(client=client), "job_v1", 1):
        result = client.generate({"athlete_input": {"age": 13}}, "Our task", "probe_v1")
    assert client._http == original and "_http" not in vars(client)
    assert result["status"] == "returned" and len(client.calls) == 4
    summary = journal.summary()
    assert summary["generation_transport_attempts"] == summary["render_transport_attempts"] == 1
    assert summary["metadata_transport_attempts"] == 2 and summary["http_requests"] == 4
    assert summary["unique_recorded_roles"] == 1 and not summary["backend_acceptance_inferred"]
    events = trace_module._read_events(journal.http_path)
    assert len(events) == 8 and not summary["http_without_terminal_event"]
    for row in events:
        assert (tmp_path / row["raw_path"]).is_file()
        body = (tmp_path / row["request_path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == row["request_sha256"]
    assert client.calls[-1][1] == {"model": "test-model", "messages": [{"athlete_input": {"age": 13}}, "Our task"]}


def test_nested_v4_clients_and_two_role_adapters_are_discovered_once(tmp_path):
    client, journal = FakeClient(tmp_path), trace(tmp_path)
    drafting, evaluation = FakeRoles(client), FakeRoles(client)
    workflow = SimpleNamespace(client=client, drafting=SimpleNamespace(client=client, roles=drafting), roles=evaluation)
    planner = SimpleNamespace(planner=workflow, client=client)
    with journal.instrument(planner, "job_v4", 4):
        drafting.generate({}, {}, "Our task", "probe_v4_training", stage="training")
        evaluation.generate({}, {}, "Our task", "probe_v4_evaluator0", stage="evaluator")
    summary = journal.summary()
    assert summary["generation_transport_attempts"] == 2
    assert summary["role_invocations"] == summary["unique_recorded_roles"] == 2
    assert {row["stage"] for row in trace_module._read_events(journal.stage_path)} == {"training", "evaluator"}
    assert "generate" not in vars(drafting) and "generate" not in vars(evaluation)


def test_resume_reuses_completed_role_and_counts_usage_only_once(tmp_path):
    client, journal = FakeClient(tmp_path), trace(tmp_path)
    with journal.instrument(SimpleNamespace(client=client), "job", 1):
        client.generate({}, "Task", "stable")
    continued = trace(tmp_path)
    with continued.instrument(SimpleNamespace(client=client), "job", 1):
        cached = client.generate({}, "Task", "stable")
    summary = continued.summary()
    assert cached["cached"] and len(client.calls) == 4
    assert summary["generation_transport_attempts"] == summary["unique_recorded_roles"] == 1
    assert summary["role_invocations"] == 2 and summary["saved_role_reads"] == 1
    assert summary["role_usage"]["stable"]["usage"]["eval_count"] == 20
    assert not summary["role_usage"]["stable"]["first_observation_cached"]


def test_completed_weak_response_is_reused_without_a_fresh_generation(tmp_path):
    client, journal = FakeClient(tmp_path), trace(tmp_path)
    client.final_status = "failed"
    with journal.instrument(SimpleNamespace(client=client), "job", 1):
        first = client.generate({}, "Task", "weak")
    with journal.instrument(SimpleNamespace(client=client), "job", 1):
        second = client.generate({}, "Task", "weak")
    assert first["status"] == second["status"] == "failed" and second["cached"]
    assert journal.summary()["generation_transport_attempts"] == 1


def test_adapter_still_rejects_changed_request_under_the_same_call_id(tmp_path):
    client, journal = FakeClient(tmp_path), trace(tmp_path)
    with journal.instrument(SimpleNamespace(client=client), "job", 1):
        client.generate({}, "Task", "stable")
    with journal.instrument(SimpleNamespace(client=client), "job", 1):
        with pytest.raises(ValueError, match="different request"):
            client.generate({}, "Changed", "stable")
    assert journal.summary()["generation_transport_attempts"] == 1


@pytest.mark.parametrize("marker", ["active_call", "incomplete", "unresolved_without_lock"])
def test_prior_uncertain_or_incomplete_request_blocks_before_any_transport(tmp_path, marker):
    client, journal = FakeClient(tmp_path), trace(tmp_path)
    folder = tmp_path / "results/integration/model_calls"
    if marker == "active_call":
        (folder / "active_call").mkdir(parents=True)
    elif marker == "incomplete":
        write(folder / "old/request.json", {"request": {}})
    else:
        write(folder / "old/result.json", {"status": "unresolved"})
    before = {p: p.read_bytes() for p in folder.rglob("*") if p.is_file()}
    with pytest.raises(UncertainProbe):
        with journal.instrument(SimpleNamespace(client=client), "job", 1):
            client.generate({}, "Task", "new")
    assert not client.calls and all(p.read_bytes() == data for p, data in before.items())


def test_generation_timeout_holds_gate_and_prevents_the_next_role(tmp_path):
    client, journal = FakeClient(tmp_path), trace(tmp_path)
    client.timeout_generation = True
    with trace_module.execution_gate(tmp_path, "our-probe", manifest_sha256="sha", trace=journal):
        with journal.instrument(SimpleNamespace(client=client), "job", 1):
            result = client.generate({}, "Task", "uncertain")
        assert result["status"] == "unresolved"
        with pytest.raises(UncertainProbe):
            journal.raise_if_uncertain()
    for name in trace_module._GATE_MARKERS + trace_module._BACKEND_MARKERS[:1]:
        assert (tmp_path / name).is_dir()
    assert journal.summary()["generation_transport_attempts"] == 1 and journal.is_uncertain()


def test_declared_generation_limit_blocks_next_role_before_metadata(tmp_path):
    client, journal = FakeClient(tmp_path), trace(tmp_path, max_generation_submissions=1)
    with journal.instrument(SimpleNamespace(client=client), "job", 1):
        client.generate({}, "Task", "first")
        with pytest.raises(ProbeBlocked, match="generation limit"):
            client.generate({}, "Task", "second")
        reused = client.generate({}, "Task", "first")
    assert reused["cached"] and len(client.calls) == 4
    assert not (tmp_path / "results/integration/model_calls/second").exists()


def test_gate_blocks_other_owners_and_releases_only_its_own_clean_markers(tmp_path):
    journal = trace(tmp_path)
    with trace_module.execution_gate(tmp_path, "our-probe", manifest_sha256="sha", trace=journal):
        with pytest.raises(ProbeBlocked):
            with trace_module.execution_gate(tmp_path, "another", manifest_sha256="sha", trace=journal):
                pytest.fail("A second runtime must not start")
        assert (tmp_path / trace_module._GATE_MARKERS[0] / "owner.json").is_file()
    assert all(not (tmp_path / name).exists() for name in trace_module._GATE_MARKERS)
    other = tmp_path / trace_module._GATE_MARKERS[0] / "owner.json"
    write(other, {"owner_id": "someone_else"})
    before = other.read_bytes()
    with pytest.raises(ProbeBlocked):
        with trace_module.execution_gate(tmp_path, "our-probe", manifest_sha256="sha", trace=journal):
            pass
    assert other.read_bytes() == before


def test_manifest_change_and_torn_journal_are_never_silently_repaired(tmp_path):
    journal = trace(tmp_path)
    with pytest.raises(ProbeBlocked, match="differs"):
        PilotTrace(tmp_path, journal.output_dir, manifest_id="different")
    journal.http_path.write_bytes(b'{"event":"http_started"')
    with pytest.raises(ProbeBlocked, match="incomplete final record"):
        trace(tmp_path)
    assert journal.http_path.read_bytes() == b'{"event":"http_started"'


pytestmark = pytest.mark.requirement("31:bounded-probe-trace-and-resume")

pytestmark = pytest.mark.requirement("31:bounded-operational-probe")
