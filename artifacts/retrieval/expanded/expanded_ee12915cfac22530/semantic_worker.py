def summarize_step2314_download_error(error, *, stage, file_key=None):
    """Describe only observed exception attributes, including wrapped SDK causes.

    A LocalEntryNotFoundError by itself does not establish an HTTP, TLS, offline
    or missing-header cause. That wrapper is reported as unknown unless its
    actual exception chain supplies more specific evidence.
    """
    import re
    import socket
    import ssl

    allowed_files = {"README.md", "config.json", "config_sentence_transformers.json",
        "sentence_bert_config.json", "special_tokens_map.json", "tokenizer_config.json",
        "tokenizer.json", "vocab.txt", "modules.json", "1_Pooling/config.json", "model.safetensors"}

    def safe_name(value):
        name = type(value).__name__
        return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", name) else "Exception"

    def attribute(value, key):
        try:
            return getattr(value, key, None)
        except Exception:
            return None

    def integer(value, low=-2147483648, high=2147483647):
        return int(value) if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high else None

    if not isinstance(error, BaseException):
        raise TypeError("download_diagnostic_requires_exception")
    safe_stage = stage if isinstance(stage, str) and re.fullmatch(r"[A-Za-z0-9_]{1,100}", stage) else "download_failure"
    pending, seen, chain = [error], set(), []
    while pending and len(chain) < 6:
        current = pending.pop(0)
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        chain.append(current)
        for key in ("__cause__", "__context__", "reason"):
            nested = attribute(current, key)
            if isinstance(nested, BaseException):
                pending.append(nested)
        args = attribute(current, "args")
        if isinstance(args, tuple):
            pending.extend(value for value in args[:6] if isinstance(value, BaseException))
    truncated = any(isinstance(value, BaseException) and id(value) not in seen for value in pending)
    http_status = os_error = windows_error = verify_code = None
    category_flags = set()
    metadata_category = None
    for current in chain:
        name, module = safe_name(current), type(current).__module__
        response = attribute(current, "response")
        candidate_status = integer(attribute(response, "status_code"), 100, 599)
        if candidate_status is None:
            candidate_status = integer(attribute(current, "code"), 100, 599)
        if http_status is None and candidate_status is not None:
            http_status = candidate_status
        if os_error is None:
            os_error = integer(attribute(current, "errno"))
        if windows_error is None:
            windows_error = integer(attribute(current, "winerror"))
        if verify_code is None:
            verify_code = integer(attribute(current, "verify_code"), 0)
        if isinstance(current, ssl.SSLCertVerificationError):
            category_flags.add("tls_certificate_verification_error")
        elif isinstance(current, ssl.SSLError) or (name == "SSLError" and module.startswith(("requests", "urllib3"))):
            category_flags.add("tls_error")
        if isinstance(current, (TimeoutError, socket.timeout)) or (name in {"Timeout", "ReadTimeout", "ConnectTimeout", "ReadTimeoutError", "ConnectTimeoutError"}
                and module.startswith(("requests", "urllib3"))):
            category_flags.add("timeout")
        if isinstance(current, ConnectionError) or (name in {"ConnectionError", "NewConnectionError", "ProxyError", "MaxRetryError"}
                and module.startswith(("requests", "urllib3"))):
            category_flags.add("connection_error")
        if isinstance(current, socket.gaierror):
            category_flags.add("dns_error")
        if name == "OfflineModeIsEnabled" and module.startswith("huggingface_hub"):
            category_flags.add("offline_mode")
        if name == "FileMetadataError" and module.startswith("huggingface_hub"):
            metadata_category = "required_metadata_unavailable"
            # Match the SDK's fixed diagnostic wording; do not return any part
            # of the message, which may otherwise contain network details.
            try:
                message = str(current).lower()
            except Exception:
                message = ""
            if "does not have a content-length" in message:
                metadata_category = "required_content_length_missing"
            elif "does not have an etag" in message:
                metadata_category = "required_etag_missing"
            elif ("does not have a commit hash" in message
                    or "distant resource does not seem to be on huggingface.co." in message):
                metadata_category = "required_commit_metadata_missing"
    if http_status is not None:
        category = "http_error"
    else:
        category = next((value for value in ("tls_certificate_verification_error", "offline_mode", "tls_error",
            "dns_error", "timeout", "connection_error") if value in category_flags), None)
        category = category or metadata_category or ("os_error" if os_error is not None or windows_error is not None else "underlying_cause_unavailable")
    return {"status": "failed", "stage": safe_stage,
        "exception_type": safe_name(error), "exception_chain_types": [safe_name(value) for value in chain],
        "exception_chain_truncated": truncated, "diagnostic_category": category,
        "http_status": http_status, "os_error": os_error, "windows_error": windows_error,
        "ssl_verify_code": verify_code, "public_model_file": file_key if isinstance(file_key, str) and file_key in allowed_files else None,
        "underlying_cause_identified": category != "underlying_cause_unavailable",
        "raw_exception_messages_included": False}

_STEP2314_WORKER_REPO = "sentence-transformers/all-MiniLM-L6-v2"

_STEP2314_WORKER_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"

_STEP2314_WORKER_FILES = {
    "README.md": (10502, "dcd602d2fd35c203a247304a06fec6654a12f7941b739f9221a064fe8dc3b7f0"),
    "config.json": (612, "953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41"),
    "config_sentence_transformers.json": (116, "061ca9d39661d6c6d6de5ba27f79a1cd5770ea247f8d46412a68a498dc5ac9f3"),
    "sentence_bert_config.json": (53, "fc1993fde0a95c24ec6c022539d41cf6e2f7c9721e5415d6fb6897472a9cd4b7"),
    "special_tokens_map.json": (112, "303df45a03609e4ead04bc3dc1536d0ab19b5358db685b6f3da123d05ec200e3"),
    "tokenizer_config.json": (350, "acb92769e8195aabd29b7b2137a9e6d6e25c476a4f15aa4355c233426c61576b"),
    "tokenizer.json": (466247, "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037"),
    "vocab.txt": (231508, "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3"),
    "modules.json": (349, "84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf"),
    "1_Pooling/config.json": (190, "4be450dde3b0273bb9787637cfbd28fe04a7ba6ab9d36ac48e92b11e350ffc23"),
    "model.safetensors": (90868376, "53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db"),
}

def _step2314_worker_packed(value):
    import json
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")

def _step2314_worker_sha(content):
    import hashlib
    return hashlib.sha256(content).hexdigest()

def _step2314_worker_path(value, *, must_exist=False):
    from pathlib import Path
    if type(value) is not str or not value:
        raise ValueError("invalid_path")
    path = Path(value)
    if (not path.is_absolute() or path.resolve(strict=False) != path
            or any(parent.is_symlink() for parent in (path, *path.parents))):
        raise ValueError("unsafe_path")
    if must_exist and not path.exists():
        raise ValueError("missing_path")
    return path

def _step2314_worker_verify_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("invalid_model_manifest")
    if (manifest.get("repo_id") != _STEP2314_WORKER_REPO or manifest.get("revision") != _STEP2314_WORKER_REVISION
            or manifest.get("license_declared") != "apache-2.0" or type(manifest.get("files")) is not list):
        raise ValueError("unbound_model_identity")
    rows = manifest["files"]
    if (len(rows) != 11 or len({row.get("relative_path") for row in rows if isinstance(row, dict)}) != 11
            or {row.get("relative_path"): (row.get("bytes"), row.get("sha256")) for row in rows
                if isinstance(row, dict)} != _STEP2314_WORKER_FILES):
        raise ValueError("unbound_model_payloads")
    return True

def _step2314_worker_verify_cache(cache):
    """A changed, partial or unfamiliar existing cache is never repaired."""
    if not cache.exists():
        return None
    if not cache.is_dir() or cache.is_symlink() or cache.resolve() != cache:
        raise ValueError("invalid_model_cache")
    items = list(cache.rglob("*"))
    if (any(item.is_symlink() or (not item.is_file() and not item.is_dir()) for item in items)
            or {item.relative_to(cache).as_posix() for item in items if item.is_file()} != set(_STEP2314_WORKER_FILES)
            or {item.relative_to(cache).as_posix() for item in items if item.is_dir()} != {"1_Pooling"}):
        raise ValueError("partial_or_unfamiliar_model_cache_preserved")
    hashes = {}
    for name, (size, digest) in _STEP2314_WORKER_FILES.items():
        content = (cache / name).read_bytes()
        if len(content) != size or _step2314_worker_sha(content) != digest:
            raise ValueError("changed_model_cache_preserved")
        hashes[name] = digest
    return hashes

"""Encode only eleven explicitly bound reference cores with the adopted CPU encoder."""


def verify_step2314_semantic_corpus(request):
    import importlib.metadata as metadata
    import json
    import os
    import platform
    import re
    import socket
    import urllib.request

    global _STEP2314_WORKER_STAGE
    _STEP2314_WORKER_STAGE = "request_and_adopted_semantic_bindings"
    required = {"mode", "corpus_id", "semantic_runtime_adoption_id", "runtime_environment", "model_source_manifest",
        "model_metadata", "model_cache_root", "passages", "embeddings_path", "result_path", "expected_embeddings_sha256"}
    if (not isinstance(request, dict) or not required.issubset(request)
            or set(request) != required
            or request.get("mode") not in {"encode_corpus", "verify_saved"}
            or (request["mode"] == "encode_corpus" and request["expected_embeddings_sha256"] is not None)
            or (request["mode"] == "verify_saved" and re.fullmatch(r"[0-9a-f]{64}", str(request.get("expected_embeddings_sha256"))) is None)
            or re.fullmatch(r"expanded-corpus:[0-9a-f]{64}", str(request.get("corpus_id"))) is None
            or re.fullmatch(r"semantic-runtime-adoption:[0-9a-f]{64}", str(request.get("semantic_runtime_adoption_id"))) is None):
        raise ValueError("invalid_semantic_corpus_worker_request")
    _step2314_worker_verify_manifest(request["model_source_manifest"])
    rows = request["passages"]
    fields = {"passage_id", "passage_record_sha256", "reference_unit_id", "text", "text_sha256",
        "encoded_token_ids_sha256", "encoded_tokens_including_specials"}
    if (not isinstance(rows, list) or len(rows) != 11 or any(not isinstance(row, dict) or set(row) != fields
            or re.fullmatch(r"[a-z][a-z0-9-]{2,80}:[0-9a-f]{64}", str(row.get("passage_id"))) is None
            or re.fullmatch(r"[a-z][a-z0-9-]{2,80}:[0-9a-f]{64}", str(row.get("reference_unit_id"))) is None
            or any(re.fullmatch(r"[0-9a-f]{64}", str(row.get(key))) is None
                for key in ("passage_record_sha256", "text_sha256", "encoded_token_ids_sha256"))
            or type(row.get("text")) is not str or not row["text"].strip()
            or _step2314_worker_sha(row["text"].encode("utf-8")) != row["text_sha256"]
            or type(row.get("encoded_tokens_including_specials")) is not int
            or not 2 <= row["encoded_tokens_including_specials"] <= 200 for row in rows)
            or len({row["passage_id"] for row in rows}) != 11
            or len({row["reference_unit_id"] for row in rows}) != 11):
        raise ValueError("unbound_or_oversized_semantic_corpus_population")
    cache = _step2314_worker_path(request["model_cache_root"], must_exist=True)
    vectors_path = _step2314_worker_path(request["embeddings_path"])
    result_path = _step2314_worker_path(request["result_path"])
    if (vectors_path == result_path or result_path.exists() or not vectors_path.parent.is_dir()
            or not result_path.parent.is_dir() or vectors_path.is_relative_to(cache) or result_path.is_relative_to(cache)
            or (request["mode"] == "encode_corpus" and vectors_path.exists())
            or (request["mode"] == "verify_saved" and (not vectors_path.is_file()
                or _step2314_worker_sha(vectors_path.read_bytes()) != request["expected_embeddings_sha256"]))):
        raise ValueError("invalid_or_existing_semantic_corpus_worker_output")
    globals()["_STEP2314_SAFE_RESULT_PATH"] = str(result_path)
    hashes_before = _step2314_worker_verify_cache(cache)
    if hashes_before is None:
        raise ValueError("semantic_corpus_model_cache_absent_no_download_fallback")
    versions = {}
    expected_environment = request["runtime_environment"]
    if not isinstance(expected_environment, dict) or not isinstance(expected_environment.get("versions"), dict):
        raise ValueError("missing_recorded_semantic_environment")
    minimum = {"sentence-transformers", "transformers", "tokenizers", "huggingface-hub", "safetensors", "torch", "numpy"}
    if not minimum.issubset(expected_environment["versions"]):
        raise ValueError("incomplete_recorded_semantic_environment")
    for name, expected in expected_environment["versions"].items():
        try:
            observed = metadata.version(name)
        except metadata.PackageNotFoundError:
            observed = None
        if observed != expected:
            raise ValueError("recorded_semantic_runtime_distribution_changed")
        versions[name] = observed
    if (platform.python_version() != expected_environment.get("python_version")
            or any(versions[name] != value for name, value in {"sentence-transformers": "5.1.2",
                "transformers": "4.57.1", "tokenizers": "0.22.1", "huggingface-hub": "0.36.0",
                "safetensors": "0.6.2"}.items())):
        raise ValueError("recorded_semantic_runtime_python_or_pins_changed")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
        TOKENIZERS_PARALLELISM="false", USE_TF="0", USE_FLAX="0")
    def no_network(*args, **kwargs):
        raise RuntimeError("network_disabled_during_semantic_corpus_encoding")
    socket.create_connection = no_network
    socket.socket.connect = no_network
    urllib.request.urlopen = no_network
    urllib.request.OpenerDirector.open = no_network
    _STEP2314_WORKER_STAGE = "offline_frozen_cpu_encoder_loading"
    import numpy as np
    import torch
    from safetensors.torch import load_file
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    checks = []
    def check(name, condition, observed=True):
        if not bool(condition):
            raise ValueError("semantic_corpus_worker_check_failed:" + name)
        checks.append({"check": name, "status": "pass", "observed": str(observed)})
    model = SentenceTransformer(str(cache), device="cpu", local_files_only=True,
        trust_remote_code=False, model_kwargs={"use_safetensors": True, "dtype": torch.float32})
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    tokenizer, backbone = model.tokenizer, model[0].auto_model
    raw_config = json.loads((cache / "tokenizer_config.json").read_bytes())
    st_config = json.loads((cache / "sentence_bert_config.json").read_bytes())
    pooling = json.loads((cache / "1_Pooling/config.json").read_bytes())
    modules = json.loads((cache / "modules.json").read_bytes())
    adopted = request["model_metadata"]
    configured, loaded, positions = int(model.max_seq_length), int(tokenizer.model_max_length), int(backbone.config.max_position_embeddings)
    dimension, special = int(model.get_sentence_embedding_dimension()), int(tokenizer.num_special_tokens_to_add(pair=False))
    check("loaded_encoder_and_tokenizer_match_adopted_limits_and_recipe", configured == st_config["max_seq_length"]
        == adopted["sentence_transformer_max_seq_length"] == 256
        and loaded == adopted["loaded_tokenizer_model_max_length"] == 256
        and raw_config["model_max_length"] == adopted["raw_tokenizer_declared_model_max_length"] == 512
        and positions == adopted["model_max_position_embeddings"] == 512
        and dimension == adopted["dimension"] == 384 and special == adopted["special_tokens_per_single_sequence"] == 2
        and adopted["effective_project_encoded_limit"] == 200 and adopted["device"] == "cpu" and adopted["dtype"] == "float32"
        and adopted["repo_id"] == _STEP2314_WORKER_REPO and adopted["revision"] == _STEP2314_WORKER_REVISION
        and adopted["license_declared"] == "apache-2.0" and adopted["trust_remote_code"] is False
        and adopted["safetensors_only"] is adopted["parameters_frozen"] is adopted["evaluation_mode"] is True
        and tokenizer.is_fast and adopted["normalized_embeddings"] is True
        and getattr(model, "prompts", None) == {"query": "", "document": ""} and getattr(model, "default_prompt_name", None) is None
        and getattr(model, "truncate_dim", None) is None)
    check("published_attention_mean_and_l2_modules_are_unchanged", pooling == {"word_embedding_dimension": 384,
        "pooling_mode_cls_token": False, "pooling_mode_mean_tokens": True, "pooling_mode_max_tokens": False,
        "pooling_mode_mean_sqrt_len_tokens": False}
        and [row["type"] for row in modules] == ["sentence_transformers.models.Transformer",
            "sentence_transformers.models.Pooling", "sentence_transformers.models.Normalize"])
    check("encoder_is_evaluation_only_frozen_cpu_float32", all(not module.training for module in model.modules())
        and all(not parameter.requires_grad and parameter.grad is None and parameter.device.type == "cpu"
            and parameter.dtype == torch.float32 for parameter in model.parameters()))
    checkpoint = load_file(str(cache / "model.safetensors"), device="cpu")
    state = backbone.state_dict()
    check("all_103_checkpoint_state_tensors_and_position_buffer_match", len(state) == 103
        and set(checkpoint) - set(state) == {"embeddings.position_ids"} and set(state).issubset(checkpoint)
        and all(torch.equal(state[key], checkpoint[key]) for key in state)
        and torch.equal(checkpoint["embeddings.position_ids"], backbone.embeddings.position_ids))
    del checkpoint, state
    def state_sha():
        import hashlib
        digest = hashlib.sha256()
        for key, tensor in sorted(list(model.named_parameters()) + [("buffer:" + k, t) for k, t in model.named_buffers()]):
            value = tensor.detach().cpu().contiguous()
            digest.update(_step2314_worker_packed({"key": key, "dtype": str(value.dtype), "shape": list(value.shape)}))
            digest.update(value.numpy().tobytes(order="C"))
        return digest.hexdigest()
    state_before = state_sha()
    counters = {"embedding_api_requests": 0, "backbone_forward_batches": 0, "tokenizer_requests": 0,
        "forward_input_rows_checked": 0}
    texts = [row["text"] for row in rows]
    counters["tokenizer_requests"] += 1
    untruncated = tokenizer(texts, add_special_tokens=True, truncation=False, padding=False,
        return_attention_mask=True, return_token_type_ids=False)
    ids_rows = untruncated["input_ids"]
    for index, (row, ids, attention) in enumerate(zip(rows, ids_rows, untruncated["attention_mask"]), 1):
        check("approved_core_token_ids_match_before_any_forward_" + str(index), len(ids) == row["encoded_tokens_including_specials"]
            and len(ids) <= 200 and len(ids) == len(attention) and all(v == 1 for v in attention)
            and _step2314_worker_sha(_step2314_worker_packed(ids)) == row["encoded_token_ids_sha256"])
    check("all_eleven_approved_cores_were_counted_before_any_forward", len(ids_rows) == 11
        and counters["backbone_forward_batches"] == 0)
    from collections import Counter
    expected_forward_rows = Counter(tuple(ids) for ids in ids_rows)
    actual_forward_rows = Counter()
    original_tokenize = model.tokenize
    def counted_tokenize(texts, **kwargs):
        counters["tokenizer_requests"] += 1
        return original_tokenize(texts, **kwargs)
    model.tokenize = counted_tokenize
    def checked_forward(module, args, kwargs):
        counters["backbone_forward_batches"] += 1
        batch_ids, attention = kwargs.get("input_ids"), kwargs.get("attention_mask")
        if batch_ids is None or attention is None:
            raise ValueError("semantic_forward_missing_explicit_inputs")
        for ids, mask in zip(batch_ids.detach().cpu().tolist(), attention.detach().cpu().tolist()):
            if len(ids) != len(mask) or any(v not in (0, 1) for v in mask) or mask != sorted(mask, reverse=True):
                raise ValueError("semantic_forward_attention_mask_changed")
            retained = tuple(value for value, valid in zip(ids, mask) if valid)
            if len(retained) > 200 or retained not in expected_forward_rows:
                raise ValueError("semantic_forward_inputs_differ_from_prechecked_approved_cores")
            actual_forward_rows[retained] += 1
            counters["forward_input_rows_checked"] += 1
    hook = backbone.register_forward_pre_hook(checked_forward, with_kwargs=True)
    _STEP2314_WORKER_STAGE = "approved_corpus_core_embedding"
    batch_size = 11 if request["mode"] == "encode_corpus" else 2
    counters["embedding_api_requests"] += 1
    try:
        with torch.inference_mode():
            vectors = model.encode(texts, batch_size=batch_size, precision="float32", normalize_embeddings=True,
                convert_to_numpy=True, show_progress_bar=False)
    finally:
        hook.remove()
    check("backbone_received_only_the_eleven_exact_prechecked_cores", actual_forward_rows == expected_forward_rows
        and counters["forward_input_rows_checked"] == 11 and counters["backbone_forward_batches"] == (1 if batch_size == 11 else 6))
    check("corpus_vectors_are_finite_float32_normalized_in_eleven_row_order", isinstance(vectors, np.ndarray)
        and vectors.dtype == np.dtype("float32") and vectors.shape == (11, 384) and np.isfinite(vectors).all()
        and np.allclose(np.linalg.norm(vectors.astype(np.float64), axis=1), np.ones(11), rtol=1e-5, atol=1e-6))
    state_after = state_sha()
    check("encoder_weights_buffers_and_gradients_are_unchanged", state_before == state_after
        and all(not p.requires_grad and p.grad is None for p in model.parameters()))
    hashes_after = _step2314_worker_verify_cache(cache)
    check("all_eleven_pinned_model_files_remain_unchanged", hashes_before == hashes_after)
    verified_max_difference = None
    if request["mode"] == "verify_saved":
        _STEP2314_WORKER_STAGE = "saved_corpus_matrix_comparison"
        before_file = _step2314_worker_sha(vectors_path.read_bytes())
        expected = np.load(vectors_path, allow_pickle=False)
        check("saved_corpus_matrix_is_bound_finite_normalized_float32", before_file == request["expected_embeddings_sha256"]
            and expected.dtype == np.dtype("float32") and expected.shape == (11, 384) and np.isfinite(expected).all()
            and np.allclose(np.linalg.norm(expected.astype(np.float64), axis=1), np.ones(11), rtol=1e-5, atol=1e-6))
        verified_max_difference = float(np.max(np.abs(vectors.astype(np.float64) - expected.astype(np.float64))))
        check("fresh_independent_batches_match_saved_corpus_row_order", np.allclose(vectors, expected, rtol=1e-5, atol=1e-6),
            verified_max_difference)
        check("saved_corpus_matrix_is_unchanged_after_verification", _step2314_worker_sha(vectors_path.read_bytes()) == before_file)
    else:
        _STEP2314_WORKER_STAGE = "new_corpus_matrix_publication"
        with vectors_path.open("xb") as handle:
            np.save(handle, vectors, allow_pickle=False); handle.flush(); os.fsync(handle.fileno())
    bindings = [{key: row[key] for key in ("passage_id", "passage_record_sha256", "reference_unit_id", "text_sha256",
        "encoded_token_ids_sha256", "encoded_tokens_including_specials")} for row in rows]
    report = {"schema_version": "step23-expanded-corpus-semantic-worker-report-1", "status": "verified_expanded_corpus_semantic_embeddings",
        "mode": request["mode"], "corpus_id": request["corpus_id"], "semantic_runtime_adoption_id": request["semantic_runtime_adoption_id"],
        "model_repo_id": _STEP2314_WORKER_REPO, "model_revision": _STEP2314_WORKER_REVISION,
        "runtime_environment": {"python_version": platform.python_version(), "versions": versions},
        "device": "cpu", "dtype": "float32", "embedding_dimension": 384, "embedding_shape": [11, 384],
        "normalized_embeddings": True, "parameters_frozen": True, "evaluation_mode": True,
        "cpu_threads": 1, "cpu_interop_threads": 1, "deterministic_algorithms_enabled": True,
        "pooling": "attention_masked_mean_then_l2_normalization", "trust_remote_code": False,
        "weight_format": "safetensors", "checkpoint_state_tensors_verified": 103,
        "matched_nonpersistent_position_buffer": True,
        "project_encoded_core_limit": 200, "core_token_counts": [len(ids) for ids in ids_rows],
        "full_untruncated_pre_forward_token_ids_verified": True,
        "native_encoder_truncation_did_not_change_any_forward_input": True,
        "passage_bindings": bindings, "embedding_rows_computed": 11,
        "embedding_rows_saved": 11 if request["mode"] == "encode_corpus" else 0,
        "saved_matrix_rows_reverified": 11 if request["mode"] == "verify_saved" else 0,
        "model_instances_loaded": 1, "checkpoint_verification_tensor_loads": 1,
        **counters, "model_state_sha256_before": state_before, "model_state_sha256_after": state_after,
        "model_state_fingerprint_policy": "sorted_named_parameters_and_all_named_buffers_including_nonpersistent",
        "task_prompt_applied": False,
        "registered_prompt_names": sorted(model.prompts), "registered_prompt_texts_are_empty": True,
        "default_prompt_name": None, "truncate_dim": None,
        "model_file_hashes": hashes_after, "embeddings_file_sha256": _step2314_worker_sha(vectors_path.read_bytes()),
        "computed_array_content_sha256": _step2314_worker_sha(vectors.tobytes(order="C")),
        "max_absolute_difference_from_saved_matrix": verified_max_difference,
        "comparison_rtol": 1e-5, "comparison_atol": 1e-6,
        "publisher_or_model_download_requests": 0, "query_embedding_requests": 0, "delivery_texts_embedded": 0,
        "classifier_texts_processed": 0, "model_training_or_finetuning_runs": 0,
        "gpu_runtime_verified": False, "retrieval_requests": 0, "questions_or_judgments_used": 0,
        "checks": checks}
    _STEP2314_WORKER_STAGE = "semantic_corpus_report_publication"
    with result_path.open("xb") as handle:
        handle.write(_step2314_worker_packed(report)); handle.flush(); os.fsync(handle.fileno())
    return report


def _step2314_semantic_main():
    import json
    import sys
    try:
        request = json.load(sys.stdin)
        verify_step2314_semantic_corpus(request)
        return 0
    except Exception as error:
        result = summarize_step2314_download_error(error,
            stage=globals().get("_STEP2314_WORKER_STAGE", "semantic_corpus_request_parsing"))
        try:
            path = _step2314_worker_path(globals()["_STEP2314_SAFE_RESULT_PATH"])
            with path.open("xb") as handle:
                handle.write(_step2314_worker_packed(result)); handle.flush()
        except Exception:
            pass
        print(json.dumps(result, sort_keys=True), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(_step2314_semantic_main())

