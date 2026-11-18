"""Exercise prospective wiring and request boundaries without backend execution."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "src/champion_athletic_map").is_dir():
    ROOT = Path(__file__).resolve().parents[1] / "work_step30/project/folder-before-step-30"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


SOURCE = ROOT / "src/champion_athletic_map/reviewed_runtime.py"
if not SOURCE.is_file():
    SOURCE = Path(__file__).with_name("reviewed_runtime.py")
API = load(SOURCE, "reviewed_runtime_under_test")
HELPERS = load(ROOT / "tests/operational_corrections/test_operational_runtime.py", "reviewed_runtime_operational_helpers")
PUBLIC, SCHEMA, NOTE = HELPERS.PUBLIC, HELPERS.SCHEMA, HELPERS.NOTE


@pytest.fixture
def project(tmp_path):
    target = tmp_path / "src/champion_athletic_map"
    target.mkdir(parents=True)
    for name in ("contract_runtime", "request_contracts", "shared_guidance_runtime", "operational_runtime", "food_reference_encoding", "pilot_references", "reference_context", "reference_preparation"):
        (target / (name + ".py")).write_bytes((ROOT / "src/champion_athletic_map" / (name + ".py")).read_bytes())
    for name in ("reviewed_runtime", "food_fact_focus", "selected_drill_context"):
        source = ROOT / "src/champion_athletic_map" / (name + ".py")
        if not source.is_file():
            source = Path(__file__).with_name(name + ".py")
        (target / (name + ".py")).write_bytes(source.read_bytes())
    # The checker graph is an explicit software double; no native/model readiness is claimed.
    (target / "reviewed_planning_checks.py").write_text(
        "from types import SimpleNamespace\n"
        "def make_checker(root, client, policy, resources=None):\n"
        "    return SimpleNamespace(client=client, resources=resources, retained_policy=policy, pilot_schedule_policy={'version':'software-reviewed-checker'}, check=lambda *a,**k: {'reviewed_internal_fixture':True})\n"
        "def make_assessor(root, public_schema):\n"
        "    return SimpleNamespace(schema=public_schema, reviewed_assessor_fixture=True)\n", encoding="utf-8")
    release = tmp_path / "artifacts/language_model/approved_resources/software-only"
    release.mkdir(parents=True)
    body = b'{"software_fixture":true}\n'
    (release / "manifest.json").write_bytes(body)
    (tmp_path / API._POINTER).write_text(json.dumps({"release_directory": release.relative_to(tmp_path).as_posix(),
        "manifest_sha256": hashlib.sha256(body).hexdigest()}), encoding="utf-8")
    guidance = tmp_path / API._SHARED_NOTICE
    guidance.parent.mkdir(parents=True)
    guidance.write_bytes((ROOT / API._SHARED_NOTICE).read_bytes())
    return tmp_path


def base_runtime(project, *, elapsed=1):
    base = HELPERS.compose(project, HELPERS.base_graph(project, elapsed=elapsed))
    base.planners[4].planner.checker.resources = {"unchanged_test_resources": True}
    for node in (base.planners[3], base.planners[4].planner.drafting):
        node._preparation = SimpleNamespace(validate_packet=lambda *a, **k: False, retained_fixture_attribute=True)
    return base


def compose(project, base=None):
    base = base or base_runtime(project)
    return API.build_runtime(project, {}, SCHEMA, public_record=deepcopy(PUBLIC), runtime_builder=lambda *a, **k: base)


def packet():
    result = HELPERS.packet()
    lookup = result["payload"]["food_lookup"][0]
    lookup["source_refs"] = ["https://example.test/food123"]
    data = lookup["data"]
    data["food_id"] = "123"
    for index, row in enumerate(data["nutrients"]):
        row.update(nutrient_id="1003" if index == 0 else "1008", fdc_id="123", description=data["description"],
            grams=150, reference_mass_g=100, reference_basis="Amount per100g reference food", source_record_url=lookup["source_refs"][0],
            amount="2.715" if index == 0 else "300", amount_per_100g_raw="1.81" if index == 0 else "200")
    return result


def matched_packet(runtime):
    result = packet()
    result["preparation"] = {"builder_policy": runtime.reference_policy["policy_version"],
        "source_configuration_sha256": runtime.reference_policy["source_configuration_sha256"]}
    return result


def test_six_equal_instructions_four_clients_and_three_trace_targets(project):
    runtime = compose(project)
    nodes = HELPERS.HELPERS.nodes(runtime)
    assert len({n.instructions for n in nodes}) == 1
    assert all(API.COMMON_GUIDANCE in n.instructions for n in nodes)
    assert len({id(runtime.planners[v].client) for v in range(1, 5)}) == 4
    assert [r["target"] for r in runtime.roles] == [runtime.planners[3].roles,
        runtime.planners[4].planner.roles, runtime.planners[4].planner.drafting.roles]
    for node in nodes:
        if "reference_policy" in node.config:
            assert node.config["reference_policy"] == runtime.reference_policy
        if hasattr(node, "roles"):
            assert node.roles.reference_policy == runtime.reference_policy
    assert runtime.manifest["constructor_test_doubles"] is True
    assert runtime.manifest["new_native_backend_contract_verified"] is False


def test_baseline_remains_reference_free_and_bound_to_original_public_input(project):
    base = base_runtime(project)
    prepare, decoder = base.planners[1].client.prepare_request, base.planners[1]._adapter._decode
    runtime = compose(project, base)
    one = runtime.planners[1]
    assert one.client.prepare_request == prepare and one._adapter._decode is decoder
    _, payload, config = one.client.prepare_request(PUBLIC, one.instructions, planner_version=1)
    assert json.loads(payload["messages"][1]["content"]) == {"athlete_input": PUBLIC["input"]}
    assert "requested_food_focus_version" not in config
    changed = deepcopy(PUBLIC)
    changed["input"]["athlete_request"] = "Different case"
    with pytest.raises(ValueError, match="different public athlete input"):
        one.client.prepare_request(changed, one.instructions, planner_version=1)


def test_v2_food_fact_is_source_derived_and_strict_rag_guard_still_checks_original_view(project):
    runtime = compose(project)
    two, references = runtime.planners[2], matched_packet(runtime)
    original = deepcopy(references)
    _, payload, config = two.client.prepare_request(PUBLIC, two.instructions, planner_version=2, reference_packet=references)
    view = json.loads(payload["messages"][1]["content"])
    assert view["requested_food_facts"]["status"] == "available"
    assert view["requested_food_facts"]["requested_facts"][0]["amount"] == "2.715"
    assert two._adapter._decode(API.canonical(view)) == {"athlete_input": PUBLIC["input"], "reference_data": references["payload"]}
    assert references == original and config["food_focus_is_input_only"] is True
    two._lock = Lock()
    two.integration = {"model": "offline-test-double", "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 2048}}
    value = HELPERS.RAG.RAGPlanner.generate(two, PUBLIC, references, "software_reviewed_guard")
    assert value["status"] == "returned" and value["transport_attempts"] == {"metadata": 0, "render": 1, "generation": 1}
    assert len(two.client.http_observations) == 2
    assert two.client.budget_checks[-1]["messages"] == payload["messages"]


def test_tampered_or_missing_focus_and_duplicate_json_keys_are_rejected(project):
    runtime = compose(project)
    two, references = runtime.planners[2], matched_packet(runtime)
    _, payload, _ = two.client.prepare_request(PUBLIC, two.instructions, planner_version=2, reference_packet=references)
    view = json.loads(payload["messages"][1]["content"])
    view["requested_food_facts"]["requested_facts"][0]["amount"] = "999"
    with pytest.raises(ValueError, match="facts changed"):
        two._adapter._decode(API.canonical(view))
    view.pop("requested_food_facts")
    with pytest.raises(ValueError, match="food focus is missing"):
        two._adapter._decode(API.canonical(view))
    with pytest.raises(ValueError):
        two._adapter._decode(b'{"a":1,"a":2}')


def test_all_roles_keep_food_focus_complete_sources_and_candidate_check_codecs(project):
    runtime = compose(project)
    engine, references = runtime.planners[4].planner, matched_packet(runtime)
    original = deepcopy(references)
    for role, stage in ((runtime.planners[3].roles, "training"), (engine.drafting.roles, "food"),
                        (engine.roles, "evaluator"), (engine.roles, "revision")):
        _, payload, config = role.prepare_request(PUBLIC, references, "Original role instructions", stage=stage,
            output_schema=None if stage == "revision" else NOTE, output_tokens=2048 if stage == "revision" else 512,
            specialist_notes=[{"role": "training", "contribution": {"recommendations": ["Original model note"]}}])
        view = role.shared._decode(payload["messages"][1]["content"].encode())
        assert view["requested_food_facts"]["status"] == "available"
        assert view["reference_data"] == references["payload"] and view["athlete_input"] == PUBLIC["input"]
        assert config["original_public_and_reference_values_preserved"] is True
        if role is engine.roles:
            assert config["candidate_encoding"] == "existing-candidate-codec"
            assert config["review_encoding"] == "existing-check-codec"
            assert view["candidate"]["rows"] == [["complete original candidate", None, 15]]
        if stage == "food":
            assert API.FOOD_ROLE_GUIDANCE in payload["messages"][0]["content"]
        assert role.budget_checks[-1] == payload
    assert references == original


def test_internal_checker_and_packet_validators_are_updated_without_mutating_original_objects(project):
    base = base_runtime(project)
    engine = base.planners[4].planner
    old_checker = engine.checker
    old_validator = base.planners[3]._preparation
    policy = deepcopy(engine.policy)
    runtime = compose(project, base)
    assert runtime.checker is engine.checker and runtime.checker is not old_checker
    assert runtime.checker.check()["reviewed_internal_fixture"] is True
    assert runtime.checker.resources == old_checker.resources
    assert runtime.planners[3]._preparation is not old_validator
    assert old_validator.validate_packet() is False
    assert runtime.planners[3]._preparation.retained_fixture_attribute is True
    assert engine.policy == policy
    assert runtime.assessor_factory(project, SCHEMA).reviewed_assessor_fixture is True


def test_stable_identity_settings_and_no_writes_or_transport_during_construction(project):
    first_base = base_runtime(project, elapsed=1)
    options = deepcopy(first_base.planners[4].planner.roles.integration)
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob('*') if p.is_file()}
    first = compose(project, first_base)
    second = compose(project, base_runtime(project, elapsed=9))
    assert first.reference_policy == second.reference_policy
    assert first.manifest["reviewed_runtime_configuration_sha256"] == second.manifest["reviewed_runtime_configuration_sha256"]
    assert first.planners[4].planner.roles.integration == options
    assert {p.relative_to(project): p.read_bytes() for p in project.rglob('*') if p.is_file()} == before
    assert first.manifest["model_calls_during_construction"] == first.manifest["query_encoding_during_construction"] == 0
    assert first.manifest["output_and_context_limits_changed"] is False
    assert first.manifest["acceptance_policy_changed"] is False


def test_changed_release_or_graph_fails_before_rebinding_clients(project):
    base = base_runtime(project)
    prior = base.planners[2].client.prepare_request
    pointer = project / API._POINTER
    changed = json.loads(pointer.read_bytes())
    changed["manifest_sha256"] = "0" * 64
    pointer.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="manifest changed"):
        compose(project, base)
    assert base.planners[2].client.prepare_request == prior


def test_concise_instructions_replace_exact_addenda_and_retain_original_task(project):
    contract = API.load(project, "src/champion_athletic_map/contract_runtime.py")
    shared = (project / API._SHARED_NOTICE).read_text(encoding="utf-8")
    original = "Original task and full schedule safeguards.\n\n" + shared + "\n\n" + contract.COMMON_NOTICE
    compact, names = API.concise_instructions(project, original, contract)
    assert compact.startswith("Original task and full schedule safeguards.")
    assert shared not in compact and contract.COMMON_NOTICE not in compact
    assert names == ["shared_task_candidate", "request_contract_candidate"]
    assert len(compact.encode()) < len(original.encode())
    with pytest.raises(ValueError, match="exact prospective"):
        API.concise_instructions(project, original.replace(shared, "Changed prospective guidance"), contract)


def test_fresh_reference_factory_keeps_original_guards_and_labels_test_injection(project):
    runtime = compose(project)
    api = API.load(project, "src/champion_athletic_map/pilot_references.py")
    tools = SimpleNamespace(source_bindings={}, core=SimpleNamespace(_query_api=object()),
        load_query_runtime=lambda: {"config": {"software_fixture": True}, "guard": lambda: None})
    fresh = API.build_reference_preparer(project, tools, runtime.planners[2].client, runtime.reference_policy,
        preparer_api=api)
    assert fresh.setup_record["original_constructor_dependency_injection"] is True
    assert fresh.setup_record["dependency_injection_kind"] == "explicit_test_dependencies"
    assert fresh.setup_record["injected_test_dependencies"] is True
    assert fresh.setup_record["query_encoder_processes"] == 0
    assert {"src/champion_athletic_map/reference_context.py", "src/champion_athletic_map/reference_preparation.py"} <= set(fresh.module_bindings)
    fresh._guard()
    changed = deepcopy(runtime.reference_policy)
    changed["resource_release_manifest_sha256"] = "wrong"
    with pytest.raises(ValueError, match="another approved-resource"):
        API.build_reference_preparer(project, tools, runtime.planners[2].client, changed, preparer_api=api)
    reference = project / "src/champion_athletic_map/reference_context.py"
    reference.write_text("# Changed original source")
    with pytest.raises(ValueError, match="recorded reference component changed"):
        API.build_reference_preparer(project, tools, runtime.planners[2].client, runtime.reference_policy, preparer_api=api)


pytestmark = pytest.mark.requirement("31:reviewed-development-runtime")
