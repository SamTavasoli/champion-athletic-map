"""Exercise bounded outputs and complete encoded inputs using isolated graphs."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from threading import Lock
from types import MethodType

from jsonschema import Draft202012Validator
import pytest


ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


SOURCE = ROOT / "src/champion_athletic_map/operational_runtime.py"
CODEC_SOURCE = ROOT / "src/champion_athletic_map/food_reference_encoding.py"
if not CODEC_SOURCE.is_file():
    CODEC_SOURCE = Path(__file__).with_name("food_reference_encoding.py")
API = load(SOURCE, "operational_runtime_under_test")
HELPERS = load(ROOT / "tests/request_contracts/test_contract_runtime.py", "operational_contract_graph_helpers")
CONTRACT = load(ROOT / "src/champion_athletic_map/contract_runtime.py", "operational_original_contract_runtime")
RAG = load(ROOT / "src/champion_athletic_map/planners/rag.py", "operational_original_rag_guard")
PUBLIC, SCHEMA, NOTE = HELPERS.PUBLIC, HELPERS.INPUT_SCHEMA, HELPERS.NOTE


def packet():
    shared = {"status": "available", "qualification": "Original source qualification and reference amount are retained. " * 5,
        "source_ref": "https://example.test/frozen-food-reference", "recorded_basis": {"grams": 100, "method": "Original frozen reference basis"}}
    return {"packet_id": "synthetic-matched-packet", "payload": {
        "references": [{"complete_required_delivery_text": "Every source sentence remains present."}],
        "food_lookup": [{"status": "found", "source_refs": ["Original source"], "data": {
            "description": "Dates, medjool", "grams": 150, "qualifications": ["No dietary prescription is supplied."],
            "nutrients": [{**deepcopy(shared), "nutrient_name": "Protein", "amount": 2, "unit": "G"},
                {**deepcopy(shared), "nutrient_name": "Energy", "amount": 300, "unit": "KCAL"}]}}]}}


class FullPublic(HELPERS.PublicModule):
    def prepare_public_input(self, record, schema):
        result = super().prepare_public_input(record, schema)
        result["audit"].update(profile_id=record["profile_id"], profile_schema_version=record["schema_version"])
        return result


class FullViewRole(HELPERS.DraftingRole):
    def __init__(self, *args):
        super().__init__(*args)
        self.budget_checks = []

    def _budget_view(self, payload):
        self.budget_checks.append(deepcopy(payload))
        assert payload["options"]["num_ctx"] == 8192
        return payload

    def prepare_request(self, public, references, instructions, **kwargs):
        prepared, payload, config = super().prepare_request(public, references, instructions, **kwargs)
        view = {"athlete_input": deepcopy(prepared["public_input"]), "reference_data": deepcopy(references["payload"])}
        if kwargs.get("specialist_notes") is not None:
            view["specialist_notes"] = deepcopy(kwargs["specialist_notes"])
        payload["messages"][1]["content"] = json.dumps(view)
        return prepared, payload, config


class ExistingEncodedEvaluator(FullViewRole):
    encoding_marker = "original-candidate-and-check-codecs"

    def prepare_request(self, *args, **kwargs):
        prepared, payload, config = super().prepare_request(*args, **kwargs)
        view = json.loads(payload["messages"][1]["content"])
        view["candidate"] = {"encoding": "original-candidate-table", "rows": [["complete original candidate", None, 15]]}
        view["check_results"] = {"columns": ["check_id", "status", "reason"],
            "findings": [["required-check", "unknown", "Original complete finding."]]}
        payload["messages"][1]["content"] = json.dumps(view)
        config.update(candidate_encoding="existing-candidate-codec", review_encoding="existing-check-codec")
        return prepared, payload, config


@pytest.fixture
def project(tmp_path):
    target = tmp_path / "src/champion_athletic_map"
    target.mkdir(parents=True)
    for name in ("contract_runtime.py", "request_contracts.py", "shared_guidance_runtime.py"):
        (target / name).write_bytes((ROOT / "src/champion_athletic_map" / name).read_bytes())
    (target / "operational_runtime.py").write_bytes(SOURCE.read_bytes())
    (target / "food_reference_encoding.py").write_bytes(CODEC_SOURCE.read_bytes())
    return tmp_path


def base_graph(project, *, elapsed=1):
    result = HELPERS.graph(construction_seconds=elapsed)
    for number, node in result.planners.items():
        shared, client = (node._adapter if number != 4 else node.planner._adapter), node.client
        shared._decode = HELPERS.ADAPTER._decode
        shared.json = json
        exec("def prepare_request(self, public_record, instructions, *, planner_version=None, reference_packet=None):\n"
             "    prepared = self.public.prepare_public_input(public_record, self.input_schema)\n"
             "    view = {'athlete_input': prepared['public_input']}\n"
             "    if planner_version != 1: view['reference_data'] = reference_packet['payload']\n"
             "    payload = {'model': 'offline-test-double', 'stream': False, 'format': self.output_schema, 'truncate': False, 'shift': False,\n"
             "       'messages': [{'role': 'system', 'content': instructions + '\\n\\n' + RESPONSE_FORMAT}, {'role': 'user', 'content': json.dumps(view)}],\n"
             "       'options': {'temperature': 0, 'seed': 42, 'num_ctx': 8192, 'num_predict': 2048}}\n"
             "    return prepared, payload, {'fixture_only': True}\n", shared.__dict__)
        type(client).prepare_request = shared.prepare_request
        client.public = FullPublic()
        client.budget_checks, client.http_observations = [], []
        def budget(self, payload):
            self.budget_checks.append(deepcopy(payload))
            assert payload["format"] == self.output_schema and payload["options"]["num_ctx"] == 8192
            return payload
        def transport(self, endpoint, payload=None, timeout=8, raw_path=None):
            self.http_observations.append({"endpoint": endpoint, "payload": deepcopy(payload)})
            return {"fixture_only": True}
        def generate(self, public_record, instructions, call_id, **kwargs):
            _, payload, config = self.prepare_request(public_record, instructions, **kwargs)
            self._http("/api/chat", {**payload, "_debug_render_only": True})
            self._http("/api/chat", payload)
            return {"status": "returned", "completion_valid": True, "format_valid": True,
                "input_configuration": config, "fixture_only": True}
        client._budget_view, client._http, client.generate = MethodType(budget, client), MethodType(transport, client), MethodType(generate, client)
    policy = result.reference_policy
    for node in (result.planners[3], result.planners[4].planner.drafting):
        node.roles = FullViewRole(node.client, node._adapter, policy)
    engine = result.planners[4].planner
    engine.roles = ExistingEncodedEvaluator(engine.client, engine._adapter, policy)
    result.roles[0]["target"] = result.planners[3].roles
    result.roles[1]["target"] = engine.roles
    result.roles[2]["target"] = engine.drafting.roles
    return CONTRACT.build_runtime(project, {}, SCHEMA, public_record=deepcopy(PUBLIC), runtime_builder=lambda *args: result)


def compose(project, base=None):
    return API.build_runtime(project, {}, SCHEMA, public_record=deepcopy(PUBLIC),
        runtime_builder=lambda *args, **kwargs: base if base is not None else base_graph(project))


def test_equal_identifier_limits_allow_null_optional_fields_and_honest_unknown(project):
    result = compose(project)
    response = {"response_type": "clarification", "explanation": "Essential information is missing.",
        "questions": ["Which days are available?"], "food_facts": [{"statement": "The requested value is unknown.", "food_id": None, "source_ref": None}]}
    for number in range(1, 5):
        client = result.planners[number].client
        for schema in (client.response_schema, client.output_schema):
            assert Draft202012Validator(schema).is_valid(response)
            omitted = deepcopy(response)
            del omitted["food_facts"][0]["food_id"], omitted["food_facts"][0]["source_ref"]
            assert Draft202012Validator(schema).is_valid(omitted)
            for field, bound in (("food_id", 64), ("source_ref", 512)):
                long = deepcopy(response)
                long["food_facts"][0][field] = "x" * (bound + 1)
                assert not Draft202012Validator(schema).is_valid(long)
    assert len({API.wire(result.planners[v].client.output_schema) for v in range(1, 5)}) == 1


def test_v1_view_decoder_and_reference_access_are_unchanged(project):
    base = base_graph(project)
    one = base.planners[1]
    before_decoder, before_prepare = one._adapter._decode, one.client.prepare_request
    result = compose(project, base)
    assert one._adapter._decode is before_decoder and one.client.prepare_request == before_prepare
    _, payload, config = one.client.prepare_request(PUBLIC, one.instructions, planner_version=1)
    assert json.loads(payload["messages"][1]["content"]) == {"athlete_input": PUBLIC["input"]}
    assert "food_reference_encoding" not in config
    assert "reference_policy" not in one.config
    assert result.manifest["baseline_reference_access_changed"] is False


def test_reference_wire_is_encoded_and_private_rag_guard_restores_complete_values(project):
    result = compose(project)
    two, references = result.planners[2], packet()
    references["preparation"] = {"builder_policy": result.reference_policy["policy_version"],
        "source_configuration_sha256": result.reference_policy["source_configuration_sha256"]}
    _, payload, config = two.client.prepare_request(PUBLIC, two.instructions, planner_version=2, reference_packet=references)
    wire_view = json.loads(payload["messages"][1]["content"])
    assert isinstance(wire_view["reference_data"]["food_lookup"][0]["data"]["nutrients"], dict)
    expected = {"athlete_input": PUBLIC["input"], "reference_data": references["payload"]}
    assert two._adapter._decode(payload["messages"][1]["content"].encode()) == expected
    assert two.client.budget_checks[-1] == payload
    assert config["lossless_food_reference_roundtrip_verified"] is True
    # Exercise the real Version 2 counted_http guard against the encoded wire view.
    two._lock = Lock()
    two.integration = {"model": "offline-test-double", "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 2048}}
    outcome = RAG.RAGPlanner.generate(two, PUBLIC, references, "synthetic_guard")
    assert outcome["status"] == "returned" and outcome["transport_attempts"] == {"metadata": 0, "render": 1, "generation": 1}
    assert len(two.client.http_observations) == 2
    response_like = {**wire_view, "response_type": "plan"}
    assert two._adapter._decode(API.canonical(response_like)) == response_like
    with pytest.raises(ValueError):
        two._adapter._decode(b'{"duplicate":1,"duplicate":2}')


def test_all_role_handoffs_keep_full_values_and_existing_encoding_layers(project):
    result = compose(project)
    references = packet()
    engine = result.planners[4].planner
    assert isinstance(engine.roles, ExistingEncodedEvaluator)
    for role, stage in ((result.planners[3].roles, "training"), (engine.drafting.roles, "food"), (engine.roles, "evaluator"), (engine.roles, "revision")):
        schema = NOTE if stage != "revision" else None
        notes = [{"role": "training", "contribution": {"recommendations": ["Complete original note."]}}]
        _, payload, config = role.prepare_request(PUBLIC, references, "Original role instructions", stage=stage,
            output_schema=schema, output_tokens=2048 if stage == "revision" else 512, specialist_notes=notes)
        encoded = json.loads(payload["messages"][1]["content"])
        assert isinstance(encoded["reference_data"]["food_lookup"][0]["data"]["nutrients"], dict)
        restored = role.shared._decode(payload["messages"][1]["content"].encode())
        assert restored["reference_data"] == references["payload"] and restored["athlete_input"] == PUBLIC["input"]
        assert restored["specialist_notes"] == notes
        if role is engine.roles:
            assert config["candidate_encoding"] == "existing-candidate-codec"
            assert config["review_encoding"] == "existing-check-codec"
            assert restored["candidate"]["rows"] == [["complete original candidate", None, 15]]
            assert restored["check_results"]["findings"][0][-1] == "Original complete finding."
        assert role.budget_checks[-1] == payload
    assert [row["target"] for row in result.roles] == [result.planners[3].roles, engine.roles, engine.drafting.roles]


def test_food_role_still_parses_effective_food_schema_and_rejects_empty_provided(project):
    result = compose(project)
    for role in (result.planners[3].roles, result.planners[4].planner.drafting.roles):
        value = role.generate(PUBLIC, packet(), "Food instructions", "synthetic_food", stage="food", output_schema=NOTE, output_tokens=512)
        assert value["format_valid"] is False
        assert role.last_parse_schema == result.request_contracts["food_note_schema"]
        assert value["input_configuration"]["note_schema_version"] == "food-note-request-contract-1"
        assert role.last_payload["options"] == {"num_ctx": 8192, "num_predict": 512}


def test_configuration_is_stable_and_rebinds_every_shared_reference_policy(project):
    first = compose(project, base_graph(project, elapsed=1))
    second = compose(project, base_graph(project, elapsed=9))
    assert first.reference_policy == second.reference_policy
    assert first.manifest["operational_configuration_sha256"] == second.manifest["operational_configuration_sha256"]
    for node in HELPERS.nodes(first):
        if "reference_policy" in node.config:
            assert node.config["reference_policy"] == first.reference_policy
        if hasattr(node, "roles"):
            assert node.roles.reference_policy == first.reference_policy
    assert first.manifest["native_schema_ordered_wire_sha256"] == API.sha(API.wire(first.request_contracts["native_response_schema"]))
    changed = deepcopy(PUBLIC)
    changed["input"]["athlete_request"] = "A different public request."
    with pytest.raises(ValueError, match="different public athlete input"):
        first.planners[2].client.prepare_request(changed, "Original instructions", planner_version=2, reference_packet=packet())


def test_original_files_packets_settings_and_acceptance_rules_remain_unchanged(project):
    base, references = base_graph(project), packet()
    old_packet, policy = deepcopy(references), deepcopy(base.planners[4].planner.policy)
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    result = compose(project, base)
    result.planners[3].roles.prepare_request(PUBLIC, references, "Training instructions", stage="training", output_schema=NOTE)
    assert references == old_packet and result.planners[4].planner.policy == policy
    assert {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()} == before
    assert result.manifest["legacy_files_modified"] is result.manifest["acceptance_policy_changed"] is False
    assert result.manifest["output_and_context_limits_changed"] is False
    assert result.manifest["model_calls_during_construction"] == result.manifest["query_encoding_during_construction"] == 0
    assert result.manifest["new_native_backend_contract_verified"] is False


@pytest.mark.parametrize("fault", ["inventory", "contract", "adapter"])
def test_changed_contract_graph_is_rejected_before_mutating_clients(project, fault):
    base = base_graph(project)
    if fault == "inventory":
        base.roles = list(reversed(base.roles))
    elif fault == "contract":
        base.planners[2].client.output_schema = {"changed": True}
    else:
        base.planners[3].roles.shared = base.planners[2]._adapter
    before = [deepcopy(base.planners[v].client.output_schema) for v in range(1, 5)]
    with pytest.raises(ValueError):
        compose(project, base)
    assert [base.planners[v].client.output_schema for v in range(1, 5)] == before


pytestmark = pytest.mark.requirement("31:bounded-lossless-reference-runtime")
