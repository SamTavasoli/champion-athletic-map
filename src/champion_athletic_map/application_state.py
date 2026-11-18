"""Keep profile versions, plan edits and reported progress in one isolated session."""

from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
import re
from uuid import uuid4


STATE_VERSION = "prototype-state-1"
PROGRESS_STATUSES = ("pending", "completed", "skipped")
EDIT_FIELDS = {"activity_id", "date", "start_time", "end_time", "duration_minutes", "replacement_id"}


def clone(value):
    return deepcopy(value)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def planning_content_hash(response):
    """Display ordering does not change the planning facts or their review binding."""
    value = clone(response)
    if isinstance(value, dict) and isinstance(value.get("weekly_schedule"), list):
        for day in value["weekly_schedule"]:
            if isinstance(day, dict) and isinstance(day.get("activities"), list):
                day["activities"].sort(key=lambda item: str(item.get("activity_id", "")))
        value["weekly_schedule"].sort(key=lambda day: str(day.get("date", "")))
    return content_hash(value)


def new_state(session_id=None):
    return {"schema_version": STATE_VERSION, "session_id": session_id or uuid4().hex,
            "profiles": {}, "plans": {}, "current_profile": None, "current_plan": None,
            "jobs": {}, "active_job": None, "progress": {}, "progress_history": [],
            "assessments": [], "events": [], "selection_epoch": 0}


def current_profile(state):
    item = state["profiles"].get(state.get("current_profile"))
    if item is not None and content_hash(item["public_record"]) != item["planning_hash"]:
        raise ValueError("Saved athlete information changed outside the profile form.")
    return clone(item) if item is not None else None


def current_plan(state):
    item = state["plans"].get(state.get("current_plan"))
    if item is not None and planning_content_hash(item["response"]) != item["content_hash"]:
        raise ValueError("A saved plan was changed outside the controlled editor.")
    return clone(item) if item is not None else None


def save_profile(state, public_record, validate_profile):
    record = clone(public_record)
    validate_profile(record)
    digest = content_hash(record)
    old = current_profile(state)
    if old is not None and old["planning_hash"] == digest:
        return old
    version = "profile-" + uuid4().hex
    item = {"profile_version": version, "planning_hash": digest,
            "public_record": record, "saved_at": _now()}
    state["profiles"][version] = clone(item)
    state["current_profile"], state["current_plan"] = version, None
    state["selection_epoch"] += 1
    state["events"].append({"event": "profile_saved", "profile_version": version, "time": _now()})
    return clone(item)


def begin_job(state, job_id, kind="generation"):
    if kind not in ("generation", "review", "demonstration"):
        raise ValueError("Unknown application action.")
    if not isinstance(job_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", job_id) is None:
        raise ValueError("Use a stable application job identifier.")
    profile = current_profile(state)
    if profile is None:
        raise ValueError("Save the athlete information first.")
    plan = current_plan(state)
    if kind == "review" and plan is None:
        raise ValueError("Save a plan version before reviewing it.")
    binding = {"owner_id": state["session_id"], "profile_version": profile["profile_version"],
               "profile_planning_hash": profile["planning_hash"], "kind": kind,
               "plan_version": plan["plan_version"] if kind == "review" else None,
               "plan_content_hash": plan["content_hash"] if kind == "review" else None}
    if job_id in state["jobs"]:
        existing = state["jobs"][job_id]
        if any(existing.get(key) != value for key, value in binding.items()):
            raise ValueError("That job belongs to another saved version or action.")
        return {"created": False, "job": clone(existing)}
    active = state.get("active_job")
    if active and state["jobs"].get(active, {}).get("status") in ("active", "unresolved"):
        raise ValueError("The earlier application job is still active or unresolved.")
    job = {"job_id": job_id, **binding, "status": "active", "started_at": _now(),
           "selection_epoch": state["selection_epoch"], "outcome": None}
    state["jobs"][job_id], state["active_job"] = clone(job), job_id
    return {"created": True, "job": clone(job)}


def complete_job(state, job_id, outcome):
    job = state["jobs"].get(job_id)
    if job is None or job.get("owner_id") != state["session_id"]:
        raise ValueError("This job does not belong to the current session.")
    if job["status"] not in ("active", "unresolved"):
        if job.get("outcome") != outcome:
            raise ValueError("A completed job cannot be replaced with another result.")
        return clone(job)
    job["outcome"], job["finished_at"] = clone(outcome), _now()
    job["status"] = "unresolved" if outcome.get("status") == "unresolved" else "completed"
    if job["status"] != "unresolved" and state.get("active_job") == job_id:
        state["active_job"] = None
    return clone(job)


def _parsed(outcome):
    response = outcome.get("response")
    if isinstance(response, dict) and isinstance(response.get("model_output"), dict):
        return response["model_output"].get("parsed_object")
    return response if isinstance(response, dict) and "response_type" in response else None


def _week(profile):
    return clone(profile["public_record"]["input"]["planning_window"])


def _activity_versions(profile, response, activity_sources):
    versions = {}
    for day in response.get("weekly_schedule", []) if isinstance(response, dict) else []:
        for activity in day.get("activities", []):
            identifier = activity["activity_id"]
            if identifier in versions:
                raise ValueError("Activity identifiers must be unique across the saved week.")
            occurrence = "occ-" + content_hash({"profile_id": profile["public_record"]["profile_id"],
                "week": _week(profile), "activity_id": identifier})[:24]
            digest = content_hash({"date": day["date"], "activity": activity,
                                   "source": activity_sources.get(identifier)})
            versions[identifier] = {"occurrence_id": occurrence, "activity_revision": "activity-" + digest[:24],
                "content_hash": digest, "date": day["date"], "activity": clone(activity)}
    return versions


def relationship_issues(response):
    """Check the identities needed for safe editing, without repairing a response."""
    if not isinstance(response, dict) or response.get("response_type") != "plan":
        return []
    days = response.get("weekly_schedule")
    if not isinstance(days, list):
        return ["The response has no calendar rows."]
    by_id, dates, issues = {}, [], []
    for day in days:
        if not isinstance(day, dict) or not isinstance(day.get("activities"), list):
            return ["A calendar row has no activity list."]
        day_date = day.get("date")
        try:
            if not isinstance(day_date, str) or date.fromisoformat(day_date).isoformat() != day_date:
                raise ValueError("Invalid date")
        except (TypeError, ValueError):
            return ["A calendar date is unavailable or invalid."]
        dates.append(day_date)
        for activity in day["activities"]:
            identifier = activity.get("activity_id") if isinstance(activity, dict) else None
            if not isinstance(identifier, str) or not identifier.strip() or identifier in by_id:
                return ["Activity identifiers are missing or duplicated."]
            by_id[identifier] = (day_date, activity)
    if len(dates) != len(set(dates)):
        issues.append("Calendar dates are duplicated.")
    for identifier, (day_date, activity) in by_id.items():
        relation = activity.get("relationship")
        if not isinstance(relation, dict):
            issues.append("An activity has no declared session relationship."); continue
        if relation.get("kind") == "separate_session":
            if relation.get("parent_activity_id") is not None:
                issues.append("A separate session has a parent.")
            continue
        if relation.get("kind") != "part_of_activity":
            issues.append("An activity has an unknown relationship type."); continue
        cursor, visited = identifier, set()
        while cursor in by_id:
            if cursor in visited:
                issues.append("Activity component relationships contain a cycle."); break
            visited.add(cursor)
            parent_relation = by_id[cursor][1].get("relationship") or {}
            if parent_relation.get("kind") != "part_of_activity":
                break
            parent = parent_relation.get("parent_activity_id")
            if parent not in by_id:
                issues.append("An activity component has a missing parent."); break
            if by_id[parent][0] != by_id[cursor][0]:
                issues.append("An activity component is on a different date from its parent."); break
            cursor = parent
    return list(dict.fromkeys(issues))


def build_plan_snapshot(profile_snapshot, response, reference_packet=None, source_versions=None,
                        original_outcome=None, parent=None, activity_sources=None, edits=None, historical=False):
    response, sources = clone(response), clone(activity_sources or {})
    if not isinstance(response, dict) or response.get("response_type") not in ("plan", "clarification", "constraint_conflict", "outside_scope"):
        raise ValueError("Expected a parsed planner response.")
    return {"plan_version": "plan-" + uuid4().hex, "content_hash": planning_content_hash(response),
        "response": response, "reference_packet": clone(reference_packet), "source_versions": clone(source_versions or {}),
        "profile_version": profile_snapshot["profile_version"], "profile_planning_hash": profile_snapshot["planning_hash"],
        "activity_versions": _activity_versions(profile_snapshot, response, sources), "activity_sources": sources,
        "check_report": None, "assessment": None, "model_review_stale": True,
        "original_outcome": clone(original_outcome), "parent_plan_version": parent["plan_version"] if parent else None,
        "edits": clone(edits or []), "saved_at": _now(), "historical": bool(historical), "historical_readonly": False}


def install_plan(state, plan, *, select=True):
    value = clone(plan)
    profile = state["profiles"].get(value["profile_version"])
    if (profile is None or profile["planning_hash"] != value["profile_planning_hash"]
            or planning_content_hash(value["response"]) != value["content_hash"]):
        raise ValueError("The saved plan does not match its profile or planning content.")
    if select and state.get("current_profile") != value["profile_version"]:
        raise ValueError("Select the plan's original saved athlete profile before displaying it as current.")
    issues = relationship_issues(value["response"])
    if issues:
        raise ValueError("The calendar cannot become an editable saved plan: " + "; ".join(issues))
    if value["plan_version"] in state["plans"] and state["plans"][value["plan_version"]] != value:
        raise ValueError("A saved plan version is immutable.")
    expected = _activity_versions(profile, value["response"], value.get("activity_sources") or {})
    if expected != value["activity_versions"]:
        raise ValueError("Activity identities do not match the saved planning content.")
    state["plans"][value["plan_version"]] = value
    if select:
        state["current_plan"] = value["plan_version"]
    for item in _trackable(profile, value) if select else []:
        existing = state["progress"].get(item["occurrence_id"])
        if existing is not None and existing.get("activity_revision") == item["activity_revision"]:
            if existing.get("plan_version") != value["plan_version"]:
                state["progress_history"].append(clone(existing))
                state["progress"][item["occurrence_id"]] = {**clone(existing), "plan_version": value["plan_version"]}
            continue
        if existing is not None:
            state["progress_history"].append(clone(existing))
        state["progress"][item["occurrence_id"]] = {"occurrence_id": item["occurrence_id"],
            "activity_revision": item["activity_revision"], "plan_version": value["plan_version"],
            "status": "pending", "updated_at": _now()}
    return clone(value)


def attach_outcome(state, job_id, outcome, reference_packet=None, source_versions=None, check_report=None, *, historical=False):
    job = state["jobs"].get(job_id)
    if job is None or job.get("kind") not in ("generation", "demonstration"):
        raise ValueError("Only the original generation job can attach its returned response.")
    complete_job(state, job_id, outcome)
    if job.get("attached_plan_version"):
        saved = clone(state["plans"][job["attached_plan_version"]])
        return {"attached": state.get("current_plan") == saved["plan_version"],
                "reason": "The saved job result was already recorded.", "plan": saved}
    response = _parsed(outcome)
    terminal = outcome.get("terminal_state")
    if (outcome.get("completion_valid") is not True or outcome.get("format_valid") is not True
            or terminal in ("execution_error", "blocked_before_execution") or response is None):
        return {"attached": False, "reason": "The workflow did not return a complete valid final response.", "plan": None}
    issues = relationship_issues(response)
    if issues:
        return {"attached": False, "reason": "Draft needs attention: " + "; ".join(issues),
                "relationship_issues": issues, "plan": None}
    profile = clone(state["profiles"][job["profile_version"]])
    historical = bool(historical or job["kind"] == "demonstration")
    plan = build_plan_snapshot(profile, response, reference_packet, source_versions,
                               original_outcome=outcome, historical=historical)
    plan["check_report"] = clone(check_report)
    current = (state.get("current_profile") == job["profile_version"]
               and state["selection_epoch"] == job["selection_epoch"])
    if not historical:
        plan["assessment"] = {"assessment_id": "assessment-" + uuid4().hex,
            "bindings": _bindings(profile, plan, source_versions or {}),
            "report": {"internally_accepted": bool(outcome.get("internally_accepted")),
                       "terminal_state": terminal, "check_results": clone(outcome.get("check_results", [])),
                       "history": clone(outcome.get("history", []))}, "historical": False, "saved_at": _now()}
        plan["model_review_stale"] = False
        state["assessments"].append(clone(plan["assessment"]))
    installed = install_plan(state, plan, select=current)
    state["jobs"][job_id]["attached_plan_version"] = installed["plan_version"]
    return {"attached": current, "reason": None if current else "Saved against its original profile; the active profile changed.", "plan": installed}


def editable_rows(plan):
    result = []
    activities = {activity["activity_id"]: activity for day in plan["response"].get("weekly_schedule", []) for activity in day.get("activities", [])}
    for day in plan["response"].get("weekly_schedule", []):
        for activity in day.get("activities", []):
            timing = activity.get("timing") or {}
            result.append({"activity_id": activity["activity_id"], "date": day["date"],
                "start_time": timing.get("start_time"), "end_time": timing.get("end_time"),
                "duration_minutes": activity.get("duration_minutes"), "description": activity.get("description"),
                "existing_commitment": _protected(activity["activity_id"], activities),
                "is_component": (activity.get("relationship") or {}).get("kind") == "part_of_activity"})
    return result


def _protected(identifier, activities):
    seen = set()
    while identifier in activities and identifier not in seen:
        seen.add(identifier)
        activity = activities[identifier]
        if activity.get("existing_commitment_refs"):
            return True
        relation = activity.get("relationship") or {}
        identifier = relation.get("parent_activity_id") if relation.get("kind") == "part_of_activity" else None
    return False


def _catalog(record):
    if (not isinstance(record, dict) or not isinstance(record.get("catalog_id"), str)
            or not record["catalog_id"].strip() or not isinstance(record.get("description"), str)
            or not record["description"].strip() or not isinstance(record.get("resources"), dict)
            or not isinstance(record.get("evidence_refs"), list)):
        raise ValueError("The replacement needs a verified canonical record and its authoritative fields.")
    return clone(record)


def save_plan_changes(state, edits, resolve_catalog, check_plan, source_versions):
    plan, profile = current_plan(state), current_profile(state)
    if plan is None or plan["response"].get("response_type") != "plan":
        raise ValueError("There is no saved calendar to edit.")
    if plan.get("historical_readonly"):
        raise ValueError("Required source versions are unavailable; this historical view cannot be edited.")
    if profile is None or plan["profile_version"] != profile["profile_version"]:
        raise ValueError("The active profile differs from this plan; generate a plan for the saved information.")
    if not isinstance(edits, list) or any(not isinstance(row, dict) or set(row) - EDIT_FIELDS for row in edits):
        raise ValueError("Only activity IDs, dates, local times, durations and eligible replacements may be edited.")
    ids = [row.get("activity_id") for row in edits]
    if len(ids) != len(set(ids)):
        raise ValueError("Each proposed activity can be edited once per save.")
    response, sources = clone(plan["response"]), clone(plan.get("activity_sources") or {})
    days = {day["date"]: day for day in response["weekly_schedule"]}
    entries = {activity["activity_id"]: (day, activity) for day in response["weekly_schedule"] for activity in day["activities"]}
    activities = {key: value[1] for key, value in entries.items()}
    changes = []
    for command in edits:
        identifier = command.get("activity_id")
        if identifier not in entries:
            raise ValueError("The edited activity does not exist in this saved plan.")
        day, activity = entries[identifier]
        proposed = clone(activity)
        target_date = command.get("date", day["date"])
        if target_date not in days:
            raise ValueError("An activity must stay inside the saved seven-day planning window.")
        if target_date != day["date"] and (activity.get("relationship") or {}).get("kind") == "part_of_activity":
            raise ValueError("Move a component's parent session to change its day.")
        for key in ("start_time", "end_time"):
            if key in command:
                value = command[key]
                if value is not None and (not isinstance(value, str) or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value) is None):
                    raise ValueError("Times must use local HH:MM or remain unknown.")
                if (proposed.get("timing") or {}).get(key) == value:
                    continue
                proposed.setdefault("timing", {"start_time": None, "end_time": None})
                if proposed["timing"] is None:
                    proposed["timing"] = {"start_time": None, "end_time": None}
                proposed["timing"][key] = value
        if "duration_minutes" in command:
            value = command["duration_minutes"]
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Duration must be a nonnegative whole number of minutes or unknown.")
            proposed["duration_minutes"] = value
        replacement = command.get("replacement_id")
        if replacement:
            if _protected(identifier, activities):
                raise ValueError("Existing commitments must be changed in the athlete information form.")
            if (proposed.get("relationship") or {}).get("kind") != "separate_session" or any((a.get("relationship") or {}).get("parent_activity_id") == identifier for a in activities.values()):
                raise ValueError("Substitute a standalone proposed session; sessions with components need a new generated plan.")
            canonical = _catalog(resolve_catalog(replacement))
            unchanged_identity = (sources.get(identifier) or {}).get("catalog_id") == canonical["catalog_id"]
            new_id = identifier if unchanged_identity else "activity-" + uuid4().hex
            proposed = {"activity_id": new_id, "description": canonical["description"],
                "duration_minutes": proposed.get("duration_minutes"), "resources": canonical["resources"],
                "evidence_refs": canonical["evidence_refs"], "existing_commitment_refs": [],
                "relationship": {"kind": "separate_session", "parent_activity_id": None},
                **({"timing": clone(proposed["timing"])} if "timing" in proposed else {})}
            if not unchanged_identity:
                sources.pop(identifier, None)
            sources[new_id] = canonical
        changed = proposed != activity or target_date != day["date"]
        if _protected(identifier, activities) and changed:
            raise ValueError("Existing commitments must be changed in the athlete information form.")
        if not changed:
            continue
        # Moving a session's day includes its nested components, without changing their times.
        descendants, frontier = [], [identifier]
        if target_date != day["date"]:
            visited = {identifier}
            while frontier:
                parent_id = frontier.pop()
                for child_id, child in activities.items():
                    if child_id not in visited and (child.get("relationship") or {}).get("parent_activity_id") == parent_id:
                        visited.add(child_id); descendants.append(child_id); frontier.append(child_id)
            if any(_protected(child_id, activities) for child_id in descendants):
                raise ValueError("A session containing an existing commitment must be changed through the athlete information form.")
        day["activities"].remove(activity)
        days[target_date]["activities"].append(proposed)
        entries[identifier] = (days[target_date], proposed)
        activities[identifier] = proposed
        changes.append({"activity_id": identifier, "replacement_activity_id": proposed["activity_id"] if proposed["activity_id"] != identifier else None,
            "before": {"date": day["date"], "activity": clone(activity)},
            "after": {"date": target_date, "activity": clone(proposed)}})
        for child_id in descendants:
            source_day, child = entries[child_id]
            if source_day["date"] == target_date:
                continue
            before = {"date": source_day["date"], "activity": clone(child)}
            source_day["activities"].remove(child)
            days[target_date]["activities"].append(child)
            entries[child_id] = (days[target_date], child)
            changes.append({"activity_id": child_id, "replacement_activity_id": None,
                "before": before, "after": {"date": target_date, "activity": clone(child)},
                "reason": "Included component moved with its parent session."})
    # Canonical records remain authoritative when an already substituted plan is saved.
    for identifier, old_source in list(sources.items()):
        authoritative = _catalog(resolve_catalog(old_source["catalog_id"]))
        for day in response["weekly_schedule"]:
            for activity in day["activities"]:
                if activity["activity_id"] == identifier:
                    before = clone(activity)
                    activity.update(description=authoritative["description"], resources=authoritative["resources"], evidence_refs=authoritative["evidence_refs"])
                    if activity != before:
                        changes.append({"activity_id": identifier, "replacement_activity_id": None,
                            "before": {"date": day["date"], "activity": before},
                            "after": {"date": day["date"], "activity": clone(activity)},
                            "reason": "Canonical source fields refreshed from the verified catalog."})
        sources[identifier] = authoritative
    for day in response["weekly_schedule"]:
        if not day["activities"] and not isinstance(day.get("rest_arrangements"), str):
            day["rest_arrangements"] = "No additional training planned."
    graph_issues = relationship_issues(response)
    if graph_issues:
        raise ValueError("The edit changes a protected activity relationship: " + "; ".join(graph_issues))
    if planning_content_hash(response) == plan["content_hash"] and sources == plan.get("activity_sources", {}):
        return plan
    try:
        report = check_plan(profile["public_record"], response, plan.get("reference_packet"))
        if not isinstance(report, dict):
            raise ValueError("The coded checker returned no explicit result.")
    except Exception as error:
        report = {"execution_status": "error", "checks": [], "error": type(error).__name__ + ": " + str(error)}
    updated = build_plan_snapshot(profile, response, plan.get("reference_packet"), source_versions,
        original_outcome=plan.get("original_outcome"), parent=plan, activity_sources=sources, edits=changes)
    updated["check_report"] = clone(report)
    state["events"].append({"event": "plan_changes_saved", "parent_plan_version": plan["plan_version"],
                            "plan_version": updated["plan_version"], "time": _now()})
    return install_plan(state, updated)


def _bindings(profile, plan, versions):
    packet = plan.get("reference_packet") or {}
    return {"profile_version": profile["profile_version"], "profile_planning_hash": profile["planning_hash"],
            "plan_version": plan["plan_version"], "plan_content_hash": plan["content_hash"],
            "reference_packet_id": plan.get("review_reference_packet_id", packet.get("packet_id")), "source_versions": clone(versions)}


def assessment_bindings(state, source_versions=None):
    profile, plan = current_profile(state), current_plan(state)
    if profile is None or plan is None or profile["profile_version"] != plan["profile_version"]:
        raise ValueError("Review requires the exact saved profile and plan version.")
    return _bindings(profile, plan, source_versions if source_versions is not None else plan["source_versions"])


def record_assessment(state, assessment, bindings):
    entry = {"assessment_id": "assessment-" + uuid4().hex, "bindings": clone(bindings),
             "report": clone(assessment), "historical": False, "saved_at": _now()}
    try:
        current = assessment_bindings(state, bindings["source_versions"])
    except (ValueError, KeyError):
        entry["historical"] = True
        state["assessments"].append(clone(entry))
        return {"attached": False, "assessment": entry}
    plan = state["plans"][state["current_plan"]]
    packet = assessment.get("reference_packet") if isinstance(assessment, dict) else None
    if packet is not None:
        profile = current_profile(state)
        if (not isinstance(packet, dict) or packet.get("packet_id") != bindings.get("reference_packet_id")
                or packet.get("public_input_sha256") != content_hash(profile["public_record"]["input"])
                or packet.get("packet_id") != "reference-packet:" + content_hash({key: value for key, value in packet.items() if key != "packet_id"})):
            raise ValueError("The review context does not match the saved athlete information and packet content.")
        current["reference_packet_id"] = packet["packet_id"]
    if current != bindings or plan.get("historical_readonly"):
        entry["historical"] = True
        state["assessments"].append(clone(entry))
        return {"attached": False, "assessment": entry}
    evaluator = assessment.get("evaluator_result") or {}
    evaluator_body = ((evaluator.get("response") or {}).get("model_output") or {}).get("parsed_object")
    complete = (assessment.get("review_complete") is True and assessment.get("execution_status") == "completed"
                and evaluator.get("completion_valid") is True and evaluator.get("format_valid") is True
                and isinstance(evaluator_body, dict) and evaluator_body.get("assessment_complete") is True
                and (assessment.get("acceptance") or {}).get("coverage_valid") is True)
    if not complete:
        entry["historical"] = True
        state["assessments"].append(clone(entry))
        plan["model_review_stale"] = True
        return {"attached": False, "assessment": entry}
    if packet is not None:
        plan["review_reference_packet_id"], plan["review_reference_packet"] = packet["packet_id"], clone(packet)
    plan["assessment"], plan["model_review_stale"] = clone(entry), False
    state["assessments"].append(clone(entry))
    return {"attached": True, "assessment": clone(entry)}


def assessment_current(state, source_versions=None):
    profile, plan = current_profile(state), current_plan(state)
    if profile is None or plan is None or plan.get("model_review_stale") or plan.get("historical_readonly"):
        return False
    assessment = plan.get("assessment")
    if not isinstance(assessment, dict) or assessment.get("historical"):
        return False
    try:
        return assessment["bindings"] == assessment_bindings(state, source_versions)
    except (ValueError, KeyError):
        return False


def _trackable(profile, plan):
    commitments = profile["public_record"]["input"].get("existing_commitments") or []
    result = []
    for identifier, version in plan.get("activity_versions", {}).items():
        activity = version["activity"]
        if (activity.get("relationship") or {}).get("kind") != "separate_session":
            continue
        refs = activity.get("existing_commitment_refs") or []
        if refs:
            indexes = [int(value.rsplit("/", 1)[-1]) for value in refs if isinstance(value, str) and re.fullmatch(r"/existing_commitments/(0|[1-9][0-9]*)", value)]
            if len(indexes) != len(refs) or any(index >= len(commitments) for index in indexes):
                continue
            if not any(commitments[index].get("activity_type") in ("organized_basketball", "other_organized_sport") for index in indexes):
                continue
        elif type(activity.get("duration_minutes")) is int and activity["duration_minutes"] <= 0:
            continue
        elif re.match(r"^\s*(?:rest(?:\s+(?:day|and recovery))?|sleep|school travel|travel|meal|homework)\b",
                      str(activity.get("description", "")), re.IGNORECASE):
            continue
        result.append({**clone(version), "activity_id": identifier, "description": activity.get("description", "")})
    return sorted(result, key=lambda item: (item["date"], item["activity_id"]))


def trackable_sessions(state):
    plan = current_plan(state)
    if plan is None:
        return []
    profile = state["profiles"][plan["profile_version"]]
    result = _trackable(profile, plan)
    for item in result:
        progress = state["progress"].get(item["occurrence_id"])
        item["status"] = progress["status"] if progress and progress.get("activity_revision") == item["activity_revision"] else "pending"
    return result


def update_progress(state, occurrence_id, status):
    if status not in PROGRESS_STATUSES:
        raise ValueError("Choose pending, completed or skipped.")
    session = next((item for item in trackable_sessions(state) if item["occurrence_id"] == occurrence_id), None)
    if session is None:
        raise ValueError("This session is not a current trackable activity.")
    old = state["progress"].get(occurrence_id)
    if old is not None and old.get("status") == status:
        return clone(old)
    if old is not None:
        state["progress_history"].append(clone(old))
    value = {"occurrence_id": occurrence_id, "activity_revision": session["activity_revision"],
             "plan_version": state["current_plan"], "status": status, "updated_at": _now()}
    state["progress"][occurrence_id] = value
    return clone(value)


def progress_summary(state):
    sessions = trackable_sessions(state)
    counts = {status: sum(item["status"] == status for item in sessions) for status in PROGRESS_STATUSES}
    return {**counts, "total": len(sessions),
            "completed_percent": round(100 * counts["completed"] / len(sessions), 1) if sessions else None}


def clear_workspace(state):
    """Clearing the view does not cancel or forget an active backend job."""
    state["current_profile"], state["current_plan"] = None, None
    state["selection_epoch"] += 1


def plan_status(state, source_versions=None):
    plan = current_plan(state)
    if plan is None:
        return "Planning is unavailable"
    kind = plan["response"].get("response_type")
    if kind == "clarification":
        return "More information needed"
    if kind == "constraint_conflict":
        return "A conflict remains"
    if kind == "outside_scope":
        return "Outside the supported scope"
    if plan.get("historical_readonly"):
        return "Historical view; source review needed"
    if assessment_current(state, source_versions):
        report = plan["assessment"]["report"]
        if report.get("internally_accepted") is True or report.get("accepted") is True:
            return "Plan checked"
        return "Draft needs attention"
    return "Changes need review"
