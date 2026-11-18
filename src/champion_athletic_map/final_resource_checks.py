"""Keep source resolution, declared resources and action proofs separate."""

from copy import deepcopy
import hashlib
import json
import re


VERSION = "final-resource-coverage-1"
CHECK_IDS = ("declared_resource_consistency", "resource_requirements_evidence")
STATUSES = {"met", "violated", "unknown", "not_applicable"}


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_source_bindings(contracts, adopted_drills):
    """Require the complete approved source records, never private case examples."""
    if (not isinstance(contracts, dict) or contracts.get("source_bindings_verified") is not True
            or contracts.get("schema_version") != "reviewed-resource-contracts-1"):
        raise ValueError("Verified resource contracts are required.")
    rows = adopted_drills.get("records") if isinstance(adopted_drills, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("The complete approved drill snapshot is required.")
    records = {}
    for row in rows:
        identifier = row.get("catalog_candidate_id") if isinstance(row, dict) else None
        if not isinstance(identifier, str) or not identifier or identifier in records:
            raise ValueError("The approved drill snapshot contains a missing or duplicate identifier.")
        if row.get("approval_decision") != "approved_for_prototype":
            raise ValueError("An unapproved drill appears in the adopted snapshot.")
        records[identifier] = row
    entries = contracts.get("contracts")
    if not isinstance(entries, list) or len(entries) != contracts.get("declared_contract_count"):
        raise ValueError("The resource proof count is inconsistent.")
    seen = set()
    for contract in entries:
        key = contract.get("contract_id") if isinstance(contract, dict) else None
        record = records.get(contract.get("source_catalog_id")) if isinstance(contract, dict) else None
        if (not isinstance(key, str) or not key or key in seen or record is None
                or _digest(record) != contract.get("source_record_sha256")):
            raise ValueError("A resource proof differs from its approved source record.")
        patterns = contract.get("description_patterns")
        if not isinstance(patterns, list) or not patterns:
            raise ValueError("A source proof needs its complete description grammar.")
        for pattern in patterns:
            re.compile(pattern)
        seen.add(key)
    aliases = adopted_drills.get("aliases", {})
    if not isinstance(aliases, dict):
        raise ValueError("The approved source alias map is invalid.")
    return records, aliases


def coverage_spec(contracts, adopted_drills):
    records, _ = validate_source_bindings(contracts, adopted_drills)
    covered = sorted({entry["source_catalog_id"] for entry in contracts["contracts"]})
    return {
        "schema_version": VERSION,
        "approved_source_records": len(records),
        "reviewed_description_contracts": len(contracts["contracts"]),
        "source_records_with_narrow_action_grammar": len(covered),
        "grammar_source_ids": covered,
        "catalog_id_required": False,
        "private_case_examples_used_as_output_templates": False,
        "source_resolution_establishes_claim_support": False,
        "declared_resources_establish_actual_requirements": False,
        "universal_free_text_resource_verification": False,
        "narrative_restrictions_automatically_verified": False,
        "unknown_is_not_a_pass": True,
        "clinical_safety_certified": False,
        "coverage_limits": [
            "Only complete descriptions covered by the reviewed action, setup and role grammar can receive an action-resource proof.",
            "Unrecognized activity descriptions and narrative restrictions require separate review.",
            "An approved source ID alone establishes neither a matching activity nor feasible resource use.",
            "Duration, role competence, supervision, goal fulfillment and clinical suitability are outside these resource proofs.",
        ],
    }


def _resolved_refs(activities, records, aliases, held):
    results = []
    for index, entry in enumerate(activities):
        activity = entry.get("activity", entry) if isinstance(entry, dict) else {}
        refs = activity.get("evidence_refs") if isinstance(activity, dict) else None
        if not isinstance(refs, list):
            continue
        for reference in refs:
            if not isinstance(reference, str):
                continue
            resolved = aliases.get(reference, reference)
            # An alias must resolve to one ID; no guess is made for other shapes.
            if not isinstance(resolved, str):
                resolved = reference
            if resolved in records:
                status = "resolved_to_approved_record"
            elif resolved in held or reference in held:
                status = "resolved_to_held_record"
            elif reference.startswith("JR-"):
                status = "unresolved_catalog_reference"
            else:
                status = "non_catalog_reference_not_resolved_here"
            results.append({"activity_index": index, "reference": reference,
                "resolved_catalog_id": resolved if resolved in records or resolved in held else None,
                "resolution_status": status, "claim_support_assessed": False})
    return results


def _activity_indexes(activities, details):
    """Join by unique IDs when an inherited scope wrapper has reordered rows."""
    original_ids = []
    for entry in activities:
        activity = entry.get("activity", entry) if isinstance(entry, dict) else None
        original_ids.append(activity.get("activity_id") if isinstance(activity, dict) else None)
    complete_ids = (all(isinstance(value, str) and value.strip() for value in original_ids)
        and len(set(original_ids)) == len(original_ids))
    if complete_ids:
        result_ids = [row.get("activity_id") for row in details]
        if len(set(result_ids)) != len(result_ids) or set(result_ids) != set(original_ids):
            raise ValueError("Activity resource evidence does not cover the original activity IDs once each.")
        by_id = {row["activity_id"]: row for row in details}
        details[:] = [by_id[identifier] for identifier in original_ids]
        for index, row in enumerate(details):
            row["original_checker_activity_index"] = row.get("activity_index")
            row["activity_index"] = index
            row["activity_index_basis"] = "unique_activity_id"
        return "unique_activity_id" if activities else "no_activities"
    # A duplicate or missing activity ID cannot establish an instance join. We
    # retain separate findings and known violations without implying an order.
    for row in details:
        row["original_checker_activity_index"] = row.get("activity_index")
        row["activity_index"] = None
        row["activity_index_basis"] = "unresolved_missing_or_duplicate_activity_ids"
        for field in ("declared_status", "requirements_status"):
            if row[field] != "violated":
                row[field] = "unknown"
        row.setdefault("reasons", []).append("Missing or duplicate activity IDs prevent an unambiguous activity-instance join.")
    return "unresolved_missing_or_duplicate_activity_ids"


def assess_resources(public_input, activities, contracts, *, checker, adopted_drills):
    """Apply the same narrow proofs to all versions without a hidden source-ID gate."""
    if not isinstance(public_input, dict) or not isinstance(activities, list):
        raise ValueError("Resource checking needs public input and a list of new activities.")
    records, aliases = validate_source_bindings(contracts, adopted_drills)
    report = deepcopy(checker.assess_resources(public_input, activities, contracts))
    checks, details = report.get("checks"), report.get("per_activity")
    if (not isinstance(checks, list) or {row.get("check_id") for row in checks} != set(CHECK_IDS)
            or len(checks) != len(CHECK_IDS) or not isinstance(details, list)
            or len(details) != len(activities)):
        raise ValueError("The resource checker returned incomplete or duplicate coverage.")
    for row in checks:
        if row.get("status") not in STATUSES or not row.get("reason"):
            raise ValueError("A resource result lacks its status or reason.")
        if not activities:
            row.update(status="not_applicable", reason="No newly prescribed activity needs a resource check; request and calendar checks remain separate.")
    by_contract = {row["contract_id"]: row for row in contracts["contracts"]}
    for detail in details:
        if (detail.get("declared_status") not in STATUSES
                or detail.get("requirements_status") not in STATUSES):
            raise ValueError("An activity resource result is malformed.")
        if detail.get("requirements_status") == "met":
            contract = by_contract.get(detail.get("contract_id"))
            if contract is None or detail.get("source_catalog_id") != contract["source_catalog_id"]:
                raise ValueError("A positive action-resource result has no verified source proof.")
        detail["catalog_id_required"] = False
    index_basis = _activity_indexes(activities, details)
    if index_basis == "unresolved_missing_or_duplicate_activity_ids":
        for check in checks:
            field = "declared_status" if check["check_id"] == "declared_resource_consistency" else "requirements_status"
            states = [row[field] for row in details]
            check["status"] = "violated" if "violated" in states else "unknown"
            check["reason"] += " Activity-instance identity is unresolved."
            check["observed"] = {"activities": len(details), **{
                status: states.count(status) for status in sorted(STATUSES)}}
    source_refs = _resolved_refs(activities, records, aliases, set(contracts.get("held_catalog_ids", [])))
    counts = {}
    for field in ("declared_status", "requirements_status"):
        histogram = {status: sum(row[field] == status for row in details) for status in sorted(STATUSES)}
        denominator = histogram["met"] + histogram["violated"] + histogram["unknown"]
        counts[field] = {**histogram, "assessable_activity_denominator": denominator,
            "determinate_coverage": ((histogram["met"] + histogram["violated"]) / denominator) if denominator else None}
    report.update(schema_version=VERSION, source_reference_resolution=source_refs)
    report["coverage"] = {**report.get("coverage", {}), **coverage_spec(contracts, adopted_drills),
        "activity_instances": len(activities), "activity_status_counts": counts,
        "activity_index_binding": index_basis,
        "approved_references_resolved": sum(row["resolution_status"] == "resolved_to_approved_record" for row in source_refs),
        "source_reference_resolution_is_a_separate_diagnostic": True}
    return report
