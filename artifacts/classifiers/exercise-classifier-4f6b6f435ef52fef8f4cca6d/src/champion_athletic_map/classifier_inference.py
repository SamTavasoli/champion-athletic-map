"""Load versioned exercise classifiers and preserve their input/output contract."""

VERSION = "0.1.0"


class ClassifierLoadError(RuntimeError):
    """A release could not be verified or loaded; no substitute model is used."""


def _classifier_packed(value):
    import json
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _classifier_sha(content):
    import hashlib
    return hashlib.sha256(content).hexdigest()


def _classifier_json(content):
    import json

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    result = json.loads(content.decode("utf-8"), object_pairs_hook=pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("nonfinite_json")))
    if not isinstance(result, dict):
        raise ValueError("expected_json_object")
    return result


def _classifier_safe_path(root, relative):
    from pathlib import PurePosixPath
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError("invalid_release_path")
    parsed = PurePosixPath(relative)
    if (parsed.is_absolute() or parsed.as_posix() != relative
            or any(part in (".", "..") for part in parsed.parts)):
        raise ValueError("invalid_release_path")
    path = root / relative
    if path == root or path.resolve() != path or not path.is_relative_to(root):
        raise ValueError("escaped_or_symlink_release_path")
    for ancestor in (path, *path.parents):
        if ancestor == root:
            break
        if ancestor.is_symlink():
            raise ValueError("symlink_release_path")
    if not path.is_file():
        raise ValueError("missing_release_file")
    return path


def _classifier_verify_release_files(root, identity):
    import re
    payloads = identity.get("payloads")
    if not isinstance(payloads, dict) or not payloads or "manifest.json" in payloads:
        raise ValueError("invalid_release_payload_manifest")
    for relative, spec in payloads.items():
        if (not isinstance(spec, dict) or type(spec.get("bytes")) is not int or spec["bytes"] < 0
                or not isinstance(spec.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", spec["sha256"]) is None):
            raise ValueError("invalid_release_payload_specification")
        path = _classifier_safe_path(root, relative)
        value = path.read_bytes()
        if len(value) != spec["bytes"] or _classifier_sha(value) != spec["sha256"]:
            raise ValueError("release_payload_hash_mismatch")
    return True


def _classifier_dependency_versions(identity):
    import importlib.metadata
    import platform
    dependencies = identity.get("dependencies")
    if (not isinstance(dependencies, dict) or not isinstance(dependencies.get("python"), str)
            or not isinstance(dependencies.get("packages"), dict)):
        raise ValueError("missing_release_dependency_versions")
    if platform.python_version() != dependencies["python"]:
        raise ValueError("python_version_mismatch")
    required = {"numpy", "scikit-learn", "joblib", "torch"}
    if not required.issubset(dependencies["packages"]):
        raise ValueError("incomplete_release_dependency_versions")
    for distribution, expected in dependencies["packages"].items():
        if (not isinstance(distribution, str) or not distribution or not isinstance(expected, str)
                or not expected or importlib.metadata.version(distribution) != expected):
            raise ValueError("dependency_version_mismatch")
    return True


def _classifier_load_sources(root, identity):
    import importlib
    import sys
    from pathlib import Path
    sources = identity.get("source_modules")
    names = ("champion_athletic_map", "champion_athletic_map.text_preprocessing",
             "champion_athletic_map.neural_classifier", "champion_athletic_map.classifier_inference")
    if not isinstance(sources, dict) or set(sources) != set(names):
        raise ValueError("incomplete_release_source_package")
    expected_paths = {"champion_athletic_map": "src/champion_athletic_map/__init__.py",
        "champion_athletic_map.text_preprocessing": "src/champion_athletic_map/text_preprocessing.py",
        "champion_athletic_map.neural_classifier": "src/champion_athletic_map/neural_classifier.py",
        "champion_athletic_map.classifier_inference": "src/champion_athletic_map/classifier_inference.py"}
    if sources != expected_paths or any(relative not in identity["payloads"] for relative in sources.values()):
        raise ValueError("unexpected_release_source_import_paths")
    source_root = str(root / "src")
    if source_root not in sys.path:
        sys.path.insert(0, source_root)
    result = {}
    for name in names:
        expected = identity["payloads"][sources[name]]["sha256"]
        existing = sys.modules.get(name)
        if existing is not None:
            location = getattr(existing, "__file__", None)
            if not isinstance(location, str) or not Path(location).is_file() or _classifier_sha(Path(location).read_bytes()) != expected:
                raise ValueError("conflicting_loaded_source_module")
        module = importlib.import_module(name)
        location = getattr(module, "__file__", None)
        if not isinstance(location, str) or not Path(location).is_file() or _classifier_sha(Path(location).read_bytes()) != expected:
            raise ValueError("loaded_source_hash_mismatch")
        result[name] = module
    return result


def _classifier_stable_value(value):
    """Describe fitted scalar/array/constructor values without process addresses."""
    import math
    import numpy as np
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            raise ValueError("nonfinite_classifier_parameter")
        return float(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.ndarray):
        if value.dtype.kind in "fc" and not bool(np.isfinite(value).all()):
            raise ValueError("nonfinite_classifier_parameter")
        return {"dtype": str(value.dtype), "shape": list(value.shape),
            "sha256": _classifier_sha(np.ascontiguousarray(value).tobytes())}
    if isinstance(value, dict):
        return {str(key): _classifier_stable_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_classifier_stable_value(item) for item in value]
    if callable(value):
        return {"callable": str(getattr(value, "__module__", "")) + "." + str(getattr(value, "__qualname__", ""))}
    raise ValueError("unsupported_classifier_parameter_type")


def fingerprint_classifier_state(handle):
    """Hash learned state and inference-relevant fitted configuration."""
    family, model = handle["family"], handle["model"]
    if handle["status"] == "disabled":
        return _classifier_sha(_classifier_packed({"status": "disabled", "release_id": handle["release_id"]}))
    if family == "neural":
        state = {}
        for key, value in model.state_dict().items():
            copied = value.detach().cpu().contiguous()
            state[key] = _classifier_stable_value(copied.numpy())
        value = {"family": family, "state": state, "training": bool(model.training),
            "submodule_training": {name: bool(module.training) for name, module in model.named_modules()},
            "configuration": handle["model_config"]}
    elif family == "logistic_regression":
        vectorizer, classifier = model.named_steps["tfidf"], model.named_steps["classifier"]
        value = {"family": family, "vectorizer_parameters": _classifier_stable_value(vectorizer.get_params(deep=False)),
            "vocabulary": {token: int(index) for token, index in vectorizer.vocabulary_.items()},
            "idf": _classifier_stable_value(vectorizer.idf_),
            "classifier_parameters": _classifier_stable_value(classifier.get_params(deep=False)),
            "classes": _classifier_stable_value(classifier.classes_), "coef": _classifier_stable_value(classifier.coef_),
            "intercept": _classifier_stable_value(classifier.intercept_), "n_iter": _classifier_stable_value(classifier.n_iter_)}
    elif family == "majority":
        value = {"family": family, "parameters": _classifier_stable_value(model.get_params(deep=False)),
            "classes": _classifier_stable_value(model.classes_), "class_prior": _classifier_stable_value(model.class_prior_),
            "constant": _classifier_stable_value(getattr(model, "constant_", None)),
            "n_classes": _classifier_stable_value(model.n_classes_)}
    else:
        raise ValueError("unsupported_classifier_family")
    return _classifier_sha(_classifier_packed(value))


def _classifier_handle_metadata(handle):
    import marshal
    result = {key: handle[key] for key in ("status", "family", "device", "class_order", "class_to_index", "artifact",
        "release_id", "model_id", "candidate_id", "configuration_id", "run_id", "vocabulary",
        "max_sequence_length", "model_config")}
    module = handle["text_module"]
    functions = ("normalize_model_text", "tokenize_model_text", "prepare_canonical_text", "tokenize_canonical_text",
                 "encode_neural_tokens", "validate_neural_vocabulary", "pad_neural_batch")
    result["preprocessing_function_code"] = {name: _classifier_sha(marshal.dumps(function.__code__))
        if callable(function) and hasattr(function, "__code__") else None
        for name in functions for function in (getattr(module, name, None),)}
    return result


def verify_classifier_integrity(handle):
    """Reject changed release files, metadata or fitted state before further use."""
    try:
        from pathlib import Path
        if not isinstance(handle, dict) or handle.get("_handle_schema") != "verified-classifier-handle-1":
            raise ValueError("unverified_classifier_handle")
        root = Path(handle["release_root"]).resolve(strict=True)
        current = _classifier_safe_path(root, "manifest.json").read_bytes()
        if (_classifier_sha(current) != handle["_manifest_sha256"]
                or _classifier_packed(handle["manifest"]) != current
                or _classifier_sha(_classifier_packed(_classifier_handle_metadata(handle))) != handle["_metadata_fingerprint"]):
            raise ValueError("classifier_release_metadata_changed")
        _classifier_verify_release_files(root, handle["manifest"]["identity"])
        if fingerprint_classifier_state(handle) != handle["state_fingerprint"]:
            raise ValueError("classifier_fitted_state_changed")
        return True
    except ClassifierLoadError:
        raise
    except Exception:
        raise ClassifierLoadError("classifier_integrity_check_failed") from None


def load_classifier(release_dir, *, family="tagging", device=None):
    """Load one explicitly identified research/tagging artifact from a verified bundle."""
    import copy
    import math
    from pathlib import Path

    stage = "release_directory"
    try:
        if family not in ("tagging", "majority", "logistic_regression", "neural"):
            raise ValueError("unsupported_classifier_family")
        supplied = Path(release_dir).expanduser().absolute()
        if supplied.is_symlink():
            raise ValueError("symlink_release_directory")
        root = supplied.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("invalid_release_directory")
        stage = "release_manifest"
        manifest_bytes = _classifier_safe_path(root, "manifest.json").read_bytes()
        manifest = _classifier_json(manifest_bytes)
        identity = manifest.get("identity")
        if (manifest.get("schema_version") != "exercise-classifier-release-1" or not isinstance(identity, dict)
                or manifest_bytes != _classifier_packed(manifest)):
            raise ValueError("invalid_release_manifest")
        digest = _classifier_sha(_classifier_packed(identity))
        if (manifest.get("identity_sha256") != digest
                or manifest.get("release_id") != "exercise-classifier-" + digest[:24]):
            raise ValueError("release_identity_mismatch")
        stage = "complete_payload_integrity"
        _classifier_verify_release_files(root, identity)
        classes, mapping = identity.get("class_order"), identity.get("class_to_index")
        if (not isinstance(classes, list) or len(classes) < 2 or len(set(classes)) != len(classes)
                or any(not isinstance(label, str) or not label.strip() for label in classes)
                or mapping != {label: index for index, label in enumerate(classes)}
                or any(type(index) is not int for index in mapping.values())):
            raise ValueError("invalid_release_class_mapping")
        artifacts = identity.get("artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != {"majority", "logistic_regression", "neural"}:
            raise ValueError("incomplete_research_artifacts")
        for kind, spec in artifacts.items():
            if (not isinstance(spec, dict) or spec.get("format") != ("state_dict" if kind == "neural" else "joblib")
                    or spec.get("relative_path") not in identity["payloads"]
                    or any(not isinstance(spec.get(key), str) or not spec[key]
                           for key in ("model_id", "configuration_id", "run_id"))
                    or (kind != "majority" and (not isinstance(spec.get("candidate_id"), str) or not spec["candidate_id"]))):
                raise ValueError("invalid_research_artifact_identity")
        tagging = identity.get("tagging_model")
        if not isinstance(tagging, dict) or tagging.get("status") not in ("selected", "disabled"):
            raise ValueError("unresolved_tagging_decision")
        disabled = family == "tagging" and tagging["status"] == "disabled"
        if tagging["status"] == "selected":
            selected = tagging.get("model_family")
            if selected not in ("logistic_regression", "neural") or any(tagging.get(key) != artifacts[selected].get(key)
                    for key in ("candidate_id", "model_id", "configuration_id", "run_id")):
                raise ValueError("tagging_artifact_identity_mismatch")
        resolved_family = tagging.get("model_family") if family == "tagging" else family
        stage = "saved_configuration_contract"
        config_paths = identity.get("configuration_files")
        required = {"preprocessing", "label_mapping", "vocabulary", "sequence_settings"}
        if not isinstance(config_paths, dict) or not required.issubset(config_paths):
            raise ValueError("missing_release_configurations")
        configs = {}
        for key, relative in config_paths.items():
            if relative not in identity["payloads"]:
                raise ValueError("unbound_release_configuration")
            configs[key] = _classifier_json(_classifier_safe_path(root, relative).read_bytes())
        labels, preprocessing = configs["label_mapping"], configs["preprocessing"]
        if (labels.get("class_order") != classes or labels.get("class_to_index") != mapping
                or preprocessing.get("class_order") != classes or preprocessing.get("class_to_index") != mapping):
            raise ValueError("configuration_class_mapping_mismatch")
        limit = configs["sequence_settings"].get("max_sequence_length")
        if type(limit) is not int or limit < 1 or preprocessing.get("sequence_settings", {}).get("max_sequence_length") != limit:
            raise ValueError("sequence_configuration_mismatch")
        stage = "recorded_dependency_versions"
        _classifier_dependency_versions(identity)
        stage = "verified_source_imports"
        modules = _classifier_load_sources(root, identity)
        text_module = modules["champion_athletic_map.text_preprocessing"]
        if any(not callable(getattr(text_module, name, None)) for name in
               ("prepare_canonical_text", "tokenize_canonical_text", "encode_neural_tokens", "validate_neural_vocabulary")):
            raise ValueError("missing_preprocessing_functions")
        text_module.validate_neural_vocabulary(configs["vocabulary"])
        planned_device = identity.get("intended_application_device", "cpu") if device is None else device
        if not isinstance(planned_device, str) or not planned_device:
            raise ValueError("invalid_inference_device")
        model, model_config = None, None
        spec = None if disabled else copy.deepcopy(artifacts[resolved_family])
        if not disabled and resolved_family in ("majority", "logistic_regression"):
            stage = "saved_sklearn_model_loading"
            if planned_device != "cpu":
                raise ValueError("sklearn_inference_requires_cpu")
            import joblib
            import numpy as np
            from sklearn.dummy import DummyClassifier
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
            model = joblib.load(_classifier_safe_path(root, spec["relative_path"]))
            if resolved_family == "majority":
                if not isinstance(model, DummyClassifier) or model.get_params(deep=False).get("strategy") != "most_frequent":
                    raise ValueError("unexpected_majority_model")
                decoded_classes = model.classes_
                prior = np.asarray(model.class_prior_)
                if (prior.shape != (len(classes),) or not np.isfinite(prior).all() or bool((prior < 0).any())
                        or not math.isclose(float(prior.sum()), 1.0, rel_tol=1e-12, abs_tol=1e-15)):
                    raise ValueError("invalid_majority_class_prior")
            else:
                if (not isinstance(model, Pipeline) or list(model.named_steps) != ["tfidf", "classifier"]
                        or not isinstance(model.named_steps["tfidf"], TfidfVectorizer)
                        or not isinstance(model.named_steps["classifier"], LogisticRegression)):
                    raise ValueError("unexpected_logistic_pipeline")
                vectorizer, classifier = model.named_steps["tfidf"], model.named_steps["classifier"]
                if (vectorizer.tokenizer is not text_module.tokenize_canonical_text
                        or vectorizer.analyzer != "word" or vectorizer.preprocessor is not None
                        or vectorizer.lowercase is not False or vectorizer.token_pattern is not None
                        or vectorizer.dtype != np.float64 or vectorizer.strip_accents is not None
                        or not vectorizer.vocabulary_ or not np.isfinite(vectorizer.idf_).all()
                        or not np.isfinite(classifier.coef_).all() or not np.isfinite(classifier.intercept_).all()
                        or classifier.coef_.shape[1] != len(vectorizer.vocabulary_)):
                    raise ValueError("incompatible_logistic_feature_contract")
                recipe = preprocessing.get("tfidf")
                recipe_keys = ("analyzer", "binary", "lowercase", "max_df", "max_features", "min_df", "norm",
                    "preprocessor", "smooth_idf", "stop_words", "strip_accents", "sublinear_tf", "token_pattern", "use_idf")
                if (not isinstance(recipe, dict) or any(key not in recipe or getattr(vectorizer, key) != recipe[key]
                        for key in recipe_keys) or recipe.get("dtype") != "float64"
                        or list(vectorizer.ngram_range) != recipe.get("ngram_range")
                        or recipe.get("tokenizer_function") != "tokenize_canonical_text"):
                    raise ValueError("saved_tfidf_recipe_mismatch")
                decoded_classes = classifier.classes_
            if np.asarray(decoded_classes).dtype.kind not in "iu" or not np.array_equal(np.asarray(decoded_classes), np.arange(len(classes))):
                raise ValueError("fitted_sklearn_class_order_mismatch")
        elif not disabled and resolved_family == "neural":
            stage = "saved_neural_configuration"
            import torch
            actual_device = torch.device(planned_device)
            if actual_device.type not in ("cpu", "cuda"):
                raise ValueError("unsupported_inference_device")
            if actual_device.type == "cuda":
                index = 0 if actual_device.index is None else actual_device.index
                if not torch.cuda.is_available() or index >= torch.cuda.device_count():
                    raise ValueError("requested_cuda_device_unavailable")
                actual_device = torch.device("cuda", index)
            planned_device = str(actual_device)
            config_relative = spec.get("model_config", config_paths.get("neural_architecture"))
            if config_relative not in identity["payloads"]:
                raise ValueError("unbound_neural_model_configuration")
            model_config = _classifier_json(_classifier_safe_path(root, config_relative).read_bytes())
            expected_keys = {"vocab_size", "num_classes", "embedding_dim", "hidden_dim", "dropout",
                             "max_sequence_length", "padding_idx", "unknown_idx"}
            if (set(model_config) != expected_keys or model_config["num_classes"] != len(classes)
                    or model_config["vocab_size"] != len(configs["vocabulary"]["id_to_token"])
                    or model_config["max_sequence_length"] != limit or model_config["padding_idx"] != 0
                    or model_config["unknown_idx"] != 1):
                raise ValueError("neural_model_configuration_mismatch")
            stage = "saved_neural_state_loading"
            state = torch.load(_classifier_safe_path(root, spec["relative_path"]), map_location="cpu", weights_only=True)
            if (not isinstance(state, dict) or not state or any(not isinstance(value, torch.Tensor)
                    or value.dtype != torch.float32 or value.device.type != "cpu"
                    or not bool(torch.isfinite(value).all()) for value in state.values())):
                raise ValueError("invalid_neural_state_dictionary")
            # Construction is needed for inference, but it must not consume caller RNG state.
            with torch.random.fork_rng(devices=[], enabled=True):
                model = modules["champion_athletic_map.neural_classifier"].NeuralExerciseClassifier(**model_config)
                model.load_state_dict(state, strict=True)
            model.to(device=actual_device, dtype=torch.float32)
            model.eval()
            if not bool(model.embedding.weight[0].detach().eq(0).all()):
                raise ValueError("nonzero_neural_padding_embedding")
        elif not disabled:
            raise ValueError("unsupported_resolved_classifier_family")
        handle = {"_handle_schema": "verified-classifier-handle-1", "status": "disabled" if disabled else "ready",
            "family": resolved_family, "model": model, "text_module": text_module,
            "vocabulary": copy.deepcopy(configs["vocabulary"]), "max_sequence_length": limit,
            "model_config": model_config, "device": planned_device, "class_order": list(classes),
            "class_to_index": dict(mapping), "artifact": spec, "manifest": copy.deepcopy(manifest),
            "release_id": manifest["release_id"], "release_root": root,
            "model_id": None if spec is None else spec["model_id"],
            "candidate_id": None if spec is None else spec.get("candidate_id"),
            "configuration_id": None if spec is None else spec["configuration_id"],
            "run_id": None if spec is None else spec["run_id"], "_manifest_sha256": _classifier_sha(manifest_bytes)}
        handle["_metadata_fingerprint"] = _classifier_sha(_classifier_packed(_classifier_handle_metadata(handle)))
        handle["state_fingerprint"] = fingerprint_classifier_state(handle)
        stage = "post_loading_release_integrity"
        verify_classifier_integrity(handle)
        return handle
    except ClassifierLoadError:
        raise
    except Exception:
        raise ClassifierLoadError("classifier_load_failed:" + stage) from None


"""Construct the frozen exercise input and predict without adopting catalog labels."""


def prepare_exercise_input(exercise_name, description=None):
    """Apply the Step 10 field construction, without model-text normalization.

    Whitespace is compacted separately within each supplied field. The source
    preparation's null-like markers count as absent fields. A name is required;
    a description is optional. Unicode NFKC and casefold remain exclusively in
    the saved Step 18 model route, where they are applied exactly once.
    """
    import hashlib
    import re

    if not isinstance(exercise_name, str):
        raise ValueError("exercise_name_requires_a_string")
    if description is not None and not isinstance(description, str):
        raise ValueError("description_requires_a_string_or_none")
    missing = {"", "null", "none", "nan", "n/a"}
    name = re.sub(r"\s+", " ", exercise_name).strip()
    detail = "" if description is None else re.sub(r"\s+", " ", description).strip()
    if name.casefold() in missing:
        raise ValueError("exercise_name_is_missing")
    if detail.casefold() in missing:
        detail = ""
    canonical = name + ("\n\n" + detail if detail else "")
    try:
        encoded = canonical.encode("utf-8")
    except UnicodeError:
        raise ValueError("exercise_input_is_not_valid_utf8_text") from None
    return {"canonical_text": canonical,
            "input_hash": hashlib.sha256(encoded).hexdigest(), "name_only": not bool(detail)}


def _prediction_response(handle, status, code, input_scope, record_type, prepared=None, flags=None):
    """Keep error and deferral records finite, serializable and free of input text."""
    values = handle if isinstance(handle, dict) else {}

    def text(key):
        value = values.get(key)
        return value if isinstance(value, str) else None

    result = {"status": status, "code": code, "prediction_produced": status == "produced",
              "release_id": text("release_id"), "prediction_model_version": text("release_id"),
              "model_family": text("family"), "model_id": text("model_id"),
              "candidate_id": text("candidate_id"), "configuration_id": text("configuration_id"),
              "run_id": text("run_id"),
              "input_scope": input_scope if isinstance(input_scope, str) else None,
              "record_type": record_type if isinstance(record_type, str) else None,
              "input_hash": None if prepared is None else prepared["input_hash"],
              "handling_flags": {} if flags is None else dict(flags),
              "catalog_review_performed": False, "source_labels_changed": False,
              "planner_eligibility_granted": False}
    return result


def _prediction_class_indices(model, class_count):
    import operator
    import numpy as np

    values = getattr(model, "classes_", None)
    if values is None:
        raise ValueError("classifier_has_no_frozen_class_indices")
    array = np.asarray(values)
    if array.shape != (class_count,):
        raise ValueError("classifier_class_axis_differs_from_frozen_mapping")
    try:
        indices = [operator.index(value) for value in array.tolist()]
    except TypeError:
        raise ValueError("classifier_class_indices_are_not_integers") from None
    if any(isinstance(value, (bool, np.bool_)) for value in array.tolist()) or indices != list(range(class_count)):
        raise ValueError("classifier_class_axis_differs_from_frozen_mapping")
    return indices


def _prediction_validate_probabilities(probabilities, class_count):
    import numpy as np

    values = np.asarray(probabilities)
    if (values.shape != (1, class_count) or not np.issubdtype(values.dtype, np.number)
            or np.issubdtype(values.dtype, np.complexfloating) or not bool(np.isfinite(values).all())
            or bool((values < 0).any()) or bool((values > 1).any())
            or not bool(np.allclose(values.sum(axis=1), 1.0, rtol=1e-5, atol=1e-6))):
        raise ValueError("classifier_probability_output_is_invalid")
    return values[0]


def _prediction_sklearn(handle, canonical, flags):
    """Transform once, then reuse the same feature row for labels and scores."""
    import operator
    import numpy as np

    family, model, class_count = handle["family"], handle["model"], len(handle["class_order"])
    if family == "logistic_regression":
        if not hasattr(model, "steps") or len(model.steps) < 2:
            raise ValueError("selected_logistic_artifact_is_not_a_complete_pipeline")
        features = model[:-1].transform([canonical])
        classifier = model.steps[-1][1]
        if not hasattr(features, "shape") or len(features.shape) != 2 or features.shape[0] != 1:
            raise ValueError("tfidf_transform_did_not_keep_one_input_row")
        stored_values = features.data if hasattr(features, "getnnz") else np.asarray(features)
        if not bool(np.isfinite(stored_values).all()):
            raise ValueError("tfidf_transform_produced_nonfinite_features")
        nonzero = int(features.getnnz()) if hasattr(features, "getnnz") else int(np.count_nonzero(features))
        flags["tfidf_zero_vector"] = nonzero == 0
        flags["tfidf_nonzero_features"] = nonzero
        # A zero vector may reflect filtering or vocabulary coverage. It does
        # not justify a second normalization/tokenization pass to infer why.
        flags["empty_tokens"] = None
    elif family == "majority":
        classifier, features = model, [canonical]
        flags["constant_training_majority_prediction"] = True
    else:
        raise ValueError("unsupported_sklearn_model_family")
    _prediction_class_indices(classifier, class_count)
    predicted = np.asarray(classifier.predict(features))
    if predicted.shape != (1,):
        raise ValueError("classifier_prediction_did_not_keep_one_input_row")
    try:
        index = operator.index(predicted.tolist()[0])
    except TypeError:
        raise ValueError("classifier_prediction_is_not_an_integer_index") from None
    if isinstance(predicted.tolist()[0], (bool, np.bool_)) or not 0 <= index < class_count:
        raise ValueError("classifier_prediction_is_outside_frozen_mapping")
    probabilities = _prediction_validate_probabilities(classifier.predict_proba(features), class_count)
    if index != int(np.argmax(probabilities)):
        raise ValueError("classifier_prediction_disagrees_with_probability_argmax")
    return index, probabilities.tolist(), None


def _prediction_neural(handle, canonical, flags):
    """Use the saved preparation and explicit device with no targets or gradients."""
    import torch

    model, module = handle["model"], handle["text_module"]
    if model.training or any(part.training for part in model.modules()):
        raise ValueError("neural_model_is_not_in_evaluation_mode")
    prepared = module.prepare_canonical_text(canonical)
    encoded = module.encode_neural_tokens(prepared["tokens"], handle["vocabulary"], handle["max_sequence_length"])
    ids = encoded["token_ids"]
    if (not isinstance(ids, list) or not ids or len(ids) > handle["max_sequence_length"]
            or any(type(value) is not int or value <= 0 for value in ids)):
        raise ValueError("encoded_neural_input_does_not_match_saved_contract")
    device = torch.device(handle["device"])
    input_ids = torch.tensor([ids], dtype=torch.long, device=device)
    # Single-record inference needs no temporary padding. UNK=1 remains a valid
    # masked-in position, including the one-position empty-token fallback.
    mask = torch.ones_like(input_ids, dtype=torch.bool)
    model.eval()
    with torch.inference_mode():
        logits = model(input_ids, mask)
        if (not isinstance(logits, torch.Tensor) or logits.shape != (1, len(handle["class_order"]))
                or logits.dtype != torch.float32 or not bool(torch.isfinite(logits).all()) or logits.requires_grad):
            raise ValueError("neural_logit_output_is_invalid")
        probabilities = torch.softmax(logits, dim=1)
        index = int(logits.argmax(dim=1).item())
        raw_logits = logits.detach().cpu().tolist()[0]
        raw_probabilities = probabilities.detach().cpu().numpy()
    values = _prediction_validate_probabilities(raw_probabilities, len(handle["class_order"]))
    if index != int(values.argmax()):
        raise ValueError("neural_prediction_disagrees_with_probability_argmax")
    for key in ("raw_token_count", "effective_token_count", "retained_length", "truncated_tokens",
                "unknown_tokens_before_truncation", "unknown_tokens_after_truncation",
                "empty_token_fallback", "all_unknown_after_truncation"):
        flags[key] = encoded[key]
    flags["padding_positions"] = 0
    flags["unk_positions_are_masked_in"] = True
    flags["model_in_evaluation_mode"] = True
    flags["gradients_disabled"] = True
    return index, values.tolist(), raw_logits


def predict_exercise(handle, exercise_name, description=None, *, input_scope="new_record",
                     record_type="general_exercise", include_scores=True):
    """Predict only for a declared authorized development or synthetic input.

    This function produces a model suggestion, never an adopted catalog label.
    The catalog workflow must verify actual development membership before it
    supplies a development scope. Unscreened new records are deferred by default.
    Scope and record-type gates execute before inspecting either text field.
    """
    if not isinstance(record_type, str) or record_type != "general_exercise":
        return _prediction_response(handle, "unsupported", "record_type_outside_classifier_scope", input_scope, record_type)
    scopes = {"synthetic": "artificial_input_handling", "development_train": "in_sample",
              "development_validation": "development"}
    if not isinstance(input_scope, str) or input_scope not in scopes:
        return _prediction_response(handle, "deferred", "input_population_is_not_cleared_for_prediction", input_scope, record_type)
    if not isinstance(handle, dict):
        return _prediction_response(handle, "loading_error", "invalid_classifier_handle", input_scope, record_type)
    if handle.get("status") == "disabled":
        return _prediction_response(handle, "disabled", "tagging_disabled_by_frozen_selection", input_scope, record_type)
    if handle.get("status") != "ready":
        return _prediction_response(handle, "loading_error", "classifier_handle_is_not_ready", input_scope, record_type)
    if type(include_scores) is not bool:
        return _prediction_response(handle, "invalid_input", "include_scores_requires_boolean", input_scope, record_type)
    try:
        verify_classifier_integrity(handle)
        classes = handle["class_order"]
        if (not isinstance(classes, list) or len(classes) < 2 or len(set(classes)) != len(classes)
                or any(not isinstance(value, str) or not value for value in classes)
                or handle["class_to_index"] != {label: index for index, label in enumerate(classes)}
                or handle["family"] not in ("majority", "logistic_regression", "neural")):
            raise ValueError("classifier_handle_mapping_is_invalid")
    except Exception:
        return _prediction_response(handle, "loading_error", "classifier_integrity_verification_failed", input_scope, record_type)
    try:
        prepared = prepare_exercise_input(exercise_name, description)
    except (TypeError, ValueError):
        return _prediction_response(handle, "invalid_input", "exercise_name_or_description_is_invalid", input_scope, record_type)
    flags = {"name_only": prepared["name_only"], "preview_kind": scopes[input_scope],
             "protected_group_screening_performed_by_predictor": False}
    try:
        if handle["family"] == "neural":
            index, probabilities, logits = _prediction_neural(handle, prepared["canonical_text"], flags)
        else:
            index, probabilities, logits = _prediction_sklearn(handle, prepared["canonical_text"], flags)
        verify_classifier_integrity(handle)
    except Exception:
        code = "classifier_prediction_failed"
        try:
            verify_classifier_integrity(handle)
        except Exception:
            code = "classifier_integrity_changed_during_prediction"
        return _prediction_response(handle, "failed", code, input_scope, record_type, prepared, flags)
    result = _prediction_response(handle, "produced", "prediction_is_pending_catalog_review", input_scope, record_type, prepared, flags)
    result["predicted_class_index"] = index
    result["predicted_body_part"] = classes[index]
    if include_scores:
        result.update({"score_type": "uncalibrated_probability", "score_class_order": list(classes),
                       "probabilities": probabilities, "logits": logits, "probabilities_calibrated": False})
    return result


def predict_from_bundle(release_dir, exercise_name, description=None, *, family="tagging", device=None,
                        input_scope="new_record", record_type="general_exercise", include_scores=True):
    """Combine explicit bundle loading with the same conservative prediction gate."""
    if not isinstance(record_type, str) or record_type != "general_exercise":
        return _prediction_response(None, "unsupported", "record_type_outside_classifier_scope", input_scope, record_type)
    if input_scope not in ("synthetic", "development_train", "development_validation"):
        return _prediction_response(None, "deferred", "input_population_is_not_cleared_for_prediction", input_scope, record_type)
    try:
        handle = load_classifier(release_dir, family=family, device=device)
    except Exception:
        return _prediction_response(None, "loading_error", "classifier_bundle_could_not_be_loaded", input_scope, record_type)
    return predict_exercise(handle, exercise_name, description, input_scope=input_scope,
                            record_type=record_type, include_scores=include_scores)
