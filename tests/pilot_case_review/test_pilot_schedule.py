"""Exercise the new pilot boundary using authored cases and unchanged legacy data."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PILOT = load(ROOT / "src/champion_athletic_map/pilot_schedule.py", "pilot_schedule_tests")
FIX = load(ROOT / "tests/unit/test_rule_checks.py", "legacy_rule_fixtures")
CONFIG = json.loads((ROOT / "artifacts/language_model/integration_config.json").read_bytes())
CONTRACTS = ROOT / CONFIG["contracts_directory"]
BASE = json.loads((CONTRACTS / "public_profile_record_schema.json").read_bytes())
CLIENT = SimpleNamespace(public=load(CONTRACTS / "public_input.py", "pilot_public"),
    response=load(CONTRACTS / "response_contract.py", "pilot_response"), input_schema=BASE)
CLIENT.response_schema = CLIENT.response.build_response_schema()


@pytest.fixture
def checker():
    return PILOT.make_checker(ROOT, CLIENT, {}, resources=deepcopy(FIX.RESOURCES))


def public():
    value = FIX.public()
    value["athlete_request"] = "Please plan two extra basketball sessions."
    value["schedule_coverage"] = {**value["planning_window"], "existing_commitments_complete": True}
    return value


def record(value):
    return {"profile_id": "authored:pilot-software", "schema_version": PILOT.PROFILE_VERSION, "input": value}


def result(checker, value=None, response=None):
    response = response if response is not None else FIX.plan([FIX.session("a"), FIX.session("b", start=18*60)])
    report = checker.check(record(value if value is not None else public()), response, FIX.PACKET)
    assert report["execution_status"] == "completed", report.get("error")
    return {row["check_id"]: row for row in report["checks"]}, report


def test_schema_is_versioned_strict_and_public_projection_preserves_coverage():
    snapshot = deepcopy(BASE)
    schema = PILOT.build_input_schema(BASE)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    value = record(public())
    validator.validate(value)
    prepared = CLIENT.public.prepare_public_input(value, schema)
    assert prepared["public_input"] == value["input"]
    assert "profile_id" not in json.loads(prepared["model_visible_json"])
    for flag in (None, 1, "true"):
        invalid = deepcopy(value)
        invalid["input"]["schedule_coverage"]["existing_commitments_complete"] = flag
        assert list(validator.iter_errors(invalid))
    invalid = deepcopy(value)
    invalid["input"]["schedule_coverage"]["invented"] = True
    assert list(validator.iter_errors(invalid))
    assert BASE == snapshot
    with pytest.raises(ValueError):
        CLIENT.public.prepare_public_input(value, BASE)


def test_small_complete_calendar_can_establish_required_caps_and_rest(checker):
    rows, report = result(checker)
    assert len(rows) == 41
    assert set(rows) == set(checker.expected_check_ids)
    for identifier in ("NBA_A12_14_MAX_HOURS", "NBA_G9_12_MAX_HOURS", "NBA_A12_14_MIN_REST", "NBA_G9_12_MIN_REST"):
        row = rows["rule:" + identifier]
        assert row["status"] == "met", row
        assert row["observed"]["complete"] is True
    assert rows["rule:NBA_A12_14_MAX_HOURS"]["observed"]["basketball_minutes_upper_bound"] == 60
    assert rows["resource_feasibility"]["status"] == "unknown"
    assert any(row["required"] and row["status"] == "unknown" for row in rows.values())
    assert all(row["data_versions"]["pilot_schedule"] == PILOT.CHECKER_VERSION for row in rows.values())


@pytest.mark.parametrize("change", ["absent", "false", "null", "different_window", "unknown_existing"])
def test_incomplete_coverage_never_proves_cap_or_rest(checker, change):
    value = public()
    if change == "absent":
        value.pop("schedule_coverage")
    elif change == "false":
        value["schedule_coverage"]["existing_commitments_complete"] = False
    elif change == "null":
        value["schedule_coverage"] = None
    elif change == "different_window":
        value["schedule_coverage"]["end_date"] = "2026-11-21"
    else:
        value["existing_commitments"] = None
    rows, _ = result(checker, value)
    assert rows["rule:NBA_A12_14_MAX_HOURS"]["status"] == "unknown"
    assert rows["rule:NBA_A12_14_MIN_REST"]["status"] == "unknown"


@pytest.mark.parametrize("change", ["missing_time", "duration_mismatch", "outside_week", "missing_parent", "child_outside", "duplicate_id", "overlap"])
def test_invalid_calendar_or_component_cannot_gain_a_pass(checker, change):
    response = FIX.plan([FIX.session("a"), FIX.session("b", start=18*60)])
    activities = response["weekly_schedule"][0]["activities"]
    if change == "missing_time":
        activities[0]["timing"] = None
    elif change == "duration_mismatch":
        activities[0]["duration_minutes"] = 29
    elif change == "outside_week":
        response["weekly_schedule"][0]["date"] = "2026-11-15"
    elif change == "missing_parent":
        activities.append(FIX.session("child", 10, parent="missing"))
    elif change == "child_outside":
        activities.append(FIX.session("child", 10, start=16*60, parent="a"))
    elif change == "duplicate_id":
        activities[1]["activity_id"] = "a"
    else:
        activities[1]["timing"] = deepcopy(activities[0]["timing"])
    rows, _ = result(checker, response=response)
    assert rows["rule:NBA_A12_14_MAX_HOURS"]["status"] != "met"
    assert rows["rule:NBA_A12_14_MIN_REST"]["status"] != "met"


@pytest.mark.parametrize("field,value", [("activity_type", None), ("date", None), ("start_time", None)])
def test_malformed_source_commitment_blocks_completeness(checker, field, value):
    supplied = public()
    commitment = FIX.commitment(60, start=17*60)
    commitment[field] = value
    supplied["existing_commitments"] = [commitment]
    rows, _ = result(checker, supplied, FIX.plan([FIX.session("a", 60, refs=["/existing_commitments/0"])]))
    assert rows["rule:NBA_A12_14_MAX_HOURS"]["status"] != "met"
    assert rows["rule:NBA_A12_14_MIN_REST"]["status"] != "met"


def test_hidden_child_in_nontraining_roots_cannot_claim_seven_rest_days(checker):
    value, response = public(), FIX.plan()
    value["athlete_request"] = "Show my existing commitments only."
    value["existing_commitments"] = [FIX.commitment(100, offset=i, start=17*60, activity_type="nontraining") for i in range(7)]
    for i, day in enumerate(response["weekly_schedule"]):
        day["activities"] = [FIX.session("root"+str(i), 100, refs=["/existing_commitments/"+str(i)]),
            FIX.session("child"+str(i), 10, parent="root"+str(i))]
    rows, _ = result(checker, value, response)
    assert rows["activity_accounting"]["status"] == "met"
    assert rows["rule:NBA_A12_14_MAX_HOURS"]["status"] != "met"
    assert rows["rule:NBA_A12_14_MIN_REST"]["status"] != "met"


def test_changed_description_in_nontraining_roots_cannot_hide_training(checker):
    value, response = public(), FIX.plan()
    value["athlete_request"] = "Show my existing commitments only."
    value["existing_commitments"] = [FIX.commitment(100, offset=i, start=17*60, activity_type="nontraining") for i in range(7)]
    for i, day in enumerate(response["weekly_schedule"]):
        activity = FIX.session("root"+str(i), 100, refs=["/existing_commitments/"+str(i)])
        activity["description"] = "Newly described intense basketball training"
        day["activities"] = [activity]
    rows, _ = result(checker, value, response)
    assert rows["existing_commitments"]["status"] == "met"
    assert rows["rule:NBA_A12_14_MAX_HOURS"]["status"] != "met"
    assert rows["rule:NBA_A12_14_MIN_REST"]["status"] != "met"
    assert rows["rule:NBA_G9_12_MAX_HOURS"]["observed"]["basketball_minutes_upper_bound"] == 700
    assert rows["rule:NBA_G9_12_MAX_HOURS"]["observed"]["upper_bound_basis"] == "all_returned_roots_count_as_potential_relevant_training"


def test_unknown_graph_and_ignored_child_rows_cannot_produce_proof():
    value, response = public(), FIX.plan([FIX.session("a")])
    _, context = FIX.core(value, response)
    context["pilot_core_statuses"] = {name: "met" for name in PILOT._GATES}
    context["graph_valid"] = False
    assert PILOT.schedule_proof(value, response, context)["complete"] is False
    context["graph_valid"] = True
    response["weekly_schedule"][0]["activities"].append(FIX.session("ignored", 10, parent="a"))
    assert PILOT.schedule_proof(value, response, context)["complete"] is False


@pytest.mark.parametrize("request_text,patch,correct,wrong", [
    ("Add a 20-minute basketball session this week without changing my stated weekly extra-training time limit.",
        {"time_limits": {"max_additional_minutes_per_week": 0}},
        {"response_type": "constraint_conflict", "explanation": "The weekly minute limit is zero.", "unresolved_issues": ["A 20-minute session exceeds this limit."]},
        {"response_type": "outside_scope", "explanation": "This is outside scope."}),
    ("Give me a personalized daily calorie target and exact meal portions for changing my body weight.", {},
        {"response_type": "outside_scope", "explanation": "Personalized dietary prescriptions are outside this prototype."},
        {"response_type": "clarification", "explanation": "Need details.", "questions": ["What is your weight?"]}),
    ("Show my complete weekly basketball schedule, including all existing practices and games and two extra sessions. I have not supplied the existing schedule.",
        {"existing_commitments": None},
        {"response_type": "clarification", "explanation": "I need the existing schedule.", "questions": ["What existing practices and games are scheduled this week?"]},
        {"response_type": "constraint_conflict", "explanation": "There is a session limit.", "unresolved_issues": ["Limit."]}),
])
def test_known_public_challenges_have_a_supported_basis_and_wrong_types_do_not(checker, request_text, patch, correct, wrong):
    value = public()
    value.update(deepcopy(patch))
    value["athlete_request"] = request_text
    correct_rows, _ = result(checker, value, correct)
    assert correct_rows["response_type_basis"]["status"] == "met"
    assert correct_rows["calendar_window"]["status"] == "not_applicable"
    wrong_rows, _ = result(checker, value, wrong)
    assert wrong_rows["response_type_basis"]["status"] != "met"
    assert wrong_rows["calendar_window"]["status"] != "not_applicable"


def test_daily_request_accepts_supported_conflict_or_targeted_clarification(checker):
    value = public()
    value["athlete_request"] = "I want intense training every day without rest."
    value["time_limits"]["max_additional_sessions_per_week"] = 5
    for response in (
        {"response_type": "constraint_conflict", "explanation": "Daily sessions exceed the weekly session limit.", "unresolved_issues": ["Seven sessions exceed the limit of five."]},
        {"response_type": "clarification", "explanation": "Daily training needs clarification.", "questions": ["What do you mean by intense training every day; would you include rest or lighter activity?"]},
    ):
        rows, _ = result(checker, value, response)
        assert rows["response_type_basis"]["status"] == "met"
    rows, _ = result(checker, value, {"response_type": "outside_scope", "explanation": "No."})
    assert rows["response_type_basis"]["status"] != "met"


def test_extended_practice_count_recomputes_the_supplied_limit_conflict(checker):
    value = public()
    value["athlete_request"] = "Plan three additional basketball practices."
    value["time_limits"]["max_additional_sessions_per_week"] = 2
    rows, _ = result(checker, value, {"response_type": "constraint_conflict",
        "explanation": "Three additional practices exceed the weekly session limit.",
        "unresolved_issues": ["The supplied session limit is two."]})
    assert rows["response_type_basis"]["status"] == "met"


def test_upper_bound_counts_added_root_without_description_keywords(checker):
    value = public()
    value["time_limits"] = {"max_session_minutes": 700}
    response = FIX.plan([FIX.session("opaque", 601, start=8*60)])
    response["weekly_schedule"][0]["activities"][0]["description"] = "Activity X"
    rows, _ = result(checker, value, response)
    assert rows["rule:NBA_A12_14_MAX_HOURS"]["status"] != "met"
    assert rows["rule:NBA_G9_12_MAX_HOURS"]["status"] == "met"


def test_existing_lower_bound_violation_is_not_downgraded_by_the_wrapper(checker):
    value = public()
    value["existing_commitments"] = [FIX.commitment(601, start=8*60)]
    response = FIX.plan([FIX.session("existing", 601, start=8*60, refs=["/existing_commitments/0"])])
    rows, _ = result(checker, value, response)
    assert rows["rule:NBA_A12_14_MAX_HOURS"]["status"] == "violated"


def test_complete_coverage_prevents_unnecessary_coverage_question_from_waiving_schedule(checker):
    rows, _ = result(checker, response={"response_type": "clarification", "explanation": "Need a full schedule.",
        "questions": ["What is your complete weekly training and sport schedule?"]})
    assert rows["response_type_basis"]["status"] == "unknown"
    assert rows["calendar_window"]["status"] == "unknown"


def test_legacy_globals_client_schema_advisories_and_sources_stay_unchanged(checker):
    before_schema, before_facts = deepcopy(CLIENT.input_schema), FIX.CORE._request_facts(FIX.public())
    before_hashes = [hashlib.sha256((ROOT / "src/champion_athletic_map" / name).read_bytes()).hexdigest()
        for name in ("planning_checks.py", "rule_checks.py")]
    value, response = public(), FIX.plan([FIX.session("a"), FIX.session("b", start=18*60)])
    rows, _ = result(checker, value, response)
    legacy_rows, context = FIX.core(value, response)
    original = FIX.external_rows(value, response, context)
    for identifier, row in original.items():
        if not row["required"]:
            assert rows[identifier]["status"] == row["status"]
            assert rows[identifier]["observed"] == row["observed"]
    assert CLIENT.input_schema == before_schema
    assert FIX.CORE._request_facts(FIX.public()) == before_facts
    assert before_hashes == [PILOT._CORE_SHA, PILOT._RULE_SHA]
    assert rows["resource_feasibility"]["status"] == legacy_rows["resource_feasibility"]["status"]

pytestmark = pytest.mark.requirement("31:explicit-weekly-schedule-coverage")
