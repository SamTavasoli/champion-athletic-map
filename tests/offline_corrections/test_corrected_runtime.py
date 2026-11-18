"""Keep the correction in the real checker and only the V4 revision handoff."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
ROOT = next((p for p in HERE.parents if (p / "src/champion_athletic_map/live_reviewed_runtime.py").is_file()),
            HERE.parent / "work_step30/project/folder-before-step-30")


def load(path, name):
    value = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    value.__spec__.loader.exec_module(value)
    return value


SOURCE = HERE / "corrected_runtime.py"
if not SOURCE.is_file():
    SOURCE = ROOT / "src/champion_athletic_map/corrected_runtime.py"
API = load(SOURCE, "corrected_runtime_under_test")
HELPERS = load(ROOT / "tests/reviewed_probe/test_live_reviewed_runtime.py", "corrected_live_graph_helpers")


@pytest.fixture
def project(tmp_path):
    root = HELPERS.project.__wrapped__(tmp_path)
    for name in ("corrected_runtime", "bounded_revision", "food_response_validation"):
        source = HERE / (name + ".py")
        if not source.is_file():
            source = ROOT / "src/champion_athletic_map" / (name + ".py")
        (root / "src/champion_athletic_map" / (name + ".py")).write_bytes(source.read_bytes())
    # This explicit graph double resolves its food helper like the real checker.
    (root / API.CHECKS).write_text('''from copy import copy
from types import SimpleNamespace
import importlib.util
from pathlib import Path
def _module(root,name):
    path=Path(root)/"src/champion_athletic_map"/(name+".py")
    v=importlib.util.module_from_spec(importlib.util.spec_from_file_location("fixture_"+name,path))
    v.__spec__.loader.exec_module(v)
    return v
def make_checker(root,client,policy,resources=None):
    food=_module(root,"food_fact_focus")
    return SimpleNamespace(client=copy(client), resources=resources,
        pilot_schedule_policy={"fixture":True}, active_food_parser=food.assess_food,
        check=lambda *a,**k:{"explicit_graph_fixture":True})
def make_assessor(root,schema):
    return SimpleNamespace(active_food_parser=_module(root,"food_fact_focus").assess_food,
        dependency_sha256={},assess=lambda *a,**k:{"fixture":True})
''', encoding="utf-8")
    return root


def test_runtime_changes_only_revision_role_and_keeps_baseline_and_all_shared_facts(project):
    original = HELPERS.FROZEN_TEST.base_runtime(project)
    old_roles = [row["target"] for row in original.roles]
    snapshots = {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob("*.py")}
    result = API.build_runtime(project, {}, HELPERS.SCHEMA, public_record=deepcopy(HELPERS.PUBLIC),
        runtime_builder=lambda *args, **kwargs: original)
    assert len(result.roles) == 3
    assert result.roles[0]["target"] is not result.roles[1]["target"]
    assert result.roles[1]["target"] is result.planners[4].planner.roles
    assert type(result.roles[1]["target"]).__name__ == "CorrectedRevisionRole"
    assert type(result.roles[0]["target"]).__name__ != "CorrectedRevisionRole"
    assert type(result.roles[2]["target"]).__name__ != "CorrectedRevisionRole"
    assert result.checker.client is result.planners[4].client
    assert result.checker.active_food_parser.__code__.co_filename.endswith("food_response_validation.py")
    nodes = [result.planners[v] for v in range(1, 5)] + [result.planners[4].planner, result.planners[4].planner.drafting]
    assert len({node.instructions for node in nodes}) == 1
    assert len({id(result.planners[v].client) for v in range(1, 5)}) == 4
    for node in nodes:
        if "reference_policy" in node.config:
            assert node.config["reference_policy"] == result.reference_policy
        if hasattr(node, "roles"):
            assert node.roles.reference_policy == result.reference_policy
    baseline = result.planners[1]
    _, payload, _ = baseline.client.prepare_request(HELPERS.PUBLIC, baseline.instructions, planner_version=1)
    assert json.loads(payload["messages"][1]["content"]) == {"athlete_input": HELPERS.PUBLIC["input"]}
    assert result.manifest["model_output_autofilled_or_repaired"] is False
    assert result.manifest["output_and_context_limits_changed"] is False
    assert result.manifest["operational_generation_ready"] is False
    for relative, data in snapshots.items():
        assert (project / relative).read_bytes() == data


def actual_case13_v2():
    summary = json.loads((ROOT / "results/step31_reviewed_probe_summary.json").read_bytes())
    case = next(c for c in summary["cases"] if c["case_index"] == 13)
    record = next(r for r in case["reports"] if r["planner_version"] == 2)
    outcome = json.loads((ROOT / record["outcome_path"]).read_bytes())
    parent = Path(record["outcome_path"]).parents[2]
    packet = json.loads((ROOT / parent / "references" / record["job_id"] / "packet.json").read_bytes())
    source = json.loads((ROOT / "artifacts/pilot/shared_guidance/pilotcase_88d6bfee05772bb8_c13/probe_manifest.json").read_bytes())
    return source, outcome, packet


def test_real_independent_and_internal_checker_keep_incomplete_food_field_blocked():
    source, outcome, packet = actual_case13_v2()
    schema = json.loads((ROOT / source["public_schema_path"]).read_bytes())
    assessor = API.make_assessor(ROOT, schema)
    before = deepcopy(outcome)
    result = assessor.assess(source["public_record"], outcome, packet, assessment_id="software:corrected-food")
    rows = {r["check_id"]: r for r in result["checks"]}
    assert len(rows) == 43
    assert rows["food_numeric_correctness"]["status"] == "met"
    assert rows["food_answer_completeness"]["status"] == "violated"
    assert result["overall"] == "requirements_violated"
    assert result["original_saved_assessments_changed"] is False
    assert set(result["food_validation_active_source_sha256"]) == {
        "src/champion_athletic_map/corrected_runtime.py", "src/champion_athletic_map/food_response_validation.py"}
    assert all(assessor.dependency_sha256[k] == v for k, v in result["food_validation_active_source_sha256"].items())
    checker = API.food_checker_api(ROOT).make_checker(ROOT, assessor.client, {}, resources=assessor.calendar.resources)
    checked = checker.check(source["public_record"], outcome["response"]["model_output"], packet,
                            candidate_id="software:corrected-internal")
    by_id = {r["check_id"]: r for r in checked["checks"]}
    assert by_id["food_facts_numeric"]["status"] == "violated"
    assert outcome == before


def test_role_keeps_original_generate_transport_and_skips_nonrevision_transforms():
    revision = API.load(ROOT, "src/champion_athletic_map/bounded_revision.py")
    payload = {"messages": [{"role": "user", "content": "unchanged evaluator input"}]}
    class Role:
        def __init__(self):
            self.guards = 0
        def prepare_request(self, *args, **kwargs):
            return {"public_input": {}}, deepcopy(payload), {"stage": kwargs["stage"]}
        def _budget_view(self, value):
            self.guards += 1
        def generate(self):
            return "original transport retained"
    old = Role()
    wrapped = API.revision_role(old, revision)
    prepared, result, config = wrapped.prepare_request(stage="evaluator")
    assert result == payload and config == {"stage": "evaluator"}
    assert wrapped.guards == 0
    assert type(wrapped).generate is Role.generate
    assert wrapped.generate() == "original transport retained"


pytestmark = pytest.mark.requirement("31:bounded-revision-and-food-runtime")
