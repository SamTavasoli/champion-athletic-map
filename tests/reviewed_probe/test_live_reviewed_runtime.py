"""Exercise real copied-checker behavior and retain every original request guard."""

from copy import copy, deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
if not (ROOT / "src/champion_athletic_map").is_dir():
    ROOT = Path(__file__).resolve().parents[1] / "work_step30/project/folder-before-step-30"


def load(path, name):
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    result.__spec__.loader.exec_module(result)
    return result


SOURCE = ROOT / "src/champion_athletic_map/live_reviewed_runtime.py"
if not SOURCE.is_file():
    SOURCE = Path(__file__).with_name("live_reviewed_runtime.py")
API = load(SOURCE, "live_reviewed_runtime_under_test")
FROZEN_TEST = load(ROOT / "tests/reviewed_workflow/test_reviewed_runtime.py", "live_reviewed_frozen_graph_helpers")
FROZEN = load(ROOT / API.FROZEN_RUNTIME, "live_frozen_reviewed_runtime")
PUBLIC, SCHEMA = FROZEN_TEST.PUBLIC, FROZEN_TEST.SCHEMA


@pytest.fixture
def project(tmp_path):
    project = FROZEN_TEST.project.__wrapped__(tmp_path)
    (project / API.SOURCE).write_bytes(SOURCE.read_bytes())
    checker = project / API.CHECKER
    source = checker.read_text(encoding="utf-8")
    source = "from copy import copy\n" + source.replace("client=client, resources=", "client=copy(client), resources=")
    checker.write_text(source, encoding="utf-8")
    return project


def compose(project):
    base = FROZEN_TEST.base_runtime(project)
    return API.build_runtime(project, {}, SCHEMA, public_record=deepcopy(PUBLIC), runtime_builder=lambda *a, **k: base)


def test_reproduces_real_copy_mismatch_then_normalizes_it_without_relaxing_contracts(project):
    base = FROZEN_TEST.base_runtime(project)
    with pytest.raises(ValueError, match="another public-input client"):
        FROZEN.build_runtime(project, {}, SCHEMA, public_record=deepcopy(PUBLIC), runtime_builder=lambda *a, **k: base)
    result = compose(project)
    assert result.checker is result.planners[4].planner.checker
    assert result.checker.client is result.planners[4].client
    assert result.manifest["equivalent_checker_client_alias_normalized"] is True
    assert result.manifest["constructor_test_doubles"] is True
    assert result.manifest["operational_generation_ready"] is False


def test_real_pilot_checker_shallow_copy_has_the_exact_required_schema_and_public_helper():
    # These are the real checker constructors and real approved rules; no model client is built.
    checks = load(ROOT / API.CHECKER, "live_real_reviewed_checks")
    integration = json.loads((ROOT / "artifacts/language_model/integration_config.json").read_bytes())
    original_schema = json.loads((ROOT / integration["contracts_directory"] / "public_profile_record_schema.json").read_bytes())
    pilot = load(ROOT / "src/champion_athletic_map/pilot_schedule.py", "live_real_pilot_schedule")
    schema = pilot.build_input_schema(original_schema)
    assessor = checks.make_assessor(ROOT, schema)
    original_client = assessor.client
    checker = checks.make_checker(ROOT, original_client, {}, resources=assessor.calendar.resources)
    assert checker.client is not original_client
    assert checker.client.public is original_client.public
    assert checker.client.input_schema == original_client.input_schema
    assert API.normalize_checker_client(checker, original_client).client is original_client
    assert checker.reviewed_planning_policy["version"] == checks.VERSION


@pytest.mark.parametrize("fault", ["public", "input_schema", "response_schema", "response", "output_schema"])
def test_mismatched_copy_is_rejected(fault):
    original = SimpleNamespace(public=object(), input_schema={"original": 1}, response_schema={"original": 2},
        response=object(), output_schema={"original": 3})
    copied = copy(original)
    setattr(copied, fault, object() if fault in {"public", "response"} else {"different": True})
    checker = SimpleNamespace(client=copied)
    with pytest.raises(ValueError, match="copied"):
        API.normalize_checker_client(checker, original)
    assert checker.client is copied


def test_all_nodes_get_neutral_catalog_guidance_and_one_rebound_policy(project):
    runtime = compose(project)
    nodes = FROZEN_TEST.HELPERS.HELPERS.nodes(runtime)
    assert len({node.instructions for node in nodes}) == 1
    assert all(API._NEW_CLAUSE in node.instructions and API._OLD_CLAUSE not in node.instructions for node in nodes)
    assert len({id(runtime.planners[v].client) for v in range(1, 5)}) == 4
    for node in nodes:
        if "reference_policy" in node.config:
            assert node.config["reference_policy"] == runtime.reference_policy
        if hasattr(node, "roles"):
            assert node.roles.reference_policy == runtime.reference_policy
    assert runtime.reference_policy["source_configuration_sha256"] == runtime.manifest["live_runtime_configuration_sha256"]
    one = runtime.planners[1]
    _, payload, _ = one.client.prepare_request(PUBLIC, one.instructions, planner_version=1)
    assert json.loads(payload["messages"][1]["content"]) == {"athlete_input": PUBLIC["input"]}
    assert runtime.manifest["baseline_reference_access_changed"] is False
    assert [row["target"] for row in runtime.roles] == [runtime.planners[3].roles,
        runtime.planners[4].planner.roles, runtime.planners[4].planner.drafting.roles]


def test_original_real_client_and_role_budget_guards_still_reject_oversized_or_injected_requests():
    shared = load(ROOT / "src/champion_athletic_map/llm.py", "live_original_shared_budget")
    role_api = load(ROOT / "src/champion_athletic_map/role_adapter.py", "live_original_role_budget")
    preflight_path = next((ROOT / "artifacts/language_model/prompt_preflight").glob("*/prompt_preflight.py"))
    preflight = load(preflight_path, "live_original_preflight")
    client = shared.OllamaClient.__new__(shared.OllamaClient)
    client.output_schema, client.preflight, client.controls = {"type": "object"}, preflight, ["<CONTROL>"]
    role = role_api.RoleAdapter.__new__(role_api.RoleAdapter)
    role.client, role.shared = client, shared
    payload = {"model": "llama3.1:8b", "stream": False, "truncate": False, "shift": False,
        "format": client.output_schema, "messages": [{"role": "system", "content": "Original instructions"},
            {"role": "user", "content": '{"athlete_input":{"label":"fictional"}}'}],
        "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 2048}}
    for owner in (client, role):
        assert owner._budget_view(payload)["format"] == "json"
        oversized = deepcopy(payload)
        oversized["messages"][1]["content"] = "x" * (256 * 1024)
        with pytest.raises(ValueError, match="byte"):
            owner._budget_view(oversized)
        changed = deepcopy(payload)
        changed["messages"][1]["content"] = "literal <CONTROL> token"
        with pytest.raises(ValueError, match="control tokens"):
            owner._budget_view(changed)
        changed = deepcopy(payload)
        changed["options"]["num_ctx"] = 16384
        with pytest.raises(ValueError, match="context"):
            owner._budget_view(changed)


def test_constructor_keeps_frozen_sources_and_budget_methods_unchanged(project):
    base = FROZEN_TEST.base_runtime(project)
    original_budget = [base.planners[v].client._budget_view for v in range(1, 5)]
    original_role_budget = [row["target"]._budget_view.__func__ for row in base.roles]
    before = {path.relative_to(project): path.read_bytes() for path in project.rglob('*') if path.is_file()}
    runtime = API.build_runtime(project, {}, SCHEMA, public_record=deepcopy(PUBLIC), runtime_builder=lambda *a, **k: base)
    assert [runtime.planners[v].client._budget_view for v in range(1, 5)] == original_budget
    assert [row["target"]._budget_view.__func__ for row in runtime.roles] == original_role_budget
    assert {path.relative_to(project): path.read_bytes() for path in project.rglob('*') if path.is_file()} == before
    assert runtime.manifest["budget_guards_changed"] is False
    assert runtime.manifest["model_calls_during_construction"] == runtime.manifest["query_encoding_during_construction"] == 0
    assert runtime.manifest["frozen_reviewed_sources_modified"] is False


pytestmark = pytest.mark.requirement("31:live-reviewed-runtime")
