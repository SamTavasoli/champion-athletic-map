"""Development-only aggregation with the exact frozen relevance/support metric module."""


def score_step2317_development(metric_source,judgments,ranked_results,corpus_unit_ids,dev_questions):
    """Score each primary query/route pair once; replay calls never add observations."""
    import hashlib
    from collections import Counter
    if type(metric_source) is not str or not metric_source.strip():
        raise ValueError("step2317_invalid_verified_metric_source")
    metric={"__name__":"champion_step2317_frozen_metric_module"}
    exec(compile(metric_source,"verified_retrieval_metrics.py","exec"),metric)
    categories=("drill_and_resource","guideline_and_qualification","unsupported_by_identified_corpus")
    routes=("lexical","semantic");checks=[]
    def check(name,condition,observed="verified"):
        if not bool(condition):raise ValueError("step2317_development_scoring_failed:"+name)
        checks.append({"check":name,"status":"pass","observed":str(observed)})
    check("exactly_thirty_development_question_and_judgment_records",type(dev_questions) is list and len(dev_questions)==30
        and type(judgments) is list and len(judgments)==30
        and all(type(q) is dict and q.get("split")=="development" for q in dev_questions)
        and all(type(j) is dict and j.get("split")=="development" for j in judgments))
    ids=[q["query_id"] for q in dev_questions]
    check("question_ids_and_partition_order_are_unique_and_aligned",len(set(ids))==30
        and len({q["question_id"] for q in dev_questions})==30
        and [q["partition_ordinal"] for q in dev_questions]==list(range(1,31))
        and [j["query_id"] for j in judgments]==ids
        and all(j["category"]==q["category"] for q,j in zip(dev_questions,judgments)))
    check("ten_questions_in_each_fixed_development_category",Counter(q["category"] for q in dev_questions)=={c:10 for c in categories})
    check("corpus_unit_population_has_distinct_explicit_ids",type(corpus_unit_ids) is list and bool(corpus_unit_ids)
        and all(type(u) is str and u for u in corpus_unit_ids) and len(set(corpus_unit_ids))==len(corpus_unit_ids))
    expected=[(qid,route) for qid in ids for route in routes]
    check("exactly_sixty_ordered_primary_query_route_pairs",type(ranked_results) is list and len(ranked_results)==60
        and [(r.get("query_id"),r.get("route")) for r in ranked_results]==expected)
    outcomes={route:{} for route in routes};raw_statuses={};rank_ids={}
    for row in ranked_results:
        qid,route=row["query_id"],row["route"];result=row["result"]
        if (type(result) is not dict or result.get("route")!=route or result.get("requested_k")!=5
                or type(result.get("results")) is not list
                or result.get("returned_distinct_reference_units")!=len(result["results"])):
            raise ValueError("step2317_development_scoring_failed:unaligned_retrieval_result_contract")
        items=result["results"];status=result.get("status")
        if status=="ranked":
            if not items:raise ValueError("step2317_development_scoring_failed:ranked_state_requires_results")
            state="completed"
        elif status=="available_no_positive_lexical_matches":
            if route!="lexical" or items:raise ValueError("step2317_development_scoring_failed:invalid_completed_empty_lexical_state")
            state="completed"
        elif status=="not_run":
            if items:raise ValueError("step2317_development_scoring_failed:unrun_result_contains_units")
            state="not_run"
        elif status=="failed" or (type(status) is str and status.startswith("unavailable_")):
            if items:raise ValueError("step2317_development_scoring_failed:failed_result_contains_units")
            state="failed"
        else:raise ValueError("step2317_development_scoring_failed:unknown_retrieval_availability_state")
        returned=[r["reference_unit_id"] for r in items]
        if any("rank" in item and item["rank"]!=rank for rank,item in enumerate(items,1)):
            raise ValueError("step2317_development_scoring_failed:result_rank_fields_disagree_with_order")
        outcomes[route][qid]={"status":state,"ranked_unit_ids":returned}
        raw_statuses[(qid,route)]=status;rank_ids[(qid,route)]=returned
    selection=metric["select_retrieval_method"](judgments,outcomes,corpus_unit_ids)
    check("both_route_aggregates_retain_all_thirty_development_rows",all(
        selection["routes"][route]["split"]=="development" and selection["routes"][route]["population_queries"]==30
        for route in routes))
    check("both_methods_use_identical_nonempty_relevance_query_ids",
        selection["routes"]["lexical"]["ranking_eligible_query_ids"]==selection["routes"]["semantic"]["ranking_eligible_query_ids"])
    check("held_out_is_not_used_for_method_selection",selection["held_out_used_for_selection"] is False and selection["unrounded_values_used"] is True)
    aggregate_fields=("split","population_queries","ranking_selection_denominator","ranking_scored_denominator",
        "empty_relevant_set_queries","pending_judgment_queries","completed_outcomes","failed_outcomes","not_run_outcomes",
        "mean_recall_at_5","mrr_at_5","complete_evidence_scored_denominator","complete_evidence_set_coverage_rate_at_5",
        "all_queries_completed_and_judged","selection_eligible")
    def summary(route,aggregate,subset_questions,**extra):
        return {"route":route,**extra,**{key:aggregate[key] for key in aggregate_fields},
            "question_families":len({q["question_family_id"] for q in subset_questions}),
            "missing_outcomes":len(aggregate["missing_outcome_query_ids"]),
            "scores_are_development_ranking_evidence":True,"ranking_establishes_answerability_or_abstention_accuracy":False}
    route_metrics=[summary(route,selection["routes"][route],dev_questions) for route in routes]
    by_query={q["query_id"]:q for q in dev_questions};gold_by_query={j["query_id"]:j for j in judgments}
    metric_rows={(r["query_id"],route):r for route in routes for r in selection["routes"][route]["per_query"]}
    per_query=[];audit=[]
    for qid,route in expected:
        q=by_query[qid];m=metric_rows[(qid,route)]
        row={"route":route,"question_id":q["question_id"],"question_family_id":q["question_family_id"],
            "partition_ordinal":q["partition_ordinal"],**m,"retrieval_status":raw_statuses[(qid,route)],
            "ranked_unit_ids":rank_ids[(qid,route)],
            "relevant_unit_ids":list(gold_by_query[qid]["relevant_unit_ids"]),
            "missing_relevant_unit_ids_at_5":[u for u in gold_by_query[qid]["relevant_unit_ids"] if u not in rank_ids[(qid,route)]]}
        per_query.append(row);issues=[]
        if m["recall_at_5"] is not None and m["recall_at_5"]<1.0:issues.append("relevant_units_missing_from_top5")
        if m["reciprocal_rank_at_5"] is not None and m["reciprocal_rank_at_5"]<1.0:issues.append("no_relevant_unit_at_rank_one")
        if m["complete_evidence_set_covered_at_5"] is False:issues.append("sufficient_evidence_set_not_covered_at_5")
        if issues:audit.append({**row,"audit_issues":issues,
            "interpretation":"descriptive_ranking_review_candidate; does_not_establish_a_source_or_gold_label_error"})
    category_metrics=[];support_metrics=[]
    for route in routes:
        for category in categories:
            js=[j for j in judgments if j["category"]==category];qs=[q for q in dev_questions if q["category"]==category]
            os={j["query_id"]:outcomes[route][j["query_id"]] for j in js}
            category_metrics.append(summary(route,metric["aggregate_route"](js,os,corpus_unit_ids),qs,category=category))
        for status in ("supported","partially_supported","unsupported"):
            js=[j for j in judgments if j["support_status"]==status];subset={j["query_id"] for j in js}
            qs=[q for q in dev_questions if q["query_id"] in subset];os={j["query_id"]:outcomes[route][j["query_id"]] for j in js}
            support_metrics.append(summary(route,metric["aggregate_route"](js,os,corpus_unit_ids),qs,support_status=status))
    check("empty_gold_rows_keep_unavailable_scores_and_do_not_become_error_rows",all(
        r["recall_at_5"] is r["reciprocal_rank_at_5"] is None for r in per_query if r["relevant_unit_count"]==0)
        and all(r["relevant_unit_count"]!=0 for r in audit))
    check("no_quality_score_is_assigned_to_an_unfinished_or_failed_outcome",all(
        r["recall_at_5"] is r["reciprocal_rank_at_5"] is r["complete_evidence_set_covered_at_5"] is None
        for r in per_query if r["outcome_status"]!="completed"))
    check("all_output_metric_rows_are_development_only",len(per_query)==60 and len(category_metrics)==len(support_metrics)==6
        and all(r["split"]=="development" for r in per_query))
    return {"selection":selection,"route_metrics":route_metrics,"per_query_metrics":per_query,
        "category_metrics":category_metrics,"support_metrics":support_metrics,"error_audit":audit,
        "outcomes":outcomes,"checks":checks,"metric_source_sha256":hashlib.sha256(metric_source.encode("utf-8")).hexdigest(),
        "primary_query_route_pairs_scored":60,"held_out_query_route_pairs_scored":0,
        "replicated_verification_rankings_added_to_metric_denominators":False}


def run_step2317_scoring_probes(metric_source):
    """Authored ranking metadata only; no actual query, encoder, index or study score."""
    import copy
    corpus=["authored-unit-"+str(i) for i in range(1,7)]
    categories=("drill_and_resource","guideline_and_qualification","unsupported_by_identified_corpus")
    questions=[];judgments=[]
    for i in range(30):
        qid="authored-query-"+str(i+1);negative=i>=20;empty=negative and i>=24
        category=categories[i//10]
        questions.append({"query_id":qid,"question_id":"authored-question-"+str(i+1),"split":"development",
            "category":category,"question_family_id":"authored-family-"+str(i//2),"partition_ordinal":i+1})
        judgments.append({"query_id":qid,"split":"development","category":category,"judgment_status":"final",
            "support_status":"unsupported" if negative else "supported","relevant_unit_ids":[] if empty else [corpus[0]],
            "complete_evidence_sets":[] if negative else [[corpus[0]]]})
    def rankings(lexical,semantic):
        rows=[]
        for q in questions:
            for route,units in (("lexical",lexical),("semantic",semantic)):
                rows.append({"query_id":q["query_id"],"route":route,"result":{"route":route,"requested_k":5,
                    "status":"ranked" if units else "available_no_positive_lexical_matches",
                    "returned_distinct_reference_units":len(units),"results":[{"reference_unit_id":u,"rank":i+1} for i,u in enumerate(units)]}})
        return rows
    baseline=rankings([corpus[0]],[corpus[0]])
    def evaluate(rows=None,js=None,qs=None):
        return score_step2317_development(metric_source,judgments if js is None else js,baseline if rows is None else rows,corpus,questions if qs is None else qs)
    checks=[]
    def record(name,condition):
        if not condition:raise AssertionError("step2317_artificial_scoring_failed:"+name)
        checks.append({"check":name,"status":"pass","observed":"authored_metadata_only;no_actual_benchmark_query_or_score"})
    def rejected(name,call):
        try:call()
        except (ValueError,TypeError,KeyError):record(name,True)
        else:record(name,False)
    report=evaluate()
    record("exact_recall_and_mrr_tie_selects_lexical",report["selection"]["selected_route"]=="lexical"
        and report["selection"]["selection_reason"]=="lexical_on_exact_double_tie")
    record("common_selection_denominator_is_twenty_four_not_thirty",all(r["ranking_scored_denominator"]==24 for r in report["route_metrics"]))
    record("six_empty_gold_rows_per_route_remain_unavailable",sum(r["ranking_metric_status"]=="unavailable_empty_relevant_set" for r in report["per_query_metrics"])==12)
    record("sufficient_evidence_coverage_has_its_own_twenty_question_denominator",all(r["complete_evidence_scored_denominator"]==20 for r in report["route_metrics"]))
    record("higher_recall_selects_semantic",evaluate(rankings([corpus[1]],[corpus[0]]))["selection"]["selected_route"]=="semantic")
    record("mrr_breaks_exact_recall_tie",evaluate(rankings([corpus[1],corpus[0]],[corpus[0],corpus[1]]))["selection"]["selection_reason"]=="higher_development_mrr_at_5_on_exact_tie")
    empty=evaluate(rankings([],[corpus[0]]))
    record("completed_empty_lexical_ranking_scores_zero_for_nonempty_gold",empty["route_metrics"][0]["mean_recall_at_5"]==0.0 and empty["route_metrics"][0]["completed_outcomes"]==30)
    failed=copy.deepcopy(baseline);failed[1]["result"].update(status="unavailable_zero_query_embedding",results=[],returned_distinct_reference_units=0)
    unavailable=evaluate(failed)
    record("unavailable_semantic_result_is_failed_unscored_and_blocks_selection",unavailable["selection"]["selected_route"] is None
        and unavailable["per_query_metrics"][1]["recall_at_5"] is None and unavailable["route_metrics"][1]["failed_outcomes"]==1)
    not_run=copy.deepcopy(baseline);not_run[1]["result"].update(status="not_run",results=[],returned_distinct_reference_units=0)
    record("not_run_result_is_not_a_completed_empty_ranking",evaluate(not_run)["selection"]["selected_route"] is None)
    failed_empty_gold=copy.deepcopy(baseline);failed_empty_gold[-1]["result"].update(status="failed",results=[],returned_distinct_reference_units=0)
    record("failed_empty_gold_question_still_blocks_method_selection",evaluate(failed_empty_gold)["selection"]["selected_route"] is None)
    record("empty_gold_is_not_reported_as_a_retrieval_error",all(r["relevant_unit_count"]>0 for r in empty["error_audit"]))
    rejected("missing_query_route_pair_cannot_shrink_denominator",lambda:evaluate(baseline[:-1]))
    wrong_order=copy.deepcopy(baseline);wrong_order[0],wrong_order[1]=wrong_order[1],wrong_order[0]
    rejected("query_route_order_is_not_silently_repaired",lambda:evaluate(wrong_order))
    duplicate=rankings([corpus[0],corpus[0]],[corpus[0]])
    rejected("duplicate_reference_units_are_rejected",lambda:evaluate(duplicate))
    outside=rankings(["authored-outside-corpus"],[corpus[0]])
    rejected("unadmitted_reference_units_are_rejected",lambda:evaluate(outside))
    held=copy.deepcopy(questions);held[0]["split"]="held_out"
    rejected("held_out_metadata_cannot_enter_development_selection",lambda:evaluate(qs=held))
    held_gold=copy.deepcopy(judgments);held_gold[0]["split"]="held_out"
    rejected("held_out_judgments_cannot_enter_development_selection",lambda:evaluate(js=held_gold))
    duplicated_questions=copy.deepcopy(questions);duplicated_questions[1]["query_id"]=duplicated_questions[0]["query_id"]
    rejected("duplicated_question_query_ids_are_rejected",lambda:evaluate(qs=duplicated_questions))
    false_empty=copy.deepcopy(baseline);false_empty[1]["result"].update(status="available_no_positive_lexical_matches",results=[],returned_distinct_reference_units=0)
    rejected("lexical_empty_state_cannot_disguise_semantic_unavailability",lambda:evaluate(false_empty))
    return checks


"""Fresh-process replay of development rankings from saved query vectors only.

The builder prepends the verified pure scoring module. This worker never calls
the query encoder, loads neural weights, fits features or reads held-out rows.
"""


def _step2317_replay_pack(value):
    import json
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n").encode("utf-8")


def _step2317_replay_sha(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()


def _step2317_replay_decode(value):
    import json
    def unique(pairs):
        result={}
        for key,item in pairs:
            if key in result:raise ValueError("duplicate_development_replay_json_key")
            result[key]=item
        return result
    return json.loads(value.decode("utf-8"),object_pairs_hook=unique,
        parse_constant=lambda value:(_ for _ in ()).throw(ValueError("nonfinite_development_replay_json")))


def _step2317_replay_path(value,*,directory=False,exists=True):
    from pathlib import Path
    path=Path(value)
    if (not path.is_absolute() or path.resolve()!=path or any(p.is_symlink() for p in (path,*path.parents))
            or (exists and not (path.is_dir() if directory else path.is_file()))):
        raise ValueError("unsafe_development_replay_path")
    return path


def _step2317_replay_relative(root,value):
    from pathlib import PurePosixPath
    if type(value) is not str or not value or "\\" in value or ":" in value:raise ValueError("unsafe_development_replay_relative_path")
    parsed=PurePosixPath(value)
    if parsed.is_absolute() or parsed.as_posix()!=value or any(p in (".","..") for p in parsed.parts):
        raise ValueError("unsafe_development_replay_relative_path")
    return _step2317_replay_path(root/value)


def _step2317_replay_same_rankings(expected,actual,rtol,atol):
    """Only cosine score scalars receive tolerance; identities and companions stay exact."""
    import math
    maximum=0.0
    def equal(left,right,key=None):
        nonlocal maximum
        if key=="score" and type(left) in (int,float) and type(right) in (int,float):
            if not math.isfinite(left) or not math.isfinite(right) or not math.isclose(left,right,rel_tol=rtol,abs_tol=atol):
                return False
            maximum=max(maximum,abs(left-right));return True
        if type(left) is not type(right):return False
        if type(left) is dict:return set(left)==set(right) and all(equal(left[k],right[k],k) for k in left)
        if type(left) is list:return len(left)==len(right) and all(equal(a,b) for a,b in zip(left,right))
        return left==right
    if not equal(expected,actual):raise ValueError("development_replayed_rankings_or_delivery_changed")
    return maximum


def _step2317_replay_csv(content,expected):
    """Read saved CSV without a dataframe dependency; metric values retain full precision."""
    import csv
    import io
    import math
    reader=csv.DictReader(io.StringIO(content.decode("utf-8")))
    rows=list(reader);columns=[]
    for row in expected:
        for key in row:
            if key not in columns:columns.append(key)
    if reader.fieldnames!=columns or len(rows)!=len(expected):raise ValueError("development_saved_metric_table_inventory_changed")
    for row,wanted in zip(rows,expected):
        for key,value in wanted.items():
            cell=row[key]
            if value is None:valid=cell==""
            elif type(value) is bool:valid=cell==str(value)
            elif type(value) in (int,float):
                try:parsed=float(cell);valid=math.isfinite(parsed) and math.isclose(parsed,value,rel_tol=1e-12,abs_tol=1e-12)
                except (ValueError,TypeError):valid=False
            else:valid=cell==str(value)
            if not valid:raise ValueError("development_saved_metric_table_value_changed")
    return True


def verify_step2317_development_replay(request):
    """Verify the published development bundle and replay its exact thirty queries."""
    import re
    import numpy as np
    required={"project_root","comparison_release_root","expected_manifest_sha256","model_cache_root","result_path"}
    if type(request) is not dict or set(request)!=required:raise ValueError("invalid_development_replay_request")
    root=_step2317_replay_path(request["project_root"],directory=True)
    folder=_step2317_replay_path(request["comparison_release_root"],directory=True)
    cache=_step2317_replay_path(request["model_cache_root"],directory=True)
    result_path=_step2317_replay_path(request["result_path"],exists=False)
    if (not folder.is_relative_to(root) or result_path.is_relative_to(root) or result_path.is_relative_to(cache)
            or result_path.exists() or not result_path.parent.is_dir()
            or re.fullmatch(r"[0-9a-f]{64}",str(request["expected_manifest_sha256"])) is None):
        raise ValueError("invalid_development_replay_locations_or_manifest_hash")
    manifest_name="development_manifest.json";producer_name="step23_development_comparison_summary.json"
    content=(folder/manifest_name).read_bytes();manifest=_step2317_replay_decode(content)
    if (_step2317_replay_sha(content)!=request["expected_manifest_sha256"] or _step2317_replay_pack(manifest)!=content
            or manifest["schema_version"]!="step23-development-comparison-manifest-1"):
        raise ValueError("development_replay_untrusted_manifest")
    expected={"development_queries.jsonl","development_query_embeddings.npy","development_query_verification.json",
        "development_rankings.jsonl","development_per_query_metrics.jsonl","development_route_metrics.csv",
        "development_category_metrics.csv","development_error_audit.jsonl","method_selection_freeze.json",
        "development_checks.csv","development_comparison_config.json","development_diagnostics.json","development_replay_worker.py"}
    hashes=manifest["payload_hashes"]
    if type(hashes) is not dict or set(hashes)!=expected:raise ValueError("development_replay_payload_inventory_changed")
    for name,digest in hashes.items():
        if (re.fullmatch(r"[0-9a-f]{64}",str(digest)) is None
                or _step2317_replay_sha(_step2317_replay_path(folder/name).read_bytes())!=digest):
            raise ValueError("development_replay_payload_hash_changed")
    allowed=expected|{manifest_name,producer_name}
    if any(p.name not in allowed or p.is_symlink() or not p.is_file() for p in folder.iterdir()):
        raise ValueError("development_replay_unbound_folder_entry")
    config=_step2317_replay_decode((folder/"development_comparison_config.json").read_bytes())
    if (config["schema_version"]!="step23-development-comparison-config-1"
            or config["expected_ranking_replay_rtol"]!=1e-5 or config["expected_ranking_replay_atol"]!=1e-6):
        raise ValueError("development_replay_configuration_changed")
    for field in ("development_comparison_id","benchmark_preparation_id","query_preparation_id","corpus_id","expanded_retrieval_id"):
        if field in config and config[field]!=manifest[field]:raise ValueError("development_replay_identity_disagrees")
    def jsonl(name):return [_step2317_replay_decode(line) for line in (folder/name).read_bytes().splitlines()]
    queries=jsonl("development_queries.jsonl");questions=config["development_questions"];judgments=config["development_metric_judgments"]
    if (len(queries)!=30 or len(questions)!=30 or len(judgments)!=30
            or any(type(q) is not dict or set(q)!={"query_id","text","text_sha256"} for q in queries)
            or any(q["split"]!="development" for q in questions) or any(j["split"]!="development" for j in judgments)
            or queries!=[{k:q[k] for k in ("query_id","text","text_sha256")} for q in questions]
            or [q["query_id"] for q in queries]!=[j["query_id"] for j in judgments]):
        raise ValueError("development_replay_thirty_query_population_changed")
    query_manifest=_step2317_replay_relative(root,config["query_manifest_relative_path"])
    source_path=_step2317_replay_path(query_manifest.parent/"query_runtime.py");source_bytes=source_path.read_bytes()
    metric_path=_step2317_replay_relative(root,config["metric_source_relative_path"]);metric_bytes=metric_path.read_bytes()
    if (_step2317_replay_sha(source_bytes)!=config["query_runtime_source_sha256"]
            or _step2317_replay_sha(metric_bytes)!=config["metric_source_sha256"]):
        raise ValueError("development_replay_runtime_or_metric_source_changed")
    api={"__name__":"champion_fresh_development_query_runtime"};exec(compile(source_bytes,str(source_path),"exec"),api)
    runtime=api["load_query_runtime"](root,query_manifest,config["query_manifest_sha256"],cache)
    if (runtime["query_manifest"]["query_preparation_id"]!=manifest["query_preparation_id"]
            or runtime["config"]["corpus_id"]!=manifest["corpus_id"]
            or runtime["config"]["expanded_retrieval_id"]!=manifest["expanded_retrieval_id"]
            or set(config["corpus_unit_ids"])!={r["reference_unit_id"] for r in runtime["index"]["metadata"]}
            or len(config["corpus_unit_ids"])!=11):
        raise ValueError("development_replay_query_runtime_identity_disagrees")
    vectors=np.load(folder/"development_query_embeddings.npy",allow_pickle=False)
    if (vectors.dtype!=np.dtype("float32") or vectors.shape!=(30,384) or not np.isfinite(vectors).all()
            or not np.allclose(np.linalg.norm(vectors.astype(np.float64),axis=1),np.ones(30),rtol=1e-5,atol=1e-6)):
        raise ValueError("development_replay_query_vectors_changed")
    saved_rankings=jsonl("development_rankings.jsonl")
    actual=api["rank_queries"](runtime,queries,vectors,routes=("lexical","semantic"))
    difference=_step2317_replay_same_rankings(saved_rankings,actual,config["expected_ranking_replay_rtol"],config["expected_ranking_replay_atol"])
    scoring=score_step2317_development(metric_bytes.decode("utf-8"),judgments,actual,config["corpus_unit_ids"],questions)
    freeze=_step2317_replay_decode((folder/"method_selection_freeze.json").read_bytes())
    if (freeze["selection"]!=scoring["selection"] or freeze["selected_route"]!=scoring["selection"]["selected_route"]
            or scoring["selection"]["status"]!="selected"
            or jsonl("development_per_query_metrics.jsonl")!=scoring["per_query_metrics"]
            or jsonl("development_error_audit.jsonl")!=scoring["error_audit"]):
        raise ValueError("development_replay_scoring_or_selection_changed")
    for field in ("benchmark_preparation_id","corpus_id","expanded_retrieval_id","query_preparation_id"):
        if field in freeze and freeze[field]!=manifest[field]:raise ValueError("development_replay_freeze_identity_disagrees")
    _step2317_replay_csv((folder/"development_route_metrics.csv").read_bytes(),scoring["route_metrics"])
    _step2317_replay_csv((folder/"development_category_metrics.csv").read_bytes(),scoring["category_metrics"])
    expected_diagnostics={"query_encoder_processes":0,"query_embedding_rows":0,"ranking_calls":60,"lexical_route_calls":30,"semantic_route_calls":30}
    if runtime["diagnostics"]!=expected_diagnostics:raise ValueError("development_replay_additional_calls_detected")
    runtime["guard"]()
    if (source_path.read_bytes()!=source_bytes or metric_path.read_bytes()!=metric_bytes or (folder/manifest_name).read_bytes()!=content
            or any(_step2317_replay_sha(_step2317_replay_path(folder/name).read_bytes())!=digest for name,digest in hashes.items())):
        raise ValueError("development_replay_bound_source_or_payload_changed")
    checks=[{"check":name,"status":"pass","observed":str(value)} for name,value in (
        ("trusted_manifest_and_thirteen_payload_hashes_verified",13),
        ("only_thirty_frozen_development_query_rows_loaded",30),
        ("saved_float32_query_vectors_reused_without_encoder",[30,384]),
        ("sixty_rankings_reproduced_with_exact_unit_order_and_complete_companions",60),
        ("cosine_scores_match_with_recorded_tolerances",difference),
        ("primary_metric_denominators_and_selected_method_match",scoring["selection"]["common_ranking_selection_denominator"]),
        ("per_query_tables_route_category_csv_and_error_audit_match",True),
        ("query_runtime_fitted_state_and_all_bound_bytes_unchanged",True),
        ("no_query_encoder_or_neural_model_calls_during_replay",0),
        ("held_out_queries_not_loaded_or_executed",0))]
    return {"schema_version":"step23-development-replay-report-1","status":"verified_development_comparison_replay",
        **{k:manifest[k] for k in ("development_comparison_id","benchmark_preparation_id","query_preparation_id","corpus_id","expanded_retrieval_id")},
        "manifest_sha256":request["expected_manifest_sha256"],"query_rows":30,"ranking_calls":60,"lexical_route_calls":30,"semantic_route_calls":30,
        "additional_model_loads":0,"query_encoder_calls":0,"held_out_queries":0,"source_hashes_unchanged":True,
        "primary_ranking_scores_max_absolute_difference":difference,"ranking_replay_rtol":1e-5,"ranking_replay_atol":1e-6,
        "scoring":scoring,"scoring_sha256":_step2317_replay_sha(_step2317_replay_pack(scoring)),"checks":checks}


def _step2317_replay_write(path,report):
    import os
    target=_step2317_replay_path(path,exists=False)
    if target.exists() or not target.parent.is_dir():raise ValueError("development_replay_result_path_exists")
    with target.open("xb") as stream:
        stream.write(_step2317_replay_pack(report));stream.flush();os.fsync(stream.fileno())


if __name__=="__main__":
    import json
    import sys
    request=None
    try:
        request=json.load(sys.stdin)
        report=verify_step2317_development_replay(request)
        _step2317_replay_write(request["result_path"],report)
    except Exception as error:
        import re
        message=str(error)
        stage=message if re.fullmatch(r"development_replay_[A-Za-z0-9_]{1,100}",message) else "saved_development_replay"
        report={"schema_version":"step23-development-replay-report-1","status":"failed","stage":stage,"exception_type":type(error).__name__}
        try:
            if type(request) is dict and type(request.get("result_path")) is str:
                _step2317_replay_write(request["result_path"],report)
        except Exception:pass
        print(json.dumps(report,sort_keys=True))
        raise SystemExit(1)
