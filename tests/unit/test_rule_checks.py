"""Check adopted boundaries without turning incomplete evidence into a pass."""

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load(name, relative):
    spec = importlib.util.spec_from_file_location("step30_checks_" + name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CORE = load("core", "src/champion_athletic_map/planning_checks.py")
EXTERNAL = load("external", "src/champion_athletic_map/rule_checks.py")
POINTER = json.loads((ROOT / "artifacts/language_model/active_resource_release.json").read_bytes())
RULE_PATH = ROOT / POINTER["release_directory"] / "adopted_rules.json"
RULES = json.loads(RULE_PATH.read_bytes())["records"]
RESOURCES = {"release_id": "authored-test-view-of-adopted-rules", "rule_file_sha256": hashlib.sha256(RULE_PATH.read_bytes()).hexdigest(),
             "rules": RULES, "drills": {}, "aliases": {}, "held_ids": set(), "known_reference_ids": set()}
PACKET = {"payload": {"references": [], "food_lookup": []}}
FIXTURE_VERSION = "step30-authored-rule-boundaries-1"
pytestmark = pytest.mark.requirement("30.5-adopted-boundaries-and-accounting")


def public():
    return {"age": 14, "school_grade": 9, "athlete_request": "Please plan two extra basketball sessions.",
        "planning_window": {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"},
        "availability": [{"date": (date(2026, 11, 16) + timedelta(days=n)).isoformat(), "start_time": "08:00", "end_time": "23:59"} for n in range(7)],
        "existing_commitments": [], "equipment": [{"name": "Basketball", "quantity": 1}],
        "space": {"court_access": "half_court", "hoop_access": True, "restrictions": []},
        "participants_available": 1, "time_limits": {"max_session_minutes": 30}}


def clock(minutes):
    return f"{minutes // 60:02}:{minutes % 60:02}"


def session(identifier, duration=30, start=17 * 60, parent=None, refs=None):
    return {"activity_id": identifier, "description": "Authored basketball practice", "duration_minutes": duration,
        "timing": {"start_time": clock(start), "end_time": clock(start + duration)},
        "resources": {"equipment": [{"name": "Basketball", "quantity": 1}], "space": "Half court", "participants": 1},
        "relationship": {"kind": "part_of_activity" if parent else "separate_session", "parent_activity_id": parent},
        "existing_commitment_refs": refs or []}


def plan(activities=None):
    days = [{"date": (date(2026, 11, 16) + timedelta(days=n)).isoformat(), "activities": [], "rest_arrangements": "No additional training."} for n in range(7)]
    days[0]["activities"] = deepcopy(activities or [])
    return {"response_type": "plan", "explanation": "Authored boundary case.",
        "planning_window": deepcopy(public()["planning_window"]), "weekly_schedule": days}


def commitment(minutes=60, offset=0, start=8 * 60, kind="practice", activity_type="organized_basketball"):
    return {"date": (date(2026, 11, 16) + timedelta(days=offset)).isoformat(), "description": "Authored supplied practice",
        "start_time": clock(start), "end_time": clock(start + minutes), "activity_type": activity_type, "activity_kind": kind}


def external_rows(value, response=None, context=None):
    return {row["check_id"]: row for row in EXTERNAL.external_rule_checks(value, response or plan(), PACKET, RESOURCES, "candidate_authored", context)}


def core(value, response):
    rows, context = CORE.core_checks(value, response, RESOURCES, "candidate_authored", True)
    return {row["check_id"]: row for row in rows}, context


@pytest.mark.parametrize("identifier,boundary", [("NBA_A12_14_MAX_HOURS", 600), ("NBA_G9_12_MAX_HOURS", 840)])
@pytest.mark.parametrize("delta,expected", [(-1, "unknown"), (0, "unknown"), (1, "violated")])
def test_adopted_hour_caps_use_minutes_and_do_not_claim_complete_coverage(identifier, boundary, delta, expected):
    definition = next(row for row in RULES if row["candidate_rule_id"] == identifier)
    assert (definition["reviewed_threshold"], definition["reviewed_operator"]) == (boundary, "<=")
    value = public()
    value["existing_commitments"] = [commitment(boundary + delta)]
    row = external_rows(value)["rule:" + identifier]
    assert row["status"] == expected
    assert row["observed"] == {"known_minutes_lower_bound": boundary + delta, "maximum_minutes": boundary}
    assert row["reason"]


@pytest.mark.parametrize("identifier,low,high", [("NBA_A12_14_PRACTICE_LENGTH", 60, 90), ("NBA_G9_12_PRACTICE_LENGTH", 90, 120)])
def test_adopted_practice_ranges_are_advisory_at_both_edges(identifier, low, high):
    definition = next(row for row in RULES if row["candidate_rule_id"] == identifier)
    assert definition["reviewed_threshold"] == [low, high]
    assert not definition["reviewed_enforcement"].startswith("required")
    for minutes, expected in [(low - 1, "violated"), (low, "unknown"), (high, "unknown"), (high + 1, "violated")]:
        value = public()
        value["existing_commitments"] = [commitment(minutes)]
        row = external_rows(value)["rule:" + identifier]
        assert row["status"] == expected
        assert row["required"] is False


@pytest.mark.parametrize("identifier,kind,maximum", [
    ("NBA_A12_14_PRACTICES", "practice", 4), ("NBA_G9_12_PRACTICES", "practice", 4),
    ("NBA_A12_14_GAMES_WEEK", "game", 2), ("NBA_G9_12_GAMES_WEEK", "game", 3),
])
def test_adopted_event_frequency_boundaries_count_distinct_known_days(identifier, kind, maximum):
    for count, expected in [(maximum - 1, "unknown"), (maximum, "unknown"), (maximum + 1, "violated")]:
        value = public()
        value["existing_commitments"] = [commitment(90, offset=n, kind=kind) for n in range(count)]
        row = external_rows(value)["rule:" + identifier]
        assert row["observed"]["known_event_days_lower_bound"] == count
        assert row["status"] == expected
        assert row["required"] is False


@pytest.mark.parametrize("identifier", ["NBA_A12_14_MIN_REST", "NBA_G9_12_MIN_REST", "AAP_WEEKLY_SPORT_REST"])
def test_rest_boundary_requires_classified_coverage_even_with_apparent_free_days(identifier):
    for apparent_rest_days, expected in [(0, "violated"), (1, "unknown"), (2, "unknown")]:
        value = public()
        value["existing_commitments"] = [commitment(60, offset=n) for n in range(7 - apparent_rest_days)]
        row = external_rows(value)["rule:" + identifier]
        assert row["status"] == expected
        assert row["observed"]["known_active_days"] == 7 - apparent_rest_days
        assert row["observed"]["complete_schedule_established"] is False


@pytest.mark.parametrize("identifier", ["NBA_A13_14_SLEEP", "NBA_G9_12_SLEEP", "CDC_TEENS_SLEEP"])
def test_sleep_average_does_not_prove_nightly_or_daily_guidance(identifier):
    definition = next(row for row in RULES if row["candidate_rule_id"] == identifier)
    assert definition["reviewed_threshold"] == [8, 10]
    for hours in [7, 8, 10, 11]:
        value = public()
        value["history"] = {"sleep": {"average_hours_per_night": hours}}
        row = external_rows(value)["rule:" + identifier]
        assert row["status"] == "unknown"
        assert row["observed"] == hours


def test_population_overlap_and_missing_grade_remain_explicit():
    rows = external_rows(public())
    assert rows["rule:NBA_A12_14_MAX_HOURS"]["applicability"] == "applicable"
    assert rows["rule:NBA_G9_12_MAX_HOURS"]["applicability"] == "applicable"
    value = public()
    value["school_grade"] = None
    missing = external_rows(value)["rule:NBA_G9_12_MAX_HOURS"]
    assert missing["status"] == missing["applicability"] == "unknown"
    value["school_grade"] = 8
    excluded = external_rows(value)["rule:NBA_G9_12_MAX_HOURS"]
    assert excluded["status"] == excluded["applicability"] == "not_applicable"
    assert excluded["reason"]


def test_parent_components_and_separate_session_contribute_90_not_100_minutes():
    value = public()
    value["existing_commitments"] = [commitment(60, start=17 * 60)]
    response = plan([session("practice", 60, refs=["/existing_commitments/0"]),
                     session("included-drill", 10, parent="practice"), session("separate", 30, start=18 * 60)])
    rows, context = core(value, response)
    assert rows["activity_accounting"]["status"] == "met"
    assert rows["additional_training_limits"]["observed"] == {"additional_sessions": 1, "known_minutes": 30}
    cap = external_rows(value, response, context)["rule:NBA_A12_14_MAX_HOURS"]
    assert cap["observed"]["known_minutes_lower_bound"] == 90


def test_duplicate_timed_event_does_not_double_its_duration_but_collision_is_reported():
    value = public()
    value["existing_commitments"] = [commitment(60, start=17 * 60)] * 2
    response = plan([session("copy-a", 60, refs=["/existing_commitments/0"]), session("copy-b", 60, refs=["/existing_commitments/1"])])
    rows, context = core(value, response)
    assert rows["availability_and_collisions"]["status"] == "violated"
    assert external_rows(value, response, context)["rule:NBA_A12_14_MAX_HOURS"]["observed"]["known_minutes_lower_bound"] == 60


def test_repeated_drill_name_does_not_collapse_distinct_adjacent_sessions():
    response = plan([session("first", 30), session("second", 30, start=17 * 60 + 30)])
    rows, context = core(public(), response)
    assert len(context["roots"]) == 2
    assert rows["requested_session_count"]["status"] == "met"
    assert rows["additional_training_limits"]["observed"] == {"additional_sessions": 2, "known_minutes": 60}
    assert rows["availability_and_collisions"]["status"] == "met"


@pytest.mark.parametrize("second_start,expected", [(17 * 60 + 29, "violated"), (17 * 60 + 30, "met")])
def test_overlap_is_distinct_from_adjacent_intervals(second_start, expected):
    rows, _ = core(public(), plan([session("first"), session("second", start=second_start)]))
    assert rows["availability_and_collisions"]["status"] == expected


@pytest.mark.parametrize("availability,expected", [(None, "unknown"), ([], "violated")])
def test_unknown_availability_is_not_confirmed_no_available_time(availability, expected):
    value = public()
    value["availability"] = availability
    rows, _ = core(value, plan([session("first")]))
    assert rows["availability_and_collisions"]["status"] == expected


@pytest.mark.parametrize("minutes,expected", [(29, "met"), (30, "met"), (31, "violated")])
def test_user_session_maximum_includes_equality(minutes, expected):
    rows, _ = core(public(), plan([session("first", minutes)]))
    assert rows["additional_training_limits"]["status"] == expected


def test_unknown_duration_prevents_complete_added_minute_total():
    item = session("first")
    item["duration_minutes"] = None
    rows, _ = core(public(), plan([item]))
    assert rows["timing_durations"]["status"] == "unknown"
    assert rows["additional_training_limits"]["status"] == "unknown"


@pytest.mark.parametrize("available,expected", [(0, "violated"), (None, "unknown"), (1, "unknown")])
def test_declared_equipment_conflict_is_actionable_without_verifying_freeform_requirements(available, expected):
    value = public()
    value["equipment"] = None if available is None else [{"name": "Basketball", "quantity": available}]
    rows, _ = core(value, plan([session("first")]))
    assert rows["resource_feasibility"]["status"] == expected
    if available == 1:
        assert "Free-form" in rows["resource_feasibility"]["reason"]


def test_participant_and_court_shortages_are_reported():
    for resource, value in [("participants", 2), ("space", "Full court with hoop")]:
        item = session("first")
        item["resources"][resource] = value
        rows, _ = core(public(), plan([item]))
        assert rows["resource_feasibility"]["status"] == "violated"


def test_component_outside_parent_is_an_accounting_violation():
    rows, _ = core(public(), plan([session("parent", 30), session("child", 10, start=18 * 60, parent="parent")]))
    assert rows["activity_accounting"]["status"] == "violated"
    assert "outside its parent" in rows["activity_accounting"]["reason"]


@pytest.mark.parametrize("end,duration", [("16:00", 30), ("17:00", 0), ("17:20", 30)])
def test_reversed_zero_and_inconsistent_intervals_do_not_pass(end, duration):
    item = session("first")
    item["timing"]["end_time"], item["duration_minutes"] = end, duration
    rows, _ = core(public(), plan([item]))
    assert rows["timing_durations"]["status"] == "violated"


def test_moved_or_missing_existing_commitment_is_reported():
    value = public()
    value["existing_commitments"] = [commitment(60, start=17 * 60)]
    for activities in [[], [session("existing", 60, start=18 * 60, refs=["/existing_commitments/0"])]]:
        rows, _ = core(value, plan(activities))
        assert rows["existing_commitments"]["status"] == "violated"


def test_unsupported_nonplan_label_does_not_waive_schedule_checks():
    rows, _ = core(public(), {"response_type": "outside_scope", "explanation": "A deliberately unjustified refusal."})
    assert rows["response_type_basis"]["status"] == "unknown"
    assert rows["calendar_window"]["status"] == "unknown"
    assert rows["rule:POLICY_SCOPE"]["status"] == "unknown"


def test_missing_age_asks_for_age_without_inventing_population():
    value = public()
    value["age"] = None
    rows, context = core(value, {"response_type": "clarification", "explanation": "Age is needed.", "questions": ["How old are you?"]})
    assert rows["response_type_basis"]["status"] == "met"
    assert context["nonplan_basis_verified"] is True
    assert rows["calendar_window"]["status"] == "not_applicable"


def test_full_checker_returns_each_declared_check_once_for_each_candidate():
    config = json.loads((ROOT / "artifacts/language_model/integration_config.json").read_bytes())
    folder = config["contracts_directory"]
    client = SimpleNamespace(public=load("public", folder + "/public_input.py"), response=load("response", folder + "/response_contract.py"),
        input_schema=json.loads((ROOT / folder / "public_profile_record_schema.json").read_bytes()))
    client.response_schema = client.response.build_response_schema()
    checker = CORE.PlanningChecker(ROOT, client, {}, resources=deepcopy(RESOURCES))
    record = {"profile_id": "authored-checker-example", "schema_version": "athlete-profile-input-1", "input": public()}
    for identifier in ("candidate_0", "candidate_1", "candidate_2"):
        result = checker.check(record, plan([session("first"), session("second", start=17 * 60 + 30)]), PACKET, identifier)
        assert result["execution_status"] == "completed"
        assert len(result["checks"]) == 41
        assert {row["check_id"] for row in result["checks"]} == set(result["expected_check_ids"])
        assert all(row["candidate_id"] == identifier and row["reason"] for row in result["checks"])
        assert any(row["required"] and row["status"] == "unknown" for row in result["checks"])


@pytest.mark.parametrize("change", ["empty", "disabled"])
def test_missing_or_unadopted_rule_register_fails_explicitly(change):
    resources = deepcopy(RESOURCES)
    if change == "empty":
        resources["rules"] = []
    else:
        resources["rules"][0]["enabled_for_planner"] = False
    with pytest.raises(ValueError, match="complete adopted"):
        CORE.PlanningChecker(ROOT, None, {}, resources=resources)
