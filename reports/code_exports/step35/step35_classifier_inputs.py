"""Read-only Step 32 evidence adapter. Never imports or loads a fitted model."""

import csv
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath


EXPECTED_PROTOCOL_ID = "020a5ce67c9ecc046548479c8bd17ee1fa51cfd3912457340924bef11a9fb49f"
FAMILIES = ("majority", "logistic_regression", "neural")
SUMMARY = "results/step32_classifier_test_summary.json"


class ClassifierInputError(ValueError):
    """Saved classifier evidence violates its original evaluation contract."""


class MissingClassifierInput(ClassifierInputError):
    """Required saved production evidence is unavailable; no substitute is used."""


def _require(condition, reason):
    if not condition:
        raise ClassifierInputError(reason)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique(items):
    result = {}
    for key, value in items:
        _require(key not in result, "Duplicate JSON key in classifier evidence: " + key)
        result[key] = value
    return result


class _Reader:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.hashes = {}

    def raw(self, name, expected=None):
        _require(isinstance(name, str) and name and "\\" not in name and ":" not in name,
                 "Invalid classifier evidence path.")
        relative = PurePosixPath(name)
        _require(not relative.is_absolute() and relative.as_posix() == name
                 and not set(relative.parts) & {".", ".."}, "Invalid classifier evidence path: " + name)
        path = self.root / name
        if not path.is_file():
            raise MissingClassifierInput("Missing saved classifier input: " + name
                                         + ". Step 35 does not generate predictions or use development substitutes.")
        _require(path.resolve() == path and path.is_relative_to(self.root),
                 "Linked or escaping classifier evidence path: " + name)
        raw = path.read_bytes()
        actual = _sha(raw)
        if expected is not None:
            _require(actual == expected, "Classifier input SHA256 differs: " + name)
        if name in self.hashes:
            _require(self.hashes[name] == actual, "Classifier input changed while reading: " + name)
        self.hashes[name] = actual
        return raw

    def json(self, name, expected=None):
        return json.loads(self.raw(name, expected).decode("utf-8-sig"), object_pairs_hook=_unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ClassifierInputError("Nonfinite JSON in classifier input.")))

    def csv(self, name, expected=None):
        reader = csv.DictReader(io.StringIO(self.raw(name, expected).decode("utf-8-sig"), newline=""))
        _require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames),
                 "Invalid classifier CSV header: " + name)
        rows = list(reader)
        _require(all(None not in row and all(value is not None for value in row.values()) for row in rows),
                 "Malformed classifier CSV: " + name)
        return rows

    def jsonl(self, name, expected=None):
        rows = []
        for line in self.raw(name, expected).decode("utf-8-sig").splitlines():
            _require(bool(line.strip()), "Blank row in classifier JSONL: " + name)
            rows.append(json.loads(line, object_pairs_hook=_unique,
                                   parse_constant=lambda value: (_ for _ in ()).throw(
                                       ClassifierInputError("Nonfinite JSON in classifier predictions."))))
        return rows

    def verify(self, bindings):
        _require(isinstance(bindings, dict) and bindings, "Classifier receipt has no file hashes.")
        for name, expected in sorted(bindings.items()):
            self.raw(name, expected)


def _by_id(rows, key, description):
    _require(all(isinstance(row, dict) and isinstance(row.get(key), str) and row[key] for row in rows),
             "Missing identifier in " + description)
    mapping = {row[key]: row for row in rows}
    _require(len(mapping) == len(rows), "Duplicate identifier in " + description)
    return mapping


def _eligible(value):
    _require(value in ("yes", "no", "True", "False", "true", "false", "1", "0"),
             "Invalid frozen classifier eligibility value.")
    return value in ("yes", "True", "true", "1")


def _prediction(value, classes):
    index, scores = value.get("predicted_class_index"), value.get("probabilities")
    _require(type(index) is int and 0 <= index < len(classes)
             and value.get("predicted_label") == classes[index], "Invalid classifier prediction label/index.")
    _require(isinstance(scores, list) and len(scores) == len(classes)
             and all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in scores)
             and math.isclose(sum(scores), 1, rel_tol=1e-5, abs_tol=1e-6)
             and index == max(range(len(classes)), key=lambda position: scores[position]),
             "Invalid classifier probability vector or class alignment.")
    logits = value.get("logits")
    _require(logits is None or isinstance(logits, list) and len(logits) == len(classes)
             and all(type(p) in (int, float) and math.isfinite(p) for p in logits),
             "Invalid classifier neural logits.")


def _load_classifier(root):
    """Return complete aligned production records or raise an explicit input error.

    Hashes are checked from receipts and the original frozen protocol. Historical
    planner source bindings remain provenance: later planner amendments need not
    restore obsolete planner source bytes. Classifier artifacts and metadata are
    checked against their original bindings. No outputs are written.
    """
    reader = _Reader(root)
    summary = reader.json(SUMMARY)
    _require(summary.get("status") == "complete" and summary.get("all_models_complete") is True
             and summary.get("injected_test_dependencies") is False,
             "Classifier results are incomplete or artificial; complete saved production predictions are required.")
    evaluation_id = summary.get("evaluation_id")
    _require(isinstance(evaluation_id, str) and len(evaluation_id) == 64
             and all(char in "0123456789abcdef" for char in evaluation_id), "Invalid classifier evaluation identity.")
    folder = "results/classifier_test/heldout_" + evaluation_id[:20]
    _require(summary.get("summary_path") == folder + "/summary.json", "Classifier summary points outside its designated evaluation.")
    _require(reader.raw(SUMMARY) == reader.raw(folder + "/summary.json"),
             "Classifier public and run summaries differ.")
    pointer = reader.json("results/classifier_test/selected_evaluation.json")
    _require(pointer == {"evaluation_id": evaluation_id, "manifest_path": folder + "/manifest.json"},
             "Classifier selected-evaluation pointer differs.")
    manifest = reader.json(folder + "/manifest.json")
    identity = {key: value for key, value in manifest.items() if key != "evaluation_id"}
    _require(manifest.get("evaluation_id") == evaluation_id == _sha(_canonical(identity)),
             "Classifier evaluation manifest identity differs.")
    _require(manifest.get("mode") == "heldout" and manifest.get("injected_test_dependencies") is False
             and manifest.get("family_order") == list(FAMILIES)
             and manifest.get("protocol_id") == summary.get("protocol_id") == EXPECTED_PROTOCOL_ID,
             "Classifier evaluation scope, families or frozen protocol differs.")
    receipt = reader.json(folder + "/completed.json")
    required = {SUMMARY, folder + "/summary.json", folder + "/manifest.json", folder + "/alignment.csv",
                folder + "/predictions.csv", folder + "/population_audit.json", folder + "/prepared_inputs_receipt.json",
                folder + "/prepared_inputs.json"}
    required |= {folder + "/" + family + "/" + filename
                 for family in FAMILIES for filename in ("predictions.jsonl", "completed.json")}
    _require(receipt.get("evaluation_id") == evaluation_id and required <= set(receipt.get("files", {})),
             "Classifier completion receipt does not bind the complete evaluation.")
    reader.verify(receipt["files"])

    checkpoint_path = "results/step31_protocol_checkpoint_summary.json"
    historical = manifest.get("source_file_sha256", {})
    _require(checkpoint_path in historical, "Classifier manifest omits the original protocol checkpoint.")
    checkpoint = reader.json(checkpoint_path, historical[checkpoint_path])
    _require(checkpoint.get("classifier_protocol_frozen") is True
             and checkpoint.get("injected_test_dependencies") is False
             and checkpoint.get("classifier_protocol_id") == EXPECTED_PROTOCOL_ID,
             "Classifier checkpoint is not the frozen production checkpoint.")
    protocol_path = checkpoint["classifier_protocol_path"]
    _require(protocol_path in historical, "Classifier manifest omits its frozen protocol.")
    protocol = reader.json(protocol_path, historical[protocol_path])
    _require(_sha(_canonical({key: value for key, value in protocol.items() if key != "protocol_id"}))
             == protocol.get("protocol_id") == EXPECTED_PROTOCOL_ID,
             "Classifier protocol identity differs.")
    _require(protocol.get("classifier_protocol_frozen") is True and protocol.get("injected_test_dependencies") is False
             and protocol.get("test_predictions_created") == 0 and protocol.get("heldout_text_parsed") is False,
             "Classifier original pre-test boundary differs.")
    bindings = protocol["source_file_sha256"]
    _require(bindings == checkpoint["source_file_sha256"]
             and all(historical.get(name) == expected for name, expected in bindings.items()),
             "Classifier checkpoint, protocol and historical source bindings differ.")
    classes = protocol["class_order"]
    _require(len(classes) == 16 and len(set(classes)) == 16
             and protocol["class_to_index"] == {label: i for i, label in enumerate(classes)},
             "Frozen classifier class mapping differs.")
    analysis = protocol["analysis"]
    analysis_path = str(PurePosixPath(protocol_path).parent / "analysis_config.json")
    _require(reader.json(analysis_path) == analysis, "Classifier standalone and protocol-embedded analysis configurations differ.")
    _require(analysis.get("class_order") == classes and analysis.get("record_id_field") == "catalog_id"
             and analysis.get("group_id_field") == "split_group_id"
             and analysis.get("target_field") == "target_label", "Frozen classifier analysis mapping differs.")
    _require(analysis.get("primary_metric") == {"name": "macro_f1", "average": "macro",
                                               "labels": "all_frozen_classes_in_saved_order", "zero_division": 0},
             "Frozen classifier metric convention differs.")

    release_path = protocol["release_manifest_path"]
    release = reader.json(release_path, bindings[release_path])
    release_base = str(PurePosixPath(release_path).parent)
    _require(release.get("release_id") == protocol["classifier_release_id"]
             and release["identity"]["artifacts"] == protocol["models"]
             and release["identity"]["benchmark_id"] == protocol["benchmark_id"]
             and release["identity"]["class_order"] == classes
             and release["identity"]["class_to_index"] == protocol["class_to_index"],
             "Classifier release/model identity differs.")
    for name, item in release["identity"]["payloads"].items():
        raw = reader.raw(release_base + "/" + name, item["sha256"])
        _require(len(raw) == item["bytes"], "Classifier release payload size differs: " + name)
    _require(protocol["models"]["logistic_regression"]["candidate_id"] == "L5"
             and protocol["models"]["neural"]["candidate_id"] == "N3"
             and protocol["models"]["neural"]["seed"] == 42
             and protocol["models"]["neural"]["best_epoch"] == 19,
             "Preselected classifier configuration differs.")
    for item in protocol["models"].values():
        source = item["source"]
        reader.raw(source["relative_path"], source["sha256"])

    split_path = "data/processed/exercise_split_manifest.csv"
    group_path = "data/processed/exercise_groups.csv"
    split_rows = reader.csv(split_path, bindings[split_path])
    group_rows = reader.csv(group_path, bindings[group_path])
    split = reader.json("results/step15_exercise_split_summary.json", bindings["results/step15_exercise_split_summary.json"])
    metrics_path = str(PurePosixPath(protocol["metric_scorer_path"]).parent / "classifier_metric_config.json")
    metrics = reader.json(metrics_path, bindings[metrics_path])
    for source in (split, metrics):
        _require(source["benchmark_id"] == protocol["benchmark_id"] and source["class_order"] == classes
                 and source["class_to_index"] == protocol["class_to_index"], "Classifier frozen metadata identities differ.")
    all_ids, groups = _by_id(split_rows, "catalog_id", "split manifest"), _by_id(group_rows, "catalog_id", "group manifest")
    _require(set(all_ids) == set(groups) and len(split_rows) == split["population"]["source_records"],
             "Classifier source population/group coverage differs.")
    selected, partition_groups, partition_counts = {}, {}, {}
    for record_id, row in all_ids.items():
        group = groups[record_id]
        _require(row["split_group_id"] and group["split_group_id"] == row["split_group_id"]
                 and group["source_sha256"] == row["source_sha256"]
                 and group["preparation_version"] == row["preparation_version"],
                 "Classifier group/source alignment differs: " + record_id)
        if not _eligible(row["benchmark_eligible"]):
            _require(row["split"] not in ("train", "validation", "test"), "Excluded classifier record entered a model split.")
            continue
        _require(row["split"] in ("train", "validation", "test") and row["target_label"] in classes
                 and row["class_index"] == str(protocol["class_to_index"][row["target_label"]]),
                 "Invalid classifier frozen target or partition.")
        partition_groups.setdefault(row["split"], set()).add(row["split_group_id"])
        partition_counts[row["split"]] = partition_counts.get(row["split"], 0) + 1
        if row["split"] == "test":
            selected[record_id] = row
    _require(all(not partition_groups[a] & partition_groups[b]
                 for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))),
             "Frozen classifier exercise groups leak across partitions.")
    for support in metrics["split_support"]:
        _require(partition_counts[support["split"]] == support["records"]
                 and len(partition_groups[support["split"]]) == support["groups"], "Classifier frozen split support differs.")
    expected = protocol["test_population_from_frozen_metadata"]
    _require(len(selected) == summary.get("records") == expected["records"] == 438
             and len(partition_groups["test"]) == summary.get("groups") == expected["groups"] == 385
             and summary.get("class_count") == 16
             and {row["target_label"] for row in selected.values()} == set(classes),
             "Classifier test population or original sixteen-class coverage differs.")
    alignment = _by_id(reader.csv(folder + "/alignment.csv"), "catalog_id", "test alignment")
    table = _by_id(reader.csv(folder + "/predictions.csv"), "catalog_id", "aligned predictions")
    _require(set(alignment) == set(table) == set(selected), "Classifier aligned prediction coverage is incomplete or unexpected.")
    prepared_receipt = reader.json(folder + "/prepared_inputs_receipt.json")
    _require(prepared_receipt.get("evaluation_id") == evaluation_id
             and folder + "/prepared_inputs.json" in prepared_receipt.get("files", {}),
             "Classifier prepared inputs lack an original matching receipt.")
    reader.verify(prepared_receipt["files"])
    prepared_value = reader.json(folder + "/prepared_inputs.json")
    _require(prepared_value.get("evaluation_id") == evaluation_id, "Classifier prepared inputs belong to another evaluation.")
    prepared = _by_id(prepared_value["records"], "catalog_id", "prepared test inputs")
    _require(set(prepared) == set(selected), "Classifier prepared test population differs.")
    population = reader.json(folder + "/population_audit.json")
    _require(population.get("records") == 438 and population.get("groups") == 385
             and population.get("class_order") == classes and population.get("split_group_leakage") is False
             and population.get("catalog_ids") == sorted(selected), "Classifier saved population audit differs.")
    outputs = {}
    for family in FAMILIES:
        model_folder = folder + "/" + family
        model_receipt = reader.json(model_folder + "/completed.json")
        prediction_path = model_folder + "/predictions.jsonl"
        _require(model_receipt.get("evaluation_id") == evaluation_id and model_receipt.get("family") == family
                 and model_receipt.get("records") == 438 and prediction_path in model_receipt.get("files", {}),
                 "Classifier model predictions lack a complete matching receipt: " + family)
        reader.verify(model_receipt["files"])
        predictions = _by_id(reader.jsonl(prediction_path), "catalog_id", family + " predictions")
        _require(set(predictions) == set(selected), "Classifier model coverage is incomplete or unexpected: " + family)
        outputs[family] = predictions
    records = []
    for record_id in sorted(selected):
        frozen, aligned, joined, original = selected[record_id], alignment[record_id], table[record_id], prepared[record_id]
        for row in (aligned, joined):
            _require(all(row[key] == frozen[key] for key in ("split_group_id", "target_label", "class_index")),
                     "Classifier target/group alignment changed: " + record_id)
        _require(aligned["input_hash"] == joined["input_hash"], "Classifier input hash alignment changed.")
        _require(original["target_label"] == frozen["target_label"]
                 and original["class_index"] == int(frozen["class_index"])
                 and original["split_group_id"] == frozen["split_group_id"]
                 and original["input_hash"] == aligned["input_hash"] == _sha(original["canonical_text"].encode("utf-8")),
                 "Classifier original prepared input hash/target/group differs.")
        predicted = {}
        for family in FAMILIES:
            value = outputs[family][record_id]
            _prediction(value, classes)
            _require(value.get("input_scope") == "heldout_benchmark_test" and value.get("model_family") == family
                     and value.get("release_id") == protocol["classifier_release_id"]
                     and value.get("split_group_id") == frozen["split_group_id"]
                     and value.get("input_hash") == aligned["input_hash"]
                     and joined[family + "_predicted_label"] == value["predicted_label"]
                     and joined[family + "_predicted_class_index"] == str(value["predicted_class_index"]),
                     "Classifier prediction identity/alignment changed: " + family + "/" + record_id)
            predicted[family] = value["predicted_label"]
        records.append({"record_id": record_id, "group_id": frozen["split_group_id"],
                        "target_label": frozen["target_label"], "predictions": predicted})
    # A final byte check catches concurrent edits to any evidence read above.
    reader.verify(dict(reader.hashes))
    return {"records": records, "class_order": classes, "summary": summary,
            "analysis_config": analysis, "input_sha256": reader.hashes,
            "historical_source_sha256": historical, "evaluation_id": evaluation_id,
            "benchmark_id": protocol["benchmark_id"], "release_id": protocol["classifier_release_id"]}


def load_classifier(root):
    """Read saved native evidence, distinguishing missing inputs from invalid evidence."""
    try:
        return _load_classifier(root)
    except ClassifierInputError:
        raise
    except (KeyError, TypeError, IndexError, json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
        raise ClassifierInputError("Invalid saved classifier evidence: " + type(error).__name__ + ": " + str(error)) from error
