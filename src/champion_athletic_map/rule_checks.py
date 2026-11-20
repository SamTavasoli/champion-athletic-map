"""Check supplied guidance and frozen food facts without inventing missing coverage."""

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


FOOD_CHECK_ID = "food_facts_numeric"


def _scope(rule, public):
    conditions = rule.get("source_population_conditions") or {}
    for key, low, high in (("age", "age_min", "age_max"), ("school_grade", "grade_min", "grade_max")):
        value = public.get(key)
        if conditions.get(low) is None and conditions.get(high) is None:
            continue
        if value is None:
            return "unknown", "The reported population field needed by this source is unknown."
        if ((conditions.get(low) is not None and value < conditions[low])
                or (conditions.get(high) is not None and value > conditions[high])):
            return "not_applicable", "The supplied age or grade is outside this source population."
    age = public.get("age")
    if age is None:
        return "unknown", "The athlete's age is unknown."
    if not 13 <= age <= 17:
        return "not_applicable", "The supplied age is outside the adopted prototype population."
    return "applicable", "The supplied population matches this source."


def _minute(value):
    if not isinstance(value, str) or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value) is None:
        return None
    return int(value[:2]) * 60 + int(value[3:])


def _window(public):
    try:
        start = date.fromisoformat(public["planning_window"]["start_date"])
        end = date.fromisoformat(public["planning_window"]["end_date"])
        if (end - start).days != 6:
            return set()
        return {(start + timedelta(days=i)).isoformat() for i in range(7)}
    except (KeyError, TypeError, ValueError):
        return set()


def _session_facts(public, response, context):
    """Known timed unions give a lower bound, even when a proposed graph is invalid."""
    window = _window(public)
    sessions, intervals, undated = [], {}, []
    for item in public.get("existing_commitments") or []:
        kind = item.get("activity_type")
        if kind not in ("organized_basketball", "other_organized_sport"):
            continue
        begin, end = _minute(item.get("start_time")), _minute(item.get("end_time"))
        duration = end - begin if begin is not None and end is not None and end >= begin else None
        sessions.append({"date": item.get("date"), "type": kind, "kind": item.get("activity_kind"),
                         "duration": duration, "start": begin, "end": end, "origin": "supplied_commitment"})
    for row in (context or {}).get("roots") or []:
        activity = row.get("activity") or {}
        if row.get("existing_commitment_indexes") or activity.get("existing_commitment_refs"):
            continue
        description = activity.get("description") or ""
        # App-prescribed basketball is structured by the adopted project interpretation.
        if not re.search(r"\bbasketball\b", description, re.I):
            continue
        timing = activity.get("timing") or {}
        begin, end = _minute(timing.get("start_time")), _minute(timing.get("end_time"))
        duration = activity.get("duration_minutes")
        if type(duration) is not int or duration < 0:
            duration = None
        if begin is not None and end is not None and end >= begin:
            if duration is not None and duration != end - begin:
                # Inconsistent candidate extents cannot prove a duration lower bound.
                begin, end, duration = None, None, None
            else:
                duration = end - begin
        sessions.append({"date": row.get("date"), "type": "organized_basketball", "kind": "training",
                         "duration": duration, "start": begin, "end": end, "origin": "proposed_basketball"})
    basketball_days, sport_days = set(), set()
    for item in sessions:
        day = item["date"]
        if day in window and item["duration"] != 0:
            sport_days.add(day)
            if item["type"] == "organized_basketball":
                basketball_days.add(day)
        if item["type"] != "organized_basketball" or item["duration"] is None:
            continue
        if day not in window:
            if day is None:
                undated.append(item["duration"])
            continue
        entry = intervals.setdefault(day, {"timed": [], "untimed": []})
        if item["start"] is not None and item["end"] is not None:
            entry["timed"].append((item["start"], item["end"]))
        else:
            entry["untimed"].append(item["duration"])
    lower_bound = 0
    for entry in intervals.values():
        merged = []
        for begin, end in sorted(entry["timed"]):
            if merged and begin <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([begin, end])
        lower_bound += max(sum(end - begin for begin, end in merged), max(entry["untimed"], default=0))
    lower_bound = max(lower_bound, max(undated, default=0))
    return {"basketball_minutes_lower_bound": lower_bound, "basketball_days": sorted(basketball_days),
            "sport_days": sorted(sport_days), "sessions": sessions,
            "complete_schedule_established": False}


def _row(rule, candidate_id, resources, scope, status, reason, observed=None):
    identifier = rule["candidate_rule_id"]
    return {"check_id": "rule:" + identifier, "candidate_id": candidate_id, "rule_ids": [identifier],
            "status": status, "required": str(rule.get("reviewed_enforcement", "")).startswith("required"),
            "applicability": scope, "reason": reason, "observed": observed,
            "data_versions": {key: resources[key] for key in ("release_id", "rule_file_sha256") if key in resources}}


def external_rule_checks(public, response, packet, resources, candidate_id, context=None):
    """Return one record for every adopted external guidance definition, plus food."""
    rows = resources.get("rules")
    if not isinstance(rows, list) or len(rows) != 29 or len({r["candidate_rule_id"] for r in rows}) != 29:
        raise ValueError("The checker requires all 29 adopted rule definitions.")
    facts = _session_facts(public, response, context)
    output = []
    for rule in rows:
        if rule.get("record_kind") not in ("structured_reference", "general_guidance"):
            continue
        if (context or {}).get("nonplan_basis_verified") is True:
            output.append(_row(rule, candidate_id, resources, "not_applicable", "not_applicable",
                "A supported non-plan request mode does not prescribe a training schedule."))
            continue
        identifier, scope_reason = _scope(rule, public)
        if identifier != "applicable":
            output.append(_row(rule, candidate_id, resources, identifier, identifier, scope_reason))
            continue
        status, observed = "unknown", None
        reason = "The required reported context does not support an automatic conclusion."
        name = rule["candidate_rule_id"]
        threshold = rule.get("reviewed_threshold")
        if name.endswith("_MAX_HOURS"):
            observed = {"known_minutes_lower_bound": facts["basketball_minutes_lower_bound"], "maximum_minutes": threshold}
            if facts["basketball_minutes_lower_bound"] > threshold:
                status, reason = "violated", "Known organized-basketball time already exceeds the adopted maximum."
            else:
                reason = "Time is below the cap on known records; complete classified coverage is not established."
        elif name.endswith("_MIN_REST") or name == "AAP_WEEKLY_SPORT_REST":
            days = facts["sport_days"] if name.startswith("AAP_") else facts["basketball_days"]
            observed = {"known_active_days": len(days), "complete_schedule_established": False}
            if len(days) == 7:
                status, reason = "violated", "All seven dates contain known relevant training or competition."
            else:
                reason = "Apparently free days do not establish rest without complete classified schedule coverage."
        elif "SLEEP" in name:
            observed = ((public.get("history") or {}).get("sleep") or {}).get("average_hours_per_night")
            reason = "A nightly average does not establish each night's sleep or a daily 24-hour measurement."
        elif name.endswith("_PRACTICE_LENGTH"):
            values = [s["duration"] for s in facts["sessions"] if s["type"] == "organized_basketball"
                      and s["kind"] == "practice" and s["duration"] is not None]
            observed = {"known_practice_minutes": values, "recommended_range": threshold}
            if any(value < threshold[0] or value > threshold[-1] for value in values):
                status, reason = "violated", "A supplied practice duration is outside this advisory range; it is not a required training minimum."
            else:
                reason = "The full practice-session set is not established; this source range remains advisory."
        elif name.endswith("_PRACTICES") or name.endswith("_GAMES_WEEK"):
            kind = "practice" if name.endswith("_PRACTICES") else "game"
            count = len({s["date"] for s in facts["sessions"] if s["type"] == "organized_basketball"
                         and s["kind"] == kind and s["date"] in _window(public)})
            maximum = threshold[-1] if isinstance(threshold, list) else threshold
            observed = {"known_event_days_lower_bound": count, "advisory_maximum": maximum}
            if count > maximum:
                status, reason = "violated", "Known distinct relevant event days already exceed this advisory event frequency."
            else:
                reason = "Complete classified weekly event coverage is not established; missing events are not assumed absent."
        output.append(_row(rule, candidate_id, resources, "applicable", status, reason, observed))
    output.append(food_check(public, response, packet, candidate_id))
    return output


def food_check(public, response, packet, candidate_id):
    """Recognize explicit numeric fact forms; other prose remains for semantic review."""
    required = isinstance(public.get("food_question"), str) and bool(public["food_question"].strip())
    facts = response.get("food_facts") if isinstance(response, dict) else None
    base = {"check_id": FOOD_CHECK_ID, "candidate_id": candidate_id, "rule_ids": [], "required": True,
            "applicability": "applicable" if required or facts else "not_applicable", "data_versions": {}, "observed": None}
    if not required and not facts:
        return {**base, "status": "not_applicable", "reason": "No food question or returned food-facts claims require numeric checking."}
    lookups = (packet.get("payload") or {}).get("food_lookup") or []
    found = {str(row["data"]["food_id"]): row for row in lookups
             if row.get("status") == "found" and isinstance(row.get("data"), dict)}
    if not facts:
        return {**base, "status": "unknown", "reason": "No structured food statement was supplied for exact quantity, identity and unit comparison."}
    uncertain = []
    for index, fact in enumerate(facts):
        lookup = found.get(str(fact.get("food_id"))) if isinstance(fact, dict) else None
        if lookup is None:
            uncertain.append(index)
            continue
        source = fact.get("source_ref")
        if not source or source not in lookup.get("source_refs", []):
            uncertain.append(index)
            continue
        data, statement = lookup["data"], fact.get("statement", "")
        # The grammar preserves literal source fields; it does not calculate nutrients.
        pattern = (r"\s*(?P<grams>\d+(?:\.\d+)?)\s*g\s+" + re.escape(data["description"])
                   + r"\s*(?:contains|—|:)\s*(?P<amount>\d+(?:\.\d+)?)\s*"
                     r"(?P<unit>[A-Za-z]+)\s+(?P<nutrient>[^.;]+)\.?\s*")
        match = re.fullmatch(pattern, statement, re.I)
        if match is None:
            uncertain.append(index)
            continue
        candidates = [r for r in data.get("nutrients", [])
                      if isinstance(r.get("nutrient_name"), str)
                      and r["nutrient_name"].casefold() == match["nutrient"].strip().casefold()]
        if len(candidates) != 1 or candidates[0].get("status") != "available":
            uncertain.append(index)
            continue
        nutrient = candidates[0]
        try:
            correct = (Decimal(match["grams"]) == Decimal(str(data["grams"]))
                       and Decimal(match["amount"]) == Decimal(str(nutrient["amount"]))
                       and match["unit"].casefold() == str(nutrient["unit"]).casefold())
        except InvalidOperation:
            uncertain.append(index)
            continue
        if not correct:
            return {**base, "status": "violated", "observed": {"statement_index": index},
                    "reason": "The recognized food statement changes its frozen quantity, nutrient value or unit."}
    if uncertain:
        return {**base, "status": "unknown", "observed": {"unverified_statement_indexes": uncertain},
                "reason": "A food statement lacks exact source/identity binding or uses prose outside the verified numeric grammar."}
    return {**base, "status": "met", "observed": {"statements_checked": len(facts)},
            "reason": "All structured food statements match their frozen identity, reference amount, nutrient value and unit."}
