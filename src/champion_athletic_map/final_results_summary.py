"""Describe the frozen saved outcomes without generating or rescoring replies."""

from collections import Counter
import json
from math import ceil, isfinite
from statistics import mean, median

VERSION = "final-saved-results-comparison-1"
CATEGORIES = {"feasible": 150, "missing_information": 20,
              "conflicting_constraints": 15, "outside_scope": 15}
KINDS = {"feasible": "plan", "missing_information": "clarification",
         "conflicting_constraints": "constraint_conflict", "outside_scope": "outside_scope"}
STATES = ("met", "violated", "unknown", "not_applicable")
BOOL_METRICS = ("strict_format_valid", "designated_workflow_completed",
               "automated_declared_checks_pass", "category_response_success")
RESOURCE_IDS = ("declared_resource_consistency", "resource_requirements_evidence")
FOOD_IDS = ("food_answer_completeness", "food_numeric_correctness", "food_source_grounding")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _food_requested(row):
    value = row["public_input"].get("food_question")
    return isinstance(value, str) and bool(value.strip())


def _kind(row):
    value = row.get("response_type")
    return value if isinstance(value, str) and value in KINDS.values() else "unavailable"


def status_counts(rows):
    return {state: sum(row["status"] == state for row in rows) for state in STATES}


def coverage(rows):
    counts = status_counts(rows)
    denominator = counts["met"] + counts["violated"] + counts["unknown"]
    return {"status_counts": counts, "parent_instances": len(rows),
        "applicable_parent_instances": denominator,
        "determinate_coverage": ((counts["met"] + counts["violated"]) / denominator
                                 if denominator else None),
        "unit": "parent-check instances; policy aliases are not counted again",
        "coverage_is_not_a_pass_rate": True}


def timing(rows):
    values = [float(row["elapsed_seconds"]) for row in rows if row["elapsed_seconds"] is not None]
    ordered = sorted(values)
    return {"outcomes": len(rows), "measured": len(values), "missing": len(rows) - len(values),
        "mean_seconds": mean(values) if values else None,
        "median_seconds": median(values) if values else None,
        "p95_seconds": ordered[ceil(.95 * len(ordered)) - 1] if ordered else None,
        "p95_method": "nearest rank: sorted elapsed[ceil(0.95*n)-1]",
        "scope": "All designated terminal workflows, including failures; missing elapsed time is not zero."}


def _check_rows(rows, *, parents):
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("check_id"), str) and row["check_id"]
            and row.get("status") in STATES and isinstance(row.get("reason"), str) and row["reason"],
            "A saved check lacks its identifier, four-state result or reason.")
        if parents:
            require(type(row.get("required")) is bool, "A parent check lacks its required/advisory flag.")
    require(len({row["check_id"] for row in rows}) == len(rows), "A saved finding repeats a check identifier.")


def validate_rows(rows):
    require(isinstance(rows, list) and len(rows) == 800,
            "The comparison requires all 800 designated and externally assessed outcomes.")
    require(len({row.get("job_id") for row in rows}) == 800, "A saved final job is missing or duplicated.")
    require(Counter(row.get("planner_version") for row in rows) == {1: 200, 2: 200, 3: 200, 4: 200},
            "Each of the four planners must retain its fixed 200-case denominator.")
    public_by_id, category_by_id = {}, {}
    for row in rows:
        require(isinstance(row.get("profile_id"), str) and isinstance(row.get("public_input"), dict)
                and row.get("case_category") in CATEGORIES, "A saved outcome lacks its authoritative case binding.")
        pid, public = row["profile_id"], _canonical(row["public_input"])
        require(pid not in public_by_id or public_by_id[pid] == public,
                "The planners received different public information for the same case.")
        require(pid not in category_by_id or category_by_id[pid] == row["case_category"],
                "A case changes reporting category between planners.")
        public_by_id[pid], category_by_id[pid] = public, row["case_category"]
        metrics = row.get("final_metrics")
        require(isinstance(metrics, dict) and all(type(metrics.get(key)) is bool for key in BOOL_METRICS),
                "A final saved metric is absent or is not a Boolean result.")
        require("automated_feasible_plan_success" in metrics
                and metrics.get("applicable_category") == row["case_category"],
                "A saved primary metric or reporting category is missing.")
        primary = metrics["automated_feasible_plan_success"]
        require(type(primary) is bool if row["case_category"] == "feasible" else primary is None,
                "The primary measure must use the fixed feasible-case roster only.")
        require(row.get("format_valid") is metrics["strict_format_valid"]
                and row.get("completion_valid") is metrics["designated_workflow_completed"],
                "A compact outcome differs from its saved common metrics.")
        require(isinstance(row.get("parent_checks"), list) and row["parent_checks"],
                "The saved common parent findings are incomplete.")
        require(isinstance(row.get("checks"), list), "The saved raw findings are unavailable.")
        _check_rows(row["parent_checks"], parents=True)
        _check_rows(row["checks"], parents=False)
        elapsed = row.get("elapsed_seconds")
        require(elapsed is None or type(elapsed) in (int, float) and isfinite(elapsed) and elapsed >= 0,
                "A terminal elapsed time must be finite, nonnegative, or unavailable.")
        if primary is True or metrics["category_response_success"]:
            require(row["response_type"] == KINDS[row["case_category"]]
                and metrics["strict_format_valid"] and metrics["designated_workflow_completed"]
                and all(check["status"] in {"met", "not_applicable"}
                        for check in row["parent_checks"] if check["required"]),
                "A positive category or primary result contradicts its saved required findings.")
    require(len(public_by_id) == 200, "The paired comparison needs 200 distinct profiles.")
    roster = set(public_by_id)
    for version in range(1, 5):
        selected = [row for row in rows if row["planner_version"] == version]
        require({row["profile_id"] for row in selected} == roster,
                "A planner is missing an outcome from the paired case roster.")
        require(Counter(row["case_category"] for row in selected) == CATEGORIES,
                "A planner's fixed category denominators changed.")
        require(sum(_food_requested(row) for row in selected) == 20,
                "The frozen comparison has 20 explicit food questions per planner.")
    return rows


def _find(rows, identifier):
    found = [row for row in rows if row["check_id"] == identifier]
    require(len(found) == 1, "A saved food or resource finding is missing: " + identifier)
    return found[0]


def _top_findings(rows):
    by_check = {}
    for row in rows:
        for finding in row["parent_checks"]:
            if finding["required"]:
                by_check.setdefault(finding["check_id"], []).append(finding)
    values = [{"check_id": key, **status_counts(findings), "case_denominator": len(rows),
        "cases_with_parent": len(findings)} for key, findings in by_check.items()]
    return sorted(values, key=lambda row: (-row["violated"], -row["unknown"], row["check_id"]))


def summarize(rows, *, cumulative_model_submissions=None, manifest_id=None):
    validate_rows(rows)
    require(cumulative_model_submissions is None or type(cumulative_model_submissions) is int
            and 0 <= cumulative_model_submissions <= 2640,
            "The cumulative submission count must come from the verified final journals.")
    planners = {}
    for version in range(1, 5):
        selected = [row for row in rows if row["planner_version"] == version]
        feasible = [row for row in selected if row["case_category"] == "feasible"]
        food = [row for row in selected if _food_requested(row)]
        parents = [finding for row in selected for finding in row["parent_checks"]]
        declared_success = [row for row in feasible if row["final_metrics"]["automated_declared_checks_pass"]]
        challenges = {}
        for category, denominator in CATEGORIES.items():
            if category == "feasible":
                continue
            items = [row for row in selected if row["case_category"] == category]
            challenges[category] = {"denominator": denominator,
                "handling_checks_passed": sum(row["final_metrics"]["category_response_success"] for row in items),
                "matching_response_type": sum(row["response_type"] == KINDS[category] for row in items),
                "matching_label_alone_is_success": False}
        planners[str(version)] = {"case_denominator": 200,
            "format_valid": sum(row["format_valid"] for row in selected),
            "workflow_completed": sum(row["completion_valid"] for row in selected),
            "response_type_counts": dict(sorted(Counter(_kind(row) for row in selected).items())),
            "feasible": {"denominator": 150,
                "returned_plan_type": sum(row["response_type"] == "plan" for row in feasible),
                "completed_valid_plan_responses": sum(row["response_type"] == "plan" and row["format_valid"]
                                                       and row["completion_valid"] for row in feasible),
                "coded_checks_passed": len(declared_success),
                "full_verification": sum(row["final_metrics"]["automated_feasible_plan_success"] for row in feasible),
                "required_parent_findings": _top_findings(feasible)},
            "challenges": challenges, "timing_all_terminal": timing(selected),
            "timing_coded_check_passes": timing(declared_success),
            "food": {"question_denominator": 20, "findings": {
                identifier: status_counts([_find(row["checks"], identifier) for row in food]) for identifier in FOOD_IDS}},
            "resource_findings_on_feasible_cases": {identifier: status_counts([
                _find(row["parent_checks"], identifier) for row in feasible]) for identifier in RESOURCE_IDS},
            "parent_coverage": {"required": coverage([row for row in parents if row["required"]]),
                                "advisory": coverage([row for row in parents if not row["required"]])}}
    return {"schema_version": VERSION, "manifest_id": manifest_id, "cases": 200, "outcomes": 800,
        "cumulative_model_submissions": cumulative_model_submissions,
        "submission_count_scope": "All final generation submissions from the leaf journals; a batch count is not substituted.",
        "planners": planners, "new_model_calls": 0, "new_query_encodings": 0,
        "primary_interpretation": "The frozen full-verification measure is conservative. Automatic skill-goal verification is unimplemented for the explicit feasible-case goals. Its zeros are verification-coverage findings, not proof that every plan is unusable.",
        "coded_measure_interpretation": "Coded-check passes exclude the unimplemented goal parent, but still require the saved coded constraints and resource evidence. Unknown requirements are not passes.",
        "evidence_support_rates": {"source_id_resolution": None, "cited_claim_support": None,
            "source_dependent_claim_attribution": None,
            "reason": "These claim-level measures are not inferred from parent-check status or identifier resolution alone."},
        "team_response_ratings": "pending", "reviewer_agreement_computed": False,
        "paired_intervals_computed": False, "best_planner_selected": False,
        "saved_replies_or_original_assessments_changed": False}


def render_comparison(summary):
    lines = ["| Planner | Format valid | Workflow completed | Coded checks passed | Full verification |",
             "|---|---:|---:|---:|---:|"]
    for version, row in summary["planners"].items():
        feasible = row["feasible"]
        lines.append("| " + version + " | " + str(row["format_valid"]) + "/200 | "
            + str(row["workflow_completed"]) + "/200 | " + str(feasible["coded_checks_passed"])
            + "/150 | " + str(feasible["full_verification"]) + "/150 |")
    return "\n".join(lines) + "\n\nCoded checks and full verification use the 150 feasible cases per planner. " \
        "Full verification is limited by the unimplemented automatic goal check. Team ratings remain pending.\n"
