"""Derive request-specific structural contracts without supplying an answer."""

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json


VERSION = "request-contracts-1"
KINDS = ("plan", "clarification", "constraint_conflict", "outside_scope")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _object(value, label):
    if not isinstance(value, dict) or value.get("type") != "object" or not isinstance(value.get("properties"), dict):
        raise ValueError("The " + label + " needs its complete object schema.")
    if not isinstance(value.get("required"), list) or any(not isinstance(name, str) for name in value["required"]):
        raise ValueError("The " + label + " needs explicit required fields.")
    return value["properties"]


def _array(value, label):
    if not isinstance(value, dict):
        raise ValueError("The " + label + " is not a schema object.")
    choices = value.get("anyOf", [value])
    arrays = [item for item in choices if isinstance(item, dict) and item.get("type") == "array"]
    if len(arrays) != 1 or not isinstance(arrays[0].get("items"), dict):
        raise ValueError("The " + label + " needs exactly one complete array branch.")
    return deepcopy(arrays[0])


def _required(schema, name):
    schema["required"] = list(dict.fromkeys([*schema["required"], name]))


def _window(public):
    window = public.get("planning_window")
    if (not isinstance(window, dict) or set(window) != {"start_date", "end_date", "timezone"}
            or not isinstance(window["timezone"], str) or not window["timezone"].strip()):
        raise ValueError("The request needs its complete stated planning window.")
    try:
        start = date.fromisoformat(window["start_date"])
        end = date.fromisoformat(window["end_date"])
    except (TypeError, ValueError):
        raise ValueError("Planning dates must use YYYY-MM-DD.") from None
    if (start.isoformat() != window["start_date"] or end.isoformat() != window["end_date"]
            or end - start != timedelta(days=6)):
        raise ValueError("The request contract requires exactly seven consecutive planning dates.")
    return deepcopy(window), [(start + timedelta(days=i)).isoformat() for i in range(7)]


def _has_keyword(value, keyword):
    if isinstance(value, dict):
        return keyword in value or any(_has_keyword(item, keyword) for item in value.values())
    if isinstance(value, list):
        return any(_has_keyword(item, keyword) for item in value)
    return False


def _food_note(note_schema):
    fields = _object(note_schema, "specialist note")
    if (fields.get("contribution_status", {}).get("enum") != ["provided", "limited_information", "outside_scope"]
            or "contribution_status" not in note_schema["required"]):
        raise ValueError("The saved specialist contribution statuses changed.")
    for field in ("recommendations", "unresolved_issues"):
        if field not in note_schema["required"]:
            raise ValueError("The food note needs its original content fields.")
        _array(fields.get(field), "food-note " + field)
    branches = []
    for status in ("provided", "limited_information", "outside_scope"):
        branch = deepcopy(note_schema)
        branch["properties"]["contribution_status"] = {"const": status}
        field = "recommendations" if status == "provided" else "unresolved_issues"
        content = branch["properties"][field]
        content["minItems"] = max(1, content.get("minItems", 0))
        branches.append(branch)
    result = {"type": "object", "anyOf": branches}
    if "$schema" in note_schema:
        result["$schema"] = note_schema["$schema"]
    return result


def build_contracts(public_input, response_schema, native_schema, note_schema):
    """Constrain output presence and calendar syntax using only public request facts.

    The returned contracts supply no food value, source reference, activity choice
    or model reply. Their structural guarantees do not establish answer quality.
    """
    if not isinstance(public_input, dict):
        raise ValueError("The request contract needs the public input object.")
    window, dates = _window(public_input)
    question = public_input.get("food_question")
    if question is not None and not isinstance(question, str):
        raise ValueError("The public food question must be a string or null.")
    food_required = isinstance(question, str) and bool(question.strip())
    local, native = deepcopy(response_schema), deepcopy(native_schema)
    fields = _object(local, "local response")
    if fields.get("response_type", {}).get("enum") != list(KINDS):
        raise ValueError("The saved local response variants changed.")
    if not isinstance(native, dict) or not isinstance(native.get("anyOf"), list) or len(native["anyOf"]) != 4:
        raise ValueError("The native response needs four complete object branches.")
    if _has_keyword(native, "prefixItems"):
        raise ValueError("The native contract cannot use unsupported prefixItems.")
    branches = {}
    for branch in native["anyOf"]:
        properties = _object(branch, "native response branch")
        kind = properties.get("response_type", {}).get("const")
        if kind not in KINDS or kind in branches:
            raise ValueError("The native response variants changed or repeat.")
        branches[kind] = branch
        _array(properties.get("food_facts"), "native food facts")
    _array(fields.get("food_facts"), "local food facts")
    if food_required:
        for schema in [local, *native["anyOf"]]:
            content = _array(schema["properties"]["food_facts"], "requested food facts")
            content["minItems"] = max(1, content.get("minItems", 0))
            schema["properties"]["food_facts"] = content
            _required(schema, "food_facts")
        for branch in native["anyOf"]:
            properties = branch["properties"]
            first = ("response_type", "food_facts", "explanation", "planning_window", "weekly_schedule")
            branch["properties"] = {**{name: properties[name] for name in first if name in properties},
                **{name: value for name, value in properties.items() if name not in first}}

    # Preserve all original day constraints while fixing the local chronological slots.
    schedule = fields.get("weekly_schedule")
    if not isinstance(schedule, dict) or schedule.get("type") != "array" or not isinstance(schedule.get("items"), dict):
        raise ValueError("The local weekly schedule needs its complete day schema.")
    day_template = schedule["items"]
    day_fields = _object(day_template, "local day")
    if day_fields.get("date", {}).get("type") != "string":
        raise ValueError("The local day date schema changed.")
    conditionals = local.get("allOf")
    if not isinstance(conditionals, list):
        raise ValueError("The local response needs its saved conditional contracts.")
    plan_rules = [item.get("then") for item in conditionals if isinstance(item, dict)
        and item.get("if", {}).get("properties", {}).get("response_type", {}).get("const") == "plan"]
    if len(plan_rules) != 1 or not isinstance(plan_rules[0], dict) or not isinstance(plan_rules[0].get("properties"), dict):
        raise ValueError("The local plan condition changed.")
    plan = plan_rules[0]["properties"]
    if not isinstance(plan.get("weekly_schedule"), dict) or not isinstance(plan.get("planning_window"), dict):
        raise ValueError("The local plan needs its window and weekly schedule constraints.")
    prefix = []
    for value in dates:
        day = deepcopy(day_template)
        day["properties"]["date"]["const"] = value
        prefix.append(day)
    plan["weekly_schedule"]["prefixItems"] = prefix
    plan["planning_window"]["const"] = deepcopy(window)

    # The backend receives only supported scalar constants and day-date enums.
    # Its array grammar does not establish chronological order or unique dates.
    native_plan = branches["plan"]["properties"]
    native_window = _object(native_plan.get("planning_window"), "native plan window")
    for name, value in window.items():
        if not isinstance(native_window.get(name), dict):
            raise ValueError("The native planning window fields changed.")
        native_window[name]["const"] = value
    native_days = native_plan.get("weekly_schedule", {}).get("items")
    if not isinstance(native_days, dict) or not isinstance(native_days.get("anyOf"), list) or len(native_days["anyOf"]) != 2:
        raise ValueError("The native calendar needs its rest and active day branches.")
    for day in native_days["anyOf"]:
        day_fields = _object(day, "native calendar day")
        if not isinstance(day_fields.get("date"), dict) or day_fields["date"].get("type") != "string":
            raise ValueError("The native calendar day date schema changed.")
        day_fields["date"]["enum"] = deepcopy(dates)
    food_note = _food_note(deepcopy(note_schema))
    policy = {"version": VERSION, "food_question_present": food_required,
        "food_answer_presence_required": food_required, "honest_unknown_food_statement_allowed": True,
        "food_value_or_reference_injected": False, "lookup_truth_read": False,
        "food_note_provided_requires_content": True, "food_note_unavailable_requires_specific_issue": True,
        "native_calendar_constraint": "exact_window_scalars_and_allowed_day_date_enum_only",
        "native_chronology_or_unique_dates_guaranteed": False, "native_prefix_items_used": False,
        "local_calendar_constraint": "seven_original_day_schemas_in_exact_chronological_positions",
        "structural_presence_is_numeric_or_activity_correctness": False, "final_approval": False,
        "planning_window_sha256": sha(window), "local_response_schema_sha256": sha(local),
        "native_response_schema_sha256": sha(native), "food_note_schema_sha256": sha(food_note)}
    return {"local_response_schema": local, "native_response_schema": native,
        "food_note_schema": food_note, "policy": policy}
