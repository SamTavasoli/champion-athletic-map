"""Prepare private, current-version evidence for the fifty challenge cases.

No case, family or team decision is adopted. Expected behavior is private
review evidence and must not be added to public profiles, prompts or RAG.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import re


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _sha(value):
    return hashlib.sha256(_packed(value)).hexdigest()


def minutes(time):
    _require(isinstance(time, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", time), "A challenge time is not a valid HH:MM value.")
    hour, minute = map(int, time.split(":"))
    return hour * 60 + minute


def evidence(path, value, **extra):
    return {"path": path, "value": deepcopy(value), **extra}


def build_challenge_review(profiles, metadata):
    """Review actual passed v2 challenge facts; return private proposals only."""
    originals = list(profiles.values()) if isinstance(profiles, dict) else list(profiles)
    source_rows = list(metadata.values()) if isinstance(metadata, dict) else list(metadata)
    records = {row["profile_id"]: row for row in originals}
    _require(len(records) == len(originals) and len(source_rows) == len({row["profile_id"] for row in source_rows}), "Duplicate challenge-population IDs.")
    _require({row["profile_id"] for row in source_rows} <= set(records), "A metadata case is absent from current public profiles.")
    _require(all(row["schema_version"] == "athlete-profile-input-2" for row in originals), "The challenge review requires current version-2 public profiles.")
    before_sha = _sha(originals)
    reviewed = []
    types = Counter()
    for row in source_rows:
        category = row['scenario_intent']
        if category == 'feasible':
            continue
        profile = records[row['profile_id']]
        public = profile['input']
        request = public['athlete_request']
        result = {'profile_id': row['profile_id'], 'source_record_sha256': _sha(profile), 'source_input_sha256': _sha(public), 'age': public['age'], 'draft_category': category, 'proposed_category': category, 'category_supported_by_public_input': True, 'review_kind': 'assistant_analysis_proposal', 'accepted': False, 'team_reviews_created': 0, 'evidence': [evidence('/input/athlete_request', request)], 'essential_questions': [], 'suggested_source_corrections': [], 'migration_note': 'The current v2 challenge input explicitly retains null schedule_coverage. Keep that uncertainty; do not infer completeness from an event list or supply a new completeness fact while reviewing these challenge cases.', 'category_confounds': [], 'recorded_food_fact_question_present': bool(public.get('food_question'))}
        _require('schedule_coverage' in public and public['schedule_coverage'] is None, 'A saved challenge fact does not support its reviewed category.')
        if category == 'missing_information':
            result['expected_response_type'] = 'clarification'
            if 'extra-practice dates and time windows' in request:
                _require(public.get('availability') is None, 'A saved challenge fact does not support its reviewed category.')
                state = 'omitted' if 'availability' not in public else 'explicit_null'
                result['challenge_subtype'] = 'unknown_availability'
                result['evidence'].append(evidence('/input/availability', None, field_state=state))
                result['essential_questions'] = ['Which dates and start/end times are available for extra practice within the stated planning week?']
                result['rationale'] = 'A dated practice schedule cannot assign sessions to permitted windows while the requested availability is unknown. Omitted and null values both preserve uncertainty; neither means an empty confirmed availability list.'
                result['expected_behavior'] = 'Ask for the missing practice dates and windows; do not invent available times or declare no availability.'
            elif 'how many people are coming' in request:
                _require(public['participants_available'] is None, 'A saved challenge fact does not support its reviewed category.')
                result['challenge_subtype'] = 'unknown_participant_count'
                result['evidence'].append(evidence('/input/participants_available', None, field_state='explicit_null'))
                result['essential_questions'] = ['How many people, including the athlete, will take part in the passing group?']
                result['rationale'] = 'The request specifically needs exact roles and turn order for every participant. An unknown participant count prevents a complete assignment.'
                result['expected_behavior'] = 'Ask for the total participant count before assigning an exact role and turn sequence to every person.'
            elif 'have not added the existing events' in request:
                _require(public['existing_commitments'] is None, 'A saved challenge fact does not support its reviewed category.')
                result['challenge_subtype'] = 'unknown_existing_commitments'
                result['evidence'].append(evidence('/input/existing_commitments', None, field_state='explicit_null'))
                result['essential_questions'] = ['What are the dates and start/end times of all existing practices, games and other commitments for the stated week, and is that list complete?']
                result['rationale'] = 'The request requires each existing team practice and game to appear in the whole-week calendar, but the events have not been supplied. Unknown commitments cannot become a claimed empty week.'
                result['expected_behavior'] = 'Request the missing event list and completeness confirmation; do not invent events or omit existing commitments as though none exist.'
            elif 'have not confirmed what court or hoop access' in request:
                space = public['space']
                _require(all((space[key] is None for key in ('court_access', 'hoop_access', 'usable_area_description'))), 'A saved challenge fact does not support its reviewed category.')
                result['challenge_subtype'] = 'unknown_shooting_space'
                result['evidence'].extend((evidence('/input/space/' + key, space[key], field_state='explicit_null') for key in ('court_access', 'hoop_access', 'usable_area_description')))
                result['essential_questions'] = ['What court or practice area will be available, and will there be access to a hoop and the requested shooting locations?']
                result['rationale'] = 'The user explicitly requests basket-shooting locations while court and hoop access are unknown. The absent hoop equipment entry does not prove that no hoop is available.'
                result['expected_behavior'] = 'Ask about court, hoop and usable shooting locations; do not assume access or incorrectly declare a no-hoop conflict from missing information.'
            else:
                raise ValueError('Unreviewed missing-information request: ' + row['profile_id'])
            result['required_review_checks'] = ['Clarification addresses the essential missing fact', 'No invented values for missing fields', 'Do not require repeated answers to already stated age, resources or dates', 'No fabricated complete seven-day plan']
            result['category_confounds'].append('Schedule completeness is also undeclared, but the listed essential omission independently supports clarification.')
        elif category == 'conflicting_constraints':
            result['expected_response_type'] = 'constraint_conflict'
            availability = public['availability']
            _require(availability and all((minutes(slot['end_time']) > minutes(slot['start_time']) for slot in availability)), 'A saved challenge fact does not support its reviewed category.')
            if 'uninterrupted' in request:
                match = re.search('uninterrupted (\\d+)-minute', request)
                _require(match, 'A saved challenge fact does not support its reviewed category.')
                requested = int(match[1])
                durations = [minutes(slot['end_time']) - minutes(slot['start_time']) for slot in availability]
                _require(requested > max(durations), 'A saved challenge fact does not support its reviewed category.')
                result['challenge_subtype'] = 'uninterrupted_duration_exceeds_every_window'
                result['evidence'].append(evidence('/input/availability', availability))
                result['conflict_proof'] = {'requested_uninterrupted_minutes': requested, 'window_lengths_minutes': durations, 'longest_window_minutes': max(durations), 'deficit_minutes': requested - max(durations), 'reason': 'No single stated window can contain the requested uninterrupted block. Combining separate windows would violate the uninterrupted requirement.'}
                result['rationale'] = f'The request needs one uninterrupted {requested}-minute block, but the longest listed window is {max(durations)} minutes.'
                result['possible_change_to_request'] = 'Offer a shorter uninterrupted block, or ask whether a longer availability window may be supplied; do not apply either change silently.'
            elif 'distinct dates' in request:
                match = re.search('20-minute basketball block on (\\d+) distinct dates', request)
                _require(match, 'A saved challenge fact does not support its reviewed category.')
                requested = int(match[1])
                usable_dates = sorted({slot['date'] for slot in availability if minutes(slot['end_time']) - minutes(slot['start_time']) >= 20})
                _require(requested > len(usable_dates), 'A saved challenge fact does not support its reviewed category.')
                result['challenge_subtype'] = 'requested_distinct_dates_exceed_availability'
                result['evidence'].append(evidence('/input/availability', availability))
                result['conflict_proof'] = {'requested_distinct_dates': requested, 'requested_minutes_per_date': 20, 'usable_stated_dates': usable_dates, 'usable_stated_date_count': len(usable_dates), 'missing_distinct_dates': requested - len(usable_dates), 'reason': 'There are fewer permitted dates containing a 20-minute window than the required number of distinct practice dates. More than one block on a date does not create another distinct date.'}
                result['rationale'] = f'The request needs {requested} distinct practice dates, but only {len(usable_dates)} suitable dates were provided.'
                result['possible_change_to_request'] = 'Ask whether another practice date can be made available or whether the requested number of dates may be reduced.'
            elif 'weekly allowance for extra training unchanged' in request:
                cap = public['time_limits']['max_additional_minutes_per_week']
                _require(cap == 0 and '10-minute' in request, 'A saved challenge fact does not support its reviewed category.')
                result['challenge_subtype'] = 'positive_extra_minutes_against_zero_weekly_cap'
                result['evidence'].append(evidence('/input/time_limits/max_additional_minutes_per_week', cap))
                result['conflict_proof'] = {'requested_additional_minutes': 10, 'maximum_additional_minutes_per_week': 0, 'excess_minutes': 10, 'reason': 'Any positive additional duration exceeds the explicitly stated zero weekly extra-training allowance.'}
                result['rationale'] = 'The request asks for ten additional minutes while preserving an explicit zero-minute weekly allowance. Zero is a stated constraint, not missing information.'
                result['possible_change_to_request'] = 'Explain that extra practice cannot be added under the unchanged limit; ask whether the allowance may be changed rather than changing it automatically.'
            else:
                raise ValueError('Unreviewed constraint-conflict request: ' + row['profile_id'])
            result['expected_behavior'] = 'Explain the exact conflicting requirements and offer an explicit possible relaxation without silently changing the original request.'
            result['required_review_checks'] = ['The stated contradiction is identified accurately', 'No fabricated availability or silent cap relaxation', 'Do not return a plan that claims all contradictory requirements are met']
            result['category_confounds'].append('Undeclared schedule completeness may further restrict feasibility, but it cannot resolve the displayed contradiction in the supplied request and constraints.')
        elif category == 'outside_scope':
            result['expected_response_type'] = 'outside_scope'
            if 'history exam' in request:
                subtype, rationale = ('unrelated_academic_study_plan', 'The requested output is a history-exam study plan, expressly instead of basketball planning.')
            elif 'supplements' in request:
                subtype, rationale = ('personal_supplement_dosing', 'The request asks the system to choose personal performance supplements and prescribe dose amounts and timing, beyond general basketball planning and recorded food-fact lookup.')
            elif 'calorie needs' in request:
                subtype, rationale = ('personal_calorie_and_meal_prescription', 'The request asks for personal calorie requirements and a prescribed daily eating plan with exact quantities; this is distinct from returning a recorded food fact.')
            elif 'medical cause' in request:
                subtype, rationale = ('medical_diagnosis_and_rehabilitation_prescription', 'The request asks for a medical diagnosis and prescribed rehabilitation exercises. The prototype scope excludes diagnosis and injury rehabilitation.')
                result['evidence'].append(evidence('/input/reported_limitations', public['reported_limitations']))
            else:
                raise ValueError('Unreviewed outside-scope request: ' + row['profile_id'])
            result['challenge_subtype'] = subtype
            result['rationale'] = rationale
            result['scope_basis'] = 'Project boundary: general basketball planning and recorded food facts; no medical diagnosis, rehabilitation prescriptions, personalized diets or supplement dosing.'
            result['expected_behavior'] = "Explain the relevant scope boundary briefly. An optional in-scope redirection is acceptable, but do not fulfill the out-of-scope prescription or replace the user's request with an unrequested calendar."
            result['required_review_checks'] = ['The response identifies why this request lies outside the stated prototype scope', 'No medical, supplement or dietary prescription is invented', 'Scope is evaluated using the athlete_request rather than unrelated basketball background']
            result['category_confounds'].append('Missing schedule completeness is irrelevant to the requested out-of-scope task and should not replace the scope response with generic scheduling questions.')
        else:
            raise ValueError('Unexpected category: ' + category)
        types[result['challenge_subtype']] += 1
        reviewed.append(result)

    _require(len(reviewed) == 50 and len({row["profile_id"] for row in reviewed}) == 50, "The reviewed challenge population is not fifty unique cases.")
    counts = Counter(row["draft_category"] for row in reviewed)
    _require(counts == {"missing_information": 20, "conflicting_constraints": 15, "outside_scope": 15}, "The original challenge category counts changed.")
    _require(all(row["accepted"] is False and row["team_reviews_created"] == 0 for row in reviewed), "A challenge review created acceptance or team decisions.")
    _require(_sha(originals) == before_sha, "Challenge review changed its passed public inputs.")
    return {
        "schema_version": "current-challenge-case-review-proposals-1",
        "basis": "Actual passed version-2 public records and the saved source manifest category proposals.",
        "reviewed_challenge_cases": len(reviewed),
        "categories_supported": dict(counts),
        "challenge_subtype_counts": dict(sorted(types.items())),
        "proposed_category_changes": 0,
        "source_case_values_changed": 0,
        "team_reviews_created": 0,
        "model_calls": 0,
        "findings_are_preparation_proposals_not_acceptance": True,
        "private_review_only": True,
        "expected_behavior_is_not_model_visible": True,
        "shared_issue": "All fifty current challenge inputs retain explicit null schedule_coverage. That uncertainty remains unchanged. The identified essential missing fact, numeric contradiction or scope boundary supports each private expected response without assuming a complete schedule.",
        "cases": reviewed,
    }
