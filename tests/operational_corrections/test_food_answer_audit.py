"""Check exact echoes separately from actual food answers and unresolved prose."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/champion_athletic_map/food_answer_audit.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


API = load(SOURCE, "question_echo_audit_under_test")
FOOD = load(ROOT / "src/champion_athletic_map/independent_food.py", "question_echo_frozen_food")
PUBLIC = {"food_question": 'For the food "Strawberries, raw", how many grams of protein are recorded for 100 g?'}
PACKET = {"payload": {"food_lookup": [{"status": "found", "source_refs": ["https://example.invalid/frozen-fixture"],
    "data": {"food_id": "167762", "description": "Strawberries, raw", "grams": "100",
        "nutrients": [{"nutrient_name": "Protein", "amount": "0.67", "unit": "G", "status": "available"}]}}]}}
CORRECT = "100 g Strawberries, raw contains 0.67 g protein"


def reply(*statements, explanation="Here is the requested calendar."):
    return {"response_type": "plan", "explanation": explanation,
        "food_facts": [{"statement": text} for text in statements]}


def assess(response, *, public=None):
    return API.assess_food(PUBLIC if public is None else public, response, PACKET, base_assess_food=FOOD.assess_food)


def states(checks):
    return [row["status"] for row in checks]


def test_exact_question_echo_is_missing_answer_not_an_asserted_wrong_numeric_fact():
    checks = assess(reply(PUBLIC["food_question"]))
    assert states(checks)[:2] == ["violated", "unknown"]
    assert checks[0]["food_answer_audit"]["question_echo_paths"] == ["/food_facts/0/statement"]
    assert checks[1]["observed"]["comparisons"] == []
    assert checks[1]["observed"]["unsupported_numeric_segments"] == []


def test_whitespace_and_case_normalization_remove_only_the_same_complete_wording():
    question = "  " + PUBLIC["food_question"].upper().replace(" ", "\n ") + "  "
    response = reply(question, explanation=question)
    checks = assess(response)
    assert states(checks)[:2] == ["violated", "unknown"]
    assert set(checks[0]["food_answer_audit"]["question_echo_paths"]) == {"/explanation", "/food_facts/0/statement"}


def test_separate_correct_answer_still_passes_when_an_exact_echo_is_also_present():
    checks = assess(reply(PUBLIC["food_question"], CORRECT))
    assert states(checks)[:2] == ["met", "met"]
    assert len(checks[1]["observed"]["comparisons"]) == 1
    assert checks[1]["observed"]["unsupported_numeric_segments"] == []


def test_echo_plus_explicit_unavailability_remains_unverified_not_correct():
    checks = assess(reply(PUBLIC["food_question"], "The recorded protein value is unknown from the supplied information."))
    assert states(checks)[:2] == ["unknown", "unknown"]
    assert checks[0]["food_answer_audit"]["question_echo_count"] == 1


def test_other_unrecognized_food_prose_retains_the_frozen_assessment_statuses():
    response = reply("The protein in these berries is approximately two-thirds of a gram per serving.")
    old = FOOD.assess_food(PUBLIC, response, PACKET)
    new = assess(response)
    assert states(new) == states(old)
    assert states(new)[:2] == ["unknown", "unknown"]
    assert new[0]["food_answer_audit"]["question_echo_paths"] == []


def test_no_public_food_question_leaves_all_findings_and_observations_unchanged():
    response = reply(explanation="The calendar has been prepared.")
    old = FOOD.assess_food({}, response, PACKET)
    new = assess(response, public={})
    assert states(new) == states(old)
    assert all(a["reason"] == b["reason"] and a["observed"] == b["observed"] for a, b in zip(new, old))
    assert new[0]["food_answer_audit"]["question_echo_count"] == 0


def test_reply_metadata_and_supplied_source_fields_are_never_changed_or_removed():
    response = reply(PUBLIC["food_question"])
    response["food_facts"][0].update(food_id=PUBLIC["food_question"], source_ref=PUBLIC["food_question"])
    response["evidence_refs"] = [PUBLIC["food_question"]]
    before = deepcopy((PUBLIC, response, PACKET))
    captured = []
    def base(public, value, packet):
        captured.append(deepcopy(value))
        return FOOD.assess_food(public, value, packet)
    API.assess_food(PUBLIC, response, PACKET, base_assess_food=base)
    assert (PUBLIC, response, PACKET) == before
    assert captured[0]["food_facts"][0]["statement"] == ""
    assert captured[0]["food_facts"][0]["food_id"] == PUBLIC["food_question"]
    assert captured[0]["food_facts"][0]["source_ref"] == PUBLIC["food_question"]
    assert captured[0]["evidence_refs"] == [PUBLIC["food_question"]]


def test_echo_audit_does_not_hide_an_actual_incorrect_food_claim():
    checks = assess(reply(PUBLIC["food_question"], "100 g Strawberries, raw contains 6.7 g protein"))
    assert states(checks)[:2] == ["met", "violated"]
    assert len(checks[1]["observed"]["comparisons"]) == 1


def test_real_independent_assessor_retains_all_checks_and_original_raw_reply():
    fixtures = load(ROOT / "tests/independent_assessment/test_independent_plan_assessment.py", "echo_audit_calendar_fixtures")
    public = fixtures.public()
    public.update(PUBLIC)
    value = fixtures.response(concrete=True)
    value["food_facts"] = [{"statement": PUBLIC["food_question"]}]
    outcome = fixtures.outcome(value, internally_accepted=True)
    record = {"profile_id": "software:question-echo", "schema_version": "athlete-profile-input-2", "input": public}
    before = deepcopy((record, outcome))
    assessor = API.make_assessor(ROOT, fixtures.SCHEDULE.build_input_schema(fixtures.BASE))
    result = assessor.assess(record, outcome, PACKET, assessment_id="software_question_echo")
    assert result["assessment_execution"] == "completed"
    assert len(result["checks"]) == len(result["expected_check_ids"]) == 43
    assert {row["check_id"] for row in result["checks"]} == set(result["expected_check_ids"])
    assert "food_answer_completeness" in result["required_violations"]
    assert result["overall"] == "requirements_violated"
    assert result["internal_evaluator_used_for_verdict"] is False
    assert result["food_answer_audit_version"] == API.VERSION
    assert (record, outcome) == before
    assert result["saved_raw_reply_changed"] is False


pytestmark = pytest.mark.requirement("31:exact-question-echo-food-assessment")
