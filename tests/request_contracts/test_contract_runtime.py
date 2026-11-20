"""Check isolated request-contract composition without constructing model clients."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

from jsonschema import Draft202012Validator
import pytest


ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


SOURCE = ROOT / "src/champion_athletic_map/contract_runtime.py"
CONTRACT_SOURCE = ROOT / "src/champion_athletic_map/request_contracts.py"
API = load(SOURCE, "contract_runtime_under_test")
ADAPTER = load(ROOT / "src/champion_athletic_map/llm.py", "contract_runtime_original_adapter")
config = json.loads((ROOT / "artifacts/planners/version3_config.json").read_bytes())
NOTE = json.loads((ROOT / config["note_schema_path"]).read_bytes())
integration = json.loads((ROOT / "artifacts/language_model/integration_config.json").read_bytes())
LOCAL = json.loads((ROOT / integration["contracts_directory"] / "planner_response_schema.json").read_bytes())
NATIVE = ADAPTER._schema_order(ADAPTER._generation_schema(LOCAL))
PUBLIC = {"profile_id": "software:request-contract-runtime", "schema_version": "athlete-profile-input-2",
    "input": {"age": 15, "athlete_request": "Organize two additional basketball practices.",
        "food_question": 'For the food "Dates, medjool", how many grams of protein are recorded for 150 g?',
        "planning_window": {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"}}}
INPUT_SCHEMA = {"type": "object", "fixture_only": True}


class PublicModule:
    marker = "original-public-helper-preserved"

    def prepare_public_input(self, record, schema):
        if record.get("invalid_synthetic_input"):
            raise ValueError("Original public validation rejected the test input.")
        return {"public_input": deepcopy(record["input"]), "audit": {"fixture_only": True}}

    def verify_prepared_input(self, prepared):
        return prepared["audit"] == {"fixture_only": True}


def shared_client():
    shared = ModuleType("isolated_software_adapter")
    shared.RESPONSE_FORMAT = ADAPTER.RESPONSE_FORMAT
    for name in ("_schema_order", "_generation_schema", "_wire_bytes", "_sha"):
        setattr(shared, name, getattr(ADAPTER, name))
    exec("def prepare_request(self, public_record, instructions, **kwargs):\n"
         "    prepared = self.public.prepare_public_input(public_record, self.input_schema)\n"
         "    return prepared, {'format': self.output_schema, 'system': instructions + '\\n\\n' + RESPONSE_FORMAT}, {}\n", shared.__dict__)
    class Client:
        prepare_request = shared.prepare_request
    client = Client()
    client.public, client.input_schema = PublicModule(), deepcopy(INPUT_SCHEMA)
    client.response_schema, client.output_schema = deepcopy(LOCAL), deepcopy(NATIVE)
    client.encoder = SimpleNamespace(encode=lambda text, parse_special=False: list(text))
    client.native = object()
    return shared, client


class DraftingRole:
    def __init__(self, client, shared, policy):
        self.client, self.shared, self.reference_policy = client, shared, deepcopy(policy)
        self.integration = {"options": {"num_ctx": 8192, "num_predict": 2048}}
        self.calls, self.last_parse_schema, self.last_payload = [], None, None
        self.reply = {"contribution_status": "provided", "recommendations": [], "questions": [],
            "unresolved_issues": [], "rationale": "Synthetic contribution.", "qualifications": [], "evidence_refs": []}

    def prepare_request(self, public, references, instructions, *, stage, output_schema=None,
                        output_tokens=512, **kwargs):
        prepared = self.client.public.prepare_public_input(public, self.client.input_schema)
        schema = self.client.response_schema if output_schema is None else output_schema
        native = self.client.output_schema if output_schema is None else self.shared._schema_order(self.shared._generation_schema(schema))
        payload = {"format": deepcopy(native), "options": {"num_ctx": 8192, "num_predict": output_tokens},
            "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": json.dumps(references)}]}
        configuration = {"stage": stage, "role_policy": "original", "note_schema_version": "specialist-note-1",
            "output_schema_sha256": self.shared._sha(self.shared._wire_bytes(native)),
            "local_schema_sha256": self.shared._sha(self.shared._wire_bytes(schema))}
        return prepared, payload, configuration

    def generate(self, public, references, instructions, call_id, *, stage, output_schema=None,
                 output_tokens=512, **kwargs):
        prepared, payload, configuration = self.prepare_request(public, references, instructions,
            stage=stage, output_schema=output_schema, output_tokens=output_tokens, **kwargs)
        self.calls.append(stage)
        self.last_payload = deepcopy(payload)
        # Match the production transport's use of the generate argument for local parsing.
        self.last_parse_schema = deepcopy(self.client.response_schema if output_schema is None else output_schema)
        return {"format_valid": Draft202012Validator(self.last_parse_schema).is_valid(self.reply),
            "input_configuration": configuration, "fixture_only": True}


class EncodedEvaluatorRole(DraftingRole):
    encoding_marker = "candidate-and-check-encoding-retained"


def graph(*, construction_seconds=1):
    pairs = [shared_client() for _ in range(4)]
    policy = {"policy_version": "fixture-reference-policy", "source_configuration_sha256": "base"}
    def node(pair, reference=True):
        shared, client = pair
        return SimpleNamespace(client=client, _adapter=shared, instructions="Original common shared task.",
            config={"fixture_only": True, **({"reference_policy": deepcopy(policy)} if reference else {})})
    one, two, three, outer = [node(pair, reference=i != 0) for i, pair in enumerate(pairs)]
    evaluated, drafting = node(pairs[3]), node(pairs[3])
    for value in (three, drafting):
        value.note_schema = deepcopy(NOTE)
        value.roles = DraftingRole(value.client, value._adapter, policy)
    evaluated.roles = EncodedEvaluatorRole(evaluated.client, evaluated._adapter, policy)
    evaluated.drafting, outer.planner = drafting, evaluated
    evaluated.checker = SimpleNamespace(client=evaluated.client)
    evaluated.policy = {"maximum_revisions": 2, "required_unknowns_block": True}
    manifest = {"effective_reference_policy": deepcopy(policy),
        "effective_instructions_sha256": API.sha(one.instructions.encode()), "verified_file_sha256": {},
        "construction_seconds": construction_seconds, "reference_tools_construction_seconds": construction_seconds / 2,
        "base_runtime_manifest": {"construction_seconds": construction_seconds * 2, "source": "preserved"},
        "constructor_test_doubles": False}
    roles = [{"label": label + ".roles", "target": value.roles, "planner_version": version}
        for label, value, version in (("v3", three, 3), ("v4.evaluated", evaluated, 4), ("v4.drafting", drafting, 4))]
    return SimpleNamespace(planners={1: one, 2: two, 3: three, 4: outer}, reference_policy=deepcopy(policy),
        roles=roles, clients=[{"target": pair[1]} for pair in pairs], manifest=manifest, tools=object())


@pytest.fixture
def project(tmp_path):
    target = tmp_path / "src/champion_athletic_map"
    target.mkdir(parents=True)
    (target / "contract_runtime.py").write_bytes(SOURCE.read_bytes())
    (target / "request_contracts.py").write_bytes(CONTRACT_SOURCE.read_bytes())
    (target / "shared_guidance_runtime.py").write_text("# Injected software graph; no model runtime is constructed.\n")
    return tmp_path


def nodes(runtime):
    p = runtime.planners
    return [p[1], p[2], p[3], p[4], p[4].planner, p[4].planner.drafting]


def compose(project, base=None):
    base = base or graph()
    return API.build_runtime(project, {}, INPUT_SCHEMA, public_record=deepcopy(PUBLIC), runtime_builder=lambda *args: base)


def test_four_contracts_six_instructions_and_late_format_guidance_are_consistent(project):
    base = graph()
    result = compose(project, base)
    for client in [result.planners[v].client for v in range(1, 5)]:
        assert client.response_schema == result.request_contracts["local_response_schema"]
        assert API.wire(client.output_schema) == API.wire(result.request_contracts["native_response_schema"])
        assert "food_facts" in client.response_schema["required"]
        _, payload, _ = client.prepare_request(PUBLIC, "Our original task")
        assert API._OLD_FORMAT_SENTENCE not in payload["system"]
        assert API._NEW_FORMAT_SENTENCE in payload["system"]
    assert len({item.instructions for item in nodes(result)}) == 1
    assert nodes(result)[0].instructions.endswith(API.COMMON_NOTICE)
    assert "reference_policy" not in result.planners[1].config
    assert result.planners[4].planner.checker.client.response_schema == result.request_contracts["local_response_schema"]
    assert all(not item.roles.calls for item in nodes(result) if hasattr(item, "roles"))
    assert ADAPTER.RESPONSE_FORMAT.count(API._OLD_FORMAT_SENTENCE) == 1


def test_food_generate_and_preview_use_same_stricter_local_schema(project):
    result = compose(project)
    for role in (result.planners[3].roles, result.planners[4].planner.drafting.roles):
        old_note = deepcopy(NOTE)
        _, preview, configuration = role.prepare_request(PUBLIC, {"fixture_only": True}, "Original food instructions",
            stage="food", output_schema=old_note, output_tokens=512)
        reply = role.generate(PUBLIC, {"fixture_only": True}, "Original food instructions", "synthetic_food",
            stage="food", output_schema=old_note, output_tokens=512)
        assert reply["format_valid"] is False  # Empty 'provided' could pass the old note schema.
        assert role.last_parse_schema == result.request_contracts["food_note_schema"]
        assert role.last_payload == preview and role.last_payload["options"]["num_predict"] == 512
        assert role.last_payload["messages"][0]["content"].count(API.FOOD_NOTICE) == 1
        assert configuration["local_schema_sha256"] == role.shared._sha(role.shared._wire_bytes(role.last_parse_schema))
        assert reply["input_configuration"]["note_schema_version"] == "food-note-request-contract-1"
        role.reply.update(contribution_status="limited_information", unresolved_issues=["The supplied lookup does not establish the requested value."])
        assert role.generate(PUBLIC, {}, "Original food instructions", "synthetic_unknown", stage="food",
            output_schema=old_note, output_tokens=512)["format_valid"] is True
        assert old_note == NOTE


def test_role_inventory_evaluator_encoding_training_and_limits_are_preserved(project):
    base = graph()
    originals = [item["target"] for item in base.roles]
    policy = deepcopy(base.planners[4].planner.policy)
    result = compose(project, base)
    assert [item["label"] for item in result.roles] == ["v3.roles", "v4.evaluated.roles", "v4.drafting.roles"]
    assert result.roles[0]["target"] is result.planners[3].roles and result.roles[0]["target"] is not originals[0]
    assert result.roles[1]["target"] is result.planners[4].planner.roles is originals[1]
    assert result.roles[2]["target"] is result.planners[4].planner.drafting.roles and result.roles[2]["target"] is not originals[2]
    assert result.roles[1]["target"].encoding_marker == "candidate-and-check-encoding-retained"
    role = result.planners[3].roles
    _, payload, configuration = role.prepare_request(PUBLIC, {}, "Training guidance", stage="training", output_schema=NOTE, output_tokens=512)
    assert API.FOOD_NOTICE not in payload["messages"][0]["content"]
    assert configuration["note_schema_version"] == "specialist-note-1"
    assert configuration["local_schema_sha256"] == role.shared._sha(role.shared._wire_bytes(NOTE))
    assert result.planners[4].planner.policy == policy
    assert result.manifest["output_and_context_limits_changed"] is False


def test_new_policy_is_stable_across_nested_construction_observations(project):
    first, second = compose(project, graph(construction_seconds=1)), compose(project, graph(construction_seconds=9))
    assert first.reference_policy == second.reference_policy
    assert first.manifest["request_contract_configuration_sha256"] == second.manifest["request_contract_configuration_sha256"]
    assert first.reference_policy["source_configuration_sha256"] != "base"
    for item in nodes(first):
        if "reference_policy" in item.config:
            assert item.config["reference_policy"] == first.reference_policy
        if hasattr(item, "roles"):
            assert item.roles.reference_policy == first.reference_policy
    assert first.manifest["native_schema_ordered_wire_sha256"] == API.sha(API.wire(first.request_contracts["native_response_schema"]))


def test_bound_public_guard_rejects_new_case_for_all_clients_and_roles(project):
    result = compose(project)
    changed = deepcopy(PUBLIC)
    changed["input"]["athlete_request"] = "A different request in the same week."
    for item in nodes(result):
        assert item.client.public.marker == "original-public-helper-preserved"
        assert item.client.public.verify_prepared_input(item.client.public.prepare_public_input(PUBLIC, INPUT_SCHEMA))
        with pytest.raises(ValueError, match="different public athlete input"):
            item.client.public.prepare_public_input(changed, INPUT_SCHEMA)
        if hasattr(item, "roles"):
            with pytest.raises(ValueError, match="different public athlete input"):
                item.roles.prepare_request(changed, {}, "Unchanged role instructions", stage="training", output_schema=NOTE)
    invalid = {**PUBLIC, "invalid_synthetic_input": True}
    with pytest.raises(ValueError, match="Original public validation"):
        result.planners[1].client.public.prepare_public_input(invalid, INPUT_SCHEMA)


def test_source_files_and_original_contract_objects_are_unchanged(project):
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    original_local, original_native, original_note = deepcopy(LOCAL), deepcopy(NATIVE), deepcopy(NOTE)
    result = compose(project)
    assert {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()} == before
    assert LOCAL == original_local and NATIVE == original_native and NOTE == original_note
    assert result.manifest["legacy_files_modified"] is result.manifest["athlete_facts_changed"] is False
    assert result.manifest["food_lookup_values_injected"] is result.manifest["acceptance_policy_changed"] is False
    assert result.manifest["model_calls_during_construction"] == result.manifest["query_encoding_during_construction"] == 0
    assert result.manifest["native_backend_contract_verified"] is result.manifest["operational_generation_ready"] is False


@pytest.mark.parametrize("fault", ["late_format", "role_adapter", "inventory", "note_schema"])
def test_changed_graph_or_late_guidance_rejected_before_mutation(project, fault):
    base = graph()
    if fault == "late_format":
        base.planners[2]._adapter.RESPONSE_FORMAT = "Unexpected changed format notice."
    elif fault == "role_adapter":
        base.planners[3].roles.shared = ModuleType("different_adapter")
    elif fault == "inventory":
        base.roles = list(reversed(base.roles))
    else:
        base.planners[4].planner.drafting.note_schema["title"] = "Changed note schema"
    before = [(item.instructions, deepcopy(item.client.response_schema), deepcopy(item.client.output_schema)) for item in nodes(base)]
    with pytest.raises(ValueError):
        compose(project, base)
    assert [(item.instructions, item.client.response_schema, item.client.output_schema) for item in nodes(base)] == before


pytestmark = pytest.mark.requirement("31:request-contract-runtime")
