"""Check the prospective corrections against saved failures and distinct counterexamples."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if not (ROOT / "src/champion_athletic_map").is_dir():
    ROOT = HERE.parent / "work_step30/project/folder-before-step-30"
SOURCE = ROOT / "src/champion_athletic_map/reviewed_planning_checks.py"
if not SOURCE.is_file():
    SOURCE = HERE / "reviewed_planning_checks.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


API = load(SOURCE, "reviewed_checks_under_test")
fixture_path = HERE / "saved_checker_fixtures.json"
DATA = json.loads(fixture_path.read_bytes())
INTEGRATION = json.loads((ROOT / "artifacts/language_model/integration_config.json").read_bytes())
BASE = json.loads((ROOT / INTEGRATION["contracts_directory"] / "public_profile_record_schema.json").read_bytes())
SCHEMA = API._module(ROOT, "pilot_schedule").build_input_schema(BASE)


@pytest.fixture
def assessor():
    return API.make_assessor(ROOT, SCHEMA)


def saved(case, version):
    record = next(row for row in DATA["rows"] if row["case"] == case and row["planner_version"] == version)
    return deepcopy(DATA["cases"][str(case)]["public_record"]), deepcopy(record["outcome"]), deepcopy(DATA["cases"][str(case)]["packet"])


def assess(assessor, values):
    result = assessor.assess(*values, assessment_id="software:prospective-review")
    assert result["assessment_execution"] == "completed", result
    assert len(result["checks"]) == len(result["expected_check_ids"]) == 43
    assert {q["check_id"] for q in result["checks"]} == set(result["expected_check_ids"])
    assert result["old_saved_assessments_replaced"] is False and result["human_review_claimed"] is False
    by_id = {q["check_id"]: q for q in result["checks"]}
    assert set(result["required_violations"]) == {q["check_id"] for q in result["checks"] if q["required"] and q["status"] == "violated"}
    assert set(result["required_unknowns"]) == {q["check_id"] for q in result["checks"] if q["required"] and q["status"] == "unknown"}
    return result, by_id


def replace_reply(outcome, response):
    outcome["response"]["model_output"]["raw_text"] = json.dumps(response, ensure_ascii=False)
    outcome["response"]["model_output"]["parsed_object"] = deepcopy(response)
    outcome["response_type"] = response["response_type"]
    return outcome


def test_saved_rest_explanation_has_a_known_applicable_source_and_complete_coverage(assessor):
    values = saved(4, 2)
    before = deepcopy(values)
    result, rows = assess(assessor, values)
    assert rows["response_type_basis"]["status"] == "met"
    assert rows["rule:POLICY_REQUIRED_INFORMATION"]["status"] == "met"
    assert rows["existing_commitments"]["status"] == "not_applicable"
    assert result["overall"] == "declared_checks_supported"
    assert values == before


@pytest.mark.parametrize("version", [1, 3, 4])
def test_saved_soccer_or_600_minute_claim_does_not_prove_the_daily_rest_conflict(assessor, version):
    result, rows = assess(assessor, saved(4, version))
    assert rows["response_type_basis"]["status"] == "unknown"
    assert rows["rule:POLICY_REQUIRED_INFORMATION"]["status"] == "unknown"
    assert rows["rule:POLICY_SCOPE"]["status"] == "unknown"
    assert result["overall"] == "requirements_unverified"


def test_rest_support_is_not_inferred_without_complete_coverage(assessor):
    public, outcome, packet = saved(4, 2)
    public["input"]["schedule_coverage"]["existing_commitments_complete"] = False
    _, rows = assess(assessor, (public, outcome, packet))
    assert rows["response_type_basis"]["status"] == "unknown"


@pytest.mark.parametrize("version", [2, 3, 4])
def test_saved_bad_graph_does_not_itself_prove_a_numeric_limit_overrun(assessor, version):
    _, rows = assess(assessor, saved(9, version))
    assert rows["activity_accounting"]["status"] == "violated"
    assert rows["additional_training_limits"]["status"] == "unknown"
    assert rows["rule:USER_AVAILABLE_TIME"]["status"] == "unknown"
    assert rows["rule:POLICY_SESSION_ACCOUNTING"]["status"] == "violated"
    assert rows["additional_training_limits"]["observed"]["proven_overruns"] == {}


def test_a_real_numeric_lower_bound_still_blocks_a_bad_graph(assessor):
    public, outcome, packet = saved(9, 3)
    public["input"]["time_limits"]["max_additional_minutes_per_week"] = 50
    _, rows = assess(assessor, (public, outcome, packet))
    assert rows["activity_accounting"]["status"] == "violated"
    assert rows["additional_training_limits"]["status"] == "violated"
    assert rows["additional_training_limits"]["observed"]["numeric_lower_bounds"]["max_additional_minutes_per_week"] == 90


def test_saved_zero_minute_conflict_needs_the_actual_limit_in_its_explanation(assessor):
    result, rows = assess(assessor, saved(16, 4))
    assert rows["response_type_basis"]["status"] == "unknown"
    assert result["overall"] == "requirements_unverified"


def test_explanation_matching_the_public_zero_minute_limit_is_supported(assessor):
    public, outcome, packet = saved(16, 4)
    response = {"response_type": "constraint_conflict", "explanation": "The requested 20 minutes cannot fit the weekly extra-training time limit of 0 minutes.",
                "unresolved_issues": ["The weekly extra-training minute limit is 0; adding 20 minutes exceeds it."]}
    _, rows = assess(assessor, (public, replace_reply(outcome, response), packet))
    assert rows["response_type_basis"]["status"] == "met"


def test_numbers_in_unrelated_sentences_do_not_support_a_generic_limit_claim(assessor):
    public, outcome, packet = saved(16, 4)
    response = {"response_type": "constraint_conflict", "explanation": "The athlete has 0 red balls. A training time limit conflicts with this request.",
                "unresolved_issues": ["There are 20 people nearby."]}
    _, rows = assess(assessor, (public, replace_reply(outcome, response), packet))
    assert rows["response_type_basis"]["status"] == "unknown"


def test_negated_limit_claim_is_not_a_supported_conflict(assessor):
    public, outcome, packet = saved(16, 4)
    response = {"response_type": "constraint_conflict", "explanation": "The request for 20 minutes does not exceed the weekly extra-training time limit of 0 minutes.",
                "unresolved_issues": ["No conflict exists."]}
    _, rows = assess(assessor, (public, replace_reply(outcome, response), packet))
    assert rows["response_type_basis"]["status"] == "unknown"


def test_existing_component_resources_do_not_become_a_new_training_shortage(assessor):
    public, outcome, packet = saved(9, 4)
    response = deepcopy(outcome["response"]["model_output"]["parsed_object"])
    soccer = response["weekly_schedule"][2]["activities"][0]
    assert soccer["existing_commitment_refs"]
    soccer["resources"]["equipment"] = [{"name": "A hundred supplied-event hoops", "quantity": 100}]
    _, rows = assess(assessor, (public, replace_reply(outcome, response), packet))
    assert rows["declared_resource_consistency"]["status"] == "unknown"
    assert rows["resource_requirements_evidence"]["status"] == "unknown"
    assert rows["activity_accounting"]["status"] == "violated"


def test_genuine_new_training_shortage_remains_a_violation(assessor):
    public, outcome, packet = saved(2, 4)
    public["input"]["food_question"] = None
    response = deepcopy(outcome["response"]["model_output"]["parsed_object"])
    first = next(a for day in response["weekly_schedule"] for a in day["activities"])
    first["resources"]["equipment"] = [{"name": "Basketball", "quantity": 100}]
    _, rows = assess(assessor, (public, replace_reply(outcome, response), packet))
    assert rows["declared_resource_consistency"]["status"] == "violated"


@pytest.mark.parametrize("version", [3, 4])
def test_saved_ladder_declaration_shortage_is_not_waived(assessor, version):
    _, rows = assess(assessor, saved(18, version))
    assert rows["declared_resource_consistency"]["status"] == "violated"
    assert rows["resource_requirements_evidence"]["status"] == "unknown"


@pytest.mark.parametrize("version", [2, 3, 4])
def test_equivalent_quote_question_echo_is_still_a_missing_food_answer(assessor, version):
    _, rows = assess(assessor, saved(9, version))
    assert rows["food_answer_completeness"]["status"] == "violated"
    assert rows["food_numeric_correctness"]["status"] == "unknown"


def test_no_food_question_remains_not_applicable(assessor):
    public, outcome, packet = saved(2, 4)
    public["input"]["food_question"] = None
    response = deepcopy(outcome["response"]["model_output"]["parsed_object"])
    response.pop("food_facts", None)
    _, rows = assess(assessor, (public, replace_reply(outcome, response), packet))
    assert rows["food_answer_completeness"]["status"] == "not_applicable"
    assert rows["food_numeric_correctness"]["status"] == "not_applicable"


def test_correct_and_wrong_food_numbers_remain_distinct(assessor):
    public, outcome, _ = saved(2, 4)
    public["input"]["food_question"] = 'For the food "Strawberries, raw", how many grams of protein are recorded for 100 g?'
    packet = {"payload": {"references": [], "food_lookup": [{"status": "found", "source_refs": ["https://example.invalid/frozen-fixture"],
        "data": {"food_id": "167762", "description": "Strawberries, raw", "grams": "100",
                 "nutrients": [{"nutrient_name": "Protein", "amount": "0.67", "unit": "G", "status": "available"}]}}]}}
    response = deepcopy(outcome["response"]["model_output"]["parsed_object"])
    for amount, expected in (("0.67", "met"), ("6.7", "violated")):
        response["food_facts"] = [{"statement": f"100 g Strawberries, raw contains {amount} g protein"}]
        _, rows = assess(assessor, (public, replace_reply(outcome, response), packet))
        assert rows["food_answer_completeness"]["status"] == "met"
        assert rows["food_numeric_correctness"]["status"] == expected


def test_internal_checker_uses_the_same_prospective_scope_and_alias_corrections(assessor):
    public, outcome, packet = saved(9, 4)
    checker = API.make_checker(ROOT, assessor.client, {})
    report = checker.check(public, outcome["response"]["model_output"]["raw_text"], packet, candidate_id="software:internal-reviewed")
    assert report["execution_status"] == "completed"
    assert set(q["check_id"] for q in report["checks"]) == set(checker.expected_check_ids)
    rows = {q["check_id"]: q for q in report["checks"]}
    assert rows["additional_training_limits"]["status"] == "unknown"
    assert rows["rule:USER_AVAILABLE_TIME"]["status"] == "unknown"
    assert rows["food_facts_numeric"]["status"] == "violated"
    assert rows["activity_accounting"]["status"] == "violated"


def test_new_component_under_a_new_root_keeps_its_real_resource_shortage(assessor):
    public, outcome, packet = saved(2, 4)
    public["input"]["food_question"] = None
    response = deepcopy(outcome["response"]["model_output"]["parsed_object"])
    day = next(day for day in response["weekly_schedule"] if day["activities"])
    parent = day["activities"][0]
    child = deepcopy(parent)
    child.update(activity_id="new_component", relationship={"kind": "part_of_activity", "parent_activity_id": parent["activity_id"]})
    child["resources"]["equipment"] = [{"name": "Basketball", "quantity": 100}]
    day["activities"].append(child)
    _, rows = assess(assessor, (public, replace_reply(outcome, response), packet))
    assert rows["declared_resource_consistency"]["status"] == "violated"
    checker = API.make_checker(ROOT, assessor.client, {})
    report = checker.check(public, json.dumps(response), packet, candidate_id="software:new-component")
    assert report["execution_status"] == "completed"
    internal = {q["check_id"]: q for q in report["checks"]}
    assert internal["resource_feasibility"]["status"] == "violated"
    assert internal["rule:USER_EQUIPMENT_SPACE"]["status"] == "violated"


@pytest.mark.parametrize("declared", ["half-court", "half_court", "half court"])
def test_equivalent_half_court_literals_fit_known_half_court_supply(assessor, declared):
    public, outcome, packet = saved(2, 4)
    public["input"]["food_question"] = None
    public["input"]["space"].update(court_access="half_court", restrictions=[])
    response = deepcopy(outcome["response"]["model_output"]["parsed_object"])
    response.pop("food_facts", None)
    for day in response["weekly_schedule"]:
        for activity in day["activities"]:
            activity["resources"]["space"] = declared
    before = deepcopy((public, response))
    _, rows = assess(assessor, (public, replace_reply(outcome, response), packet))
    assert rows["declared_resource_consistency"]["status"] == "met"
    assert rows["resource_requirements_evidence"]["status"] == "unknown"
    assert (public, response) == before


def test_full_court_alias_still_exceeds_half_court_supply_in_both_checkers(assessor):
    public, outcome, packet = saved(2, 4)
    public["input"]["food_question"] = None
    public["input"]["space"].update(court_access="half_court", restrictions=[])
    response = deepcopy(outcome["response"]["model_output"]["parsed_object"])
    response.pop("food_facts", None)
    for day in response["weekly_schedule"]:
        for activity in day["activities"]:
            activity["resources"]["space"] = "full-court"
    _, rows = assess(assessor, (public, replace_reply(outcome, response), packet))
    assert rows["declared_resource_consistency"]["status"] == "violated"
    checker = API.make_checker(ROOT, assessor.client, {})
    internal = checker.check(public, json.dumps(response), packet, candidate_id="software:space-alias")
    assert internal["execution_status"] == "completed"
    by_id = {q["check_id"]: q for q in internal["checks"]}
    assert by_id["resource_feasibility"]["status"] == "violated"


def test_restricted_rectangle_prose_does_not_acquire_an_alias_proof(assessor):
    public, outcome, packet = saved(2, 4)
    public["input"]["food_question"] = None
    public["input"]["space"].update(court_access="none", restrictions=["Only one person may move in the rectangle."])
    response = deepcopy(outcome["response"]["model_output"]["parsed_object"])
    response.pop("food_facts", None)
    text = "Clear, level practice rectangle 6 m long and 4 m wide with a waiting area."
    for day in response["weekly_schedule"]:
        for activity in day["activities"]:
            activity["resources"]["space"] = text
    assert API._space_alias(text) == text
    _, rows = assess(assessor, (public, replace_reply(outcome, response), packet))
    assert rows["declared_resource_consistency"]["status"] == "unknown"
    assert rows["resource_requirements_evidence"]["status"] == "unknown"


def test_reversed_timing_is_not_used_as_a_positive_duration_lower_bound():
    public, outcome, _ = saved(2, 4)
    value = public["input"]
    value["time_limits"]["max_additional_minutes_per_week"] = 0
    response = deepcopy(outcome["response"]["model_output"]["parsed_object"])
    for day in response["weekly_schedule"]:
        for activity in day["activities"]:
            activity["timing"] = {"start_time": "17:50", "end_time": "17:30"}
    row = {"check_id": "additional_training_limits"}
    API._numeric_limit_correction(value, response, {"accounting_status": "violated"}, row)
    assert row["status"] == "unknown"
    assert row["observed"]["numeric_lower_bounds"]["max_additional_minutes_per_week"] == 0


pytestmark = pytest.mark.requirement("31:reviewed-development-checks")
