"""We select and mask the planned team-review sample without entering ratings."""

from copy import deepcopy
from collections import Counter
import json
import pytest
from champion_athletic_map import final_team_review_preparation as review


@pytest.fixture
def config():
    return {"planned_review_sample": {"profiles": 40, "profiles_per_age": 8, "ages": list(range(13, 18)),
        "per_age_categories": {"feasible": 5, "missing_information": 1, "conflicting_constraints": 1, "outside_scope": 1},
        "independent_reviewers_per_response": 2, "planner_versions": 4, "initial_sampling_seed": 42},
        "dimensions": [{"id": identifier, "name": identifier, "anchors": ["Does not meet", "Partly meets", "Meets"]}
            for identifier in review.DIMENSIONS], "score_values": [0, 1, 2], "combined_quality_score": None,
        "new_passing_threshold": None}


@pytest.fixture
def roster():
    records, annotations, jobs = [], [], []
    counts = {"feasible": 30, "missing_information": 4, "conflicting_constraints": 3, "outside_scope": 3}
    for age in range(13, 18):
        for category, count in counts.items():
            for i in range(count):
                pid = "software:" + str(age) + ":" + category + ":" + str(i)
                record = {"profile_id": pid, "schema_version": "software-fixture",
                    "input": {"age": age, "athlete_request": "Review the fictional basketball request."}}
                records.append(record)
                annotations.append({"profile_id": pid, "case_category": category, "family_id": "family:" + pid,
                    "case_authoring_accepted": True, "public_record_sha256": review.sha(review.packed(record))})
                for version in range(1, 5):
                    jobs.append({"job_id": pid + ":v" + str(version), "profile_id": pid, "planner_version": version,
                        "execution_state": "not_started", "designated_final_outcome": None})
    return records, annotations, jobs


def prepare(roster, config):
    return review.prepare_components(*roster, config, case_freeze_id="software-case-freeze",
        reference_access=[{"label": "Adopted reference examples", "path": "neutral/reference.json", "sha256": "0" * 64}])


def rows(result, filename):
    return [json.loads(line) for line in result["files"][filename].splitlines()]


def test_sample_has_fixed_age_and_category_composition(roster, config):
    result = prepare(roster, config)
    sample = rows(result, "private_review_sample.jsonl")
    counts = Counter((row["age"], row["case_category"]) for row in sample)
    assert len(sample) == len({row["profile_id"] for row in sample}) == 40
    assert counts == {(age, category): 5 if category == "feasible" else 1
        for age in range(13, 18) for category in review.CATEGORIES}


def test_sample_is_deterministic_under_input_order_changes(roster, config):
    original = prepare(roster, config)
    reversed_roster = tuple(list(reversed(value)) for value in roster)
    assert prepare(reversed_roster, config) == original


def test_all_four_outcomes_are_included_once(roster, config):
    key = rows(prepare(roster, config), "private_response_key.jsonl")
    assert len(key) == len({row["response_id"] for row in key}) == 160
    by_profile = {}
    for row in key:
        by_profile.setdefault(row["profile_id"], set()).add(row["planner_version"])
    assert len(by_profile) == 40
    assert all(versions == {1, 2, 3, 4} for versions in by_profile.values())


def test_public_forms_exclude_private_keys_and_workflow_metadata(roster, config):
    result = prepare(roster, config)
    forms = rows(result, "review_forms_pending.jsonl")
    for form in forms:
        assert set(form) == {"response_id", "athlete_input", "response_state", "response_text", "response_citations"}
        assert form["response_text"] is None and form["response_citations"] is None
        assert form["response_state"] == "pending_final_outcome"
    assert not any("profile_id" in form or "planner_version" in form or "case_category" in form for form in forms)


def test_rating_templates_do_not_fabricate_scores_or_actual_reviewers(roster, config):
    result = prepare(roster, config)
    templates = rows(result, "rating_templates_pending.jsonl")
    assert len(templates) == 1600
    assert all(row["rating_status"] == "missing" and row["score"] is None and row["reviewer_id"] is None
        and row["template_only"] is True for row in templates)
    assignments = json.loads(result["files"]["private_reviewer_assignments.json"])
    assert len(assignments) == 2
    assert all(row["assigned_reviewer_id"] is None and row["assigned_reviewer_name"] is None
        and row["independent_reviewer_verified"] is False and row["calibration_state"] == "not_completed"
        and row["initial_ratings_locked"] is False for row in assignments)
    assert result["summary"]["actual_response_ratings"] == result["summary"]["actual_assigned_reviewers"] == 0


def test_both_slots_receive_each_response_once_in_masked_order(roster, config):
    result = prepare(roster, config)
    assignments = json.loads(result["files"]["private_reviewer_assignments.json"])
    ids = {row["response_id"] for row in rows(result, "review_forms_pending.jsonl")}
    for slot in assignments:
        assert len(slot["presentation_order"]) == len(set(slot["presentation_order"])) == 160
        assert set(slot["presentation_order"]) == ids
    assert assignments[0]["presentation_order"] != assignments[1]["presentation_order"]


def test_started_final_jobs_cannot_be_used_to_preselect_sample(roster, config):
    changed = deepcopy(roster)
    changed[2][0]["execution_state"] = "terminal"
    with pytest.raises(ValueError, match="before final outputs"):
        prepare(changed, config)


def test_stale_case_annotation_is_rejected(roster, config):
    changed = deepcopy(roster)
    changed[1][0]["public_record_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="exact accepted authoring annotation"):
        prepare(changed, config)


def test_missing_workflow_pair_is_rejected(roster, config):
    changed = deepcopy(roster)
    changed[2][-1] = deepcopy(changed[2][0])
    with pytest.raises(ValueError, match="complete paired final job roster"):
        prepare(changed, config)


def test_new_rating_threshold_is_rejected(roster, config):
    config["new_passing_threshold"] = 7
    with pytest.raises(ValueError, match="scale or threshold"):
        prepare(roster, config)


def test_reference_access_rejects_private_scoring_fields(roster, config):
    with pytest.raises(ValueError, match="unexpected field"):
        review.prepare_components(*roster, config, case_freeze_id="software-freeze",
            reference_access=[{"label": "Private answer", "expected_response": {"answer": 1}}])


def test_source_rubric_anchors_are_retained_and_team_title_used(roster, config):
    config["dimensions"][0]["anchors"] = ["Anchor zero", "Anchor one", "Anchor two"]
    result = prepare(roster, config)
    text = result["files"]["review_rubric.md"].decode("utf-8")
    assert text.startswith("# Team response-review rubric")
    assert "Anchor zero" in text and "Anchor one" in text and "Anchor two" in text
    assert "Human review" not in text


def test_case_approval_does_not_waive_response_ratings(roster, config):
    result = prepare(roster, config)
    assert result["definition"]["case_approval_waives_response_review"] is False
    assert result["definition"]["response_ratings_do_not_change_the_frozen_automated_primary_definition"] is True
    assert result["summary"]["team_response_review_ready_to_rate"] is False
