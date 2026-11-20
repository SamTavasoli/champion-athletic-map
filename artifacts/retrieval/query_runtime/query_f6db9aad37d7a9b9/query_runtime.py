"""Pinned query encoding and explicit lexical/semantic ranking; no route selection."""


def _step2315_qpack(value):
    import json
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n").encode("utf-8")


def _step2315_qsha(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()


def _step2315_qdecode(value):
    import json
    def unique(pairs):
        result={}
        for key,item in pairs:
            if key in result:raise ValueError("duplicate_query_runtime_json_key")
            result[key]=item
        return result
    def finite(value):raise ValueError("nonfinite_query_runtime_json")
    return json.loads(value.decode("utf-8"),object_pairs_hook=unique,parse_constant=finite)


def _step2315_qpath(value, *, exists=True, directory=False):
    from pathlib import Path
    path=Path(value)
    if (not path.is_absolute() or path.resolve()!=path or any(p.is_symlink() for p in (path,*path.parents))
            or (exists and not (path.is_dir() if directory else path.is_file()))):raise ValueError("unsafe_query_runtime_path")
    return path


def _step2315_qrelative(root,name):
    from pathlib import PurePosixPath
    if type(name) is not str or not name or "\\" in name or ":" in name:raise ValueError("unsafe_query_runtime_relative_path")
    parsed=PurePosixPath(name)
    if parsed.is_absolute() or parsed.as_posix()!=name or any(p in (".","..") for p in parsed.parts):raise ValueError("unsafe_query_runtime_relative_path")
    return _step2315_qpath(root/name)


def make_query_records(texts):
    """Bind caller text byte-for-byte; only blank/nontext/invalid populations are rejected."""
    if type(texts) is not list or not 1<=len(texts)<=60 or any(type(t) is not str or not t.strip() for t in texts):
        raise RuntimeError("step23_query_runtime_failed:query_population:ValueError")
    try:
        return [{"query_id":"retrieval-query:"+_step2315_qsha(_step2315_qpack({"ordinal":i,"text":text})),
            "text":text,"text_sha256":_step2315_qsha(text.encode("utf-8"))} for i,text in enumerate(texts,1)]
    except Exception as error:
        raise RuntimeError("step23_query_runtime_failed:query_population:"+type(error).__name__) from None


def _step2315_qrecords(records):
    if type(records) is not list or any(type(r) is not dict or set(r)!={"query_id","text","text_sha256"} for r in records):
        raise ValueError("invalid_typed_query_records")
    if records!=make_query_records([r["text"] for r in records]):raise ValueError("query_ids_or_raw_text_bindings_changed")
    return records


def _step2315_qindex_state(index):
    """Fingerprint learned state, all CSR/dense values and complete public metadata."""
    import hashlib
    import json
    import numpy as np
    vectorizer=index["vectorizer"];matrix=index["lexical_matrix"]
    params=vectorizer.get_params(deep=False)
    descriptor={"class":type(vectorizer).__module__+"."+type(vectorizer).__name__,"params":params,
        "vocabulary":vectorizer.vocabulary_,"features":vectorizer.get_feature_names_out().tolist(),"metadata":index["metadata"],
        "manifest":index["manifest"],"matrix_shape":list(matrix.shape),"fixed_vocabulary":getattr(vectorizer,"fixed_vocabulary_",None)}
    digest=hashlib.sha256((json.dumps(descriptor,sort_keys=True,ensure_ascii=False,allow_nan=False,default=repr)+"\n").encode("utf-8"))
    for array in (vectorizer.idf_,matrix.data,matrix.indices,matrix.indptr,index["semantic_embeddings"]):
        array=np.asarray(array);digest.update(_step2315_qpack({"dtype":str(array.dtype),"shape":list(array.shape)}));digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def create_query_runtime(project_root,config,worker_path,model_cache_root=None):
    """Load the manifest-bound expanded index; config must already be trusted by caller."""
    import copy
    import re
    from pathlib import Path
    stage="trusted_configuration"
    try:
        root=_step2315_qpath(project_root,directory=True);config=copy.deepcopy(config)
        fields={"schema_version","expanded_index_manifest_relative_path","expanded_index_manifest_sha256","expanded_retrieval_id","corpus_id",
            "retrieval_source_sha256","query_worker_sha256","semantic_runtime_adoption_id","runtime_environment","model_source_manifest","model_metadata","query_encoded_limit","max_query_rows"}
        if (type(config) is not dict or not fields.issubset(config) or config["schema_version"]!="step23-query-runtime-config-1"
                or config["query_encoded_limit"]!=200 or config["max_query_rows"]!=60
                or any(re.fullmatch(r"[0-9a-f]{64}",str(config[k])) is None for k in ("expanded_index_manifest_sha256","retrieval_source_sha256","query_worker_sha256"))):
            raise ValueError("invalid_trusted_query_runtime_configuration")
        stage="manifest_and_source_hashes_before_code_loading"
        manifest_path=_step2315_qrelative(root,config["expanded_index_manifest_relative_path"]);folder=manifest_path.parent
        manifest_bytes=manifest_path.read_bytes();manifest=_step2315_qdecode(manifest_bytes)
        source=_step2315_qpath(folder/"retrieval.py");worker=_step2315_qpath(worker_path);source_bytes=source.read_bytes()
        if (_step2315_qsha(manifest_bytes)!=config["expanded_index_manifest_sha256"] or _step2315_qpack(manifest)!=manifest_bytes
                or manifest["schema_version"]!="step23-expanded-retrieval-manifest-1" or manifest["expanded_retrieval_id"]!=config["expanded_retrieval_id"]
                or manifest["corpus_id"]!=config["corpus_id"] or manifest["semantic_runtime_adoption_id"]!=config["semantic_runtime_adoption_id"]
                or _step2315_qsha(source_bytes)!=config["retrieval_source_sha256"] or config["retrieval_source_sha256"]!=manifest["payload_hashes"]["retrieval.py"]
                or _step2315_qsha(worker.read_bytes())!=config["query_worker_sha256"]):raise ValueError("untrusted_query_runtime_source_or_manifest")
        stage="verified_expanded_index_loading"
        api={"__name__":"champion_verified_query_retrieval"};exec(compile(source_bytes,str(source),"exec"),api)
        index=api["load_expanded_indexes"](folder,config["expanded_index_manifest_sha256"])
        cache=Path(model_cache_root) if model_cache_root is not None else Path.home()/".cache"/"champion_athletic_map"/"retrieval_models"/config["model_source_manifest"]["revision"]
        cache=_step2315_qpath(cache,directory=True)
        files={p.name:_step2315_qsha(p.read_bytes()) for p in folder.iterdir()};frozen=_step2315_qindex_state(index)
        frozen_config=_step2315_qsha(_step2315_qpack(config));worker_sha=config["query_worker_sha256"]
        frozen_api={name:api[name] for name in ("load_expanded_indexes","retrieve_loaded_lexical","retrieve_loaded_semantic")}
        runtime={"project_root":root,"config":config,"index":index,"index_api":api,"worker_path":worker,"model_cache_root":cache,
            "diagnostics":{"query_encoder_processes":0,"query_embedding_rows":0,"ranking_calls":0,"lexical_route_calls":0,"semantic_route_calls":0}}
        def guard():
            try:
                good=(runtime["config"] is config and runtime["index"] is index and runtime["index_api"] is api
                    and runtime["worker_path"]==worker and runtime["model_cache_root"]==cache
                    and all(api[name] is function for name,function in frozen_api.items())
                    and _step2315_qsha(_step2315_qpack(config))==frozen_config and _step2315_qindex_state(index)==frozen
                    and {p.name for p in folder.iterdir()}==set(files) and _step2315_qsha(_step2315_qpath(worker).read_bytes())==worker_sha
                    and all(_step2315_qsha(_step2315_qpath(folder/name).read_bytes())==digest for name,digest in files.items()))
            except Exception:good=False
            if not good:raise RuntimeError("step23_query_runtime_failed:index_source_or_fitted_state_changed:ValueError")
            return True
        runtime["verify_unchanged"]=runtime["guard"]=guard;guard();return runtime
    except Exception as error:
        raise RuntimeError("step23_query_runtime_failed:"+stage+":"+type(error).__name__) from None


def encode_queries(runtime,query_records,work_dir,mode="encode_queries",expected_embeddings_sha256=None,embeddings_path=None):
    """Run the pinned offline worker in a fresh process and verify its bound report."""
    import math
    import os
    import re
    import subprocess
    import sys
    import uuid
    import numpy as np
    stage="typed_query_population"
    try:
        rows=_step2315_qrecords(query_records);runtime["guard"]();config=runtime["config"]
        if mode not in ("encode_queries","verify_queries"):raise ValueError("invalid_query_encoding_mode")
        folder=_step2315_qpath(work_dir,directory=True);tag=uuid.uuid4().hex
        if folder.is_relative_to(runtime["index"]["release_root"]) or folder.is_relative_to(runtime["model_cache_root"]):raise ValueError("query_outputs_overlap_immutable_inputs")
        target=_step2315_qpath(embeddings_path if embeddings_path is not None else folder/("query_vectors_"+tag+".npy"),exists=False)
        result=folder/("query_report_"+tag+".json")
        if (not target.parent.is_dir() or target.is_relative_to(runtime["index"]["release_root"]) or target.is_relative_to(runtime["model_cache_root"])
                or (mode=="encode_queries" and (target.exists() or expected_embeddings_sha256 is not None))
                or (mode=="verify_queries" and (not target.is_file() or re.fullmatch(r"[0-9a-f]{64}",str(expected_embeddings_sha256)) is None
                    or _step2315_qsha(target.read_bytes())!=expected_embeddings_sha256))):raise ValueError("existing_or_unbound_query_vectors")
        request={"mode":mode,"semantic_runtime_adoption_id":config["semantic_runtime_adoption_id"],"expanded_retrieval_id":config["expanded_retrieval_id"],"corpus_id":config["corpus_id"],
            "runtime_environment":config["runtime_environment"],"model_source_manifest":config["model_source_manifest"],"model_metadata":config["model_metadata"],
            "model_cache_root":str(runtime["model_cache_root"]),"queries":rows,"embeddings_path":str(target),"result_path":str(result),"expected_embeddings_sha256":expected_embeddings_sha256}
        env=dict(os.environ);env.update(PYTHONDONTWRITEBYTECODE="1",HF_HUB_OFFLINE="1",TRANSFORMERS_OFFLINE="1",HF_HUB_DISABLE_TELEMETRY="1",HF_HUB_DISABLE_PROGRESS_BARS="1",TOKENIZERS_PARALLELISM="false",USE_TF="0",USE_FLAX="0")
        stage="fresh_offline_query_worker"
        process=subprocess.Popen([sys.executable,str(runtime["worker_path"])],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
        try:
            pending=_step2315_qpack(request)
            for elapsed in range(0,241,15):
                try:process.communicate(input=pending,timeout=15);break
                except subprocess.TimeoutExpired:
                    pending=None
                    if elapsed>=225:process.kill();process.communicate();raise TimeoutError("offline_query_worker_timeout")
                    print("Offline query encoding still running ("+str(elapsed+15)+" s)...",flush=True)
        except BaseException:
            if process.poll() is None:process.kill();process.communicate()
            raise
        report=_step2315_qdecode(_step2315_qpath(result).read_bytes())
        if process.returncode!=0 or report.get("status")!="verified_semantic_query_embeddings":
            safe_stage=report.get("stage","worker_report_rejected");safe_exception=report.get("exception_type","RuntimeError")
            stage="worker_"+(safe_stage if type(safe_stage) is str and re.fullmatch(r"[A-Za-z0-9_:.-]{1,120}",safe_stage) else "report_rejected")
            raise RuntimeError("step23_query_runtime_failed:"+stage+":"+(safe_exception if type(safe_exception) is str and re.fullmatch(r"[A-Za-z0-9_]{1,80}",safe_exception) else "RuntimeError"))
        stage="bound_query_report_and_saved_vectors"
        n=len(rows);batch=8 if mode=="encode_queries" else 2;bindings=report["query_bindings"]
        zeros=("queries_generated","publisher_or_model_download_requests","delivery_texts_embedded","corpus_embeddings_created","corpus_payloads_loaded","relevance_judgments_created","classifier_texts_processed","model_training_or_finetuning_runs","retrieval_requests")
        truths=("normalized_embeddings","parameters_frozen","evaluation_mode","deterministic_algorithms_enabled","matched_nonpersistent_position_buffer","full_untruncated_pre_forward_token_ids_verified","native_encoder_truncation_did_not_change_any_forward_input","raw_utf8_query_hashes_preserved","registered_prompt_texts_are_empty")
        if (report["schema_version"]!="step23-semantic-query-worker-report-1" or report["mode"]!=mode
                or any(report[key]!=config[key] for key in ("corpus_id","expanded_retrieval_id","semantic_runtime_adoption_id"))
                or report["model_repo_id"]!=config["model_source_manifest"]["repo_id"] or report["model_revision"]!=config["model_source_manifest"]["revision"]
                or report["runtime_environment"]!={k:config["runtime_environment"][k] for k in ("python_version","versions")}
                or report["embedding_shape"]!=[n,384] or report["embedding_dimension"]!=384 or report["dtype"]!="float32" or report["device"]!="cpu"
                or any(report[key] is not True for key in truths) or any(report[key]!=0 for key in zeros)
                or report["query_token_counts"]!=[b["encoded_tokens_including_specials"] for b in bindings] or len(bindings)!=n
                or any(b["query_id"]!=r["query_id"] or b["text_sha256"]!=r["text_sha256"] or type(b["encoded_tokens_including_specials"]) is not int
                    or not 2<=b["encoded_tokens_including_specials"]<=200 or re.fullmatch(r"[0-9a-f]{64}",str(b["encoded_token_ids_sha256"])) is None for b,r in zip(bindings,rows))
                or report["queries_received"]!=n or report["query_embedding_rows_computed"]!=n or report["query_embedding_rows_saved"]!=(n if mode=="encode_queries" else 0)
                or report["saved_query_rows_reverified"]!=(n if mode=="verify_queries" else 0) or report["batch_size"]!=batch
                or report["embedding_api_requests"]!=1 or report["query_embedding_requests"]!=1 or report["backbone_forward_batches"]!=math.ceil(n/batch)
                or report["tokenizer_requests"]!=1+math.ceil(n/batch) or report["forward_input_rows_checked"]!=n
                or report["model_state_sha256_before"]!=report["model_state_sha256_after"]
                or re.fullmatch(r"[0-9a-f]{64}",str(report["model_state_sha256_before"])) is None
                or report["model_instances_loaded"]!=1 or report["checkpoint_verification_tensor_loads"]!=1 or report["checkpoint_state_tensors_verified"]!=103
                or report["cpu_threads"]!=1 or report["cpu_interop_threads"]!=1 or report["project_encoded_query_limit"]!=200
                or report["comparison_rtol"]!=1e-5 or report["comparison_atol"]!=1e-6
                or report["pooling"]!="attention_masked_mean_then_l2_normalization" or report["weight_format"]!="safetensors"
                or report["trust_remote_code"] is not False or report["default_prompt_name"] is not None or report["truncate_dim"] is not None
                or report["generation_context_budget_verified"] is not False or report["gpu_runtime_verified"] is not False
                or report["model_file_hashes"]!={r["relative_path"]:r["sha256"] for r in config["model_source_manifest"]["files"]}
                or report["classifier_preprocessing_or_task_prompt_applied"] is not False or report["task_prompt_applied"] is not False
                or not report["checks"] or any(c["status"]!="pass" for c in report["checks"])):raise ValueError("query_report_contract_mismatch")
        difference=report["max_absolute_difference_from_saved_matrix"]
        if ((mode=="encode_queries" and difference is not None) or (mode=="verify_queries" and
                (type(difference) not in (int,float) or not math.isfinite(difference) or difference<0))):raise ValueError("invalid_query_replay_difference")
        sourcehash=_step2315_qsha(_step2315_qpath(target).read_bytes());vectors=np.load(target,allow_pickle=False)
        if (sourcehash!=report["embeddings_file_sha256"] or (expected_embeddings_sha256 is not None and sourcehash!=expected_embeddings_sha256)
                or vectors.dtype!=np.dtype("float32") or vectors.shape!=(n,384) or not np.isfinite(vectors).all()
                or not np.allclose(np.linalg.norm(vectors.astype(np.float64),axis=1),np.ones(n),rtol=1e-5,atol=1e-6)):raise ValueError("query_vectors_not_bound_finite_normalized_float32")
        if mode=="encode_queries" and _step2315_qsha(vectors.tobytes(order="C"))!=report["computed_array_content_sha256"]:raise ValueError("query_array_bytes_changed")
        runtime["guard"]();runtime["diagnostics"]["query_encoder_processes"]+=1;runtime["diagnostics"]["query_embedding_rows"]+=n
        return {"report":report,"vectors":vectors,"embedding_path":target,"embeddings_path":target,"embeddings_sha256":sourcehash,"sourcehash":sourcehash}
    except Exception as error:
        runtime["guard"]()
        if str(error).startswith("step23_query_runtime_failed:"):raise
        raise RuntimeError("step23_query_runtime_failed:"+stage+":"+type(error).__name__) from None


def rank_queries(runtime,query_records,vectors,routes=("lexical","semantic")):
    """Execute only requested routes, preserving complete source companions."""
    import numpy as np
    stage="typed_query_and_route_population"
    try:
        rows=_step2315_qrecords(query_records);runtime["guard"]()
        if type(routes) not in (tuple,list) or not routes or len(set(routes))!=len(routes) or any(r not in ("lexical","semantic") for r in routes):raise ValueError("invalid_explicit_retrieval_routes")
        if "semantic" in routes and (not isinstance(vectors,np.ndarray) or vectors.dtype!=np.dtype("float32") or vectors.shape!=(len(rows),384) or not np.isfinite(vectors).all()):raise ValueError("semantic_query_vectors_not_aligned_float32")
        index,api=runtime["index"],runtime["index_api"];by_id={r["passage_id"]:r for r in index["metadata"]};results=[]
        stage="explicit_route_ranking_with_complete_delivery"
        for i,row in enumerate(rows):
            for route in routes:
                result=api["retrieve_loaded_lexical"](index,row["text"],k=5) if route=="lexical" else api["retrieve_loaded_semantic"](index,vectors[i],k=5)
                items=result["results"]
                if (result["route"]!=route or result["returned_distinct_reference_units"]!=len(items) or len(items)>5
                        or len({r["reference_unit_id"] for r in items})!=len(items)
                        or any(r["required_delivery_record"]!=by_id[r["passage_id"]]["required_delivery_record"]
                            or r["reference_unit_id"]!=by_id[r["passage_id"]]["reference_unit_id"]
                            or r["complete_required_delivery_text"]!=by_id[r["passage_id"]]["required_delivery_text"]
                            or r["required_delivery_must_be_attached"] is not True or r["standalone_core_delivery_allowed"] is not False
                            or r["answerability_established_by_score"] is not False or r["generation_context_budget_verified"] is not False for r in items)):
                    raise ValueError("retrieval_delivery_or_distinct_unit_contract_changed")
                results.append({"query_id":row["query_id"],"route":route,"result":result})
        runtime["guard"]();runtime["diagnostics"]["ranking_calls"]+=len(results)
        for route in routes:runtime["diagnostics"][route+"_route_calls"]+=len(rows)
        return results
    except Exception as error:
        runtime["guard"]()
        raise RuntimeError("step23_query_runtime_failed:"+stage+":"+type(error).__name__) from None


def load_query_runtime(project_root,manifest_path,expected_manifest_sha256,model_cache_root=None):
    """Verify an externally trusted query manifest and all its payloads before loading."""
    import re
    from pathlib import Path
    stage="trusted_query_manifest"
    try:
        root=_step2315_qpath(project_root,directory=True);name=Path(manifest_path)
        manifest_path=_step2315_qpath(name if name.is_absolute() else root/name)
        if not manifest_path.is_relative_to(root) or re.fullmatch(r"[0-9a-f]{64}",str(expected_manifest_sha256)) is None:raise ValueError("untrusted_query_manifest_location")
        content=manifest_path.read_bytes();manifest=_step2315_qdecode(content);folder=manifest_path.parent
        if _step2315_qsha(content)!=expected_manifest_sha256 or _step2315_qpack(manifest)!=content or manifest["schema_version"]!="step23-query-runtime-manifest-1":raise ValueError("untrusted_query_manifest_bytes")
        stage="query_payload_hashes_before_configuration_loading"
        hashes=manifest["payload_hashes"]
        if type(hashes) is not dict or not {"query_runtime_config.json","query_worker.py"}.issubset(hashes):raise ValueError("missing_query_runtime_payloads")
        for name,digest in hashes.items():
            if (type(name) is not str or not name or "/" in name or "\\" in name or ":" in name or name in (".","..",manifest_path.name)
                    or re.fullmatch(r"[0-9a-f]{64}",str(digest)) is None or _step2315_qsha(_step2315_qpath(folder/name).read_bytes())!=digest):raise ValueError("query_runtime_payload_hash_mismatch")
        entries=list(folder.iterdir());extra={p.name for p in entries}-set(hashes)-{manifest_path.name};producer=manifest.get("producer_filename")
        if (any(not p.is_file() or p.is_symlink() for p in entries) or (producer is not None and (type(producer) is not str or "/" in producer or "\\" in producer or ":" in producer or producer in (".","..") or extra-{producer}))
                or (producer is None and (len(extra)>1 or any(re.fullmatch(r"step23_[a-z0-9_]+_summary\.json",name) is None for name in extra)))):raise ValueError("unbound_query_runtime_folder_entry")
        config=_step2315_qdecode((folder/"query_runtime_config.json").read_bytes())
        runtime=create_query_runtime(root,config,folder/"query_worker.py",model_cache_root=model_cache_root)
        runtime["query_manifest"]=manifest;runtime["query_manifest_sha256"]=expected_manifest_sha256
        original=runtime["guard"]
        def guard():
            original()
            entries=list(folder.iterdir());extra={p.name for p in entries}-set(hashes)-{manifest_path.name}
            if (manifest_path.read_bytes()!=content or _step2315_qpack(manifest)!=content
                    or any(not p.is_file() or p.is_symlink() for p in entries)
                    or (extra-{producer} if producer is not None else (len(extra)>1 or any(re.fullmatch(r"step23_[a-z0-9_]+_summary\.json",name) is None for name in extra)))
                    or any(_step2315_qsha(_step2315_qpath(folder/name).read_bytes())!=digest for name,digest in hashes.items())):
                raise RuntimeError("step23_query_runtime_failed:query_runtime_release_changed:ValueError")
            return True
        runtime["guard"]=runtime["verify_unchanged"]=guard;guard();return runtime
    except Exception as error:
        raise RuntimeError("step23_query_runtime_failed:"+stage+":"+type(error).__name__) from None
