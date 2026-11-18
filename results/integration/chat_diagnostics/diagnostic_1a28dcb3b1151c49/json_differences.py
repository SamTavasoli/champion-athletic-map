"""Describe exact differences in already-decoded JSON without changing values."""

import hashlib
import json
import unicodedata


_MISSING = object()
_PREVIEW_LIMIT = 240
_MAX_DEPTH = 20
_MAX_VISITED_NODES = 10000
_NFC_LENGTH_LIMIT = 4096


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8", errors="strict")


def _type_name(value):
    if value is _MISSING:
        return "missing"
    return {type(None): "null", bool: "boolean", int: "integer", float: "number",
            str: "string", list: "array", dict: "object"}.get(type(value), type(value).__name__)


def _preview(value):
    shown = "<missing>" if value is _MISSING else value
    text = json.dumps(shown, ensure_ascii=True, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))
    truncated = len(text) > _PREVIEW_LIMIT
    return (text[:_PREVIEW_LIMIT - 3] + "..." if truncated else text), truncated


def _pointer(parent, part):
    escaped = str(part).replace("~", "~0").replace("/", "~1")
    return parent + "/" + escaped


def _codepoint_window(text, index):
    start = max(0, index - 8)
    stop = min(len(text), index + 9)
    return [{"index": position, "codepoint": "U+" + format(ord(text[position]), "04X"),
             "name": unicodedata.name(text[position], "UNNAMED"),
             "escaped_character": json.dumps(text[position], ensure_ascii=True)}
            for position in range(start, stop)]


def _string_details(expected, actual):
    first = min(len(expected), len(actual))
    for index, (left, right) in enumerate(zip(expected, actual)):
        if left != right:
            first = index
            break
    expected_bytes = expected.encode("utf-8", errors="strict")
    actual_bytes = actual.encode("utf-8", errors="strict")
    compare_nfc = max(len(expected), len(actual)) <= _NFC_LENGTH_LIMIT
    return {
        "expected_codepoint_length": len(expected), "actual_codepoint_length": len(actual),
        "expected_utf8_length": len(expected_bytes), "actual_utf8_length": len(actual_bytes),
        "expected_utf8_sha256": hashlib.sha256(expected_bytes).hexdigest(),
        "actual_utf8_sha256": hashlib.sha256(actual_bytes).hexdigest(),
        "first_differing_codepoint_index": first,
        "expected_window": _codepoint_window(expected, first),
        "actual_window": _codepoint_window(actual, first),
        "nfc_equivalent": (unicodedata.normalize("NFC", expected) == unicodedata.normalize("NFC", actual)
                           if compare_nfc else None),
        "nfc_comparison_status": "compared_without_modifying_values" if compare_nfc else "skipped_length_limit",
        "normalization_performed": False,
    }


def compare_json(expected, actual, max_differences=32):
    """Compare exact parsed values and produce a bounded diagnostic report.

    Exact matching follows canonical UTF-8 JSON serialization, consistent with
    the saved fixture check. Traversal and preview limits affect diagnostics
    only; they never turn a mismatch into a match.
    """
    if type(max_differences) is not int or not 1 <= max_differences <= 32:
        raise ValueError("max_differences must be an integer from 1 through 32")
    exact = _canonical(expected) == _canonical(actual)
    result = {"exact_match": exact, "differences": [], "diagnostic_truncated": False}
    if exact:
        return result
    visited = 0

    def add(path, kind, left, right):
        if len(result["differences"]) >= max_differences:
            result["diagnostic_truncated"] = True
            return False
        left_preview, left_truncated = _preview(left)
        right_preview, right_truncated = _preview(right)
        row = {"path": path, "kind": kind, "expected_type": _type_name(left), "actual_type": _type_name(right),
               "expected_preview": left_preview, "actual_preview": right_preview,
               "expected_preview_truncated": left_truncated, "actual_preview_truncated": right_truncated}
        if type(left) is str and type(right) is str:
            row["string_details"] = _string_details(left, right)
        result["differences"].append(row)
        if left_truncated or right_truncated:
            result["diagnostic_truncated"] = True
        return True

    def walk(left, right, path, depth):
        nonlocal visited
        visited += 1
        if visited > _MAX_VISITED_NODES:
            result["diagnostic_truncated"] = True
            return
        if type(left) is not type(right):
            add(path, "type_mismatch", left, right)
            return
        if depth > _MAX_DEPTH:
            if _canonical(left) == _canonical(right):
                return
            result["diagnostic_truncated"] = True
            add(path, "depth_limit", left, right)
            return
        if type(left) is dict:
            for key in sorted(left.keys() | right.keys()):
                if len(result["differences"]) >= max_differences or visited >= _MAX_VISITED_NODES:
                    result["diagnostic_truncated"] = True
                    return
                if key not in right:
                    add(_pointer(path, key), "missing_key", left[key], _MISSING)
                elif key not in left:
                    add(_pointer(path, key), "extra_key", _MISSING, right[key])
                else:
                    walk(left[key], right[key], _pointer(path, key), depth + 1)
        elif type(left) is list:
            if len(left) != len(right):
                add(path, "list_length_mismatch", left, right)
            for index in range(max(len(left), len(right))):
                if len(result["differences"]) >= max_differences or visited >= _MAX_VISITED_NODES:
                    result["diagnostic_truncated"] = True
                    return
                if index >= len(right):
                    add(_pointer(path, index), "missing_item", left[index], _MISSING)
                elif index >= len(left):
                    add(_pointer(path, index), "extra_item", _MISSING, right[index])
                else:
                    walk(left[index], right[index], _pointer(path, index), depth + 1)
        elif _canonical(left) != _canonical(right):
            add(path, "string_mismatch" if type(left) is str else "value_mismatch", left, right)

    walk(expected, actual, "", 0)
    return result
