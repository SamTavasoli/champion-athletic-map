"""Exercise common offline requirements without an evaluator's acceptance flag."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    result.__spec__.loader.exec_module(result)
    return result


API = load(ROOT / "src/champion_athletic_map/independent_plan_assessment.py", "independent_plan_tests")
FIX = load(ROOT / "tests/unit/test_rule_checks.py", "independent_calendar_fixtures")
RESOURCE_FIX = load(ROOT / "tests/independent_assessment/test_independent_resources.py", "independent_resource_fixtures")
FOOD_FIX = load(ROOT / "tests/independent_assessment/test_independent_food.py", "independent_food_fixtures")
SCHEDULE = load(ROOT / "src/champion_athletic_map/pilot_schedule.py", "independent_public_schema")
INTEGRATION = json.loads((ROOT / "artifacts/language_model/integration_config.json").read_bytes())
BASE = json.loads((ROOT / INTEGRATION["contracts_directory"] / "public_profile_record_schema.json").read_bytes())


def public():
    value = FIX.public()
    value["schedule_coverage"] = {**value["planning_window"], "existing_commitments_complete": True}
    return value


def response(count=2, *, concrete=False):
    activities = [FIX.session("activity_" + str(i), duration=10, start=(17 * 60) + 15 * i) for i in range(count)]
    for activity in activities:
        activity["description"] = RESOURCE_FIX.STATIONARY if concrete else "Basketball session to work on ball control"
    return FIX.plan(activities)


def outcome(value, **extra):
    return {"completion_valid": True, "format_valid": True,
        "response": {"model_output": {"raw_text": json.dumps(value, ensure_ascii=False)}}, **extra}


@pytest.fixture
def assessor():
    return API.IndependentAssessor(ROOT, SCHEDULE.build_input_schema(BASE))


def assess(assessor, value=None, answer=None, **extra):
    public_input = value or public()
    record = {"profile_id": "software:independent", "schema_version": "athlete-profile-input-2", "input": public_input}
    return assessor.assess(record, outcome(answer or response(), **extra), FOOD_FIX.PACKET, assessment_id="authored_software_case")


def test_all_common_required_checks_have_a_positive_path_without_catalog_ids(assessor):
    report = assess(assessor, answer=response(concrete=True))
    assert report["assessment_execution"] == "completed"
    assert report["overall"] == "declared_checks_supported", report["required_unknowns"]
    assert not report["required_unknowns"] and not report["required_violations"]
    assert report["quality_or_safety_certified"] is False and report["final_study_score"] is None


def test_same_resources_can_fit_declarations_but_have_unverified_real_requirements(assessor):
    report = assess(assessor)
    rows = {row["check_id"]: row for row in report["checks"]}
    assert rows["declared_resource_consistency"]["status"] == "met"
    assert rows["resource_requirements_evidence"]["status"] == "unknown"
    assert report["overall"] == "requirements_unverified"


def test_three_roots_do_not_satisfy_two_requested_sessions_even_under_cap_three(assessor):
    value = public()
    value["time_limits"]["max_additional_sessions_per_week"] = 3
    report = assess(assessor, value, response(3))
    rows = {row["check_id"]: row for row in report["checks"]}
    assert rows["requested_session_count"]["status"] == "violated"
    assert rows["requested_session_count"]["observed"]["known_additional_roots"] == 3
    assert rows["additional_training_limits"]["status"] == "met"


def test_food_accuracy_is_separate_from_citations_and_internal_verdict(assessor):
    value = public()
    value.update(FOOD_FIX.PUBLIC)
    answer = response(concrete=True)
    answer["food_facts"] = [{"statement": "100 g raw strawberries contains 0.67 g protein"}]
    report = assess(assessor, value, answer, internally_accepted=False,
        acceptance={"accepted": False, "blocking_evaluator_categories": ["scope"]})
    rows = {row["check_id"]: row for row in report["checks"]}
    assert rows["food_answer_completeness"]["status"] == rows["food_numeric_correctness"]["status"] == "met"
    assert rows["food_source_grounding"]["required"] is False
    assert report["overall"] == "declared_checks_supported"
    assert report["internal_evaluator_used_for_verdict"] is False


def test_omitted_requested_food_answer_remains_a_completeness_failure(assessor):
    value = public()
    value.update(FOOD_FIX.PUBLIC)
    report = assess(assessor, value, response(concrete=True), internally_accepted=True)
    assert "food_answer_completeness" in report["required_violations"]
    assert "food_numeric_correctness" in report["required_unknowns"]


def test_components_are_not_extra_sessions_and_invalid_graph_cannot_pass(assessor):
    answer = response(concrete=True)
    child = FIX.session("component", duration=5, start=17 * 60, parent="activity_0")
    child["description"] = RESOURCE_FIX.STATIONARY
    answer["weekly_schedule"][0]["activities"].append(child)
    report = assess(assessor, answer=answer)
    rows = {row["check_id"]: row for row in report["checks"]}
    assert rows["requested_session_count"]["observed"]["known_additional_roots"] == 2
    assert rows["requested_session_count"]["status"] == "met"
    child["relationship"]["parent_activity_id"] = "component"
    report = assess(assessor, answer=answer)
    assert report["overall"] != "declared_checks_supported"
    assert "resource_requirements_evidence" in report["required_unknowns"]


@pytest.mark.parametrize("inside_existing", [False, True])
def test_child_resource_shortage_is_not_hidden_inside_parent_session(assessor, inside_existing):
    value, answer = public(), response(concrete=True)
    parent = "activity_0"
    start = 17 * 60
    if inside_existing:
        value["existing_commitments"] = [FIX.commitment(10, start=16 * 60)]
        preserved = FIX.session("existing", 10, start=16 * 60, refs=["/existing_commitments/0"])
        answer["weekly_schedule"][0]["activities"].insert(0, preserved)
        parent, start = "existing", 16 * 60
    child = FIX.session("shooting_component", 5, start=start, parent=parent)
    child["description"] = RESOURCE_FIX.FORM
    child["resources"]["participants"] = 2
    answer["weekly_schedule"][0]["activities"].append(child)
    report = assess(assessor, value, answer)
    assert "resource_requirements_evidence" in report["required_violations"]
    assert any(item.get("activity_id") == "shooting_component" for item in report["resources"]["per_activity"])


def test_missing_external_required_rows_cannot_make_a_pass(assessor, monkeypatch):
    monkeypatch.setattr(assessor.food, "assess_food", lambda *args: [])
    with pytest.raises(ValueError, match="invalid or duplicate coverage"):
        assess(assessor, answer=response(concrete=True))


def test_missing_designated_reply_does_not_fall_back_to_an_earlier_draft(assessor):
    record = {"profile_id": "software:failure", "schema_version": "athlete-profile-input-2", "input": public()}
    failed = {"completion_valid": False, "response": None, "draft_result": outcome(response(concrete=True))}
    report = assessor.assess(record, failed, FOOD_FIX.PACKET, assessment_id="original_failed_job")
    assert "execution_completion" in report["required_violations"]
    assert "output_structure" in report["required_violations"]
    assert report["raw_response_sha256"] is None


@pytest.mark.parametrize("request_text,expected", [("Plan two extra basketball sessions.", 2),
    ("Plan 3 additional practices.", 3), ("No additional training this week.", 0),
    ("Two balls are available for practice.", None)])
def test_literal_request_grammar_does_not_convert_cap_or_equipment_into_a_request(request_text, expected):
    assert API.requested_count({"athlete_request": request_text})[0] == expected


def test_noninterpreted_numeric_request_stays_unknown():
    value = public()
    value["athlete_request"] = "Arrange 2 sessions for me."
    check = API.session_check(value, response(), structure_valid=True)
    assert check["status"] == "unknown"


pytestmark = pytest.mark.requirement("31:independent-saved-plan-assessment")

