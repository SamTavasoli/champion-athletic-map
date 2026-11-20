"""Reproduce the first handoff through real frozen role preparation layers."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if not (ROOT / "src/champion_athletic_map").is_dir():
    ROOT = HERE.parent / "work_step30/project/folder-before-step-30"
DATA = json.loads((HERE / "actual_handoff_fixture.json").read_bytes())


def load(path, name):
    value = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    value.__spec__.loader.exec_module(value)
    return value


def module(name):
    return load(ROOT / ("src/champion_athletic_map/" + name + ".py"), "handoff_actual_" + name.replace("/", "_"))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@pytest.fixture(scope="module")
def assets():
    op = module("operational_preparation")
    manifest_path = next((ROOT / "artifacts/language_model/tokenizers").glob("*/tokenizer_manifest.json"))
    manifest = json.loads(manifest_path.read_bytes())
    model = json.loads((manifest_path.parent / "normal_bpe_tokenizer.json").read_bytes())["model"]
    native = json.loads((ROOT / manifest["source_native_metadata"]["relative_path"]).read_bytes())
    counter = op.SourceTableCounter(model, native["model_info"])
    integration = json.loads((ROOT / "artifacts/language_model/integration_config.json").read_bytes())
    contracts = ROOT / integration["contracts_directory"]
    schema = module("pilot_schedule").build_input_schema(json.loads((contracts / "public_profile_record_schema.json").read_bytes()))
    local_schema = json.loads((contracts / "planner_response_schema.json").read_bytes())
    v3 = json.loads((ROOT / "artifacts/planners/version3_config.json").read_bytes())
    note_schema = json.loads((ROOT / v3["note_schema_path"]).read_bytes())
    public = load(contracts / "public_input.py", "handoff_actual_public_projection")
    response = load(contracts / "response_contract.py", "handoff_actual_response_contract")
    preflight = load(next((ROOT / "artifacts/language_model/prompt_preflight").glob("*/prompt_preflight.py")), "handoff_actual_request_preflight")
    return SimpleNamespace(counter=counter, native=native, integration=integration, schema=schema,
        local_schema=local_schema, note_schema=note_schema, public=public, response=response, preflight=preflight)


def actual_role(assets):
    shared, request_api = module("llm"), module("request_contracts")
    operational, contract = module("operational_runtime"), module("contract_runtime")
    codec, checks = module("context_encoding"), module("review_encoding")
    evaluated, candidates = module("evaluated_role_adapter"), module("planners/candidate_focused")
    continuation, raw_roles = module("continuation_runtime"), module("role_adapter")
    food_codec, focus = module("food_reference_encoding"), module("food_fact_focus")
    reviewed, corrected = module("reviewed_runtime"), module("corrected_runtime")
    bounded = module("bounded_revision")
    shared.RESPONSE_FORMAT = shared.RESPONSE_FORMAT.replace(contract._OLD_FORMAT_SENTENCE, contract._NEW_FORMAT_SENTENCE, 1)
    base_native = shared._schema_order(shared._generation_schema(assets.local_schema))
    bundle = operational.bounded_contracts(request_api.build_contracts(DATA["public_record"]["input"],
        assets.local_schema, base_native, assets.note_schema))
    assert canonical(bundle["native_response_schema"]) == canonical(DATA["captured_original_revision_payload"]["format"])
    class PinnedCounterAdapter:
        """Explicit test dependency: real source-table BPE lengths, no native process."""
        def encode(self, text, parse_special=False, **kwargs):
            assert parse_special is False and not kwargs
            return [0] * assets.counter.count(text)
    client = shared.OllamaClient.__new__(shared.OllamaClient)
    client.root, client.public = ROOT, assets.public
    client.input_schema, client.response_schema = deepcopy(assets.schema), deepcopy(bundle["local_response_schema"])
    client.output_schema, client.response = deepcopy(bundle["native_response_schema"]), assets.response
    client.preflight, client.encoder, client.native = assets.preflight, PinnedCounterAdapter(), deepcopy(assets.native)
    info = assets.native["model_info"]
    client.controls = [token for token, kind in zip(info["tokenizer.ggml.tokens"], info["tokenizer.ggml.token_type"]) if kind == 3]
    client._http = lambda *a, **k: (_ for _ in ()).throw(AssertionError("No HTTP is permitted in handoff regression tests"))
    kind = continuation.encoded_role_type(candidates._role_type(evaluated.EvaluatedRoleAdapter, codec), checks)
    role = kind.__new__(kind)
    role.root, role.client, role.shared = ROOT, client, shared
    role.integration = deepcopy(assets.integration)
    role.encoder, role.native, role._base = client.encoder, client.native, raw_roles.RoleAdapter
    role.packets = module("reference_packets")
    role.reference_policy = deepcopy(DATA["historical_reference_policy"])
    role._lock, role._active_payload = Lock(), None
    role.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}
    role = operational.encoded_role(role, food_codec, shared._decode)
    role = reviewed.focused_role(role, focus, food_codec, shared._decode, contract.FOOD_NOTICE)
    return corrected.revision_role(role, bounded)


def source_values():
    engine_api = module("planners/evaluated_specialists")
    return {"current": {"candidate": deepcopy(DATA["candidate_result"]), "check_report": deepcopy(DATA["full_check_report"])},
        "assessment": deepcopy(DATA["evaluator_assessment"]),
        "initial": {"new_candidate_request": deepcopy(DATA["expected_corrected_payload"]),
                    "removed_generated_notes": deepcopy(DATA["generated_notes"])},
        "selected": {"public": deepcopy(DATA["public_record"]["input"]), "packet": deepcopy(DATA["reference_packet"])},
        "old": {"draft_result": {"specialist_notes": deepcopy(DATA["generated_notes"]) }},
        "public_record": deepcopy(DATA["public_record"]), "reference_packet": deepcopy(DATA["reference_packet"])}


def ordinary_envelope():
    source, engine_api = source_values(), module("planners/evaluated_specialists")
    return {"notes": deepcopy(DATA["generated_notes"]),
        "candidate": engine_api.candidate_view(source["current"]["candidate"], "candidate_0"),
        "check_results": engine_api.model_check_view(source["current"]["check_report"]),
        "evaluator_assessment": deepcopy(source["assessment"])}


def prepare(role, envelope):
    return role.prepare_request(deepcopy(DATA["public_record"]), deepcopy(DATA["reference_packet"]),
        "Original shared task and revision-role instructions are retained in the archived audit.", stage="revision",
        output_schema=None, output_tokens=2048, specialist_notes=envelope, planner_version=4)


def test_real_chain_reproduces_frozen_first_guard_failure_from_saved_column_order(assets):
    _, payload, _ = prepare(actual_role(assets), ordinary_envelope())
    expected = DATA["expected_corrected_payload"]
    assert canonical(payload) != canonical(expected)
    actual_view = json.loads(payload["messages"][1]["content"])
    expected_view = json.loads(expected["messages"][1]["content"])
    assert [key for key in actual_view if actual_view[key] != expected_view[key]] == ["check_results"]
    decoder = module("review_encoding")
    actual_checks, expected_checks = decoder.decode_checks(actual_view["check_results"]), decoder.decode_checks(expected_view["check_results"])
    assert actual_checks["columns"] != expected_checks["columns"]
    assert canonical([dict(zip(actual_checks["columns"], row)) for row in actual_checks["findings"]]) == canonical(
        [dict(zip(expected_checks["columns"], row)) for row in expected_checks["findings"]])


def test_real_chain_matches_every_expected_payload_field_with_validated_original_layout(assets):
    # The shipped helper restores only a semantically proved source table layout.
    helper_path = ROOT / "src/champion_athletic_map/resumed_continuation.py"
    if not helper_path.is_file():
        helper_path = HERE / "resumed_continuation.py"
    helper = load(helper_path, "handoff_shipped_continuation_helper")
    envelope = helper.initial_envelope(ROOT, source_values())
    before = deepcopy(envelope)
    _, payload, cfg = prepare(actual_role(assets), envelope)
    assert canonical(payload) == canonical(DATA["expected_corrected_payload"])
    assert envelope == before
    assert cfg["bounded_revision"]["all_other_user_fields_preserved"] is True
    assert cfg["bounded_revision"]["model_schema_options_unchanged"] is True


def test_source_finding_change_is_rejected_before_it_can_be_reencoded(assets):
    helper_path = ROOT / "src/champion_athletic_map/resumed_continuation.py"
    if not helper_path.is_file():
        helper_path = HERE / "resumed_continuation.py"
    helper = load(helper_path, "handoff_shipped_negative_helper")
    source = source_values()
    source["current"]["check_report"]["checks"][0]["reason"] = "Changed required finding"
    with pytest.raises(ValueError):
        helper.initial_envelope(ROOT, source)


pytestmark = pytest.mark.requirement("31:exact-saved-handoff-prepare")
