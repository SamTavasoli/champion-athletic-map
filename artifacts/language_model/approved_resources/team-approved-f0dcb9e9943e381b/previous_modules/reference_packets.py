"""Prepare one public reference packet shared by reference-supported planners."""

import hashlib
import json
from copy import deepcopy


POLICY_VERSION = "shared-reference-packet-policy-1"
_LIMITATION = "Some ranked references were omitted as complete units to fit the packet budget."
_TOOL_FIELDS = ("status", "data", "issues", "source_refs", "data_version")
_FOOD_ARGUMENTS = {"food_id", "search_text", "grams", "portion_id", "multiplier"}


def _json(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    text.encode("utf-8", errors="strict")
    return text


def _sha(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _public(prepared):
    if type(prepared) is not dict or prepared.get("schema_version") != "step24-prepared-public-input-1":
        raise ValueError("Expected a prepared public input")
    public = prepared["public_input"]
    if (type(public) is not dict or _sha(public) != prepared["audit"]["public_input_sha256"]
            or _json(public) != prepared["model_visible_json"]):
        raise ValueError("Prepared public facts changed")
    return public


def _tool_result(result):
    if type(result) is not dict or any(key not in result for key in _TOOL_FIELDS):
        raise ValueError("Invalid reference tool result")
    return deepcopy({key: result[key] for key in _TOOL_FIELDS})


def _tokens(payload, count_tokens):
    count = count_tokens(_json(payload))
    if type(count) is not int or count < 0:
        raise ValueError("Token counter must return a nonnegative integer")
    return count


def _complete_reference(item):
    record = item["required_delivery_record"]
    key = "display_text" if "display_text" in record else "complete_display_text"
    text = item["complete_required_delivery_text"]
    if (type(text) is not str or not text or text != record.get(key)
            or hashlib.sha256(text.encode("utf-8")).hexdigest() != record.get(key + "_sha256")):
        raise ValueError("A reference lost its complete required source context")
    return {"reference_unit_id": item["reference_unit_id"], "passage_id": item["passage_id"],
            "complete_required_delivery_text": text}


def _food_arguments(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate food argument")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite food argument")))
    except (ValueError, TypeError):
        return None


def build_reference_packet(prepared, tools, count_tokens, max_packet_tokens=2200):
    """Select whole ranked units; token limit is provisional, not a full-chat budget."""
    if type(max_packet_tokens) is not int or max_packet_tokens < 1:
        raise ValueError("Packet token limit must be a positive integer")
    public = _public(prepared)
    query = public["athlete_request"]
    goals = public.get("goals")
    if type(goals) is list and all(type(goal) is str for goal in goals) and goals:
        query += "\nGoals: " + "; ".join(goals)
    payload = {
        "references": [],
        "planning_rules": _tool_result(tools.get_planning_rules(public.get("age"), public.get("school_grade"))),
        "catalog_availability": {"selected_drill_lookup": "awaiting_approval",
                                 "selected_development_exercise_lookup": "awaiting_approval"},
        "context_limitations": ["Retrieval ranking alone does not establish answerability."],
    }
    question = public.get("food_question")
    food_mode = "not_requested"
    if type(question) is str and question.strip():
        arguments = _food_arguments(question)
        if type(arguments) is dict and arguments and set(arguments).issubset(_FOOD_ARGUMENTS):
            food = tools.lookup_food(**arguments)
            food_mode = "explicit_public_json_arguments"
        else:
            food = tools.lookup_food(search_text=question)
            food_mode = "description_search_only"
            payload["context_limitations"].append("Food text was searched as a description; natural-language quantities were not inferred.")
        payload["food_lookup"] = _tool_result(food)
        if food["status"] != "found":
            payload["context_limitations"].append("The requested food facts remain unresolved; preserve the lookup status.")
    if _tokens(payload, count_tokens) > max_packet_tokens:
        raise ValueError("Required rule and food context exceeds the packet budget; nothing was removed")

    # One query serves all three reference-supported versions.
    retrieval = tools.search_references(query)
    if type(retrieval) is not dict:
        raise ValueError("Invalid retrieval result")
    if retrieval.get("status") != "found":
        payload["context_limitations"].append("Reference search returned " + str(retrieval.get("status")) + "; no retrieved evidence is available.")
    items = (retrieval.get("data") or {}).get("references", [])
    if type(items) is not list or len(items) > 5:
        raise ValueError("Expected at most five ranked reference units")
    omissions, seen = [], set()
    for item in items:
        reference = _complete_reference(item)
        unit_id = reference["reference_unit_id"]
        if unit_id in seen:
            raise ValueError("Duplicate reference unit in the ranked result")
        seen.add(unit_id)
        trial = deepcopy(payload)
        trial["references"].append(reference)
        # Reserve the omission notice while testing each complete unit.
        if _LIMITATION not in trial["context_limitations"]:
            trial["context_limitations"].append(_LIMITATION)
        if _tokens(trial, count_tokens) <= max_packet_tokens:
            payload["references"].append(reference)
        else:
            omissions.append({"reference_unit_id": unit_id, "reason": "complete_unit_exceeds_packet_budget"})
    if omissions:
        payload["context_limitations"].append(_LIMITATION)
    count = _tokens(payload, count_tokens)
    if count > max_packet_tokens:
        raise ValueError("Required packet context exceeds its budget; nothing was truncated")
    packet = {
        "schema_version": "shared-reference-packet-1",
        "public_input_sha256": prepared["audit"]["public_input_sha256"],
        "payload": payload,
        "preparation": {"policy_version": POLICY_VERSION, "query": query, "retrieval_method": "semantic",
                        "retrieval_status": retrieval.get("status"), "retrieval_data_version": retrieval.get("data_version"),
                        "selected_reference_ids": [row["reference_unit_id"] for row in payload["references"]],
                        "omitted_references": omissions, "food_lookup_mode": food_mode,
                        "packet_text_tokens": count, "max_packet_tokens": max_packet_tokens,
                        "full_prompt_budget_verified": False},
    }
    packet["packet_id"] = "reference-packet:" + _sha(packet)
    return packet


def model_input_for_version(prepared, version, packet=None):
    """Build matched public inputs and enforce the reference-access boundary."""
    public = _public(prepared)
    if type(version) is not int or version not in (1, 2, 3, 4):
        raise ValueError("Planner version must be 1, 2, 3 or 4")
    result = {"athlete_input": deepcopy(public)}
    if version == 1:
        if packet is not None:
            raise ValueError("Version 1 cannot receive a reference packet")
        return result
    if (type(packet) is not dict or packet.get("schema_version") != "shared-reference-packet-1"
            or packet.get("public_input_sha256") != prepared["audit"]["public_input_sha256"]):
        raise ValueError("Reference packet is missing or belongs to different public facts")
    body = {key: value for key, value in packet.items() if key != "packet_id"}
    if packet.get("packet_id") != "reference-packet:" + _sha(body):
        raise ValueError("Reference packet changed after preparation")
    result["reference_data"] = deepcopy(packet["payload"])
    return result
