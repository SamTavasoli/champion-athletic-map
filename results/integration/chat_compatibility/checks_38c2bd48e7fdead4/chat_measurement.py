"""Inspect saved chat responses without repairing or regenerating their content.

Usage agreement applies only to the measured fixtures and installed runtime.
The reported prompt count already includes cache reuse; we never add it twice.
"""

import json


def decode_json_object(raw):
    """Decode one strict JSON object, rejecting duplicate keys and nonfinite values."""
    if type(raw) is bytes:
        raw = raw.decode("utf-8", errors="strict")
    if type(raw) is not str:
        raise TypeError("JSON input must be UTF-8 bytes or text")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("Nonfinite JSON constant")

    result = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
    if type(result) is not dict:
        raise ValueError("JSON root must be an object")
    # JSON numeric exponents can overflow float conversion without parse_constant.
    canonical = json.dumps(result, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    canonical.encode("utf-8", errors="strict")
    return result


def _canonical(value):
    return json.dumps(value, allow_nan=False, ensure_ascii=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8", errors="strict")


def inspect_response(response, expected_object, model="llama3.1:8b", output_limit=2048,
                     rendered_body_tokens=None):
    """Return diagnostics for a backend response; malformed output remains an outcome."""
    result = {
        "schema_version": "step24-chat-response-measurement-1",
        "completed_model_response": False, "json_object_valid": False,
        "fixture_exact_match": False, "done_reason": None,
        "input_count": None, "cached_count": None, "output_count": None,
        "observed_input_offset": None, "offset_classification": "unavailable",
        "within_boundary_reserve": False, "metrics_valid": False,
        "acceptable_response": False, "json_error_type": None, "issues": [],
        "prompt_count_includes_cached_tokens": True,
        "operational_generation_ready": False,
    }
    issues = result["issues"]
    if type(response) is not dict:
        issues.append("response_is_not_an_object")
        return result

    envelope_issues = []
    if type(response.get("model")) is not str or response["model"] != model:
        envelope_issues.append("response_model_mismatch")
    if any(response.get(key) not in (None, "") for key in ("remote_host", "remote_model")):
        envelope_issues.append("remote_response_metadata_present")
    if response.get("error") not in (None, ""):
        envelope_issues.append("backend_error_present")
    if response.get("done") is not True:
        envelope_issues.append("response_not_completed")
    if any(response.get(key) is not None for key in ("_debug_info", "debug_info")):
        envelope_issues.append("debug_response_instead_of_generation")
    for key in ("images", "media"):
        if response.get(key) not in (None, []):
            envelope_issues.append("unexpected_response_" + key)
    message = response.get("message")
    content = None
    if type(message) is not dict:
        envelope_issues.append("message_is_not_an_object")
    else:
        if message.get("role") != "assistant":
            envelope_issues.append("unexpected_message_role")
        if type(message.get("content")) is not str:
            envelope_issues.append("message_content_is_not_text")
        else:
            content = message["content"]
        if message.get("thinking") not in (None, ""):
            envelope_issues.append("unexpected_thinking_content")
        for key in ("tool_calls", "images", "media"):
            if message.get(key) not in (None, []):
                envelope_issues.append("unexpected_message_" + key)
    issues.extend(envelope_issues)
    result["completed_model_response"] = not envelope_issues
    reason = response.get("done_reason")
    result["done_reason"] = reason if type(reason) is str else None
    if reason != "stop":
        issues.append("completion_reason_is_not_stop")

    if content is not None:
        try:
            parsed = decode_json_object(content)
            result["json_object_valid"] = True
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as error:
            result["json_error_type"] = type(error).__name__
            issues.append("invalid_json_object")
        else:
            try:
                expected_valid = type(expected_object) is dict
                result["fixture_exact_match"] = expected_valid and _canonical(parsed) == _canonical(expected_object)
            except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
                result["fixture_exact_match"] = False
            if not result["fixture_exact_match"]:
                issues.append("fixture_value_or_type_mismatch")

    prompt = response.get("prompt_eval_count")
    cached = response.get("prompt_eval_cached_count")
    output = response.get("eval_count")
    for name, value in (("input_count", prompt), ("cached_count", cached), ("output_count", output)):
        result[name] = value if type(value) is int else None
    prompt_valid = type(prompt) is int and prompt > 0
    output_valid = (type(output_limit) is int and output_limit > 0
                    and type(output) is int and 0 < output <= output_limit)
    cache_valid = cached is None or (prompt_valid and type(cached) is int and 0 <= cached <= prompt)
    if not prompt_valid:
        issues.append("prompt_count_unavailable_or_invalid")
    if not output_valid:
        issues.append("output_count_unavailable_or_invalid")
    if not cache_valid:
        issues.append("cached_count_invalid")
    result["metrics_valid"] = bool(prompt_valid and output_valid and cache_valid)
    if prompt_valid and type(rendered_body_tokens) is int and rendered_body_tokens >= 0:
        offset = prompt - rendered_body_tokens
        result["observed_input_offset"] = offset
        result["within_boundary_reserve"] = 0 <= offset <= 2
        result["offset_classification"] = ("within_boundary_reserve" if 0 <= offset <= 2
                                             else "outside_boundary_reserve")
        if not result["within_boundary_reserve"]:
            issues.append("observed_input_offset_outside_boundary_reserve")
    elif type(rendered_body_tokens) is not int or rendered_body_tokens < 0:
        issues.append("rendered_body_count_unavailable_or_invalid")
    result["acceptable_response"] = bool(
        result["completed_model_response"] and reason == "stop"
        and result["json_object_valid"] and result["fixture_exact_match"]
        and result["metrics_valid"])
    return result


def aggregate_measurements(measurements):
    """Report fixture-scoped agreement without adopting operational settings."""
    rows = measurements if type(measurements) is list else []
    valid_rows = bool(rows) and all(type(row) is dict for row in rows)
    metrics_valid = valid_rows and all(row.get("metrics_valid") is True for row in rows)
    completed = valid_rows and all(row.get("completed_model_response") is True for row in rows)
    offsets = [row.get("observed_input_offset") for row in rows] if valid_rows else []
    fixed_offset = (offsets[0] if offsets and all(type(value) is int and value == offsets[0]
                                                and 0 <= value <= 2 for value in offsets) else None)
    agreement = bool(len(rows) >= 3 and metrics_valid and completed and fixed_offset is not None)
    compatibility = bool(valid_rows and all(row.get("acceptable_response") is True for row in rows))
    return {
        "schema_version": "step24-chat-measurement-aggregate-1",
        "fixture_count": len(rows), "all_metrics_valid": bool(metrics_valid),
        "all_completed_model_responses": bool(completed),
        "observed_input_offsets": offsets,
        "fixed_observed_input_offset": fixed_offset,
        "backend_count_agreement_for_saved_fixtures": agreement,
        "json_generation_compatible_for_saved_fixtures": compatibility,
        "measurement_scope": "saved_software_fixtures_only_not_arbitrary_prompts_or_capacity",
        "observed_offset_interpreted_as_bos_policy": False,
        "operational_generation_ready": False,
    }
