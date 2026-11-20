"""Report checks use artificial text and targets, never benchmark rows."""

import copy
import csv
import hashlib
import importlib.util
import os
from pathlib import Path

import pytest


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def _project():
    configured = os.environ.get("CHAMPION_CLASSIFIER_TEST_ROOT")
    if configured:
        return Path(configured)
    for root in (Path.cwd(), *Path.cwd().parents):
        if (root / "artifacts/evaluation/classifier_metrics_db3e5f3df78a126c/classifier_metrics.py").is_file():
            return root
    raise AssertionError("The frozen scorer source is required.")


@pytest.fixture
def reports_and_fixture(tmp_path):
    project = _project()
    helper = Path(os.environ.get("CHAMPION_STEP32_REPORT_PATH", project / "src/champion_athletic_map/classifier_test_reports.py"))
    reports = _load(helper, "step32_artificial_reports")
    scorer = _load(project / "artifacts/evaluation/classifier_metrics_db3e5f3df78a126c/classifier_metrics.py", "step32_report_scorer")
    classes = [f"artificial_label_{i}" for i in range(16)]
    protocol = {"protocol_id": "artificial_report_fixture", "class_order": classes,
                "models": {family: {"model_id": "artificial_" + family} for family in reports.FAMILIES}}
    prepared = [{"catalog_id": f"artificial_{i:03}", "split_group_id": f"artificial_group_{i}",
                 "target_label": classes[i % 16], "class_index": i % 16, "name_only": True,
                 "input_hash": hashlib.sha256(f"Artificial input {i}".encode()).hexdigest(),
                 "canonical_text": f"Artificial input {i}"} for i in range(35)]
    outputs, results = {}, {}
    for family in reports.FAMILIES:
        outputs[family] = [{"catalog_id": row["catalog_id"], "predicted_label": classes[0],
                            "predicted_class_index": 0, "handling_flags": {"raw_token_count": 3,
                            "retained_length": 3, "unknown_tokens_after_truncation": 1,
                            "tfidf_zero_vector": False, "tfidf_nonzero_features": 2}}
                           for row in prepared]
        results[family] = scorer.summarize_classifier_predictions([row["target_label"] for row in prepared],
                         [row["predicted_label"] for row in outputs[family]],
                         [row["split_group_id"] for row in prepared], classes)
    return reports, tmp_path, protocol, prepared, outputs, results


def test_reports_keep_complete_order_precision_and_deterministic_errors(reports_and_fixture):
    helper, root, protocol, prepared, outputs, results = reports_and_fixture
    folder = root / "results/classifier_test/artificial_reports"
    assert helper.report_environment()["backend"].casefold() == "agg"
    paths = helper.write_reports(root, folder, protocol, prepared, outputs, results, {})
    assert len(paths) == 10
    assert all((root / path).is_file() for path in paths)
    with (folder / "predictions.csv").open(newline="", encoding="utf-8") as stream:
        aligned = list(csv.DictReader(stream))
    assert [row["catalog_id"] for row in aligned] == [row["catalog_id"] for row in prepared]
    with (folder / "metrics.csv").open(newline="", encoding="utf-8") as stream:
        metrics = list(csv.DictReader(stream))
    assert float(metrics[0]["macro_f1"]) == results["majority"]["macro_f1"]
    with (folder / "confusion_matrices.csv").open(newline="", encoding="utf-8") as stream:
        matrices = list(csv.DictReader(stream))
    assert len(matrices) == 3 * 16 * 16
    assert matrices[0]["actual_label"] == protocol["class_order"][0]
    assert matrices[1]["predicted_label"] == protocol["class_order"][1]
    with (folder / "error_review.csv").open(newline="", encoding="utf-8") as stream:
        errors = list(csv.DictReader(stream))
    assert len(errors) == 60
    for family in helper.FAMILIES:
        chosen = [row for row in errors if row["model"] == family]
        assert [row["selection_sha256"] for row in chosen] == sorted(row["selection_sha256"] for row in chosen)
        assert all(row["review_status"] == "not_human_reviewed" for row in chosen)
        assert all(row["target_label"] != row["predicted_label"] for row in chosen)
    for name in ("classifier_test_confusion_counts.png", "classifier_test_confusion_normalized.png"):
        assert (folder / "figures" / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    note = (folder / "classifier_test_findings.md").read_text(encoding="utf-8")
    assert "Step 35" in note and "Source labels may still contain errors" in note
    snapshot = {name: (root / name).read_bytes() for name in paths}
    helper.write_reports(root, folder, protocol, prepared, outputs, results, {})
    assert all((root / name).read_bytes() == data for name, data in snapshot.items())


def test_reports_reject_partial_or_misaligned_comparisons_before_output(reports_and_fixture):
    helper, root, protocol, prepared, outputs, results = reports_and_fixture
    partial = copy.deepcopy(outputs)
    partial["neural"] = partial["neural"][:-1]
    folder = root / "should_not_exist"
    with pytest.raises(ValueError, match="coverage"):
        helper.write_reports(root, folder, protocol, prepared, partial, results, {})
    assert not folder.exists()
