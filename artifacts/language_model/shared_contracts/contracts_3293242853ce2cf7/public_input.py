"""Keep public athlete facts and generated text in separate, traceable records.

Only the validated input object is model-visible. Wrapper identifiers stay in
audit metadata. This component neither accepts study cases nor checks whether
a plan is substantively correct.
"""

import hashlib
import json
import math

from jsonschema import Draft202012Validator, FormatChecker


def _native_json(value, depth=0):
    if depth > 128:
        raise ValueError("JSON nesting exceeds the application limit")
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ValueError("JSON object keys must be strings")
        for item in value.values():
            _native_json(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _native_json(item, depth + 1)
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
    elif type(value) not in (str, int, bool, type(None)):
        raise ValueError("Only native JSON values are accepted")


def canonical_json(value):
    _native_json(value)
    text = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)
    text.encode("utf-8", errors="strict")
    return text


def _clone(value):
    return json.loads(canonical_json(value))


def prepare_public_input(record, public_record_schema):
    """Validate the unchanged public record schema and project input only.

    Unknown fields are rejected rather than scrubbed. Missing, null, empty,
    zero, false, conflicting details and supplied string values stay distinct.
    Allowed free text still requires author review for private information.
    """
    saved_record = _clone(record)
    schema = _clone(public_record_schema)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(saved_record), key=lambda error: repr(list(error.absolute_path)))
    if errors:
        first = errors[0]
        # We report the field path and rule without echoing private field values.
        raise ValueError("Public input schema rejected a field at " + repr(list(first.absolute_path))
                         + " (" + str(first.validator) + ")")
    if type(saved_record) is not dict or set(saved_record) != {"profile_id", "schema_version", "input"}:
        raise ValueError("Expected only the public record wrapper")
    public = _clone(saved_record["input"])
    public_text = canonical_json(public)
    return {
        "schema_version": "step24-prepared-public-input-1",
        "audit": {"profile_id": saved_record["profile_id"], "profile_schema_version": saved_record["schema_version"],
                  "public_input_sha256": hashlib.sha256(public_text.encode("utf-8")).hexdigest()},
        "public_input": public,
        "model_visible_json": public_text,
    }


def verify_prepared_input(prepared):
    """Check the application snapshot before using it or archiving a response."""
    if (type(prepared) is not dict or set(prepared) != {"schema_version", "audit", "public_input", "model_visible_json"}
            or prepared.get("schema_version") != "step24-prepared-public-input-1"):
        raise ValueError("Invalid prepared input envelope")
    audit = prepared["audit"]
    if type(audit) is not dict or set(audit) != {"profile_id", "profile_schema_version", "public_input_sha256"}:
        raise ValueError("Invalid input audit envelope")
    public_text = canonical_json(prepared["public_input"])
    if (prepared["model_visible_json"] != public_text
            or audit["public_input_sha256"] != hashlib.sha256(public_text.encode("utf-8")).hexdigest()):
        raise ValueError("Prepared public facts changed after projection")
    return True


def _strict_value(text):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON key")
            value[key] = item
        return value
    def reject(value):
        raise ValueError("Nonfinite JSON constant")
    value = json.loads(text, object_pairs_hook=unique, parse_constant=reject)
    canonical_json(value)
    return value


def preserve_response_record(prepared, parsed_response):
    """Attach the original input beside a response, never merge or repair it."""
    verify_prepared_input(prepared)
    if type(parsed_response) is not dict or type(parsed_response.get("raw_text")) is not str:
        raise ValueError("Expected a parser result retaining the raw response text")
    raw_text = parsed_response["raw_text"]
    raw_text.encode("utf-8", errors="strict")
    if type(parsed_response.get("parse_valid")) is not bool:
        raise ValueError("Expected an explicit structural parsing status")
    try:
        actual_object = _strict_value(raw_text)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        if parsed_response["parse_valid"] or parsed_response.get("parsed_object") is not None:
            raise ValueError("Invalid JSON was replaced by a parsed or repaired object") from None
    else:
        if canonical_json(actual_object) != canonical_json(parsed_response.get("parsed_object")):
            raise ValueError("Parsed object differs from the original model text")
    return {
        "schema_version": "step24-source-and-response-record-1",
        "audit": {**_clone(prepared["audit"]), "raw_response_utf8_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest()},
        "authoritative_public_input": _clone(prepared["public_input"]),
        "model_output": _clone(parsed_response),
        "semantic_correctness_verified": False,
        "input_authority": "supplied_public_input_only",
    }
