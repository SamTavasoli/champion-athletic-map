"""Parse candidate planner responses without repairing model-produced values.

Structural validity does not establish plan accuracy, completeness, feasibility,
resource eligibility, rule compliance, or suitability for an athlete.
"""

import json
from datetime import date, timedelta

from jsonschema import Draft202012Validator, FormatChecker


def _text():
    return {"type": "string", "minLength": 1, "pattern": r"\S"}


def _nullable(value):
    return {"anyOf": [value, {"type": "null"}]}


def _strings():
    return {"type": "array", "items": _text()}


def build_response_schema():
    """Return a fresh candidate schema; it supplies no defaults or corrections."""
    timing = {"type": "object", "additionalProperties": False,
              "properties": {key: _nullable({"type": "string", "pattern": r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"})
                             for key in ("start_time", "end_time")}}
    relationship = {
        "type": "object", "additionalProperties": False,
        "required": ["kind", "parent_activity_id"],
        "properties": {"kind": {"enum": ["separate_session", "part_of_activity"]},
                       "parent_activity_id": _nullable(_text())},
        "allOf": [
            {"if": {"properties": {"kind": {"const": "part_of_activity"}}},
             "then": {"properties": {"parent_activity_id": _text()}},
             "else": {"properties": {"parent_activity_id": {"type": "null"}}}},
        ],
    }
    equipment = {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["name", "quantity"],
        "properties": {"name": _text(), "quantity": _nullable({"type": "integer", "minimum": 0})}}}
    resources = {"type": "object", "additionalProperties": False,
                 "required": ["equipment", "space", "participants"],
                 "properties": {"equipment": _nullable(equipment), "space": _nullable(_text()),
                                "participants": _nullable({"type": "integer", "minimum": 1})}}
    activity = {
        "type": "object", "additionalProperties": False,
        "required": ["activity_id", "description", "duration_minutes", "resources", "relationship"],
        "properties": {
            "activity_id": _text(), "description": _text(),
            "duration_minutes": _nullable({"type": "integer", "minimum": 0}),
            "resources": resources, "relationship": relationship, "timing": _nullable(timing),
            "existing_commitment_refs": {"type": "array", "items": {"type": "string", "pattern": r"^/existing_commitments/(0|[1-9][0-9]*)$"}},
            "evidence_refs": _nullable(_strings()),
        },
    }
    day = {
        "type": "object", "additionalProperties": False,
        "required": ["date", "activities", "rest_arrangements"],
        "properties": {"date": {"type": "string", "format": "date"},
                       "activities": {"type": "array", "items": activity},
                       "rest_arrangements": _nullable(_text())},
        "allOf": [{"if": {"properties": {"activities": {"maxItems": 0}}},
                   "then": {"properties": {"rest_arrangements": _text()}}}],
    }
    window = {"type": "object", "additionalProperties": False,
              "required": ["start_date", "end_date", "timezone"],
              "properties": {"start_date": {"type": "string", "format": "date"},
                             "end_date": {"type": "string", "format": "date"}, "timezone": _text()}}
    food_fact = {"type": "object", "additionalProperties": False, "required": ["statement"],
                 "properties": {"statement": _text(), "food_id": _nullable(_text()), "source_ref": _nullable(_text())}}
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:champion-athletic-map:planner-response-candidate:1",
        "title": "Shared planner response candidate",
        "description": "Structural validation only; no factual, feasibility, eligibility or rule-compliance guarantee.",
        "type": "object", "additionalProperties": False,
        "required": ["response_type", "explanation"],
        "properties": {
            "response_type": {"enum": ["plan", "clarification", "constraint_conflict", "outside_scope"]},
            "explanation": _text(), "planning_window": _nullable(window),
            "weekly_schedule": {"type": "array", "maxItems": 7, "items": day},
            "questions": _strings(), "unresolved_issues": _strings(), "evidence_refs": _nullable(_strings()),
            "food_facts": _nullable({"type": "array", "items": food_fact}),
        },
        "allOf": [
            {"if": {"properties": {"response_type": {"const": "plan"}}},
             "then": {"required": ["planning_window", "weekly_schedule"],
                      "properties": {"planning_window": {"type": "object"}, "weekly_schedule": {"minItems": 7, "maxItems": 7}}},
             "else": {"properties": {"weekly_schedule": {"maxItems": 0}}}},
            {"if": {"properties": {"response_type": {"const": "clarification"}}},
             "then": {"required": ["questions"], "properties": {"questions": {"minItems": 1}}}},
            {"if": {"properties": {"response_type": {"const": "constraint_conflict"}}},
             "then": {"required": ["unresolved_issues"], "properties": {"unresolved_issues": {"minItems": 1}}}},
        ],
    }
    Draft202012Validator.check_schema(schema)
    return schema


def _pointer(parts):
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _structure_issues(parsed):
    """Check date and identifier structure, without evaluating training content."""
    if parsed.get("response_type") != "plan":
        return []
    issues = []
    window = parsed["planning_window"]
    start, end = date.fromisoformat(window["start_date"]), date.fromisoformat(window["end_date"])
    days = parsed["weekly_schedule"]
    expected_dates = [(start + timedelta(days=index)).isoformat() for index in range(7)]
    actual_dates = [day["date"] for day in days]
    if end != start + timedelta(days=6):
        issues.append({"path": "/planning_window", "code": "window_not_seven_days", "message": "The planning window must span exactly seven consecutive dates."})
    if actual_dates != expected_dates:
        issues.append({"path": "/weekly_schedule", "code": "schedule_dates_do_not_match_window", "message": "Day records must contain each planning-window date once, in chronological order."})
    activities = [(day_index, activity_index, activity)
                  for day_index, day in enumerate(days) for activity_index, activity in enumerate(day["activities"])]
    ids = [activity["activity_id"] for _, _, activity in activities]
    known = set(ids)
    seen = set()
    for day_index, activity_index, activity in activities:
        path = _pointer(["weekly_schedule", day_index, "activities", activity_index])
        activity_id = activity["activity_id"]
        if activity_id in seen:
            issues.append({"path": path + "/activity_id", "code": "duplicate_activity_id", "message": "Activity identifiers must be unique within the response."})
        seen.add(activity_id)
        relationship = activity["relationship"]
        if relationship["kind"] == "part_of_activity":
            parent = relationship["parent_activity_id"]
            if parent == activity_id:
                issues.append({"path": path + "/relationship/parent_activity_id", "code": "self_parent_activity", "message": "An activity cannot identify itself as its parent."})
            elif parent not in known:
                issues.append({"path": path + "/relationship/parent_activity_id", "code": "unknown_parent_activity", "message": "The referenced parent activity identifier is absent from this response."})
    return issues


def parse_response_text(raw_text, schema=None):
    """Preserve raw and parsed data and validate; never repair or regenerate it."""
    result = {"parse_valid": False, "parsed_object": None, "error_code": None, "issues": [], "raw_text": raw_text}
    if type(raw_text) not in (str, bytes):
        result["error_code"] = "invalid_text_type"
        return result
    try:
        text = raw_text.decode("utf-8", errors="strict") if type(raw_text) is bytes else raw_text
        text.encode("utf-8", errors="strict")
    except UnicodeError:
        result["error_code"] = "invalid_utf8"
        return result

    def unique(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise ValueError("duplicate_json_key")
            data[key] = value
        return data

    def nonfinite(value):
        raise ValueError("nonfinite_json_number")

    try:
        parsed = json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
        json.dumps(parsed, allow_nan=False, ensure_ascii=False).encode("utf-8", errors="strict")
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as error:
        result["error_code"] = "invalid_json"
        result["issues"] = [{"path": "", "code": type(error).__name__, "message": "The response is not strict UTF-8 JSON with unique keys and finite numbers."}]
        return result
    result["parsed_object"] = parsed
    candidate = build_response_schema() if schema is None else schema
    try:
        Draft202012Validator.check_schema(candidate)
    except Exception:
        result["error_code"] = "invalid_response_schema"
        return result
    validator = Draft202012Validator(candidate, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(parsed), key=lambda error: (_pointer(error.absolute_path), error.validator))
    if errors:
        result["error_code"] = "schema_validation_failed"
        result["issues"] = [{"path": _pointer(error.absolute_path), "code": str(error.validator), "message": error.message[:240]} for error in errors[:64]]
        return result
    try:
        structural = (_structure_issues(parsed) if type(parsed) is dict else
                      [{"path": "", "code": "invalid_structure", "message": "A shared planner response must remain an object."}])
    except (ValueError, TypeError, KeyError, OverflowError):
        structural = [{"path": "", "code": "invalid_structure", "message": "Response structure could not be checked under the shared contract."}]
    if structural:
        result["error_code"] = "structure_validation_failed"
        result["issues"] = structural[:64]
        return result
    result["parse_valid"] = True
    return result
