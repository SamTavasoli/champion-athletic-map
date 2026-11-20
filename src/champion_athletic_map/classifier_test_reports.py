"""Write classifier findings from complete saved predictions without model access."""

from collections import Counter
import csv
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path

FAMILIES = ("majority", "logistic_regression", "neural")
LABELS = {"majority": "Majority baseline", "logistic_regression": "L5 logistic regression",
          "neural": "N3 neural classifier (seed 42)"}


def report_environment():
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import numpy as np
    figure, _ = plt.subplots(figsize=(1, 1))
    stream = io.BytesIO()
    figure.savefig(stream, format="png")
    plt.close(figure)
    if not stream.getvalue().startswith(b"\x89PNG"):
        raise ValueError("The report plotting check did not produce a PNG.")
    return {"matplotlib": importlib.metadata.version("matplotlib"),
            "numpy": np.__version__, "backend": matplotlib.get_backend()}


def _write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8") if isinstance(content, str) else content
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("A saved classifier report was preserved: " + str(path))
    else:
        with path.open("xb") as handle:
            handle.write(data)


def _csv(path, rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    _write(path, stream.getvalue())


def _heatmaps(folder, classes, results, *, normalized):
    import matplotlib.pyplot as plt
    import numpy as np
    key = "confusion_row_proportions" if normalized else "confusion_counts"
    arrays = [np.array([[float("nan") if value is None else value for value in row]
                       for row in results[family][key]], dtype=float) for family in FAMILIES]
    scale = 1.0 if normalized else max(float(np.nanmax(array)) for array in arrays)
    figure, axes = plt.subplots(1, 3, figsize=(24, 8), constrained_layout=True)
    cmap = plt.get_cmap("Blues").copy()
    cmap.set_bad("#dddddd")
    for family, array, axis in zip(FAMILIES, arrays, axes):
        image = axis.imshow(np.ma.masked_invalid(array), vmin=0, vmax=max(scale, 1), cmap=cmap)
        axis.set_xticks(range(len(classes)), classes, rotation=90, fontsize=8)
        axis.set_yticks(range(len(classes)), classes, fontsize=8)
        axis.set_xlabel("Predicted label")
        axis.set_ylabel("Actual label")
        axis.set_title(LABELS[family], fontsize=11)
        for i in range(len(classes)):
            for j in range(len(classes)):
                value = array[i, j]
                if not np.isfinite(value) or value == 0:
                    continue
                text = f"{value:.2f}" if normalized else str(int(value))
                axis.text(j, i, text, ha="center", va="center", fontsize=6,
                          color="white" if value > scale * .55 else "#202020")
    figure.colorbar(image, ax=list(axes), fraction=.015,
                    label="Proportion within actual label" if normalized else "Number of records")
    figure.suptitle("Classifier test confusion matrices — " + ("row proportions" if normalized else "counts"))
    target = folder / "figures" / ("classifier_test_confusion_normalized.png" if normalized
                                  else "classifier_test_confusion_counts.png")
    stream = io.BytesIO()
    figure.savefig(stream, format="png", dpi=150, metadata={"Software": "Champions Athletic Map"})
    plt.close(figure)
    _write(target, stream.getvalue())
    return target


def write_reports(root, folder, protocol, prepared, outputs, results, differences):
    """Require full ID alignment before writing any comparison tables or figures."""
    root, folder = Path(root), Path(folder)
    classes = protocol["class_order"]
    ids = [row["catalog_id"] for row in prepared]
    if not ids or len(ids) != len(set(ids)) or set(results) != set(FAMILIES) or set(outputs) != set(FAMILIES):
        raise ValueError("A classifier report needs the complete three-model comparison.")
    for family in FAMILIES:
        if ([row["catalog_id"] for row in outputs[family]] != ids
                or results[family]["n_records"] != len(ids) or results[family]["class_order"] != classes):
            raise ValueError("Classifier report coverage, order or class mapping differs.")

    rows, diagnostics, errors, metrics, per_class, matrices, checks = [], [], [], [], [], [], []
    error_totals = {}
    for position, source in enumerate(prepared):
        row = {key: source[key] for key in ("catalog_id", "split_group_id", "target_label", "class_index", "input_hash")}
        diagnostic = {**row, "name_only": source["name_only"],
                      "canonical_characters": len(source["canonical_text"]),
                      "canonical_utf8_bytes": len(source["canonical_text"].encode("utf-8"))}
        predictions = []
        for family in FAMILIES:
            prediction = outputs[family][position]
            row[family + "_predicted_label"] = prediction["predicted_label"]
            row[family + "_predicted_class_index"] = prediction["predicted_class_index"]
            predictions.append(prediction["predicted_label"])
            flags = prediction.get("handling_flags") or {}
            if family == "logistic_regression":
                for key in ("tfidf_nonzero_features", "tfidf_zero_vector"):
                    diagnostic[key] = flags.get(key)
            elif family == "neural":
                for key in ("raw_token_count", "effective_token_count", "retained_length", "truncated_tokens",
                            "unknown_tokens_before_truncation", "unknown_tokens_after_truncation",
                            "empty_token_fallback", "all_unknown_after_truncation"):
                    diagnostic[key] = flags.get(key)
            diagnostic[family + "_correct"] = prediction["predicted_label"] == source["target_label"]
        diagnostic["models_disagree"] = len(set(predictions)) > 1
        rows.append(row)
        diagnostics.append(diagnostic)

    for family in FAMILIES:
        scored = results[family]
        metrics.append({"model": family, "model_id": protocol["models"][family]["model_id"],
                        "accuracy": scored["accuracy"], "macro_f1": scored["macro_f1"],
                        "records": scored["n_records"], "groups": scored["n_groups"]})
        per_class.extend({"model": family, **row} for row in scored["per_class"])
        for i, actual in enumerate(classes):
            for j, predicted in enumerate(classes):
                matrices.append({"model": family, "actual_index": i, "predicted_index": j,
                                 "actual_label": actual, "predicted_label": predicted,
                                 "count": scored["confusion_counts"][i][j],
                                 "row_proportion": scored["confusion_row_proportions"][i][j]})
        wrong = []
        for source, prediction in zip(prepared, outputs[family]):
            if source["target_label"] != prediction["predicted_label"]:
                selection = hashlib.sha256((protocol["protocol_id"] + "|" + family + "|" + source["catalog_id"]).encode()).hexdigest()
                wrong.append({"model": family, "catalog_id": source["catalog_id"], "split_group_id": source["split_group_id"],
                              "target_label": source["target_label"], "predicted_label": prediction["predicted_label"],
                              "canonical_text": source["canonical_text"], "name_only": source["name_only"],
                              "selection_sha256": selection, "review_status": "not_human_reviewed"})
        wrong.sort(key=lambda item: item["selection_sha256"])
        errors.extend(wrong[:20])
        error_totals[family] = len(wrong)
        checks.append({"check": "complete_aligned_prediction_coverage", "model": family,
                       "status": "passed", "records": len(outputs[family])})
    checks.extend({"check": key, "model": "all", "status": "passed", "records": len(prepared)}
                  for key in ("same_frozen_targets_and_groups", "same_sixteen_class_order", "no_successful_subset_scores"))
    tables = {
        "predictions.csv": (rows, list(rows[0])),
        "metrics.csv": (metrics, list(metrics[0])),
        "per_class_metrics.csv": (per_class, list(per_class[0])),
        "input_diagnostics.csv": (diagnostics, list(diagnostics[0])),
        "confusion_matrices.csv": (matrices, list(matrices[0])),
        "evaluation_checks.csv": (checks, list(checks[0])),
        "error_review.csv": (errors, ["model", "catalog_id", "split_group_id", "target_label", "predicted_label",
                                       "canonical_text", "name_only", "selection_sha256", "review_status"]),
    }
    paths = []
    for name, (data, fields) in tables.items():
        _csv(folder / name, data, fields)
        paths.append(folder / name)
    paths.extend(_heatmaps(folder, classes, results, normalized=value) for value in (False, True))
    text = ["# Final exercise classifier findings", "",
            f"We evaluated the three preselected classifiers on {len(prepared)} records in {len({r['split_group_id'] for r in prepared})} exercise groups, using all {len(classes)} frozen labels.", "",
            "| Model | Macro-F1 | Accuracy | Errors |", "|---|---:|---:|---:|"]
    for family in FAMILIES:
        text.append(f"| {LABELS[family]} | {results[family]['macro_f1']:.4f} | {results[family]['accuracy']:.4f} | {error_totals[family]} |")
    text.extend(["", "Macro-F1 gives every frozen label equal weight, with zero_division=0. Accuracy is the proportion of records classified correctly. CSV and JSON scores retain full precision; this table rounds for display.", "",
                 "## Input and error review", "",
                 f"The test includes {sum(row['name_only'] for row in prepared)} name-only inputs. Inputs containing unfamiliar words and zero TF-IDF feature rows remain included. The input diagnostics table records the saved neural token, unknown-word and truncation counts alongside each model's correctness.", "",
                 f"The models disagree on {sum(row['models_disagree'] for row in diagnostics)} records. The error review contains up to 20 mistakes per model, ordered by SHA256(protocol ID, model family and catalog ID). These are examples for analysis; no human error ratings have been entered and no benchmark labels were changed.", ""])
    for family in FAMILIES:
        pairs = Counter((source["target_label"], prediction["predicted_label"])
                        for source, prediction in zip(prepared, outputs[family])
                        if source["target_label"] != prediction["predicted_label"])
        top = sorted(pairs.items(), key=lambda item: (-item[1], item[0]))[:5]
        description = "; ".join(f"{actual} → {predicted}: {count}" for (actual, predicted), count in top) or "No errors recorded."
        text.append(f"- {LABELS[family]} — most frequent actual → predicted errors: {description}")
    text.extend(["", "## Interpretation and limits", "",
                 "These scores measure agreement with this constructed exercise-label benchmark. They do not establish basketball-plan quality, athlete suitability or real-world safety. Related records were kept within their frozen groups, but full-source preparation and exploratory analysis took place before the benchmark freeze. Source labels may still contain errors or broad categories.", "",
                 "The confusion matrices use actual labels on rows and predicted labels on columns. Row proportions divide by actual-label support. An undefined row remains blank in the CSV and grey in the figure.", "",
                 "The error patterns are exploratory. We did not refit a model, select another seed, remove difficult examples or change targets after testing. The application keeps its validation-selected L5 model, and these test predictions are not added to the planner inputs. Human review and the planner experiment remain separate.", "",
                 "Confidence intervals and paired group-bootstrap comparisons are reserved for Step 35. The aligned prediction table retains catalog IDs, group IDs and the original targets for that analysis.", ""])
    report = folder / "classifier_test_findings.md"
    _write(report, "\n".join(text))
    paths.append(report)
    return [path.relative_to(root).as_posix() for path in paths]
