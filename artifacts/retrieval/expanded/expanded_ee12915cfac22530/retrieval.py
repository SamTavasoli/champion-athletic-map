"""Deterministic passage ranking with complete, indivisible delivery companions.

The caller supplies a verified, explicitly assembled index and passage list.
This module never scans folders, opens publisher pages or selects a model.
"""


def _step2314_validate_ranking_metadata(metadata):
    if not isinstance(metadata, list) or not metadata:
        raise ValueError("retrieval_metadata_requires_explicit_passage_rows")
    seen = set()
    for row in metadata:
        if not isinstance(row, dict):
            raise ValueError("retrieval_metadata_row_not_a_record")
        passage_id, unit_id = row.get("passage_id"), row.get("reference_unit_id")
        if (type(passage_id) is not str or not passage_id or passage_id in seen
                or type(unit_id) is not str or not unit_id):
            raise ValueError("retrieval_passage_ids_must_be_distinct_and_unit_ids_present")
        seen.add(passage_id)
        delivery = row.get("required_delivery_record")
        if not isinstance(delivery, dict):
            raise ValueError("retrieval_required_delivery_record_missing")
        display = delivery.get("display_text", delivery.get("complete_display_text"))
        if type(display) is not str or not display.strip():
            raise ValueError("retrieval_complete_required_delivery_text_missing")
        if delivery.get("passage_id") != passage_id or delivery.get("reference_unit_id") != unit_id:
            raise ValueError("retrieval_required_delivery_record_not_bound_to_passage")
        if "required_delivery_record_sha256" in row:
            import hashlib
            import json
            encoded = (json.dumps(delivery, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
            if hashlib.sha256(encoded).hexdigest() != row["required_delivery_record_sha256"]:
                raise ValueError("retrieval_required_delivery_record_hash_changed")
    return True


def rank_passage_scores(scores, metadata, *, route, k=5):
    """Rank at most five distinct units, retaining each winning passage's companion.

    Unit score is the maximum passage score. Exact passage ties retain the
    lexicographically earlier passage ID; exact unit ties retain the earlier
    unit ID. Lexical zero/negative scores are excluded. Semantic scores have
    no adopted answerability threshold and may include negative cosine values.
    """
    import copy
    import numpy as np
    if route not in ("lexical", "semantic"):
        raise ValueError("retrieval_route_must_be_lexical_or_semantic")
    if type(k) is not int or not 1 <= k <= 5:
        raise ValueError("retrieval_k_must_be_an_integer_from_one_to_five")
    _step2314_validate_ranking_metadata(metadata)
    values = np.asarray(scores)
    if (values.ndim != 1 or len(values) != len(metadata) or values.dtype.kind not in "fiu"
            or not np.isfinite(values).all()):
        raise ValueError("retrieval_scores_must_be_aligned_finite_numeric_values")
    with np.errstate(over="ignore", invalid="ignore"):
        values = values.astype(np.float64, copy=False)
    if not np.isfinite(values).all():
        raise ValueError("retrieval_scores_are_not_representable_as_finite_float64")
    best = {}
    for value, row in zip(values, metadata):
        score = float(value)
        if route == "lexical" and score <= 0.0:
            continue
        current = best.get(row["reference_unit_id"])
        if current is None or score > current[0] or (score == current[0] and row["passage_id"] < current[1]["passage_id"]):
            best[row["reference_unit_id"]] = score, row
    selected = sorted(best.items(), key=lambda item: (-item[1][0], item[0]))[:k]
    rows = []
    for rank, (unit_id, (score, row)) in enumerate(selected, 1):
        delivery = copy.deepcopy(row["required_delivery_record"])
        rows.append({"rank": rank, "reference_unit_id": unit_id, "passage_id": row["passage_id"],
            "score": score, "score_kind": "tfidf_cosine" if route == "lexical" else "embedding_cosine",
            "required_delivery_record": delivery,
            "complete_required_delivery_text": delivery.get("display_text", delivery.get("complete_display_text")),
            "required_delivery_must_be_attached": True, "standalone_core_delivery_allowed": False,
            "answerability_established_by_score": False, "generation_context_budget_verified": False})
    return {"status": "ranked" if rows else "available_no_positive_lexical_matches", "route": route,
        "requested_k": k, "returned_distinct_reference_units": len(rows), "results": rows,
        "unit_score_rule": "maximum_passage_score", "passage_tie_rule": "stable_passage_id",
        "unit_tie_rule": "stable_reference_unit_id", "lexical_zero_score_fill_used": False,
        "semantic_answerability_threshold_adopted": False,
        "generation_context_budget_verified": False}


def retrieve_lexical(vectorizer, matrix, query, metadata, *, k=5):
    """Transform one query with a verified fitted corpus vectorizer; never refit."""
    import numpy as np
    from scipy import sparse
    _step2314_validate_ranking_metadata(metadata)
    if type(query) is not str:
        raise ValueError("lexical_query_must_be_text")
    if not sparse.issparse(matrix) or matrix.ndim != 2 or matrix.shape[0] != len(metadata):
        raise ValueError("lexical_matrix_and_passage_order_disagree")
    if matrix.dtype != np.dtype("float64") or not np.isfinite(matrix.data).all():
        raise ValueError("lexical_matrix_must_be_finite_float64")
    if not query.strip():
        result = rank_passage_scores(np.zeros(len(metadata), dtype=np.float64), metadata, route="lexical", k=k)
        result["status"] = "unavailable_empty_query"
        return result
    transformed = vectorizer.transform([query])
    if transformed.shape != (1, matrix.shape[1]):
        raise ValueError("lexical_query_feature_order_disagrees")
    if not np.isfinite(transformed.data).all():
        raise ValueError("lexical_query_vector_nonfinite")
    if transformed.nnz == 0:
        return rank_passage_scores(np.zeros(len(metadata), dtype=np.float64), metadata, route="lexical", k=k)
    # Both corpus and query use the fixed fitted L2-normalized TF-IDF transform.
    scores = (matrix @ transformed.T).toarray().reshape(-1)
    return rank_passage_scores(scores, metadata, route="lexical", k=k)


def retrieve_semantic(embeddings, query_embedding, metadata, *, k=5):
    """Rank one externally encoded query using cosine; no model is selected here."""
    import numpy as np
    _step2314_validate_ranking_metadata(metadata)
    corpus, query = np.asarray(embeddings), np.asarray(query_embedding)
    if (corpus.ndim != 2 or corpus.shape[0] != len(metadata) or corpus.shape[1] == 0
            or corpus.dtype.kind not in "fiu" or query.dtype.kind not in "fiu"
            or query.ndim != 1 or query.shape[0] != corpus.shape[1]
            or not np.isfinite(corpus).all() or not np.isfinite(query).all()):
        raise ValueError("semantic_embeddings_require_aligned_finite_numeric_vectors")
    corpus, query = corpus.astype(np.float64, copy=False), query.astype(np.float64, copy=False)
    corpus_norms, query_norm = np.linalg.norm(corpus, axis=1), float(np.linalg.norm(query))
    if not np.isfinite(corpus_norms).all() or not np.isfinite(query_norm):
        raise ValueError("semantic_vector_norms_are_nonfinite")
    if np.any(corpus_norms <= 0.0):
        raise ValueError("semantic_corpus_contains_zero_vectors")
    if query_norm <= 0.0:
        if type(k) is not int or not 1 <= k <= 5:
            raise ValueError("retrieval_k_must_be_an_integer_from_one_to_five")
        return {"status": "unavailable_zero_query_embedding", "route": "semantic", "requested_k": k,
            "returned_distinct_reference_units": 0, "results": [], "semantic_answerability_threshold_adopted": False,
            "generation_context_budget_verified": False}
    scores = (corpus @ query) / (corpus_norms * query_norm)
    scores = np.clip(scores, -1.0, 1.0)
    return rank_passage_scores(scores, metadata, route="semantic", k=k)


def run_step2314_ranking_probes():
    """Check authored scores/vectors only; no actual corpus query or model call."""
    import copy
    import numpy as np
    def row(pid, uid):
        return {"passage_id": pid, "reference_unit_id": uid,
            "required_delivery_record": {"passage_id": pid, "reference_unit_id": uid,
                "display_text": "Complete authored fixture text, context and usage notice: " + pid}}
    metadata = [row("authored-p-z", "authored-u-a"), row("authored-p-a", "authored-u-a"),
        row("authored-p-c", "authored-u-b"), row("authored-p-d", "authored-u-c")]
    checks = []
    def check(name, condition):
        if not bool(condition):
            raise RuntimeError("step23_expanded_ranking_probe_failed:" + name)
        checks.append({"check": name, "status": "pass", "observed": "authored_scores_and_vectors_only"})
    result = rank_passage_scores([0.5, 0.5, 0.5, 0.1], metadata, route="lexical")
    check("duplicate_passages_contribute_one_reference_unit", result["returned_distinct_reference_units"] == 3)
    check("passage_ties_keep_earlier_passage_id", result["results"][0]["passage_id"] == "authored-p-a")
    check("unit_ties_keep_earlier_reference_unit_id", [r["reference_unit_id"] for r in result["results"][:2]]
        == ["authored-u-a", "authored-u-b"])
    result = rank_passage_scores([0.2, 0.7, 0.3, 0.1], metadata, route="semantic")
    check("unit_score_is_maximum_passage_score", result["results"][0]["score"] == 0.7)
    result = rank_passage_scores([0, -0.2, 0.4, 0], metadata, route="lexical")
    check("lexical_nonpositive_scores_are_not_filled", len(result["results"]) == 1)
    check("all_zero_lexical_scores_return_no_results", rank_passage_scores([0] * 4, metadata, route="lexical")["results"] == [])
    result = rank_passage_scores([-0.1, -0.3, -0.2, -0.4], metadata, route="semantic")
    check("semantic_negative_scores_have_no_adopted_abstention_threshold", len(result["results"]) == 3)
    check("cosine_scores_do_not_establish_answerability", all(not row["answerability_established_by_score"] for row in result["results"]))
    long = copy.deepcopy(metadata); long[0]["required_delivery_record"]["display_text"] = "authored required notice " * 400
    selected = rank_passage_scores([1, 0, 0, 0], long, route="lexical")["results"][0]
    check("complete_delivery_is_retained_without_context_truncation", selected["complete_required_delivery_text"] == "authored required notice " * 400)
    selected["required_delivery_record"]["display_text"] = "altered returned copy"
    check("returned_delivery_does_not_mutate_source_metadata", long[0]["required_delivery_record"]["display_text"] != selected["required_delivery_record"]["display_text"])
    nine = [row("authored-p-" + str(i), "authored-u-" + str(i)) for i in range(9)]
    check("retrieval_output_caps_at_five_distinct_units", len(rank_passage_scores(np.arange(9), nine, route="semantic")["results"]) == 5)
    for name, scores, rows, route, k in (
        ("nonfinite_scores", [float("nan"), 0, 0, 0], metadata, "lexical", 5),
        ("boolean_scores", [True] * 4, metadata, "lexical", 5),
        ("misaligned_scores", [1, 2], metadata, "semantic", 5),
        ("unknown_route", [1] * 4, metadata, "unknown", 5),
        ("invalid_k", [1] * 4, metadata, "lexical", 6),
        ("duplicate_passage_ids", [1, 2], [metadata[0], metadata[0]], "lexical", 5)):
        try:
            rank_passage_scores(scores, rows, route=route, k=k)
        except ValueError:
            check("reject_" + name, True)
        else:
            check("reject_" + name, False)
    check("zero_semantic_query_is_unavailable_without_fallback", retrieve_semantic(
        np.asarray([[1, 0], [0, 1], [1, 1], [-1, 0]], dtype=np.float32), np.zeros(2), metadata)["status"]
        == "unavailable_zero_query_embedding")
    return {"scenario_count": len(checks), "check_records": checks,
        "actual_corpus_retrieval_requests": 0, "embedding_or_model_calls": 0,
        "query_or_relevance_judgments_created": 0}


STEP2314_RELEASE_FILENAMES = (
    "expanded_passages.jsonl", "required_delivery_bundles.jsonl", "expanded_metadata.jsonl",
    "lexical_vectorizer.joblib", "lexical_matrix.npz", "semantic_embeddings.npy",
    "retrieval.py", "lexical_worker.py", "semantic_worker.py", "index_diagnostics.json",
    "index_checks.csv", "reload_verification.json", "expanded_manifest.json", "step23_expanded_retrieval_summary.json")


def load_expanded_indexes(release_root, expected_manifest_sha256):
    """Load one explicitly identified release after an externally trusted hash check.

    The caller must supply the manifest SHA-256 from a separately verified
    producer/receipt. A hash read from the same untrusted release is not an
    authority. Joblib is loaded only after all manifest-bound payload bytes,
    flat inventory, runtime versions and public metadata bindings pass.
    """
    import hashlib
    import importlib.metadata as installed
    import json
    import platform
    import re
    from pathlib import Path
    import numpy as np
    from scipy import sparse
    checks = []
    def check(name, condition, observed=True):
        if not bool(condition):
            raise ValueError("expanded_index_load_failed:" + name)
        checks.append({"check": name, "status": "pass", "observed": str(observed)})
    def packed(value):
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    def sha(content):
        return hashlib.sha256(content).hexdigest()
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate_expanded_index_json_key")
            value[key] = item
        return value
    def decode(content):
        return json.loads(content.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite_expanded_index_json")))
    check("caller_supplied_a_manifest_sha256", type(expected_manifest_sha256) is str
        and re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) is not None)
    root = Path(release_root)
    check("release_root_is_absolute_existing_and_not_a_symlink", root.is_absolute() and root.is_dir()
        and root.resolve() == root and not any(p.is_symlink() for p in (root, *root.parents)))
    entries = list(root.iterdir())
    check("release_contains_exactly_the_fourteen_canonical_files", len(entries) == 14
        and {p.name for p in entries} == set(STEP2314_RELEASE_FILENAMES)
        and all(p.is_file() and not p.is_symlink() and p.resolve() == p for p in entries))
    manifest_bytes = (root / "expanded_manifest.json").read_bytes()
    check("manifest_matches_the_separately_trusted_hash", sha(manifest_bytes) == expected_manifest_sha256)
    manifest = decode(manifest_bytes)
    check("manifest_is_canonical_and_has_the_supported_schema", isinstance(manifest, dict)
        and packed(manifest) == manifest_bytes and manifest.get("schema_version") == "step23-expanded-retrieval-manifest-1")
    names = set(STEP2314_RELEASE_FILENAMES) - {"expanded_manifest.json", "step23_expanded_retrieval_summary.json"}
    hashes = manifest.get("payload_hashes")
    check("manifest_binds_exactly_the_twelve_used_payloads", isinstance(hashes, dict) and set(hashes) == names
        and all(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None for value in hashes.values()))
    payloads = {name: (root / name).read_bytes() for name in names}
    check("all_payloads_match_before_any_joblib_deserialization", all(sha(payloads[name]) == digest for name, digest in hashes.items()))
    passage_ids, unit_ids = manifest.get("ordered_passage_ids"), manifest.get("ordered_reference_unit_ids")
    check("manifest_names_eleven_distinct_passages_and_units", isinstance(passage_ids, list) and isinstance(unit_ids, list)
        and len(passage_ids) == len(unit_ids) == len(set(passage_ids)) == len(set(unit_ids)) == 11
        and all(type(value) is str and value for value in passage_ids + unit_ids)
        and re.fullmatch(r"expanded-corpus:[0-9a-f]{64}", str(manifest.get("corpus_id"))) is not None
        and re.fullmatch(r"expanded-retrieval-index:[0-9a-f]{64}", str(manifest.get("expanded_retrieval_id"))) is not None)
    def records(name):
        rows = [decode(line) for line in payloads[name].splitlines()]
        if len(rows) != 11 or any(not isinstance(row, dict) for row in rows):
            raise ValueError("expanded_index_load_failed:eleven_jsonl_records_required:" + name)
        return rows
    passages, metadata, deliveries = (records(name) for name in
        ("expanded_passages.jsonl", "expanded_metadata.jsonl", "required_delivery_bundles.jsonl"))
    check("all_saved_record_orders_match_the_manifest", all(
        [r.get("passage_id") for r in rows] == passage_ids and [r.get("reference_unit_id") for r in rows] == unit_ids
        for rows in (passages, metadata, deliveries)))
    _step2314_validate_ranking_metadata(metadata)
    check("metadata_contains_the_exact_complete_delivery_records", all(
        row["required_delivery_record"] == delivery.get("required_delivery_record")
        and row.get("required_delivery_bundle_id") == delivery.get("required_delivery_bundle_id")
        and row.get("required_delivery_record_sha256") == delivery.get("required_delivery_record_sha256")
            == sha(packed(row["required_delivery_record"]))
        and row.get("index_row") == index
        for index, (row, delivery) in enumerate(zip(metadata, deliveries))))
    versions = manifest.get("versions")
    actual = {name: installed.version(name) for name in ("numpy", "scipy", "scikit-learn", "joblib")}
    check("lexical_runtime_matches_the_recorded_release_before_joblib_loading", isinstance(versions, dict)
        and versions.get("python_version") == platform.python_version()
        and isinstance(versions.get("versions"), dict)
        and all(versions["versions"].get(name) == version for name, version in actual.items()))
    feature_count = manifest.get("lexical_feature_count")
    check("manifest_dimensions_are_explicit", type(feature_count) is int and feature_count > 0
        and manifest.get("semantic_dimension") == 384)
    # The unpickler sees only a file whose complete hash was checked above.
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    vectorizer = joblib.load(root / "lexical_vectorizer.joblib")
    matrix = sparse.load_npz(root / "lexical_matrix.npz").tocsr()
    embeddings = np.load(root / "semantic_embeddings.npy", allow_pickle=False)
    check("lexical_payload_is_the_fixed_tfidf_vectorizer_and_csr_matrix", isinstance(vectorizer, TfidfVectorizer)
        and sparse.isspmatrix_csr(matrix) and matrix.shape == (11, feature_count)
        and matrix.dtype == np.dtype("float64") and matrix.has_sorted_indices
        and np.isfinite(matrix.data).all() and np.all(matrix.data >= 0.0))
    params = vectorizer.get_params(deep=False)
    required_settings = {"analyzer": "word", "lowercase": True, "strip_accents": None,
        "token_pattern": r"(?u)\b\w\w+\b", "preprocessor": None, "tokenizer": None,
        "ngram_range": (1, 2), "min_df": 1, "max_df": 1.0, "max_features": None, "stop_words": None,
        "smooth_idf": True, "sublinear_tf": False, "use_idf": True, "norm": "l2", "binary": False,
        "encoding": "utf-8", "decode_error": "strict"}
    vocabulary = getattr(vectorizer, "vocabulary_", {})
    idf = np.asarray(vectorizer.idf_)
    check("loaded_vocabulary_idf_and_feature_settings_match_the_fixed_route", all(params.get(key) == value for key, value in required_settings.items())
        and np.dtype(params.get("dtype")) == np.dtype("float64")
        and len(vocabulary) == len(vectorizer.get_feature_names_out()) == feature_count
        and set(vocabulary.values()) == set(range(feature_count)) and idf.shape == (feature_count,)
        and idf.dtype == np.dtype("float64") and np.isfinite(idf).all() and np.all(idf > 0.0))
    row_norms = np.sqrt(np.asarray(matrix.multiply(matrix).sum(axis=1)).reshape(-1))
    nonzero = np.diff(matrix.indptr) > 0
    check("loaded_lexical_nonzero_rows_remain_l2_normalized", np.allclose(row_norms[nonzero], 1.0, rtol=1e-12, atol=1e-12))
    check("loaded_semantic_vectors_are_eleven_finite_normalized_float32_rows", embeddings.shape == (11, 384)
        and embeddings.dtype == np.dtype("float32") and np.isfinite(embeddings).all()
        and np.allclose(np.linalg.norm(embeddings.astype(np.float64), axis=1), 1.0, rtol=1e-5, atol=1e-6))
    check("loading_does_not_change_manifest_bound_bytes", (root / "expanded_manifest.json").read_bytes() == manifest_bytes
        and all(sha((root / name).read_bytes()) == digest for name, digest in hashes.items()))
    return {"release_root": root, "manifest": manifest, "vectorizer": vectorizer,
        "lexical_matrix": matrix, "semantic_embeddings": embeddings, "metadata": metadata,
        "loader_checks": checks, "manifest_sha256": expected_manifest_sha256,
        "producer_summary_used_as_trust_anchor": False, "queries_run_during_loading": 0,
        "generation_context_budget_verified": False}


def retrieve_loaded_lexical(index, query, *, k=5):
    return retrieve_lexical(index["vectorizer"], index["lexical_matrix"], query, index["metadata"], k=k)


def retrieve_loaded_semantic(index, query_embedding, *, k=5):
    return retrieve_semantic(index["semantic_embeddings"], query_embedding, index["metadata"], k=k)
