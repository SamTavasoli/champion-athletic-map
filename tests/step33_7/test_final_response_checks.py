"""Check frozen bindings and parent accounting without generating a reply."""
from copy import deepcopy
import pytest
from champion_athletic_map import final_response_checks as final


def row(key, status="met", required=True):
    return {"check_id": key, "status": status, "reason": "Recorded test evidence.", "required": required}


def fixture_binding():
    record = {"profile_id": "fictional-test", "schema_version": "athlete-profile-input-2", "input": {"age": 14}}
    schema = {"type": "object", "properties": {"response_type": {"const": "plan"}}, "required": ["response_type"], "additionalProperties": False}
    bundle = {"local_response_schema": schema}
    identifier = final.sha(final.canonical(bundle))
    binding = {"profile_id": record["profile_id"], "public_record_canonical_sha256": final.sha(final.canonical(record)),
        "public_input_canonical_sha256": final.sha(final.canonical(record["input"])), "contract_bundle_id": identifier,
        "local_response_schema_sha256": final.sha(final.canonical(schema))}
    assessor = final.FinalResponseAssessor.__new__(final.FinalResponseAssessor)
    assessor.bindings = {record["profile_id"]: binding}
    assessor.contracts = {"contract_bundles": {identifier: bundle}}
    annotation = {"profile_id": record["profile_id"], "public_record_sha256": final.sha(final.packed(record)),
        "case_authoring_accepted": True, "case_category": "feasible"}
    return assessor, record, annotation


def test_exact_case_binding():
    assessor, record, annotation = fixture_binding()
    assert assessor.validate_case_binding(record, annotation)["accepted_case_version_verified"] is True


@pytest.mark.parametrize("field", ["age", "profile_id", "private_annotation"])
def test_changed_public_case_rejected(field):
    assessor, record, annotation = fixture_binding()
    if field == "age":
        record["input"][field] = 15
    else:
        record[field] = "changed"
    with pytest.raises(ValueError):
        assessor.validate_case_binding(record, annotation)


def test_stale_schema_rejected():
    assessor, record, annotation = fixture_binding()
    next(iter(assessor.contracts["contract_bundles"].values()))["local_response_schema"]["additionalProperties"] = True
    with pytest.raises(ValueError):
        assessor.validate_case_binding(record, annotation)


def test_stale_annotation_rejected():
    assessor, record, annotation = fixture_binding()
    annotation["public_record_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        assessor.validate_case_binding(record, annotation)


def test_aliases_do_not_multiply_coverage():
    checks = [row("availability_and_collisions"), row("additional_training_limits"), row("rule:USER_AVAILABLE_TIME")]
    report = final.parent_report(checks, {})
    assert len(report["parent_checks"]) == 2
    assert report["parent_coverage"]["required"]["parent_checks"] == 2
    assert report["retained_policy_aliases"]["rule:USER_AVAILABLE_TIME"] == ["availability_and_collisions", "additional_training_limits"]


def test_numeric_aliases_scored_once_at_declared_most_restrictive_bound():
    annotation = {"rule_applicability": {"numeric_groups": [{"evaluation_group_id": "weekly_minutes", "operator": "<=", "threshold": 600,
        "rule_refs": [{"rule_id": "age_cap"}, {"rule_id": "grade_cap"}]}]}}
    report = final.parent_report([row("rule:age_cap", "violated"), row("rule:grade_cap")], annotation)
    assert len(report["parent_checks"]) == 1
    assert report["parent_checks"][0]["status"] == "violated"
    assert report["parent_checks"][0]["threshold"] == 600


def test_unknown_prevents_positive_parent_and_empty_coverage_is_unavailable():
    assert final.combine([row("a"), row("b", "unknown")]) == "unknown"
    assert final.coverage([])["determinate_coverage"] is None
    assert final.coverage([row("a", "not_applicable")])["determinate_coverage"] is None


def test_advisory_coverage_kept_separate():
    result = final.parent_report([row("required"), row("advisory", "unknown", False)], {})
    assert result["parent_coverage"]["required"]["determinate_coverage"] == 1
    assert result["parent_coverage"]["advisory"]["determinate_coverage"] == 0


def test_duplicate_checks_rejected():
    with pytest.raises(ValueError):
        final.parent_report([row("a"), row("a")], {})


def test_requested_duration_mismatch_dominates_unknown_graph():
    requests = type('Requests', (), {'requested_duration': staticmethod(lambda public: 20)})
    result = final.duration_check({}, {}, requests, lambda response: ([{'duration_minutes': 15}], False),
        structure_valid=False, supported_nonplan=False)
    assert result['status'] == 'violated'


def test_requested_duration_missing_and_matching():
    requests = type('Requests', (), {'requested_duration': staticmethod(lambda public: 20)})
    assert final.duration_check({}, {}, requests, lambda response: ([{'duration_minutes': None}], True),
        structure_valid=True, supported_nonplan=False)['status'] == 'unknown'
    assert final.duration_check({}, {}, requests, lambda response: ([{'duration_minutes': 20}], True),
        structure_valid=True, supported_nonplan=False)['status'] == 'met'


def test_maximum_is_not_an_exact_requested_duration():
    requests = type('Requests', (), {'requested_duration': staticmethod(lambda public: None)})
    assert final.duration_check({'time_limits': {'max_session_minutes': 20}}, {}, requests,
        lambda response: ([{'duration_minutes': 15}], True), structure_valid=True, supported_nonplan=False)['status'] == 'not_applicable'


def test_supported_nonplan_duration_needs_no_plan():
    requests = type('Requests', (), {'requested_duration': staticmethod(lambda public: 20)})
    assert final.duration_check({}, {'response_type': 'constraint_conflict'}, requests,
        lambda response: ([], False), structure_valid=False, supported_nonplan=True)['status'] == 'not_applicable'


@pytest.fixture(scope='module')
def composed_assessor():
    """Build only software clients and synthetic inputs; no inference or retrieval."""
    import os
    from pathlib import Path
    from champion_athletic_map import runtime_settings
    root = Path(os.environ.get('CAM_TEST_PROJECT_ROOT', Path(__file__).resolve().parents[2]))
    if not (root / 'artifacts/language_model/integration_config.json').is_file():
        pytest.skip('The composed checker requires the local project resource release.')
    import json
    schema_path = 'artifacts/pilot/case_review_794f10d9d10a5fde/public_profile_schema.json'
    schema = json.loads((root / schema_path).read_bytes())
    window = {'start_date': '2026-11-16', 'end_date': '2026-11-22', 'timezone': 'America/Los_Angeles'}
    public = {'age': 14, 'school_grade': 9, 'planning_window': window,
        'athlete_request': 'Plan one additional 20-minute basketball practice block.',
        'availability': [{'date': '2026-11-16', 'start_time': '17:00', 'end_time': '17:30'}],
        'existing_commitments': [], 'equipment': [{'name': 'basketball', 'quantity': 1}],
        'participants_available': 1,
        'space': {'court_access': 'full_court', 'hoop_access': True, 'usable_area_description': 'Full basketball court.', 'restrictions': []},
        'time_limits': {'max_additional_sessions_per_week': 2, 'max_additional_minutes_per_week': 40, 'max_session_minutes': 20},
        'schedule_coverage': {**window, 'existing_commitments_complete': True}}
    records = [{'profile_id': 'software-synthetic-' + str(i), 'schema_version': 'athlete-profile-input-2', 'input': deepcopy(public)} for i in range(200)]
    records[0]['input']['food_question'] = 'For the food "Fictional food", how many grams of protein are recorded for 100 g?'
    paths = ['src/champion_athletic_map/' + name + '.py' for name in ('llm', 'request_contracts', 'operational_runtime', 'contract_runtime', 'corrected_runtime', 'food_response_validation')]
    contracts_folder = 'artifacts/language_model/shared_contracts/contracts_3293242853ce2cf7/'
    paths += [contracts_folder + name for name in ('public_input.py', 'planner_response_schema.json')]
    paths += [schema_path, 'artifacts/planners/version3_note_schema.json', 'artifacts/planners/version4_evaluator_schema.json']
    inventory = {'schema_version': runtime_settings.VERSION, 'source_file_sha256': {p: final.sha((root / p).read_bytes()) for p in paths}}
    inventory['settings_id'] = final.sha(final.packed(inventory))
    contracts = runtime_settings.build_case_contracts(root, records, inventory)
    assessor = final.FinalResponseAssessor(root, schema, contracts)
    annotations = [{'profile_id': r['profile_id'], 'public_record_sha256': final.sha(final.packed(r)),
        'case_authoring_accepted': True, 'case_category': 'feasible'} for r in records]
    return assessor, records, annotations


def synthetic_plan(*, duration=20):
    from datetime import date, timedelta
    start = date(2026, 11, 16)
    response = {'response_type': 'plan', 'explanation': 'We schedule the requested practice block.',
        'planning_window': {'start_date': '2026-11-16', 'end_date': '2026-11-22', 'timezone': 'America/Los_Angeles'},
        'weekly_schedule': [{'date': (start + timedelta(days=i)).isoformat(), 'activities': [], 'rest_arrangements': 'No additional training.'} for i in range(7)]}
    response['weekly_schedule'][0]['activities'] = [{'activity_id': 'synthetic-session', 'description': 'Practice basketball ball handling.',
        'duration_minutes': duration, 'timing': {'start_time': '17:00', 'end_time': '17:' + str(duration).zfill(2)},
        'resources': {'equipment': [{'name': 'basketball', 'quantity': 1}], 'space': 'full court', 'participants': 1},
        'relationship': {'kind': 'separate_session', 'parent_activity_id': None}, 'existing_commitment_refs': []}]
    return response


def assess_synthetic(fixture, response, *, index=1, completion=True, **other):
    import json
    assessor, records, annotations = fixture
    raw = response if isinstance(response, str) else json.dumps(response)
    return assessor.assess(records[index], {'completion_valid': completion, 'response': {'model_output': {'raw_text': raw}}, **other},
        {'payload': {'references': [], 'food_lookup': []}}, assessment_id='synthetic-software-assessment', case_annotation=annotations[index])


def test_composed_effective_food_contract_and_calendar_dates(composed_assessor):
    missing_food = assess_synthetic(composed_assessor, synthetic_plan(), index=0)
    assert missing_food['assessment_execution'] == 'completed'
    assert missing_food['final_metrics']['strict_format_valid'] is False
    response = synthetic_plan()
    response['weekly_schedule'][1]['date'] = '2026-11-16'
    changed_dates = assess_synthetic(composed_assessor, response)
    assert changed_dates['assessment_execution'] == 'completed'
    assert changed_dates['final_metrics']['strict_format_valid'] is False


def test_composed_no_reply_or_malformed_are_model_failures(composed_assessor):
    for raw in ('', 'not JSON', '{"response_type":"plan","response_type":"plan"}'):
        result = assess_synthetic(composed_assessor, raw, completion=False)
        assert result['assessment_execution'] == 'completed'
        assert result['final_metrics']['automated_feasible_plan_success'] is False
        assert result['final_metrics']['designated_workflow_completed'] is False


def test_composed_checker_exception_is_incomplete(composed_assessor):
    assessor, _, _ = composed_assessor
    original = assessor.assessor.calendar.check
    def broken(*args, **kwargs):
        raise RuntimeError('Synthetic external checker failure.')
    assessor.assessor.calendar.check = broken
    try:
        result = assess_synthetic(composed_assessor, synthetic_plan())
    finally:
        assessor.assessor.calendar.check = original
    assert result['assessment_execution'] == 'error'
    assert result['final_metrics'] is None


def test_composed_self_parent_and_changed_duration_never_pass(composed_assessor):
    response = synthetic_plan()
    response['weekly_schedule'][0]['activities'][0]['relationship'] = {'kind': 'part_of_activity', 'parent_activity_id': 'synthetic-session'}
    result = assess_synthetic(composed_assessor, response, internal_review_passed=True)
    assert result['assessment_execution'] == 'completed'
    assert result['final_metrics']['automated_feasible_plan_success'] is False
    assert result['internal_evaluator_used_for_verdict'] is False
    changed = assess_synthetic(composed_assessor, synthetic_plan(duration=15))
    assert changed['assessment_execution'] == 'completed'
    assert next(r for r in changed['checks'] if r['check_id'] == 'requested_session_duration')['status'] == 'violated'
    assert changed['overall'] == 'requirements_violated'
    assert 'requested_session_duration' in changed['required_parent_violations']


def test_public_goal_echo_and_source_identifier_are_not_semantic_proof():
    result = final.goal_check({'goals': ['Improve shooting']}, {'response_type': 'plan',
        'explanation': 'This plan improves shooting.', 'evidence_refs': ['approved-source']}, supported_nonplan=False)
    assert result['status'] == 'unknown'
    assert result['required'] is True
    assert result['observed']['semantic_verification_implemented'] is False


def test_goal_nonplan_exemption_requires_supported_public_basis():
    public = {'goals': ['Improve shooting']}
    response = {'response_type': 'clarification'}
    assert final.goal_check(public, response, supported_nonplan=False)['status'] == 'unknown'
    assert final.goal_check(public, response, supported_nonplan=True)['status'] == 'not_applicable'


@pytest.mark.parametrize('malformed', ['[1]', '7', '"text"', 'null',
    {'response_type': 'plan', 'explanation': 'Schedule.', 'weekly_schedule': 5},
    {'response_type': 'plan', 'explanation': 'Schedule.', 'weekly_schedule': [{'date': '2026-11-16', 'activities': 5}]},
    {'response_type': 'plan', 'explanation': 'Schedule.', 'food_facts': 5}])
def test_valid_json_with_invalid_contract_shape_is_completed_model_failure(composed_assessor, malformed):
    result = assess_synthetic(composed_assessor, malformed)
    assert result['assessment_execution'] == 'completed', result.get('error')
    assert result['final_metrics']['strict_format_valid'] is False
    assert result['final_metrics']['automated_feasible_plan_success'] is False
    assert result['schema_invalid_object_used_for_semantic_positive_result'] is False
