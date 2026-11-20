"""Propose authored-base family decisions without inventing ancestry or team review."""

from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_bytes().splitlines() if line.strip()]


def build_family_decisions(resolution_root, original_root, *, public_profiles=None,
                           current_family_evidence=None):
    """Return concrete suggestions; an override needs a matching fresh screen for freezing."""
    resolution_root, original_root = Path(resolution_root), Path(original_root)
    manifest_path = resolution_root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    require(manifest["schema_version"] == "final-case-resolution-proposals-1"
            and manifest["accepted_cases"] == 0
            and manifest["final_planner_execution_authorized"] is False,
            "The unaccepted Step 33-3 proposal package is required.")
    for relative, expected in manifest["files"].items():
        path = (resolution_root / relative).resolve()
        require(path.is_relative_to(resolution_root.resolve())
                and digest(path.read_bytes()) == expected,
                "A bound resolution input changed: " + relative)
    source_manifest = json.loads((original_root / "manifest.json").read_bytes())
    require(source_manifest["package_id"] == manifest["source_package_id"],
            "The source case package differs.")
    for relative in ("source_manifest.csv", "source_public_profiles.jsonl", "source_field_lineage.csv",
                     "future_acceptance_requirements.json"):
        require(digest((original_root / relative).read_bytes()) == source_manifest["files"][relative],
                "A bound original family source changed: " + relative)
    with (original_root / "source_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        metadata = {row["profile_id"]: row for row in csv.DictReader(handle)}
    originals = {row["profile_id"]: row for row in jsonl(original_root / "source_public_profiles.jsonl")}
    native_profiles = jsonl(resolution_root / "proposed_public_profiles.jsonl")
    native = json.loads((resolution_root / "family_resolution_proposals.json").read_bytes())
    profiles = native_profiles if public_profiles is None else list(public_profiles)
    public = {row["profile_id"]: row for row in profiles}
    native_public = {row["profile_id"]: row for row in native_profiles}
    require(len(profiles) == len(public) == len(originals) == len(metadata) == 200
            and public.keys() == originals.keys() == metadata.keys() == native_public.keys(),
            "The proposed case population changed size or identities.")
    native_cases = {row["profile_id"]: row for row in native["all_case_family_proposals"]}
    require(len(native_cases) == 200 and all(row["candidate_record_sha256"] == digest(packed(native_public[pid]))
            for pid, row in native_cases.items()), "The native family evidence has stale case hashes.")
    source_verification = native["source_verification"]
    require(source_verification["all_original_200_protected_records_replayed_exactly"] is True
            and source_verification["protected_authoring_arguments_containing_parent_or_counterpart_records"] == 0
            and source_verification["protected_lineage_rows_with_parent_source"] == 0,
            "The exact separate authoring trace is incomplete.")
    require(len(native["retained_prior_pair_proposals"]) == 618
            and len(native["historical_native_development_pair_proposals"]) == 59,
            "Historical pair evidence was not retained.")

    evidence = native if current_family_evidence is None else current_family_evidence
    evidence_cases = {row["profile_id"]: row for row in evidence["all_case_family_proposals"]}
    evidence_matches_current = len(evidence_cases) == 200 and all(
        evidence_cases.get(pid, {}).get("candidate_record_sha256") == digest(packed(record))
        for pid, record in public.items())
    rescreen = evidence.get("fresh_candidate_rescreen") or {}
    pair_screen = evidence.get("fresh_candidate_candidate_screen") or {}
    complete_fresh_screen = evidence_matches_current and rescreen.get("summary", {}).get("screened_pairs") == 24000 \
        and pair_screen.get("comparisons") == 19900
    changed = [pid for pid in public if public[pid] != native_public[pid]]

    legacy = [row for row in native["retained_prior_pair_proposals"] if row["comparison_kind"] == "legacy_source"]
    require(len(legacy) == 9, "The nine retained legacy comparisons changed.")
    legacy_by_case = defaultdict(list)
    legacy_decisions = []
    for row in legacy:
        pid = row["candidate_profile_id"]
        trace = row["candidate_authoring_trace"]
        require(trace["replay_exactly_matches_original"] is True
                and not trace["recorded_parent_source_record_key"]
                and trace["development_or_legacy_record_passed_to_generator"] is False,
                "The legacy relation lacks its separate authoring trace.")
        partial = row["original_flags_preserved"]["partial_source_projection_match"]
        recommendation = {
            "screen_pair_id": row["screen_pair_id"], "profile_id": pid,
            "legacy_record_id": row["other_record_id"],
            "current_proposed_record_sha256": digest(packed(public[pid])),
            "historical_pair_evidence_sha256": digest(packed(row)),
            "historical_projection_match": partial,
            "historical_shared_coarse_facts": row["matching_screen_facts"],
            "historical_different_coarse_facts": row["different_screen_facts"],
            "proposed_operational_family_decision": "retain_separately_authored_base_without_source_family_merge_or_duplicate_exclusion",
            "rationale": "The original base is reproduced exactly from its reserved slot without a legacy record or source-parent argument. "
                "The matching coarse attributes are retained as resemblance evidence, not unique athlete identity or recorded derivation. "
                + ("All six comparable attributes match, so the partial-match warning remains explicit. " if partial else
                   "At least one comparable coarse fact differs. ")
                + "Under the proposed authored-base convention, retain this case separately; do not declare complete legacy nonduplication or statistical independence.",
            "source_equality_diagnostic": "not_assessable_from_incomplete_legacy_source_fields",
            "unknown_complete_legacy_facts_preserved": True,
            "suggested_merge": False, "suggested_duplicate_exclusion": False,
            "operational_recommendation_requires_team_adoption": True,
            "adopted_family_id": None, "team_decision": None,
        }
        legacy_decisions.append(recommendation)
        legacy_by_case[pid].append(recommendation)

    decisions = []
    full_match_cases = set()
    for row in rescreen.get("flagged_pairs", []):
        if row.get("exact_full_input") or row.get("common_input_equal_without_schedule_coverage"):
            full_match_cases.add(row["candidate_profile_id"])
    for row in pair_screen.get("flagged_pairs", []):
        if row.get("exact_full_input"):
            full_match_cases.update((row["left_profile_id"], row["right_profile_id"]))
    for pid in sorted(public):
        case = native_cases[pid]
        trace = case["original_base_family_basis"]
        require(trace["replay_exactly_matches_original"] is True and not trace["recorded_parent_source_record_key"],
                "A case does not have the recorded separate-base origin.")
        hold = pid in full_match_cases
        decisions.append({
            "profile_id": pid,
            "current_proposed_record_sha256": digest(packed(public[pid])),
            "original_record_sha256": digest(packed(originals[pid])),
            "proposed_authored_base_family_id": None if hold else metadata[pid]["proposed_family_id"],
            "proposed_disposition": "hold_for_complete_fact_relationship_decision" if hold else "retain_distinct_authored_base",
            "original_blueprint_slot_id": trace["blueprint_slot_id"],
            "original_authoring_arguments_sha256": trace["arguments_sha256"],
            "family_basis": "One recorded separately authored reserved-slot base; later versions of that base remain in this same case family.",
            "rationale": "Keep authored ancestry separate from shared goals, resource choices and request templates. "
                "The exact generator replay establishes recorded direct inputs, not unrecorded author knowledge or independent real users.",
            "literal_request_design_tag": case["literal_request_design_tag"],
            "request_pattern_design_tag": case["request_pattern_design_tag"],
            "retained_legacy_pair_ids": [row["screen_pair_id"] for row in legacy_by_case[pid]],
            "complete_legacy_source_equality_established": False if legacy_by_case[pid] else None,
            "needs_fresh_current_record_screen": not complete_fresh_screen,
            "proposed_exclusion": False, "independence_established": False,
            "adopted_family_id": None, "team_decision": None,
        })
    family_ids = [row["proposed_authored_base_family_id"] for row in decisions if row["proposed_authored_base_family_id"]]
    require(len(family_ids) == len(set(family_ids)), "The proposed base-family IDs are not unique.")
    working_path = resolution_root / "working/team_decisions.csv"
    working_rows = []
    if working_path.is_file():
        with working_path.open(encoding="utf-8-sig", newline="") as handle:
            working_rows = list(csv.DictReader(handle))
    review_fields = ("prepared_by", "reviewed_by", "team_decision", "relationship_decision")
    review_counts = {key: sum(bool((row.get(key) or "").strip()) for row in working_rows) for key in review_fields}
    patterns = native["shared_design_pattern_groups"]
    require(len(patterns) == 14 and sum(row["case_count"] for row in patterns) == 200,
            "The original shared design-pattern tags changed.")
    return {
        "schema_version": "step33-family-decision-recommendations-1",
        "status": "concrete_recommendations_not_adopted_case_or_sampling_decisions",
        "source_bindings": {"resolution_manifest_sha256": digest(manifest_path.read_bytes()),
            "native_family_evidence_sha256": manifest["files"]["family_resolution_proposals.json"],
            "native_population_sha256": manifest["files"]["proposed_public_profiles.jsonl"],
            "original_source_manifest_sha256": digest((original_root / "manifest.json").read_bytes()),
            "current_family_evidence_sha256": digest(packed(evidence)),
            "working_decision_file_sha256": digest(working_path.read_bytes()) if working_path.is_file() else None},
        "case_family_recommendations": decisions,
        "legacy_relation_recommendations": legacy_decisions,
        "paired_resampling_recommendation": {
            "status": "proposed_for_explicit_adoption_before_final_generation_and_scoring",
            "primary_unit": "accepted_authored_base_case_family",
            "current_proposed_base_families": len(family_ids),
            "pairing": "Draw one common family resample for all four workflows; keep all outcomes belonging to each drawn family, including failures and unknown required evidence.",
            "resamples": 2000, "seed": 42,
            "claims_scope": "Performance on the fixed constructed-case benchmark and sensitivity to its authored-case composition. This does not establish generalization to independent real athletes or all youth basketball requests.",
            "case_category_handling": "Retain the preaccepted case/category definitions and common denominators; do not omit failed outcomes or reinterpret categories from a workflow reply.",
            "shared_pattern_sensitivity": {"recommended_to_predeclare": True,
                "grouping": "original_request_pattern_design_tag", "groups": len(patterns),
                "meaning": "A separate sensitivity grouping for shared task/wording design; it is not athlete ancestry and does not replace the primary family convention.",
                "reporting": "Present separately and label the limited constructed patterns; do not choose whichever interval or grouping gives the preferred outcome."},
            "interval_style_confidence_level_and_metrics": "Use the existing Step35 protocol once explicitly finalized; this family recommendation does not add a new interval method, metric or success threshold.",
            "sampling_performed": False, "test_outcomes_inspected": False,
        },
        "recorded_team_review": {"working_rows": len(working_rows), "nonempty_fields": review_counts,
            "working_file_changed": False, "actual_preparer_or_reviewer_names_created": 0},
        "remaining_before_final_planner_execution": [
            "Resolve and accept the public case choices and complete private witnesses under the adopted case criteria.",
            "Record actual preparation and review by a distinct teammate; delegated resource approval does not supply a nonexistent second case review.",
            "Adopt the authored-base family convention and record the retained partial-legacy diagnostics and shared-recipe limitations.",
            "Bind all accepted changed records to complete current relationship screens before freezing.",
            "Finalize the common scoring protocol, applicability masks, evaluator preparation and final case freeze independently of Version4 internal review.",
        ],
        "summary": {"case_recommendations": len(decisions), "proposed_distinct_authored_base_families": len(family_ids),
            "legacy_retain_separate_recommendations": len(legacy_decisions),
            "legacy_partial_projection_warnings_preserved": sum(row["historical_projection_match"] for row in legacy_decisions),
            "complete_legacy_source_comparisons_available": 0,
            "changed_from_step33_3_public_records": len(changed),
            "current_record_evidence_matches": evidence_matches_current,
            "current_relationship_rescreens_complete": complete_fresh_screen,
            "full_fact_match_cases_held": len(full_match_cases),
            "historical_flags_retained": 618, "proposed_case_exclusions": 0,
            "family_adoptions_created": 0, "team_approvals_created": 0,
            "new_model_calls": 0, "final_planner_execution_authorized": False},
        "privacy": "Family choices, source relationships, categories and review materials remain private evaluation evidence, never planner prompts, retrieval inputs or Version4 internal evaluator inputs.",
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("resolution_root")
    parser.add_argument("original_root")
    parser.add_argument("output")
    args = parser.parse_args()
    result = build_family_decisions(args.resolution_root, args.original_root)
    Path(args.output).write_bytes(packed(result))
    print(json.dumps(result["summary"], indent=2))
