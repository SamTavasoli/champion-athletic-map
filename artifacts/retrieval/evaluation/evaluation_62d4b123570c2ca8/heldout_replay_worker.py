"""Held-out ranking evaluation under the development-frozen method and metric policy."""


def score_step2318_heldout(metric_source,judgments,ranked_results,corpus_unit_ids,heldout_questions,selected_route):
    """Aggregate the selected route once; held-out outcomes never choose a method."""
    import hashlib
    from collections import Counter
    if type(metric_source) is not str or not metric_source.strip():
        raise ValueError("step2318_invalid_verified_metric_source")
    metric={"__name__":"champion_step2318_frozen_metric_module"}
    exec(compile(metric_source,"verified_retrieval_metrics.py","exec"),metric)
    categories=("drill_and_resource","guideline_and_qualification","unsupported_by_identified_corpus")
    checks=[]
    def check(name,condition,observed="verified"):
        if not bool(condition):raise ValueError("step2318_heldout_scoring_failed:"+name)
        checks.append({"check":name,"status":"pass","observed":str(observed)})
    check("only_an_explicit_development_frozen_route_is_evaluated",selected_route in ("lexical","semantic"))
    check("exactly_thirty_heldout_questions_and_judgments",type(heldout_questions) is list and len(heldout_questions)==30
        and type(judgments) is list and len(judgments)==30
        and all(type(q) is dict and q.get("split")=="held_out" for q in heldout_questions)
        and all(type(j) is dict and j.get("split")=="held_out" for j in judgments))
    ids=[q["query_id"] for q in heldout_questions]
    check("question_identity_and_frozen_partition_order_are_aligned",len(set(ids))==30
        and len({q["question_id"] for q in heldout_questions})==30
        and [q["partition_ordinal"] for q in heldout_questions]==list(range(1,31))
        and [j["query_id"] for j in judgments]==ids
        and all(j["category"]==q["category"] for q,j in zip(heldout_questions,judgments)))
    check("each_fixed_category_has_ten_questions_and_five_families",
        Counter(q["category"] for q in heldout_questions)=={c:10 for c in categories}
        and len({q["question_family_id"] for q in heldout_questions})==15
        and all(len({q["question_family_id"] for q in heldout_questions if q["category"]==c})==5 for c in categories))
    check("corpus_unit_population_has_distinct_explicit_ids",type(corpus_unit_ids) is list and bool(corpus_unit_ids)
        and all(type(u) is str and u for u in corpus_unit_ids) and len(set(corpus_unit_ids))==len(corpus_unit_ids))
    check("frozen_gold_has_twenty_supported_six_empty_and_twenty_four_nonempty_sets",
        all(j.get("judgment_status")=="final" for j in judgments)
        and sum(j["support_status"]=="supported" for j in judgments)==20
        and sum(not j["relevant_unit_ids"] for j in judgments)==6
        and sum(bool(j["relevant_unit_ids"]) for j in judgments)==24)
    expected=[(qid,selected_route) for qid in ids]
    check("exactly_thirty_ordered_selected_route_pairs_and_no_alternate_route",type(ranked_results) is list
        and len(ranked_results)==30 and all(type(r) is dict for r in ranked_results)
        and [(r.get("query_id"),r.get("route")) for r in ranked_results]==expected)
    outcomes={};raw_statuses={};rank_ids={}
    for row in ranked_results:
        qid=row["query_id"];result=row["result"]
        if (type(result) is not dict or result.get("route")!=selected_route or result.get("requested_k")!=5
                or type(result.get("results")) is not list
                or result.get("returned_distinct_reference_units")!=len(result["results"])):
            raise ValueError("step2318_heldout_scoring_failed:unaligned_retrieval_result_contract")
        items=result["results"];status=result.get("status")
        if status=="ranked":
            if not items:raise ValueError("step2318_heldout_scoring_failed:ranked_state_requires_results")
            state="completed"
        elif status=="available_no_positive_lexical_matches":
            if selected_route!="lexical" or items:raise ValueError("step2318_heldout_scoring_failed:invalid_completed_empty_lexical_state")
            state="completed"
        elif status=="not_run":
            if items:raise ValueError("step2318_heldout_scoring_failed:unrun_result_contains_units")
            state="not_run"
        elif status=="failed" or (type(status) is str and status.startswith("unavailable_")):
            if items:raise ValueError("step2318_heldout_scoring_failed:failed_result_contains_units")
            state="failed"
        else:raise ValueError("step2318_heldout_scoring_failed:unknown_retrieval_availability_state")
        if any("rank" in item and item["rank"]!=rank for rank,item in enumerate(items,1)):
            raise ValueError("step2318_heldout_scoring_failed:result_rank_fields_disagree_with_order")
        returned=[item["reference_unit_id"] for item in items]
        outcomes[qid]={"status":state,"ranked_unit_ids":returned};raw_statuses[qid]=status;rank_ids[qid]=returned
    # Deliberately do not call the metric module's development selector.
    aggregate=metric["aggregate_route"](judgments,outcomes,corpus_unit_ids)
    check("the_heldout_aggregate_retains_all_thirty_rows",aggregate["split"]=="held_out" and aggregate["population_queries"]==30
        and aggregate["ranking_selection_denominator"]==24 and aggregate["empty_relevant_set_queries"]==6)
    aggregate_fields=("split","population_queries","ranking_selection_denominator","ranking_scored_denominator",
        "empty_relevant_set_queries","pending_judgment_queries","completed_outcomes","failed_outcomes","not_run_outcomes",
        "mean_recall_at_5","mrr_at_5","complete_evidence_scored_denominator","complete_evidence_set_coverage_rate_at_5",
        "all_queries_completed_and_judged")
    def summary(aggregated,subset_questions,**extra):
        return {"route":selected_route,**extra,**{key:aggregated[key] for key in aggregate_fields},
            "question_families":len({q["question_family_id"] for q in subset_questions}),
            "missing_outcomes":len(aggregated["missing_outcome_query_ids"]),
            "scores_are_heldout_ranking_evidence":True,"used_for_method_selection":False,
            "ranking_establishes_answerability_or_abstention_accuracy":False}
    route_metrics=[summary(aggregate,heldout_questions)]
    gold_by_query={j["query_id"]:j for j in judgments};metric_rows={r["query_id"]:r for r in aggregate["per_query"]}
    per_query=[];audit=[]
    for q in heldout_questions:
        qid=q["query_id"];m=metric_rows[qid]
        row={"route":selected_route,"question_id":q["question_id"],"question_family_id":q["question_family_id"],
            "partition_ordinal":q["partition_ordinal"],**m,"retrieval_status":raw_statuses[qid],
            "ranked_unit_ids":rank_ids[qid],"relevant_unit_ids":list(gold_by_query[qid]["relevant_unit_ids"]),
            "missing_relevant_unit_ids_at_5":[u for u in gold_by_query[qid]["relevant_unit_ids"] if u not in rank_ids[qid]]}
        per_query.append(row);issues=[]
        if m["recall_at_5"] is not None and m["recall_at_5"]<1.0:issues.append("relevant_units_missing_from_top5")
        if m["reciprocal_rank_at_5"] is not None and m["reciprocal_rank_at_5"]<1.0:issues.append("no_relevant_unit_at_rank_one")
        if m["complete_evidence_set_covered_at_5"] is False:issues.append("sufficient_evidence_set_not_covered_at_5")
        if issues:audit.append({**row,"audit_issues":issues,
            "interpretation":"descriptive_heldout_ranking_review_candidate; does_not_establish_a_source_or_gold_label_error"})
    category_metrics=[];support_metrics=[]
    for category in categories:
        js=[j for j in judgments if j["category"]==category];qs=[q for q in heldout_questions if q["category"]==category]
        os={j["query_id"]:outcomes[j["query_id"]] for j in js}
        category_metrics.append(summary(metric["aggregate_route"](js,os,corpus_unit_ids),qs,category=category))
    for status in ("supported","partially_supported","unsupported"):
        js=[j for j in judgments if j["support_status"]==status];subset={j["query_id"] for j in js}
        qs=[q for q in heldout_questions if q["query_id"] in subset];os={j["query_id"]:outcomes[j["query_id"]] for j in js}
        support_metrics.append(summary(metric["aggregate_route"](js,os,corpus_unit_ids),qs,support_status=status))
    check("empty_gold_scores_stay_unavailable_and_are_not_error_candidates",all(
        r["recall_at_5"] is r["reciprocal_rank_at_5"] is None for r in per_query if r["relevant_unit_count"]==0)
        and all(r["relevant_unit_count"]>0 for r in audit))
    check("failed_and_unrun_results_are_unscored_and_prevent_completion",all(
        r["recall_at_5"] is r["reciprocal_rank_at_5"] is r["complete_evidence_set_covered_at_5"] is None
        for r in per_query if r["outcome_status"]!="completed")
        and (aggregate["all_queries_completed_and_judged"] or aggregate["completed_outcomes"]<30))
    check("all_saved_metric_rows_are_selected_route_heldout_only",len(per_query)==30
        and len(category_metrics)==len(support_metrics)==3 and all(r["split"]=="held_out" and r["route"]==selected_route for r in per_query))
    return {"selected_route":selected_route,"aggregate":aggregate,"route_metrics":route_metrics,"per_query_metrics":per_query,
        "category_metrics":category_metrics,"support_metrics":support_metrics,"error_audit":audit,"outcomes":outcomes,"checks":checks,
        "metric_source_sha256":hashlib.sha256(metric_source.encode("utf-8")).hexdigest(),"primary_query_route_pairs_scored":30,
        "alternate_route_query_pairs_scored":0,"method_selection_performed":False,"held_out_used_for_method_selection":False,
        "held_out_evaluation_complete":aggregate["all_queries_completed_and_judged"],
        "replicated_verification_rankings_added_to_metric_denominators":False}


def run_step2318_scoring_probes(metric_source):
    """Authored ranking metadata only; no corpus requests, encodings or study scores."""
    import copy
    corpus=["authored-unit-"+str(i) for i in range(1,7)]
    categories=("drill_and_resource","guideline_and_qualification","unsupported_by_identified_corpus")
    questions=[];judgments=[]
    for i in range(30):
        qid="authored-heldout-query-"+str(i+1);negative=i>=20;empty=negative and i>=24
        status="supported" if not negative else ("partially_supported" if i<22 else "unsupported")
        questions.append({"query_id":qid,"question_id":"authored-heldout-question-"+str(i+1),"split":"held_out",
            "category":categories[i//10],"question_family_id":"authored-heldout-family-"+str(i//2),"partition_ordinal":i+1})
        judgments.append({"query_id":qid,"split":"held_out","category":categories[i//10],"judgment_status":"final",
            "support_status":status,"relevant_unit_ids":[] if empty else [corpus[0]],
            "complete_evidence_sets":[] if negative else [[corpus[0]]]})
    def rankings(route,units):
        return [{"query_id":q["query_id"],"route":route,"result":{"route":route,"requested_k":5,
            "status":"ranked" if units else "available_no_positive_lexical_matches",
            "returned_distinct_reference_units":len(units),"results":[{"reference_unit_id":u,"rank":i+1} for i,u in enumerate(units)]}}
            for q in questions]
    baseline=rankings("semantic",[corpus[0]])
    def evaluate(rows=None,qs=None,js=None,route="semantic",source=None):
        return score_step2318_heldout(metric_source if source is None else source,judgments if js is None else js,
            baseline if rows is None else rows,corpus,questions if qs is None else qs,route)
    checks=[]
    def record(name,condition):
        if not condition:raise AssertionError("step2318_artificial_scoring_failed:"+name)
        checks.append({"check":name,"status":"pass","observed":"authored_metadata_only;no_actual_heldout_query_or_score"})
    def rejected(name,call):
        try:call()
        except (ValueError,TypeError,KeyError):record(name,True)
        else:record(name,False)
    report=evaluate()
    record("thirty_completed_heldout_rows_retain_twenty_four_ranking_scores",report["held_out_evaluation_complete"]
        and report["aggregate"]["population_queries"]==30 and report["aggregate"]["ranking_scored_denominator"]==24)
    record("six_empty_gold_queries_are_unavailable_not_zero_or_perfect",sum(r["ranking_metric_status"]=="unavailable_empty_relevant_set" for r in report["per_query_metrics"])==6)
    record("complete_evidence_coverage_uses_twenty_supported_queries_only",report["aggregate"]["complete_evidence_scored_denominator"]==20
        and all(r["complete_evidence_set_covered_at_5"] is None for r in report["per_query_metrics"] if r["support_status"]!="supported"))
    record("partial_context_scores_do_not_become_full_answer_support",report["support_metrics"][1]["ranking_scored_denominator"]==2
        and report["support_metrics"][1]["complete_evidence_scored_denominator"]==0)
    guarded_source=metric_source+"\n\ndef select_retrieval_method(*args,**kwargs):\n    raise AssertionError('heldout_must_never_call_selector')\n"
    no_selection=evaluate(source=guarded_source)
    record("heldout_evaluation_never_calls_the_development_method_selector",no_selection["selected_route"]=="semantic" and no_selection["method_selection_performed"] is False)
    bad=evaluate(rankings("semantic",[corpus[1]]))
    record("poor_heldout_scores_do_not_switch_the_frozen_method",bad["selected_route"]=="semantic"
        and bad["aggregate"]["mean_recall_at_5"]==0.0 and bad["method_selection_performed"] is False)
    lexical=evaluate(rankings("lexical",[]),route="lexical")
    record("a_frozen_lexical_route_can_complete_empty_rankings_without_fallback",lexical["selected_route"]=="lexical"
        and lexical["aggregate"]["mean_recall_at_5"]==0.0 and lexical["held_out_evaluation_complete"])
    failed=copy.deepcopy(baseline);failed[0]["result"].update(status="unavailable_zero_query_embedding",results=[],returned_distinct_reference_units=0)
    unavailable=evaluate(failed)
    record("unavailable_result_is_unscored_and_blocks_completion",not unavailable["held_out_evaluation_complete"]
        and unavailable["per_query_metrics"][0]["recall_at_5"] is None and unavailable["aggregate"]["failed_outcomes"]==1)
    unrun=copy.deepcopy(baseline);unrun[0]["result"].update(status="not_run",results=[],returned_distinct_reference_units=0)
    record("not_run_is_distinct_from_completed_empty_retrieval",not evaluate(unrun)["held_out_evaluation_complete"])
    failed_empty=copy.deepcopy(baseline);failed_empty[-1]["result"].update(status="failed",results=[],returned_distinct_reference_units=0)
    record("failed_empty_gold_query_still_prevents_completion",not evaluate(failed_empty)["held_out_evaluation_complete"])
    record("empty_gold_queries_are_not_ranking_error_candidates",all(r["relevant_unit_count"]>0 for r in lexical["error_audit"]))
    rejected("missing_selected_route_pair_cannot_shrink_population",lambda:evaluate(baseline[:-1]))
    alternate=copy.deepcopy(baseline);alternate[0]["route"]="lexical";alternate[0]["result"]["route"]="lexical"
    rejected("alternate_route_cannot_enter_heldout_comparison",lambda:evaluate(alternate))
    wrong_order=copy.deepcopy(baseline);wrong_order[0],wrong_order[1]=wrong_order[1],wrong_order[0]
    rejected("saved_partition_order_is_not_silently_repaired",lambda:evaluate(wrong_order))
    rejected("duplicate_ranked_units_are_rejected",lambda:evaluate(rankings("semantic",[corpus[0],corpus[0]])))
    rejected("unadmitted_ranked_unit_is_rejected",lambda:evaluate(rankings("semantic",["authored-outside-corpus"])))
    development=copy.deepcopy(questions);development[0]["split"]="development"
    rejected("development_question_metadata_cannot_enter_heldout_scores",lambda:evaluate(qs=development))
    development_gold=copy.deepcopy(judgments);development_gold[0]["split"]="development"
    rejected("development_judgments_cannot_enter_heldout_scores",lambda:evaluate(js=development_gold))
    duplicate=copy.deepcopy(questions);duplicate[1]["query_id"]=duplicate[0]["query_id"]
    rejected("duplicated_question_query_ids_are_rejected",lambda:evaluate(qs=duplicate))
    false_empty=copy.deepcopy(baseline);false_empty[0]["result"].update(status="available_no_positive_lexical_matches",results=[],returned_distinct_reference_units=0)
    rejected("lexical_empty_state_cannot_disguise_semantic_unavailability",lambda:evaluate(false_empty))
    return checks


"""Fresh-process replay of only the frozen retrieval method on held-out questions.

The builder prepends the verified pure scoring module. This worker never calls
the query encoder, loads neural weights, fits features or changes the method choice.
"""


def _step2318_replay_pack(value):
    import json
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n").encode("utf-8")


def _step2318_replay_sha(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()


def _step2318_replay_decode(value):
    import json
    def unique(pairs):
        result={}
        for key,item in pairs:
            if key in result:raise ValueError("duplicate_heldout_replay_json_key")
            result[key]=item
        return result
    return json.loads(value.decode("utf-8"),object_pairs_hook=unique,
        parse_constant=lambda value:(_ for _ in ()).throw(ValueError("nonfinite_heldout_replay_json")))


def _step2318_replay_path(value,*,directory=False,exists=True):
    from pathlib import Path
    path=Path(value)
    if (not path.is_absolute() or path.resolve()!=path or any(p.is_symlink() for p in (path,*path.parents))
            or (exists and not (path.is_dir() if directory else path.is_file()))):
        raise ValueError("unsafe_heldout_replay_path")
    return path


def _step2318_replay_relative(root,value):
    from pathlib import PurePosixPath
    if type(value) is not str or not value or "\\" in value or ":" in value:raise ValueError("unsafe_heldout_replay_relative_path")
    parsed=PurePosixPath(value)
    if parsed.is_absolute() or parsed.as_posix()!=value or any(p in (".","..") for p in parsed.parts):
        raise ValueError("unsafe_heldout_replay_relative_path")
    return _step2318_replay_path(root/value)


def _step2318_replay_same_rankings(expected,actual,rtol,atol):
    """Only cosine score scalars receive tolerance; identities and companions stay exact."""
    import math
    maximum=0.0
    def equal(left,right,key=None):
        nonlocal maximum
        if key in ("required_delivery_record","complete_required_delivery_text"):
            return type(left) is type(right) and left==right
        if key=="score" and type(left) in (int,float) and type(right) in (int,float):
            if not math.isfinite(left) or not math.isfinite(right) or not math.isclose(left,right,rel_tol=rtol,abs_tol=atol):
                return False
            maximum=max(maximum,abs(left-right));return True
        if type(left) is not type(right):return False
        if type(left) is dict:return set(left)==set(right) and all(equal(left[k],right[k],k) for k in left)
        if type(left) is list:return len(left)==len(right) and all(equal(a,b) for a,b in zip(left,right))
        return left==right
    if not equal(expected,actual):raise ValueError("heldout_replayed_rankings_or_delivery_changed")
    return maximum


def _step2318_replay_csv(content,expected):
    """Read saved CSV without a dataframe dependency; metric values retain full precision."""
    import csv
    import io
    import math
    reader=csv.DictReader(io.StringIO(content.decode("utf-8")))
    rows=list(reader);columns=[]
    for row in expected:
        for key in row:
            if key not in columns:columns.append(key)
    if reader.fieldnames!=columns or len(rows)!=len(expected):raise ValueError("heldout_saved_metric_table_inventory_changed")
    for row,wanted in zip(rows,expected):
        for key,value in wanted.items():
            cell=row[key]
            if value is None:valid=cell==""
            elif type(value) is bool:valid=cell==str(value)
            elif type(value) in (int,float):
                try:parsed=float(cell);valid=math.isfinite(parsed) and math.isclose(parsed,value,rel_tol=1e-12,abs_tol=1e-12)
                except (ValueError,TypeError):valid=False
            else:valid=cell==str(value)
            if not valid:raise ValueError("heldout_saved_metric_table_value_changed")
    return True


def _step2318_replay_handoff(handoff,config,runtime):
    """Only public runtime bindings may be delivered as the next-stage runtime view."""
    allowed={"selected_route","query_manifest_relative_path","query_manifest_sha256",
        "expanded_index_manifest_relative_path","expanded_index_manifest_sha256","corpus_id",
        "expanded_retrieval_id","query_preparation_id","ranking_k","unit_score",
        "semantic_answerability_threshold","lexical_zero_score_fill"}
    view=handoff.get("runtime") if type(handoff) is dict else None
    if type(view) is not dict or set(view)!=allowed:
        raise ValueError("heldout_replay_handoff_runtime_scope_changed")
    same=("selected_route","query_manifest_relative_path","query_manifest_sha256","corpus_id","expanded_retrieval_id","query_preparation_id")
    if (any(view[k]!=config[k] for k in same)
            or view["expanded_index_manifest_relative_path"]!=runtime["config"]["expanded_index_manifest_relative_path"]
            or view["expanded_index_manifest_sha256"]!=runtime["config"]["expanded_index_manifest_sha256"]
            or view["ranking_k"]!=5 or view["unit_score"]!="maximum_passage_score"
            or view["semantic_answerability_threshold"] is not None or view["lexical_zero_score_fill"] is not False):
        raise ValueError("heldout_replay_handoff_runtime_identity_changed")
    prohibited={"questions","heldout_questions","development_questions","judgments","metric_judgments",
        "heldout_metric_judgments","development_metric_judgments","gold","error_audit","rankings",
        "per_query_metrics","expected_support_outline","required_claims"}
    forbidden_names=("benchmark_questions.jsonl","benchmark_judgments.jsonl","heldout_queries.jsonl",
        "heldout_rankings.jsonl","heldout_per_query_metrics.jsonl","heldout_error_audit.jsonl")
    def safe(value):
        if type(value) is dict:return not (set(value)&prohibited) and all(safe(v) for v in value.values())
        if type(value) is list:return all(safe(v) for v in value)
        if type(value) is str:return not any(name in value for name in forbidden_names)
        return True
    if not safe(handoff):raise ValueError("heldout_replay_private_evaluation_material_in_handoff")
    return True


def verify_step2318_heldout_replay(request):
    """Replay saved held-out vectors on the original selected route, with no reselection."""
    import re
    import numpy as np
    required={"project_root","evaluation_release_root","expected_manifest_sha256","model_cache_root","result_path"}
    if type(request) is not dict or set(request)!=required:raise ValueError("invalid_heldout_replay_request")
    root=_step2318_replay_path(request["project_root"],directory=True)
    folder=_step2318_replay_path(request["evaluation_release_root"],directory=True)
    cache=_step2318_replay_path(request["model_cache_root"],directory=True)
    result_path=_step2318_replay_path(request["result_path"],exists=False)
    if (not folder.is_relative_to(root) or result_path.is_relative_to(root) or result_path.is_relative_to(cache)
            or result_path.exists() or not result_path.parent.is_dir()
            or re.fullmatch(r"[0-9a-f]{64}",str(request["expected_manifest_sha256"])) is None):
        raise ValueError("invalid_heldout_replay_locations_or_manifest_hash")
    manifest_name="heldout_manifest.json";producer_name="step23_retrieval_evaluation_summary.json"
    content=(folder/manifest_name).read_bytes();manifest=_step2318_replay_decode(content)
    if (_step2318_replay_sha(content)!=request["expected_manifest_sha256"] or _step2318_replay_pack(manifest)!=content
            or manifest["schema_version"]!="step23-heldout-evaluation-manifest-1"):
        raise ValueError("heldout_replay_untrusted_manifest")
    expected={"heldout_queries.jsonl","heldout_query_embeddings.npy","heldout_query_verification.json",
        "heldout_rankings.jsonl","heldout_per_query_metrics.jsonl","heldout_route_metrics.csv",
        "heldout_category_metrics.csv","heldout_error_audit.jsonl","frozen_method_evaluation.json",
        "retrieval_handoff.json","retrieval_findings.md","heldout_checks.csv","heldout_evaluation_config.json",
        "heldout_diagnostics.json","heldout_replay_worker.py"}
    hashes=manifest["payload_hashes"]
    if type(hashes) is not dict or set(hashes)!=expected:raise ValueError("heldout_replay_payload_inventory_changed")
    for name,digest in hashes.items():
        if (re.fullmatch(r"[0-9a-f]{64}",str(digest)) is None
                or _step2318_replay_sha(_step2318_replay_path(folder/name).read_bytes())!=digest):
            raise ValueError("heldout_replay_payload_hash_changed")
    allowed=expected|{manifest_name,producer_name}
    if any(p.name not in allowed or p.is_symlink() or not p.is_file() for p in folder.iterdir()):
        raise ValueError("heldout_replay_unbound_folder_entry")
    config=_step2318_replay_decode((folder/"heldout_evaluation_config.json").read_bytes())
    route=config["selected_route"]
    if (config["schema_version"]!="step23-heldout-evaluation-config-1" or route not in ("lexical","semantic")
            or config["expected_ranking_replay_rtol"]!=1e-5 or config["expected_ranking_replay_atol"]!=1e-6):
        raise ValueError("heldout_replay_configuration_changed")
    identity_fields=("heldout_evaluation_id","development_comparison_id","benchmark_preparation_id",
        "query_preparation_id","corpus_id","expanded_retrieval_id","selected_route")
    if any(config[k]!=manifest[k] for k in identity_fields):raise ValueError("heldout_replay_identity_disagrees")
    # The prior development freeze is checked before any held-out ranking is executed.
    old_freeze_path=_step2318_replay_relative(root,config["selection_freeze_relative_path"])
    old_freeze_bytes=old_freeze_path.read_bytes();old_freeze=_step2318_replay_decode(old_freeze_bytes)
    wanted_id="retrieval-method-selection:"+_step2318_replay_sha(_step2318_replay_pack({
        k:v for k,v in old_freeze.items() if k!="selection_freeze_id"}))
    if (_step2318_replay_sha(old_freeze_bytes)!=config["selection_freeze_sha256"]
            or _step2318_replay_pack(old_freeze)!=old_freeze_bytes
            or old_freeze["selection_freeze_id"]!=wanted_id
            or old_freeze["selected_route"]!=route or old_freeze["selection"]["selected_route"]!=route
            or old_freeze["selection"]["status"]!="selected" or old_freeze["selection"]["held_out_used_for_selection"] is not False
            or old_freeze["held_out_queries_used_for_selection"]!=0
            or old_freeze["held_out_execution_status"]!="pending_step23_18"
            or any(old_freeze[k]!=manifest[k] for k in ("development_comparison_id","benchmark_preparation_id","query_preparation_id","corpus_id","expanded_retrieval_id"))):
        raise ValueError("heldout_replay_original_method_freeze_changed")
    def jsonl(name):return [_step2318_replay_decode(line) for line in (folder/name).read_bytes().splitlines()]
    queries=jsonl("heldout_queries.jsonl");questions=config["heldout_questions"];judgments=config["heldout_metric_judgments"]
    if (len(queries)!=30 or len(questions)!=30 or len(judgments)!=30
            or any(type(q) is not dict or set(q)!={"query_id","text","text_sha256"} for q in queries)
            or any(q["split"]!="held_out" for q in questions) or any(j["split"]!="held_out" for j in judgments)
            or queries!=[{k:q[k] for k in ("query_id","text","text_sha256")} for q in questions]
            or [q["query_id"] for q in queries]!=[j["query_id"] for j in judgments]):
        raise ValueError("heldout_replay_thirty_query_population_changed")
    query_manifest=_step2318_replay_relative(root,config["query_manifest_relative_path"])
    source_path=_step2318_replay_path(query_manifest.parent/"query_runtime.py");source_bytes=source_path.read_bytes()
    metric_path=_step2318_replay_relative(root,config["metric_source_relative_path"]);metric_bytes=metric_path.read_bytes()
    if (_step2318_replay_sha(source_bytes)!=config["query_runtime_source_sha256"]
            or _step2318_replay_sha(metric_bytes)!=config["metric_source_sha256"]):
        raise ValueError("heldout_replay_runtime_or_metric_source_changed")
    api={"__name__":"champion_fresh_heldout_query_runtime"};exec(compile(source_bytes,str(source_path),"exec"),api)
    runtime=api["load_query_runtime"](root,query_manifest,config["query_manifest_sha256"],cache)
    if (runtime["query_manifest"]["query_preparation_id"]!=manifest["query_preparation_id"]
            or runtime["config"]["corpus_id"]!=manifest["corpus_id"]
            or runtime["config"]["expanded_retrieval_id"]!=manifest["expanded_retrieval_id"]
            or set(config["corpus_unit_ids"])!={r["reference_unit_id"] for r in runtime["index"]["metadata"]}
            or len(config["corpus_unit_ids"])!=11):
        raise ValueError("heldout_replay_query_runtime_identity_disagrees")
    saved_vectors=np.load(folder/"heldout_query_embeddings.npy",allow_pickle=False)
    if route=="semantic":
        if (saved_vectors.dtype!=np.dtype("float32") or saved_vectors.shape!=(30,384) or not np.isfinite(saved_vectors).all()
                or not np.allclose(np.linalg.norm(saved_vectors.astype(np.float64),axis=1),np.ones(30),rtol=1e-5,atol=1e-6)):
            raise ValueError("heldout_replay_query_vectors_changed")
        vectors=saved_vectors;embedding_rows=30
    else:
        if saved_vectors.dtype!=np.dtype("float32") or saved_vectors.shape!=(0,384):
            raise ValueError("heldout_replay_unused_semantic_vector_inventory_changed")
        vectors=None;embedding_rows=0
    saved_rankings=jsonl("heldout_rankings.jsonl")
    actual=api["rank_queries"](runtime,queries,vectors,routes=(route,))
    difference=_step2318_replay_same_rankings(saved_rankings,actual,config["expected_ranking_replay_rtol"],config["expected_ranking_replay_atol"])
    scoring=score_step2318_heldout(metric_bytes.decode("utf-8"),judgments,actual,config["corpus_unit_ids"],questions,route)
    evaluation=_step2318_replay_decode((folder/"frozen_method_evaluation.json").read_bytes())
    if (evaluation["heldout_scoring"]!=scoring or evaluation["selected_route"]!=route
            or evaluation["selection_freeze_id"]!=old_freeze["selection_freeze_id"]
            or scoring["selected_route"]!=route or scoring["method_selection_performed"] is not False
            or scoring["held_out_used_for_method_selection"] is not False or scoring["held_out_evaluation_complete"] is not True
            or jsonl("heldout_per_query_metrics.jsonl")!=scoring["per_query_metrics"]
            or jsonl("heldout_error_audit.jsonl")!=scoring["error_audit"]):
        raise ValueError("heldout_replay_scoring_or_frozen_method_changed")
    if any(evaluation[k]!=manifest[k] for k in identity_fields):raise ValueError("heldout_replay_evaluation_identity_disagrees")
    _step2318_replay_csv((folder/"heldout_route_metrics.csv").read_bytes(),scoring["route_metrics"])
    _step2318_replay_csv((folder/"heldout_category_metrics.csv").read_bytes(),scoring["category_metrics"])
    handoff=_step2318_replay_decode((folder/"retrieval_handoff.json").read_bytes())
    _step2318_replay_handoff(handoff,config,runtime)
    expected_diagnostics={"query_encoder_processes":0,"query_embedding_rows":0,"ranking_calls":30,
        "lexical_route_calls":30 if route=="lexical" else 0,"semantic_route_calls":30 if route=="semantic" else 0}
    if runtime["diagnostics"]!=expected_diagnostics:raise ValueError("heldout_replay_additional_calls_detected")
    runtime["guard"]()
    if (source_path.read_bytes()!=source_bytes or metric_path.read_bytes()!=metric_bytes or old_freeze_path.read_bytes()!=old_freeze_bytes
            or (folder/manifest_name).read_bytes()!=content
            or any(_step2318_replay_sha(_step2318_replay_path(folder/name).read_bytes())!=digest for name,digest in hashes.items())):
        raise ValueError("heldout_replay_bound_source_or_payload_changed")
    checks=[{"check":name,"status":"pass","observed":str(value)} for name,value in (
        ("trusted_manifest_and_fifteen_payload_hashes_verified",15),
        ("original_development_freeze_verified_before_heldout_ranking",old_freeze["selection_freeze_id"]),
        ("only_thirty_frozen_heldout_query_rows_loaded",30),
        ("saved_query_vector_rows_reused_without_encoder",embedding_rows),
        ("thirty_selected_route_rankings_reproduced_with_complete_companions",30),
        ("cosine_scores_match_with_recorded_tolerances",difference),
        ("heldout_metric_denominators_and_unrounded_values_match",scoring["aggregate"]["ranking_scored_denominator"]),
        ("per_query_route_category_and_error_audit_tables_match",True),
        ("frozen_method_and_all_bound_sources_remain_unchanged",True),
        ("runtime_handoff_excludes_private_evaluation_material",True),
        ("no_query_encoder_neural_model_fit_or_method_selection_calls",0))]
    return {"schema_version":"step23-heldout-replay-report-1","status":"verified_heldout_retrieval_replay",
        **{k:manifest[k] for k in identity_fields},"selection_freeze_id":old_freeze["selection_freeze_id"],
        "manifest_sha256":request["expected_manifest_sha256"],"query_rows":30,"ranking_calls":30,
        "lexical_route_calls":30 if route=="lexical" else 0,"semantic_route_calls":30 if route=="semantic" else 0,
        "additional_model_loads":0,"query_encoder_calls":0,"method_selection_performed":False,"selected_route_unchanged":True,
        "development_queries_retrieved":0,"source_hashes_unchanged":True,"private_evaluation_material_in_runtime_handoff":False,
        "primary_ranking_scores_max_absolute_difference":difference,"ranking_replay_rtol":1e-5,"ranking_replay_atol":1e-6,
        "scoring":scoring,"scoring_sha256":_step2318_replay_sha(_step2318_replay_pack(scoring)),"checks":checks}


def _step2318_replay_write(path,report):
    import os
    target=_step2318_replay_path(path,exists=False)
    if target.exists() or not target.parent.is_dir():raise ValueError("heldout_replay_result_path_exists")
    with target.open("xb") as stream:
        stream.write(_step2318_replay_pack(report));stream.flush();os.fsync(stream.fileno())


if __name__=="__main__":
    import json
    import sys
    request=None
    try:
        request=json.load(sys.stdin)
        report=verify_step2318_heldout_replay(request)
        _step2318_replay_write(request["result_path"],report)
    except Exception as error:
        import re
        message=str(error)
        stage=message if re.fullmatch(r"heldout_replay_[A-Za-z0-9_]{1,100}",message) else "saved_heldout_replay"
        report={"schema_version":"step23-heldout-replay-report-1","status":"failed","stage":stage,"exception_type":type(error).__name__}
        try:
            if type(request) is dict and type(request.get("result_path")) is str:
                _step2318_replay_write(request["result_path"],report)
        except Exception:pass
        print(json.dumps(report,sort_keys=True))
        raise SystemExit(1)


