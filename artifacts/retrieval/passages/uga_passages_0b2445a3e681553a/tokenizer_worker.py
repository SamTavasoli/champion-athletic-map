STEP239_PINNED_MODEL_FILES = {'README.md': (10502, 'dcd602d2fd35c203a247304a06fec6654a12f7941b739f9221a064fe8dc3b7f0'), 'config.json': (612, '953f9c0d463486b10a6871cc2fd59f223b2c70184f49815e7efbcab5d8908b41'), 'config_sentence_transformers.json': (116, '061ca9d39661d6c6d6de5ba27f79a1cd5770ea247f8d46412a68a498dc5ac9f3'), 'sentence_bert_config.json': (53, 'fc1993fde0a95c24ec6c022539d41cf6e2f7c9721e5415d6fb6897472a9cd4b7'), 'special_tokens_map.json': (112, '303df45a03609e4ead04bc3dc1536d0ab19b5358db685b6f3da123d05ec200e3'), 'tokenizer_config.json': (350, 'acb92769e8195aabd29b7b2137a9e6d6e25c476a4f15aa4355c233426c61576b'), 'tokenizer.json': (466247, 'be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037'), 'vocab.txt': (231508, '07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3'), 'modules.json': (349, '84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf'), '1_Pooling/config.json': (190, '4be450dde3b0273bb9787637cfbd28fe04a7ba6ab9d36ac48e92b11e350ffc23'), 'model.safetensors': (90868376, '53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db')}

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

"""Measure six bound UGA reference cores and complete delivery texts offline."""


def verify_step239_uga_tokenization(request):
    import hashlib
    import importlib.metadata as metadata
    import json
    import os
    import platform
    import re
    import socket
    import urllib.request
    from pathlib import Path

    global _STEP239_TOKENIZER_STAGE
    _STEP239_TOKENIZER_STAGE = "request_and_adopted_runtime_binding"
    required = {"semantic_runtime_adoption_id", "uga_reference_review_id", "runtime_environment",
        "model_source_manifest", "model_metadata", "model_cache_root", "reference_units", "texts", "result_path"}
    if not isinstance(request, dict) or set(request) != required:
        raise ValueError("invalid_uga_tokenizer_request")
    model_source, adopted = request["model_source_manifest"], request["model_metadata"]
    if (model_source["repo_id"] != "sentence-transformers/all-MiniLM-L6-v2"
            or model_source["revision"] != "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
            or len(model_source["files"]) != 11
            or {row["relative_path"]: (row["bytes"], row["sha256"]) for row in model_source["files"]}
                != STEP239_PINNED_MODEL_FILES
            or re.fullmatch(r"semantic-runtime-adoption:[0-9a-f]{64}", str(request["semantic_runtime_adoption_id"])) is None
            or re.fullmatch(r"uga-reference-review:[0-9a-f]{64}", str(request["uga_reference_review_id"])) is None):
        raise ValueError("unbound_uga_tokenizer_model_or_review")
    units, texts = request["reference_units"], request["texts"]
    if (not isinstance(units, list) or len(units) != 6
            or any(not isinstance(row, dict) or set(row) != {"reference_unit_id", "reference_unit_record_sha256", "source_version_record_sha256"}
                or re.fullmatch(r"uga-reference-unit:[0-9a-f]{64}", str(row.get("reference_unit_id"))) is None
                or any(re.fullmatch(r"[0-9a-f]{64}", str(row.get(key))) is None
                    for key in ("reference_unit_record_sha256", "source_version_record_sha256")) for row in units)
            or len({row["reference_unit_id"] for row in units}) != 6):
        raise ValueError("unbound_uga_reference_unit_population")
    unit_ids = [row["reference_unit_id"] for row in units]
    expected_population = [(unit_id, role) for role in ("reference_core", "complete_required_delivery") for unit_id in unit_ids]
    if (not isinstance(texts, list) or len(texts) != 12
            or [(row.get("reference_unit_id"), row.get("text_role")) for row in texts] != expected_population
            or any(set(row) != {"reference_unit_id", "text_role", "text", "text_sha256"}
                or type(row.get("text")) is not str or not row["text"].strip()
                or hashlib.sha256(row["text"].encode("utf-8")).hexdigest() != row.get("text_sha256") for row in texts)):
        raise ValueError("unbound_uga_tokenizer_text_population")
    cache, result_path = Path(request["model_cache_root"]), Path(request["result_path"])
    for path in (cache, result_path):
        if (not path.is_absolute() or path.resolve() != path
                or any(parent.is_symlink() for parent in (path, *path.parents))):
            raise ValueError("unsafe_uga_tokenizer_path")
    if result_path.exists() or not result_path.parent.is_dir() or result_path.is_relative_to(cache):
        raise ValueError("existing_or_unproven_uga_tokenizer_output")
    globals()["_STEP239_SAFE_RESULT_PATH"] = str(result_path)

    def model_hashes():
        entries = list(cache.rglob("*"))
        if (not cache.is_dir() or any(path.is_symlink() or (not path.is_file() and not path.is_dir()) for path in entries)
                or {path.relative_to(cache).as_posix() for path in entries if path.is_file()} != set(STEP239_PINNED_MODEL_FILES)
                or {path.relative_to(cache).as_posix() for path in entries if path.is_dir()} != {"1_Pooling"}):
            raise ValueError("changed_uga_tokenizer_model_cache")
        result = {}
        for name, (size, expected) in STEP239_PINNED_MODEL_FILES.items():
            path = cache / name
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if path.stat().st_size != size or digest != expected:
                raise ValueError("changed_uga_tokenizer_payload")
            result[name] = digest
        return result

    hashes_before = model_hashes()
    checks = []
    def check(name, condition, observed=True):
        if not bool(condition):
            raise ValueError("uga_tokenizer_condition_failed:" + name)
        checks.append({"check": name, "status": "pass", "observed": str(observed)})

    _STEP239_TOKENIZER_STAGE = "recorded_tokenizer_runtime_versions"
    versions = {name: metadata.version(name) for name in
        ("sentence-transformers", "transformers", "tokenizers", "huggingface-hub", "safetensors", "torch")}
    check("tokenizer_runtime_versions_match_the_adopted_environment", all(
        request["runtime_environment"]["versions"].get(name) == version for name, version in versions.items())
        and platform.python_version() == request["runtime_environment"]["python_version"])

    def forbidden(*args, **kwargs):
        raise RuntimeError("model_weights_forwards_or_network_forbidden_during_uga_tokenization")

    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
        TOKENIZERS_PARALLELISM="false", USE_TF="0", USE_FLAX="0")
    socket.create_connection = forbidden
    socket.socket.connect = forbidden
    urllib.request.urlopen = forbidden
    urllib.request.OpenerDirector.open = forbidden
    import torch
    import safetensors
    import safetensors.torch as safe_torch
    torch.load = forbidden
    torch.nn.Embedding.__init__ = forbidden
    torch.nn.Module.__call__ = forbidden
    safetensors.safe_open = forbidden
    safe_torch.load_file = forbidden
    safe_torch.load_model = forbidden
    _STEP239_TOKENIZER_STAGE = "offline_pinned_tokenizer_loading"
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(cache), local_files_only=True,
        trust_remote_code=False, use_fast=True, model_max_length=adopted["loaded_tokenizer_model_max_length"])
    raw = json.loads((cache / "tokenizer_config.json").read_bytes())
    wrapper = json.loads((cache / "sentence_bert_config.json").read_bytes())
    model_config = json.loads((cache / "config.json").read_bytes())
    special = int(tokenizer.num_special_tokens_to_add(pair=False))
    check("loaded_tokenizer_and_all_limit_bases_match_prior_adoption", tokenizer.is_fast
        and tokenizer.model_max_length == adopted["loaded_tokenizer_model_max_length"] == 256
        and raw["model_max_length"] == adopted["raw_tokenizer_declared_model_max_length"] == 512
        and wrapper["max_seq_length"] == adopted["sentence_transformer_max_seq_length"] == 256
        and model_config["max_position_embeddings"] == adopted["model_max_position_embeddings"] == 512
        and adopted["effective_project_encoded_limit"] == 200 and special == adopted["special_tokens_per_single_sequence"] == 2)
    check("bert_vocabulary_and_special_tokens_are_explicit", int(tokenizer.vocab_size) == 30522
        and tokenizer.cls_token_id == 101 and tokenizer.sep_token_id == 102)
    _STEP239_TOKENIZER_STAGE = "full_uga_reference_and_delivery_token_counts"
    result = tokenizer([row["text"] for row in texts], add_special_tokens=True,
        truncation=False, padding=False, return_attention_mask=True, return_token_type_ids=False)
    rows = []
    unit_map = {row["reference_unit_id"]: row for row in units}
    for index, (item, ids, attention) in enumerate(zip(texts, result["input_ids"], result["attention_mask"]), 1):
        check("untruncated_unpadded_ids_and_masks_are_valid:" + str(index),
            len(ids) == len(attention) and len(ids) >= special
            and ids[0] == tokenizer.cls_token_id and ids[-1] == tokenizer.sep_token_id
            and all(type(value) is int and 0 <= value < tokenizer.vocab_size for value in ids)
            and all(value == 1 for value in attention), len(ids))
        ids_bytes = (json.dumps(ids, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
        rows.append({"reference_unit_id": item["reference_unit_id"], **{key: unit_map[item["reference_unit_id"]][key]
                for key in ("reference_unit_record_sha256", "source_version_record_sha256")},
            "text_role": item["text_role"], "text_sha256": item["text_sha256"],
            "text_utf8_bytes": len(item["text"].encode("utf-8")),
            "encoded_tokens_including_specials": len(ids), "token_id_count": len(ids),
            "encoded_token_ids": ids, "token_ids_sha256": hashlib.sha256(ids_bytes).hexdigest(),
            "unknown_token_count": ids.count(tokenizer.unk_token_id),
            "embedding_core_cap_applies": item["text_role"] == "reference_core",
            "core_within_project_limit": len(ids) <= 200 if item["text_role"] == "reference_core" else None})
    check("token_counts_cover_exactly_twelve_ordered_bound_uga_texts", len(rows) == 12
        and [(row["reference_unit_id"], row["text_role"]) for row in rows] == expected_population)
    _STEP239_TOKENIZER_STAGE = "final_local_payload_integrity"
    check("all_eleven_model_files_are_unchanged_after_tokenization", model_hashes() == hashes_before)
    measurements = {"schema_version": "step23-uga-reference-tokenization-measurements-1",
        "semantic_runtime_adoption_id": request["semantic_runtime_adoption_id"],
        "uga_reference_review_id": request["uga_reference_review_id"],
        "model_repo_id": model_source["repo_id"], "model_revision": model_source["revision"],
        "reference_units": units,
        "add_special_tokens": True, "truncation_used": False, "padding_used": False,
        "project_encoded_limit": 200, "special_tokens_per_single_sequence": special,
        "raw_tokenizer_declared_limit": raw["model_max_length"],
        "loaded_tokenizer_limit": int(tokenizer.model_max_length), "model_wrapper_limit": wrapper["max_seq_length"],
        "model_position_limit": model_config["max_position_embeddings"],
        "tokenizer_is_fast": bool(tokenizer.is_fast), "tokenizer_class": type(tokenizer).__name__,
        "vocab_size": int(tokenizer.vocab_size), "cls_token_id": int(tokenizer.cls_token_id), "sep_token_id": int(tokenizer.sep_token_id),
        "tokenizer_loads": 1, "tokenizer_requests": 1, "reference_units_measured": 6,
        "reference_texts_tokenized": 12, "reference_core_texts_tokenized": 6, "complete_delivery_texts_tokenized": 6,
        "weights_loaded": 0, "model_forwards": 0, "corpus_embeddings": 0, "network_requests": 0,
        "classifier_texts_processed": 0, "generation_model_token_budget_assessed": False,
        "full_delivery_texts_are_not_embedding_inputs": True,
        "oversized_cores_are_measured_without_truncation_or_automatic_admission": True,
        "texts": rows}
    report = {"status": "verified_uga_reference_tokenization", "measurements": measurements,
        "checks": checks, "model_file_hashes": hashes_before}
    _STEP239_TOKENIZER_STAGE = "tokenizer_result_publication"
    with result_path.open("xb") as handle:
        handle.write((json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8"))
        handle.flush(); os.fsync(handle.fileno())
    return report


def _step239_tokenizer_main():
    import json
    request = None
    try:
        import sys
        request = json.load(sys.stdin)
        verify_step239_uga_tokenization(request)
        return 0
    except Exception as error:
        diagnostic = summarize_step235_download_error(error,
            stage=globals().get("_STEP239_TOKENIZER_STAGE", "tokenizer_request_parsing"))
        try:
            from pathlib import Path
            path = Path(globals()["_STEP239_SAFE_RESULT_PATH"])
            if path.is_absolute() and path.parent.is_dir() and not path.exists() and not path.is_symlink():
                with path.open("xb") as handle:
                    handle.write((json.dumps(diagnostic, sort_keys=True) + "\n").encode("utf-8"))
        except Exception:
            pass
        print(json.dumps(diagnostic, sort_keys=True), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(_step239_tokenizer_main())
