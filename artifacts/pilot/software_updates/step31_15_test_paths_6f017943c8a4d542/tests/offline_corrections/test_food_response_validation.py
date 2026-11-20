from collections import Counter
from copy import deepcopy
from pathlib import Path
import importlib.util
import json

import pytest


HERE = Path(__file__).resolve().parent
PROJECT = next((p for p in (HERE, *HERE.parents) if (p / "src/champion_athletic_map").is_dir()), None)
SOURCE = HERE / "food_response_validation.py"
if not SOURCE.is_file() and PROJECT is not None:
    SOURCE = PROJECT / "src/champion_athletic_map/food_response_validation.py"
spec = importlib.util.spec_from_file_location("tested_new_food_validation", SOURCE)
food = importlib.util.module_from_spec(spec)
spec.loader.exec_module(food)
QUESTION = 'For the food "Blueberries, raw", how many grams of protein are recorded for 250 g?'
CORRECT = "250g of Blueberries, raw contains 1.85g of protein."


@pytest.fixture
def public():
    return {"food_question": QUESTION}


@pytest.fixture
def packet():
    data = {"food_id": "171711", "description": "Blueberries, raw", "grams": "250", "nutrients": []}
    for nutrient_id, name, amount, raw, unit in [("1003", "Protein", "1.85", "0.74", "G"),
                                               ("1008", "Energy", "142.5", "57", "KCAL")]:
        data["nutrients"].append({"nutrient_id": nutrient_id, "nutrient_name": name, "amount": amount,
            "unit": unit, "fdc_id": "171711", "description": "Blueberries, raw", "grams": "250",
            "status": "available", "source_record_url": "https://fdc.nal.usda.gov/food-details/171711/nutrients",
            "source_footnote": "", "amount_per_100g_raw": raw, "reference_mass_g": "100"})
    return {"payload": {"food_lookup": [{"status": "found", "data": data,
        "source_refs": ["https://fdc.nal.usda.gov/food-details/171711/nutrients"]}]}}


def response(statement=CORRECT, explanation="We saved the requested answer."):
    return {"food_facts": [{"food_id": "171711", "source_ref": "https://fdc.nal.usda.gov/food-details/171711/nutrients",
                            "statement": statement}], "explanation": explanation}


@pytest.mark.parametrize("statement", [CORRECT,
    "250 g Blueberries, raw contains 1.85 g Protein.",
    "250 grams of Blueberries, raw, provides 1.850 grams of protein.",
    "Protein in 250g of Blueberries, raw is 1.85g.",
    "Blueberries, raw has 1.85g of protein per 250g.",
    "The supplied reference states that 250g of Blueberries, raw contains 1.85g of protein."])
def test_supported_field_forms_are_complete_and_numeric(statement, public, packet):
    diagnostic = food.diagnose_food(public, response(statement), packet)
    assert diagnostic["field_answer_status"] == diagnostic["numeric_answer_status"] == "met"
    assert not diagnostic["supported_elsewhere"]


def test_correct_answer_elsewhere_does_not_fill_food_field(public, packet):
    reply = response("Protein in 250g of Blueberries, raw",
        "The food facts array includes the requested information, stating that " + CORRECT)
    original = deepcopy(reply)
    result = food.diagnose_food(public, reply, packet)
    assert result["field_answer_status"] == "violated"
    assert result["numeric_answer_status"] == "met" and result["supported_elsewhere"]
    assert not result["unsupported_assertions"] and reply == original


@pytest.mark.parametrize("suffix,expected", [
    (" 250g of Blueberries, raw contains 99g of protein.", "violated"),
    (" Protein in 250g of Blueberries, raw is -1g.", "violated"),
    (" The protein amount totals 99 g.", "unknown"),
    (" Protein 99 g.", "unknown"),
    (" 250g of Blueberries, raw contains NaN g protein.", "unknown"),
    (" 250g of Blueberries, raw contains two grams of protein.", "unknown"),
    (" The athlete requested protein and 250g of Blueberries, raw contains 99g of protein.", "unknown"),
    (" The question asks about protein and 250g of Blueberries, raw contains 99g of protein.", "unknown"),
    (" 250g of Blueberries, raw might contain 99g of protein.", "unknown"),
    (" 250g of Blueberries, raw does not contain 99g of protein.", "unknown"),
    (" 250g of Other berries contains 99g of protein.", "unknown"),
    (" 250g of Blueberries, raw contains 99mg of protein.", "unknown"),
    (" 100g of Blueberries, raw contains 0.74g of protein.", "unknown"),
    (" 250g of Blueberries, raw contains approximately 1.85g of protein.", "unknown"),
])
def test_correct_claim_does_not_mask_bad_or_unverified_claims(public, packet, suffix, expected):
    diagnostic = food.diagnose_food(public, response(explanation="A recorded value is supplied." + suffix), packet)
    assert diagnostic["numeric_answer_status"] == expected


@pytest.mark.parametrize("text", [
    "The athlete has also asked about the protein content of 250g of Blueberries, raw.",
    "Is 1.85 g protein correct?", "Does 250g of Blueberries, raw contain 99g protein?",
    "Protein in 250g of Blueberries, raw", QUESTION])
def test_questions_mentions_and_subject_titles_are_not_extra_assertions(public, packet, text):
    diagnostic = food.diagnose_food(public, response(explanation=text), packet)
    assert diagnostic["numeric_answer_status"] == "met"
    assert not diagnostic["unsupported_assertions"]


@pytest.mark.parametrize("statement", [QUESTION, QUESTION.replace('"', "'"),
    QUESTION.replace('"Blueberries, raw"', '\u201cBlueberries, raw\u201d'), "Protein in 250g of Blueberries, raw", ""])
def test_question_or_label_is_not_a_field_answer(public, packet, statement):
    diagnostic = food.diagnose_food(public, response(statement, "We reviewed the input."), packet)
    assert diagnostic["field_answer_status"] == "violated"
    assert diagnostic["numeric_answer_status"] == "unknown"


@pytest.mark.parametrize("statement", ["Unknown", "The requested protein amount is unknown.",
    "I cannot verify the protein amount from the supplied references.", "The value is not available."])
def test_explicit_unknown_stays_unknown(public, packet, statement):
    diagnostic = food.diagnose_food(public, response(statement), packet)
    assert diagnostic["field_answer_status"] == diagnostic["numeric_answer_status"] == "unknown"


@pytest.mark.parametrize("key,value", [
    ("source_footnote", "< 0.74 g per 100 g"), ("source_footnote", "Approximately 0.74 g"),
    ("source_footnote", ["malformed"]), ("qualifier", "<"), ("value_qualifier", "estimated"),
    ("amount", "NaN"), ("amount", "Infinity"), ("status", "unavailable"),
    ("fdc_id", "another-food"), ("grams", "100"), ("nutrient_id", "1008"),
    ("reason", {"malformed": True}), ("amount_per_100g_raw", "0.8"),
])
def test_source_ambiguity_and_qualifiers_never_become_numeric_passes(public, packet, key, value):
    packet["payload"]["food_lookup"][0]["data"]["nutrients"][0][key] = value
    result = food.diagnose_food(public, response(), packet)
    assert result["numeric_answer_status"] == "unknown"


def test_duplicate_food_source_is_unknown(public, packet):
    packet["payload"]["food_lookup"].append(deepcopy(packet["payload"]["food_lookup"][0]))
    assert food.diagnose_food(public, response(), packet)["numeric_answer_status"] == "unknown"


def test_wrong_additional_food_value_is_not_hidden(public, packet):
    extra = deepcopy(packet["payload"]["food_lookup"][0])
    extra["data"].update(food_id="other", description="Other berries")
    for row in extra["data"]["nutrients"]:
        row.update(fdc_id="other", description="Other berries")
    packet["payload"]["food_lookup"].append(extra)
    result = food.diagnose_food(public, response(explanation="250g of Other berries contains 99g of protein."), packet)
    assert result["numeric_answer_status"] == "violated"


def test_multiple_clauses_are_all_compared(public, packet):
    reply = response("250g of Blueberries, raw contains 1.85g of protein and 250g of Blueberries, raw contains 99g of protein.")
    assert food.diagnose_food(public, reply, packet)["numeric_answer_status"] == "violated"


def test_wrong_value_still_has_field_coverage_but_fails_numeric_accuracy(public, packet):
    result = food.diagnose_food(public, response(CORRECT.replace("1.85", "2")), packet)
    assert result["field_answer_status"] == "met" and result["numeric_answer_status"] == "violated"


def test_grounding_is_separate_and_input_copies_are_protected(public, packet):
    reply = response()
    before = deepcopy((public, reply, packet))
    def base(p, r, k):
        p.clear(); r.clear(); k.clear()
        return [{"check_id": "food_source_grounding", "status": "violated", "reason": "Separate attribution finding.", "required": False}]
    checks = food.assess_food(public, reply, packet, base_assess_food=base)
    assert [c["check_id"] for c in checks] == list(food.CHECK_IDS)
    assert checks[1]["status"] == "met" and checks[2]["status"] == "violated"
    assert (public, reply, packet) == before


def test_observed_checks_do_not_duplicate_unrelated_calendar_prose(public, packet):
    reply = response()
    reply["weekly_schedule"] = [{"description": "Unrelated calendar description. " * 100} for _ in range(7)]
    checks = food.assess_food(public, reply, packet)
    assert len(json.dumps(checks)) < 4000
    assert "Unrelated calendar description" not in json.dumps(checks)


def saved_sources():
    root = next((p for p in (HERE, *HERE.parents) if (p / "work_step31_15/review_input").is_dir()), None)
    if root is None:
        pytest.skip("Uploaded saved development evidence is not present here.")
    return root


def test_actual_six_food_values_and_old_twenty_four_echo_or_unknown_replies():
    root = saved_sources()
    base = root / "work_step31_12/review_input"
    summary = json.loads((root / "upload/step31_development_pilot_summary.json").read_bytes())
    counts = Counter(); positive_controls = 0
    for case in summary["cases"]:
        ci = case["case_index"]
        if ci not in {1, 2, 5, 9, 13, 18}:
            continue
        probe = f"pilotcase_88d6bfee05772bb8_c{ci:02}"
        public = json.loads((base / "artifacts/pilot/shared_guidance" / probe / "probe_manifest.json").read_bytes())["public_record"]["input"]
        packet = json.loads(next((base / "results/pilot/probes" / probe / "references").rglob("packet.json")).read_bytes())
        lookup = packet["payload"]["food_lookup"][0]["data"]
        nutrient = "Energy" if ci in {1, 18} else "Protein"
        row = next(r for r in lookup["nutrients"] if r["nutrient_name"] == nutrient)
        positive = f"{lookup['grams']} g {lookup['description']} contains {row['amount']} {row['unit']} {nutrient}."
        d = food.diagnose_food(public, response(positive), packet)
        assert d["field_answer_status"] == d["numeric_answer_status"] == "met"
        positive_controls += 1
        for report in case["reports"]:
            path = base / report["outcome_path"]; before = path.read_bytes()
            parsed = json.loads(before)["response"]["model_output"]["parsed_object"]
            d = food.diagnose_food(public, parsed, packet)
            counts[d["field_answer_status"]] += 1
            assert d["numeric_answer_status"] == "unknown"
            assert path.read_bytes() == before
    assert positive_controls == 6 and counts == {"violated": 21, "unknown": 3}


def test_actual_sixteen_outcomes_keep_v2_numeric_recognition_separate():
    root = saved_sources(); base = root / "work_step31_15/review_input"
    summary = json.loads((base / "results/step31_reviewed_probe_summary.json").read_bytes())
    food_status = {}
    for case in summary["cases"]:
        folder = base / Path(case["reports"][0]["outcome_path"]).parents[2]
        packet = json.loads(next((folder / "references").rglob("packet.json")).read_bytes())
        public = None
        for event in map(json.loads, (folder / "http_events.jsonl").read_text().splitlines()):
            if event.get("event") == "http_started" and event.get("phase") == "generation":
                body = json.loads((folder / "http_requests" / (event["http_id"] + ".json")).read_bytes())
                public = json.loads(body["messages"][1]["content"])["athlete_input"]; break
        assert public is not None
        for report in case["reports"]:
            path = base / report["outcome_path"]; before = path.read_bytes(); outcome = json.loads(before)
            parsed = (outcome.get("response") or {}).get("model_output", {}).get("parsed_object")
            d = food.diagnose_food(public, parsed, packet)
            if case["case_index"] == 13:
                food_status[report["planner_version"]] = (d["field_answer_status"], d["numeric_answer_status"], d["supported_elsewhere"])
            else:
                assert d["field_answer_status"] == d["numeric_answer_status"] == "not_applicable"
            assert path.read_bytes() == before
    assert food_status == {1: ("violated", "unknown", False), 2: ("violated", "met", True),
                           3: ("violated", "unknown", False), 4: ("violated", "unknown", False)}

pytestmark = pytest.mark.requirement("31:offline-revision-and-food-corrections")
