"""Check classifier contracts with authored text and release metadata only."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.requirement("30.6.classifier_boundaries")
FIXTURE_VERSION = "step30-classifier-fixtures-1"


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


text = load("step30_text_preparation", "src/champion_athletic_map/text_preprocessing.py")
inference = load("step30_classifier_contract", "src/champion_athletic_map/classifier_inference.py")


def test_canonical_fields_and_shared_normalization_follow_the_recorded_order():
    prepared = inference.prepare_exercise_input("  ＰＡＳＳ  ", "  Keep\n balance.  ")
    assert prepared["canonical_text"] == "ＰＡＳＳ\n\nKeep balance."
    normalized = text.prepare_canonical_text(prepared["canonical_text"])
    assert normalized == {"model_text": "pass keep balance.", "tokens": ["pass", "keep", "balance"]}
    assert prepared["input_hash"] == hashlib.sha256("ＰＡＳＳ\n\nKeep balance.".encode()).hexdigest()


@pytest.mark.parametrize("name", [None, 42, "", " N/A ", "null"])
def test_missing_or_non_text_exercise_name_is_not_coerced_into_a_prediction(name):
    with pytest.raises(ValueError):
        inference.prepare_exercise_input(name)


def test_training_only_vocabulary_and_limit_do_not_expand_for_new_synthetic_text():
    training = [["pass", "pass", "balance"], ["balance"], []]
    vocabulary = text.fit_training_vocabulary(training, min_frequency=1)
    before = deepcopy(vocabulary)
    limit = text.choose_training_sequence_limit(training, percentile=0.5, minimum=1, maximum=20)
    # The effective training lengths are 1, 1, 3; median nearest rank is 1.
    assert limit["max_sequence_length"] == 1
    encoded = text.encode_neural_tokens(["new-synthetic-token", "pass"], vocabulary, 2)
    assert encoded["token_ids"] == [1, vocabulary["token_to_id"]["pass"]]
    assert "new-synthetic-token" not in vocabulary["token_to_id"] and vocabulary == before
    assert vocabulary["fit_policy"]["fit_split"] == "train"
    assert limit["split_verification"] == "caller_responsibility"


def test_empty_text_tokens_use_unknown_token_without_adding_padding_or_training_counts():
    vocabulary = text.fit_training_vocabulary([["pass", "pass"], []])
    encoded = text.encode_neural_tokens([], vocabulary, 5)
    assert encoded["token_ids"] == [1] and encoded["empty_token_fallback"] is True
    assert vocabulary["raw_token_occurrences"] == 2
    assert vocabulary["token_to_id"]["<PAD>"] == 0


def test_batch_padding_keeps_class_zero_separate_from_padding_zero():
    batch = text.pad_neural_batch([
        {"record_id": "authored-a", "token_ids": [2, 3], "target": 0},
        {"record_id": "authored-b", "token_ids": [1], "target": 1}], 5, 4, 2)
    assert batch["targets"] == [0, 1]
    assert batch["token_ids"] == [[2, 3], [1, 0]]
    assert batch["mask"] == [[True, True], [True, False]]


def test_tampered_vocabulary_mapping_is_rejected_before_encoding():
    vocabulary = text.fit_training_vocabulary([["pass", "pass"]])
    vocabulary["token_to_id"]["pass"] = 1
    with pytest.raises(ValueError, match="contiguous"):
        text.encode_neural_tokens(["pass"], vocabulary, 5)


def test_release_mapping_and_preprocessing_match_without_loading_model_or_test_features():
    folder = ROOT / "artifacts/classifiers/exercise-classifier-4f6b6f435ef52fef8f4cca6d"
    identity = json.loads((folder / "manifest.json").read_bytes())["identity"]
    classes = identity["class_order"]
    assert len(classes) == len(set(classes)) == 16
    assert identity["class_to_index"] == {name: index for index, name in enumerate(classes)}
    for name in ("label_mapping", "preprocessing"):
        relative = identity["configuration_files"][name]
        raw = (folder / relative).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == identity["payloads"][relative]["sha256"]
        config = json.loads(raw)
        assert config["class_order"] == classes and config["class_to_index"] == identity["class_to_index"]
    source = "src/champion_athletic_map/text_preprocessing.py"
    assert hashlib.sha256((ROOT / source).read_bytes()).hexdigest() == identity["payloads"][source]["sha256"]
    assert identity["tagging_model"]["catalog_predictions_are_suggestions"] is True
    assert identity["tagging_model"]["exercise_or_drill_approval_granted"] is False
    assert all(item["fit_partition"] == "train" for item in identity["artifacts"].values())


def test_classifier_release_paths_and_changed_payloads_are_rejected(tmp_path):
    (tmp_path / "record.json").write_bytes(b'{}')
    for path in ("../outside.json", "/absolute.json", "nested\\record.json"):
        with pytest.raises(ValueError):
            inference._classifier_safe_path(tmp_path, path)
    identity = {"payloads": {"record.json": {"bytes": 2, "sha256": hashlib.sha256(b'{}').hexdigest()}}}
    assert inference._classifier_verify_release_files(tmp_path, identity) is True
    (tmp_path / "record.json").write_bytes(b'[]')
    with pytest.raises(ValueError, match="hash_mismatch"):
        inference._classifier_verify_release_files(tmp_path, identity)


def test_classifier_output_axis_cannot_relabel_the_frozen_classes():
    assert inference._prediction_class_indices(SimpleNamespace(classes_=[0, 1, 2]), 3) == [0, 1, 2]
    for classes in ([1, 0, 2], [0, 1], [0, 1, True]):
        with pytest.raises(ValueError):
            inference._prediction_class_indices(SimpleNamespace(classes_=classes), 3)


@pytest.mark.parametrize("probabilities", [[[0.2, 0.2]], [[-0.1, 1.1]], [[float("nan"), 0.5]], [[float("inf"), 0.0]]])
def test_invalid_classifier_probabilities_do_not_become_predictions(probabilities):
    with pytest.raises(ValueError, match="probability_output"):
        inference._prediction_validate_probabilities(probabilities, 2)
