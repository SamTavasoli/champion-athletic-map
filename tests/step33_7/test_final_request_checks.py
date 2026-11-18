"""We check literal requests with fictional public examples."""
from copy import deepcopy
from champion_athletic_map import final_request_checks as rules


def public(request="Arrange 2 additional practice blocks."):
    return {"athlete_request": request, "age": 15,
        "planning_window": {"start_date": "2026-12-07", "end_date": "2026-12-13", "timezone": "America/Los_Angeles"},
        "availability": [{"date": "2026-12-08", "start_time": "17:00", "end_time": "17:20"},
                         {"date": "2026-12-10", "start_time": "17:00", "end_time": "17:20"}],
        "existing_commitments": [], "space": {"court_access": "full_court", "hoop_access": True},
        "participants_available": 2, "time_limits": {"max_additional_sessions_per_week": 5,
        "max_additional_minutes_per_week": 80, "max_session_minutes": 40}}


def test_blocks_and_old_session_wording_agree():
    for phrase in ("2 extra practice blocks", "two additional basketball sessions", "two additional workouts", "2 extra practices"):
        assert rules.requested_count(public("Arrange " + phrase + "."))[0] == 2


def test_explicit_zero_has_own_basis():
    assert rules.requested_count(public("No additional training this week.")) == (0, "explicit_no_additional_training")


def test_maximum_never_becomes_requested_count():
    assert rules.requested_count(public("Build a basketball schedule."))[0] is None


def test_conflicting_counts_remain_unknown():
    assert rules.requested_count(public("Add two extra sessions and three additional workouts."))[0] is None


def test_repeated_same_count_is_not_ambiguous():
    assert rules.requested_count(public("Add two extra sessions. Schedule 2 additional practice blocks."))[0] == 2


def test_bounds_are_not_exact_requests():
    for phrase in ("at least 2 extra sessions", "at most 2 extra sessions", "up to 2 extra sessions", "between 2 extra sessions"):
        assert rules.requested_count(public("Arrange " + phrase))[0] is None


def test_number_range_is_not_an_exact_request():
    for phrase in ("2 or 3 extra sessions", "2-3 additional practice blocks", "2 to 3 extra practices"):
        assert rules.requested_count(public("Arrange " + phrase))[0] is None


def test_negated_count_is_not_a_prescription():
    assert rules.requested_count(public("Do not schedule 2 extra practice blocks."))[0] is None


def test_one_uninterrupted_block_has_count_and_duration():
    value = public("Keep one uninterrupted 40-minute basketball block inside one listed window.")
    assert rules.requested_count(value)[0] == 1
    assert rules.requested_duration(value) == 40


def test_added_block_without_extra_word():
    value = public("Add one 10-minute basketball practice block.")
    assert rules.requested_count(value)[0] == 1
    assert rules.requested_duration(value) == 10


def test_distinct_date_request_sets_count():
    value = public("Place an additional 20-minute basketball block on 3 distinct dates using only my availability.")
    assert rules.requested_count(value)[0] == 3
    assert rules.distinct_date_proof(value)["bound"] == 2


def test_same_date_windows_are_counted_once():
    value = public("Add an additional basketball block on 2 different days.")
    value["availability"][1]["date"] = value["availability"][0]["date"]
    assert rules.distinct_date_proof(value)["bound"] == 1


def test_exact_distinct_date_capacity_has_no_conflict():
    assert rules.distinct_date_proof(public("Add an additional 20-minute basketball block on 2 distinct dates.")) is None


def test_unknown_availability_cannot_prove_shortage():
    value = public("Add an additional basketball block on 3 distinct dates.")
    value["availability"] = None
    assert rules.distinct_date_proof(value) is None


def test_malformed_availability_cannot_hide_an_extra_day():
    value = public("Add an additional basketball block on 3 distinct dates.")
    value["availability"].append({"date": "unreported", "start_time": "17:00", "end_time": "17:20"})
    assert rules.distinct_date_proof(value) is None


def test_unknown_commitments_do_not_increase_available_date_bound():
    value = public("Add an additional basketball block on 3 distinct dates.")
    value["existing_commitments"] = None
    assert rules.distinct_date_proof(value)["bound"] == 2


def test_existing_commitment_can_remove_known_duration_capacity():
    value = public("Add an additional 20-minute basketball block on 2 distinct dates.")
    value["existing_commitments"] = [{"date": "2026-12-08", "start_time": "17:05", "end_time": "17:15"}]
    assert rules.distinct_date_proof(value)["bound"] == 1


def test_boundary_touching_commitment_does_not_block_practice():
    value = public("Add an additional 20-minute basketball block on 2 distinct dates.")
    value["existing_commitments"] = [{"date": "2026-12-08", "start_time": "16:40", "end_time": "17:00"}]
    assert rules.distinct_date_proof(value) is None


def test_adjoining_availability_is_conservative_upper_bound():
    value = public("Add an additional 30-minute basketball block on 2 distinct dates.")
    value["availability"] += [{"date": "2026-12-08", "start_time": "17:20", "end_time": "17:40"},
                              {"date": "2026-12-10", "start_time": "17:20", "end_time": "17:40"}]
    assert rules.distinct_date_proof(value) is None


def test_invalid_or_unknown_week_does_not_prove_chronology():
    value = public("Add an additional basketball block on 3 distinct dates.")
    value["planning_window"]["start_date"] = "2026-12-20"
    assert rules.distinct_date_proof(value) is None


def test_outside_week_dates_do_not_increase_capacity():
    value = public("Add an additional basketball block on 3 distinct dates.")
    value["availability"].append({"date": "2026-12-15", "start_time": "17:00", "end_time": "17:20"})
    assert rules.distinct_date_proof(value)["bound"] == 2


def test_conflict_explanation_requires_actual_counts_and_basis():
    value = public("Add an additional basketball block on 3 distinct dates.")
    response = {"response_type": "constraint_conflict", "explanation": "You requested 3 different dates but only 2 dates are available."}
    assert rules.response_conflict_basis(value, response)["status"] == "met"
    response["explanation"] = "You requested 4 dates but only 2 are available."
    assert rules.response_conflict_basis(value, response)["status"] == "unknown"
    response["explanation"] = "Only 2 dates are available. There are 3 basketballs."
    assert rules.response_conflict_basis(value, response)["status"] == "unknown"
    response["explanation"] = "There is no conflict between 3 dates and 2 available days."
    assert rules.response_conflict_basis(value, response)["status"] == "unknown"


def test_a_plan_does_not_waive_known_distinct_date_conflict():
    value = public("Add an additional basketball block on 3 distinct dates.")
    assert rules.response_conflict_basis(value, {"response_type": "plan"})["status"] == "violated"


def test_request_facts_are_non_mutating_and_do_not_replace_limits():
    value = public()
    before = deepcopy(value)
    original = {"essential_missing": [], "conflict": None, "outside_scope": False, "only_existing": False, "keep": {"a": 1}}
    result = rules.request_facts(value, original)
    assert result["requested_sessions"] == 2
    assert result["keep"] == original["keep"]
    assert "requested_sessions" not in original and value == before


def test_literal_weekly_zero_conflict_is_detected():
    value = public("Add one 10-minute basketball practice block.")
    value["time_limits"]["max_additional_minutes_per_week"] = 0
    assert rules.request_facts(value, {})["conflict"]


def test_essential_missing_fields_come_from_public_task():
    value = public("Lay out my whole basketball week, including every existing practice and game.")
    value["existing_commitments"] = None
    assert "existing_commitments" in rules.request_facts(value, {})["essential_missing"]
    value = public("I want basket-shooting practice with specific shooting locations.")
    value["space"] = {"court_access": None, "hoop_access": None}
    assert "court_or_hoop" in rules.request_facts(value, {})["essential_missing"]
    value = public("Give each person in my passing group an exact role and turn order.")
    value["participants_available"] = None
    assert "participants" in rules.request_facts(value, {})["essential_missing"]


def test_scope_service_requests_are_literal_not_goals():
    for request in ("Create a study plan for my upcoming history exam.",
                    "Choose performance supplements for me and specify the amount and timing of each dose.",
                    "Set my personal calorie needs and prescribe a daily eating plan with exact quantities.",
                    "Find the medical cause of knee pain and prescribe rehabilitation exercises."):
        assert rules.request_facts(public(request), {})["outside_scope"] is True
    assert not rules.request_facts(public("Do not prescribe supplements. Arrange 2 additional practice blocks."), {}).get("outside_scope")


def test_negated_distinct_date_and_duration_requests_do_not_create_proofs():
    value = public("Do not schedule an additional 40-minute basketball block on 3 distinct dates.")
    assert rules.requested_count(value)[0] is None
    assert rules.requested_duration(value) is None
    assert rules.distinct_date_proof(value) is None
    assert rules.request_facts(value, {"requested_duration": 40, "conflict": "legacy first-match conflict"})["conflict"] is None


def test_qualified_duration_does_not_become_exact_dose():
    assert rules.requested_duration(public("Schedule up to 30-minute basketball blocks.")) is None


def test_conflicting_durations_do_not_leave_legacy_duration():
    value = public("Add one 20-minute basketball block or one 30-minute basketball block.")
    assert rules.requested_duration(value) is None
    assert rules.request_facts(value, {"requested_duration": 20})["requested_duration"] is None
