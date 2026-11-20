"""Check reversible report encoding with the exact saved findings and JSON edge cases."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "src/champion_athletic_map/review_encoding.py"
spec = importlib.util.spec_from_file_location("review_encoding_tests", PATH)
CODEC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CODEC)

# Only the check-results section is retained as a portable fixture. The original
# athlete, reference packet, candidate and generated notes are not duplicated.
SAVED_CHECKS_JSON = '{"columns":["check_ids","status","required","applicability","reason","observed"],"execution_status":"completed","findings":[[["output_structure"],"met",true,"applicable_or_unresolved","Shared strict JSON/schema/structure validation passed.",null],[["calendar_window"],"met",true,"applicable_or_unresolved","Seven chronological dates and planning window match.",null],[["activity_accounting","rule:POLICY_SESSION_ACCOUNTING"],"met",true,"applicable_or_unresolved","Distinct root sessions and component links are consistent.",null],[["existing_commitments","rule:USER_EXISTING_COMMITMENTS"],"met",true,"applicable_or_unresolved","Every supplied commitment is preserved once with known timing and duration.",null],[["timing_durations","rule:POLICY_TIMING_INTEGRITY"],"met",true,"applicable_or_unresolved","All declared activity durations match their local intervals.",null],[["availability_and_collisions","rule:USER_AVAILABLE_TIME"],"met",true,"applicable_or_unresolved","Added sessions fit supplied slots and known commitments without root-session overlap.",null],[["additional_training_limits"],"met",true,"applicable_or_unresolved","Known additional-session and minute limits are respected.",{"additional_sessions":3,"known_minutes":60}],[["requested_session_count"],"violated",true,"applicable_or_unresolved","Requested 2 additional sessions; scheduled 3.",null],[["resource_feasibility"],"unknown",true,"applicable_or_unresolved","Free-form activity requirements are not independently verified; declared resource conflicts remain actionable.",null],[["reference_identity","rule:POLICY_CATALOG_ELIGIBILITY"],"met",true,"applicable_or_unresolved","No optional source IDs supplied; absence is not a catalog-membership failure.",null],[["response_type_basis","rule:POLICY_REQUIRED_INFORMATION"],"met",true,"applicable_or_unresolved","No coded public scope, essential-information or numeric conflict prevents planning.",null],[["rule:USER_EQUIPMENT_SPACE"],"unknown",true,"applicable_or_unresolved","Declared equipment space checks: unknown; unknown activity-specific requirements are not assumed.",null],[["rule:USER_PARTICIPANTS"],"unknown",true,"applicable_or_unresolved","Declared participants checks: unknown; unknown activity-specific requirements are not assumed.",null],[["rule:POLICY_SCOPE"],"met",true,"applicable_or_unresolved","Basketball planning and its relevant clarifications or conflicts are in scope.",null],[["rule:POLICY_RESULT_SEMANTICS"],"met",true,"applicable_or_unresolved","Four-state results retain reasons and unknown evidence.",null],[["rule:POLICY_INDEPENDENT_EVALUATION"],"met",true,"applicable_or_unresolved","Internal checks use public inputs and do not produce independent research scores.",null],[["rule:POLICY_REVIEW_ACTIVATION"],"met",true,"applicable_or_unresolved","Active delegated approval hashes and all 29 adopted definitions were verified.",null],[["rule:NBA_A12_14_MAX_HOURS"],"met",true,"applicable","The conservative weekly basketball-time upper bound is within the adopted maximum.",{"basketball_active_days_upper_bound":["2026-11-16","2026-11-18","2026-11-21"],"basketball_minutes_upper_bound":60,"complete":true,"known_minutes_lower_bound":60,"maximum_minutes":600,"policy":"pilot-schedule-checks-2","reason":"Explicit public coverage and complete timed session/component accounting support conservative upper bounds.","sport_active_days_upper_bound":["2026-11-16","2026-11-18","2026-11-21"],"upper_bound_basis":"all_returned_roots_count_as_potential_relevant_training"}],[["rule:NBA_G9_12_MAX_HOURS","rule:NBA_G9_12_MIN_REST"],"not_applicable",true,"not_applicable","The supplied age or grade is outside this source population.",null],[["rule:NBA_A12_14_MIN_REST"],"met",true,"applicable","Complete public coverage establishes the adopted minimum number of basketball-rest days.",{"basketball_active_days_upper_bound":["2026-11-16","2026-11-18","2026-11-21"],"basketball_minutes_upper_bound":60,"complete":true,"complete_schedule_established":false,"known_active_days":3,"policy":"pilot-schedule-checks-2","reason":"Explicit public coverage and complete timed session/component accounting support conservative upper bounds.","sport_active_days_upper_bound":["2026-11-16","2026-11-18","2026-11-21"],"upper_bound_basis":"all_returned_roots_count_as_potential_relevant_training"}],[["rule:NBA_A13_14_SLEEP","rule:CDC_TEENS_SLEEP"],"unknown",false,"applicable","A nightly average does not establish each night\'s sleep or a daily 24-hour measurement.",null],[["rule:NBA_G9_12_SLEEP","rule:NBA_G9_12_PRACTICE_LENGTH","rule:NBA_G9_12_PRACTICES","rule:NBA_G9_12_GAMES_WEEK"],"not_applicable",false,"not_applicable","The supplied age or grade is outside this source population.",null],[["rule:NBA_A12_14_PRACTICE_LENGTH"],"unknown",false,"applicable","The full practice-session set is not established; this source range remains advisory.",{"known_practice_minutes":[],"recommended_range":[60,90]}],[["rule:NBA_A12_14_PRACTICES"],"unknown",false,"applicable","Complete classified weekly event coverage is not established; missing events are not assumed absent.",{"advisory_maximum":4,"known_event_days_lower_bound":0}],[["rule:NBA_A12_14_GAMES_WEEK"],"unknown",false,"applicable","Complete classified weekly event coverage is not established; missing events are not assumed absent.",{"advisory_maximum":2,"known_event_days_lower_bound":0}],[["rule:AAP_WEEKLY_SPORT_REST"],"unknown",false,"applicable","Apparently free days do not establish rest without complete classified schedule coverage.",{"complete_schedule_established":false,"known_active_days":3}],[["rule:RECOVERY-GUIDANCE-6e306f115a65dbdd9e95","rule:RECOVERY-GUIDANCE-48fe143c5cd140813352","rule:RECOVERY-GUIDANCE-9918e3d81af2dba2604b"],"unknown",false,"applicable","The required reported context does not support an automatic conclusion.",null],[["food_facts_numeric"],"unknown",true,"applicable","No structured food statement was supplied for exact quantity, identity and unit comparison.",null]]}'
SAVED_CHECKS = json.loads(SAVED_CHECKS_JSON)


def exact(a, b):
    # JSON text distinguishes False/0, 0/0.0, null/absence and escaped strings.
    return CODEC._json(a) == CODEC._json(b)


def test_exact_saved_checks_round_trip_and_reduce_bytes():
    assert hashlib.sha256(SAVED_CHECKS_JSON.encode()).hexdigest() == "cc3eb62371024c9c515c031e85331795ba7c3adf076e632792255f52cdf81ae5"
    original = deepcopy(SAVED_CHECKS)
    encoded = CODEC.encode_checks(original)
    assert encoded["encoding"] == CODEC.ENCODING_VERSION
    assert exact(CODEC.decode_checks(encoded), original)
    assert original == SAVED_CHECKS
    assert CODEC._size(original) == 5997
    assert CODEC._size(original) - CODEC._size(encoded) >= 1100
    # This is a UTF-8 representation measurement, not a native-token fit claim.
    assert CODEC._size(original) - CODEC._size(encoded) > len(CODEC.ENCODING_NOTICE.encode())


def test_only_check_results_change_in_complete_user_view():
    view = {"athlete_input": {"request": "Café Ω 中文 🏀\nKeep every fact.", "known": False, "zero": 0},
        "reference_data": {"references": [{"text": "Full quoted source\nwith \"escapes\"."}]},
        "candidate": {"calendar_table": {"fields": {"unchanged": None}}},
        "specialist_notes": [{"role": "training", "contribution": {"text": "Keep this whole."}}],
        "evaluator_assessment": {"assessment_complete": True, "issues": [{"path": "/a~1b", "correction": "Keep all issues."}]},
        "check_results": deepcopy(SAVED_CHECKS)}
    before = deepcopy(view)
    encoded = CODEC.encode_view(view)
    for key in view:
        if key != "check_results":
            assert exact(encoded[key], view[key])
    assert exact(CODEC.decode_view(encoded), view)
    assert exact(view, before)


def test_pool_and_defaults_preserve_json_types_null_missing_and_control_looking_fields():
    values = [False, 0, 0.0, None, "", [], {}, {"absent_elsewhere": None},
        {"values": [], "default": False, "pool": [0], "indexes": [0], "shared_fields": []},
        "Café Ω 中文 🏀\n\t\\\"", True, 1, 1.0]
    report = {"columns": ["check_ids", "observed"], "findings": [[[str(i)], value] for i, value in enumerate(values*6)],
        "encoding": CODEC.ENCODING_VERSION, "extra": {"preserve": None}}
    encoded = CODEC.encode_checks(report)
    decoded = CODEC.decode_checks(encoded)
    assert exact(decoded, report)
    restored = [row[1] for row in decoded["findings"]]
    assert type(restored[0]) is bool and type(restored[1]) is int and type(restored[2]) is float
    assert "absent_elsewhere" not in restored[6] and restored[7]["absent_elsewhere"] is None


def test_common_object_fields_restore_every_value_and_preserve_absence():
    shared = {"proof": "Exact long proof wording remains available. "*12, "complete": True,
        "dates": ["2026-11-16", "2026-11-18"], "literal_null": None}
    objects = [{**shared, "minutes": 60}, {**shared, "rest": 4}, {"minutes": 60}, {"rest": None}]
    encoded = CODEC._encode_column(objects)
    assert "shared_fields" in encoded
    report = {"encoding": CODEC.ENCODING_VERSION, "fields": {"execution_status": "completed"},
        "columns": ["observed"], "row_count": 4, "data": [encoded]}
    decoded = CODEC.decode_checks(report)
    assert exact(decoded["findings"], [[value] for value in objects])
    assert "literal_null" not in decoded["findings"][2][0]


@pytest.mark.parametrize("value", [None, [], {"anything": True},
    {"columns": ["a", "a"], "findings": [[1, 2]]},
    {"columns": ["a"], "findings": [[1, 2]]},
    {"columns": ["a"], "findings": []},
    {"columns": [], "findings": [[], []]}])
def test_unrecognized_or_unhelpful_shapes_remain_unchanged(value):
    assert exact(CODEC.decode_checks(CODEC.encode_checks(value)), value)


@pytest.mark.parametrize("column", [
    {"default": None, "exceptions": [[0, 1], [0, 2]]},
    {"default": None, "exceptions": [[True, 1]]},
    {"default": None, "exceptions": [[-1, 1]]},
    {"values": [1]},
    {"pool": [False], "indexes": [False, 0]},
    {"pool": [False], "indexes": [0, 1]},
    {"values": [{"x": 1}, {}], "shared_fields": [[[0], {"x": 2}]]},
    {"values": [{}, {}], "shared_fields": [[[0], {"x": 1}], [[0], {"y": 2}]]},
    {"values": [{}, {}], "shared_fields": [[[2], {"x": 1}]]},
])
def test_invalid_encoded_columns_fail_closed(column):
    report = {"encoding": CODEC.ENCODING_VERSION, "fields": {}, "columns": ["observed"],
        "row_count": 2, "data": [column]}
    with pytest.raises(ValueError):
        CODEC.decode_checks(report)


def test_decoder_returns_independent_mutable_values():
    report = {"encoding": CODEC.ENCODING_VERSION, "fields": {}, "columns": ["observed"],
        "row_count": 2, "data": [{"default": {"list": []}, "exceptions": []}]}
    result = CODEC.decode_checks(report)
    result["findings"][0][0]["list"].append(1)
    assert result["findings"][1][0] == {"list": []}
    assert report["data"][0]["default"] == {"list": []}


def test_callback_uses_canonical_text_and_keeps_cost_local():
    baseline = CODEC.encode_checks(SAVED_CHECKS)
    cost_function = CODEC._size
    calls = []
    def counter(text):
        assert type(text) is str
        value = json.loads(text)
        assert CODEC._json(value) == text
        calls.append(text)
        return len(text) + (100000 if type(value) is dict and "pool" in value else 0)
    encoded = CODEC.encode_checks(SAVED_CHECKS, count_tokens=counter)
    assert calls and exact(CODEC.decode_checks(encoded), SAVED_CHECKS)
    assert encoded != baseline
    assert CODEC._size is cost_function
    assert exact(CODEC.encode_checks(SAVED_CHECKS), baseline)


def test_saved_native_column_costs_can_choose_a_different_layout_than_bytes():
    values = [row[1] for row in SAVED_CHECKS["findings"]]
    # These three costs were measured with the source-table native BPE on the
    # exact saved status column, not with the language model or a backend call.
    native_costs = {
        "6d6bdd75b3f301c83183b5a4fb3edca38a33a430bf9d149aca8755a01c6205f9": 64,
        "6b43171b1dbe180722ea1c5993377806c0944533ee0c414e62aad1008a76f820": 78,
        "11db064cb8b3e7449dd51a981fd1c4f5747c266111c43e2d9685a95975f842c6": 72,
    }
    def native_cost(value):
        return native_costs[hashlib.sha256(CODEC._json(value).encode()).hexdigest()]
    assert "pool" in CODEC._column(values)
    assert CODEC._column(values, cost=native_cost) == {"values": values}


@pytest.mark.parametrize("invalid", [-1, True, 1.5, None])
def test_invalid_token_cost_is_rejected(invalid):
    with pytest.raises(ValueError, match="nonnegative integer"):
        CODEC.encode_checks(SAVED_CHECKS, count_tokens=lambda text: invalid)

pytestmark = pytest.mark.requirement("31:lossless-final-revision-continuation")
