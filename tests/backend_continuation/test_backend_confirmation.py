"""Exercise real render preflight and trace machinery with explicit fake HTTP."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import MethodType, SimpleNamespace

from jsonschema import Draft202012Validator
import pytest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if not (ROOT / "src/champion_athletic_map").is_dir():
    ROOT = HERE.parent / "work_step30/project/folder-before-step-30"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SOURCE = ROOT / "src/champion_athletic_map/backend_confirmation.py"
if not SOURCE.is_file():
    SOURCE = HERE / "backend_confirmation.py"
API = load(SOURCE, "backend_confirmation_under_test")
TRACE = load(ROOT / "src/champion_athletic_map/pilot_trace.py", "backend_confirmation_original_trace")
SHARED = load(ROOT / "src/champion_athletic_map/llm.py", "backend_confirmation_original_identity")
ROLE = load(ROOT / "src/champion_athletic_map/role_adapter.py", "backend_confirmation_original_budget")
PREFLIGHT = load(next((ROOT / "artifacts/language_model/prompt_preflight").glob("*/prompt_preflight.py")), "backend_confirmation_original_preflight")


@pytest.fixture(scope="module")
def source_data():
    path = ROOT / "tests/offline_corrections/saved_revision_requests.json"
    if not path.is_file():
        path = HERE.parent / "work_step31_15/saved_revision_requests.json"
    rows = json.loads(path.read_bytes())["rows"]
    bounded_path = ROOT / "src/champion_athletic_map/bounded_revision.py"
    if not bounded_path.is_file():
        bounded_path = HERE.parent / "work_step31_15/bounded_revision.py"
    bounded = load(bounded_path, "backend_confirmation_bounded_inputs")
    original = load(ROOT / "src/champion_athletic_map/operational_preparation.py", "backend_confirmation_counter")
    manifest_path = next((ROOT / "artifacts/language_model/tokenizers").glob("*/tokenizer_manifest.json"))
    manifest = json.loads(manifest_path.read_bytes())
    model = json.loads((manifest_path.parent / "normal_bpe_tokenizer.json").read_bytes())["model"]
    info = json.loads((ROOT / manifest["source_native_metadata"]["relative_path"]).read_bytes())["model_info"]
    counter = original.SourceTableCounter(model, info)
    requests = []
    for index, row in enumerate(rows, 1):
        prepared, payload, configuration = bounded.transform_request(row["prepared"], row["request"], row["configuration"], counter=counter)
        measured = configuration["bounded_revision"]["offline_measurement"]
        requests.append({"request_id": row["call_id"], "case_index": row["case"], "payload": payload, "prepared": prepared,
            "predicted_body_tokens": measured["new_body_tokens"],
            "predicted_input_tokens": measured["new_input_tokens_with_boundary_reserve"],
            "predicted_render_sha256": API.sha(bounded.recorded_render(payload).encode()), "output_reserve": 2048})
    controls = [token for token, kind in zip(info["tokenizer.ggml.tokens"], info["tokenizer.ggml.token_type"]) if kind == 3]
    return counter, controls, requests, bounded.recorded_render


class FakeBackend:
    """Tests only: every transport is local and explicitly declared injected."""
    def __init__(self, counter, controls, render, *, fault=None):
        self.counter, self.render, self.fault = counter, render, fault
        self.calls, self.loaded = [], fault not in {"cold_start", "never_load"}
        self.native = {"template": "Software fixture template", "system": "", "messages": None,
            "parameters": None, "renderer": None, "parser": None, "template_source": None}
        backend = self
        class Encoder:
            def encode(self, text, **kwargs):
                assert kwargs == {"parse_special": True, "add_bos": False, "add_eos": False}
                return [0] * (backend.counter.count(text) + (1 if backend.fault == "count_drift" else 0))
        self.client = SimpleNamespace(native=deepcopy(self.native), preflight=PREFLIGHT, controls=controls,
            encoder=Encoder(), response=SimpleNamespace(Draft202012Validator=Draft202012Validator),
            _identity=None, _http=None, generate=lambda *a, **k: (_ for _ in ()).throw(AssertionError("No generation in render-only tests")))
        self.client._http = self.http
        self.client._identity = MethodType(SHARED.OllamaClient._identity, self.client)
        self.role = SimpleNamespace(client=self.client, shared=SimpleNamespace(_wire_bytes=SHARED._wire_bytes))
        self.role._budget_view = MethodType(ROLE.RoleAdapter._budget_view, self.role)

    def http(self, endpoint, payload=None, timeout=8, raw_path=None):
        self.calls.append({"endpoint": endpoint, "payload": deepcopy(payload)})
        if endpoint == "/api/version":
            value = {"version": "wrong" if self.fault == "version" else "0.40.16"}
        elif endpoint == "/api/tags":
            value = {"models": [{"name": SHARED.MODEL, "model": SHARED.MODEL, "digest": SHARED.DIGEST,
                "details": {"quantization_level": "Q4_K_M"}}]}
        elif endpoint == "/api/show":
            value = deepcopy(self.native)
        elif endpoint == "/api/ps":
            value = {"models": [{"digest": SHARED.DIGEST, "context_length": 4096 if self.fault == "context" else 8192}] if self.loaded else []}
        elif endpoint == "/api/chat":
            assert payload.get("_debug_render_only") is True, "A generation request escaped the module gate"
            if self.fault == "timeout":
                raise TimeoutError("Explicit fake HTTP timeout")
            self.loaded = self.fault != "never_load"
            rendered = self.render(payload)
            if self.fault == "rewrite":
                rendered = "changed backend text" + rendered
            value = {"_debug_info": {"rendered_template": rendered, "image_count": 0}, "eval_count": 0, "prompt_eval_count": 0}
            if self.fault == "generated_reply":
                value.update(done=True, eval_count=1, message={"role": "assistant", "content": "Unexpected generation"})
        else:
            raise AssertionError(endpoint)
        if raw_path is not None:
            Path(raw_path).write_bytes(API.canonical(value))
        return value


@pytest.fixture
def scenario(tmp_path, source_data):
    counter, controls, requests, render = source_data
    entries = deepcopy(requests)
    for index, entry in enumerate(entries, 1):
        path = tmp_path / "results/pilot/offline_corrections/fixture/requests" / (str(index) + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(API.canonical(entry["payload"]) + b"\n")
        entry.update(source_path=path.relative_to(tmp_path).as_posix(), source_sha256=API.sha(path.read_bytes()))
    descriptors = API.request_descriptors(entries)
    manifest = {"manifest_id": "a" * 64, "continuation_id": "software_render_confirmation", "injected_test_dependencies": True,
        "backend_confirmation_requests": descriptors, "backend_confirmation_request_roster_sha256": API.sha(API.canonical(descriptors))}
    folder = tmp_path / "results/pilot/saved_continuation/software_render_confirmation"
    trace = TRACE.PilotTrace(tmp_path, folder, manifest_id=manifest["manifest_id"], max_generation_submissions=4)
    return tmp_path, manifest, entries, trace, lambda fault=None: FakeBackend(counter, controls, render, fault=fault)


def run(scenario, backend):
    root, manifest, requests, trace, _ = scenario
    with TRACE.execution_gate(root, "software_confirmation_owner", manifest_sha256=manifest["manifest_id"], trace=trace):
        return API.confirm_requests(root, manifest, requests, role=backend.role, trace=trace)


def test_five_real_preflight_confirmations_have_exact_trace_caps_and_zero_generation(scenario):
    root, manifest, requests, trace, make = scenario
    backend = make()
    result = run(scenario, backend)
    assert result["all_five_confirmed"] is True and result["new_render_requests"] == 5
    assert result["new_metadata_requests"] == 8 and result["new_http_requests"] == 13
    assert result["backend_token_count_agreement_verified"] is False
    assert result["injected_test_dependencies"] is True and result["operational_generation_ready"] is False
    assert trace.summary()["generation_transport_attempts"] == 0
    chats = [row for row in backend.calls if row["endpoint"] == "/api/chat"]
    assert len(chats) == 5 and all(row["payload"]["_debug_render_only"] is True for row in chats)
    assert all(API.canonical({key: value for key, value in chat["payload"].items() if key != "_debug_render_only"})
               == API.canonical(entry["payload"]) for chat, entry in zip(chats, requests))
    assert backend.client._http == backend.http and trace.current is None
    assert not (root / "results/integration/active_runtime").exists()
    cached = API.confirm_requests(root, manifest, requests, output_dir=trace.output_dir / "backend_confirmation")
    assert cached["saved_confirmation_reused"] is True and cached["new_http_requests"] == 0
    assert len(backend.calls) == 13


def test_cold_runner_is_allowed_before_render_but_required_after_all_five(scenario):
    root, _, _, trace, make = scenario
    result = run(scenario, make("cold_start"))
    assert result["confirmed_requests"] == 5
    before = API.read(trace.output_dir / "backend_confirmation/identity_before.json")
    after = API.read(trace.output_dir / "backend_confirmation/identity_after.json")
    assert before["cold_before_render"] is True and before["runner"] is None
    assert after["runner"]["context_length"] == 8192


@pytest.mark.parametrize("fault,render_count", [("rewrite", 1), ("count_drift", 1), ("generated_reply", 1), ("version", 0), ("context", 0), ("never_load", 5)])
def test_completed_mismatches_block_without_retry_or_stale_global_gate(scenario, fault, render_count):
    root, manifest, requests, trace, make = scenario
    backend = make(fault)
    with pytest.raises((ValueError, API.ConfirmationBlocked)):
        run(scenario, backend)
    assert sum(row["endpoint"] == "/api/chat" for row in backend.calls) == render_count
    assert not (root / "results/integration/active_runtime").exists()
    assert trace.summary()["generation_transport_attempts"] == 0
    before = len(backend.calls)
    with pytest.raises(API.ConfirmationBlocked, match="incomplete"):
        API.confirm_requests(root, manifest, requests, role=backend.role, trace=trace)
    assert len(backend.calls) == before


def test_uncertain_transport_preserves_global_gate_and_does_not_resubmit(scenario):
    root, manifest, requests, trace, make = scenario
    backend = make("timeout")
    with pytest.raises(TimeoutError):
        run(scenario, backend)
    assert (root / "results/integration/active_runtime/owner.json").is_file()
    assert trace.is_uncertain() is True
    before = len(backend.calls)
    with pytest.raises(API.ConfirmationBlocked, match="incomplete"):
        API.confirm_requests(root, manifest, requests, role=backend.role, trace=trace)
    assert len(backend.calls) == before


def test_tampered_completed_evidence_is_not_reused(scenario):
    _, manifest, requests, trace, make = scenario
    run(scenario, make())
    rendered = next((trace.output_dir / "backend_confirmation").glob("*/rendered_prompt.txt"))
    rendered.write_text("changed")
    with pytest.raises(API.ConfirmationBlocked, match="evidence changed"):
        API.confirm_requests(scenario[0], manifest, requests, output_dir=trace.output_dir / "backend_confirmation")


def test_changed_source_or_roster_is_rejected_before_any_http(scenario):
    root, manifest, requests, trace, make = scenario
    backend = make()
    Path(root / requests[0]["source_path"]).write_text('{"different":true}')
    with pytest.raises(ValueError, match="candidate changed"):
        run(scenario, backend)
    assert backend.calls == []
    with pytest.raises(ValueError, match="Exactly five"):
        API.request_descriptors(requests + [deepcopy(requests[0])])


def test_actual_guard_forbids_generation_even_if_identity_code_attempts_it(scenario):
    _, _, requests, trace, make = scenario
    backend = make()
    backend.client._identity = lambda: backend.client._http("/api/chat", requests[0]["payload"])
    with pytest.raises(API.ConfirmationBlocked, match="forbids generation"):
        run(scenario, backend)
    assert backend.calls == [] and trace.summary()["generation_transport_attempts"] == 0


pytestmark = pytest.mark.requirement("31:backend-render-confirmation")
