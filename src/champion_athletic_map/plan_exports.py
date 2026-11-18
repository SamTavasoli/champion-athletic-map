"""Export a selected saved version and restore it without trusting imported reviews."""

from copy import deepcopy
import csv
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


SNAPSHOT_VERSION = "prototype-snapshot-1"
APPLICATION_VERSION = "prototype-29-1"
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
_PROGRESS_FIELDS = ("occurrence_id", "activity_revision", "plan_version", "status", "updated_at")
_EDIT_FIELDS = ("activity_id", "replacement_activity_id", "date", "start_time", "end_time", "duration_minutes", "replacement_id")
_REVIEW_VERSION_KEYS = {"interactive_profile_schema_sha256", "workflow_config_sha256", "checker_sha256",
    "rule_checker_sha256", "evaluator_prompt_sha256", "evaluator_schema_sha256", "acceptance_policy_sha256",
    "model_digest", "application_config_sha256", "interactive_reference_policy_sha256", "checker"}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _state():
    path = Path(__file__).with_name("application_state.py")
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location("champion_export_state", path))
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def _schema():
    local = Path(__file__).with_name("snapshot_schema.json")
    installed = Path(__file__).resolve().parents[2] / "artifacts/application/snapshot_schema.json"
    return json.loads((local if local.is_file() else installed).read_bytes())


def _strict_json(data):
    if isinstance(data, str):
        data = data.encode("utf-8", errors="strict")
    if not isinstance(data, (bytes, bytearray)) or not 0 < len(data) <= MAX_SNAPSHOT_BYTES:
        raise ValueError("Choose a JSON snapshot no larger than 2 MiB.")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("The snapshot contains a repeated JSON key.")
            result[key] = value
        return result
    def finite(value):
        raise ValueError("The snapshot contains a nonfinite number.")
    try:
        value = json.loads(bytes(data).decode("utf-8", errors="strict"), object_pairs_hook=unique, parse_constant=finite)
        _canonical(value).encode("utf-8", errors="strict")
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("The snapshot must be strict UTF-8 JSON with unique keys and finite numbers.") from error
    return value


def _validate_snapshot(value):
    errors = sorted(Draft202012Validator(_schema(), format_checker=FormatChecker()).iter_errors(value),
                    key=lambda error: (str(list(error.absolute_path)), error.validator))
    if errors:
        error = errors[0]
        path = "/" + "/".join(map(str, error.absolute_path))
        raise ValueError("Snapshot " + path + ": " + error.message[:180])


def _validate(callback, value, label):
    if not callable(callback):
        raise ValueError("A current " + label + " validator is required for restoration.")
    outcome = callback(deepcopy(value))
    if outcome is False or isinstance(outcome, dict) and (outcome.get("parse_valid") is False or outcome.get("valid") is False):
        raise ValueError("The imported " + label + " did not pass current structural validation.")


def _versions(value):
    if not isinstance(value, dict):
        raise ValueError("Source versions must be a mapping.")
    result = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip() or key.casefold() in {"password", "credentials", "api_key", "access_token", "refresh_token", "secret"}:
            raise ValueError("Source version names cannot contain credential fields.")
        result[key] = item if item is None or type(item) in (str, int, bool) else "sha256:" + _hash(item)
    return result


def _progress(value):
    if not isinstance(value, dict) or set(value) != set(_PROGRESS_FIELDS):
        raise ValueError("A progress record does not match the saved-session contract.")
    return {key: deepcopy(value[key]) for key in _PROGRESS_FIELDS}


def _assessment(value):
    """Export only review provenance and a historical, untrusted reported outcome."""
    if not isinstance(value, dict):
        return None
    report = value.get("report") or {}
    accepted = report.get("internally_accepted", report.get("accepted"))
    return {"assessment_id": str(value.get("assessment_id") or "historical-review"),
        "bindings": _versions(value.get("bindings") or {}), "reported_accepted": accepted if type(accepted) is bool else None,
        "reported_status": str(report.get("status") or report.get("terminal_state") or "recorded"),
        "saved_at": str(value.get("saved_at") or _now()), "historical": True}


def _edits(value):
    result = []
    for edit in value or []:
        if not isinstance(edit, dict):
            continue
        item = {key: deepcopy(edit[key]) for key in _EDIT_FIELDS if key in edit}
        for side in ("before", "after"):
            if isinstance(edit.get(side), dict):
                # Activity details already live in the selected response; only IDs/dates belong in edit history.
                activity = edit[side].get("activity") or {}
                item[side] = {"date": edit[side].get("date"), "activity_id": activity.get("activity_id")}
        if item:
            result.append(item)
    return result


def export_snapshot(state, source_versions=None):
    """Create a minimal snapshot, excluding jobs, raw traces and reference collections."""
    app = _state()
    plan = app.current_plan(state)
    profile = deepcopy(state["profiles"].get(plan["profile_version"])) if plan else app.current_profile(state)
    if profile is None:
        raise ValueError("Save athlete information before downloading a snapshot.")
    selected = None
    if plan:
        sources = {identifier: {"catalog_id": source.get("catalog_id")}
                   for identifier, source in (plan.get("activity_sources") or {}).items()}
        selected = {"plan_version": plan["plan_version"], "parent_plan_version": plan.get("parent_plan_version"),
            "content_hash": plan["content_hash"], "profile_version": plan["profile_version"],
            "profile_planning_hash": plan["profile_planning_hash"], "response": deepcopy(plan["response"]),
            "reference_packet_id": (plan.get("reference_packet") or {}).get("packet_id"),
            "source_versions": _versions(plan.get("source_versions") or {}),
            "activity_versions": deepcopy(plan["activity_versions"]), "activity_sources": sources,
            "edits": _edits(plan.get("edits")), "saved_at": plan.get("saved_at") or _now()}
    assessments = [item for item in [_assessment(plan.get("assessment")) if plan else None]
                   + [_assessment(item) for item in state.get("assessments", [])
                      if (item.get("bindings") or {}).get("profile_version") == profile["profile_version"]] if item is not None]
    assessments = list({_canonical(item): item for item in assessments}.values())
    sessions = app.trackable_sessions(state) if plan else []
    progress = []
    for session in sessions:
        item = state.get("progress", {}).get(session["occurrence_id"])
        if item is not None and item.get("activity_revision") == session["activity_revision"]:
            item = _progress(item)
            item["plan_version"] = plan["plan_version"]
        else:
            item = {"occurrence_id": session["occurrence_id"], "activity_revision": session["activity_revision"],
                "plan_version": plan["plan_version"], "status": "pending", "updated_at": _now()}
        progress.append(item)
    history_occurrences = {item["occurrence_id"] for saved in state.get("plans", {}).values()
        if saved.get("profile_version") == profile["profile_version"] for item in saved.get("activity_versions", {}).values()}
    imported_scope = state.get("imported_progress_history_scope") or {}
    if imported_scope.get("profile_version") == profile["profile_version"]:
        history_occurrences.update(imported_scope.get("occurrence_ids") or [])
    history = [_progress(item) for item in state.get("progress_history", []) if isinstance(item, dict)
               and set(item) == set(_PROGRESS_FIELDS) and item["occurrence_id"] in history_occurrences]
    snapshot = {"schema_version": SNAPSHOT_VERSION, "application_version": APPLICATION_VERSION, "exported_at": _now(),
        "profile": {key: deepcopy(profile[key]) for key in ("profile_version", "planning_hash", "public_record", "saved_at")},
        "plan": selected, "progress": progress, "progress_history": history,
        "assessments": assessments, "application_versions": _versions(source_versions or {})}
    _validate_snapshot(snapshot)
    data = (json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise ValueError("This saved history exceeds the snapshot size limit.")
    return data


def _safe_cell(value):
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) else text


def export_schedule_csv(state):
    """Export the visible selected response with self-reported session progress."""
    app, text = _state(), io.StringIO(newline="")
    plan = app.current_plan(state)
    if plan is None:
        raise ValueError("There is no saved response to download.")
    fields = ["response_type", "date", "activity_id", "activity", "start_time", "end_time", "duration_minutes",
              "equipment", "space", "participants", "relationship", "existing_commitment_refs", "rest_arrangements", "source_refs", "progress", "message"]
    writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    response = plan["response"]
    progress = {item["activity_id"]: item["status"] for item in app.trackable_sessions(state)}
    rows = []
    if response["response_type"] != "plan":
        rows.append({"response_type": response["response_type"], "message": response.get("explanation", "")
            + " " + "; ".join(response.get("questions") or response.get("unresolved_issues") or [])})
    else:
        for day in response["weekly_schedule"]:
            if not day["activities"]:
                rows.append({"response_type": "plan", "date": day["date"], "rest_arrangements": day.get("rest_arrangements")})
            for activity in day["activities"]:
                timing, resources = activity.get("timing") or {}, activity.get("resources") or {}
                rows.append({"response_type": "plan", "date": day["date"], "activity_id": activity["activity_id"],
                    "activity": activity.get("description"), "start_time": timing.get("start_time"), "end_time": timing.get("end_time"),
                    "duration_minutes": activity.get("duration_minutes"), "equipment": _canonical(resources.get("equipment")),
                    "space": resources.get("space"), "participants": resources.get("participants"),
                    "relationship": (activity.get("relationship") or {}).get("kind"),
                    "existing_commitment_refs": "; ".join(activity.get("existing_commitment_refs") or []),
                    "rest_arrangements": day.get("rest_arrangements"), "source_refs": "; ".join(activity.get("evidence_refs") or []),
                    "progress": progress.get(activity["activity_id"], "")})
    writer.writerows({key: _safe_cell(value) for key, value in row.items()} for row in rows)
    return ("\ufeff" + text.getvalue()).encode("utf-8")


export_csv = export_schedule_csv


def _activity_map(response):
    return {activity["activity_id"]: {"date": day["date"], "activity": activity}
            for day in response.get("weekly_schedule", []) for activity in day.get("activities", [])}


def _validate_relationships(public, response):
    if response.get("response_type") != "plan":
        return
    if response.get("planning_window") != public["input"]["planning_window"]:
        raise ValueError("The imported calendar window differs from its athlete profile.")
    start = date.fromisoformat(public["input"]["planning_window"]["start_date"])
    expected = [(start + timedelta(days=index)).isoformat() for index in range(7)]
    days = response.get("weekly_schedule", [])
    if [day.get("date") for day in days] != expected:
        raise ValueError("The snapshot needs seven ordered dates in the supplied planning window.")
    entries = _activity_map(response)
    if len(entries) != sum(len(day["activities"]) for day in days):
        raise ValueError("Activity identifiers cannot be duplicated in a snapshot.")
    commitments = public["input"].get("existing_commitments") or []
    for identifier, entry in entries.items():
        activity, seen = entry["activity"], set()
        for reference in activity.get("existing_commitment_refs") or []:
            if not isinstance(reference, str) or not reference.startswith("/existing_commitments/"):
                raise ValueError("An imported commitment reference is invalid.")
            suffix = reference.rsplit("/", 1)[-1]
            if not suffix.isdigit() or suffix != str(int(suffix)) or int(suffix) >= len(commitments):
                raise ValueError("An imported commitment reference does not exist in the profile.")
        cursor = identifier
        while (entries[cursor]["activity"].get("relationship") or {}).get("kind") == "part_of_activity":
            if cursor in seen:
                raise ValueError("The imported activity relationships contain a cycle.")
            seen.add(cursor)
            parent = entries[cursor]["activity"]["relationship"].get("parent_activity_id")
            if parent not in entries or parent == cursor or entries[parent]["date"] != entries[cursor]["date"]:
                raise ValueError("An imported activity has a missing, self or cross-date parent.")
            cursor = parent


def _reconcile(response, declared_sources, resolve_catalog):
    value, sources, issues = deepcopy(response), {}, []
    activities = _activity_map(value)
    for identifier, descriptor in declared_sources.items():
        if identifier not in activities:
            raise ValueError("A source binding refers to an activity absent from the imported plan.")
        catalog_id = descriptor.get("catalog_id")
        if catalog_id is None:
            continue
        try:
            canonical = resolve_catalog(catalog_id) if callable(resolve_catalog) else None
            if (not isinstance(canonical, dict) or canonical.get("catalog_id") != catalog_id
                    or not isinstance(canonical.get("description"), str) or not canonical["description"].strip()
                    or not isinstance(canonical.get("resources"), dict) or not isinstance(canonical.get("evidence_refs"), list)):
                raise ValueError("The declared catalog record is unavailable or ineligible.")
            activity = activities[identifier]["activity"]
            activity.update(description=deepcopy(canonical["description"]), resources=deepcopy(canonical["resources"]),
                            evidence_refs=deepcopy(canonical["evidence_refs"]))
            sources[identifier] = deepcopy(canonical)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as error:
            issues.append({"activity_id": identifier, "catalog_id": catalog_id, "reason": str(error)})
    return value, sources, issues


def restore_snapshot(data, *, session_id=None, validate_profile, validate_response, resolve_catalog, check_plan, source_versions):
    """Return a new isolated state only after validation; imported reviews stay historical."""
    snapshot = _strict_json(data)
    _validate_snapshot(snapshot)
    app = _state()
    profile = deepcopy(snapshot["profile"])
    _validate(validate_profile, profile["public_record"], "profile")
    if app.content_hash(profile["public_record"]) != profile["planning_hash"]:
        raise ValueError("The imported profile hash does not match its public planning facts.")
    state = app.new_state(session_id)
    state["profiles"][profile["profile_version"]] = profile
    state["current_profile"], state["selection_epoch"] = profile["profile_version"], 1
    state["assessments"] = [{**deepcopy(item), "historical": True} for item in snapshot["assessments"]]
    state["progress_history"] = deepcopy(snapshot["progress_history"])
    state["imported_progress_history_scope"] = {"profile_version": profile["profile_version"],
        "occurrence_ids": [item["occurrence_id"] for item in snapshot["progress_history"]]}
    imported = snapshot["plan"]
    if imported is None:
        if snapshot["progress"]:
            raise ValueError("Progress cannot refer to a snapshot without a saved plan.")
        state["restore_status"] = {"historical_assessments": True, "source_issues": [], "coded_checks_recomputed": False}
        return state
    if (imported["profile_version"] != profile["profile_version"] or imported["profile_planning_hash"] != profile["planning_hash"]
            or app.planning_content_hash(imported["response"]) != imported["content_hash"]):
        raise ValueError("The imported plan is not bound to the supplied profile and planning content.")
    _validate(validate_response, imported["response"], "response")
    _validate_relationships(profile["public_record"], imported["response"])
    original_activities = _activity_map(imported["response"])
    declared = imported["activity_versions"]
    if set(declared) != set(original_activities):
        raise ValueError("Activity identity records do not match the imported calendar.")
    expected_without_sources = app.build_plan_snapshot(profile, imported["response"])["activity_versions"]
    for identifier, version in declared.items():
        if (version["activity"] != original_activities[identifier]["activity"] or version["date"] != original_activities[identifier]["date"]
                or version["occurrence_id"] != expected_without_sources[identifier]["occurrence_id"]
                or version["activity_revision"] != "activity-" + version["content_hash"][:24]):
            raise ValueError("An imported activity version disagrees with its actual date, identity or content.")
    occurrence_versions = {item["occurrence_id"]: item for item in declared.values()}
    progress_ids = set()
    for item in snapshot["progress"]:
        version = occurrence_versions.get(item["occurrence_id"])
        if (item["occurrence_id"] in progress_ids or version is None or item["plan_version"] != imported["plan_version"]
                or item["activity_revision"] != version["activity_revision"]):
            raise ValueError("A progress record refers to another activity or saved plan version.")
        progress_ids.add(item["occurrence_id"])
    declared_versions, current_versions = imported["source_versions"], _versions(source_versions)
    changed_versions = [name for name, value in declared_versions.items() if name not in current_versions or current_versions[name] != value]
    mismatches = [name for name in changed_versions if name not in _REVIEW_VERSION_KEYS]
    review_changes = [name for name in changed_versions if name in _REVIEW_VERSION_KEYS]
    working_response, authoritative, issues = _reconcile(imported["response"], imported["activity_sources"], resolve_catalog)
    _validate(validate_response, working_response, "source-resolved response")
    _validate_relationships(profile["public_record"], working_response)
    context = {"schema_version": "restored-reference-context-1", "packet_id": None,
               "imported_packet_id": imported["reference_packet_id"],
               "payload": {"references": [], "catalog_records": [], "food_lookup": []}}
    original = app.build_plan_snapshot(profile, imported["response"], context, declared_versions,
        activity_sources=deepcopy(imported["activity_sources"]), edits=imported["edits"], historical=True)
    original["plan_version"], original["parent_plan_version"], original["saved_at"] = imported["plan_version"], imported["parent_plan_version"], imported["saved_at"]
    original["historical_readonly"] = True
    original["imported_activity_versions"] = deepcopy(declared)
    original["imported_original_response"] = deepcopy(imported["response"])
    app.install_plan(state, original, select=False)
    working = app.build_plan_snapshot(profile, working_response, context, current_versions,
        parent=original, activity_sources=authoritative, edits=[{"action": "restored_and_source_resolved", "source_plan_version": imported["plan_version"]}], historical=True)
    working["historical_readonly"] = bool(mismatches or issues)
    working["imported_plan_version"] = imported["plan_version"]
    if not callable(check_plan):
        raise ValueError("Restoration needs the current coded checker; no model call is required.")
    report = check_plan(deepcopy(profile["public_record"]), deepcopy(working_response), deepcopy(context))
    if not isinstance(report, dict):
        raise ValueError("The coded checker did not return a recorded result.")
    working["check_report"], working["assessment"], working["model_review_stale"] = deepcopy(report), None, True
    app.install_plan(state, working)
    trackable = {item["activity_id"]: item for item in app.trackable_sessions(state)}
    imported_progress = {item["occurrence_id"]: item for item in snapshot["progress"]}
    for identifier, current in trackable.items():
        previous = declared.get(identifier)
        if (previous is None or previous["date"] != current["date"] or previous["activity"] != current["activity"]
                or previous["content_hash"] != current["content_hash"]):
            continue
        old = imported_progress.get(previous["occurrence_id"])
        if old:
            state["progress"][current["occurrence_id"]] = {"occurrence_id": current["occurrence_id"],
                "activity_revision": current["activity_revision"], "plan_version": working["plan_version"],
                "status": old["status"], "updated_at": old["updated_at"]}
    state["progress_history"].extend(deepcopy(snapshot["progress"]))
    state["restore_status"] = {"historical_assessments": True, "source_issues": issues,
        "unavailable_or_incompatible_versions": mismatches, "coded_checks_recomputed": True,
        "review_version_changes": review_changes,
        "source_content_changed": app.planning_content_hash(working_response) != imported["content_hash"],
        "imported_original_plan_version": original["plan_version"]}
    return state
