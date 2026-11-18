"""Evaluate the separately authorized, frozen exercise-classifier test population."""

from collections import Counter, defaultdict
from copy import deepcopy
import csv
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import unicodedata

VERSION = "heldout-classifier-evaluation-1"
CHECKPOINT = "results/step31_protocol_checkpoint_summary.json"
SUMMARY = "results/step32_classifier_test_summary.json"
EXPECTED_PROTOCOL_ID = "020a5ce67c9ecc046548479c8bd17ee1fa51cfd3912457340924bef11a9fb49f"
FAMILIES = ("majority", "logistic_regression", "neural")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative, "Invalid evaluation source path.")
    parts = PurePosixPath(relative)
    require(not parts.is_absolute() and parts.as_posix() == relative and not set(parts.parts) & {".", ".."}, "Invalid evaluation source path.")
    result = root / relative
    require(result.resolve() == result and result.is_relative_to(root) and result.is_file(), "Missing or linked evaluation source: " + relative)
    return result


def read(root, relative):
    def unique(items):
        out = {}
        for key, value in items:
            require(key not in out, "Duplicate JSON key in evaluation source.")
            out[key] = value
        return out
    return json.loads(checked(root, relative).read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON value.")))


def save_once(path, value, *, raw=False):
    data = value if raw else canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == data, "An immutable evaluation output changed: " + str(path))
    else:
        with path.open("xb") as handle:
            handle.write(data)


def verify(root, bindings):
    for name, expected in bindings.items():
        require(sha(checked(root, name).read_bytes()) == expected, "An evaluation source changed: " + name)


def module(root, relative):
    path = checked(root, relative)
    spec = importlib.util.spec_from_file_location("heldout_evaluation_" + sha(str(path).encode())[:12], path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def csv_rows(root, relative):
    with checked(root, relative).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), "Invalid CSV header: " + relative)
        rows = list(reader)
    require(all(None not in row and all(value is not None for value in row.values()) for row in rows), "Malformed CSV row: " + relative)
    return rows


def _true(value):
    require(value in ("yes", "no", "True", "False", "true", "false", "1", "0"), "Invalid frozen eligibility value.")
    return value in ("yes", "True", "true", "1")


def load_protocol(root, *, injected=False):
    root = Path(root).resolve()
    checkpoint = read(root, CHECKPOINT)
    require(checkpoint.get("classifier_protocol_frozen") is True and checkpoint.get("step32_preparation_may_continue") is True
            and checkpoint.get("injected_test_dependencies") is False, "The production classifier protocol checkpoint is required.")
    protocol_path = checkpoint["classifier_protocol_path"]
    protocol = read(root, protocol_path)
    identity = {key: value for key, value in protocol.items() if key != "protocol_id"}
    require(sha(canonical(identity)) == protocol.get("protocol_id") == checkpoint.get("classifier_protocol_id"), "The classifier protocol identity changed.")
    if not injected:
        require(protocol["protocol_id"] == EXPECTED_PROTOCOL_ID and protocol.get("injected_fixture") is not True,
                "The held-out evaluation is not the approved classifier protocol.")
    else:
        require(protocol.get("injected_fixture") is True, "Injected tests require an explicitly artificial protocol.")
    require(protocol.get("classifier_protocol_frozen") is True and protocol.get("models_fitted") == 0
            and protocol.get("test_predictions_created") == 0 and protocol.get("heldout_text_parsed") is False,
            "The frozen pre-test boundary is invalid.")
    bindings = deepcopy(protocol["source_file_sha256"])
    require(bindings == checkpoint["source_file_sha256"], "Checkpoint and protocol source bindings differ.")
    verify(root, bindings)
    bindings[protocol_path] = sha(checked(root, protocol_path).read_bytes())
    bindings[CHECKPOINT] = sha(checked(root, CHECKPOINT).read_bytes())
    split = read(root, "results/step15_exercise_split_summary.json")
    metrics_path = str(PurePosixPath(protocol["metric_scorer_path"]).parent / "classifier_metric_config.json")
    metrics = read(root, metrics_path)
    release_path = str(PurePosixPath(protocol["release_manifest_path"]).parent)
    release = read(root, protocol["release_manifest_path"])
    require(protocol["benchmark_id"] == split["benchmark_id"] == metrics["benchmark_id"] == release["identity"]["benchmark_id"], "Benchmark identities disagree.")
    classes = protocol["class_order"]
    require(len(classes) == 16 and len(set(classes)) == 16 and protocol["class_to_index"] == {label: i for i, label in enumerate(classes)}, "The frozen sixteen-class mapping changed.")
    require(all(item["class_order"] == classes and item["class_to_index"] == protocol["class_to_index"] for item in (split, metrics, release["identity"])), "Class mappings disagree.")
    require(protocol["models"] == release["identity"]["artifacts"] and protocol["classifier_release_id"] == release["release_id"], "The frozen comparison artifacts changed.")
    require(set(protocol["models"]) == set(FAMILIES) and protocol["models"]["logistic_regression"]["candidate_id"] == "L5"
            and protocol["models"]["neural"]["candidate_id"] == "N3" and protocol["models"]["neural"]["seed"] == 42
            and protocol["models"]["neural"]["best_epoch"] == 19
            and all(spec["fit_partition"] == "train" and spec["retrained_after_selection"] is False for spec in protocol["models"].values()), "The preselected training-only model comparison changed.")
    require(protocol["dependencies"] == release["identity"]["dependencies"] and protocol["unicode_database"] == release["identity"]["unicode_database"]
            and protocol["evaluation_device"] == release["identity"]["reference_inference_device"] == "cuda:0", "The frozen inference environment changed.")
    require(metrics["primary_metric"] == protocol["analysis"]["primary_metric"] == {"average": "macro", "labels": "all_frozen_classes_in_saved_order", "name": "macro_f1", "zero_division": 0}, "The primary metric changed.")
    for relative, spec in release["identity"]["payloads"].items():
        name = release_path + "/" + relative
        content = checked(root, name).read_bytes()
        require(len(content) == spec["bytes"] and sha(content) == spec["sha256"], "The release payload changed: " + name)
        bindings[name] = spec["sha256"]
    # These remain opaque bytes until all protocol, model and environment gates pass.
    for relative in ("data/processed/exercise_catalog.csv", "results/step10_exercise_preparation.json"):
        expected = split["input_hashes"][relative]
        require(sha(checked(root, relative).read_bytes()) == expected, "The original exercise preparation changed.")
        bindings[relative] = expected
    preparation = read(root, "results/step10_exercise_preparation.json")
    require(preparation["artifacts"]["catalog"]["sha256"] == bindings["data/processed/exercise_catalog.csv"], "Catalog preparation lineage changed.")
    parent = preparation["parent_source"]
    require(split["input_hashes"].get(parent["relative_path"]) == parent["sha256"], "Original exercise source lineage changed.")
    require(sha(checked(root, parent["relative_path"]).read_bytes()) == parent["sha256"], "The original source bytes changed.")
    bindings[parent["relative_path"]] = parent["sha256"]
    return {"root": root, "checkpoint": checkpoint, "protocol": protocol, "bindings": bindings, "split": split,
            "metrics": metrics, "release": release, "release_path": release_path, "preparation": preparation}


def verify_environment(source):
    protocol = source["protocol"]
    expected = protocol["dependencies"]
    require(platform.python_version() == expected["python"], "The recorded Python version is required for held-out inference.")
    actual = {name: importlib.metadata.version(name) for name in expected["packages"]}
    require(actual == expected["packages"] and unicodedata.unidata_version == protocol["unicode_database"], "The recorded dependency or Unicode versions differ.")
    import torch
    runtime = source["release"]["identity"]["reference_runtime"]
    workspace = runtime["cublas_workspace_config"]
    require(not torch.cuda.is_initialized() or os.environ.get("CUBLAS_WORKSPACE_CONFIG") == workspace,
            "CUDA was initialized before the frozen workspace configuration; start the dedicated evaluator process again.")
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = workspace
    if torch.get_num_threads() != runtime["cpu_intraop_threads"]:
        torch.set_num_threads(runtime["cpu_intraop_threads"])
    if torch.get_num_interop_threads() != runtime["cpu_interop_threads"]:
        torch.set_num_interop_threads(runtime["cpu_interop_threads"])
    torch.use_deterministic_algorithms(runtime["deterministic_algorithms"], warn_only=runtime["deterministic_warn_only"])
    torch.backends.cudnn.benchmark = runtime["cudnn_benchmark"]
    torch.backends.cudnn.deterministic = runtime["cudnn_deterministic"]
    precision = runtime["float32_precision"]
    require(precision["api"] == "fp32_precision", "The saved numerical precision API is unsupported.")
    torch.backends.fp32_precision = precision["global"]
    torch.backends.cuda.matmul.fp32_precision = precision["cuda_matmul"]
    torch.backends.cudnn.fp32_precision = precision["cudnn"]
    require(torch.cuda.is_available() and torch.cuda.device_count() > 0, "The frozen cuda:0 evaluation device is unavailable; no CPU substitution was made.")
    restored = {"cpu_intraop_threads": torch.get_num_threads(), "cpu_interop_threads": torch.get_num_interop_threads(),
        "cublas_workspace_config": os.environ.get("CUBLAS_WORKSPACE_CONFIG"),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        "deterministic_warn_only": torch.is_deterministic_algorithms_warn_only_enabled(),
        "cudnn_benchmark": torch.backends.cudnn.benchmark, "cudnn_deterministic": torch.backends.cudnn.deterministic,
        "float32_precision": {"api": "fp32_precision", "global": torch.backends.fp32_precision,
            "cuda_matmul": torch.backends.cuda.matmul.fp32_precision, "cudnn": torch.backends.cudnn.fp32_precision},
        "cuda_build": torch.version.cuda, "cudnn_version": torch.backends.cudnn.version(),
        "device_name": torch.cuda.get_device_name(0), "cuda_compute_capability": list(torch.cuda.get_device_capability(0))}
    require(all(restored[key] == runtime[key] for key in restored), "The frozen numerical runtime or CUDA device differs.")
    return {"python": platform.python_version(), "packages": actual, "unicode_database": unicodedata.unidata_version,
            "neural_device": "cuda:0", "runtime": restored,
            "device_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory}


def validate_population(split_rows, group_rows, protocol, metric_config, split_summary):
    require(len(split_rows) == split_summary["population"]["source_records"] and len(group_rows) == len(split_rows), "The frozen source population count changed.")
    identifiers = [row["catalog_id"] for row in split_rows]
    groups = {row["catalog_id"]: row for row in group_rows}
    require(all(identifiers) and len(set(identifiers)) == len(identifiers) and len(groups) == len(group_rows)
            and set(groups) == set(identifiers), "Missing, duplicate or unexpected catalog/group IDs.")
    classes = protocol["class_order"]
    selected, partition_groups, partition_rows = [], defaultdict(set), Counter()
    for row in split_rows:
        require(row["split_group_id"] and groups[row["catalog_id"]]["split_group_id"] == row["split_group_id"], "An original split-group assignment changed.")
        require(groups[row["catalog_id"]]["source_sha256"] == row["source_sha256"] and groups[row["catalog_id"]]["preparation_version"] == row["preparation_version"], "Group/source lineage differs.")
        if not _true(row["benchmark_eligible"]):
            require(row["split"] not in ("train", "validation", "test"), "An excluded record entered a model partition.")
            continue
        require(row["split"] in ("train", "validation", "test") and row["target_label"] in classes
                and str(protocol["class_to_index"][row["target_label"]]) == row["class_index"], "A frozen target, class index or partition changed.")
        partition_groups[row["split"]].add(row["split_group_id"])
        partition_rows[row["split"]] += 1
        if row["split"] == "test":
            selected.append(deepcopy(row))
    require(not (partition_groups["train"] & partition_groups["validation"] or partition_groups["train"] & partition_groups["test"]
                 or partition_groups["validation"] & partition_groups["test"]), "Split-group leakage was found before test text preparation.")
    for support in metric_config["split_support"]:
        require(partition_rows[support["split"]] == support["records"] and len(partition_groups[support["split"]]) == support["groups"], "Frozen partition support differs.")
    expected = protocol["test_population_from_frozen_metadata"]
    require(len(selected) == expected["records"] and len(partition_groups["test"]) == expected["groups"]
            and {row["target_label"] for row in selected} == set(classes), "The complete test population or sixteen-class coverage differs.")
    return sorted(selected, key=lambda row: row["catalog_id"])


def align_catalog(test_metadata, catalog_rows, inference_api, *, all_metadata=None):
    catalog = {row["catalog_id"]: row for row in catalog_rows}
    require(len(catalog) == len(catalog_rows), "Duplicate prepared catalog IDs.")
    if all_metadata is not None:
        require(set(catalog) == {row["catalog_id"] for row in all_metadata}, "The prepared catalog and split manifest have different IDs.")
    # Verify every selected source join before preparing the first feature string.
    for metadata in test_metadata:
        require(metadata["catalog_id"] in catalog, "A test catalog record is missing.")
        row = catalog[metadata["catalog_id"]]
        for key in ("split_group_id", "source_file", "source_sha256", "source_cleaned_record_position", "preparation_version"):
            require(row[key] == metadata[key], "The test record's source alignment changed: " + key)
        if "body_part_prepared" in metadata:
            require(row["body_part_prepared"] == metadata["body_part_prepared"], "The original source label metadata changed.")
    prepared = []
    for metadata in test_metadata:
        row = catalog[metadata["catalog_id"]]
        value = inference_api.prepare_exercise_input(row["exercise_name_prepared"], row["description_prepared"])
        require(value["canonical_text"] == row["classifier_text"], "The frozen feature allowlist or canonical input construction differs.")
        prepared.append({"catalog_id": metadata["catalog_id"], "split_group_id": metadata["split_group_id"],
            "target_label": metadata["target_label"], "class_index": int(metadata["class_index"]), **value})
    return prepared


def infer_one(handle, canonical_text, inference_api):
    """Use the verified saved routes in this dedicated held-out evaluator only."""
    flags = {}
    method = inference_api._prediction_neural if handle["family"] == "neural" else inference_api._prediction_sklearn
    index, probabilities, logits = method(handle, canonical_text, flags)
    classes = handle["class_order"]
    require(type(index) is int and 0 <= index < len(classes), "A model returned an invalid class index.")
    require(len(probabilities) == len(classes) and all(type(p) in (float, int) and math.isfinite(p) and 0 <= p <= 1 for p in probabilities)
            and math.isclose(sum(probabilities), 1, rel_tol=1e-5, abs_tol=1e-6)
            and index == max(range(len(classes)), key=lambda i: probabilities[i]), "A model returned invalid or misaligned scores.")
    return {"predicted_class_index": index, "predicted_label": classes[index], "probabilities": probabilities,
            "logits": logits, "handling_flags": flags}


def _csv_bytes(rows, fields):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _valid_prediction(value, classes):
    require(isinstance(value, dict) and type(value.get("predicted_class_index")) is int, "A prediction is missing its integer class index.")
    index, probabilities = value["predicted_class_index"], value.get("probabilities")
    require(0 <= index < len(classes) and value.get("predicted_label") == classes[index]
            and isinstance(probabilities, list) and len(probabilities) == len(classes)
            and all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1 for p in probabilities)
            and math.isclose(sum(probabilities), 1, rel_tol=1e-5, abs_tol=1e-6)
            and index == max(range(len(classes)), key=lambda i: probabilities[i]), "A prediction has invalid labels, scores or class alignment.")
    logits = value.get("logits")
    require(logits is None or isinstance(logits, list) and len(logits) == len(classes)
            and all(type(v) in (float, int) and math.isfinite(v) for v in logits), "A prediction has invalid neural logits.")
    canonical(value)


def _receipt(root, folder, identity):
    path = folder / "completed.json"
    if not path.exists():
        return None
    value = read(root, path.relative_to(root).as_posix())
    require(value.get("evaluation_id") == identity and value.get("family") == folder.name, "A completed model receipt belongs to another evaluation or model.")
    verify(root, value["files"])
    require((folder / "predictions.jsonl").relative_to(root).as_posix() in value["files"], "A receipt does not bind its model predictions.")
    return value


def _read_predictions(root, folder, prepared, classes, identity, release_id):
    require(_receipt(root, folder, identity) is not None, "Saved predictions have no verified terminal model receipt.")
    values = [json.loads(line) for line in (folder / "predictions.jsonl").read_bytes().splitlines()]
    require(len(values) == len(prepared) and [row.get("catalog_id") for row in values] == [row["catalog_id"] for row in prepared], "Model predictions do not completely align with the intended test IDs.")
    for value, source in zip(values, prepared):
        require(value.get("input_hash") == source["input_hash"] and value.get("split_group_id") == source["split_group_id"], "Prediction input/group alignment changed.")
        require(value.get("model_family") == folder.name and value.get("release_id") == release_id
                and value.get("input_scope") in ("heldout_benchmark_test", "artificial_evaluator_test"), "Prediction model or evaluation scope changed.")
        _valid_prediction(value, classes)
    return values


def execute(root, *, emit=print, software_evidence=None, dependencies=None):
    """Run the prespecified test once; verified terminal model outputs may be reused."""
    root = Path(root).resolve()
    injected = dependencies is not None
    deps = dict(dependencies or {})
    allowed = {"load_protocol", "verify_environment", "load_classifier", "verify_classifier_integrity", "predict_one", "summarize", "inference_api", "reports_api"}
    require(not (set(deps) - allowed), "Unknown test dependency injection.")
    source = (deps.get("load_protocol") or load_protocol)(root, injected=injected)
    protocol = source["protocol"]
    require(bool(protocol.get("injected_fixture")) is injected, "Artificial test dependencies and protocol scopes must agree.")
    bindings = deepcopy(source["bindings"])
    verify(root, bindings)
    evidence = deepcopy(software_evidence)
    require(isinstance(evidence, dict) and evidence.get("status") == "passed" and evidence.get("passed", 0) > 0
            and evidence.get("files"), "The dedicated classifier evaluator software checks must pass before test access.")
    verify(root, evidence["files"])
    evaluator = root / "src/champion_athletic_map/classifier_test_evaluation.py"
    require(evaluator.is_file(), "The installed dedicated evaluator source is required.")
    evaluator_hash = sha(evaluator.read_bytes())
    require(evidence.get("failed", 0) == 0 and evidence.get("not_completed", 0) == 0
            and evidence["files"].get("src/champion_athletic_map/classifier_test_evaluation.py") == evaluator_hash,
            "The successful software checks must bind this exact evaluator source.")
    reports = deps.get("reports_api") or module(root, "src/champion_athletic_map/classifier_test_reports.py")
    reports_path = root / "src/champion_athletic_map/classifier_test_reports.py"
    require(reports_path.is_file() and evidence["files"].get(reports_path.relative_to(root).as_posix()) == sha(reports_path.read_bytes()),
            "The successful software checks must bind the report helper source.")
    mode = "injected_test" if injected else "heldout"
    identity = {"schema_version": VERSION, "protocol_id": protocol["protocol_id"], "mode": mode,
        "injected_test_dependencies": injected, "source_file_sha256": bindings,
        "evaluator_sha256": evaluator_hash, "software_check_source_sha256": evidence["files"],
        "family_order": list(FAMILIES), "error_example_limit": 20,
        "error_selection": "ascending SHA256(protocol_id|family|catalog_id), wrong predictions only",
        "no_automatic_retraining_or_reselection": True, "no_completed_model_repetition": True}
    evaluation_id = sha(canonical(identity))
    relative = "results/classifier_test/" + ("injected_" if injected else "heldout_") + evaluation_id[:20]
    folder = root / relative
    target = root / ("results/classifier_test/injected_test_summary.json" if injected else SUMMARY)
    if target.exists():
        require(read(root, target.relative_to(root).as_posix()).get("evaluation_id") == evaluation_id
                and (folder / "completed.json").is_file() and (folder / "summary.json").is_file()
                and target.read_bytes() == (folder / "summary.json").read_bytes(),
                "A classifier test summary already exists without matching verified terminal evidence; no test inference was started.")
    pointer_path = root / "results/classifier_test" / ("injected_evaluation.json" if injected else "selected_evaluation.json")
    pointer = {"evaluation_id": evaluation_id, "manifest_path": relative + "/manifest.json"}
    if pointer_path.exists():
        require(read(root, pointer_path.relative_to(root).as_posix()) == pointer,
                "A classifier test evaluation is already selected. Preserve its exposure record; a different evaluator needs an explicit amendment.")
        require(read(root, pointer["manifest_path"]) == {**identity, "evaluation_id": evaluation_id}, "The selected evaluation manifest changed.")
    terminal = folder / "completed.json"
    if terminal.exists():
        receipt = read(root, terminal.relative_to(root).as_posix())
        require(receipt.get("evaluation_id") == evaluation_id and relative + "/summary.json" in receipt.get("files", {}), "Invalid complete evaluation receipt.")
        verify(root, receipt["files"])
        summary = read(root, relative + "/summary.json")
        return {**summary, "saved_execution_reused": True, "new_predictions": 0, "new_prediction_attempts": 0, "models_loaded_this_run": 0}
    stopped = folder / "failed.json"
    if stopped.exists():
        result = read(root, stopped.relative_to(root).as_posix())
        require(result["evaluation_id"] == evaluation_id, "The saved failure belongs to another evaluation.")
        verify(root, result["files"])
        return {**result["summary"], "saved_execution_reused": True, "new_predictions": 0, "new_prediction_attempts": 0, "models_loaded_this_run": 0}
    # Dependency/device/reporting failures precede any selected test attempt or text exposure.
    environment = (deps.get("verify_environment") or verify_environment)(source)
    environment["reports"] = reports.report_environment()
    save_once(folder / "manifest.json", {**identity, "evaluation_id": evaluation_id})
    save_once(pointer_path, pointer)
    lock = folder / "evaluation.lock"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError("An evaluation is running or its process stopped unexpectedly. No held-out inference was repeated.") from None
    os.close(descriptor)
    new_predictions, loaded, prediction_attempts = 0, 0, 0
    outputs, handles, stage = {}, {}, "environment_verification"
    summary, active_record = None, None
    try:
        save_once(folder / "environment.json", environment)
        inference_path = source.get("inference_path") or source["release_path"] + "/src/champion_athletic_map/classifier_inference.py"
        inference_api = deps.get("inference_api") or module(root, inference_path)
        load_handle = deps.get("load_classifier") or inference_api.load_classifier
        integrity = deps.get("verify_classifier_integrity") or inference_api.verify_classifier_integrity
        predict = deps.get("predict_one") or (lambda handle, text: infer_one(handle, text, inference_api))
        scorer = deps.get("summarize")
        if scorer is None:
            scorer = module(root, protocol["metric_scorer_path"]).summarize_classifier_predictions
        stage = "model_identity_verification"
        for family in FAMILIES:
            handle = load_handle(root / source["release_path"], family=family, device="cuda:0" if family == "neural" else "cpu")
            loaded += 1
            require(handle.get("status") == "ready" and handle["family"] == family and handle["class_order"] == protocol["class_order"]
                    and handle["class_to_index"] == protocol["class_to_index"] and handle["artifact"] == protocol["models"][family]
                    and handle["release_id"] == protocol["classifier_release_id"]
                    and handle["device"] == ("cuda:0" if family == "neural" else "cpu"), "A loaded model differs from its preselected identity, class mapping or device.")
            require(integrity(handle) is True, "A classifier handle failed integrity verification.")
            handles[family] = handle
        # The split manifest carries targets and source identities, but no exercise text.
        stage = "population_verification"
        split_rows = csv_rows(root, "data/processed/exercise_split_manifest.csv")
        group_rows = csv_rows(root, "data/processed/exercise_groups.csv")
        metadata = validate_population(split_rows, group_rows, protocol, source["metrics"], source["split"])
        save_once(folder / "population_audit.json", {"records": len(metadata), "groups": len({row["split_group_id"] for row in metadata}),
            "class_order": protocol["class_order"], "catalog_ids": [row["catalog_id"] for row in metadata], "split_group_leakage": False,
            "all_metadata_verified_before_test_text_preparation": True})
        prepared_path = folder / "prepared_inputs.json"
        exposure = folder / "test_input_access_started.json"
        stage = "test_input_preparation"
        if exposure.exists():
            require(prepared_path.exists(), "A previous test-input preparation did not finish; preserve exposure and use an explicit technical amendment.")
            prepared_receipt = read(root, relative + "/prepared_inputs_receipt.json")
            verify(root, prepared_receipt["files"])
            prepared = read(root, relative + "/prepared_inputs.json")["records"]
        else:
            save_once(exposure, {"evaluation_id": evaluation_id, "scope": "dedicated_authorized_heldout_classifier_test", "model_predictions_started": False})
            prepared = align_catalog(metadata, csv_rows(root, "data/processed/exercise_catalog.csv"), inference_api, all_metadata=split_rows)
            save_once(prepared_path, {"evaluation_id": evaluation_id, "records": prepared})
            save_once(folder / "prepared_inputs_receipt.json", {"evaluation_id": evaluation_id,
                "files": {relative + "/prepared_inputs.json": sha(prepared_path.read_bytes())}})
        require(len(prepared) == len(metadata) and [row["catalog_id"] for row in prepared] == [row["catalog_id"] for row in metadata], "Prepared test inputs do not match the verified complete roster.")
        for row, frozen in zip(prepared, metadata):
            require(row["target_label"] == frozen["target_label"] and row["class_index"] == int(frozen["class_index"])
                    and row["split_group_id"] == frozen["split_group_id"]
                    and row["input_hash"] == sha(row["canonical_text"].encode("utf-8")), "A prepared input's target, group or feature identity changed.")
        verify(root, bindings)
        alignment_fields = ["catalog_id", "split_group_id", "target_label", "class_index", "input_hash", "name_only"]
        save_once(folder / "alignment.csv", _csv_bytes([{key: row[key] for key in alignment_fields} for row in prepared], alignment_fields), raw=True)
        for family in FAMILIES:
            stage = family + "_inference"
            model_folder = folder / family
            if _receipt(root, model_folder, evaluation_id) is not None:
                outputs[family] = _read_predictions(root, model_folder, prepared, protocol["class_order"], evaluation_id, protocol["classifier_release_id"])
                continue
            require(not (model_folder / "attempt_started.json").exists(), "A model inference attempt lacks a terminal receipt; no automatic retry is allowed.")
            save_once(model_folder / "attempt_started.json", {"evaluation_id": evaluation_id, "family": family, "expected_records": len(prepared)})
            emit({"majority": "Majority baseline", "logistic_regression": "Logistic model L5", "neural": "Neural model N3"}[family] + " — evaluating the fixed test records…")
            predictions = []
            with (model_folder / "predictions.jsonl").open("xb") as writer:
                for row in prepared:
                    active_record = {"model_family": family, "catalog_id": row["catalog_id"], "input_hash": row["input_hash"],
                                     "completed_prediction_rows_before_attempt": len(predictions)}
                    prediction_attempts += 1
                    value = predict(handles[family], row["canonical_text"])
                    _valid_prediction(value, protocol["class_order"])
                    record = {**value, "catalog_id": row["catalog_id"], "split_group_id": row["split_group_id"],
                        "input_hash": row["input_hash"], "model_family": family, "release_id": protocol["classifier_release_id"],
                        "input_scope": "artificial_evaluator_test" if injected else "heldout_benchmark_test"}
                    writer.write(canonical(record) + b"\n")
                    writer.flush()
                    predictions.append(record)
                    new_predictions += 1
                    active_record = None
            require(integrity(handles[family]) is True, "A model changed during held-out inference.")
            require(len(predictions) == len(prepared), "Model coverage is incomplete; no subset metrics are permitted.")
            path = model_folder / "predictions.jsonl"
            save_once(model_folder / "completed.json", {"evaluation_id": evaluation_id, "family": family,
                "records": len(predictions), "files": {path.relative_to(root).as_posix(): sha(path.read_bytes())}})
            outputs[family] = _read_predictions(root, model_folder, prepared, protocol["class_order"], evaluation_id, protocol["classifier_release_id"])
        # No headline score is calculated until every frozen model covers every intended row.
        stage = "complete_population_scoring"
        results = {}
        for family in FAMILIES:
            predictions = outputs[family]
            result = scorer([row["target_label"] for row in prepared], [row["predicted_label"] for row in predictions],
                            [row["split_group_id"] for row in prepared], protocol["class_order"])
            require(result["n_records"] == len(prepared) and result["class_order"] == protocol["class_order"], "The scorer changed the complete population or class order.")
            results[family] = result
            model_folder = folder / family
            save_once(model_folder / "metrics.json", result)
            save_once(model_folder / "per_class.csv", _csv_bytes(result["per_class"], list(result["per_class"][0])), raw=True)
            save_once(model_folder / "confusion_matrix.json", {key: result[key] for key in ("class_order", "confusion_axes", "confusion_counts", "confusion_row_proportions")})
            wrong = [{"catalog_id": row["catalog_id"], "actual": row["target_label"], "predicted": pred["predicted_label"],
                      "input_hash": row["input_hash"]} for row, pred in zip(prepared, predictions) if row["target_label"] != pred["predicted_label"]]
            wrong.sort(key=lambda row: sha((protocol["protocol_id"] + "|" + family + "|" + row["catalog_id"]).encode()))
            flags = Counter(key for pred in predictions for key, value in pred.get("handling_flags", {}).items() if value is True)
            save_once(model_folder / "diagnostics.json", {"handling_flags_true_counts": dict(flags), "name_only_records": sum(row["name_only"] for row in prepared),
                "wrong_predictions": len(wrong), "error_examples": wrong[:20], "error_examples_used_for_retraining": False})
        contrasts = {"logistic_regression_minus_majority": ("logistic_regression", "majority"), "neural_minus_majority": ("neural", "majority"), "neural_minus_logistic_regression": ("neural", "logistic_regression")}
        differences = {name: {metric: results[a][metric] - results[b][metric] for metric in ("accuracy", "macro_f1")} for name, (a, b) in contrasts.items()}
        stage = "report_generation"
        report_files = reports.write_reports(root, folder, protocol, prepared, outputs, results, differences)
        summary = {"schema_version": VERSION, "status": "complete", "evaluation_id": evaluation_id, "protocol_id": protocol["protocol_id"],
            "injected_test_dependencies": injected, "records": len(prepared), "groups": len({row["split_group_id"] for row in prepared}),
            "class_count": len(protocol["class_order"]), "models": {family: {"accuracy": result["accuracy"], "macro_f1": result["macro_f1"],
                "records": result["n_records"], "metrics_path": relative + "/" + family + "/metrics.json"} for family, result in results.items()},
            "contrasts": differences, "all_models_complete": True, "new_predictions": new_predictions,
            "new_prediction_attempts": prediction_attempts,
            "models_loaded_this_run": loaded, "saved_execution_reused": False, "heldout_text_processed": not injected,
            "model_training_calls": 0, "new_model_calls": 0, "bootstrap_executed": False, "application_selection_changed": False,
            "planner_inputs_changed": False, "human_ratings_created": 0, "planner_final_scores_created": False,
            "summary_path": relative + "/summary.json", "report_files": report_files, "software_evidence": evidence}
        verify(root, bindings)
        save_once(folder / "summary.json", summary)
        files = {path.relative_to(root).as_posix(): sha(path.read_bytes()) for path in folder.rglob("*") if path.is_file() and path.name not in ("completed.json", "evaluation.lock")}
        # Per-model receipts are included too; the outer receipt itself is the only excluded receipt.
        files.update({(folder / family / "completed.json").relative_to(root).as_posix(): sha((folder / family / "completed.json").read_bytes()) for family in FAMILIES})
        save_once(target, summary)
        files[target.relative_to(root).as_posix()] = sha(target.read_bytes())
        save_once(terminal, {"evaluation_id": evaluation_id, "files": files})
        return summary
    except Exception as failure:
        error = type(failure).__name__ + ": " + str(failure)
        save_once(folder / "failure_detail.json", {"evaluation_id": evaluation_id, "failed_stage": stage,
            "active_record": active_record, "error": error, "prediction_attempts_this_run": prediction_attempts,
            "complete_prediction_rows_this_run": new_predictions, "original_outputs_preserved": True})
        existing = {path.relative_to(root).as_posix(): sha(path.read_bytes()) for path in folder.rglob("*") if path.is_file() and path.name not in ("evaluation.lock", "failed.json")}
        summary = {"schema_version": VERSION, "status": "incomplete_no_headline_metrics", "evaluation_id": evaluation_id,
            "protocol_id": protocol["protocol_id"], "injected_test_dependencies": injected, "failed_stage": stage,
            "error": error, "models": {}, "all_models_complete": False,
            "new_predictions": new_predictions, "models_loaded_this_run": loaded, "saved_execution_reused": False,
            "new_prediction_attempts": prediction_attempts,
            "heldout_text_processed": (folder / "test_input_access_started.json").exists() and not injected,
            "model_training_calls": 0, "new_model_calls": 0, "bootstrap_executed": False,
            "automatic_retry_allowed": False, "summary_path": relative + "/failed.json"}
        save_once(stopped, {"evaluation_id": evaluation_id, "summary": summary, "files": existing})
        return summary
    finally:
        lock.unlink(missing_ok=True)
