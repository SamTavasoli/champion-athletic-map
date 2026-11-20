"""Check declared schedules and preserve unknown facts during internal review."""

import hashlib
import importlib.util
import json
import re
from datetime import date, timedelta
from pathlib import Path


CORE_CHECK_IDS = ("output_structure", "calendar_window", "existing_commitments", "activity_accounting",
                  "timing_durations", "availability_and_collisions", "additional_training_limits",
                  "requested_session_count", "resource_feasibility", "reference_identity", "response_type_basis")
POLICY_RULE_IDS = ("USER_AVAILABLE_TIME", "USER_EQUIPMENT_SPACE", "USER_PARTICIPANTS", "USER_EXISTING_COMMITMENTS",
                   "POLICY_REQUIRED_INFORMATION", "POLICY_TIMING_INTEGRITY", "POLICY_SESSION_ACCOUNTING",
                   "POLICY_CATALOG_ELIGIBILITY", "POLICY_SCOPE", "POLICY_RESULT_SEMANTICS",
                   "POLICY_INDEPENDENT_EVALUATION", "POLICY_REVIEW_ACTIVATION")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _minute(value):
    if not isinstance(value, str) or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value) is None:
        return None
    return int(value[:2]) * 60 + int(value[3:])


def _interval(value):
    if not isinstance(value, dict):
        return None
    start, end = _minute(value.get("start_time")), _minute(value.get("end_time"))
    return (start, end) if start is not None and end is not None and end > start else None


def _overlap(a, b):
    return max(a[0], b[0]) < min(a[1], b[1])


def _combine(statuses):
    return "violated" if "violated" in statuses else "unknown" if "unknown" in statuses else "met"


def _request_facts(public):
    request = public["athlete_request"].lower()
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
    count = re.search(r"\b(one|two|three|four|five|six|seven|[1-9][0-9]*)\s+(?:(?:extra|additional|uninterrupted)\s+)?(?:[1-9][0-9]*[- ]minute\s+)?(?:basketball\s+)?sessions?\b", request)
    number = words.get(count.group(1), None) if count else None
    if count and number is None:
        number = int(count.group(1))
    duration = re.search(r"\b([1-9][0-9]*)[- ]minute\s+(?:basketball\s+)?session\b", request)
    duration = int(duration.group(1)) if duration else None
    prohibited = bool(re.search(r"\b(diagnose|diagnosis|rehabilitation program|rehab program|weight[- ]cutting|supplement dos(?:e|ing)|individualized diet|personalized calorie target)\b", request))
    if re.search(r"\b(?:do not|don't|without|no)\s+(?:provide\s+)?(?:a\s+)?(?:diagnose|diagnosis|rehabilitation|rehab|weight[- ]cutting|supplement|individualized|personalized)", request):
        prohibited = False
    if public.get("age") is not None and not 13 <= public["age"] <= 17:
        prohibited = True
    missing = []
    if public.get("age") is None:
        missing.append("age")
    if public.get("participants_available") is None and any(term in request for term in ("passing rotation", "equal turns", "everyone who", "all participants", "each person")):
        missing.append("participants")
    only_existing = (any(term in request for term in ("existing", "supplied", "current"))
                     and any(term in request for term in ("only", "no additional", "no extra")))
    if not only_existing and public.get("availability") is None:
        missing.append("availability")
    conflict = None
    if duration is not None:
        known = [_interval(item) for item in public.get("availability") or []]
        if known and all(item is not None for item in known) and all(b - a < duration for a, b in known):
            conflict = "Requested " + str(duration) + " minutes; longest supplied window is " + str(max(b - a for a, b in known)) + "."
        cap = (public.get("time_limits") or {}).get("max_session_minutes")
        if cap is not None and duration > cap:
            conflict = "Requested " + str(duration) + " minutes exceeds session limit " + str(cap) + "."
    limits = public.get("time_limits") or {}
    if number is not None and limits.get("max_additional_sessions_per_week") is not None and number > limits["max_additional_sessions_per_week"]:
        conflict = "Requested " + str(number) + " extra sessions exceeds limit " + str(limits["max_additional_sessions_per_week"]) + "."
    return {"requested_sessions": number, "requested_duration": duration, "outside_scope": prohibited,
            "essential_missing": missing, "conflict": conflict, "only_existing": only_existing,
            "requires_complete_schedule": not only_existing and bool(re.search(r"\b(?:extra|additional|sessions?|workouts?)\b", request))}


def _basis(public, response):
    facts, kind = _request_facts(public), response.get("response_type")
    if facts["outside_scope"]:
        return ("met", "Public request asks for an excluded service.", True, facts) if kind == "outside_scope" else ("violated", "Public request asks for an excluded service; use outside_scope.", False, facts)
    if facts["essential_missing"]:
        fields = ", ".join(facts["essential_missing"])
        if kind == "clarification":
            questions = " ".join(response.get("questions") or []).lower()
            if all(any(term in questions for term in ({"participants": ("participant", "people", "person", "attend"), "age": ("age", "old"), "availability": ("available", "availability", "days", "times")}[field])) for field in facts["essential_missing"]):
                return "met", "Clarification addresses essential missing " + fields + ".", True, facts
            return "unknown", "Clarification must address essential missing " + fields + ".", False, facts
        return "violated", "Essential missing " + fields + " is not resolved by this response type.", False, facts
    if facts["conflict"]:
        if kind == "constraint_conflict":
            text = (str(response.get("explanation", "")) + " " + " ".join(response.get("unresolved_issues") or [])).lower()
            if any(term in text for term in ("window", "availab", "limit", "minute", "session")):
                return "met", facts["conflict"], True, facts
            return "unknown", "Conflict response must identify the supported public conflict.", False, facts
        return "violated", facts["conflict"], False, facts
    if kind == "clarification" and facts["requires_complete_schedule"]:
        questions = " ".join(response.get("questions") or []).lower()
        if (re.search(r"\b(?:complete|full|all|other|entire)\b", questions)
                and re.search(r"\b(?:sports?|basketball|training|practice|practices)\b", questions)
                and re.search(r"\b(?:schedule|commitments?|activities|sessions?)\b", questions)):
            return "met", "Clarification requests complete weekly sport coverage needed by the adopted participation checks; no completeness attestation is supplied.", True, facts
    if kind == "plan":
        return "met", "No coded public scope, essential-information or numeric conflict prevents planning.", False, facts
    if kind in ("clarification", "constraint_conflict", "outside_scope"):
        return "unknown", "No coded public basis establishes this non-plan response; evaluator interpretation cannot waive this unknown.", False, facts
    return "unknown", "Response type is unavailable.", False, facts


def core_checks(public, response, resources, candidate_id, format_valid):
    versions = {"checker": "planning-checks-1", "resource_release": resources["release_id"],
                "rules_sha256": resources["rule_file_sha256"]}
    checks, detail = [], {}
    def add(identifier, status, reason, observed=None, required=True, rule_ids=None):
        row = {"check_id": identifier, "candidate_id": candidate_id, "status": status, "required": required,
               "applicability": "excluded_with_public_basis" if status == "not_applicable" else "applicable_or_unresolved",
               "reason": reason, "observed": observed, "rule_ids": rule_ids or [], "data_versions": versions}
        checks.append(row)
        detail[identifier] = row
        return row
    add("output_structure", "met" if format_valid else "violated", "Shared strict JSON/schema/structure validation " + ("passed." if format_valid else "failed; raw output retained."))
    if not isinstance(response, dict):
        for identifier in CORE_CHECK_IDS[1:]:
            add(identifier, "unknown", "No usable response object for this check.")
        context = {"nonplan_basis_verified": False, "graph_valid": False, "roots": [], "activities": [], "accounting_status": "unknown"}
    else:
        basis, basis_reason, verified, facts = _basis(public, response)
        kind = response.get("response_type")
        context = {"nonplan_basis_verified": verified, "graph_valid": False, "roots": [], "activities": [], "accounting_status": "unknown"}
        if kind != "plan":
            for identifier in CORE_CHECK_IDS[1:-1]:
                if identifier == "reference_identity":
                    continue
                add(identifier, "not_applicable" if verified else "unknown", "Supported non-plan response has no new schedule." if verified else "Non-plan basis is unresolved; schedule checks are not waived.")
            _references(public, response, resources, candidate_id, add)
            add("response_type_basis", basis, basis_reason)
        else:
            rows = response.get("weekly_schedule")
            rows = rows if isinstance(rows, list) else []
            activities = []
            for day in rows:
                if not isinstance(day, dict):
                    continue
                for activity in day.get("activities", []) if isinstance(day.get("activities"), list) else []:
                    if not isinstance(activity, dict):
                        continue
                    timing = _interval(activity.get("timing"))
                    refs = activity.get("existing_commitment_refs")
                    indexes = []
                    for ref in refs if isinstance(refs, list) else []:
                        if isinstance(ref, str) and re.fullmatch(r"/existing_commitments/(0|[1-9][0-9]*)", ref):
                            indexes.append(int(ref.rsplit("/", 1)[1]))
                    activities.append({"date": day.get("date"), "activity": activity,
                        "duration_minutes": activity.get("duration_minutes"),
                        "start_minute": timing[0] if timing else None, "end_minute": timing[1] if timing else None,
                        "existing_commitment_indexes": indexes})
            expected = [(date.fromisoformat(public["planning_window"]["start_date"]) + timedelta(days=i)).isoformat() for i in range(7)]
            dates = [day.get("date") if isinstance(day, dict) else None for day in rows]
            window_ok = response.get("planning_window") == public["planning_window"] and dates == expected
            add("calendar_window", "met" if window_ok else "violated", "Seven chronological dates and planning window " + ("match." if window_ok else "do not match the supplied window."))

            by_id, graph_status, graph_reasons = {}, "met", []
            for item in activities:
                identifier = item["activity"].get("activity_id")
                if not isinstance(identifier, str) or identifier in by_id:
                    graph_status = "violated"; graph_reasons.append("Missing or duplicate activity ID.")
                else:
                    by_id[identifier] = item
            roots = []
            for item in activities:
                activity, chain = item["activity"], set()
                relation = activity.get("relationship") or {}
                if not isinstance(relation, dict):
                    graph_status = "violated"; continue
                if relation.get("kind") == "separate_session":
                    if relation.get("parent_activity_id") is not None:
                        graph_status = "violated"; graph_reasons.append("Separate session has a parent.")
                    roots.append(item)
                    continue
                if relation.get("kind") != "part_of_activity":
                    graph_status = "violated"; graph_reasons.append("Unknown session relationship."); continue
                cursor = item
                while (cursor["activity"].get("relationship") or {}).get("kind") == "part_of_activity":
                    identifier = cursor["activity"].get("activity_id")
                    parent_id = (cursor["activity"].get("relationship") or {}).get("parent_activity_id")
                    if identifier in chain or parent_id not in by_id or parent_id == identifier:
                        graph_status = "violated"; graph_reasons.append("Missing, self or cyclic parent."); break
                    chain.add(identifier)
                    parent = by_id[parent_id]
                    if parent["date"] != cursor["date"]:
                        graph_status = "violated"; graph_reasons.append("Component parent is on another date."); break
                    if cursor["start_minute"] is None or parent["start_minute"] is None:
                        if graph_status != "violated": graph_status = "unknown"
                        graph_reasons.append("Component containment has unknown timing.")
                    elif not (parent["start_minute"] <= cursor["start_minute"] < cursor["end_minute"] <= parent["end_minute"]):
                        graph_status = "violated"; graph_reasons.append("Component lies outside its parent.")
                    if type(cursor["duration_minutes"]) is int and type(parent["duration_minutes"]) is int and cursor["duration_minutes"] > parent["duration_minutes"]:
                        graph_status = "violated"; graph_reasons.append("Component duration exceeds its parent.")
                    cursor = parent
            context.update(activities=activities, roots=roots, graph_valid=graph_status == "met", accounting_status=graph_status)
            add("activity_accounting", graph_status, "; ".join(dict.fromkeys(graph_reasons)) if graph_reasons else "Distinct root sessions and component links are consistent.")

            existing = public.get("existing_commitments")
            existing_status, existing_reasons = "met", []
            if existing is None:
                existing_status, existing_reasons = "unknown", ["Existing commitments were not reported."]
                existing = []
            for item in activities:
                refs = item["activity"].get("existing_commitment_refs")
                if not isinstance(refs, list) or len(refs) != len(item["existing_commitment_indexes"]) or len(set(refs)) != len(refs) or any(i >= len(existing) for i in item["existing_commitment_indexes"]):
                    existing_status = "violated"; existing_reasons.append("Invalid or invented commitment reference.")
                elif len(item["existing_commitment_indexes"]) > 1:
                    existing_status = _combine([existing_status, "unknown"]); existing_reasons.append("A single activity links multiple commitments; distinct-event identity is unresolved.")
            for index, commitment in enumerate(existing):
                matches = [item for item in roots if index in item["existing_commitment_indexes"]]
                if len(matches) != 1:
                    existing_status = "violated"; existing_reasons.append("Commitment " + str(index) + " must appear once as a root session."); continue
                item = matches[0]
                known = _interval(commitment)
                timing = item["activity"].get("timing") or {}
                if commitment.get("date") is None or known is None:
                    if existing_status != "violated": existing_status = "unknown"
                    existing_reasons.append("Commitment " + str(index) + " has unknown date or timing.")
                if (commitment.get("date") is not None and item["date"] != commitment["date"]
                    or any(commitment.get(key) is not None and timing.get(key) != commitment[key] for key in ("start_time", "end_time"))
                    or known is not None and item["duration_minutes"] != known[1] - known[0]):
                    existing_status = "violated"; existing_reasons.append("Commitment " + str(index) + " changed its date, time or duration.")
            add("existing_commitments", existing_status, "; ".join(dict.fromkeys(existing_reasons)) if existing_reasons else "Every supplied commitment is preserved once with known timing and duration.")

            timing_status, timing_reasons = "met", []
            for item in activities:
                activity, duration = item["activity"], item["duration_minutes"]
                if item["start_minute"] is None or type(duration) is not int:
                    timing_status = _combine([timing_status, "unknown"]); timing_reasons.append("Activity timing or duration is unknown.")
                elif duration <= 0 or duration != item["end_minute"] - item["start_minute"]:
                    timing_status = "violated"; timing_reasons.append("Activity duration disagrees with its local time interval.")
                raw_timing = activity.get("timing")
                if isinstance(raw_timing, dict) and _minute(raw_timing.get("start_time")) is not None and _minute(raw_timing.get("end_time")) is not None and _minute(raw_timing["end_time"]) <= _minute(raw_timing["start_time"]):
                    timing_status = "violated"; timing_reasons.append("Reversed or zero-length timing cannot be treated as an overnight session.")
            add("timing_durations", timing_status, "; ".join(dict.fromkeys(timing_reasons)) if timing_reasons else "All declared activity durations match their local intervals.")

            additional = [item for item in roots if not item["existing_commitment_indexes"]]
            availability_status, availability_reasons = "met", []
            available = public.get("availability")
            for item in additional:
                span = None if item["start_minute"] is None else (item["start_minute"], item["end_minute"])
                slots = [slot for slot in available or [] if slot.get("date") in (None, item["date"])]
                if available is None or span is None:
                    availability_status = _combine([availability_status, "unknown"]); availability_reasons.append("Added session availability or timing is unknown.")
                elif not any(slot.get("date") == item["date"] and _interval(slot) and _interval(slot)[0] <= span[0] < span[1] <= _interval(slot)[1] for slot in slots):
                    if any(slot.get("date") is None or _interval(slot) is None for slot in slots):
                        availability_status = _combine([availability_status, "unknown"]); availability_reasons.append("A potentially relevant availability slot is incomplete.")
                    else:
                        availability_status = "violated"; availability_reasons.append("An added session lies outside supplied availability.")
                for commitment in existing:
                    other = _interval(commitment)
                    if span and other and commitment.get("date") == item["date"] and _overlap(span, other):
                        availability_status = "violated"; availability_reasons.append("An added session overlaps a supplied commitment.")
            for i, first in enumerate(roots):
                for second in roots[i + 1:]:
                    if first["date"] == second["date"] and first["start_minute"] is not None and second["start_minute"] is not None and _overlap((first["start_minute"], first["end_minute"]), (second["start_minute"], second["end_minute"])):
                        availability_status = "violated"; availability_reasons.append("Distinct root sessions overlap.")
            add("availability_and_collisions", availability_status, "; ".join(dict.fromkeys(availability_reasons)) if availability_reasons else "Added sessions fit supplied slots and known commitments without root-session overlap.")

            limits, limit_status, limit_reasons = public.get("time_limits") or {}, graph_status, []
            known_durations = [item["duration_minutes"] for item in additional if type(item["duration_minutes"]) is int]
            total = sum(known_durations)
            for key, observed in (("max_additional_sessions_per_week", len(additional)), ("max_additional_minutes_per_week", total)):
                bound = limits.get(key)
                if bound is not None and observed > bound:
                    limit_status = "violated"; limit_reasons.append(str(observed) + " exceeds " + key + "=" + str(bound) + ".")
            bound = limits.get("max_session_minutes")
            if bound is not None and any(value > bound for value in known_durations):
                limit_status = "violated"; limit_reasons.append("An added root session exceeds max_session_minutes=" + str(bound) + ".")
            if len(known_durations) != len(additional):
                limit_status = _combine([limit_status, "unknown"]); limit_reasons.append("Unknown added duration prevents a complete total.")
            add("additional_training_limits", limit_status, "; ".join(limit_reasons) if limit_reasons else "Known additional-session and minute limits are respected.", {"additional_sessions": len(additional), "known_minutes": total})
            target = facts["requested_sessions"]
            requested_status = graph_status
            if target is None:
                numeric_request = bool(re.search(r"\b(?:one|two|three|four|five|six|seven|[1-9][0-9]*)\b", public["athlete_request"].lower())
                                       and re.search(r"\b(?:sessions?|workouts?|practices?)\b", public["athlete_request"].lower()))
                requested_status = "unknown" if numeric_request else "not_applicable"
                request_reason = "A numeric training request is outside the declared literal count grammar." if numeric_request else "No explicit numeric session count applies; goal interpretation is reviewed by the evaluator."
            else:
                requested_status = "met" if graph_status == "met" and len(additional) == target else "violated" if graph_status == "met" else "unknown"
                request_reason = "Requested " + str(target) + " additional sessions; scheduled " + str(len(additional)) + "."
            if facts["requested_duration"] is not None:
                if any(value != facts["requested_duration"] for value in known_durations):
                    requested_status = "violated"; request_reason += " Requested session duration was changed."
            add("requested_session_count", requested_status, request_reason)
            resource_status, resource_reason, resource_parts = _resources(public, additional, resources)
            context["resource_parts"] = resource_parts
            add("resource_feasibility", resource_status, resource_reason)
            _references(public, response, resources, candidate_id, add)
            add("response_type_basis", basis, basis_reason)
    # Each adopted project policy is represented, including workflow-only safeguards.
    mapping = {
        "USER_AVAILABLE_TIME": ("availability_and_collisions", "additional_training_limits"),
        "USER_EQUIPMENT_SPACE": ("resource_feasibility",), "USER_PARTICIPANTS": ("resource_feasibility",),
        "USER_EXISTING_COMMITMENTS": ("existing_commitments",), "POLICY_REQUIRED_INFORMATION": ("response_type_basis",),
        "POLICY_TIMING_INTEGRITY": ("timing_durations", "availability_and_collisions"),
        "POLICY_SESSION_ACCOUNTING": ("activity_accounting",), "POLICY_CATALOG_ELIGIBILITY": ("reference_identity",),
        "POLICY_SCOPE": ("response_type_basis",)}
    for rule_id in POLICY_RULE_IDS:
        if rule_id == "POLICY_SCOPE" and isinstance(response, dict):
            scope_facts = _request_facts(public)
            if scope_facts["outside_scope"]:
                status = "met" if response.get("response_type") == "outside_scope" else "violated"
                reason = "An excluded service request requires outside_scope."
            elif public.get("age") is None:
                status = "met" if response.get("response_type") == "clarification" and "age" in " ".join(response.get("questions") or []).lower() else "unknown"
                reason = "Unknown age requires a relevant clarification; no target population is inferred."
            elif response.get("response_type") == "outside_scope":
                status, reason = "unknown", "No coded public scope exclusion supports outside_scope."
            else:
                status, reason = "met", "Basketball planning and its relevant clarifications or conflicts are in scope."
        elif rule_id in ("USER_EQUIPMENT_SPACE", "USER_PARTICIPANTS") and context.get("resource_parts"):
            key = "equipment_space" if rule_id == "USER_EQUIPMENT_SPACE" else "participants"
            status = context["resource_parts"][key]
            reason = "Declared " + key.replace("_", " ") + " checks: " + status + "; unknown activity-specific requirements are not assumed."
        elif rule_id in mapping:
            source = [detail[key] for key in mapping[rule_id]]
            statuses = [row["status"] for row in source]
            status = "not_applicable" if all(value == "not_applicable" for value in statuses) else _combine(statuses)
            reason = "; ".join(dict.fromkeys(row["reason"] for row in source if row["status"] not in ("met", "not_applicable"))) or source[0]["reason"]
        elif rule_id == "POLICY_RESULT_SEMANTICS":
            status, reason = "met", "Four-state results retain reasons and unknown evidence."
        elif rule_id == "POLICY_INDEPENDENT_EVALUATION":
            status, reason = "met", "Internal checks use public inputs and do not produce independent research scores."
        else:
            status, reason = "met", "Active delegated approval hashes and all 29 adopted definitions were verified."
        add("rule:" + rule_id, status, reason, rule_ids=[rule_id])
    return checks, context


def _resources(public, additional, resources):
    if not additional:
        return "not_applicable", "No newly added session requires resources.", {"equipment_space": "not_applicable", "participants": "not_applicable"}
    status, reasons, people_status, equipment_status = "met", [], "met", "met"
    available = public.get("equipment")
    quantities = {} if available is None else {str(item["name"]).casefold().strip(): item.get("quantity") for item in available}
    aliases = {"ball": "basketball", "basketballs": "basketball", "balls": "basketball", "cone": "cones", "basket": "hoop", "basketball hoop": "hoop"}
    canonical = lambda value: aliases.get(str(value).casefold().strip(), str(value).casefold().strip())
    quantities = {canonical(key): value for key, value in quantities.items()}
    supplied_space = public.get("space") or {}
    for item in additional:
        declared = item["activity"].get("resources")
        if not isinstance(declared, dict):
            status = _combine([status, "unknown"]); people_status = _combine([people_status, "unknown"]); equipment_status = _combine([equipment_status, "unknown"]); reasons.append("Added session resource requirements are unreported."); continue
        equipment = declared.get("equipment")
        if equipment is None or available is None:
            status = _combine([status, "unknown"]); equipment_status = _combine([equipment_status, "unknown"]); reasons.append("Equipment requirements or availability are unknown.")
        else:
            for needed in equipment:
                key, quantity = canonical(needed["name"]), needed.get("quantity")
                if key not in quantities:
                    status = "violated"; equipment_status = "violated"; reasons.append("Required equipment " + needed["name"] + " is not supplied.")
                elif quantities[key] is None or quantity is None:
                    status = _combine([status, "unknown"]); equipment_status = _combine([equipment_status, "unknown"]); reasons.append("Equipment quantity is unknown.")
                elif quantity > quantities[key]:
                    status = "violated"; equipment_status = "violated"; reasons.append("Required equipment quantity exceeds supply.")
        need, supply = declared.get("participants"), public.get("participants_available")
        if need is None or supply is None:
            status = _combine([status, "unknown"]); people_status = _combine([people_status, "unknown"]); reasons.append("Participant requirement or availability is unknown.")
        elif need > supply:
            status = "violated"; people_status = "violated"; reasons.append("Required participants exceed supplied count.")
        space = declared.get("space")
        if not isinstance(space, str) or not space.strip() or not supplied_space:
            status = _combine([status, "unknown"]); equipment_status = _combine([equipment_status, "unknown"]); reasons.append("Space requirements or availability are unknown.")
        else:
            text = space.casefold()
            rank = {"none": 0, "single_hoop_area": 1, "half_court": 2, "full_court": 3}
            needed = 3 if "full court" in text or "full_court" in text else 2 if "half court" in text or "half_court" in text else 1 if "hoop" in text or "basket" in text else 0
            supply = supplied_space.get("court_access")
            if needed and supply is not None and needed > rank[supply]:
                status = "violated"; equipment_status = "violated"; reasons.append("Declared court requirement exceeds supplied access.")
            if ("hoop" in text or "basket" in text) and supplied_space.get("hoop_access") is False:
                status = "violated"; equipment_status = "violated"; reasons.append("Declared hoop requirement conflicts with no hoop access.")
            if supplied_space.get("restrictions"):
                status = _combine([status, "unknown"]); equipment_status = _combine([equipment_status, "unknown"]); reasons.append("Narrative space restrictions require interpretation; no coded feasibility pass.")
        # Optional catalog IDs do not become a membership requirement for free-form activities.
        identifiers = [value for value in item["activity"].get("evidence_refs") or [] if value in resources["drills"]]
        if identifiers:
            for identifier in identifiers:
                record = resources["drills"][identifier]
                minimum = record.get("minimum_participants")
                if minimum is None:
                    status = _combine([status, "unknown"]); people_status = _combine([people_status, "unknown"]); reasons.append("Selected catalog participant-role requirements are not numerically verified.")
                elif public.get("participants_available") is not None and public["participants_available"] < minimum:
                    status = "violated"; people_status = "violated"; reasons.append("Selected catalog minimum participants exceed supply.")
                if not record.get("equipment") or not record.get("space"):
                    status = _combine([status, "unknown"]); equipment_status = _combine([equipment_status, "unknown"]); reasons.append("Selected catalog equipment or space requirements are incomplete.")
                equipment_status = _combine([equipment_status, "unknown"])
                status = _combine([status, "unknown"]); reasons.append("Narrative catalog equipment and space requirements are not fully machine-verifiable.")
        else:
            status = _combine([status, "unknown"]); people_status = _combine([people_status, "unknown"]); equipment_status = _combine([equipment_status, "unknown"]); reasons.append("Free-form activity requirements are not independently verified; declared resource conflicts remain actionable.")
    return status, "; ".join(dict.fromkeys(reasons)) if reasons else "Reviewed requirements fit supplied resources.", {"equipment_space": equipment_status, "participants": people_status}


def _references(public, response, resources, candidate_id, add):
    identifiers = list(response.get("evidence_refs") or [])
    for day in response.get("weekly_schedule") or []:
        if isinstance(day, dict):
            for item in day.get("activities") or []:
                if isinstance(item, dict): identifiers.extend(item.get("evidence_refs") or [])
    for fact in response.get("food_facts") or []:
        if isinstance(fact, dict) and fact.get("source_ref"): identifiers.append(fact["source_ref"])
    unknown = [value for value in identifiers if value not in resources["known_reference_ids"]]
    held = [value for value in identifiers if value in resources["held_ids"]]
    if unknown or held:
        add("reference_identity", "violated", "Unknown or ineligible supplied source IDs: " + ", ".join(map(str, (unknown + held)[:5])) + ".")
    else:
        add("reference_identity", "met", "Supplied IDs exist and are eligible; identity alone does not establish claim support." if identifiers else "No optional source IDs supplied; absence is not a catalog-membership failure.")


class PlanningChecker:
    def __init__(self, root, client, policy, resources=None):
        self.root, self.client, self.policy = Path(root).resolve(), client, policy
        if resources is not None:
            self.resources = resources
        else:
            pointer = json.loads(self._read("artifacts/language_model/active_resource_release.json"))
            folder = pointer["release_directory"]
            manifest = json.loads(self._read(folder + "/manifest.json", pointer["manifest_sha256"]))
            loaded = {name: json.loads(self._read(folder + "/" + name, manifest["file_hashes"][name]))
                      for name in ("adopted_rules.json", "adopted_drills.json", "decisions.json")}
            rules, drills, decisions = loaded["adopted_rules.json"], loaded["adopted_drills.json"], loaded["decisions.json"]
            self.resources = {"rules": rules["records"], "release_id": manifest["release_id"],
                "rule_file_sha256": manifest["file_hashes"]["adopted_rules.json"],
                "drills": {row["catalog_candidate_id"]: row for row in drills["records"]}, "aliases": drills["aliases"],
                "held_ids": set(decisions["held_drill_ids"] + decisions["held_rule_ids"])}
        if (len(self.resources.get("rules", [])) != 29 or len({row["candidate_rule_id"] for row in self.resources["rules"]}) != 29
                or any(row.get("adoption_status") != "adopted_by_team_delegation" or row.get("enabled_for_planner") is not True for row in self.resources["rules"])):
            raise ValueError("The checker requires the complete adopted and enabled rule release.")
        source = self.root / "src/champion_athletic_map/rule_checks.py"
        module = importlib.util.module_from_spec(importlib.util.spec_from_file_location("champion_external_rule_checks", source))
        exec(compile(source.read_bytes(), str(source), "exec"), module.__dict__)
        self.external = module.external_rule_checks
        self.expected_check_ids = list(CORE_CHECK_IDS) + ["rule:" + row["candidate_rule_id"] for row in self.resources["rules"]] + ["food_facts_numeric"]

    def _read(self, relative, expected=None):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Checker resources must stay inside our project.")
        data = path.read_bytes()
        if expected and _sha(data) != expected:
            raise ValueError("A checker resource changed: " + relative)
        return data

    def check(self, public_record, candidate, reference_packet, candidate_id="candidate_0"):
        prepared = self.client.public.prepare_public_input(public_record, self.client.input_schema)
        public = prepared["public_input"]
        if isinstance(candidate, str):
            raw = candidate
        elif isinstance(candidate, dict) and isinstance(candidate.get("response"), dict):
            raw = candidate["response"].get("model_output", {}).get("raw_text", "")
        elif isinstance(candidate, dict) and isinstance(candidate.get("raw_text"), str):
            raw = candidate["raw_text"]
        else:
            raw = json.dumps(candidate, ensure_ascii=False, allow_nan=False)
        parsed = self.client.response.parse_response_text(raw, self.client.response_schema)
        response = parsed["parsed_object"]
        known = set(self.resources["drills"]) | set(self.resources.get("aliases", {})) | {row["candidate_rule_id"] for row in self.resources["rules"]}
        known.update(row.get("source_url") for row in self.resources["rules"] if row.get("source_url"))
        for row in reference_packet["payload"].get("references", []):
            known.update(value for key, value in row.items() if key in ("reference_unit_id", "passage_id") and isinstance(value, str))
            known.update(re.findall(r"https?://[^\s<>\"']+", row.get("complete_required_delivery_text", "")))
        for row in reference_packet["payload"].get("food_lookup", []):
            known.update(row.get("source_refs") or [])
            if isinstance(row.get("data"), dict) and row["data"].get("food_id"): known.add(row["data"]["food_id"])
        resources = {**self.resources, "known_reference_ids": known}
        try:
            usable = response if parsed["parse_valid"] else None
            checks, context = core_checks(public, usable, resources, candidate_id, parsed["parse_valid"])
            if not parsed["parse_valid"]:
                checks[0]["observed"] = parsed["issues"]
                checks[0]["reason"] = "Shared output validation failed: " + str(parsed.get("error_code")) + "."
            checks.extend(self.external(public, usable, reference_packet, resources, candidate_id, context))
            ids = [row["check_id"] for row in checks]
            if len(ids) != len(set(ids)) or set(ids) != set(self.expected_check_ids):
                raise ValueError("The checker did not return exactly its declared coverage.")
            return {"execution_status": "completed", "candidate_id": candidate_id, "checks": checks,
                    "expected_check_ids": self.expected_check_ids, "format_valid": parsed["parse_valid"],
                    "parsed_object": response, "parse_issues": parsed["issues"], "raw_text": raw}
        except Exception as error:
            return {"execution_status": "error", "candidate_id": candidate_id, "checks": [],
                    "expected_check_ids": self.expected_check_ids, "format_valid": parsed["parse_valid"],
                    "parsed_object": response, "raw_text": raw, "error": type(error).__name__ + ": " + str(error)}
