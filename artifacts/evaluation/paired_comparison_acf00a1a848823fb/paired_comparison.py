"""Pure paired accounting for supplied independent feasible-case assessments."""

VERSION = "paired-feasible-accounting-1"
VERSIONS = ("V1", "V2", "V3", "V4")
CONTRASTS = (("V1", "V2"), ("V2", "V3"), ("V3", "V4"), ("V1", "V4"))
DISPOSITIONS = ("success", "non_success", "not_ready", "execution_incomplete", "assessment_incomplete")


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonblank text.")
    return value


def summarize_paired_feasible_results(profile_roster, outcomes, population_ready):
    """Keep profile denominators fixed and preserve incomplete comparison pairs."""
    if not isinstance(profile_roster, list) or not isinstance(outcomes, list) or type(population_ready) is not bool:
        raise ValueError("Supply a profile roster, outcome list, and explicit population-readiness flag.")
    profiles = {}
    for row in profile_roster:
        if not isinstance(row, dict) or set(row) != {"profile_id", "family_id"}:
            raise ValueError("Invalid profile/family roster fields.")
        profile = _text(row["profile_id"])
        family = _text(row["family_id"])
        if profile in profiles:
            raise ValueError("Duplicate profile identifier.")
        profiles[profile] = family
    profiles = dict(sorted(profiles.items()))
    records = {}
    fields = {"profile_id", "family_id", "version_id", "disposition", "success", "scoring_complete"}
    for row in outcomes:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("Invalid independent-outcome fields.")
        profile = _text(row["profile_id"])
        family = _text(row["family_id"])
        version = row["version_id"]
        if not isinstance(version, str) or version not in VERSIONS or profile not in profiles:
            raise ValueError("Outcome is outside the declared profile/version roster.")
        if family != profiles[profile] or (profile, version) in records:
            raise ValueError("Family mismatch or duplicate profile/version outcome.")
        disposition = row["disposition"]
        if not isinstance(disposition, str) or disposition not in DISPOSITIONS or type(row["scoring_complete"]) is not bool:
            raise ValueError("Invalid independent assessment disposition.")
        if disposition in ("success", "non_success"):
            expected = disposition == "success"
            if row["scoring_complete"] is not True or type(row["success"]) is not bool or row["success"] != expected:
                raise ValueError("Completed outcomes need a consistent Boolean success result.")
        elif row["scoring_complete"] is not False or row["success"] is not None:
            raise ValueError("Unfinished assessments must remain incomplete with null success.")
        records[(profile, version)] = row
    count = len(profiles)
    per_version = {}
    for version in VERSIONS:
        states = dict.fromkeys((*DISPOSITIONS, "not_recorded"), 0)
        for profile in profiles:
            row = records.get((profile, version))
            states[row["disposition"] if row is not None else "not_recorded"] += 1
        completed = states["success"] + states["non_success"]
        complete = completed == count
        reason = ("population_not_ready" if not population_ready else "assessment_incomplete" if not complete else "zero_denominator" if not count else None)
        per_version[version] = {"expected_profiles": count, "completed_profiles": completed,
            "incomplete_profiles": count - completed, "status_counts": states,
            "successes_observed": states["success"], "denominator_profiles": count,
            "success_rate": states["success"] / count if reason is None else None,
            "success_percent": 100 * states["success"] / count if reason is None else None,
            "assessment_complete": complete, "unavailable_reason": reason}
    contrasts = {}
    for earlier, later in CONTRASTS:
        counts = dict.fromkeys(("improved", "worsened", "unchanged_success", "unchanged_non_success", "incomplete"), 0)
        pairs = []
        for profile, family in profiles.items():
            a, b = records.get((profile, earlier)), records.get((profile, later))
            x, y = (a["success"] if a is not None else None), (b["success"] if b is not None else None)
            if x is None or y is None:
                state, difference = "incomplete", None
            elif y and not x:
                state, difference = "improved", 1
            elif x and not y:
                state, difference = "worsened", -1
            else:
                state, difference = ("unchanged_success" if x else "unchanged_non_success"), 0
            counts[state] += 1
            pairs.append({"profile_id": profile, "family_id": family, "earlier_success": x,
                "later_success": y, "pair_state": state, "success_difference": difference})
        reason = ("population_not_ready" if not population_ready else "assessment_incomplete" if counts["incomplete"] else "zero_denominator" if not count else None)
        contrasts[later + "_minus_" + earlier] = {"earlier_version": earlier, "later_version": later,
            "expected_pairs": count, "completed_pairs": count - counts["incomplete"], "pair_counts": counts,
            "unchanged_pairs": counts["unchanged_success"] + counts["unchanged_non_success"],
            "denominator_profiles": count, "assessment_complete": counts["incomplete"] == 0,
            "difference_percentage_points": 100 * (counts["improved"] - counts["worsened"]) / count if reason is None else None,
            "unavailable_reason": reason, "paired_case_outcomes": pairs}
    family_sizes = {family: sum(value == family for value in profiles.values()) for family in sorted(set(profiles.values()))}
    return {"version": VERSION, "population_ready": population_ready, "profiles": count, "families": len(family_sizes),
        "family_sizes": family_sizes, "point_estimate_weighting": "one weight per profile",
        "experiment_complete": population_ready and count > 0 and all(row["assessment_complete"] for row in per_version.values()),
        "version_order": list(VERSIONS), "per_version": per_version, "contrasts": contrasts,
        "bootstrap_performed": False}
