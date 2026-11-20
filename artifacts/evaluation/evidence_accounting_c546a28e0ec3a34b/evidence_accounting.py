"""Account for supplied evidence assessments; no extraction, lookup, or factual checking."""

VERSION = "evidence-accounting-1"
SUPPORT_RESULTS = ("supported", "contradicted", "insufficient_support", "missing_qualification", "unknown")
RESOLUTION_RESULTS = ("resolved", "unresolved", "unknown")
ATTRIBUTION_RESULTS = ("usable", "absent", "unusable", "unknown")
ASSESSMENT_STATES = ("completed", "unrun", "error", "not_recorded")


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonblank text.")
    return value


def _ids(values, unique=True):
    if not isinstance(values, list):
        raise ValueError("Expected an identifier list.")
    for value in values:
        _text(value)
    if unique and len(set(values)) != len(values):
        raise ValueError("Expected unique identifiers.")
    return list(values)


def _claims(values):
    if not isinstance(values, list):
        raise ValueError("Expected a declared claim roster.")
    result = {}
    for row in values:
        if not isinstance(row, dict) or set(row) != {"claim_id", "has_citation", "source_dependent"}:
            raise ValueError("Invalid claim-roster fields.")
        key = _text(row["claim_id"])
        if key in result or type(row["has_citation"]) is not bool or type(row["source_dependent"]) is not bool:
            raise ValueError("Invalid claim-roster values.")
        result[key] = row
    return result


def _assessments(records, roster, key_field, results, require_basis=False):
    if not isinstance(records, list):
        raise ValueError("Expected assessment records.")
    indexed = {}
    fields = {key_field, "assessment_status", "result", "note", "basis_refs", "error_code"}
    for row in records:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("Invalid assessment fields.")
        key = _text(row[key_field])
        if key not in roster or key in indexed:
            raise ValueError("Unexpected or duplicate assessment identifier.")
        status = row["assessment_status"]
        if not isinstance(status, str) or status not in ASSESSMENT_STATES[:3]:
            raise ValueError("Invalid assessment status.")
        basis = _ids(row["basis_refs"])
        if row["note"] is not None:
            _text(row["note"])
        if status == "completed":
            if not isinstance(row["result"], str) or row["result"] not in results or row["error_code"] is not None:
                raise ValueError("Invalid completed assessment.")
            _text(row["note"])
            if require_basis and row["result"] in ("supported", "contradicted", "missing_qualification") and not basis:
                raise ValueError("This support finding requires a recorded evidence basis.")
        else:
            if row["result"] is not None or basis:
                raise ValueError("Unfinished assessments cannot carry a completed result or evidence basis.")
            if status == "error":
                _text(row["error_code"])
            elif row["error_code"] is not None:
                raise ValueError("Unrun assessments cannot carry an execution error.")
        indexed[key] = row
    return indexed


def _summary(roster, records, results, positive, denominator_basis):
    states = dict.fromkeys(ASSESSMENT_STATES, 0)
    counts = dict.fromkeys(results, 0)
    for key in roster:
        row = records.get(key)
        status = "not_recorded" if row is None else row["assessment_status"]
        states[status] += 1
        if status == "completed":
            counts[row["result"]] += 1
    complete = states["completed"] == len(roster)
    denominator = len(roster) if denominator_basis == "expected" else states["completed"]
    unavailable = "assessment_incomplete" if not complete else ("zero_denominator" if not denominator else None)
    return {"expected_items": len(roster), "completed_items": states["completed"],
        "assessment_complete": complete, "assessment_counts": states, "result_counts": counts,
        "numerator": counts[positive], "denominator": denominator,
        "ratio": counts[positive] / denominator if unavailable is None else None,
        "unavailable_reason": unavailable}


def summarize_reference_ids(supplied_reference_ids, assessments, inventory_complete):
    """Count distinct supplied identifiers; existence is independent of claim support."""
    if type(inventory_complete) is not bool:
        raise ValueError("Declare whether reference inventory is complete.")
    occurrences = _ids(supplied_reference_ids, unique=False)
    roster = list(dict.fromkeys(occurrences))
    records = _assessments(assessments, roster, "reference_id", RESOLUTION_RESULTS)
    summary = _summary(roster, records, RESOLUTION_RESULTS, "resolved", "expected")
    if not inventory_complete:
        summary["ratio"] = None
        summary["unavailable_reason"] = "reference_inventory_incomplete"
    return {"version": VERSION, "measure": "supplied_distinct_id_validity",
        "reference_inventory_complete": inventory_complete,
        "measure_complete": inventory_complete and summary["assessment_complete"],
        "supplied_occurrences": len(occurrences), "distinct_supplied_ids": len(roster),
        "duplicate_occurrences": len(occurrences) - len(roster),
        **summary}


def summarize_claim_support(claims, assessments, roster_complete):
    """Summarize supplied support findings by declared citation presence."""
    if type(roster_complete) is not bool:
        raise ValueError("Declare whether claim inventory is complete.")
    roster = _claims(claims)
    records = _assessments(assessments, roster, "claim_id", SUPPORT_RESULTS, require_basis=True)
    output = {"version": VERSION, "measure": "claim_support", "claim_roster_complete": roster_complete}
    for group, keys in (("all_claims", list(roster)),
        ("cited", [key for key, row in roster.items() if row["has_citation"]]),
        ("uncited", [key for key, row in roster.items() if not row["has_citation"]])):
        summary = _summary(keys, records, SUPPORT_RESULTS, "supported", "completed")
        summary["inventory_complete"] = roster_complete
        if not roster_complete:
            summary["ratio"] = None
            summary["unavailable_reason"] = "claim_inventory_incomplete"
        summary["measure_complete"] = roster_complete and summary["assessment_complete"]
        output[group] = summary
    return output


def summarize_attribution(claims, assessments, roster_complete):
    """Use declared source-dependent claims; a citation token alone is not usable attribution."""
    if type(roster_complete) is not bool:
        raise ValueError("Declare whether claim inventory is complete.")
    roster = _claims(claims)
    keys = [key for key, row in roster.items() if row["source_dependent"]]
    records = _assessments(assessments, keys, "claim_id", ATTRIBUTION_RESULTS)
    for key, row in records.items():
        if row["assessment_status"] == "completed":
            if row["result"] in ("usable", "unusable") and not roster[key]["has_citation"]:
                raise ValueError("Usable or unusable attribution requires a supplied citation.")
            if row["result"] == "absent" and roster[key]["has_citation"]:
                raise ValueError("A supplied citation must be assessed separately from absent attribution.")
    summary = _summary(keys, records, ATTRIBUTION_RESULTS, "usable", "completed")
    if not roster_complete:
        summary["ratio"] = None
        summary["unavailable_reason"] = "claim_inventory_incomplete"
    return {"version": VERSION, "measure": "source_dependent_claim_attribution", "claim_roster_complete": roster_complete,
        "source_independent_claims_excluded": len(roster) - len(keys),
        "measure_complete": roster_complete and summary["assessment_complete"], **summary}
