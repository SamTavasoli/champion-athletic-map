"""We describe fictional saved outcomes without treating unknown checks as passes."""

from copy import deepcopy

import pytest

from champion_athletic_map import final_results_summary as report


def finding(identifier, status="met", required=True):
    return {"check_id": identifier, "status": status, "required": required,
            "reason": "Fictional recorded software evidence."}


@pytest.fixture
def rows():
    result, sequence = [], 0
    for category, size in report.CATEGORIES.items():
        for index in range(size):
            sequence += 1
            public = {"age": 15, "athlete_request": "Fictional software request.", "goals": ["Improve ball control"]}
            requested_food = category == "feasible" and index < 20
            if requested_food:
                public["food_question"] = 'For the food "Software food", how many grams of protein are recorded for 100 g?'
            feasible = category == "feasible"
            parents = [finding("output_structure"), finding("execution_completion"),
                finding("public_goal_fulfillment", "unknown" if feasible else "not_applicable"),
                finding("declared_resource_consistency", "met" if feasible else "not_applicable"),
                finding("resource_requirements_evidence", "unknown" if feasible else "not_applicable")]
            checks = [finding(name, "met" if requested_food else "not_applicable", name != "food_source_grounding")
                      for name in report.FOOD_IDS]
            for version in range(1, 5):
                metrics = {"strict_format_valid": True, "designated_workflow_completed": True,
                    "automated_declared_checks_pass": not feasible,
                    "automated_feasible_plan_success": False if feasible else None,
                    "category_response_success": not feasible, "applicable_category": category}
                result.append({"job_id": "software-job-" + str(sequence) + "-" + str(version),
                    "profile_id": "software-profile-" + str(sequence), "planner_version": version,
                    "case_category": category, "family_id": "software-family-" + str(sequence),
                    "public_input": deepcopy(public), "response_type": report.KINDS[category],
                    "format_valid": True, "completion_valid": True, "elapsed_seconds": sequence,
                    "final_metrics": metrics, "parent_checks": deepcopy(parents), "checks": deepcopy(checks)})
    return result


def test_complete_paired_roster_retains_fixed_denominators(rows):
    result = report.summarize(rows, cumulative_model_submissions=2500)
    assert result["outcomes"] == 800 and result["cases"] == 200
    for planner in result["planners"].values():
        assert planner["format_valid"] == planner["workflow_completed"] == 200
        assert planner["feasible"]["denominator"] == 150
        assert planner["feasible"]["coded_checks_passed"] == planner["feasible"]["full_verification"] == 0
        assert planner["challenges"]["missing_information"]["handling_checks_passed"] == 20
        assert planner["food"]["question_denominator"] == 20
    assert result["cumulative_model_submissions"] == 2500
    assert result["team_response_ratings"] == "pending" and not result["best_planner_selected"]


def test_unknown_is_separate_from_a_known_violation(rows):
    target = next(row for row in rows if row["planner_version"] == 1)
    next(row for row in target["parent_checks"] if row["check_id"] == "resource_requirements_evidence")["status"] = "violated"
    result = report.summarize(rows)["planners"]["1"]
    states = result["resource_findings_on_feasible_cases"]["resource_requirements_evidence"]
    assert states["unknown"] == 149 and states["violated"] == 1 and states["met"] == 0
    parent = next(row for row in result["feasible"]["required_parent_findings"]
                  if row["check_id"] == "resource_requirements_evidence")
    assert parent["case_denominator"] == parent["cases_with_parent"] == 150


def test_food_uses_explicit_question_cases_not_all_200(rows):
    result = report.summarize(rows)["planners"]["1"]["food"]
    assert result["findings"]["food_answer_completeness"] == {
        "met": 20, "violated": 0, "unknown": 0, "not_applicable": 0}


def test_failed_workflow_is_included_in_terminal_timing(rows):
    row = rows[0]
    row["elapsed_seconds"] = 1000
    row["completion_valid"] = row["final_metrics"]["designated_workflow_completed"] = False
    next(p for p in row["parent_checks"] if p["check_id"] == "execution_completion")["status"] = "violated"
    result = report.summarize(rows)["planners"]["1"]
    assert result["workflow_completed"] == 199
    assert result["timing_all_terminal"]["measured"] == 200
    assert result["timing_all_terminal"]["mean_seconds"] > 100.5
    assert result["timing_coded_check_passes"]["measured"] == 0
    assert result["timing_coded_check_passes"]["median_seconds"] is None


def test_timing_has_explicit_missing_and_nearest_rank_percentile(rows):
    original = report.summarize(rows)["planners"]["1"]["timing_all_terminal"]
    assert original["median_seconds"] == 100.5 and original["p95_seconds"] == 190
    for row in rows:
        row["elapsed_seconds"] = None
    missing = report.summarize(rows)["planners"]["1"]["timing_all_terminal"]
    assert missing["measured"] == 0 and missing["missing"] == 200
    assert missing["mean_seconds"] is missing["median_seconds"] is missing["p95_seconds"] is None


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf")])
def test_invalid_timing_is_not_silently_zero_or_missing(rows, value):
    rows[0]["elapsed_seconds"] = value
    with pytest.raises(ValueError, match="elapsed time"):
        report.summarize(rows)


def test_coverage_is_determinate_fraction_not_pass_fraction():
    result = report.coverage([finding("a"), finding("b", "violated"),
                              finding("c", "unknown"), finding("d", "not_applicable")])
    assert result["determinate_coverage"] == 2 / 3
    assert result["status_counts"]["violated"] == result["status_counts"]["unknown"] == 1
    assert report.coverage([])["determinate_coverage"] is None
    assert report.coverage([finding("x", "not_applicable")])["determinate_coverage"] is None


def test_dropped_or_duplicate_outcome_cannot_reduce_denominator(rows):
    with pytest.raises(ValueError, match="all 800"):
        report.summarize(rows[:-1])
    rows[-1] = deepcopy(rows[0])
    with pytest.raises(ValueError, match="missing or duplicated"):
        report.summarize(rows)


def test_different_public_facts_between_planners_are_rejected(rows):
    rows[1]["public_input"]["goals"] = ["A different goal"]
    with pytest.raises(ValueError, match="different public information"):
        report.summarize(rows)


def test_missing_metric_is_not_counted_as_a_false_result(rows):
    rows[0]["final_metrics"].pop("strict_format_valid")
    with pytest.raises(ValueError, match="absent"):
        report.summarize(rows)


def test_missing_resource_or_food_finding_is_rejected(rows):
    rows[0]["checks"] = []
    with pytest.raises(ValueError, match="food or resource finding"):
        report.summarize(rows)


def test_wrong_clarification_basis_is_not_rescued_by_matching_label(rows):
    target = next(row for row in rows if row["planner_version"] == 1 and row["case_category"] == "missing_information")
    target["final_metrics"]["category_response_success"] = False
    target["final_metrics"]["automated_declared_checks_pass"] = False
    target["parent_checks"].append(finding("response_type_basis", "violated"))
    result = report.summarize(rows)["planners"]["1"]["challenges"]["missing_information"]
    assert result["matching_response_type"] == 20 and result["handling_checks_passed"] == 19


def test_invalid_response_type_shape_remains_descriptive_failure(rows):
    rows[0]["response_type"] = ["not a response type"]
    result = report.summarize(rows)["planners"]["1"]
    assert result["response_type_counts"]["unavailable"] == 1
    assert result["feasible"]["returned_plan_type"] == 149


def test_impossible_positive_result_with_required_unknown_is_rejected(rows):
    rows[0]["final_metrics"]["automated_feasible_plan_success"] = True
    with pytest.raises(ValueError, match="positive category or primary"):
        report.summarize(rows)


def test_rendered_table_labels_measurement_limits(rows):
    text = report.render_comparison(report.summarize(rows))
    assert "| 1 | 200/200 | 200/200 | 0/150 | 0/150 |" in text
    assert "unimplemented automatic goal check" in text and "Team ratings remain pending" in text
