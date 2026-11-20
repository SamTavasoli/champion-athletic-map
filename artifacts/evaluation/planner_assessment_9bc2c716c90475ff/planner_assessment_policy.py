"""Pure assessment aggregation and feasible-case outcome policy."""

from copy import deepcopy

VERSION = "planner-assessment-policy-1"
_RESULTS = ("met", "violated", "unknown", "not_applicable")
_REQUIREMENTS = ("required", "advisory")


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a nonblank string.")
    return value


def _basis(value):
    if not isinstance(value, dict):
        raise ValueError("Non-applicability requires an evidence basis.")
    _text(value.get("reason"))
    _text(value.get("evidence_ref"))
    return deepcopy(value)


def _requirement(value):
    if value not in _REQUIREMENTS:
        raise ValueError("Invalid requirement designation.")
    return value


def _obligations(values):
    if not isinstance(values, list):
        raise ValueError("Expected an obligations list.")
    result = {}
    for row in values:
        if not isinstance(row, dict):
            raise ValueError("Expected an obligation record.")
        key = _text(row.get("parent_id"))
        if key in result:
            raise ValueError("Duplicate obligation identifier.")
        result[key] = _requirement(row.get("requirement"))
    return result


def guarded_ratio(numerator, denominator):
    """Return a bounded count ratio, with no value for an empty denominator."""
    if (type(numerator) is not int or type(denominator) is not int
            or not 0 <= numerator <= denominator):
        raise ValueError("Expected nonnegative integer counts with numerator at most denominator.")
    return None if denominator == 0 else numerator / denominator


def aggregate_parent_check(parent_id, requirement, expected_instance_ids,
                           observations, not_applicable_basis=None):
    """Keep checker completeness separate from known semantic findings."""
    _text(parent_id)
    _requirement(requirement)
    if not isinstance(expected_instance_ids, list) or not isinstance(observations, list):
        raise ValueError("Expected instance and observation lists.")
    expected = [_text(value) for value in expected_instance_ids]
    if len(set(expected)) != len(expected):
        raise ValueError("Duplicate expected instance identifier.")
    basis = _basis(not_applicable_basis) if not_applicable_basis is not None else None
    seen, results, issues = set(), [], []
    for row in observations:
        if not isinstance(row, dict):
            raise ValueError("Expected an observation record.")
        key = _text(row.get("instance_id"))
        if key not in expected or key in seen:
            raise ValueError("Duplicate or unexpected observation identifier.")
        seen.add(key)
        error = row.get("checker_error")
        if error is not None:
            _text(error)
            if row.get("result") is not None:
                raise ValueError("A checker error cannot include a semantic result.")
            if "checker_error" not in issues:
                issues.append("checker_error")
        result = row.get("result")
        if result is None:
            if error is None:
                raise ValueError("An absent semantic result requires a checker error.")
        elif not isinstance(result, str) or result not in _RESULTS:
            raise ValueError("Invalid semantic result.")
        if result == "not_applicable":
            _basis(row.get("not_applicable_basis"))
        results.append(result)
    if set(expected) != seen:
        issues.append("missing_expected_observations")
    if not expected and basis is None:
        issues.append("empty_instances_without_non_applicability_basis")
    complete = not issues
    if "violated" in results:
        result = "violated"
    elif not complete:
        result = None
    elif not expected or all(value == "not_applicable" for value in results):
        result = "not_applicable"
    elif "unknown" in results:
        result = "unknown"
    else:
        result = "met"
    return {"parent_id": parent_id, "requirement": requirement, "result": result,
            "assessment_complete": complete, "issues": issues,
            "expected_instance_ids": deepcopy(expected),
            "observations": deepcopy(observations), "not_applicable_basis": basis}


def summarize_check_coverage(obligations, parents):
    """Count only complete parent assessments; never count instances as parents."""
    expected = _obligations(obligations)
    if not isinstance(parents, list):
        raise ValueError("Expected a parent assessment list.")
    observed = {}
    for row in parents:
        if not isinstance(row, dict):
            raise ValueError("Expected a parent assessment record.")
        key = _text(row.get("parent_id"))
        if key not in expected or key in observed:
            raise ValueError("Duplicate or unexpected parent identifier.")
        if row.get("requirement") != expected[key]:
            raise ValueError("Parent requirement differs from its obligation.")
        complete, result = row.get("assessment_complete"), row.get("result")
        if type(complete) is not bool or (result is not None and result not in _RESULTS):
            raise ValueError("Invalid parent assessment state.")
        if complete and result is None:
            raise ValueError("A complete parent requires a semantic result.")
        if result == "not_applicable":
            if row.get("not_applicable_basis") is not None:
                _basis(row["not_applicable_basis"])
            else:
                instances = row.get("observations")
                if not isinstance(instances, list) or not instances:
                    raise ValueError("Non-applicability requires an evidence basis.")
                for instance in instances:
                    if not isinstance(instance, dict) or instance.get("result") != "not_applicable":
                        raise ValueError("Non-applicability requires an evidence basis.")
                    _basis(instance.get("not_applicable_basis"))
        observed[key] = row
    coverage = {}
    for requirement in _REQUIREMENTS:
        keys = [key for key, value in expected.items() if value == requirement]
        counts = {status: 0 for status in _RESULTS}
        incomplete = 0
        for key in keys:
            row = observed.get(key)
            if row is None or not row["assessment_complete"]:
                incomplete += 1
            else:
                counts[row["result"]] += 1
        numerator = counts["met"] + counts["violated"]
        denominator = numerator + counts["unknown"]
        reason = ("assessment_incomplete" if incomplete else
                  "no_expected_parent_checks" if not keys else
                  "no_applicable_semantic_assessments" if not denominator else None)
        coverage[requirement] = {"expected_parent_checks": len(keys), "counts": counts,
            "assessment_incomplete": incomplete, "numerator": numerator, "denominator": denominator,
            "ratio": None if incomplete else guarded_ratio(numerator, denominator),
            "reason": reason, "status": "available" if reason is None else "unavailable"}
    return coverage


def feasible_case_disposition(job_state, response, obligations, parents, case_scoring_ready):
    """Apply ordered gates without requesting downstream checks after a decisive gate."""
    states = ("not_started", "pending", "returned", "timeout", "failed", "missing_response")
    if job_state not in states or type(case_scoring_ready) is not bool:
        raise ValueError("Invalid execution state or scoring-readiness flag.")

    def outcome(disposition, success, complete, reasons, coverage=None):
        result = {"disposition": disposition, "success": success,
                  "scoring_complete": complete, "reasons": reasons}
        if coverage is not None:
            result["coverage"] = coverage
        return result

    if not case_scoring_ready or obligations is None or obligations == []:
        return outcome("not_ready", None, False, ["case_or_obligation_mask_not_ready"])
    expected = _obligations(obligations)
    if "required" not in expected.values():
        return outcome("not_ready", None, False,
                       ["no_required_obligation_or_applicability_evidence"])
    if job_state in ("not_started", "pending"):
        return outcome("execution_incomplete", None, False, ["execution_not_terminal"])
    if job_state in ("timeout", "failed", "missing_response"):
        return outcome("non_success", False, True, ["terminal_execution_failure"])
    if response is None:
        response = {}
    if not isinstance(response, dict):
        raise ValueError("Expected normalized response assessment fields.")
    gates = ("designated_response_present", "parse_valid", "required_plan_present",
             "plan_complete", "required_activity_content_present")
    for gate in gates:
        value = response.get(gate)
        if value is not None and type(value) is not bool:
            raise ValueError("Expected Boolean or unavailable response assessments.")
        if value is False:
            return outcome("non_success", False, True, [gate + "_false"])
        if value is None:
            return outcome("assessment_incomplete", None, False, [gate + "_unavailable"])
    coverage = summarize_check_coverage(obligations, parents)
    if any(item["assessment_incomplete"] for item in coverage.values()):
        return outcome("assessment_incomplete", None, False, ["expected_assessments_incomplete"], coverage)
    required = coverage["required"]["counts"]
    if required["violated"] or required["unknown"]:
        return outcome("non_success", False, True, ["required_check_not_met"], coverage)
    advisory = coverage["advisory"]["counts"]
    reasons = ["advisory_findings_reported"] if advisory["violated"] or advisory["unknown"] else []
    return outcome("success", True, True, reasons, coverage)
