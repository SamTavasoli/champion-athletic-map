"""Fit or freshly reload the fixed retrieval TF-IDF index for seven admitted cores."""

STEP2310_LEXICAL_POLICY = {
    "analyzer": "word", "lowercase": True, "strip_accents": None,
    "token_pattern": r"(?u)\b\w\w+\b", "preprocessor": None, "tokenizer": None,
    "ngram_range": [1, 2], "min_df": 1, "max_df": 1.0, "max_features": None,
    "stop_words": None, "smooth_idf": True, "sublinear_tf": False, "use_idf": True,
    "norm": "l2", "binary": False, "dtype": "float64", "encoding": "utf-8", "decode_error": "strict",
    "classifier_vectorizer_or_preprocessor_reused": False,
    "query_vocabulary_or_idf_fitting": False,
}


def _step2310_lexical_pack(value):
    import json
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _step2310_lexical_sha(content):
    import hashlib
    return hashlib.sha256(content).hexdigest()


def _step2310_lexical_state(vectorizer, matrix):
    import numpy as np
    from scipy import sparse
    if (not sparse.isspmatrix_csr(matrix) or matrix.dtype != np.dtype("float64")
            or not matrix.has_sorted_indices or not np.isfinite(matrix.data).all()
            or np.any(matrix.data < 0.0)):
        raise ValueError("lexical_corpus_matrix_is_not_canonical_finite_csr_float64")
    vocabulary = {key: int(value) for key, value in vectorizer.vocabulary_.items()}
    names = vectorizer.get_feature_names_out().tolist()
    idf = np.asarray(vectorizer.idf_)
    if (idf.dtype != np.dtype("float64") or idf.shape != (matrix.shape[1],)
            or len(names) != len(vocabulary) or set(vocabulary.values()) != set(range(matrix.shape[1]))
            or not np.isfinite(idf).all() or np.any(idf <= 0.0)):
        raise ValueError("lexical_vocabulary_idf_or_feature_order_invalid")
    params = vectorizer.get_params(deep=False)
    for key, expected in STEP2310_LEXICAL_POLICY.items():
        if key in ("classifier_vectorizer_or_preprocessor_reused", "query_vocabulary_or_idf_fitting"):
            continue
        actual = params.get(key)
        if key == "ngram_range":
            actual = list(actual)
        elif key == "dtype":
            actual = np.dtype(actual).name
        if actual != expected:
            raise ValueError("lexical_fixed_vectorizer_setting_changed:" + key)
    def array_hash(array):
        value = np.ascontiguousarray(array)
        return _step2310_lexical_sha(_step2310_lexical_pack({"dtype": value.dtype.str, "shape": list(value.shape)}) + value.tobytes())
    norms = np.sqrt(np.asarray(matrix.multiply(matrix).sum(axis=1)).reshape(-1))
    nonzero_rows = np.diff(matrix.indptr) > 0
    if not np.allclose(norms[nonzero_rows], 1.0, rtol=1e-12, atol=1e-12):
        raise ValueError("lexical_corpus_rows_not_l2_normalized")
    return {"rows": int(matrix.shape[0]), "features": int(matrix.shape[1]), "nonzero_values": int(matrix.nnz),
        "zero_vector_rows": int((~nonzero_rows).sum()), "dtype": matrix.dtype.name, "matrix_format": "csr",
        "density": float(matrix.nnz / (matrix.shape[0] * matrix.shape[1])),
        "vocabulary_sha256": _step2310_lexical_sha(_step2310_lexical_pack(vocabulary)),
        "feature_order_sha256": _step2310_lexical_sha(_step2310_lexical_pack(names)),
        "idf_array_sha256": array_hash(idf), "csr_data_sha256": array_hash(matrix.data),
        "csr_indices_sha256": array_hash(matrix.indices), "csr_indptr_sha256": array_hash(matrix.indptr),
        "fitted_policy": STEP2310_LEXICAL_POLICY}


def run_step2310_lexical_worker(request):
    import importlib.metadata as metadata
    import json
    import os
    import platform
    import re
    import socket
    import urllib.request
    import warnings
    from pathlib import Path
    import joblib
    import numpy as np
    from scipy import sparse
    from sklearn.feature_extraction.text import TfidfVectorizer

    mode = request.get("mode") if isinstance(request, dict) else None
    required = {"mode", "corpus_id", "runtime_environment", "passages", "output_directory", "result_path"}
    if mode == "reload_verify":
        required |= {"expected_output_hashes", "expected_index_state"}
    if mode not in ("fit", "reload_verify") or set(request) != required:
        raise ValueError("lexical_worker_request_scope_invalid")
    if type(request["corpus_id"]) is not str or not request["corpus_id"]:
        raise ValueError("lexical_worker_corpus_identity_missing")
    rows = request["passages"]
    if (not isinstance(rows, list) or len(rows) != 7
            or any(not isinstance(row, dict) or set(row) != {"passage_id", "reference_unit_id", "text", "text_sha256"}
                or any(type(row.get(key)) is not str or not row[key] for key in ("passage_id", "reference_unit_id", "text"))
                or _step2310_lexical_sha(row["text"].encode("utf-8")) != row["text_sha256"] for row in rows)
            or len({row["passage_id"] for row in rows}) != 7 or len({row["reference_unit_id"] for row in rows}) != 7):
        raise ValueError("lexical_worker_requires_seven_distinct_bound_admitted_cores")
    folder, result_path = Path(request["output_directory"]), Path(request["result_path"])
    for path in (folder, result_path):
        if (not path.is_absolute() or path.resolve() != path
                or any(parent.is_symlink() for parent in (path, *path.parents))):
            raise ValueError("unsafe_lexical_worker_path")
    if not folder.is_dir() or not result_path.parent.is_dir() or result_path.exists():
        raise ValueError("lexical_worker_output_directory_or_report_invalid")
    globals()["_STEP2310_LEXICAL_SAFE_REPORT"] = str(result_path)
    expected_names = {"lexical_vectorizer.joblib", "lexical_matrix.npz"}
    vectorizer_path, matrix_path = folder / "lexical_vectorizer.joblib", folder / "lexical_matrix.npz"
    if (result_path in (vectorizer_path, matrix_path)
            or any(path.is_symlink() or path.resolve() != path for path in (vectorizer_path, matrix_path))):
        raise ValueError("unsafe_lexical_index_payload_path")
    versions = {name: metadata.version(name) for name in ("numpy", "scipy", "scikit-learn", "joblib")}
    environment = request["runtime_environment"]
    if (platform.python_version() != environment["python_version"]
            or any(environment["versions"].get(name) != version for name, version in versions.items())):
        raise ValueError("lexical_worker_runtime_differs_from_recorded_environment")
    def forbidden(*args, **kwargs):
        raise RuntimeError("network_forbidden_during_lexical_index_work")
    socket.create_connection = forbidden; socket.socket.connect = forbidden
    urllib.request.urlopen = forbidden; urllib.request.OpenerDirector.open = forbidden
    checks = []
    def check(name, condition, observed=True):
        if not bool(condition):
            raise ValueError("lexical_worker_condition_failed:" + name)
        checks.append({"check": name, "status": "pass", "observed": str(observed)})
    check("seven_explicit_core_texts_are_bound_without_queries", len(rows) == 7)
    check("installed_lexical_runtime_matches_the_recorded_environment", True)
    texts = [row["text"] for row in rows]
    warnings_seen = []
    replay_max_absolute_difference = None
    replay_rtol, replay_atol = 1e-12, 1e-15
    if mode == "fit":
        check("fit_does_not_replace_existing_index_files", not vectorizer_path.exists() and not matrix_path.exists())
        vectorizer = TfidfVectorizer(analyzer="word", lowercase=True, strip_accents=None,
            token_pattern=r"(?u)\b\w\w+\b", preprocessor=None, tokenizer=None, ngram_range=(1, 2),
            min_df=1, max_df=1.0, max_features=None, stop_words=None, smooth_idf=True,
            sublinear_tf=False, use_idf=True, norm="l2", binary=False, dtype=np.float64,
            encoding="utf-8", decode_error="strict")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            matrix = vectorizer.fit_transform(texts).tocsr()
        warnings_seen = [type(item.message).__name__ for item in caught]
        matrix.sort_indices()
        state = _step2310_lexical_state(vectorizer, matrix)
        # This private cache is a process address, not a fitted parameter.
        # Omitting it makes identical fresh-process fits serialize identically.
        vectorizer.__dict__.pop("_stop_words_id", None)
        # The worker writes only into an exclusive temporary directory supplied by the parent.
        with vectorizer_path.open("xb") as handle:
            joblib.dump(vectorizer, handle, compress=0)
            handle.flush(); os.fsync(handle.fileno())
        with matrix_path.open("xb") as handle:
            sparse.save_npz(handle, matrix, compressed=True)
            handle.flush(); os.fsync(handle.fileno())
        fits, transforms = 1, 0
        check("training_population_is_only_the_seven_approved_corpus_cores", state["rows"] == 7)
    else:
        check("reload_names_only_the_two_bound_index_payloads", set(request["expected_output_hashes"]) == expected_names)
        before_hashes = {}
        for name, path in (("lexical_vectorizer.joblib", vectorizer_path), ("lexical_matrix.npz", matrix_path)):
            if not path.is_file() or path.is_symlink():
                raise ValueError("lexical_saved_index_payload_missing_or_symlink")
            before_hashes[name] = _step2310_lexical_sha(path.read_bytes())
            if before_hashes[name] != request["expected_output_hashes"][name]:
                raise ValueError("lexical_saved_index_payload_hash_changed")
        # Deserialization occurs only after the parent-bound bytes have been verified.
        vectorizer, matrix = joblib.load(vectorizer_path), sparse.load_npz(matrix_path).tocsr()
        state = _step2310_lexical_state(vectorizer, matrix)
        check("fresh_reload_reproduces_all_fitted_and_sparse_state", state == request["expected_index_state"])
        before_state = state
        replay = vectorizer.transform(texts).tocsr(); replay.sort_indices()
        structure_exact = (replay.shape == matrix.shape and np.array_equal(replay.indices, matrix.indices)
            and np.array_equal(replay.indptr, matrix.indptr))
        if structure_exact and replay.data.shape == matrix.data.shape:
            replay_max_absolute_difference = float(np.max(np.abs(replay.data - matrix.data))) if matrix.data.size else 0.0
        check("fresh_corpus_transform_replays_saved_values_with_float64_tolerance_and_exact_order", structure_exact
            and np.allclose(replay.data, matrix.data, rtol=replay_rtol, atol=replay_atol), replay_max_absolute_difference)
        check("corpus_replay_does_not_change_fitted_vectorizer_or_saved_files", before_state == _step2310_lexical_state(vectorizer, matrix)
            and all(_step2310_lexical_sha((folder / name).read_bytes()) == digest for name, digest in before_hashes.items()))
        fits, transforms = 0, 1
    check("all_corpus_features_are_finite_l2_float64_with_fixed_settings", state["dtype"] == "float64" and state["matrix_format"] == "csr")
    hashes = {name: _step2310_lexical_sha((folder / name).read_bytes()) for name in sorted(expected_names)}
    report = {"status": "lexical_index_fitted" if mode == "fit" else "lexical_index_reload_verified",
        "mode": mode, "corpus_id": request["corpus_id"],
        "passage_ids": [row["passage_id"] for row in rows], "reference_unit_ids": [row["reference_unit_id"] for row in rows],
        "corpus_input_sha256": _step2310_lexical_sha(_step2310_lexical_pack(rows)),
        "index_state": state, "output_hashes": hashes,
        "runtime_versions": versions, "python_version": platform.python_version(),
        "vectorizer_fits_this_execution": fits, "fit_transform_requests_this_execution": fits,
        "additional_corpus_transform_requests_this_execution": transforms, "query_transforms_this_execution": 0,
        "model_training_runs": 0, "network_requests": 0,
        "fit_warning_count": len(warnings_seen), "fit_warning_categories": warnings_seen,
        "scores_or_benchmark_questions_created": 0,
        "non_fitted_process_cache_omitted_from_serialization": ["_stop_words_id"],
        "corpus_replay_data_max_absolute_difference": replay_max_absolute_difference,
        "corpus_replay_data_rtol": replay_rtol, "corpus_replay_data_atol": replay_atol,
        "corpus_replay_structure_comparison": "exact_shape_indices_and_indptr", "checks": checks}
    with result_path.open("xb") as handle:
        handle.write(_step2310_lexical_pack(report)); handle.flush(); os.fsync(handle.fileno())
    return report


def _step2310_lexical_main():
    import json
    import sys
    try:
        request = json.load(sys.stdin)
        run_step2310_lexical_worker(request)
        return 0
    except Exception as error:
        allowed_checks = {"seven_explicit_core_texts_are_bound_without_queries",
            "installed_lexical_runtime_matches_the_recorded_environment", "fit_does_not_replace_existing_index_files",
            "training_population_is_only_the_seven_approved_corpus_cores", "all_corpus_features_are_finite_l2_float64_with_fixed_settings",
            "reload_names_only_the_two_bound_index_payloads", "fresh_reload_reproduces_all_fitted_and_sparse_state",
            "fresh_corpus_transform_replays_saved_values_with_float64_tolerance_and_exact_order",
            "corpus_replay_does_not_change_fitted_vectorizer_or_saved_files"}
        prefix = "lexical_worker_condition_failed:"
        message = str(error)
        category = message[len(prefix):] if message.startswith(prefix) and message[len(prefix):] in allowed_checks else "lexical_worker_failure"
        diagnostic = {"status": "failed", "exception_type": type(error).__name__,
            "stage": "fixed_lexical_index_work", "diagnostic_category": category, "raw_exception_messages_included": False}
        try:
            from pathlib import Path
            path = Path(globals()["_STEP2310_LEXICAL_SAFE_REPORT"])
            if path.is_absolute() and path.parent.is_dir() and not path.exists() and not path.is_symlink():
                with path.open("xb") as handle:
                    handle.write((json.dumps(diagnostic, sort_keys=True) + "\n").encode("utf-8"))
        except Exception:
            pass
        print(json.dumps(diagnostic, sort_keys=True), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(_step2310_lexical_main())
