"""Explicit unit-relevance ranking metrics, separate from complete evidence support."""

STEP2315_CATEGORIES = ("drill_and_resource", "guideline_and_qualification", "unsupported_by_identified_corpus")


def step2315_metric_policy():
    return {"schema_version": "step23-retrieval-metric-policy-1", "cutoff": 5,
        "planned_development_questions": 30, "planned_held_out_questions": 30,
        "planned_category_counts_per_partition": {key: 10 for key in STEP2315_CATEGORIES},
        "query_fields": ["query_id", "split", "category", "judgment_status", "support_status", "relevant_unit_ids", "complete_evidence_sets"],
        "unit_relevance_labels": ["relevant", "not_relevant", "pending"],
        "final_judgment_requirement": "Complete review of the identified corpus, relevance labels, required claims and sufficient evidence sets; IDs alone do not prove semantic review.",
        "support_statuses": {"supported": "At least one reviewed evidence set covers all required claims with the required context.",
            "partially_supported": "Some required claims have support, but no reviewed set supports the full request.",
            "unsupported": "No required claim is supported by the identified corpus; topically relevant units may still exist.",
            "pending": "Support review is unfinished; no metric is assigned."},
        "final_category_consistency": {"positive_categories": "supported with one or more nonempty sufficient evidence sets",
            "unsupported_by_identified_corpus": "partially_supported or unsupported, with no sufficient full-answer evidence set"},
        "recall_at_5": "For a final nonempty relevant-unit set R: |retrieved_top5 intersect R| / |R|.",
        "reciprocal_rank_at_5": "For a final nonempty R: reciprocal of the first relevant rank within top5; zero if there is no hit.",
        "empty_relevant_set": {"recall_at_5": None, "reciprocal_rank_at_5": None,
            "included_in_ranking_selection_denominator": False, "reported_as": "unavailable_empty_relevant_set",
            "automatic_zero_or_perfect_score": False},
        "selection_denominator": "All final development questions with nonempty relevant-unit sets, including unsupported-category questions with partial/topic relevance; identical query IDs for both routes.",
        "pending_failed_missing_outcomes": "Unscored and unavailable; never silently dropped to select a method. Selection requires all30 development judgments and both routes'30 completed outcomes.",
        "empty_completed_ranking": "A completed retrieval returning zero units: Recall and reciprocal rank are zero when R is nonempty.",
        "complete_evidence_set_covered_at_5": "Separate from ranking relevance: available only for supported questions with reviewed sufficient sets and a completed ranking; true if any full set is contained in top5.",
        "partial_or_unsupported_full_evidence_coverage": "Unavailable because no reviewed sufficient full-answer set exists; not automatically zero or perfect.",
        "method_selection_rule": ["higher_development_mean_recall_at_5", "higher_development_mrr_at_5_on_exact_tie", "lexical_on_exact_double_tie"],
        "means_use_unrounded_values": True, "held_out_may_select_method": False,
        "question_families_cannot_cross_partitions": True, "source_disjointness_required": False,
        "result_counts_establish_answerability_or_abstention_accuracy": False,
        "no_answer_or_abstention_prediction_scored_here": True, "semantic_abstention_threshold_adopted": False,
        "ranking_relevance_and_complete_evidence_judgments_separate": True,
        "ranked_evidence_set_coverage_is_not_verified_generation_context_delivery": True,
        "population_counts_and_outcome_counts_may_overlap": True,
        "actual_benchmark_questions_or_judgments_created_by_policy": 0}


def _step2315_ids(value, label, allowed=None):
    if type(value) is not list or any(type(x) is not str or not x.strip() for x in value) or len(set(value)) != len(value):
        raise ValueError("retrieval_metric_invalid_" + label)
    if allowed is not None and not set(value).issubset(allowed):
        raise ValueError("retrieval_metric_unbound_" + label)
    return set(value)


def _step2315_judgment(judgment, corpus):
    required = {"query_id", "split", "category", "judgment_status", "support_status", "relevant_unit_ids", "complete_evidence_sets"}
    if (type(judgment) is not dict or set(judgment) != required or type(judgment["query_id"]) is not str or not judgment["query_id"].strip()
            or judgment["split"] not in ("development", "held_out") or judgment["category"] not in STEP2315_CATEGORIES
            or judgment["judgment_status"] not in ("final", "pending")
            or judgment["support_status"] not in ("supported", "partially_supported", "unsupported", "pending")):
        raise ValueError("retrieval_metric_invalid_judgment")
    relevant = _step2315_ids(judgment["relevant_unit_ids"], "relevant_units", corpus)
    alternatives = judgment["complete_evidence_sets"]
    if type(alternatives) is not list: raise ValueError("retrieval_metric_invalid_evidence_sets")
    complete, seen = [], set()
    for group in alternatives:
        ids = _step2315_ids(group, "complete_evidence_set", corpus)
        if not ids or not ids.issubset(relevant) or frozenset(ids) in seen:
            raise ValueError("retrieval_metric_invalid_complete_evidence_set")
        complete.append(ids); seen.add(frozenset(ids))
    status = judgment["support_status"]
    if judgment["judgment_status"] == "pending":
        if status != "pending": raise ValueError("retrieval_metric_provisional_support_claimed_final")
    else:
        if status == "pending" or (status == "supported" and (not relevant or not complete)):
            raise ValueError("retrieval_metric_final_support_incomplete")
        if status in ("partially_supported", "unsupported") and complete:
            raise ValueError("retrieval_metric_insufficient_support_has_full_evidence_set")
        if status == "partially_supported" and not relevant:
            raise ValueError("retrieval_metric_partial_support_requires_relevant_evidence")
        negative = judgment["category"] == "unsupported_by_identified_corpus"
        if (negative and status == "supported") or (not negative and status != "supported"):
            raise ValueError("retrieval_metric_category_support_inconsistent")
    return relevant, complete


def score_query(judgment, outcome, corpus_unit_ids):
    """Score one reviewed query; flags do not establish answer correctness."""
    corpus = _step2315_ids(corpus_unit_ids, "corpus_units")
    if not corpus: raise ValueError("retrieval_metric_empty_corpus")
    relevant, complete = _step2315_judgment(judgment, corpus)
    if (type(outcome) is not dict or set(outcome) != {"status", "ranked_unit_ids"}
            or outcome["status"] not in ("completed", "failed", "not_run")):
        raise ValueError("retrieval_metric_invalid_outcome")
    found = _step2315_ids(outcome["ranked_unit_ids"], "ranked_units", corpus)
    if len(found) > 5 or (outcome["status"] != "completed" and found):
        raise ValueError("retrieval_metric_invalid_ranked_population")
    available = judgment["judgment_status"] == "final" and outcome["status"] == "completed"
    recall = reciprocal = full_coverage = None
    state = "available"
    if judgment["judgment_status"] != "final": state = "unavailable_pending_judgment"
    elif outcome["status"] != "completed": state = "unavailable_" + outcome["status"]
    elif not relevant: state = "unavailable_empty_relevant_set"
    if available and relevant:
        recall = len(found & relevant) / len(relevant)
        reciprocal = next((1.0 / rank for rank, unit in enumerate(outcome["ranked_unit_ids"], 1) if unit in relevant), 0.0)
    if available and complete:
        full_coverage = any(group.issubset(found) for group in complete)
    return {"query_id": judgment["query_id"], "split": judgment["split"], "category": judgment["category"],
        "judgment_status": judgment["judgment_status"], "support_status": judgment["support_status"],
        "outcome_status": outcome["status"], "ranking_metric_status": state,
        "relevant_unit_count": len(relevant) if judgment["judgment_status"] == "final" else None,
        "returned_unit_count": len(found) if outcome["status"] == "completed" else None,
        "recall_at_5": recall, "reciprocal_rank_at_5": reciprocal,
        "complete_evidence_set_covered_at_5": full_coverage,
        "ranking_establishes_answerability_or_abstention_accuracy": False}


def aggregate_route(judgments, outcomes, corpus_unit_ids):
    import math
    if type(judgments) is not list or type(outcomes) is not dict: raise ValueError("retrieval_metric_invalid_population")
    ids = [j.get("query_id") if type(j) is dict else None for j in judgments]
    if any(type(q) is not str or not q for q in ids) or len(set(ids)) != len(ids) or not set(outcomes).issubset(ids):
        raise ValueError("retrieval_metric_unaligned_outcomes")
    rows = [score_query(j, outcomes.get(j["query_id"], {"status": "not_run", "ranked_unit_ids": []}), corpus_unit_ids) for j in judgments]
    if len({r["split"] for r in rows}) > 1: raise ValueError("retrieval_metric_partition_aggregates_must_remain_separate")
    eligible = [r["query_id"] for r in rows if r["judgment_status"] == "final" and r["relevant_unit_count"] > 0]
    scored = [r for r in rows if r["recall_at_5"] is not None]
    sufficient = [r for r in rows if r["complete_evidence_set_covered_at_5"] is not None]
    complete = bool(rows) and len(outcomes) == len(rows) and all(r["judgment_status"] == "final" and r["outcome_status"] == "completed" for r in rows)
    return {"split": rows[0]["split"] if rows else None, "population_queries": len(rows), "ranking_eligible_query_ids": eligible,
        "ranking_selection_denominator": len(eligible), "ranking_scored_query_ids": [r["query_id"] for r in scored],
        "ranking_scored_denominator": len(scored), "empty_relevant_set_queries": sum(r["judgment_status"] == "final" and r["relevant_unit_count"] == 0 for r in rows),
        "pending_judgment_queries": sum(r["judgment_status"] != "final" for r in rows),
        "completed_outcomes": sum(r["outcome_status"] == "completed" for r in rows),
        "failed_outcomes": sum(r["outcome_status"] == "failed" for r in rows),
        "not_run_outcomes": sum(r["outcome_status"] == "not_run" for r in rows),
        "missing_outcome_query_ids": [q for q in ids if q not in outcomes],
        "mean_recall_at_5": math.fsum(r["recall_at_5"] for r in scored) / len(scored) if scored else None,
        "mrr_at_5": math.fsum(r["reciprocal_rank_at_5"] for r in scored) / len(scored) if scored else None,
        "complete_evidence_scored_denominator": len(sufficient),
        "complete_evidence_set_coverage_rate_at_5": sum(r["complete_evidence_set_covered_at_5"] for r in sufficient) / len(sufficient) if sufficient else None,
        "all_queries_completed_and_judged": complete, "selection_eligible": complete and bool(eligible), "per_query": rows}


def select_retrieval_method(judgments, route_outcomes, corpus_unit_ids):
    from collections import Counter
    if type(judgments) is not list: raise ValueError("retrieval_metric_invalid_development_population")
    if type(route_outcomes) is not dict or not set(route_outcomes).issubset({"lexical", "semantic"}):
        raise ValueError("retrieval_metric_invalid_route_scope")
    if any(type(j) is not dict or j.get("split") != "development" for j in judgments):
        raise ValueError("held_out_questions_cannot_select_retrieval_method")
    results = {route: aggregate_route(judgments, route_outcomes.get(route, {}), corpus_unit_ids) for route in ("lexical", "semantic")}
    expected = len(judgments) == 30 and Counter(j["category"] for j in judgments) == {c: 10 for c in STEP2315_CATEGORIES}
    ready = (expected and all(r["selection_eligible"] for r in results.values())
        and results["lexical"]["ranking_eligible_query_ids"] == results["semantic"]["ranking_eligible_query_ids"])
    chosen, reason = None, "unavailable_incomplete_development_population_or_judgments_or_outcomes"
    if ready:
        left, right = results["lexical"], results["semantic"]
        if left["mean_recall_at_5"] != right["mean_recall_at_5"]:
            chosen = "lexical" if left["mean_recall_at_5"] > right["mean_recall_at_5"] else "semantic"; reason = "higher_development_mean_recall_at_5"
        elif left["mrr_at_5"] != right["mrr_at_5"]:
            chosen = "lexical" if left["mrr_at_5"] > right["mrr_at_5"] else "semantic"; reason = "higher_development_mrr_at_5_on_exact_tie"
        else: chosen, reason = "lexical", "lexical_on_exact_double_tie"
    return {"status": "selected" if ready else "unavailable", "selected_route": chosen, "selection_reason": reason,
        "planned_development_queries": 30, "actual_development_queries": len(judgments),
        "common_ranking_selection_denominator": results["lexical"]["ranking_selection_denominator"] if ready else None,
        "routes": results, "held_out_used_for_selection": False, "unrounded_values_used": True}


def run_step2315_metric_probes():
    import copy
    corpus = ["authored-u" + str(i) for i in range(1, 7)]
    checks = []
    def record(name, condition):
        if condition is not True: raise RuntimeError("step2315_artificial_metric_failed:" + name)
        checks.append({"check": name, "status": "pass", "observed": "authored_metadata_only;no_actual_benchmark_scores"})
    def j(q="authored-q", category="drill_and_resource", support="supported", relevant=None, sets=None):
        return {"query_id": q, "split": "development", "category": category, "judgment_status": "final", "support_status": support,
            "relevant_unit_ids": [corpus[0], corpus[1]] if relevant is None else relevant,
            "complete_evidence_sets": [[corpus[0], corpus[1]]] if sets is None else sets}
    def o(ids=None, status="completed"): return {"status": status, "ranked_unit_ids": [] if ids is None else ids}
    def rejected(name, call):
        try: call()
        except (ValueError, TypeError): record(name, True)
        else: raise RuntimeError("step2315_artificial_metric_failed:" + name)
    r = score_query(j(), o([corpus[2], corpus[0]]), corpus)
    record("unit_recall_and_first_hit_reciprocal_rank_use_separate_denominators", r["recall_at_5"] == 0.5 and r["reciprocal_rank_at_5"] == 0.5 and r["complete_evidence_set_covered_at_5"] is False)
    r = score_query(j(), o(corpus[:2]), corpus)
    record("multi_unit_complete_evidence_set_requires_both_units", r["complete_evidence_set_covered_at_5"] is True)
    r = score_query(j(sets=[[corpus[0]], [corpus[1]]]), o([corpus[1]]), corpus)
    record("alternative_sufficient_evidence_sets_are_disjunctive", r["complete_evidence_set_covered_at_5"] is True)
    r = score_query(j(), o(), corpus)
    record("completed_empty_ranking_is_zero_for_nonempty_gold", r["recall_at_5"] == r["reciprocal_rank_at_5"] == 0.0)
    negative = j(category="unsupported_by_identified_corpus", support="unsupported", relevant=[], sets=[])
    r = score_query(negative, o(corpus[:5]), corpus)
    record("empty_gold_is_unavailable_not_zero_or_perfect", r["recall_at_5"] is r["reciprocal_rank_at_5"] is r["complete_evidence_set_covered_at_5"] is None)
    topical = j(category="unsupported_by_identified_corpus", support="unsupported", relevant=[corpus[0]], sets=[])
    r = score_query(topical, o([corpus[0]]), corpus)
    record("unsupported_can_have_relevance_without_full_answer_support", r["recall_at_5"] == 1.0 and r["complete_evidence_set_covered_at_5"] is None and r["ranking_establishes_answerability_or_abstention_accuracy"] is False)
    partial = j(category="unsupported_by_identified_corpus", support="partially_supported", relevant=[corpus[0]], sets=[])
    record("partial_required_claim_support_remains_distinct", score_query(partial, o(), corpus)["support_status"] == "partially_supported")
    pending = j(); pending.update(judgment_status="pending", support_status="pending")
    record("pending_judgment_is_unscored", score_query(pending, o(corpus[:2]), corpus)["recall_at_5"] is None)
    record("failed_outcome_is_unavailable_not_zero", score_query(j(), o(status="failed"), corpus)["recall_at_5"] is None)
    record("not_run_outcome_is_unavailable_not_zero", score_query(j(), o(status="not_run"), corpus)["recall_at_5"] is None)
    rejected("duplicate_ranked_units_are_rejected", lambda: score_query(j(), o([corpus[0], corpus[0]]), corpus))
    rejected("unbound_ranked_units_are_rejected", lambda: score_query(j(), o(["authored-outside"]), corpus))
    rejected("rankings_over_five_are_rejected", lambda: score_query(j(), o(corpus), corpus))
    rejected("full_evidence_sets_must_be_subsets_of_relevance", lambda: score_query(j(sets=[[corpus[5]]]), o(), corpus))
    rejected("supported_status_requires_a_complete_evidence_set", lambda: score_query(j(sets=[]), o(), corpus))
    rejected("unsupported_category_cannot_claim_complete_support", lambda: score_query(j(category="unsupported_by_identified_corpus"), o(), corpus))
    rejected("positive_categories_require_supported_final_judgments", lambda: score_query(j(support="unsupported", sets=[]), o(), corpus))
    aggregate = aggregate_route([j("authored-a"), j("authored-b", category="unsupported_by_identified_corpus", support="unsupported", relevant=[], sets=[])], {"authored-a": o(corpus[:2]), "authored-b": o(corpus[:5])}, corpus)
    record("empty_gold_excluded_with_population_denominator_retained", aggregate["population_queries"] == 2 and aggregate["ranking_scored_denominator"] == 1 and aggregate["empty_relevant_set_queries"] == 1 and aggregate["mean_recall_at_5"] == 1.0)
    queries = [j("authored-q" + str(i), category=STEP2315_CATEGORIES[i // 10]) if i < 20 else j("authored-q" + str(i), category=STEP2315_CATEGORIES[2], support="unsupported", relevant=[], sets=[]) for i in range(30)]
    outcomes = {q["query_id"]: o(corpus[:2]) for q in queries}
    s = select_retrieval_method(queries, {"lexical": outcomes, "semantic": outcomes}, corpus)
    record("exact_double_tie_selects_lexical_on_twenty_common_nonempty_sets", s["selected_route"] == "lexical" and s["common_ranking_selection_denominator"] == 20)
    semantic = copy.deepcopy(outcomes); lexical = {q["query_id"]: o([corpus[0]]) for q in queries}
    record("higher_unrounded_development_recall_selects_method", select_retrieval_method(queries, {"lexical": lexical, "semantic": semantic}, corpus)["selected_route"] == "semantic")
    lexical = {q["query_id"]: o([corpus[2], *corpus[:2]]) for q in queries}
    record("mrr_breaks_an_exact_recall_tie", select_retrieval_method(queries, {"lexical": lexical, "semantic": semantic}, corpus)["selection_reason"] == "higher_development_mrr_at_5_on_exact_tie")
    missing = copy.deepcopy(outcomes); missing.pop(queries[-1]["query_id"])
    record("even_an_empty_gold_question_requires_a_completed_outcome", select_retrieval_method(queries, {"lexical": missing, "semantic": semantic}, corpus)["selected_route"] is None)
    record("missing_route_cannot_select_a_winner", select_retrieval_method(queries, {"lexical": outcomes}, corpus)["selected_route"] is None)
    failed = copy.deepcopy(outcomes); failed[queries[0]["query_id"]] = o(status="failed")
    record("failed_result_cannot_shrink_selection_denominator", select_retrieval_method(queries, {"lexical": failed, "semantic": semantic}, corpus)["selected_route"] is None)
    held = copy.deepcopy(queries); held[0]["split"] = "held_out"
    rejected("held_out_rows_cannot_select_method", lambda: select_retrieval_method(held, {"lexical": outcomes, "semantic": semantic}, corpus))
    return checks
