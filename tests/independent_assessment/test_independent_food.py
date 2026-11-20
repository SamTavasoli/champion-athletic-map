"""Test common food scoring with exact facts, coverage gaps and optional attribution."""

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[2] / "src/champion_athletic_map/independent_food.py"
spec = importlib.util.spec_from_file_location("independent_food_tests", PATH)
FOOD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(FOOD)


SOURCE = "https://fdc.nal.usda.gov/food-details/167762/nutrients"
PUBLIC = {"food_question": 'For the food "Strawberries, raw", how many grams of protein are recorded for 100 g?'}
PACKET = {"packet_id": "software-fixture-food-truth", "payload": {"food_lookup": [{"status": "found",
    "source_refs": [SOURCE], "data_version": "frozen-test-facts", "data": {"food_id": "167762", "description": "Strawberries, raw",
    "grams": "100", "nutrients": [{"nutrient_name": "Protein", "amount": "0.67", "unit": "G", "status": "available"},
        {"nutrient_name": "Energy", "amount": "32", "unit": "KCAL", "status": "available"}]}}]}}


def assess(text=None, *, food_id=None, source_ref=None, explanation=None, public=None, packet=None):
    response = {"response_type": "plan", "explanation": explanation or "Here is the requested calendar."}
    if text is not None:
        response["food_facts"] = [{"statement": text, "food_id": food_id, "source_ref": source_ref}]
    return {row["check_id"]: row for row in FOOD.assess_food(public or PUBLIC, response, packet or PACKET)}


def statuses(rows):
    return [rows[key]["status"] for key in FOOD.CHECK_IDS]


def test_omitted_food_answer_is_missing_not_a_claimed_wrong_number():
    rows = assess()
    assert statuses(rows) == ["violated", "unknown", "not_applicable"]
    assert rows[FOOD.CHECK_IDS[2]]["observed"]["attribution_presence"] == "absent"
    assert rows[FOOD.CHECK_IDS[2]]["observed"]["source_supported_claims"] == 0
    assert not rows[FOOD.CHECK_IDS[2]]["observed"]["all_recognized_numeric_claims_supported"]


@pytest.mark.parametrize("text", [
    "100 g Strawberries, raw contains 0.67 g protein",
    "100 g of Strawberries, raw: 0.670 grams Protein.",
    "Protein in 100g of raw strawberries: 0.67g",
    "Strawberries, raw provides 0.67 g protein per 100 g.",
    "100 g raw strawberries — 0.67 g protein.",
])
def test_plain_correct_answer_needs_no_catalogue_or_source_ids(text):
    rows = assess(text)
    assert statuses(rows) == ["met", "met", "not_applicable"]
    assert rows[FOOD.CHECK_IDS[2]]["observed"]["unattributed_recognized_claims"] == 1


def test_correct_answer_in_explanation_is_checked_like_structured_food_facts():
    rows = assess(explanation="The calendar is below. Protein in 100g of raw strawberries: 0.67g.")
    assert statuses(rows) == ["met", "met", "not_applicable"]


def test_source_attribution_is_a_separate_optional_measure():
    text = "100 g Strawberries, raw contains 0.67 g protein"
    plain = assess(text)
    cited = assess(text, food_id="167762", source_ref=SOURCE)
    assert statuses(cited) == ["met", "met", "met"]
    assert plain[FOOD.CHECK_IDS[1]]["status"] == cited[FOOD.CHECK_IDS[1]]["status"]
    assert not cited[FOOD.CHECK_IDS[2]]["required"]
    assert cited[FOOD.CHECK_IDS[2]]["observed"]["source_supported_claims"] == 1
    assert cited[FOOD.CHECK_IDS[2]]["observed"]["all_recognized_numeric_claims_supported"]


@pytest.mark.parametrize("food_id,source,status", [("wrong-id", SOURCE, "violated"),
    ("167762", None, "unknown"), (None, "https://unverified.example/food", "unknown")])
def test_attribution_problem_never_changes_correct_numeric_claim(food_id, source, status):
    rows = assess("100 g Strawberries, raw contains 0.67 g protein", food_id=food_id, source_ref=source)
    assert rows[FOOD.CHECK_IDS[1]]["status"] == "met"
    assert rows[FOOD.CHECK_IDS[2]]["status"] == status


@pytest.mark.parametrize("text", ["100 g Strawberries, raw contains 6.7 g protein",
    "100 g Strawberries, raw contains 0.7 g protein", "100 g Strawberries, raw contains 0.67 kcal protein",
    "100 g Strawberries, raw contains -0.67 g protein"])
def test_recognized_changed_values_or_units_are_actual_numeric_violations(text):
    assert statuses(assess(text))[:2] == ["met", "violated"]


@pytest.mark.parametrize("text", ["100 g Strawberries, raw contains about 0.67 g protein",
    "Approximately 100 g raw strawberries provides 0.67 g protein.",
    "Protein: roughly 0.7 g in 100 g raw strawberries.",
    "For 100 g strawberries, protein is around two-thirds of a gram."])
def test_approximate_or_unsupported_numeric_prose_remains_unknown(text):
    rows = assess(text)
    assert rows[FOOD.CHECK_IDS[1]]["status"] == "unknown"
    assert rows[FOOD.CHECK_IDS[0]]["status"] == "unknown"


def test_exact_scaling_does_not_use_binary_float_or_an_undeclared_tolerance():
    public = {"food_question": 'For the food "Strawberries, raw", how many grams of protein are recorded for 150 g?'}
    rows = assess("150 g Strawberries, raw contains 1.005 g protein", public=public)
    assert statuses(rows)[:2] == ["met", "met"]
    assert assess("150 g Strawberries, raw contains 1.01 g protein", public=public)[FOOD.CHECK_IDS[1]]["status"] == "violated"


def test_correct_fact_for_wrong_quantity_is_not_a_false_numeric_fact():
    rows = assess("50 g Strawberries, raw contains 0.335 g protein")
    assert statuses(rows)[:2] == ["violated", "met"]


def test_correct_energy_fact_does_not_fulfill_a_protein_question():
    rows = assess("100 g Strawberries, raw contains 32 kcal Energy")
    assert statuses(rows)[:2] == ["violated", "met"]


def test_energy_question_and_kilocalorie_unit_are_supported():
    public = {"food_question": 'For the food "Strawberries, raw", how many kilocalories of energy are recorded for 150 g?'}
    assert statuses(assess("Energy in 150g of raw strawberries: 48 kilocalories", public=public))[:2] == ["met", "met"]


def test_conflicting_food_claims_do_not_pass_by_selecting_the_correct_one():
    response = {"explanation": "100 g Strawberries, raw contains 0.67 g protein. 100 g Strawberries, raw contains 6.7 g protein."}
    rows = {row["check_id"]: row for row in FOOD.assess_food(PUBLIC, response, PACKET)}
    assert statuses(rows)[:2] == ["met", "violated"]
    assert len(rows[FOOD.CHECK_IDS[1]]["observed"]["comparisons"]) == 2


def test_alias_requires_exact_source_identity_and_description():
    other = deepcopy(PACKET)
    other["payload"]["food_lookup"][0]["data"]["food_id"] = "different-id"
    assert assess("Protein in 100g of raw strawberries:0.67g", packet=other)[FOOD.CHECK_IDS[1]]["status"] == "unknown"


def test_unrecognized_question_never_receives_a_guessed_completeness_pass():
    public = {"food_question": "How nutritious are strawberries?"}
    rows = assess("100 g Strawberries, raw contains 0.67 g protein", public=public)
    assert statuses(rows)[:2] == ["unknown", "met"]


def test_empty_reference_truth_does_not_prove_factual_incorrectness():
    packet = {"payload": {"food_lookup": []}}
    rows = assess("100 g Strawberries, raw contains 0.67 g protein", packet=packet)
    assert rows[FOOD.CHECK_IDS[1]]["status"] == "unknown"


def test_grounding_claim_in_unsupported_wording_is_not_reported_absent():
    rows = assess("Protein is roughly two-thirds of a gram per 100 g.", food_id="167762", source_ref=SOURCE)
    assert rows[FOOD.CHECK_IDS[2]]["status"] == "unknown"
    assert rows[FOOD.CHECK_IDS[2]]["observed"]["attribution_presence"] == "present"


@pytest.mark.parametrize("structured", [True, False])
def test_bare_numeric_answer_is_unsupported_not_proven_omitted(structured):
    rows = assess("0.67 g") if structured else assess(explanation="0.67 g")
    assert statuses(rows)[:2] == ["unknown", "unknown"]


def test_food_answer_in_other_public_response_text_is_not_reported_omitted():
    response = {"explanation": "See the schedule.", "weekly_schedule": [{"activities": [
        {"description": "100 g Strawberries, raw contains 0.67 g protein"}]}]}
    rows = {row["check_id"]: row for row in FOOD.assess_food(PUBLIC, response, PACKET)}
    assert statuses(rows)[:2] == ["met", "met"]


def test_matching_response_evidence_url_can_ground_without_food_id():
    response = {"explanation": "100 g Strawberries, raw contains 0.67 g protein", "evidence_refs": [SOURCE]}
    rows = {row["check_id"]: row for row in FOOD.assess_food(PUBLIC, response, PACKET)}
    assert statuses(rows) == ["met", "met", "met"]


def test_resolving_source_identity_does_not_claim_support_for_a_wrong_number():
    rows = assess("100 g Strawberries, raw contains 6.7 g protein", source_ref=SOURCE)
    assert statuses(rows) == ["met", "violated", "violated"]
    observed = rows[FOOD.CHECK_IDS[2]]["observed"]
    assert observed["source_identity_resolved_claims"] == 1 and observed["source_supported_claims"] == 0


def test_conflicting_assessment_truth_stays_unknown_instead_of_choosing_a_record():
    packet = deepcopy(PACKET)
    second = deepcopy(packet["payload"]["food_lookup"][0])
    second["data"]["nutrients"][0]["amount"] = "9.67"
    packet["payload"]["food_lookup"].append(second)
    rows = assess("100 g Strawberries, raw contains 0.67 g protein", packet=packet)
    assert rows[FOOD.CHECK_IDS[1]]["status"] == "unknown"


def test_questionless_calendar_has_no_food_obligation():
    rows = {row["check_id"]: row for row in FOOD.assess_food({}, {"explanation": "Here is the calendar."}, PACKET)}
    assert statuses(rows) == ["not_applicable", "not_applicable", "not_applicable"]


def test_inputs_stay_unchanged_and_planner_identity_is_not_an_assessor_input():
    response = {"explanation": "100 g Strawberries, raw contains 0.67 g protein"}
    before = deepcopy((PUBLIC, response, PACKET))
    results = [FOOD.assess_food(PUBLIC, {**response, "planner_version": version}, PACKET) for version in range(1, 5)]
    assert all(value == results[0] for value in results)
    assert (PUBLIC, response, PACKET) == before


pytestmark = pytest.mark.requirement("31:independent-food-assessment")
