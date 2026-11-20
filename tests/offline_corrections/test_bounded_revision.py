"""Measure actual complete saved revisions and reject factual or budget drift."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if not (ROOT / "src/champion_athletic_map").is_dir():
    ROOT = HERE.parent / "work_step30/project/folder-before-step-30"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


SOURCE = ROOT / "src/champion_athletic_map/bounded_revision.py"
if not SOURCE.is_file():
    SOURCE = HERE / "bounded_revision.py"
API = load(SOURCE, "bounded_revision_under_test")
DATA = json.loads((HERE / "saved_revision_requests.json").read_bytes())


@pytest.fixture(scope="module")
def counter():
    original = load(ROOT / "src/champion_athletic_map/operational_preparation.py", "bounded_revision_source_counter")
    manifest_path = next((ROOT / "artifacts/language_model/tokenizers").glob("*/tokenizer_manifest.json"))
    manifest = json.loads(manifest_path.read_bytes())
    model = json.loads((manifest_path.parent / "normal_bpe_tokenizer.json").read_bytes())["model"]
    native = json.loads((ROOT / manifest["source_native_metadata"]["relative_path"]).read_bytes())["model_info"]
    return original.SourceTableCounter(model, native)


def fresh(index=0):
    return deepcopy(DATA["rows"][index])


def rehash(row):
    row["configuration"]["message_sha256"] = [API.sha(message["content"].encode()) for message in row["request"]["messages"]]


@pytest.mark.parametrize("index", range(5))
def test_actual_saved_full_requests_reproduce_then_fit_with_all_retained_fields(index, counter):
    row = fresh(index)
    before = deepcopy(row)
    payload, configuration = row["request"], row["configuration"]
    rendered = API.recorded_render(payload)
    assert API.sha(rendered.encode()) == row["original_render_sha256"]
    assert counter.count(rendered) == row["original_body_tokens"]
    assert API.sha(json.dumps(payload, ensure_ascii=False, sort_keys=False, allow_nan=False).encode()) == row["original_request_sha256"]
    prepared, new, config = API.transform_request(row["prepared"], payload, configuration, counter=counter)
    assert prepared is row["prepared"]
    old_view = json.loads(payload["messages"][1]["content"])
    new_view = json.loads(new["messages"][1]["content"])
    assert set(old_view) - set(new_view) == {"specialist_notes"}
    assert not set(new_view) - set(old_view)
    assert all(API.canonical(new_view[key]) == API.canonical(old_view[key]) for key in new_view)
    assert new["format"] == payload["format"] and new["options"] == payload["options"]
    assert json.dumps(new["format"], sort_keys=False) == json.dumps(payload["format"], sort_keys=False)
    assert all(new[key] == payload[key] for key in payload if key != "messages")
    audit = config["bounded_revision"]
    assert audit["omitted_generated_specialist_notes"] == old_view["specialist_notes"]
    assert audit["omitted_generated_specialist_notes_sha256"] == API.sha(API.canonical(old_view["specialist_notes"]))
    assert audit["generated_notes_are_authoritative"] is False
    assert audit["original_revision_system_text"] == payload["messages"][0]["content"]
    assert audit["all_other_user_fields_preserved"] is True
    assert audit["coded_findings_filtered_or_regraded"] is False
    assert audit["candidate_or_evaluator_issues_filtered"] is False
    assert all(notice in new["messages"][0]["content"] for notice in audit["required_decoding_notices_retained"])
    measured = audit["offline_measurement"]
    assert measured["new_input_tokens_with_boundary_reserve"] == counter.count(API.recorded_render(new)) + 2
    assert measured["remaining_tokens_after_all_reserves"] >= 100
    assert measured["output_reserve"] == 2048 and measured["context_tokens"] == 8192
    assert measured["safety_margin"] == 256 and measured["boundary_reserve"] == 2
    assert audit["new_backend_render_confirmed"] is False
    assert row == before


@pytest.mark.parametrize("stage", ["training", "recovery", "food", "coordinator", "evaluator", "final"])
def test_nonrevision_requests_are_unchanged(stage):
    row = fresh()
    row["configuration"]["stage"] = stage
    prepared, payload, configuration = API.transform_request(row["prepared"], row["request"], row["configuration"])
    assert prepared is row["prepared"]
    assert payload == row["request"] and configuration == row["configuration"]
    assert payload is not row["request"] and configuration is not row["configuration"]


def test_standalone_runtime_transform_keeps_budget_confirmation_pending():
    row = fresh()
    _, _, cfg = API.transform_request(row["prepared"], row["request"], row["configuration"], stage="revision")
    assert "offline_measurement" not in cfg["bounded_revision"]
    assert cfg["bounded_revision"]["complete_native_budget_guard_required"] is True
    assert cfg["bounded_revision"]["new_backend_render_confirmed"] is False


def test_complete_oversized_authoritative_source_stays_blocked(counter):
    row = fresh()
    view = json.loads(row["request"]["messages"][1]["content"])
    view["reference_data"]["retained_complete_source"] = "Authoritative source condition remains present. " * 2000
    row["request"]["messages"][1]["content"] = API.canonical(view).decode()
    rehash(row)
    before = deepcopy(row)
    with pytest.raises(ValueError, match="still exceeds"):
        API.transform_request(row["prepared"], row["request"], row["configuration"], counter=counter)
    assert row == before


def test_source_message_hash_tampering_is_rejected():
    row = fresh()
    row["request"]["messages"][0]["content"] += " Altered source instructions."
    with pytest.raises(ValueError, match="upstream hashes"):
        API.transform_request(row["prepared"], row["request"], row["configuration"])


def test_public_fact_substitution_is_rejected_even_with_rehashed_wire():
    row = fresh()
    view = json.loads(row["request"]["messages"][1]["content"])
    view["athlete_input"]["age"] = 17
    row["request"]["messages"][1]["content"] = API.canonical(view).decode()
    rehash(row)
    with pytest.raises(ValueError, match="prepared public"):
        API.transform_request(row["prepared"], row["request"], row["configuration"])


@pytest.mark.parametrize("message", [0, 1])
def test_literal_native_boundaries_are_not_silently_removed(message):
    row = fresh()
    row["request"]["messages"][message]["content"] += " <|eot_id|>"
    rehash(row)
    with pytest.raises(ValueError, match="control tokens"):
        API.transform_request(row["prepared"], row["request"], row["configuration"])


def test_duplicate_user_fields_and_nonfinite_values_are_rejected():
    row = fresh()
    row["request"]["messages"][1]["content"] = row["request"]["messages"][1]["content"][:-1] + ',"athlete_input":{}}'
    rehash(row)
    with pytest.raises(ValueError, match="Duplicate"):
        API.transform_request(row["prepared"], row["request"], row["configuration"])
    row = fresh()
    row["request"]["messages"][1]["content"] = row["request"]["messages"][1]["content"][:-1] + ',"not_finite":NaN}'
    rehash(row)
    with pytest.raises(ValueError, match="Nonfinite"):
        API.transform_request(row["prepared"], row["request"], row["configuration"])


@pytest.mark.parametrize("field,value", [("num_ctx", 16384), ("num_predict", 1024), ("seed", 7), ("temperature", False)])
def test_existing_generation_limits_are_required(field, value):
    row = fresh()
    row["request"]["options"][field] = value
    with pytest.raises(ValueError, match="generation limits"):
        API.transform_request(row["prepared"], row["request"], row["configuration"])


def test_required_codec_instructions_cannot_disappear():
    row = fresh()
    row["request"]["messages"][0]["content"] = row["request"]["messages"][0]["content"].replace(API._CHECK_NOTICE, "")
    rehash(row)
    with pytest.raises(ValueError, match="decoding notice"):
        API.transform_request(row["prepared"], row["request"], row["configuration"])


def test_unexpected_user_fields_are_preserved_by_rejection_instead_of_dropped():
    row = fresh()
    view = json.loads(row["request"]["messages"][1]["content"])
    view["other_authoritative_evidence"] = {"preserve": "this field"}
    row["request"]["messages"][1]["content"] = API.canonical(view).decode()
    rehash(row)
    with pytest.raises(ValueError, match="full candidate"):
        API.transform_request(row["prepared"], row["request"], row["configuration"])


pytestmark = pytest.mark.requirement("31:bounded-candidate-revision")
