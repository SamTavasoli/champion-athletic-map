"""Represent repeated nutrient metadata once without removing reference fields."""

from copy import deepcopy
import json


ENCODING_VERSION = "shared-fields-1"
ENCODING_NOTICE = (
    "reference_data.food_lookup data.nutrients shared-fields-1 contains shared fields and rows. "
    "Merge shared into each row to restore every original nutrient record; "
    "no field or qualification is omitted."
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")


def _object(value):
    return type(value) is dict and all(type(key) is str for key in value)


def _recognized(value):
    return type(value) is dict and value.get("encoding") == ENCODING_VERSION


def decode_nutrients(value):
    """Restore only this codec's tagged nutrient representation."""
    if not _recognized(value):
        return deepcopy(value)
    if (set(value) != {"encoding", "shared", "rows"}
            or not _object(value.get("shared")) or not value["shared"]
            or type(value.get("rows")) is not list or len(value["rows"]) < 2
            or any(not _object(row) for row in value["rows"])):
        raise ValueError("The encoded nutrient metadata has invalid fields or rows.")
    shared = value["shared"]
    if any(set(shared) & set(row) for row in value["rows"]):
        raise ValueError("Shared nutrient metadata overlaps a row field.")
    restored = [{**deepcopy(shared), **deepcopy(row)} for row in value["rows"]]
    canonical(restored)
    return restored


def encode_nutrients(value):
    """Factor identical complete fields only when the canonical JSON is smaller."""
    if _recognized(value):
        decode_nutrients(value)
        return deepcopy(value)
    if type(value) is not list or len(value) < 2 or any(not _object(row) for row in value):
        return deepcopy(value)
    shared = {key: deepcopy(item) for key, item in value[0].items()
        if all(key in row and canonical(row[key]) == canonical(item) for row in value[1:])}
    if not shared:
        return deepcopy(value)
    encoded = {"encoding": ENCODING_VERSION, "shared": shared,
        "rows": [{key: deepcopy(item) for key, item in row.items() if key not in shared} for row in value]}
    if canonical(decode_nutrients(encoded)) != canonical(value):
        raise ValueError("The nutrient encoding changed an original reference value.")
    return encoded if len(canonical(encoded)) < len(canonical(value)) else deepcopy(value)


def _model_view(value):
    return (_object(value) and "athlete_input" in value and "reference_data" in value
        and "response_type" not in value and _object(value["reference_data"]))


def _transform(view, operation):
    result = deepcopy(view)
    if not _model_view(result):
        return result
    lookups = result["reference_data"].get("food_lookup")
    if type(lookups) is not list:
        return result
    for lookup in lookups:
        if not _object(lookup) or not _object(lookup.get("data")) or "nutrients" not in lookup["data"]:
            continue
        lookup["data"]["nutrients"] = operation(lookup["data"]["nutrients"])
    return result


def encode_view(view):
    """Change only nutrient representation inside a quoted model-input view."""
    return _transform(view, encode_nutrients)


def decode_view(view):
    """Never interpret a public reply or unrelated object as an encoded input."""
    return _transform(view, decode_nutrients)
