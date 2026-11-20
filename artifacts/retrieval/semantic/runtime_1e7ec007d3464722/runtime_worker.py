"""Validate authored-only embedding diagnostics without loading any model."""


STEP23_AUTHORED_RUNTIME_TEXTS = (
    "A basketball player practices a chest pass.",
    "A teenager follows a regular sleep schedule.",
    "The reference includes its original source and required notices.",
    "Short text.",
    "Basketball footwork and passing drills are different activities.",
    "A basketball player practices a chest pass.",
)


def _step235_runtime_texts(texts):
    """Only the six authored diagnostics are permitted by this validation recipe."""
    if (not isinstance(texts, (list, tuple)) or len(texts) != len(STEP23_AUTHORED_RUNTIME_TEXTS)
            or any(type(value) is not str for value in texts)
            or tuple(texts) != STEP23_AUTHORED_RUNTIME_TEXTS):
        raise ValueError("step23_embedding_validation_failed:authored_text_population")
    return tuple(texts)


def validate_step23_embedding_outputs(texts, full_vectors, repeated_vectors, reordered_vectors,
                                     batched_vectors, *, dimension=384, rtol=1e-5, atol=1e-6):
    """Validate four forward results on the exact authored population.

    ``reordered_vectors`` must be returned from the reversed text order, without
    restoring that order beforehand. ``batched_vectors`` must concatenate the
    independently encoded batches back into the original text order. Comparing
    their rows checks batch/padding composition invariance, not retrieval quality.
    This helper does not perform a model or tokenizer call.
    """
    import numpy as np

    values = _step235_runtime_texts(texts)
    if type(dimension) is not int or dimension < 1:
        raise ValueError("step23_embedding_validation_failed:dimension")
    for key, value in (("rtol", rtol), ("atol", atol)):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not np.isfinite(value) or value < 0 or value > 1e-3):
            raise ValueError("step23_embedding_validation_failed:" + key)
    checks = []

    def check(name, condition, observed=True):
        if not bool(condition):
            raise ValueError("step23_embedding_validation_failed:" + name)
        checks.append({"check": name, "status": "pass", "observed": str(observed)})

    arrays = {"full": full_vectors, "repeat": repeated_vectors,
              "reverse_order": reordered_vectors, "independent_batches": batched_vectors}
    expected_shape = (len(values), dimension)
    for name, vectors in arrays.items():
        check(name + "_is_float32_matrix", isinstance(vectors, np.ndarray)
              and vectors.dtype == np.dtype("float32") and vectors.shape == expected_shape,
              expected_shape)
        check(name + "_has_finite_values", np.isfinite(vectors).all())
        norms = np.linalg.norm(vectors.astype(np.float64), axis=1)
        check(name + "_rows_are_l2_normalized", np.allclose(norms, np.ones(len(values)),
              rtol=rtol, atol=atol), float(np.max(np.abs(norms - 1.0))))
        cosine = vectors.astype(np.float64) @ vectors.astype(np.float64).T
        cosine_tolerance = max(1e-6, 4.0 * (rtol + atol))
        check(name + "_cosine_values_are_bounded", np.all(cosine >= -1.0 - cosine_tolerance)
              and np.all(cosine <= 1.0 + cosine_tolerance))
    check("repeated_forward_matches", np.allclose(full_vectors, repeated_vectors, rtol=rtol, atol=atol),
          float(np.max(np.abs(full_vectors.astype(np.float64) - repeated_vectors))))
    check("reverse_order_restores_the_original_rows", np.allclose(full_vectors, reordered_vectors[::-1],
          rtol=rtol, atol=atol), float(np.max(np.abs(full_vectors.astype(np.float64) - reordered_vectors[::-1]))))
    check("independent_batch_and_padding_composition_matches", np.allclose(full_vectors, batched_vectors,
          rtol=rtol, atol=atol), float(np.max(np.abs(full_vectors.astype(np.float64) - batched_vectors))))
    duplicate_indices = [(left, right) for left in range(len(values)) for right in range(left + 1, len(values))
                         if values[left] == values[right]]
    check("authored_population_includes_duplicate_text", bool(duplicate_indices))
    check("duplicate_text_embeddings_match", all(np.allclose(full_vectors[left], full_vectors[right],
          rtol=rtol, atol=atol) for left, right in duplicate_indices))
    return checks


def validate_step23_runtime_token_counts(texts, untruncated_counts, *, configured_max_sequence_length,
                                        tokenizer_model_max_length, model_position_limit,
                                        special_tokens_count, truncation_used=False):
    """Check counts supplied by the actual tokenizer with special tokens included.

    Counts must come from a separate untruncated tokenizer call. The helper checks
    accounting and limits; it does not infer or manufacture token counts.
    """
    values = _step235_runtime_texts(texts)
    limits = (configured_max_sequence_length, tokenizer_model_max_length, model_position_limit)
    if (any(type(value) is not int or value < 1 for value in limits)
            or type(special_tokens_count) is not int or special_tokens_count < 0
            or type(truncation_used) is not bool or truncation_used):
        raise ValueError("step23_embedding_validation_failed:tokenizer_limit_metadata")
    if (not isinstance(untruncated_counts, (list, tuple)) or len(untruncated_counts) != len(values)
            or any(type(value) is not int or value < max(1, special_tokens_count) for value in untruncated_counts)):
        raise ValueError("step23_embedding_validation_failed:untruncated_token_counts")
    if (configured_max_sequence_length > min(tokenizer_model_max_length, model_position_limit)
            or max(untruncated_counts) > configured_max_sequence_length):
        raise ValueError("step23_embedding_validation_failed:authored_input_exceeds_verified_limit")
    return [
        {"check": "authored_token_counts_cover_all_six_inputs", "status": "pass", "observed": str(len(values))},
        {"check": "diagnostic_tokenization_used_no_truncation", "status": "pass", "observed": "False"},
        {"check": "configured_limit_respects_tokenizer_and_model_positions", "status": "pass",
         "observed": str(configured_max_sequence_length)},
        {"check": "all_diagnostic_counts_include_special_tokens_and_fit", "status": "pass",
         "observed": str(max(untruncated_counts))},
    ]


def run_step23_embedding_validation_probes():
    """Exercise validation with artificial arrays; these are not model forwards."""
    import copy
    import numpy as np

    texts = list(STEP23_AUTHORED_RUNTIME_TEXTS)
    full = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [-1, 0, 0], [0, -1, 0], [1, 0, 0]], dtype=np.float32)
    base = [texts, full, full.copy(), full[::-1].copy(), full.copy()]
    checks = []

    def check(name, condition):
        if not bool(condition):
            raise ValueError("step23_embedding_probe_failed:" + name)
        checks.append({"check": name, "status": "pass", "observed": "authored_artificial_arrays_only_no_model_run"})

    def run(values, **kwargs):
        return validate_step23_embedding_outputs(*values, dimension=3, **kwargs)

    def reject(name, mutate, **kwargs):
        values = copy.deepcopy(base)
        mutate(values)
        try:
            run(values, **kwargs)
        except (ValueError, TypeError):
            check(name, True)
        else:
            raise ValueError("step23_embedding_probe_failed:" + name)

    before = copy.deepcopy(base)
    good = run(base)
    check("normalized_artificial_vectors_pass", len(good) == 21 and all(row["status"] == "pass" for row in good))
    check("inputs_remain_unchanged", base[0] == before[0] and all(np.array_equal(left, right)
          for left, right in zip(base[1:], before[1:])))
    reject("unfamiliar_or_corpus_text_rejected", lambda x: x[0].__setitem__(0, "A real source record would not be permitted."))
    reject("missing_authored_text_rejected", lambda x: x[0].pop())
    reject("nonstring_text_rejected", lambda x: x[0].__setitem__(1, None))
    reject("float64_forward_rejected", lambda x: x.__setitem__(1, x[1].astype(np.float64)))
    reject("nonarray_forward_rejected", lambda x: x.__setitem__(1, x[1].tolist()))
    reject("wrong_dimension_rejected", lambda x: x.__setitem__(1, x[1][:, :2]))
    reject("missing_row_rejected", lambda x: x.__setitem__(1, x[1][:-1]))
    reject("nan_forward_rejected", lambda x: x[1].__setitem__((0, 0), np.nan))
    reject("infinite_forward_rejected", lambda x: x[1].__setitem__((0, 0), np.inf))
    reject("zero_vector_rejected", lambda x: x[1].__setitem__(0, np.zeros(3, dtype=np.float32)))
    reject("unnormalized_vector_rejected", lambda x: x[1].__setitem__((0, 0), 2.0))
    reject("repeat_forward_drift_rejected", lambda x: x[2].__setitem__(0, x[2][1]))
    reject("unreversed_rows_rejected", lambda x: x.__setitem__(3, x[1].copy()))
    reject("batch_order_drift_rejected", lambda x: x[4].__setitem__(0, x[4][1]))
    reject("loose_tolerance_rejected", lambda x: None, atol=0.1)
    reject("nonfinite_tolerance_rejected", lambda x: None, rtol=float("nan"))
    # Every forward may agree while repeated source text differs; that must fail too.
    changed = full.copy()
    changed[-1] = changed[1]
    try:
        validate_step23_embedding_outputs(texts, changed, changed.copy(), changed[::-1].copy(), changed.copy(), dimension=3)
    except ValueError:
        check("duplicate_text_difference_rejected", True)
    else:
        raise ValueError("step23_embedding_probe_failed:duplicate_text_difference_rejected")

    token_kwargs = {"configured_max_sequence_length": 256, "tokenizer_model_max_length": 512,
                    "model_position_limit": 512, "special_tokens_count": 2, "truncation_used": False}
    counts = [12, 13, 17, 5, 16, 12]
    token_checks = validate_step23_runtime_token_counts(texts, counts, **token_kwargs)
    check("authored_count_accounting_passes_without_claiming_actual_tokenizer_run", len(token_checks) == 4)
    for name, new_counts, update in (
        ("missing_token_count_rejected", counts[:-1], {}),
        ("boolean_token_count_rejected", [True] + counts[1:], {}),
        ("negative_token_count_rejected", [-1] + counts[1:], {}),
        ("count_below_special_token_allowance_rejected", [1] + counts[1:], {}),
        ("truncated_tokenization_rejected", counts, {"truncation_used": True}),
        ("overlong_authored_input_rejected", [257] + counts[1:], {}),
        ("configured_limit_above_model_rejected", counts, {"model_position_limit": 128}),
        ("configured_limit_above_tokenizer_rejected", counts, {"tokenizer_model_max_length": 128}),
        ("unknown_tokenizer_limit_rejected", counts, {"tokenizer_model_max_length": None}),
    ):
        try:
            validate_step23_runtime_token_counts(texts, new_counts, **dict(token_kwargs, **update))
        except ValueError:
            check(name, True)
        else:
            raise ValueError("step23_embedding_probe_failed:" + name)
    return {"scenario_count": len(checks), "check_records": checks,
            "actual_model_forward_calls": 0, "actual_tokenizer_calls": 0,
            "study_or_corpus_texts_processed": 0, "model_quality_assessed": False}


"""Validate a portable copy of the exact public model; do not load its weights."""

STEP235_PORTABLE_MODEL_BINDING = {'archive_file_name': 'all-MiniLM-L6-v2-1110a243fdf4.zip', 'archive_bytes': 83501492, 'archive_sha256': '95e916e551dc17adfdd83d9720436b6f023c0c9fa3f66471732f64dae6e13888', 'repo_id': 'sentence-transformers/all-MiniLM-L6-v2', 'revision': '1110a243fdf4706b3f48f1d95db1a4f5529b4d41', 'members': {'model/README.md': {'bytes': 10502, 'sha256': 'dcd602d2fd35c203a247304a06fec6654a12f7941b739f9221a064fe8dc3b7f0'}, 'model/config.json': {'bytes': 612, 'sha256': '953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41'}, 'model/config_sentence_transformers.json': {'bytes': 116, 'sha256': '061ca9d39661d6c6d6de5ba27f79a1cd5770ea247f8d46412a68a498dc5ac9f3'}, 'model/sentence_bert_config.json': {'bytes': 53, 'sha256': 'fc1993fde0a95c24ec6c022539d41cf6e2f7c9721e5415d6fb6897472a9cd4b7'}, 'model/special_tokens_map.json': {'bytes': 112, 'sha256': '303df45a03609e4ead04bc3dc1536d0ab19b5358db685b6f3da123d05ec200e3'}, 'model/tokenizer_config.json': {'bytes': 350, 'sha256': 'acb92769e8195aabd29b7b2137a9e6d6e25c476a4f15aa4355c233426c61576b'}, 'model/tokenizer.json': {'bytes': 466247, 'sha256': 'be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037'}, 'model/vocab.txt': {'bytes': 231508, 'sha256': '07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3'}, 'model/modules.json': {'bytes': 349, 'sha256': '84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf'}, 'model/1_Pooling/config.json': {'bytes': 190, 'sha256': '4be450dde3b0273bb9787637cfbd28fe04a7ba6ab9d36ac48e92b11e350ffc23'}, 'model/model.safetensors': {'bytes': 90868376, 'sha256': '53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db'}, 'distribution/LICENSE-2.0.txt': {'bytes': 11358, 'sha256': 'cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'}, 'distribution/PROVENANCE.json': {'bytes': 4539, 'sha256': '2cb95326e5c180577baafff16a126e125feb6753c22c880b649df6b92d509ae6'}, 'distribution/NOTICE.txt': {'bytes': 851, 'sha256': '5c2944ee27bd38f63ce6e33b0b85ead217c8e38f80e41e690926f69f49937002'}}, 'packaged_at': '2026-11-12T19:01:41.401518+00:00'}
STEP235_PORTABLE_MODEL_ARCHIVE_NAME = STEP235_PORTABLE_MODEL_BINDING["archive_file_name"]
STEP235_PORTABLE_MODEL_ARCHIVE_SHA256 = STEP235_PORTABLE_MODEL_BINDING["archive_sha256"]
STEP235_PORTABLE_MODEL_ARCHIVE_BYTES = STEP235_PORTABLE_MODEL_BINDING["archive_bytes"]


def _step235_portable_sha(content):
    import hashlib
    return hashlib.sha256(content).hexdigest()


def _step235_portable_path(value):
    from pathlib import Path
    path = Path(value)
    if (not path.is_absolute() or path.resolve(strict=False) != path
            or any(item.is_symlink() for item in (path, *path.parents))):
        raise ValueError("step235_portable_model_invalid:unsafe_path")
    return path


def inspect_step235_portable_model(archive_path):
    """Verify the complete archive and return bounded provenance, without writes."""
    import json
    import stat
    import zipfile
    from pathlib import PurePosixPath
    path = _step235_portable_path(archive_path)
    binding = STEP235_PORTABLE_MODEL_BINDING
    if not path.is_file() or path.stat().st_size != binding["archive_bytes"]:
        raise ValueError("step235_portable_model_invalid:archive_size")
    if _step235_portable_sha(path.read_bytes()) != binding["archive_sha256"]:
        raise ValueError("step235_portable_model_invalid:archive_sha256")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if (len(entries) != len(binding["members"]) or len({item.filename for item in entries}) != len(entries)
                or {item.filename for item in entries} != set(binding["members"])):
            raise ValueError("step235_portable_model_invalid:archive_inventory")
        for item in entries:
            pure = PurePosixPath(item.filename)
            expected = binding["members"][item.filename]
            file_mode = item.external_attr >> 16
            if (pure.is_absolute() or pure.as_posix() != item.filename or "\\" in item.filename or ":" in item.filename
                    or any(part in (".", "..") for part in pure.parts) or item.is_dir()
                    or item.flag_bits & 1 or stat.S_ISLNK(file_mode)
                    or (stat.S_IFMT(file_mode) not in (0, stat.S_IFREG))
                    or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or item.file_size != expected["bytes"]):
                raise ValueError("step235_portable_model_invalid:archive_member_metadata")
            with archive.open(item) as handle:
                content = handle.read(expected["bytes"] + 1)
                if len(content) != expected["bytes"] or handle.read(1) or _step235_portable_sha(content) != expected["sha256"]:
                    raise ValueError("step235_portable_model_invalid:archive_member_bytes")
        provenance = json.loads(archive.read("distribution/PROVENANCE.json"))
    if (provenance.get("schema_version") != "step235-portable-model-provenance-1"
            or provenance.get("repo_id") != binding["repo_id"] or provenance.get("revision") != binding["revision"]
            or provenance.get("acquisition_origin") != "assistant_workspace_previously_downloaded_official_immutable_revision"
            or provenance.get("publisher_fetch_on_user_machine_claimed") is not False
            or provenance.get("upstream_model_files_modified") is not False
            or provenance.get("corpus_or_study_text_included") is not False):
        raise ValueError("step235_portable_model_invalid:archive_provenance")
    return {"method": "verified_portable_archive_import", "acquisition_method": "verified_portable_archive_import",
        "repo_id": binding["repo_id"], "revision": binding["revision"],
        "archive_sha256": binding["archive_sha256"], "archive_bytes": binding["archive_bytes"],
        "archive_file_name": binding["archive_file_name"], "packaged_at": binding["packaged_at"],
        "original_acquisition_origin": provenance["acquisition_origin"],
        "original_transport_receipt_included": provenance["original_transport_receipt_included"],
        "publisher_requests_on_this_machine_for_model_acquisition": 0,
        "upstream_model_files_modified": False, "upstream_model_files_verified": 11,
        "license_declared": "apache-2.0", "license_text_in_archive": True,
        "distribution_notice_in_archive": True, "model_inference_verified_by_archive_import": False}


def verify_and_stage_step235_portable_model(archive_path, stage_dir):
    """Write only eleven verified files to an existing empty owned staging directory.

    Caller owns staging cleanup and immutable cache publication. This function
    never replaces an existing file or model-cache directory and never fetches
    a publisher page. Archive provenance is distinct from local model inference.
    """
    import os
    import zipfile
    path, staged = _step235_portable_path(archive_path), _step235_portable_path(stage_dir)
    if not staged.is_dir() or list(staged.iterdir()):
        raise ValueError("step235_portable_model_invalid:staging_must_be_empty_owned_directory")
    provenance = inspect_step235_portable_model(path)
    with zipfile.ZipFile(path) as archive:
        for name, pin in STEP235_PORTABLE_MODEL_BINDING["members"].items():
            if not name.startswith("model/"):
                continue
            relative = name.removeprefix("model/")
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if (target.resolve(strict=False) != target or not target.is_relative_to(staged)
                    or any(item.is_symlink() for item in (staged, *target.parents))):
                raise ValueError("step235_portable_model_invalid:staging_path_changed")
            with archive.open(name) as source, target.open("xb") as destination:
                remaining = pin["bytes"]
                import hashlib
                digest = hashlib.sha256()
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError("step235_portable_model_invalid:staged_member_truncated")
                    destination.write(block)
                    digest.update(block)
                    remaining -= len(block)
                if source.read(1) or digest.hexdigest() != pin["sha256"]:
                    raise ValueError("step235_portable_model_invalid:staged_member_changed")
                destination.flush()
                os.fsync(destination.fileno())
    if (staged.resolve(strict=False) != staged or staged.is_symlink()
            or any(item.is_symlink() for item in staged.rglob("*"))
            or _step235_portable_sha(path.read_bytes()) != STEP235_PORTABLE_MODEL_BINDING["archive_sha256"]
            or {p.relative_to(staged).as_posix() for p in staged.rglob("*") if p.is_file()}
                != {name.removeprefix("model/") for name in STEP235_PORTABLE_MODEL_BINDING["members"] if name.startswith("model/")}):
        raise ValueError("step235_portable_model_invalid:archive_or_staged_inventory_changed")
    return provenance


"""Bounded download diagnostics without returning exception text or private URLs."""


def summarize_step235_download_error(error, *, stage, file_key=None):
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


"""Fresh-process CPU checks for one pinned semantic model and authored text only."""

_STEP235_WORKER_REPO = "sentence-transformers/all-MiniLM-L6-v2"
_STEP235_WORKER_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
_STEP235_WORKER_STAGE = "request_parsing"
_STEP235_WORKER_FILES = {
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


def _step235_worker_packed(value):
    import json
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _step235_worker_sha(content):
    import hashlib
    return hashlib.sha256(content).hexdigest()


def _step235_worker_path(value, *, must_exist=False):
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


def _step235_worker_verify_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("invalid_model_manifest")
    if (manifest.get("repo_id") != _STEP235_WORKER_REPO or manifest.get("revision") != _STEP235_WORKER_REVISION
            or manifest.get("license_declared") != "apache-2.0" or type(manifest.get("files")) is not list):
        raise ValueError("unbound_model_identity")
    rows = manifest["files"]
    if (len(rows) != 11 or len({row.get("relative_path") for row in rows if isinstance(row, dict)}) != 11
            or {row.get("relative_path"): (row.get("bytes"), row.get("sha256")) for row in rows
                if isinstance(row, dict)} != _STEP235_WORKER_FILES):
        raise ValueError("unbound_model_payloads")
    return True


def _step235_worker_verify_cache(cache):
    """A changed, partial or unfamiliar existing cache is never repaired."""
    if not cache.exists():
        return None
    if not cache.is_dir() or cache.is_symlink() or cache.resolve() != cache:
        raise ValueError("invalid_model_cache")
    items = list(cache.rglob("*"))
    if (any(item.is_symlink() or (not item.is_file() and not item.is_dir()) for item in items)
            or {item.relative_to(cache).as_posix() for item in items if item.is_file()} != set(_STEP235_WORKER_FILES)
            or {item.relative_to(cache).as_posix() for item in items if item.is_dir()} != {"1_Pooling"}):
        raise ValueError("partial_or_unfamiliar_model_cache_preserved")
    hashes = {}
    for name, (size, digest) in _STEP235_WORKER_FILES.items():
        content = (cache / name).read_bytes()
        if len(content) != size or _step235_worker_sha(content) != digest:
            raise ValueError("changed_model_cache_preserved")
        hashes[name] = digest
    return hashes


def _step235_worker_publish_cache(staged, target):
    """Atomically rename a complete directory without replacing another entry."""
    import os
    import sys
    if os.name == "nt":
        # Windows os.rename fails if its destination already exists.
        os.rename(staged, target)
    elif sys.platform.startswith("linux"):
        import ctypes
        import errno
        library = ctypes.CDLL(None, use_errno=True)
        rename = getattr(library, "renameat2", None)
        if rename is None:
            raise RuntimeError("exclusive_directory_publication_unavailable")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(staged), -100, os.fsencode(target), 1) != 0:
            code = ctypes.get_errno()
            if code == errno.EEXIST:
                raise FileExistsError("model_cache_concurrent_entry_preserved")
            raise OSError(code, "exclusive_directory_publication_failed")
    else:
        raise RuntimeError("exclusive_directory_publication_unavailable")


def _step235_worker_acquire(cache, mode, portable_archive=None):
    import os
    import shutil
    import tempfile
    global _STEP235_WORKER_STAGE
    _STEP235_WORKER_STAGE = "existing_model_cache_integrity"
    hashes = _step235_worker_verify_cache(cache)
    if hashes is not None:
        return {"cache_reused": True, "download_performed": False, "portable_archive_imported": False,
            "model_acquisition": {"method": "preexisting_complete_sha256_verified_model_cache"},
            "model_file_hashes": hashes}
    if mode != "download_and_verify":
        raise ValueError("model_cache_absent_and_download_disabled")
    cache.parent.mkdir(parents=True, exist_ok=True)
    workspace = tempfile.mkdtemp(prefix=".step235-model-stage-", dir=cache.parent)
    from pathlib import Path
    workspace = Path(workspace)
    try:
        staged = workspace / "complete_model"
        staged.mkdir()
        if portable_archive is not None:
            _STEP235_WORKER_STAGE = "verified_portable_model_archive_import"
            importer = globals().get("verify_and_stage_step235_portable_model")
            if importer is None:
                from step235_portable_model import verify_and_stage_step235_portable_model as importer
            print("Verifying the local pinned-model archive; no model download request...", flush=True)
            acquisition = importer(portable_archive, staged)
        else:
            _STEP235_WORKER_STAGE = "pinned_public_model_download"
            from huggingface_hub import snapshot_download
            print("Downloading the pinned public model files; no study text is sent...", flush=True)
            downloaded = Path(snapshot_download(repo_id=_STEP235_WORKER_REPO, revision=_STEP235_WORKER_REVISION,
                allow_patterns=list(_STEP235_WORKER_FILES), token=False, local_files_only=False,
                cache_dir=str(workspace / "download_cache"), max_workers=4))
            for name, (size, digest) in _STEP235_WORKER_FILES.items():
                content = (downloaded / name).read_bytes()
                if len(content) != size or _step235_worker_sha(content) != digest:
                    raise ValueError("downloaded_model_bytes_do_not_match_pinned_source")
                destination = staged / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            acquisition = {"method": "official_hugging_face_immutable_revision_https_download",
                "repo_id": _STEP235_WORKER_REPO, "revision": _STEP235_WORKER_REVISION}
        _step235_worker_verify_cache(staged)
        _STEP235_WORKER_STAGE = "exclusive_model_cache_publication"
        _step235_worker_publish_cache(staged, cache)
        return {"cache_reused": False, "download_performed": portable_archive is None,
            "portable_archive_imported": portable_archive is not None, "model_acquisition": acquisition,
            "model_file_hashes": _step235_worker_verify_cache(cache)}
    finally:
        shutil.rmtree(workspace)


def verify_step23_semantic_worker(request):
    """Check the frozen encoder using authored diagnostics, never corpus records."""
    import importlib.metadata as metadata
    import json
    import os
    import platform
    import sys
    import socket
    import urllib.request

    global _STEP235_WORKER_STAGE
    _STEP235_WORKER_STAGE = "request_and_pinned_source_manifest"
    required = {"mode", "model_cache_root", "model_source_manifest", "result_path", "embeddings_path"}
    if (not isinstance(request, dict) or not required.issubset(request)
            or set(request) - required - {"portable_model_archive"}
            or request.get("mode") not in {"verify", "download_and_verify"}):
        raise ValueError("invalid_worker_request")
    _step235_worker_verify_manifest(request["model_source_manifest"])
    cache = _step235_worker_path(request["model_cache_root"])
    vectors_path = _step235_worker_path(request["embeddings_path"])
    result_path = _step235_worker_path(request["result_path"])
    if (vectors_path == result_path or vectors_path.exists() or result_path.exists()
            or not vectors_path.parent.is_dir() or not result_path.parent.is_dir()
            or vectors_path.is_relative_to(cache) or result_path.is_relative_to(cache)):
        raise ValueError("invalid_or_existing_worker_output")
    archive = request.get("portable_model_archive")
    if archive is not None:
        archive = _step235_worker_path(archive, must_exist=True)
    acquired = _step235_worker_acquire(cache, request["mode"], archive)
    _STEP235_WORKER_STAGE = "offline_cpu_model_loading"
    print("Checking the local frozen model on CPU with authored diagnostics...", flush=True)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    def no_network(*args, **kwargs):
        raise RuntimeError("network_disabled_during_local_model_verification")

    socket.create_connection = no_network
    socket.socket.connect = no_network
    urllib.request.urlopen = no_network
    urllib.request.OpenerDirector.open = no_network
    import numpy as np
    import torch
    from safetensors.torch import load_file
    from sentence_transformers import SentenceTransformer
    helper_names = ("STEP23_AUTHORED_RUNTIME_TEXTS", "validate_step23_embedding_outputs", "validate_step23_runtime_token_counts")
    if not all(name in globals() for name in helper_names):
        from step23_embedding_validation import STEP23_AUTHORED_RUNTIME_TEXTS as authored_texts
        from step23_embedding_validation import validate_step23_embedding_outputs as validate_vectors
        from step23_embedding_validation import validate_step23_runtime_token_counts as validate_counts
    else:
        authored_texts = globals()["STEP23_AUTHORED_RUNTIME_TEXTS"]
        validate_vectors = globals()["validate_step23_embedding_outputs"]
        validate_counts = globals()["validate_step23_runtime_token_counts"]
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    checks = []

    def check(name, condition, observed=True):
        if not bool(condition):
            raise ValueError("semantic_worker_check_failed")
        checks.append({"check": name, "status": "pass", "observed": str(observed)})

    model = SentenceTransformer(str(cache), device="cpu", local_files_only=True,
        trust_remote_code=False, model_kwargs={"use_safetensors": True, "dtype": torch.float32})
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    tokenizer, backbone = model.tokenizer, model[0].auto_model
    raw_config = json.loads((cache / "tokenizer_config.json").read_bytes())
    st_config = json.loads((cache / "sentence_bert_config.json").read_bytes())
    pooling_config = json.loads((cache / "1_Pooling/config.json").read_bytes())
    modules_config = json.loads((cache / "modules.json").read_bytes())
    configured = int(model.max_seq_length)
    loaded_limit = int(tokenizer.model_max_length)
    positions = int(backbone.config.max_position_embeddings)
    dimension = int(model.get_sentence_embedding_dimension())
    special = int(tokenizer.num_special_tokens_to_add(pair=False))
    effective = min(200, configured, loaded_limit, positions)
    _STEP235_WORKER_STAGE = "model_limits_and_checkpoint_coverage"
    check("actual_model_limits_dimension_and_special_tokens_are_recorded",
        configured == st_config["max_seq_length"] == 256 and loaded_limit == 256
        and raw_config["model_max_length"] == positions == 512 and dimension == 384 and special == 2)
    check("published_pooling_and_normalization_match_the_loaded_recipe",
        pooling_config == {"word_embedding_dimension": 384, "pooling_mode_cls_token": False,
            "pooling_mode_mean_tokens": True, "pooling_mode_max_tokens": False,
            "pooling_mode_mean_sqrt_len_tokens": False}
        and [row["type"] for row in modules_config] == ["sentence_transformers.models.Transformer",
            "sentence_transformers.models.Pooling", "sentence_transformers.models.Normalize"])
    check("reference_model_is_evaluation_only_cpu_float32_with_frozen_parameters",
        all(not module.training for module in model.modules())
        and all(not parameter.requires_grad and parameter.grad is None and parameter.device.type == "cpu"
            and parameter.dtype == torch.float32 for parameter in model.parameters()))
    checkpoint = load_file(str(cache / "model.safetensors"), device="cpu")
    state = backbone.state_dict()
    extra = set(checkpoint) - set(state)
    check("all_state_tensors_exactly_match_safetensors_without_missing_or_random_weights",
        set(state).issubset(checkpoint) and extra == {"embeddings.position_ids"}
        and all(torch.equal(state[key], checkpoint[key]) for key in state)
        and torch.equal(checkpoint["embeddings.position_ids"], backbone.embeddings.position_ids),
        f"{len(state)} state tensors and one explicitly matched nonpersistent position buffer")
    del checkpoint, state

    def state_sha():
        import hashlib
        digest = hashlib.sha256()
        for key, tensor in sorted(model.state_dict().items()):
            value = tensor.detach().cpu().contiguous()
            digest.update(_step235_worker_packed({"key": key, "dtype": str(value.dtype), "shape": list(value.shape)}))
            digest.update(value.numpy().tobytes(order="C"))
        return digest.hexdigest()

    before_state = state_sha()
    counters = {"embedding_request_count": 0, "model_forward_batches": 0, "tokenizer_request_calls": 0}
    original_tokenize = model.tokenize

    def counted_model_tokenize(texts, **kwargs):
        counters["tokenizer_request_calls"] += 1
        return original_tokenize(texts, **kwargs)

    model.tokenize = counted_model_tokenize
    def count_forward(module, args):
        counters["model_forward_batches"] += 1
    hook = backbone.register_forward_pre_hook(count_forward)

    def counted_tokenize(texts, **kwargs):
        counters["tokenizer_request_calls"] += 1
        return tokenizer(texts, **kwargs)

    def checked_encode(texts, batch_size):
        if not isinstance(texts, (list, tuple)) or not texts or any(type(text) is not str or not text.strip() for text in texts):
            raise ValueError("invalid_authored_embedding_request")
        count_rows = counted_tokenize(list(texts), add_special_tokens=True, truncation=False, padding=False)["input_ids"]
        if any(len(row) > effective for row in count_rows):
            raise ValueError("encoded_input_exceeds_project_limit")
        counters["embedding_request_count"] += 1
        return model.encode(list(texts), batch_size=batch_size, precision="float32", normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False)

    texts = list(authored_texts)
    _STEP235_WORKER_STAGE = "authored_embedding_and_tokenizer_diagnostics"
    token_rows = counted_tokenize(texts, add_special_tokens=True, truncation=False, padding=False)["input_ids"]
    token_counts = [len(row) for row in token_rows]
    checks.extend(validate_counts(texts, token_counts, configured_max_sequence_length=configured,
        tokenizer_model_max_length=loaded_limit, model_position_limit=positions, special_tokens_count=special,
        truncation_used=False))
    full = checked_encode(texts, 6)
    repeated = checked_encode(texts, 6)
    reversed_vectors = checked_encode(texts[::-1], 6)
    batched = np.concatenate([checked_encode(texts[start:start + 2], 2) for start in range(0, len(texts), 2)])
    checks.extend(validate_vectors(texts, full, repeated, reversed_vectors, batched, dimension=dimension,
        rtol=1e-5, atol=1e-6))
    boundaries = []
    for encoded_count in (199, 200, 201):
        text = "basketball " * (encoded_count - special)
        actual = len(counted_tokenize(text, add_special_tokens=True, truncation=False)["input_ids"])
        before_calls = counters["model_forward_batches"]
        rejected = False
        try:
            checked_encode([text], 1)
        except ValueError:
            rejected = True
        boundaries.append({"encoded_tokens_including_specials": actual, "rejected_before_model_forward": rejected,
            "model_forward_batches": counters["model_forward_batches"] - before_calls})
        check("project_token_limit_boundary_" + str(encoded_count), actual == encoded_count
            and rejected == (encoded_count > effective)
            and counters["model_forward_batches"] - before_calls == (0 if rejected else 1), actual)
    padded = counted_tokenize(texts[:2], padding="max_length", max_length=200, truncation=False,
        add_special_tokens=True, return_tensors="pt")
    with torch.inference_mode():
        output = backbone(**padded).last_hidden_state
        attention = padded["attention_mask"].unsqueeze(-1).to(output.dtype)
        pooled = (output * attention).sum(1) / attention.sum(1).clamp(min=1e-9)
        padded_vectors = torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().numpy()
    check("explicit_masked_mean_excludes_extra_padding_and_matches_encoder",
        padded["input_ids"].shape == (2, 200) and bool((padded["attention_mask"] == 0).any())
        and np.allclose(padded_vectors, full[:2], rtol=1e-5, atol=1e-6))
    hook.remove()
    after_state = state_sha()
    check("frozen_parameters_and_buffers_are_unchanged_after_all_forwards",
        before_state == after_state and all(not parameter.requires_grad and parameter.grad is None
            for parameter in model.parameters()))
    hashes_after = _step235_worker_verify_cache(cache)
    _STEP235_WORKER_STAGE = "final_model_state_and_file_integrity"
    check("all_eleven_local_model_files_are_unchanged", hashes_after == acquired["model_file_hashes"])
    versions = {}
    dependencies = ("sentence-transformers", "transformers", "huggingface-hub", "tokenizers", "safetensors",
        "torch", "numpy", "scipy", "scikit-learn", "packaging", "pyyaml", "filelock", "fsspec", "regex",
        "requests", "tqdm", "typing-extensions", "hf-xet", "urllib3", "certifi", "charset-normalizer",
        "idna", "pillow", "sympy", "networkx", "jinja2", "markupsafe")
    for name in dependencies:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    environment = {"python_version": platform.python_version(), "python_full_version": sys.version,
        "platform_system": platform.system(), "platform_machine": platform.machine(), "versions": versions}
    model_metadata = {"repo_id": _STEP235_WORKER_REPO, "revision": _STEP235_WORKER_REVISION,
        "license_declared": "apache-2.0", "license_basis": "pinned_README_front_matter",
        "device": "cpu", "dtype": "float32", "dimension": dimension,
        "sentence_transformer_max_seq_length": configured, "raw_tokenizer_declared_model_max_length": raw_config["model_max_length"],
        "loaded_tokenizer_model_max_length": loaded_limit, "model_max_position_embeddings": positions,
        "special_tokens_per_single_sequence": special, "effective_project_encoded_limit": effective,
        "pooling": "attention_masked_mean_then_l2_normalization", "normalized_embeddings": True,
        "trust_remote_code": False, "safetensors_only": True, "all_checkpoint_tensors_accounted_for": True,
        "checkpoint_state_tensor_count": 103, "matched_nonpersistent_buffer_keys": ["embeddings.position_ids"],
        "evaluation_mode": True, "parameters_frozen": True, "deterministic_algorithms_enabled": True,
        "cpu_threads": 1, "tokenizer_fast": bool(tokenizer.is_fast), "diagnostic_untruncated_token_counts": token_counts,
        "boundary_fixtures": boundaries, "native_encoder_truncation_is_not_used_to_satisfy_project_budget": True}
    result = {"status": "verified_semantic_runtime", "runtime_environment": environment,
        "model_metadata": model_metadata, "checks": checks, **counters,
        "authored_embedding_rows_saved": 6, "authored_embedding_shape": list(full.shape),
        "model_state_sha256_before": before_state, "model_state_sha256_after": after_state,
        "model_file_hashes": hashes_after, "corpus_texts_used": 0, "study_texts_used": 0,
        "model_training_runs": 0, "retrieval_requests": 0, "gpu_runtime_verified": False,
        "model_network_requests_during_verification": 0,
        "download_performed": acquired["download_performed"], "cache_reused": acquired["cache_reused"],
        "portable_archive_imported": acquired["portable_archive_imported"],
        "model_acquisition": acquired["model_acquisition"]}
    _STEP235_WORKER_STAGE = "authored_vector_and_result_publication"
    with vectors_path.open("xb") as handle:
        np.save(handle, full, allow_pickle=False)
        handle.flush()
        os.fsync(handle.fileno())
    result["authored_embeddings_file_sha256"] = _step235_worker_sha(vectors_path.read_bytes())
    with result_path.open("xb") as handle:
        handle.write(_step235_worker_packed(result))
        handle.flush()
        os.fsync(handle.fileno())
    return result


def _step235_worker_main():
    import json
    import sys
    request, stage = None, "request_parsing"
    try:
        request = json.load(sys.stdin)
        stage = "model_cache_and_local_cpu_verification"
        verify_step23_semantic_worker(request)
        print("Pinned semantic runtime checks completed; no corpus text was processed.", flush=True)
        return 0
    except Exception as error:
        summarizer = globals().get("summarize_step235_download_error")
        if summarizer is None:
            from step235_download_diagnostics import summarize_step235_download_error as summarizer
        result = summarizer(error, stage=globals().get("_STEP235_WORKER_STAGE", stage))
        if isinstance(error, ValueError) and str(error).startswith("step235_portable_model_invalid:"):
            import re
            code = str(error).split(":", 1)[1]
            if re.fullmatch(r"[a-z_]{1,80}", code):
                result["validation_code"] = code
        try:
            path = _step235_worker_path(request["result_path"])
            with path.open("xb") as handle:
                handle.write(_step235_worker_packed(result))
        except Exception:
            pass
        print(json.dumps(result, sort_keys=True), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(_step235_worker_main())
