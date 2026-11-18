"""Lossless calendar tables for quoted candidate input, never final responses."""

from copy import deepcopy
import json


ENCODING_VERSION = "candidate-calendar-table-1"
ENCODING_NOTICE = (
    "Tables use columns and indexed shared values."
)
DECODING_NOTICE = ENCODING_NOTICE


def encode_candidate_view(view):
    """Use a reversible layout only for a recognized parsed calendar structure."""
    source = deepcopy(view)
    if (type(view) is not dict or set(view) != {"candidate_id", "parsed_object", "format_valid"}
            or type(view["parsed_object"]) is not dict):
        return source
    answer = view["parsed_object"]
    days = answer.get("weekly_schedule")
    if (type(days) is not list or not days
            or any(type(day) is not dict or set(day) != {"date", "activities", "rest_arrangements"}
                   or type(day["activities"]) is not list
                   or any(type(activity) is not dict for activity in day["activities"])
                   for day in days)):
        return source
    activities = [deepcopy(activity) for day in days for activity in day["activities"]]
    uniform = bool(activities) and all(set(activity) == set(activities[0]) for activity in activities)
    body = {"fields": {key: deepcopy(value) for key, value in answer.items() if key != "weekly_schedule"},
            "day_columns": ["date", "activities", "rest"],
            "days": [], "rest": []}
    if uniform:
        body["columns"] = list(activities[0])
        body["activities"] = [[deepcopy(activity[key]) for key in body["columns"]] for activity in activities]
        shared = {}
        for key in ("resources", "relationship", "timing"):
            if key not in body["columns"]:
                continue
            position = body["columns"].index(key)
            unique, indexes, seen = [], [], {}
            for row in body["activities"]:
                value = row[position]
                identity = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                if identity not in seen:
                    seen[identity] = len(unique)
                    unique.append(deepcopy(value))
                indexes.append(seen[identity])
            if len(unique) < len(activities):
                shared[key] = unique
                for row, index in zip(body["activities"], indexes):
                    row[position] = index
        if shared:
            body["shared"] = shared
    else:
        body["objects"] = activities
    offset = 0
    for day in days:
        rest = deepcopy(day["rest_arrangements"])
        # Equality alone would merge False with 0; compare both type and value.
        index = next((i for i, value in enumerate(body["rest"])
                      if type(value) is type(rest) and value == rest), None)
        if index is None:
            index = len(body["rest"])
            body["rest"].append(rest)
        length = len(day["activities"])
        body["days"].append([deepcopy(day["date"]), list(range(offset, offset + length)), index])
        offset += length
    return {"candidate_id": view["candidate_id"], "format_valid": view["format_valid"], "calendar_table": body}


def decode_candidate_view(view):
    """Reconstruct every original field, including absence and literal nulls."""
    if type(view) is not dict or "calendar_table" not in view:
        return deepcopy(view)
    if set(view) != {"candidate_id", "format_valid", "calendar_table"}:
        raise ValueError("Unrecognized encoded candidate fields.")
    body = view["calendar_table"]
    if type(body) is not dict or body.get("day_columns") != ["date", "activities", "rest"]:
        raise ValueError("Unrecognized calendar encoding.")
    if "columns" in body:
        columns = body["columns"]
        if len(columns) != len(set(columns)) or any(len(row) != len(columns) for row in body["activities"]):
            raise ValueError("Activity table columns do not match their complete rows.")
        activities = [dict(zip(columns, deepcopy(row))) for row in body["activities"]]
        for activity in activities:
            for key, values in body.get("shared", {}).items():
                activity[key] = deepcopy(values[activity[key]])
    else:
        activities = deepcopy(body["objects"])
    answer = deepcopy(body["fields"])
    answer["weekly_schedule"] = [{"date": deepcopy(day), "activities": [deepcopy(activities[index]) for index in indexes],
                                  "rest_arrangements": deepcopy(body["rest"][rest])}
                                 for day, indexes, rest in body["days"]]
    return {"candidate_id": view["candidate_id"], "format_valid": view["format_valid"], "parsed_object": answer}


encode_candidate = encode_candidate_view
decode_candidate = decode_candidate_view
