"""Check independently specified denominators and incomplete-assessment behavior."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.requirement("30.10.result_accounting")
FIXTURE_VERSION = "step30-accounting-fixtures-1"


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


policy = load("step30_scoring_policy", "artifacts/evaluation/planner_assessment_9bc2c716c90475ff/planner_assessment_policy.py")
retrieval = load("step30_retrieval_accounting", "artifacts/retrieval/query_runtime/query_f6db9aad37d7a9b9/retrieval_metrics.py")
evidence = load("step30_evidence_accounting", "artifacts/evaluation/evidence_accounting_c546a28e0ec3a34b/evidence_accounting.py")


OBLIGATIONS = [{"parent_id": "duration", "requirement": "required"}]
RESPONSE = {key: True for key in ("designated_response_present", "parse_valid", "required_plan_present",
                                "plan_complete", "required_activity_content_present")}


def parent(result="met", requirement="required", identifier="duration"):
    return policy.aggregate_parent_check(identifier, requirement, ["session"], [{"instance_id": "session", "result": result}])


def test_four_feasible_cases_include_timeout_and_required_unknown_in_denominator():
    cases = [
        policy.feasible_case_disposition("returned", RESPONSE, OBLIGATIONS, [parent()], True),
        policy.feasible_case_disposition("returned", RESPONSE, OBLIGATIONS, [parent()], True),
        policy.feasible_case_disposition("timeout", None, OBLIGATIONS, [], True),
        policy.feasible_case_disposition("returned", RESPONSE, OBLIGATIONS, [parent("unknown")], True),
    ]
    assert [case["success"] for case in cases] == [True, True, False, False]
    assert policy.guarded_ratio(sum(case["success"] is True for case in cases), len(cases)) == 0.5
    assert all(case["scoring_complete"] for case in cases)


@pytest.mark.parametrize("response, expected", [
    ({**RESPONSE, "required_plan_present": False}, "non_success"),
    ({**RESPONSE, "required_plan_present": None}, "assessment_incomplete"),
    ({**RESPONSE, "parse_valid": False}, "non_success"),
])
def test_refusal_missing_plan_or_unavailable_assessment_never_pass(response, expected):
    answer = policy.feasible_case_disposition("returned", response, OBLIGATIONS, [parent()], True)
    assert answer["disposition"] == expected and answer["success"] is not True


def test_missing_check_rows_empty_obligations_and_unavailable_prerequisites_cannot_pass():
    missing = policy.feasible_case_disposition("returned", RESPONSE, OBLIGATIONS, [], True)
    assert missing["disposition"] == "assessment_incomplete" and missing["success"] is None
    assert policy.feasible_case_disposition("returned", RESPONSE, [], [], True)["disposition"] == "not_ready"
    assert policy.feasible_case_disposition("returned", RESPONSE, OBLIGATIONS, [parent()], False)["success"] is None


def test_internal_acceptance_cannot_override_a_conclusive_violation():
    answer = policy.feasible_case_disposition("returned", {**RESPONSE, "internally_accepted": True},
                                              OBLIGATIONS, [parent("violated")], True)
    assert answer["success"] is False and answer["reasons"] == ["required_check_not_met"]


def test_advisory_unknown_remains_visible_without_becoming_a_required_failure():
    obligations = [*OBLIGATIONS, {"parent_id": "advice", "requirement": "advisory"}]
    answer = policy.feasible_case_disposition("returned", RESPONSE, obligations,
        [parent(), parent("unknown", "advisory", "advice")], True)
    assert answer["success"] is True
    assert answer["reasons"] == ["advisory_findings_reported"]
    assert answer["coverage"]["advisory"]["counts"]["unknown"] == 1


def test_no_instances_requires_non_applicability_evidence_and_never_creates_a_vacuous_pass():
    empty = policy.aggregate_parent_check("rest", "required", [], [])
    assert empty["assessment_complete"] is False and empty["result"] is None
    explained = policy.aggregate_parent_check("rest", "required", [], [],
        {"reason": "Authored rule excludes this population.", "evidence_ref": "fixture:scope"})
    assert explained["assessment_complete"] is True and explained["result"] == "not_applicable"


def test_checker_error_keeps_known_violation_but_marks_coverage_incomplete():
    result = policy.aggregate_parent_check("duration", "required", ["one", "two"], [
        {"instance_id": "one", "result": "violated"},
        {"instance_id": "two", "result": None, "checker_error": "Authored failure"}])
    assert result["result"] == "violated" and result["assessment_complete"] is False
    answer = policy.feasible_case_disposition("returned", RESPONSE, OBLIGATIONS, [result], True)
    assert answer["success"] is None and answer["scoring_complete"] is False


def judgment(identifier="q1", relevant=None, support="supported"):
    units = ["a", "b"] if relevant is None else relevant
    return {"query_id": identifier, "split": "development",
        "category": "drill_and_resource" if support == "supported" else "unsupported_by_identified_corpus",
        "judgment_status": "final", "support_status": support, "relevant_unit_ids": units,
        "complete_evidence_sets": [["a", "b"]] if support == "supported" else []}


CORPUS = ["a", "b", "c", "d"]


def test_retrieved_relevance_and_complete_evidence_are_different_measures():
    result = retrieval.score_query(judgment(), {"status": "completed", "ranked_unit_ids": ["c", "a"]}, CORPUS)
    assert result["recall_at_5"] == 0.5
    assert result["reciprocal_rank_at_5"] == 0.5
    assert result["complete_evidence_set_covered_at_5"] is False
    assert result["ranking_establishes_answerability_or_abstention_accuracy"] is False


def test_unsupported_empty_relevance_is_not_assigned_zero_or_perfect_recall():
    result = retrieval.score_query(judgment(relevant=[], support="unsupported"),
        {"status": "completed", "ranked_unit_ids": ["a"]}, CORPUS)
    assert result["recall_at_5"] is None
    assert result["complete_evidence_set_covered_at_5"] is None


def test_failed_answerable_retrieval_stays_in_selection_population():
    rows = [judgment("q1"), judgment("q2")]
    result = retrieval.aggregate_route(rows, {"q1": {"status": "completed", "ranked_unit_ids": ["a", "b"]},
        "q2": {"status": "failed", "ranked_unit_ids": []}}, CORPUS)
    assert result["population_queries"] == result["ranking_selection_denominator"] == 2
    assert result["ranking_scored_denominator"] == 1 and result["failed_outcomes"] == 1
    assert result["selection_eligible"] is False


def test_completed_empty_retrieval_is_zero_but_failed_retrieval_is_unavailable():
    empty = retrieval.score_query(judgment(), {"status": "completed", "ranked_unit_ids": []}, CORPUS)
    failed = retrieval.score_query(judgment(), {"status": "failed", "ranked_unit_ids": []}, CORPUS)
    assert empty["recall_at_5"] == empty["reciprocal_rank_at_5"] == 0
    assert failed["recall_at_5"] is None


def test_duplicate_retrieval_results_and_unaligned_profile_ids_are_rejected():
    with pytest.raises(ValueError, match="invalid_ranked_units"):
        retrieval.score_query(judgment(), {"status": "completed", "ranked_unit_ids": ["a", "a"]}, CORPUS)
    with pytest.raises(ValueError, match="unaligned"):
        retrieval.aggregate_route([judgment()], {"wrong-profile": {"status": "completed", "ranked_unit_ids": []}}, CORPUS)


def assessment(key="claim_id", identifier="claim", result="supported", state="completed"):
    return {key: identifier, "assessment_status": state, "result": result if state == "completed" else None,
            "note": "Authored independent assessment.", "basis_refs": ["fixture:source"] if state == "completed" else [],
            "error_code": "authored_error" if state == "error" else None}


def test_resolved_citation_does_not_establish_claim_support():
    resolved = evidence.summarize_reference_ids(["source", "source"],
        [assessment("reference_id", "source", "resolved")], True)
    claims = [{"claim_id": "claim", "has_citation": True, "source_dependent": True}]
    unsupported = evidence.summarize_claim_support(claims, [assessment(result="contradicted")], True)
    assert resolved["ratio"] == 1 and resolved["duplicate_occurrences"] == 1
    assert unsupported["all_claims"]["ratio"] == 0


def test_missing_evidence_assessment_stays_unavailable_and_claim_roster_is_preserved():
    claims = [{"claim_id": "claim", "has_citation": False, "source_dependent": True}]
    answer = evidence.summarize_claim_support(claims, [], True)
    assert answer["all_claims"]["expected_items"] == 1
    assert answer["all_claims"]["ratio"] is None
    assert answer["all_claims"]["unavailable_reason"] == "assessment_incomplete"
    assert claims == [{"claim_id": "claim", "has_citation": False, "source_dependent": True}]
