"""Check request-specific structure without supplying food facts or model replies."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/champion_athletic_map/request_contracts.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


API = load(SOURCE, "request_contracts_under_test")
ADAPTER = load(ROOT / "src/champion_athletic_map/llm.py", "request_contracts_saved_schema_builder")
LOCAL = json.loads((ROOT / "artifacts/language_model/shared_contracts/contracts_3293242853ce2cf7/planner_response_schema.json").read_bytes())
NATIVE = ADAPTER._schema_order(ADAPTER._generation_schema(LOCAL))
NOTE = json.loads((ROOT / "artifacts/planners/version3_note_schema.json").read_bytes())
PUBLIC = {"planning_window": {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"},
    "food_question": 'For the food "Fictional food", how many grams of protein are recorded for 150 g?'}
UNKNOWN = {"statement": "The supplied information does not establish the requested recorded food value."}


def build(public=None):
    return API.build_contracts(deepcopy(PUBLIC if public is None else public), LOCAL, NATIVE, NOTE)


def answer(kind="plan"):
    value = {"response_type": kind, "explanation": "The request has been considered.", "food_facts": [deepcopy(UNKNOWN)]}
    if kind == "plan":
        value["planning_window"] = deepcopy(PUBLIC["planning_window"])
        value["weekly_schedule"] = [{"date": "2026-11-" + str(day), "activities": [], "rest_arrangements": "Rest."}
            for day in range(16, 23)]
    elif kind == "clarification":
        value["questions"] = ["Which essential resource is available?"]
    elif kind == "constraint_conflict":
        value["unresolved_issues"] = ["The stated constraints conflict."]
    return value


def note(status="provided"):
    return {"contribution_status": status, "recommendations": [], "evidence_refs": [], "qualifications": [],
        "unresolved_issues": [], "questions": [], "rationale": "The supplied question was considered."}


def valid(schema, value):
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema).is_valid(value)


def test_original_inputs_remain_unchanged_and_outputs_have_independent_copies():
    before = deepcopy((PUBLIC, LOCAL, NATIVE, NOTE))
    result = API.build_contracts(PUBLIC, LOCAL, NATIVE, NOTE)
    assert (PUBLIC, LOCAL, NATIVE, NOTE) == before
    result["local_response_schema"]["properties"]["explanation"]["minLength"] = 99
    assert (PUBLIC, LOCAL, NATIVE, NOTE) == before


@pytest.mark.parametrize("kind", API.KINDS)
def test_all_response_variants_require_early_food_content_but_allow_honest_unknown(kind):
    result = build()
    branch = next(item for item in result["native_response_schema"]["anyOf"]
        if item["properties"]["response_type"]["const"] == kind)
    assert list(branch["properties"])[:2] == ["response_type", "food_facts"]
    assert "food_facts" in branch["required"]
    value = answer(kind)
    for schema in (result["local_response_schema"], result["native_response_schema"]):
        assert valid(schema, value)
        for bad in (None, []):
            changed = deepcopy(value)
            changed["food_facts"] = bad
            assert not valid(schema, changed)
        changed = deepcopy(value)
        changed.pop("food_facts")
        assert not valid(schema, changed)


def test_no_food_question_keeps_food_optional_without_inventing_content():
    result = build({"planning_window": PUBLIC["planning_window"], "food_question": "  "})
    assert result["policy"]["food_answer_presence_required"] is False
    value = answer("outside_scope")
    value.pop("food_facts")
    assert valid(result["local_response_schema"], value)
    assert valid(result["native_response_schema"], value)
    assert "food_facts" not in result["local_response_schema"]["required"]


def test_a_provided_food_note_needs_substantive_content_and_not_just_rationale():
    result = build()["food_note_schema"]
    native_note = ADAPTER._generation_schema(result)
    value = note()
    for schema in (result, native_note):
        assert not valid(schema, value)
        changed = deepcopy(value)
        changed["recommendations"] = [UNKNOWN["statement"]]
        assert valid(schema, changed)
    assert result["type"] == "object" and len(result["anyOf"]) == 3
    assert all(branch["type"] == "object" and "properties" in branch for branch in result["anyOf"])


@pytest.mark.parametrize("status", ["limited_information", "outside_scope"])
def test_unavailable_food_contribution_needs_a_specific_issue(status):
    result = build()["food_note_schema"]
    value = note(status)
    assert not valid(result, value)
    value["unresolved_issues"] = ["The supplied reference has no value for the requested nutrient."]
    assert valid(result, value)
    assert valid(ADAPTER._generation_schema(result), value)


def test_native_window_is_fixed_and_each_day_uses_the_supplied_date_set():
    result = build()
    native = result["native_response_schema"]
    value = answer()
    assert valid(native, value)
    wrong_window = deepcopy(value)
    wrong_window["planning_window"]["timezone"] = "UTC"
    assert not valid(native, wrong_window)
    wrong_date = deepcopy(value)
    wrong_date["weekly_schedule"][0]["date"] = "2026-12-16"
    assert not valid(native, wrong_date)
    # Enum-only native grammar deliberately does not establish order or uniqueness.
    duplicated = deepcopy(value)
    duplicated["weekly_schedule"][1]["date"] = duplicated["weekly_schedule"][0]["date"]
    assert valid(native, duplicated)
    assert not valid(result["local_response_schema"], duplicated)
    reversed_days = deepcopy(value)
    reversed_days["weekly_schedule"].reverse()
    assert valid(native, reversed_days)
    assert not valid(result["local_response_schema"], reversed_days)


def test_local_exact_calendar_retains_original_day_constraints():
    result = build()
    value = answer()
    value["weekly_schedule"][0]["rest_arrangements"] = []
    assert not valid(result["local_response_schema"], value)
    value = answer()
    value["planning_window"]["start_date"] = "2026-11-17"
    assert not valid(result["local_response_schema"], value)


def test_different_public_week_changes_contract_values_and_identity_without_food_truth():
    first = build()
    public = deepcopy(PUBLIC)
    public["planning_window"].update(start_date="2026-11-23", end_date="2026-11-29")
    second = build(public)
    assert first["policy"]["native_response_schema_sha256"] != second["policy"]["native_response_schema_sha256"]
    assert first["policy"]["local_response_schema_sha256"] != second["policy"]["local_response_schema_sha256"]
    assert first["policy"]["planning_window_sha256"] != second["policy"]["planning_window_sha256"]
    text = json.dumps(second)
    assert "Fictional food" not in text and "150 g" not in text and "2.715" not in text
    assert second["policy"]["food_value_or_reference_injected"] is False
    assert second["policy"]["lookup_truth_read"] is False


def test_native_contract_adds_only_supported_scalar_array_constraints():
    result = build()
    native = result["native_response_schema"]
    def keywords(value):
        if isinstance(value, dict):
            names = set(value)
            for child in value.values():
                names |= keywords(child)
            return names
        if isinstance(value, list):
            return set().union(*(keywords(item) for item in value))
        return set()
    assert "prefixItems" not in keywords(native)
    assert not (keywords(native) - keywords(NATIVE)) - {"enum"}
    assert result["policy"]["native_chronology_or_unique_dates_guaranteed"] is False
    assert result["policy"]["final_approval"] is False


@pytest.mark.parametrize("change", ["bad_week", "bad_native", "bad_note"])
def test_changed_schema_or_window_shape_is_rejected(change):
    public, native, notes = deepcopy(PUBLIC), deepcopy(NATIVE), deepcopy(NOTE)
    if change == "bad_week":
        public["planning_window"]["end_date"] = "2026-11-23"
    elif change == "bad_native":
        native["anyOf"].pop()
    else:
        notes["properties"]["contribution_status"]["enum"].append("approved")
    with pytest.raises(ValueError):
        API.build_contracts(public, LOCAL, native, notes)


pytestmark = pytest.mark.requirement("31:request-specific-structural-contracts")
