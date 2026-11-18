"""Artificial evaluator checks; no protected benchmark rows are used here."""
from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _project():
    locations = []
    configured = os.environ.get("CHAMPION_CLASSIFIER_TEST_ROOT")
    if configured:
        locations.append(Path(configured))
    for base in (Path.cwd(), Path(__file__).resolve().parent):
        locations.extend((base, *base.parents))
        locations.append(base / "work_step30/project/folder-before-step-30")
    for root in locations:
        if (root / "artifacts/evaluation/classifier_metrics_db3e5f3df78a126c/classifier_metrics.py").is_file():
            return root.resolve()
    raise AssertionError("The saved classifier source bundle is required for artificial checks.")


@pytest.fixture(scope="session")
def source_project():
    return _project()


@pytest.fixture(scope="session")
def frozen_api(source_project):
    path = source_project / "artifacts/classifiers/exercise-classifier-4f6b6f435ef52fef8f4cca6d/src/champion_athletic_map/classifier_inference.py"
    return _module(path, "step32_frozen_inference_api")


@pytest.fixture(scope="session")
def text_api(source_project):
    return _module(source_project / "src/champion_athletic_map/text_preprocessing.py", "step32_frozen_text_api")


@pytest.fixture(scope="session")
def metric_api(source_project):
    path = source_project / "artifacts/evaluation/classifier_metrics_db3e5f3df78a126c/classifier_metrics.py"
    return _module(path, "step32_frozen_metric_api")


@pytest.fixture(scope="session")
def evaluator(source_project):
    supplied = os.environ.get("CHAMPION_STEP32_EVALUATOR_PATH")
    paths = ([Path(supplied)] if supplied else []) + [source_project / "src/champion_athletic_map/classifier_test_evaluation.py", Path(__file__).with_name("classifier_test_evaluation.py")]
    path = next((path for path in paths if path.is_file()), None)
    assert path is not None, "The candidate evaluator source is required."
    return _module(path, "step32_candidate_evaluator")


class _ForbiddenText:
    def __str__(self):
        raise AssertionError("A protected text field was inspected through the application route.")


def test_existing_application_gate_rejects_test_scope_without_inspecting_text(frozen_api):
    before = hashlib.sha256(Path(frozen_api.__file__).read_bytes()).hexdigest()
    value = frozen_api.predict_exercise(None, _ForbiddenText(), _ForbiddenText(), input_scope="protected_test")
    assert value["status"] == "deferred"
    assert value["code"] == "input_population_is_not_cleared_for_prediction"
    assert value["prediction_produced"] is False
    again = frozen_api.predict_from_bundle(Path("absent-release"), _ForbiddenText(), input_scope="test")
    assert again["status"] == "deferred"
    assert hashlib.sha256(Path(frozen_api.__file__).read_bytes()).hexdigest() == before


@pytest.mark.parametrize("name,description,canonical,name_only", [
    ("  Synthetic\t footwork ", " Side\n to\t side ", "Synthetic footwork\n\nSide to side", False),
    ("Fictional drill", None, "Fictional drill", True),
    ("Fictional drill", " N/A ", "Fictional drill", True),
    ("Ｃafé Ω", "unknown 🏀", "Ｃafé Ω\n\nunknown 🏀", False),
])
def test_real_frozen_field_preparation_keeps_name_only_and_unicode(frozen_api, name, description, canonical, name_only):
    prepared = frozen_api.prepare_exercise_input(name, description)
    assert prepared == {"canonical_text": canonical, "name_only": name_only,
        "input_hash": hashlib.sha256(canonical.encode()).hexdigest()}


@pytest.mark.parametrize("name,description", [("", None), ("NONE", "description"), (None, "detail"), ("name", 4)])
def test_real_frozen_field_preparation_rejects_invalid_fields(frozen_api, name, description):
    with pytest.raises((ValueError, TypeError)):
        frozen_api.prepare_exercise_input(name, description)


def test_frozen_scorer_retains_all_sixteen_classes_and_zero_division(metric_api):
    order = ["synthetic_class_" + str(index) for index in range(16)]
    scored = metric_api.summarize_classifier_predictions([order[0]], [order[0]], ["artificial_group"], order)
    assert scored["class_order"] == order
    assert scored["accuracy"] == 1.0
    assert scored["macro_f1"] == pytest.approx(1 / 16)
    assert scored["confusion_axes"] == {"rows": "actual", "columns": "predicted"}
    assert len(scored["per_class"]) == 16
    assert scored["per_class"][1]["f1"] == 0.0
    assert scored["per_class"][1]["recall_defined"] is False
    empty = metric_api.summarize_classifier_predictions([], [], [], order)
    assert empty["accuracy"] is None and empty["macro_f1"] is None


def test_real_frozen_scorer_refuses_silent_alignment_or_unknown_labels(metric_api):
    with pytest.raises(ValueError):
        metric_api.summarize_classifier_predictions(["a", "b"], ["a"], ["g", "h"], ["a", "b"])
    with pytest.raises(ValueError):
        metric_api.summarize_classifier_predictions(["a"], ["unknown"], ["g"], ["a", "b"])


def test_saved_neural_encoding_preserves_unknown_and_empty_token_rows(text_api):
    vocabulary = text_api.fit_training_vocabulary([["known", "known"]], min_frequency=1)
    unknown = text_api.encode_neural_tokens(["artificial_unseen_token"], vocabulary, 4)
    empty = text_api.encode_neural_tokens([], vocabulary, 4)
    assert unknown["token_ids"] == [1]
    assert unknown["all_unknown_after_truncation"] is True
    assert empty["token_ids"] == [1]
    assert empty["empty_token_fallback"] is True


def test_real_low_level_logistic_route_keeps_all_zero_tfidf_input(frozen_api, text_api):
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    examples = ["artificialtoken" + str(index) for index in range(16)]
    model = Pipeline([("tfidf", TfidfVectorizer(tokenizer=text_api.tokenize_canonical_text,
        lowercase=False, token_pattern=None)), ("classifier", LogisticRegression(max_iter=200))])
    model.fit(examples, np.arange(16))
    handle = {"family": "logistic_regression", "model": model, "class_order": examples}
    flags = {}
    index, probabilities, logits = frozen_api._prediction_sklearn(handle, "totally_unseen_æ_名字", flags)
    assert type(index) is int and 0 <= index < 16
    assert len(probabilities) == 16 and sum(probabilities) == pytest.approx(1.0)
    assert flags["tfidf_zero_vector"] is True
    assert flags["tfidf_nonzero_features"] == 0
    assert logits is None


def test_real_loader_dependency_gate_precedes_model_deserialization(frozen_api, source_project, monkeypatch):
    calls = []
    def reject_environment(_identity):
        calls.append("environment")
        raise ValueError("artificial_dependency_mismatch")
    def forbid_model(*_args, **_kwargs):
        raise AssertionError("A model was deserialized before the environment gate passed.")
    import joblib
    monkeypatch.setattr(frozen_api, "_classifier_dependency_versions", reject_environment)
    monkeypatch.setattr(joblib, "load", forbid_model)
    release = source_project / "artifacts/classifiers/exercise-classifier-4f6b6f435ef52fef8f4cca6d"
    with pytest.raises(frozen_api.ClassifierLoadError, match="recorded_dependency_versions"):
        frozen_api.load_classifier(release, family="logistic_regression", device="cpu")
    assert calls == ["environment"]


def _artificial_tables():
    classes = ["synthetic_class_" + str(i) for i in range(16)]
    rows = []
    for split in ("train", "validation", "test"):
        for index, label in enumerate(classes):
            rows.append({"catalog_id": split + "_" + str(index), "split_group_id": split + "_group_" + str(index),
                "source_file": "artificial_records.csv", "source_sha256": "a" * 64, "preparation_version": "artificial-v1",
                "source_cleaned_record_position": str(len(rows)), "benchmark_eligible": "True", "split": split,
                "target_label": label, "class_index": str(index), "body_part_prepared": label})
    extra = {**rows[-16], "catalog_id": "test_additional_member", "source_cleaned_record_position": str(len(rows))}
    rows.append(extra)
    groups = [{key: row[key] for key in ("catalog_id", "split_group_id", "source_sha256", "preparation_version")} for row in rows]
    protocol = {"injected_fixture": True, "class_order": classes, "class_to_index": {label: i for i, label in enumerate(classes)},
        "test_population_from_frozen_metadata": {"records": 17, "groups": 16, "split": "test"}}
    metric = {"split_support": [{"split": part, "records": 17 if part == "test" else 16, "groups": 16}
        for part in ("train", "validation", "test")]}
    summary = {"population": {"source_records": len(rows)}}
    catalog = []
    for row in rows:
        name = "Artificial exercise " + row["catalog_id"]
        detail = "" if row["catalog_id"] == "test_0" else "Fictional motion without athlete data"
        catalog.append({**row, "exercise_name_prepared": name, "description_prepared": detail,
            "classifier_text": name + ("\n\n" + detail if detail else ""), "body_part_prepared": row["target_label"],
            "equipment": "metadata excluded from features", "target_label": "metadata must not enter features"})
    return rows, groups, protocol, metric, summary, catalog


def test_population_selects_every_artificial_test_record_in_stable_id_order(evaluator):
    rows, groups, protocol, metric, summary, _ = _artificial_tables()
    selected = evaluator.validate_population(rows[::-1], groups[::-1], protocol, metric, summary)
    assert len(selected) == 17
    assert len({row["split_group_id"] for row in selected}) == 16
    assert [row["catalog_id"] for row in selected] == sorted(row["catalog_id"] for row in rows if row["split"] == "test")
    assert selected[-1]["target_label"] in protocol["class_order"]


@pytest.mark.parametrize("defect", ["duplicate", "missing_group", "lineage", "invalid_eligibility", "target", "class_index", "excluded_partition", "row_count", "support", "class_coverage"])
def test_population_rejects_silent_drops_invalid_targets_and_wrong_frozen_counts(evaluator, defect):
    rows, groups, protocol, metric, summary, _ = _artificial_tables()
    if defect == "duplicate": rows[-1]["catalog_id"] = rows[-2]["catalog_id"]
    elif defect == "missing_group": groups.pop()
    elif defect == "lineage": groups[-1]["source_sha256"] = "b" * 64
    elif defect == "invalid_eligibility": rows[-1]["benchmark_eligible"] = "maybe"
    elif defect == "target": rows[-1]["target_label"] = "unknown label"
    elif defect == "class_index": rows[-1]["class_index"] = "1"
    elif defect == "excluded_partition": rows[-1]["benchmark_eligible"] = "False"
    elif defect == "row_count": summary["population"]["source_records"] += 1
    elif defect == "support": metric["split_support"][-1]["groups"] += 1
    elif defect == "class_coverage":
        rows[-2]["target_label"] = protocol["class_order"][0]
        rows[-2]["class_index"] = "0"
    with pytest.raises(ValueError):
        evaluator.validate_population(rows, groups, protocol, metric, summary)


def test_population_rejects_shared_group_between_training_and_test_before_alignment(evaluator):
    rows, groups, protocol, metric, summary, _ = _artificial_tables()
    for index, row in enumerate(rows):
        if row["split"] == "test" and row["class_index"] == "0":
            row["split_group_id"] = rows[0]["split_group_id"]
            groups[index]["split_group_id"] = rows[0]["split_group_id"]
    with pytest.raises(ValueError, match="leakage"):
        evaluator.validate_population(rows, groups, protocol, metric, summary)


def test_catalog_alignment_uses_allowlisted_text_and_frozen_manifest_targets(evaluator, frozen_api):
    rows, groups, protocol, metric, summary, catalog = _artificial_tables()
    selected = evaluator.validate_population(rows, groups, protocol, metric, summary)
    prepared = evaluator.align_catalog(selected, catalog, frozen_api, all_metadata=rows)
    assert len(prepared) == 17
    for actual, expected in zip(prepared, selected):
        assert actual["target_label"] == expected["target_label"]
        assert actual["class_index"] == int(expected["class_index"])
        assert "metadata excluded" not in actual["canonical_text"]
        assert "metadata must not" not in actual["canonical_text"]
        assert actual["input_hash"] == hashlib.sha256(actual["canonical_text"].encode()).hexdigest()
    assert next(row for row in prepared if row["catalog_id"] == "test_0")["name_only"] is True


@pytest.mark.parametrize("defect", ["missing", "duplicate", "extra", "source_file", "source_sha256", "source_cleaned_record_position", "preparation_version", "split_group_id", "target", "text"])
def test_catalog_alignment_rejects_changed_lineage_missing_records_and_feature_disagreement(evaluator, frozen_api, defect):
    rows, groups, protocol, metric, summary, catalog = _artificial_tables()
    selected = evaluator.validate_population(rows, groups, protocol, metric, summary)
    item = next(row for row in catalog if row["catalog_id"] == "test_0")
    if defect == "missing": catalog.remove(item)
    elif defect == "duplicate": catalog.append(copy.deepcopy(item))
    elif defect == "extra": catalog.append({**item, "catalog_id": "unexpected"})
    elif defect == "target": item["body_part_prepared"] = protocol["class_order"][1]
    elif defect == "text": item["classifier_text"] += " target metadata was appended"
    else: item[defect] += "changed"
    with pytest.raises(ValueError):
        evaluator.align_catalog(selected, catalog, frozen_api, all_metadata=rows)


def test_dedicated_inference_uses_low_level_saved_route_without_claiming_synthetic_scope(evaluator):
    seen = []
    def route(handle, text, flags):
        seen.append((handle["family"], text))
        flags["artificial_test_adapter"] = True
        return 0, [1.0] + [0.0] * 15, None
    def app_route(*_args, **_kwargs):
        raise AssertionError("Protected benchmark inference must never call the application predictor.")
    api = SimpleNamespace(_prediction_neural=route, _prediction_sklearn=route, predict_exercise=app_route)
    classes = ["synthetic_class_" + str(index) for index in range(16)]
    for family in ("majority", "logistic_regression", "neural"):
        result = evaluator.infer_one({"family": family, "class_order": classes}, "Artificial name-only input", api)
        assert result["predicted_class_index"] == 0
        assert result["predicted_label"] == classes[0]
        assert result["handling_flags"]["artificial_test_adapter"] is True
    assert len(seen) == 3


@pytest.mark.parametrize("index,probabilities", [(True, [1.0]+[0.0]*15), (16, [1.0]+[0.0]*15), (0, [float("nan")]+[0.0]*15),
    (0, [0.0, 1.0]+[0.0]*14), (0, [1.0]), (0, [True]+[0.0]*15)])
def test_inference_rejects_invalid_class_indices_and_score_axes(evaluator, index, probabilities):
    api = SimpleNamespace(_prediction_sklearn=lambda *_args: (index, probabilities, None))
    with pytest.raises(ValueError):
        evaluator.infer_one({"family": "majority", "class_order": [str(i) for i in range(16)]}, "Artificial", api)


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def artificial_project(tmp_path, evaluator, metric_api, frozen_api):
    """A new artificial benchmark, explicitly ineligible for production execution."""
    rows, groups, minimum, metric, summary, catalog = _artificial_tables()
    root = tmp_path / "artificial_project"
    benchmark = "artificial-benchmark-no-athlete-data"
    classes = minimum["class_order"]
    mapping = minimum["class_to_index"]
    catalog_path = "data/processed/exercise_catalog.csv"
    split_path = "data/processed/exercise_split_manifest.csv"
    groups_path = "data/processed/exercise_groups.csv"
    _write_csv(root / catalog_path, catalog)
    _write_csv(root / split_path, rows)
    _write_csv(root / groups_path, groups)
    prep_path = "results/step10_exercise_preparation.json"
    raw_source_path = "data/raw/artificial_source.csv"
    (root / raw_source_path).parent.mkdir(parents=True, exist_ok=True)
    (root / raw_source_path).write_bytes(b"Artificial source marker; no real records.\n")
    _write_json(root / prep_path, {"artifacts": {"catalog": {"sha256": evaluator.sha((root / catalog_path).read_bytes())}},
        "parent_source": {"relative_path": raw_source_path, "sha256": evaluator.sha((root / raw_source_path).read_bytes())}})
    summary.update(benchmark_id=benchmark, class_order=classes, class_to_index=mapping,
        input_hashes={name: evaluator.sha((root / name).read_bytes()) for name in (catalog_path, prep_path, raw_source_path)})
    _write_json(root / "results/step15_exercise_split_summary.json", summary)
    primary = {"average": "macro", "labels": "all_frozen_classes_in_saved_order", "name": "macro_f1", "zero_division": 0}
    metric.update(benchmark_id=benchmark, class_order=classes, class_to_index=mapping, primary_metric=primary)
    scorer_path = "artifacts/evaluation/artificial/classifier_metrics.py"
    (root / scorer_path).parent.mkdir(parents=True, exist_ok=True)
    (root / scorer_path).write_bytes(Path(metric_api.__file__).read_bytes())
    _write_json(root / "artifacts/evaluation/artificial/classifier_metric_config.json", metric)
    inference_path = "src/champion_athletic_map/classifier_inference.py"
    (root / inference_path).parent.mkdir(parents=True, exist_ok=True)
    (root / inference_path).write_bytes(Path(frozen_api.__file__).read_bytes())
    models = {family: {"candidate_id": None if family == "majority" else "L5" if family == "logistic_regression" else "N3",
        "fit_partition": "train", "retrained_after_selection": False, "relative_path": "models/" + family + ".artificial",
        "model_id": "artificial-" + family, "configuration_id": "artificial-config", "run_id": "artificial-run"}
        for family in evaluator.FAMILIES}
    models["neural"].update(seed=42, best_epoch=19)
    release_root = "artifacts/classifiers/artificial"
    payloads = {}
    for family, model in models.items():
        data = ("Artificial opaque payload; never deserialized: " + family).encode()
        path = root / release_root / model["relative_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        payloads[model["relative_path"]] = {"sha256": evaluator.sha(data), "bytes": len(data)}
    environment = {"python": "artificial-fixture", "packages": {}}
    identity = {"benchmark_id": benchmark, "class_order": classes, "class_to_index": mapping, "artifacts": models,
        "dependencies": environment, "unicode_database": "artificial-fixture", "reference_inference_device": "cuda:0", "payloads": payloads}
    release_path = release_root + "/manifest.json"
    _write_json(root / release_path, {"release_id": "artificial-release", "identity": identity})
    bindings = {path.relative_to(root).as_posix(): evaluator.sha(path.read_bytes()) for path in root.rglob("*") if path.is_file()}
    protocol = {**minimum, "classifier_protocol_frozen": True, "models_fitted": 0, "test_predictions_created": 0,
        "heldout_text_parsed": False, "benchmark_id": benchmark, "models": models, "classifier_release_id": "artificial-release",
        "release_manifest_path": release_path, "metric_scorer_path": scorer_path, "dependencies": environment,
        "unicode_database": "artificial-fixture", "evaluation_device": "cuda:0", "analysis": {"primary_metric": primary},
        "source_file_sha256": bindings}
    protocol["protocol_id"] = evaluator.sha(evaluator.canonical(protocol))
    protocol_path = "artifacts/evaluation/artificial_protocol/manifest.json"
    _write_json(root / protocol_path, protocol)
    checkpoint = {"classifier_protocol_frozen": True, "step32_preparation_may_continue": True, "injected_test_dependencies": False,
        "classifier_protocol_id": protocol["protocol_id"], "classifier_protocol_path": protocol_path, "source_file_sha256": bindings}
    _write_json(root / evaluator.CHECKPOINT, checkpoint)
    return SimpleNamespace(root=root, protocol=protocol, checkpoint=checkpoint, rows=rows, groups=groups, catalog=catalog,
        inference_path=inference_path, scorer_path=scorer_path, split_path=split_path, groups_path=groups_path, catalog_path=catalog_path)


def test_artificial_protocol_is_explicit_and_cannot_be_used_as_the_approved_production_protocol(evaluator, artificial_project):
    source = evaluator.load_protocol(artificial_project.root, injected=True)
    assert source["protocol"]["injected_fixture"] is True
    assert source["protocol"]["test_population_from_frozen_metadata"]["records"] == 17
    with pytest.raises(ValueError, match="approved|production|artificial"):
        evaluator.load_protocol(artificial_project.root)


@pytest.mark.parametrize("defect", ["protocol_identity", "model_bytes", "scorer_bytes", "data_bytes", "checkpoint_bindings"])
def test_frozen_protocol_and_sources_fail_before_any_feature_table_parse(evaluator, artificial_project, monkeypatch, defect):
    fixture = artificial_project
    if defect == "protocol_identity":
        value = copy.deepcopy(fixture.protocol)
        value["class_order"] = value["class_order"][::-1]
        _write_json(fixture.root / fixture.checkpoint["classifier_protocol_path"], value)
    elif defect == "checkpoint_bindings":
        value = copy.deepcopy(fixture.checkpoint)
        value["source_file_sha256"][fixture.scorer_path] = "0" * 64
        _write_json(fixture.root / evaluator.CHECKPOINT, value)
    else:
        relative = ("artifacts/classifiers/artificial/models/neural.artificial" if defect == "model_bytes"
            else fixture.scorer_path if defect == "scorer_bytes" else fixture.catalog_path)
        path = fixture.root / relative
        path.write_bytes(path.read_bytes() + b"changed")
    def forbid_parse(*_args, **_kwargs):
        raise AssertionError("A table parser ran before frozen-source verification passed.")
    monkeypatch.setattr(evaluator, "csv_rows", forbid_parse)
    with pytest.raises(ValueError):
        evaluator.load_protocol(fixture.root, injected=True)
    assert not (fixture.root / evaluator.SUMMARY).exists()
    assert not (fixture.root / "results/classifier_test").exists()


def test_immutable_output_writer_never_clobbers_an_existing_result(evaluator, tmp_path):
    path = tmp_path / "receipt.json"
    evaluator.save_once(path, {"prediction": "first"})
    expected = path.read_bytes()
    evaluator.save_once(path, {"prediction": "first"})
    with pytest.raises(ValueError, match="immutable"):
        evaluator.save_once(path, {"prediction": "different"})
    assert path.read_bytes() == expected


def _execution(fixture, evaluator, frozen_api, metric_api):
    installed = fixture.root / "src/champion_athletic_map/classifier_test_evaluation.py"
    installed.parent.mkdir(parents=True, exist_ok=True)
    installed.write_bytes(Path(evaluator.__file__).read_bytes())
    calls = {"environment": 0, "load": [], "predict": [], "score": []}
    def load_source(root, *, injected):
        assert injected is True
        return evaluator.load_protocol(root, injected=True)
    def environment(source):
        calls["environment"] += 1
        return {"artificial_environment": True, "no_native_environment_claim": True}
    def load_model(_release, *, family, device):
        calls["load"].append(family)
        return {"status": "ready", "family": family, "class_order": fixture.protocol["class_order"],
            "class_to_index": fixture.protocol["class_to_index"], "artifact": fixture.protocol["models"][family],
            "release_id": "artificial-release", "device": device}
    def predict(handle, text):
        assert isinstance(text, str)
        calls["predict"].append((handle["family"], text))
        index = evaluator.FAMILIES.index(handle["family"])
        return {"predicted_class_index": index, "predicted_label": handle["class_order"][index],
            "probabilities": [1.0 if i == index else 0.0 for i in range(16)], "logits": None,
            "handling_flags": {"artificial_test_adapter": True}}
    def score(actual, predicted, groups, classes):
        calls["score"].append((list(actual), list(predicted), list(groups), list(classes)))
        return metric_api.summarize_classifier_predictions(actual, predicted, groups, classes)
    deps = {"load_protocol": load_source, "verify_environment": environment, "load_classifier": load_model,
        "verify_classifier_integrity": lambda _handle: True, "predict_one": predict, "summarize": score,
        "inference_api": frozen_api}
    reports = fixture.root / "src/champion_athletic_map/classifier_test_reports.py"
    reports.write_text("# Artificial report helper; no real reporting environment is claimed.\n", encoding="utf-8")
    deps["reports_api"] = SimpleNamespace(report_environment=lambda: {"artificial_report_adapter": True}, write_reports=lambda *_args, **_kwargs: [])
    evidence = {"status": "passed", "passed": 1, "failed": 0, "not_completed": 0, "injected_fixture": True,
        "files": {path.relative_to(fixture.root).as_posix(): evaluator.sha(path.read_bytes()) for path in (installed, reports)}}
    return deps, calls, evidence


def test_complete_artificial_execution_has_all_three_full_populations_and_real_metric_results(evaluator, artificial_project, frozen_api, metric_api):
    fixture = artificial_project
    deps, calls, evidence = _execution(fixture, evaluator, frozen_api, metric_api)
    result = evaluator.execute(fixture.root, emit=lambda _message: None, software_evidence=evidence, dependencies=deps)
    assert result["status"] == "complete", result
    assert result["injected_test_dependencies"] is True
    assert result["heldout_text_processed"] is False
    assert result["records"] == 17 and result["groups"] == 16
    assert result["new_predictions"] == 51
    assert calls["load"] == list(evaluator.FAMILIES)
    assert [sum(family == name for family, _text in calls["predict"]) for name in evaluator.FAMILIES] == [17, 17, 17]
    assert len(calls["score"]) == 3
    for family, arguments in zip(evaluator.FAMILIES, calls["score"]):
        expected = metric_api.summarize_classifier_predictions(*arguments)
        assert result["models"][family]["macro_f1"] == expected["macro_f1"]
        assert result["models"][family]["accuracy"] == expected["accuracy"]
        assert result["models"][family]["records"] == 17
    assert not (fixture.root / evaluator.SUMMARY).exists()
    assert (fixture.root / "results/classifier_test/injected_test_summary.json").is_file()
    alignment = list(csv.DictReader((fixture.root / result["summary_path"]).with_name("alignment.csv").open()))
    assert len(alignment) == 17
    assert {row["catalog_id"] for row in alignment} == {row["catalog_id"] for row in fixture.rows if row["split"] == "test"}
    original_calls = copy.deepcopy(calls)
    reused = evaluator.execute(fixture.root, emit=lambda _message: None, software_evidence=evidence, dependencies=deps)
    assert reused["status"] == "complete" and reused["saved_execution_reused"] is True
    assert reused["new_predictions"] == 0 and reused["models_loaded_this_run"] == 0
    assert calls == original_calls


@pytest.mark.parametrize("stage", ["environment", "model_identity", "software_evidence"])
def test_preflight_failures_precede_population_and_feature_table_parsing(evaluator, artificial_project, frozen_api, metric_api, monkeypatch, stage):
    fixture = artificial_project
    deps, calls, evidence = _execution(fixture, evaluator, frozen_api, metric_api)
    def forbidden_parse(*_args, **_kwargs):
        raise AssertionError("CSV parsing occurred before the failed readiness gate.")
    monkeypatch.setattr(evaluator, "csv_rows", forbidden_parse)
    if stage == "environment":
        def fail_environment(_source):
            raise ValueError("artificial environment mismatch")
        deps["verify_environment"] = fail_environment
    elif stage == "model_identity":
        original = deps["load_classifier"]
        def bad_handle(*args, **kwargs):
            handle = original(*args, **kwargs)
            if handle["family"] == "neural": handle["artifact"] = {"candidate_id": "wrong"}
            return handle
        deps["load_classifier"] = bad_handle
    else:
        evidence["files"]["src/champion_athletic_map/classifier_test_evaluation.py"] = "0" * 64
    if stage in ("software_evidence", "environment"):
        with pytest.raises(ValueError):
            evaluator.execute(fixture.root, emit=lambda _message: None, software_evidence=evidence, dependencies=deps)
    else:
        result = evaluator.execute(fixture.root, emit=lambda _message: None, software_evidence=evidence, dependencies=deps)
        assert result["status"] == "incomplete_no_headline_metrics", result
        assert result["models"] == {}
        assert "CSV parsing" not in result["error"]
    assert calls["predict"] == [] and calls["score"] == []
    assert not list((fixture.root / "results/classifier_test").glob("**/test_input_access_started.json"))
    assert not (fixture.root / evaluator.SUMMARY).exists()


@pytest.mark.parametrize("failure_kind", ["exception", "invalid_prediction", "interruption"])
def test_partial_failure_never_scores_a_subset_or_repeats_completed_inference(evaluator, artificial_project, frozen_api, metric_api, failure_kind):
    fixture = artificial_project
    deps, calls, evidence = _execution(fixture, evaluator, frozen_api, metric_api)
    original = deps["predict_one"]
    def fail_partway(handle, text):
        count = sum(family == "logistic_regression" for family, _text in calls["predict"])
        if handle["family"] == "logistic_regression" and count == 5:
            if failure_kind == "interruption": raise KeyboardInterrupt("artificial interruption")
            if failure_kind == "exception": raise ValueError("artificial incomplete model output")
            return {"predicted_class_index": 99, "predicted_label": "unknown"}
        return original(handle, text)
    deps["predict_one"] = fail_partway
    if failure_kind == "interruption":
        with pytest.raises(KeyboardInterrupt):
            evaluator.execute(fixture.root, emit=lambda _message: None, software_evidence=evidence, dependencies=deps)
    else:
        result = evaluator.execute(fixture.root, emit=lambda _message: None, software_evidence=evidence, dependencies=deps)
        assert result["status"] == "incomplete_no_headline_metrics"
        assert result["models"] == {}
    assert len(calls["predict"]) == 22
    assert calls["score"] == []
    assert not list((fixture.root / "results/classifier_test").glob("**/metrics.json"))
    before = list(calls["predict"])
    again = evaluator.execute(fixture.root, emit=lambda _message: None, software_evidence=evidence, dependencies=deps)
    assert again["status"] == "incomplete_no_headline_metrics", again
    assert calls["predict"] == before
    assert sum(family == "majority" for family, _text in calls["predict"]) == 17
    assert not (fixture.root / evaluator.SUMMARY).exists()


def test_tampered_completed_prediction_blocks_reuse_before_new_inference(evaluator, artificial_project, frozen_api, metric_api):
    fixture = artificial_project
    deps, calls, evidence = _execution(fixture, evaluator, frozen_api, metric_api)
    result = evaluator.execute(fixture.root, emit=lambda _message: None, software_evidence=evidence, dependencies=deps)
    assert result["status"] == "complete", result
    path = (fixture.root / result["summary_path"]).parent / "majority/predictions.jsonl"
    path.write_bytes(path.read_bytes() + b"{}\n")
    before = copy.deepcopy(calls)
    with pytest.raises(ValueError, match="changed"):
        evaluator.execute(fixture.root, emit=lambda _message: None, software_evidence=evidence, dependencies=deps)
    assert calls == before


def test_native_yes_no_eligibility_convention_keeps_excluded_records_out(evaluator):
    rows, groups, protocol, metric, summary, _ = _artificial_tables()
    for row in rows: row["benchmark_eligible"] = "yes"
    excluded = {**rows[0], "catalog_id": "excluded_artificial", "benchmark_eligible": "no", "split": "", "target_label": "", "class_index": ""}
    rows.append(excluded)
    groups.append({key: excluded[key] for key in ("catalog_id", "split_group_id", "source_sha256", "preparation_version")})
    summary["population"]["source_records"] += 1
    selected = evaluator.validate_population(rows, groups, protocol, metric, summary)
    assert len(selected) == 17
    assert "excluded_artificial" not in {row["catalog_id"] for row in selected}


def test_benchmark_target_is_authoritative_even_when_original_source_label_differs(evaluator, frozen_api):
    rows, groups, protocol, metric, summary, catalog = _artificial_tables()
    item = next(row for row in rows if row["catalog_id"] == "test_0")
    item["target_label"], item["class_index"] = protocol["class_order"][1], "1"
    selected = evaluator.validate_population(rows, groups, protocol, metric, summary)
    prepared = evaluator.align_catalog(selected, catalog, frozen_api, all_metadata=rows)
    aligned = next(row for row in prepared if row["catalog_id"] == "test_0")
    assert aligned["target_label"] == protocol["class_order"][1]
    assert item["body_part_prepared"] == protocol["class_order"][0]
    assert protocol["class_order"][1] not in aligned["canonical_text"]


def test_different_existing_public_summary_blocks_before_any_new_predictions(evaluator, artificial_project, frozen_api, metric_api):
    fixture = artificial_project
    deps, calls, evidence = _execution(fixture, evaluator, frozen_api, metric_api)
    path = fixture.root / "results/classifier_test/injected_test_summary.json"
    _write_json(path, {"evaluation_id": "another-evaluation", "status": "preserved-earlier-result"})
    previous = path.read_bytes()
    with pytest.raises(ValueError):
        evaluator.execute(fixture.root, emit=lambda _message: None, software_evidence=evidence, dependencies=deps)
    assert calls["predict"] == [] and calls["load"] == []
    assert path.read_bytes() == previous


@pytest.mark.parametrize("defect", ["missing", "extra", "duplicate_id", "unexpected_id", "input_hash", "group", "label", "receipt_identity", "receipt_family", "record_family", "record_release", "record_scope"])
def test_saved_prediction_join_rejects_incomplete_or_misaligned_output_without_subset_scoring(evaluator, tmp_path, defect):
    root = tmp_path.resolve()
    folder = root / "results/majority"
    folder.mkdir(parents=True)
    classes = ["synthetic_class_" + str(i) for i in range(16)]
    prepared = [{"catalog_id": "artificial_" + str(i), "split_group_id": "artificial_group_" + str(i),
        "input_hash": str(i) * 64} for i in (1, 2)]
    values = [{**row, "predicted_class_index": 0, "predicted_label": classes[0],
        "probabilities": [1.0] + [0.0] * 15, "logits": None, "model_family": "majority",
        "release_id": "artificial-release", "input_scope": "artificial_evaluator_test"} for row in prepared]
    if defect == "missing": values.pop()
    elif defect == "extra": values.append(copy.deepcopy(values[0]))
    elif defect == "duplicate_id": values[1]["catalog_id"] = values[0]["catalog_id"]
    elif defect == "unexpected_id": values[1]["catalog_id"] = "unexpected_artificial_id"
    elif defect == "input_hash": values[1]["input_hash"] = "9" * 64
    elif defect == "group": values[1]["split_group_id"] = "wrong_group"
    elif defect == "label": values[1]["predicted_label"] = classes[1]
    elif defect == "record_family": values[1]["model_family"] = "neural"
    elif defect == "record_release": values[1]["release_id"] = "different-release"
    elif defect == "record_scope": values[1]["input_scope"] = "synthetic"
    path = folder / "predictions.jsonl"
    path.write_bytes(b"".join(evaluator.canonical(value) + b"\n" for value in values))
    evaluator.save_once(folder / "completed.json", {"evaluation_id": "wrong" if defect == "receipt_identity" else "artificial_id",
        "family": "neural" if defect == "receipt_family" else "majority",
        "files": {path.relative_to(root).as_posix(): evaluator.sha(path.read_bytes())}})
    with pytest.raises(ValueError):
        evaluator._read_predictions(root, folder, prepared, classes, "artificial_id", "artificial-release")


def test_finished_public_summary_is_bound_on_zero_inference_reuse(evaluator, artificial_project, frozen_api, metric_api):
    fixture = artificial_project
    deps, calls, evidence = _execution(fixture, evaluator, frozen_api, metric_api)
    result = evaluator.execute(fixture.root, emit=lambda _message: None, software_evidence=evidence, dependencies=deps)
    assert result["status"] == "complete", result
    target = fixture.root / "results/classifier_test/injected_test_summary.json"
    value = json.loads(target.read_bytes())
    value["models"]["majority"]["accuracy"] = 0.999
    _write_json(target, value)
    before = copy.deepcopy(calls)
    with pytest.raises(ValueError):
        evaluator.execute(fixture.root, emit=lambda _message: None, software_evidence=evidence, dependencies=deps)
    assert calls == before


@pytest.mark.parametrize("defect", [None, "cuda_build", "hardware", "initialized_workspace"])
def test_frozen_numerical_runtime_is_restored_before_cuda_work_and_mismatches_rejected(evaluator, monkeypatch, defect):
    """A fake Torch API checks control ordering without loading Torch or any model."""
    import sys
    runtime = {"cpu_intraop_threads": 12, "cpu_interop_threads": 12, "cublas_workspace_config": ":4096:8",
        "deterministic_algorithms": True, "deterministic_warn_only": False, "cudnn_benchmark": False,
        "cudnn_deterministic": True, "float32_precision": {"api": "fp32_precision", "global": "ieee", "cuda_matmul": "ieee", "cudnn": "ieee"},
        "cuda_build": "12.6", "cudnn_version": 91002, "device_name": "Artificial GPU", "cuda_compute_capability": [8, 6]}
    state = {"intra": 1, "interop": 1, "deterministic": False, "warn": True}
    events = []
    cudnn = SimpleNamespace(benchmark=True, deterministic=False, fp32_precision="tf32", version=lambda: 91002)
    backends = SimpleNamespace(cudnn=cudnn, cuda=SimpleNamespace(matmul=SimpleNamespace(fp32_precision="tf32")), fp32_precision="tf32")
    def set_threads(key, count):
        events.append(key)
        state[key] = count
    def set_deterministic(enabled, *, warn_only):
        events.append("deterministic")
        state.update(deterministic=enabled, warn=warn_only)
    def available():
        events.append("cuda_available")
        assert os.environ["CUBLAS_WORKSPACE_CONFIG"] == runtime["cublas_workspace_config"]
        assert state == {"intra": 12, "interop": 12, "deterministic": True, "warn": False}
        assert backends.fp32_precision == backends.cuda.matmul.fp32_precision == cudnn.fp32_precision == "ieee"
        assert cudnn.benchmark is False and cudnn.deterministic is True
        return True
    cuda = SimpleNamespace(is_initialized=lambda: defect == "initialized_workspace", is_available=available, device_count=lambda: 1,
        get_device_name=lambda _index: "Other artificial GPU" if defect == "hardware" else "Artificial GPU",
        get_device_capability=lambda _index: (8, 6), get_device_properties=lambda _index: SimpleNamespace(total_memory=123456))
    torch = SimpleNamespace(cuda=cuda, backends=backends, version=SimpleNamespace(cuda="12.7" if defect == "cuda_build" else "12.6"),
        get_num_threads=lambda: state["intra"], set_num_threads=lambda count: set_threads("intra", count),
        get_num_interop_threads=lambda: state["interop"], set_num_interop_threads=lambda count: set_threads("interop", count),
        use_deterministic_algorithms=set_deterministic, are_deterministic_algorithms_enabled=lambda: state["deterministic"],
        is_deterministic_algorithms_warn_only_enabled=lambda: state["warn"])
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(evaluator.importlib.metadata, "version", lambda _name: "artificial-version")
    monkeypatch.setenv("CUBLAS_WORKSPACE_CONFIG", ":16:8")
    source = {"protocol": {"dependencies": {"python": evaluator.platform.python_version(), "packages": {"torch": "artificial-version"}},
        "unicode_database": evaluator.unicodedata.unidata_version}, "release": {"identity": {"reference_runtime": runtime}}}
    if defect:
        with pytest.raises(ValueError, match="workspace|runtime|device"):
            evaluator.verify_environment(source)
        if defect == "initialized_workspace":
            assert events == []
        else:
            assert events[-1] == "cuda_available"
    else:
        result = evaluator.verify_environment(source)
        assert result["runtime"] == runtime
        assert result["device_total_memory_bytes"] == 123456
        assert events == ["intra", "interop", "deterministic", "cuda_available"]
