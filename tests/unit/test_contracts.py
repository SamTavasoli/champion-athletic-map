"""Exercise public facts and response boundaries with authored, non-study examples."""

from copy import deepcopy
from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "artifacts/language_model/integration_config.json").read_bytes())
CONTRACTS = ROOT / CONFIG["contracts_directory"]


def load(name):
    path = CONTRACTS / (name + ".py")
    spec = importlib.util.spec_from_file_location("step30_contract_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PUBLIC = load("public_input")
RESPONSE = load("response_contract")
INPUT_SCHEMA = json.loads((CONTRACTS / "public_profile_record_schema.json").read_bytes())
FIXTURE_VERSION = "step30-authored-contracts-1"
pytestmark = pytest.mark.requirement("30.4-public-and-response-contracts")


def record():
    return {"profile_id": "authored-contract-example", "schema_version": "athlete-profile-input-1", "input": {
        "athlete_request": "Please plan one extra basketball session.",
        "planning_window": {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"},
        "age": 14, "school_grade": 9,
        "availability": [{"date": "2026-11-16", "start_time": "17:00", "end_time": "18:00"}],
        "existing_commitments": [], "equipment": [{"name": "Basketball", "quantity": 1}],
        "participants_available": 1,
        "space": {"court_access": "half_court", "hoop_access": True, "restrictions": []}}}


def activity(identifier="authored-session"):
    return {"activity_id": identifier, "description": "Authored basketball practice",
        "duration_minutes": 20, "timing": {"start_time": "17:00", "end_time": "17:20"},
        "resources": {"equipment": [{"name": "Basketball", "quantity": 1}], "space": "Half court", "participants": 1},
        "relationship": {"kind": "separate_session", "parent_activity_id": None},
        "existing_commitment_refs": []}


def plan():
    start = date(2026, 11, 16)
    days = [{"date": (start + timedelta(days=n)).isoformat(), "activities": [],
             "rest_arrangements": "No additional training in this authored example."} for n in range(7)]
    days[0]["activities"] = [activity()]
    return {"response_type": "plan", "explanation": "Authored example: Café Ω 中文 🏀",
            "planning_window": deepcopy(record()["input"]["planning_window"]), "weekly_schedule": days}


def parse(value):
    return RESPONSE.parse_response_text(json.dumps(value, ensure_ascii=False))


def test_model_projection_excludes_wrapper_identity_and_keeps_exact_supplied_facts():
    source = record()
    prepared = PUBLIC.prepare_public_input(source, INPUT_SCHEMA)
    assert json.loads(prepared["model_visible_json"]) == source["input"]
    assert prepared["audit"]["profile_id"] == "authored-contract-example"
    assert "authored-contract-example" not in prepared["model_visible_json"]
    assert "schema_version" not in json.loads(prepared["model_visible_json"])
    source["input"]["age"] = 17
    assert prepared["public_input"]["age"] == 14


def test_unknown_missing_and_confirmed_absence_are_distinct():
    omitted, unknown, absent = record(), record(), record()
    omitted["input"].pop("existing_commitments")
    unknown["input"]["existing_commitments"] = None
    absent["input"]["existing_commitments"] = []
    results = [PUBLIC.prepare_public_input(item, INPUT_SCHEMA) for item in (omitted, unknown, absent)]
    assert "existing_commitments" not in results[0]["public_input"]
    assert results[1]["public_input"]["existing_commitments"] is None
    assert results[2]["public_input"]["existing_commitments"] == []
    assert len({item["audit"]["public_input_sha256"] for item in results}) == 3


def test_missing_age_and_grade_are_preserved_without_inference():
    source = record()
    source["input"]["age"], source["input"]["school_grade"] = None, None
    prepared = PUBLIC.prepare_public_input(source, INPUT_SCHEMA)
    assert prepared["public_input"]["age"] is None
    assert prepared["public_input"]["school_grade"] is None


def test_confirmed_zero_false_and_empty_values_survive_projection():
    source = record()
    source["input"].update(equipment=[{"name": "Basketball", "quantity": 0}], availability=[], goals=[],
        space={"court_access": "none", "hoop_access": False, "restrictions": []},
        time_limits={"max_additional_sessions_per_week": 0})
    prepared = PUBLIC.prepare_public_input(source, INPUT_SCHEMA)
    assert prepared["public_input"] == source["input"]


@pytest.mark.parametrize("field,value", [
    ("age", 12), ("age", 18), ("age", "14"), ("age", True), ("school_grade", 0),
    ("participants_available", 0), ("equipment", [{"name": "Basketball", "quantity": -1}]),
    ("availability", [{"date": "2026-11-23", "start_time": "17:00", "end_time": "18:00"}]),
    ("availability", [{"date": "2026-11-16", "start_time": "25:00", "end_time": "18:00"}]),
    ("time_limits", {"max_session_minutes": float("inf")}),
])
def test_invalid_public_values_are_rejected_without_repair(field, value):
    source = record()
    source["input"][field] = value
    with pytest.raises(ValueError):
        PUBLIC.prepare_public_input(source, INPUT_SCHEMA)


@pytest.mark.parametrize("location", ["wrapper", "input"])
def test_private_expected_answers_and_scenario_fields_are_rejected(location):
    source = record()
    target = source if location == "wrapper" else source["input"]
    target["private_expected_answer"] = "PRIVATE_SENTINEL_DO_NOT_SEND"
    with pytest.raises(ValueError) as error:
        PUBLIC.prepare_public_input(source, INPUT_SCHEMA)
    assert "PRIVATE_SENTINEL_DO_NOT_SEND" not in str(error.value)


def test_conflicting_commitments_are_not_deleted_by_structural_input_validation():
    source = record()
    first = {"description": "Authored basketball practice", "date": "2026-11-16", "start_time": "17:00", "end_time": "18:00"}
    source["input"]["existing_commitments"] = [first, {**first, "description": "Authored other commitment", "start_time": "17:30"}]
    result = PUBLIC.prepare_public_input(source, INPUT_SCHEMA)
    assert result["public_input"]["existing_commitments"] == source["input"]["existing_commitments"]


@pytest.mark.parametrize("raw", [
    '{"response_type":"outside_scope","response_type":"plan","explanation":"x"}',
    '{"response_type":"outside_scope","explanation":"x","value":NaN}',
    '{"response_type":"outside_scope","explanation":"x","value":Infinity}',
    '{"response_type":"outside_scope","explanation":"x","value":1e999}',
    '```json\n{"response_type":"outside_scope","explanation":"x"}\n```',
    '{"response_type":"outside_scope","explanation":"x"} trailing text',
    b'\xff',
])
def test_non_strict_response_text_is_rejected_and_preserved(raw):
    result = RESPONSE.parse_response_text(raw)
    assert result["parse_valid"] is False
    assert result["raw_text"] == raw
    assert result["parsed_object"] is None
    assert result["error_code"] in {"invalid_json", "invalid_utf8"}


def test_valid_seven_day_response_preserves_unicode_and_values():
    value = plan()
    result = parse(value)
    assert result["parse_valid"] is True
    assert result["parsed_object"] == value


@pytest.mark.parametrize("change", ["duplicate_day", "duplicate_id", "missing_parent", "self_parent", "component_null_parent", "day_extra_field", "rest_array"])
def test_invalid_calendar_structure_cannot_pass_format_validation(change):
    value = plan()
    if change == "duplicate_day":
        value["weekly_schedule"][1]["date"] = "2026-11-16"
    elif change == "duplicate_id":
        value["weekly_schedule"][1]["activities"] = [activity()]
    elif change in {"missing_parent", "self_parent", "component_null_parent"}:
        value["weekly_schedule"][0]["activities"][0]["relationship"] = {
            "kind": "part_of_activity", "parent_activity_id": {"missing_parent": "absent", "self_parent": "authored-session", "component_null_parent": None}[change]}
    elif change == "day_extra_field":
        value["weekly_schedule"][1]["existing_commitment_refs"] = []
    else:
        value["weekly_schedule"][1]["rest_arrangements"] = []
    result = parse(value)
    assert result["parse_valid"] is False
    assert result["parsed_object"] == value
    assert result["issues"]


def test_source_facts_stay_authoritative_beside_generated_text():
    prepared = PUBLIC.prepare_public_input(record(), INPUT_SCHEMA)
    response = {"response_type": "outside_scope", "explanation": "A deliberately incorrect claim that the athlete is 99."}
    parsed = parse(response)
    archived = PUBLIC.preserve_response_record(prepared, parsed)
    assert archived["authoritative_public_input"]["age"] == 14
    assert archived["model_output"]["parsed_object"] == response
    assert archived["semantic_correctness_verified"] is False
    tampered = deepcopy(parsed)
    tampered["parsed_object"]["explanation"] = "Repaired text that was never returned."
    with pytest.raises(ValueError, match="differs"):
        PUBLIC.preserve_response_record(prepared, tampered)


def test_changed_prepared_facts_fail_integrity_verification():
    prepared = PUBLIC.prepare_public_input(record(), INPUT_SCHEMA)
    prepared["public_input"]["age"] = 15
    with pytest.raises(ValueError, match="changed"):
        PUBLIC.verify_prepared_input(prepared)
