"""Private conditional rule evidence for proposed fictional evaluation cases.

This is not an automatic rule checker, accepted witness or final outcome score.
It never changes a public case, adopts a decision or makes a model request.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

SCHEMA = "case-rule-bound-review-proposals-1"
NUMERIC_GROUPS = {
    "NBA_WEEKLY_ORGANIZED_BASKETBALL_MINUTES": "<=",
    "NBA_WEEKLY_ORGANIZED_BASKETBALL_REST_DAYS": ">=",
}


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def _sha(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _load(path):
    return json.loads(Path(path).read_bytes())


def _lines(path):
    return [json.loads(line) for line in Path(path).read_bytes().splitlines() if line.strip()]


def _minute(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise ValueError("A rule-bound time is not HH:MM.")
    h, m = (int(part) for part in value.split(":"))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("A rule-bound time is outside the local clock.")
    return h * 60 + m


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("An explicit nonnegative integer is needed: " + label)
    return value


def _matches(rule, public):
    conditions = rule.get("source_population_conditions") or {}
    for key, suffix in (("age", "age"), ("school_grade", "grade")):
        lower, upper = conditions.get(suffix + "_min"), conditions.get(suffix + "_max")
        if lower is None and upper is None:
            continue
        value = public.get(key)
        if value is None:
            return None
        if lower is not None and value < lower:
            return False
        if upper is not None and value > upper:
            return False
    return True


def _rule_identity(rule):
    return {
        "candidate_rule_id": rule["candidate_rule_id"],
        "revision_id": rule.get("revision_id"),
        "rule_record_sha256": _sha(rule),
        "source_url": rule.get("source_url"),
        "policy_origin": rule.get("policy_origin"),
    }


def _review_one(record, rules):
    public = record["input"]
    age, grade = public.get("age"), public.get("school_grade")
    if isinstance(age, bool) or not isinstance(age, int) or not 13 <= age <= 17:
        raise ValueError("A proposed planning case is outside the declared age scope.")
    if isinstance(grade, bool) or not isinstance(grade, int):
        raise ValueError("The proposed planning case has no explicit school grade.")
    window = public["planning_window"]
    start, end = date.fromisoformat(window["start_date"]), date.fromisoformat(window["end_date"])
    if (end - start).days != 6:
        raise ValueError("A declared seven-day window is needed for the rule bounds.")
    dates = [(start + timedelta(days=n)).isoformat() for n in range(7)]
    coverage = public.get("schedule_coverage")
    coverage_ok = isinstance(coverage, dict) and coverage.get("existing_commitments_complete") is True and all(
        coverage.get(key) == window[key] for key in ("start_date", "end_date", "timezone"))
    events = public.get("existing_commitments")
    if not isinstance(events, list):
        raise ValueError("The proposed planning case needs an explicit event list.")
    basketball, event_evidence, other_sport = [], [], []
    for index, event in enumerate(events):
        if event["date"] not in dates:
            raise ValueError("An existing event is outside the declared seven-day window.")
        duration = _minute(event["end_time"]) - _minute(event["start_time"])
        if duration <= 0:
            raise ValueError("An existing event has no positive same-day elapsed duration.")
        kind = event.get("activity_type")
        if kind not in {"organized_basketball", "other_organized_sport", "nontraining"}:
            raise ValueError("An existing event needs explicit activity classification.")
        item = {"input_ref": "/input/existing_commitments/" + str(index),
                "date": event["date"], "start_time": event["start_time"],
                "end_time": event["end_time"], "duration_minutes": duration,
                "activity_type": kind, "activity_kind": event.get("activity_kind")}
        event_evidence.append(item)
        if kind == "organized_basketball":
            basketball.append(item)
        elif kind == "other_organized_sport":
            other_sport.append(item)
    overlapping = []
    for index, first in enumerate(basketball):
        for second in basketball[index + 1:]:
            if first["date"] == second["date"] and max(_minute(first["start_time"]), _minute(second["start_time"])) < min(_minute(first["end_time"]), _minute(second["end_time"])):
                overlapping.append([first["input_ref"], second["input_ref"]])
    limits = public["time_limits"]
    additional_minutes = _number(limits["max_additional_minutes_per_week"], "weekly additional minutes")
    additional_sessions = _number(limits["max_additional_sessions_per_week"], "weekly additional sessions")
    per_session = _number(limits["max_session_minutes"], "minutes per session")
    minutes_upper_bound = min(additional_minutes, additional_sessions * per_session)
    existing_minutes = sum(item["duration_minutes"] for item in basketball)
    existing_days = sorted({item["date"] for item in basketball})
    total_upper_bound = existing_minutes + minutes_upper_bound
    rest_lower_bound = max(0, 7 - len(existing_days) - additional_sessions)
    numeric = []
    for group, operator in NUMERIC_GROUPS.items():
        aliases = [rule for rule in rules if rule.get("evaluation_group_id") == group
                   and rule.get("reviewed_enforcement") == "required_prototype_constraint"
                   and _matches(rule, public) is True]
        if not aliases:
            raise ValueError("The proposed case has no applicable adopted numeric rule: " + group)
        if any(rule["reviewed_operator"] != operator for rule in aliases):
            raise ValueError("The adopted numeric operator changed.")
        threshold = (min if operator == "<=" else max)(rule["reviewed_threshold"] for rule in aliases)
        observed = total_upper_bound if operator == "<=" else rest_lower_bound
        covered = observed <= threshold if operator == "<=" else observed >= threshold
        numeric.append({"evaluation_group_id": group, "aliases_scored_once": True,
            "applicable_rule_versions": [_rule_identity(rule) for rule in aliases],
            "project_overlap_policy": "PROJECT_NBA_OVERLAP_CONSERVATIVE_V1",
            "operator": operator, "threshold": threshold,
            "bound_kind": "existing_plus_maximum_additional_minutes" if operator == "<=" else "minimum_remaining_basketball_free_local_dates",
            "bound_value": observed, "bound_covers_required_threshold": covered,
            "result_status": "conditional_bound_supported" if coverage_ok and not overlapping and covered else "needs_review",
            "not_a_final_outcome_score": True})
    project = [rule for rule in rules if rule.get("reviewed_enforcement") == "required_project_policy"]
    advisory = [rule for rule in rules if rule.get("reviewed_enforcement") in {"advisory", "contextual_advisory"}
                and _matches(rule, public) is True]
    return {
        "profile_id": record["profile_id"], "public_record_sha256": _sha(record),
        "age": age, "school_grade": grade, "planning_window": window,
        "schedule_coverage_is_proposed_complete_fact": coverage_ok,
        "source_event_evidence": event_evidence,
        "existing_basketball_minutes": existing_minutes,
        "existing_basketball_dates": existing_days,
        "basketball_free_dates_before_additions": [value for value in dates if value not in existing_days],
        "existing_basketball_overlaps_needing_component_review": overlapping,
        "known_other_sport_events": other_sport,
        "additional_weekly_minutes_limit": additional_minutes,
        "additional_session_limit": additional_sessions,
        "per_session_minutes_limit": per_session,
        "maximum_additional_minutes_within_both_limits": minutes_upper_bound,
        "numeric_rule_bounds": numeric,
        "required_project_policy_versions": [_rule_identity(rule) for rule in project],
        "project_policy_condition_notes": {
            "POLICY_CATALOG_ELIGIBILITY": "Applies to an explicit catalog selection. Do not demand a private witness ID or catalog membership from a generic activity response.",
            "POLICY_SESSION_ACCOUNTING": "Check actual parent/component links and preserve existing events; do not count nested component time twice.",
            "POLICY_REVIEW_ACTIVATION": "A recorded adoption/activation gate; this conditional calculation does not satisfy it.",
            "POLICY_INDEPENDENT_EVALUATION": "A research-protocol requirement separate from Version4 internal review and from this private witness evidence.",
            "POLICY_RESULT_SEMANTICS": "Conditional bounds do not become final Met scores; unknown essential evidence stays Unknown.",
        },
        "applicable_advisory_versions": [_rule_identity(rule) for rule in advisory],
        "remaining_required_evidence": [
            "Accepted source-supported private activity witness with goal relevance, exact dose and resource/role evidence.",
            "Witness sessions within availability and all stated limits; preserve existing events and count parent/component time once.",
            "Essential information and content scope decisions supported by the actual case; no missing fact treated as zero.",
            "Recorded team case/family acceptance and review activation before final protocol freezing.",
            "Common independent evaluation for all versions; no hidden catalog-membership requirement for generic activities.",
        ],
        "advisory_handling": "Sleep, practice-length/frequency, game-frequency and broad sport-rest guidance remain advisory/contextual; absent sleep reports do not create new required feasibility gates.",
        "case_accepted": False, "final_scoring_completed": False,
        "status": "conditional_private_rule_bound_evidence_pending_team_review",
    }


def build_rule_review(source_package, correction_package, *, public_profiles=None):
    """Return private conditional rule evidence; optionally bind new proposed versions."""
    source_package, correction_package = Path(source_package), Path(correction_package)
    rule_path = source_package / "reference_snapshot/adopted_rules.json"
    source_manifest = _load(source_package / "manifest.json")
    correction_manifest = _load(correction_package / "manifest.json")
    expected = source_manifest["files"]["reference_snapshot/adopted_rules.json"]
    if hashlib.sha256(rule_path.read_bytes()).hexdigest() != expected:
        raise ValueError("The bound adopted-rule snapshot changed.")
    register_path = correction_package / "correction_register.jsonl"
    if hashlib.sha256(register_path.read_bytes()).hexdigest() != correction_manifest["files"]["correction_register.jsonl"]:
        raise ValueError("The bound correction register changed.")
    rules = _load(rule_path)["records"]
    if len(rules) != 29 or len({rule["candidate_rule_id"] for rule in rules}) != 29:
        raise ValueError("The adopted29-rule population changed.")
    registers = _lines(register_path)
    selected = {row["profile_id"]: row for row in registers if row["draft_category"] == "feasible"}
    if len(registers) != 200 or len(selected) != 150:
        raise ValueError("The proposed200-case category balance changed.")
    records = {row["profile_id"]: row for row in public_profiles} if public_profiles is not None else {
        key: value["proposed_public_record"] for key, value in selected.items()}
    if not set(selected) <= set(records):
        raise ValueError("A proposed feasible case is absent from the reviewed versions.")
    rows = [_review_one(records[key], rules) for key in selected]
    return {"schema_version": SCHEMA,
        "source_bindings": {"reference_snapshot/adopted_rules.json": expected,
            "correction_register.jsonl": correction_manifest["files"]["correction_register.jsonl"]},
        "cases": rows,
        "summary": {"planning_proposals_reviewed": len(rows), "adopted_rule_definitions": len(rules),
            "numeric_groups_per_case": len(NUMERIC_GROUPS),
            "cases_with_conditional_numeric_bounds_supported": sum(all(rule["result_status"] == "conditional_bound_supported" for rule in row["numeric_rule_bounds"]) for row in rows),
            "largest_existing_basketball_minutes": max(row["existing_basketball_minutes"] for row in rows),
            "largest_basketball_minutes_with_additional_limits": max(next(rule["bound_value"] for rule in row["numeric_rule_bounds"] if rule["operator"] == "<=") for row in rows),
            "least_conservative_basketball_free_days": min(next(rule["bound_value"] for rule in row["numeric_rule_bounds"] if rule["operator"] == ">=") for row in rows),
            "cases_accepted": 0, "new_model_calls": 0},
        "interpretation": [
            "Conditional evidence only: proposed complete coverage and all public case facts require recorded acceptance.",
            "Weekly organized basketball minutes count existing practices/games and app-prescribed structured sessions; a component is not counted twice.",
            "Use the most restrictive applicable overlapping required bound once, including600min for age14/grade9.",
            "No sleep, annual-history, medical clearance, inferred role, invented dose or new required advisory gate is supplied by this review.",
            "Numeric bounds do not certify the complete29-rule workflow, source suitability, accepted feasible witnesses or generated model responses.",
        ],
        "case_approval_created": False, "final_planner_execution_authorized": False}
