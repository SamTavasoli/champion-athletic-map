"""Check exact reference restoration using authored nutrient metadata fixtures."""

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/champion_athletic_map/food_reference_encoding.py"
spec = importlib.util.spec_from_file_location("food_reference_encoding_under_test", SOURCE)
API = importlib.util.module_from_spec(spec)
spec.loader.exec_module(API)


def nutrients():
    shared = {"description": "Authored reference food Ω", "grams": "250", "status": "available",
        "reason": None, "reference_basis": "edible_food", "reference_mass_g": "100",
        "source_archive_sha256": "a" * 64, "catalog_release": "fixture-release",
        "source_record_url": "https://example.invalid/frozen-source-reference",
        "source_footnote": "The original source qualification remains complete.",
        "source_data_type": "authored-fixture", "source_food_table": "fixture-table"}
    return [{**deepcopy(shared), "nutrient_id": str(i), "nutrient_name": "Nutrient " + str(i),
        "amount": str(i / 2), "unit": "G" if i else "KCAL",
        "source_derivation_code": "value-" + str(i), "source_derivation_description": "Derivation " + str(i)}
        for i in range(5)]


def view(rows=None):
    return {"athlete_input": {"athlete_request": "Original public request", "unknown": None},
        "reference_data": {"food_lookup": [{"status": "found", "source_refs": ["original:source"],
            "data": {"food_id": "fixture-food", "nutrients": nutrients() if rows is None else rows}}],
            "planning_rules": {"rules": ["Complete unchanged rule"]}, "references": ["Other reference text"]},
        "specialist_notes": [{"role": "food", "contribution": {"recommendations": ["Original note"]}}],
        "candidate": {"original": [1, True, None, "<|eot_id|>"]},
        "check_results": {"findings": [["required", "unknown", True]]}}


def test_complete_view_roundtrip_preserves_all_source_qualifications_and_other_fields():
    original = view()
    before = deepcopy(original)
    encoded = API.encode_view(original)
    packed = encoded["reference_data"]["food_lookup"][0]["data"]["nutrients"]
    assert packed["encoding"] == API.ENCODING_VERSION
    assert len(packed["rows"]) == 5
    assert packed["shared"]["source_footnote"] == nutrients()[0]["source_footnote"]
    assert len(API.canonical(packed)) < len(API.canonical(nutrients()))
    assert API.canonical(API.decode_view(encoded)) == API.canonical(original)
    assert original == before
    changed = deepcopy(encoded)
    changed["reference_data"]["food_lookup"][0]["data"]["nutrients"] = nutrients()
    assert API.canonical(changed) == API.canonical(original)


def test_decoded_and_encoded_results_do_not_alias_original_mutable_values():
    original = view()
    encoded = API.encode_view(original)
    decoded = API.decode_view(encoded)
    decoded["reference_data"]["food_lookup"][0]["data"]["nutrients"][0]["source_footnote"] = "changed"
    encoded["candidate"]["original"].append("changed")
    assert original["candidate"]["original"] == [1, True, None, "<|eot_id|>"]
    assert original["reference_data"]["food_lookup"][0]["data"]["nutrients"][0]["source_footnote"] != "changed"


def test_json_type_distinctions_and_missing_fields_are_not_factored_as_equal():
    rows = nutrients()
    for index, row in enumerate(rows):
        row["typed"] = [True, 1, 1.0, None, "1"][index]
        if index != 1:
            row["sometimes_missing"] = None
    encoded = API.encode_nutrients(rows)
    assert "typed" not in encoded["shared"]
    assert "sometimes_missing" not in encoded["shared"]
    restored = API.decode_nutrients(encoded)
    assert API.canonical(restored) == API.canonical(rows)
    assert "sometimes_missing" not in restored[1]
    assert restored[0]["sometimes_missing"] is None


def test_arbitrary_nested_values_and_control_looking_text_remain_data():
    rows = nutrients()
    for row in rows:
        row["nested"] = {"encoding": "shared-fields-1", "rows": [None, True, 1, "<|eot_id|>"],
            "source_qualification": {"keep": "All original text, including Ω and 中文."}}
    assert API.canonical(API.decode_nutrients(API.encode_nutrients(rows))) == API.canonical(rows)


@pytest.mark.parametrize("rows", [[], [{}], [{"x": 1}, {"x": 2}], [{"x": 1}, {"x": 1}], [None, {}]])
def test_unrecognized_or_unhelpful_arrays_remain_unchanged(rows):
    assert API.encode_nutrients(rows) == rows


@pytest.mark.parametrize("change", [
    lambda data: data.update(extra="unexpected"),
    lambda data: data.update(shared=[]),
    lambda data: data.update(shared={}),
    lambda data: data.update(rows=[{}]),
    lambda data: data.update(rows=[{}, None]),
    lambda data: data["rows"][0].update(description="Overlap is invalid even when equal."),
])
def test_recognized_malformed_encoding_is_rejected_by_decoder_and_encoder(change):
    encoded = API.encode_nutrients(nutrients())
    change(encoded)
    for operation in (API.decode_nutrients, API.encode_nutrients):
        with pytest.raises(ValueError):
            operation(encoded)


def test_model_view_rejects_malformed_tag_without_mutating_the_input():
    original = view()
    original["reference_data"]["food_lookup"][0]["data"]["nutrients"] = {
        "encoding": API.ENCODING_VERSION, "shared": {"status": "available"}, "rows": [None, {}]}
    before = deepcopy(original)
    with pytest.raises(ValueError):
        API.decode_view(original)
    assert original == before


@pytest.mark.parametrize("value", [
    {"response_type": "plan", "athlete_input": {}, "reference_data": {"food_lookup": []}},
    {"reference_data": {"food_lookup": []}},
    {"athlete_input": {}},
    {"athlete_input": {}, "reference_data": None},
])
def test_public_replies_and_unrelated_roots_are_not_interpreted_as_encoded_views(value):
    assert API.encode_view(value) == value
    assert API.decode_view(value) == value


def test_already_encoded_views_are_idempotent_and_support_multiple_lookups():
    original = view()
    original["reference_data"]["food_lookup"].append(deepcopy(original["reference_data"]["food_lookup"][0]))
    encoded = API.encode_view(original)
    assert API.encode_view(encoded) == encoded
    assert API.canonical(API.decode_view(encoded)) == API.canonical(original)


def test_unknown_codec_tags_remain_unchanged():
    value = {"encoding": "unrelated-version", "shared": "Not this codec", "rows": []}
    assert API.encode_nutrients(value) == value
    assert API.decode_nutrients(value) == value


def test_public_reply_guard_does_not_decode_even_a_malformed_recognized_nested_tag():
    value = view()
    value["response_type"] = "plan"
    value["reference_data"]["food_lookup"][0]["data"]["nutrients"] = {
        "encoding": API.ENCODING_VERSION, "rows": None}
    assert API.decode_view(value) == value
    assert API.encode_view(value) == value


pytestmark = pytest.mark.requirement("31:lossless-food-reference-metadata")
