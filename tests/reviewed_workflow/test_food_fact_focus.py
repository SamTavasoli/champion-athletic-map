from copy import deepcopy
from pathlib import Path
import hashlib
import importlib.util
import json

import pytest


HERE = Path(__file__).resolve().parent
PROJECT = next((p for p in (HERE, *HERE.parents) if (p / "src/champion_athletic_map").is_dir()), None)
SOURCE = HERE / "food_fact_focus.py"
if not SOURCE.is_file() and PROJECT is not None:
    SOURCE = PROJECT / "src/champion_athletic_map/food_fact_focus.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


focus = load(SOURCE, "tested_food_focus")
QUESTION = 'For the food "Strawberries, raw", how many grams of protein are recorded for 100 g?'


@pytest.fixture
def public():
    return {"food_question": QUESTION}


@pytest.fixture
def payload():
    return {"food_lookup": [{"status": "found", "data": {
        "food_id": "167762", "description": "Strawberries, raw", "grams": "100", "nutrients": [{
            "nutrient_id": "1003", "nutrient_name": "Protein", "amount": "0.67", "unit": "G",
            "fdc_id": "167762", "description": "Strawberries, raw", "grams": "100", "status": "available",
            "amount_per_100g_raw": "0.67", "reference_mass_g": "100", "reference_basis": "edible_food",
            "source_record_url": "https://fdc.nal.usda.gov/food-details/167762/nutrients",
            "source_footnote": "", "reason": None, "source_data_type": "sr_legacy_food",
            "source_derivation_code": "A", "source_derivation_description": "Analytical",
            "catalog_release": "2018-04"}]},
        "source_refs": ["https://fdc.nal.usda.gov/food-details/167762/nutrients"]}],
        "references": [{"text": "The rest of the reference packet stays present."}], "catalog_records": []}


def test_focus_preserves_source_and_complete_view(public, payload):
    before = deepcopy(payload)
    view = {"athlete_input": public, "reference_data": payload, "candidate": {"explanation": "unchanged"}}
    original = deepcopy(view)
    encoded = focus.attach_food_focus(view)
    item = encoded["requested_food_facts"]["requested_facts"][0]
    assert encoded["requested_food_facts"]["status"] == "available"
    assert (item["food_id"], item["amount"], item["unit"], item["grams"]) == ("167762", "0.67", "G", "100")
    assert encoded["reference_data"] == before and view == original
    assert item["source_path"] == "/food_lookup/0/data/nutrients/0"
    item["source_qualifiers"]["source_footnote"] = "changed only in private view"
    assert payload == before


def test_baseline_view_is_unchanged_without_reference_access(public):
    view = {"athlete_input": public}
    assert focus.attach_food_focus(view) == view
    assert focus.attach_food_focus(None) is None


@pytest.mark.parametrize("question", [None, "", "  "])
def test_no_question_has_no_fact(question, payload):
    assert focus.make_food_focus({"food_question": question}, payload)["status"] == "not_requested"


@pytest.mark.parametrize("question", [True, "How much protein is in strawberries?",
    QUESTION.replace("100 g?", "0 g?"), QUESTION.replace("100 g?", "100 mg?"),
    QUESTION.replace('"Strawberries, raw"', '"Raw strawberries"')])
def test_unsupported_question_has_no_inferred_answer(question, payload):
    result = focus.make_food_focus({"food_question": question}, payload)
    assert result["status"] == "unresolved" and not result["requested_facts"]


@pytest.mark.parametrize("field,value", [
    ("amount", "0.68"), ("amount", "NaN"), ("amount", "Infinity"), ("amount", True),
    ("amount", -1), ("amount", "<0.67"), ("amount_per_100g_raw", "0.68"),
    ("unit", "MG"), ("grams", "150"), ("fdc_id", "another-food"),
    ("description", "Strawberries, cooked"), ("nutrient_name", "Energy"),
    ("nutrient_id", "1008"), ("status", "unavailable"),
    ("reference_mass_g", "0"), ("reference_mass_g", "200"), ("reference_basis", None),
    ("source_footnote", ["not a text qualifier"]), ("reason", {"malformed": True}),
    ("qualifier", "<"), ("value_qualifier", "approximately"),
    ("source_record_url", "https://different.example/record")])
def test_bad_or_qualified_source_values_remain_unresolved(public, payload, field, value):
    payload["food_lookup"][0]["data"]["nutrients"][0][field] = value
    result = focus.make_food_focus(public, payload)
    assert result["status"] == "unresolved" and not result["requested_facts"]


def test_source_footnote_and_derivation_remain_visible(public, payload):
    row = payload["food_lookup"][0]["data"]["nutrients"][0]
    row["source_footnote"] = "Recorded edible portion only; keep this qualification."
    result = focus.make_food_focus(public, payload)
    assert result["requested_facts"][0]["source_qualifiers"]["source_footnote"] == row["source_footnote"]
    assert result["requested_facts"][0]["source_qualifiers"]["source_derivation_description"] == "Analytical"


@pytest.mark.parametrize("kind", ["lookup", "nutrient", "mass", "name", "status", "source", "empty"])
def test_missing_or_ambiguous_sources_are_unresolved(public, payload, kind):
    row = payload["food_lookup"][0]
    if kind == "lookup":
        payload["food_lookup"].append(deepcopy(row))
    elif kind == "nutrient":
        row["data"]["nutrients"].append(deepcopy(row["data"]["nutrients"][0]))
    elif kind == "mass":
        row["data"]["grams"] = "150"
    elif kind == "name":
        row["data"]["description"] = "Strawberries, cooked"
    elif kind == "status":
        row["status"] = "not_found"
    elif kind == "source":
        row["source_refs"] = []
    else:
        payload["food_lookup"] = []
    result = focus.make_food_focus(public, payload)
    assert result["status"] == "unresolved" and not result["requested_facts"]


@pytest.mark.parametrize("left,right", [('"', '"'), ("'", "'"), ("\u2018", "\u2019"), ("\u201c", "\u201d")])
def test_equivalent_question_quotes_are_echoes(left, right):
    question = QUESTION.replace('"Strawberries, raw"', left + "Strawberries, raw" + right)
    assert focus.is_question_echo(question, QUESTION)
    assert focus.is_question_echo("  " + question.upper() + "  ", QUESTION)


@pytest.mark.parametrize("text", [QUESTION.replace("100 g", "150 g"), QUESTION.replace("100 g", "100 mg"),
    QUESTION.replace("Strawberries, raw", "Strawberries, cooked"), QUESTION.replace("protein", "energy"),
    QUESTION + " 0.67 g protein.", "100 g Strawberries, raw contains 0.67 g Protein.",
    "Unknown", "How much protein is in the strawberries?"])
def test_echo_audit_preserves_numbers_units_and_other_wording(text):
    assert not focus.is_question_echo(text, QUESTION)


def food_assessor():
    locations = [HERE.parent / "work_step31_5/independent_food.py"]
    if PROJECT is not None:
        locations.append(PROJECT / "src/champion_athletic_map/independent_food.py")
    source = next((p for p in locations if p.is_file()), None)
    if source is None:
        pytest.skip("Saved base food assessor is not present in this source tree.")
    return load(source, "frozen_food_for_focus_test").assess_food


def test_audit_keeps_wrong_numerical_answers_violated(public, payload):
    response = {"food_facts": [{"statement": "100 g Strawberries, raw contains 0.68 g Protein."}]}
    original = deepcopy(response)
    checks = focus.assess_food(public, response, {"payload": payload}, base_assess_food=food_assessor())
    assert next(c for c in checks if c["check_id"] == "food_numeric_correctness")["status"] == "violated"
    assert response == original


def test_audit_does_not_turn_unknown_into_a_pass(public, payload):
    response = {"food_facts": [{"statement": "Unknown"}]}
    checks = focus.assess_food(public, response, {"payload": payload}, base_assess_food=food_assessor())
    assert all(c["status"] != "met" for c in checks)


def actual_inputs():
    task_root = next((p for p in (HERE, *HERE.parents) if (p / "work_step31_12/review_input").is_dir()), None)
    if task_root:
        return task_root / "work_step31_12/review_input", task_root / "upload/step31_development_pilot_summary.json"
    if PROJECT is not None and (PROJECT / "results/step31_development_pilot_summary.json").is_file():
        return PROJECT, PROJECT / "results/step31_development_pilot_summary.json"
    pytest.skip("Completed development pilot files are not installed here.")


def test_all_six_saved_requested_facts_are_lossless():
    base, summary_path = actual_inputs()
    summary = json.loads(summary_path.read_bytes())
    expected = {1: ("85.5", "KCAL"), 2: ("0.67", "G"), 5: ("0.72", "G"),
                9: ("2.715", "G"), 13: ("1.85", "G"), 18: ("133.5", "KCAL")}
    for case in summary["cases"]:
        ci = case["case_index"]
        if ci not in expected:
            continue
        folder = Path(case["reports"][0]["outcome_path"]).parents[2]
        probe_id = folder.name
        manifest_path = base / "artifacts/pilot/shared_guidance" / probe_id / "probe_manifest.json"
        public = json.loads(manifest_path.read_bytes())["public_record"]["input"]
        packet_path = next((base / "results/pilot/probes" / probe_id / "references").rglob("packet.json"))
        packet_bytes = packet_path.read_bytes()
        payload = json.loads(packet_bytes)["payload"]
        before = deepcopy(payload)
        result = focus.make_food_focus(public, payload)
        assert result["status"] == "available"
        item = result["requested_facts"][0]
        assert (item["amount"], item["unit"]) == expected[ci]
        assert payload == before and packet_path.read_bytes() == packet_bytes


def test_audit_all_twenty_four_designated_food_replies():
    base, summary_path = actual_inputs()
    summary = json.loads(summary_path.read_bytes())
    base_assess = food_assessor()
    echoes = unknown = 0
    for case in summary["cases"]:
        ci = case["case_index"]
        if ci not in {1, 2, 5, 9, 13, 18}:
            continue
        probe_id = Path(case["reports"][0]["outcome_path"]).parents[2].name
        public = json.loads((base / "artifacts/pilot/shared_guidance" / probe_id / "probe_manifest.json").read_bytes())["public_record"]["input"]
        packet = json.loads(next((base / "results/pilot/probes" / probe_id / "references").rglob("packet.json")).read_bytes())
        for report in case["reports"]:
            path = base / report["outcome_path"]
            before = path.read_bytes()
            response = json.loads(before)["response"]["model_output"]["parsed_object"]
            checks = focus.assess_food(public, response, packet, base_assess_food=base_assess)
            completeness = next(c for c in checks if c["check_id"] == "food_answer_completeness")
            numeric = next(c for c in checks if c["check_id"] == "food_numeric_correctness")
            if completeness["food_answer_audit"]["question_echo_count"]:
                echoes += 1
                assert completeness["status"] == "violated"
            else:
                unknown += 1
                assert completeness["status"] == "unknown"
            assert numeric["status"] == "unknown"
            assert path.read_bytes() == before
    assert (echoes, unknown) == (21, 3)

pytestmark = pytest.mark.requirement("31:reviewed-workflow-corrections")
