"""We keep missing jobs and failed assessments visible in the paired ledger."""

from copy import deepcopy

import pytest

from champion_athletic_map import common_response_preparation as prep


@pytest.fixture
def freeze():
    annotations, jobs = [], []
    for category, count in prep.CATEGORIES.items():
        for number in range(count):
            pid = "software:" + category + ":" + str(number)
            annotations.append({"profile_id": pid, "family_id": "family:" + pid,
                                "case_category": category})
            for version in range(1, 5):
                jobs.append({"job_id": pid + ":v" + str(version), "profile_id": pid,
                    "planner_version": version, "public_record_sha256": "0" * 64})
    return {"annotations": annotations, "jobs": jobs}


def assessment(row, outcome, **changes):
    result = {"assessment_execution": "completed", "designated_outcome_sha256": prep.sha(prep.compact(outcome)),
        "public_record_sha256": row["public_record_sha256"],
        "final_metrics": {"applicable_category": row["case_category"],
            "automated_feasible_plan_success": False if row["case_category"] == "feasible" else None,
            "category_response_success": False, "strict_format_valid": False,
            "designated_workflow_completed": False}}
    result.update(changes)
    return result


def test_all_unstarted_jobs_remain_in_fixed_denominators(freeze):
    rows = prep.pending_ledger(freeze)
    counts = prep.ledger_counts(rows)
    assert len(rows) == 800
    for result in counts.values():
        assert result["feasible_plan_denominator"] == result["feasible_incomplete"] == 150
        assert result["all_jobs_incomplete"] == 200
        assert result["feasible_failures"] == result["feasible_successes"] == 0


def test_external_checker_error_remains_incomplete(freeze):
    row = prep.pending_ledger(freeze)[0]
    updated = prep.record_assessment(row, {"completion_valid": True},
        {"assessment_execution": "error", "error": "Checker failed."})
    assert updated["metric_state"] == "incomplete"
    assert updated["execution_state"] == "terminal"
    assert updated["automated_feasible_plan_success"] is None


def test_terminal_model_failure_is_retained_as_assessed_failure(freeze):
    row = prep.pending_ledger(freeze)[0]
    outcome = {"completion_valid": False, "response": None}
    updated = prep.record_assessment(row, outcome, assessment(row, outcome))
    assert updated["metric_state"] == "assessed"
    assert updated["automated_feasible_plan_success"] is False
    assert row["execution_state"] == "not_started"


def test_external_assessment_retry_preserves_error_and_designated_outcome(freeze):
    row = prep.pending_ledger(freeze)[0]
    outcome = {"completion_valid": False}
    error = {"assessment_execution": "error", "error": "Interrupted checker."}
    interrupted = prep.record_assessment(row, outcome, error)
    retried = prep.record_assessment(interrupted, outcome, assessment(row, outcome))
    assert retried["metric_state"] == "assessed"
    assert retried["assessment_history"][0]["assessment_sha256"] == prep.sha(prep.compact(error))
    assert retried["assessment_history"][0]["error"] == "Interrupted checker."
    with pytest.raises(ValueError, match="already exists"):
        prep.record_assessment(interrupted, {"completion_valid": True}, assessment(row, outcome))


def test_assessment_of_another_saved_reply_is_rejected(freeze):
    row = prep.pending_ledger(freeze)[0]
    outcome = {"completion_valid": False}
    other = assessment(row, {"completion_valid": True})
    with pytest.raises(ValueError, match="different saved outcome"):
        prep.record_assessment(row, outcome, other)


def test_earlier_draft_cannot_replace_designated_result(freeze):
    row = prep.pending_ledger(freeze)[0]
    designated = {"completion_valid": False}
    saved_assessment = assessment(row, designated)
    updated = prep.record_assessment(row, designated, saved_assessment)
    assert prep.record_assessment(updated, designated, saved_assessment) == updated
    with pytest.raises(ValueError, match="already exists"):
        prep.record_assessment(updated, {"completion_valid": True}, saved_assessment)


def test_stale_public_case_assessment_cannot_be_joined(freeze):
    row = prep.pending_ledger(freeze)[0]
    outcome = {"completion_valid": False}
    with pytest.raises(ValueError, match="different public case"):
        prep.record_assessment(row, outcome, assessment(row, outcome, public_record_sha256="1" * 64))


def test_challenge_response_does_not_enter_feasible_primary(freeze):
    row = next(row for row in prep.pending_ledger(freeze) if row["case_category"] == "outside_scope")
    outcome = {"completion_valid": True}
    report = assessment(row, outcome)
    report["final_metrics"].update(category_response_success=True, strict_format_valid=True,
                                  designated_workflow_completed=True)
    updated = prep.record_assessment(row, outcome, report)
    assert updated["automated_feasible_plan_success"] is None
    assert updated["category_response_success"] is True


def test_dropped_failure_cannot_reduce_comparison_denominator(freeze):
    rows = prep.pending_ledger(freeze)
    with pytest.raises(ValueError, match="800 distinct"):
        prep.ledger_counts(rows[1:])


def test_duplicate_job_cannot_replace_a_missing_pair(freeze):
    rows = prep.pending_ledger(freeze)
    rows[-1] = deepcopy(rows[0])
    with pytest.raises(ValueError, match="800 distinct"):
        prep.ledger_counts(rows)
