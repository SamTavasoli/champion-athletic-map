"""Read-only analysis of the saved Step 23 held-out retrieval adopted by Step 33.

This module never imports the retrieval runtime or executes saved source code.
Primary estimates are copied from the hash-bound saved evaluation, after an
independent arithmetic and ID check. No replacement retrieval is performed.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path


EVALUATION = Path("artifacts/retrieval/evaluation/evaluation_62d4b123570c2ca8")
REVIEW = Path("results/final_case_review/review_cb1efb8523e7c29384d3")
SUMMARY_NAME = "step23_retrieval_evaluation_summary.json"
REQUIRED_PAYLOADS = (
    "heldout_manifest.json", "heldout_evaluation_config.json",
    "heldout_queries.jsonl", "heldout_rankings.jsonl",
    "heldout_per_query_metrics.jsonl", "frozen_method_evaluation.json",
)
METRICS = ("mean_recall_at_5", "mrr_at_5", "complete_evidence_set_coverage_rate_at_5")
CATEGORIES = ("drill_and_resource", "guideline_and_qualification", "unsupported_by_identified_corpus")
SUPPORTS = ("supported", "partially_supported", "unsupported")


class RetrievalEvidenceError(ValueError):
    """A present saved artifact is invalid, unbound, or internally inconsistent."""


def _require(condition, message):
    if not condition:
        raise RetrievalEvidenceError(message)


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _read(root, relative, inputs):
    path = root / relative
    raw = path.read_bytes()
    inputs[relative.as_posix()] = _digest(raw)
    try:
        if path.suffix == ".jsonl":
            return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise RetrievalEvidenceError(f"Invalid JSON: {relative}") from exc


def _bound_read(root, relative, expected, inputs):
    result = _read(root, relative, inputs)
    _require(isinstance(expected, str) and len(expected) == 64,
             f"Missing SHA-256 binding for {relative}")
    _require(inputs[relative.as_posix()] == expected, f"SHA-256 mismatch: {relative}")
    return result


def _index(rows, label):
    _require(type(rows) is list and all(type(row) is dict for row in rows), f"Invalid {label} rows")
    ids = [row.get("query_id") for row in rows]
    _require(all(type(q) is str and q.strip() for q in ids), f"Invalid {label} IDs")
    _require(len(set(ids)) == len(ids), f"Duplicate {label} IDs")
    return dict(zip(ids, rows))


def _ids(value, label, allowed=None):
    _require(type(value) is list and all(type(x) is str and x for x in value), f"Invalid {label}")
    _require(len(set(value)) == len(value), f"Duplicate {label}")
    if allowed is not None:
        _require(set(value).issubset(allowed), f"Unbound {label}")
    return value


def _same(actual, expected, label):
    """Compare JSON values without accepting bools as numeric measurements."""
    if type(expected) is float:
        _require(type(actual) in (float, int) and math.isfinite(actual)
                 and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12),
                 f"Calculation mismatch: {label}: {actual!r} != {expected!r}")
    elif type(expected) is dict:
        _require(type(actual) is dict and set(actual) == set(expected), f"Keys mismatch: {label}")
        for key, value in expected.items():
            _same(actual[key], value, label + "/" + key)
    elif type(expected) is list:
        _require(type(actual) is list and len(actual) == len(expected), f"Length mismatch: {label}")
        for i, (left, right) in enumerate(zip(actual, expected)):
            _same(left, right, f"{label}/{i}")
    else:
        _require(type(actual) is type(expected) and actual == expected, f"Value/type mismatch: {label}")


def _score(judgment, outcome, corpus):
    """Independent implementation of the frozen unit metric arithmetic."""
    _require(judgment.get("split") == "held_out", "Development or unknown judgment split")
    _require(judgment.get("category") in CATEGORIES, "Unknown judgment category")
    _require(judgment.get("judgment_status") == "final", "Held-out judgment is unfinished")
    support = judgment.get("support_status")
    _require(support in SUPPORTS, "Unknown support status")
    relevant = set(_ids(judgment.get("relevant_unit_ids"), "relevant units", corpus))
    sets = judgment.get("complete_evidence_sets")
    _require(type(sets) is list, "Invalid complete evidence sets")
    complete = []
    for group in sets:
        unit_set = set(_ids(group, "complete evidence set", corpus))
        _require(unit_set and unit_set.issubset(relevant), "Invalid sufficient evidence set")
        _require(unit_set not in complete, "Duplicate sufficient evidence set")
        complete.append(unit_set)
    _require((support == "supported") == bool(complete), "Support/evidence-set mismatch")
    _require(support != "partially_supported" or relevant, "Partial support without relevant units")
    _require((judgment["category"] == CATEGORIES[2]) == (support != "supported"),
             "Category/support mismatch")
    _require(type(outcome) is dict and set(outcome) == {"status", "ranked_unit_ids"}, "Invalid outcome fields")
    status = outcome["status"]
    _require(status in ("completed", "failed", "not_run"), "Unknown outcome status")
    ranked = _ids(outcome["ranked_unit_ids"], "ranked units", corpus)
    _require(len(ranked) <= 5 and (status == "completed" or not ranked), "Invalid ranked population")
    available = status == "completed"
    recall = len(set(ranked) & relevant) / len(relevant) if available and relevant else None
    reciprocal = (next((1.0 / i for i, unit in enumerate(ranked, 1) if unit in relevant), 0.0)
                  if available and relevant else None)
    state = ("unavailable_" + status if not available else
             "unavailable_empty_relevant_set" if not relevant else "available")
    return {
        "query_id": judgment["query_id"], "split": "held_out", "category": judgment["category"],
        "judgment_status": "final", "support_status": support, "outcome_status": status,
        "ranking_metric_status": state, "relevant_unit_count": len(relevant),
        "returned_unit_count": len(ranked) if available else None,
        "recall_at_5": recall, "reciprocal_rank_at_5": reciprocal,
        "complete_evidence_set_covered_at_5": any(group.issubset(ranked) for group in complete)
        if available and complete else None,
        "ranking_establishes_answerability_or_abstention_accuracy": False,
    }


def _aggregate(rows):
    scored = [row for row in rows if row["recall_at_5"] is not None]
    sufficient = [row for row in rows if row["complete_evidence_set_covered_at_5"] is not None]
    return {
        "split": "held_out", "population_queries": len(rows),
        "ranking_selection_denominator": sum(row["relevant_unit_count"] > 0 for row in rows),
        "ranking_scored_denominator": len(scored),
        "empty_relevant_set_queries": sum(row["relevant_unit_count"] == 0 for row in rows),
        "pending_judgment_queries": 0,
        "completed_outcomes": sum(row["outcome_status"] == "completed" for row in rows),
        "failed_outcomes": sum(row["outcome_status"] == "failed" for row in rows),
        "not_run_outcomes": sum(row["outcome_status"] == "not_run" for row in rows),
        "mean_recall_at_5": math.fsum(row["recall_at_5"] for row in scored) / len(scored) if scored else None,
        "mrr_at_5": math.fsum(row["reciprocal_rank_at_5"] for row in scored) / len(scored) if scored else None,
        "complete_evidence_scored_denominator": len(sufficient),
        "complete_evidence_set_coverage_rate_at_5": sum(row["complete_evidence_set_covered_at_5"] for row in sufficient) / len(sufficient) if sufficient else None,
        "all_queries_completed_and_judged": all(row["outcome_status"] == "completed" for row in rows),
    }


def _check_aggregate(saved, rows, label, families):
    calculated = _aggregate(rows)
    for key, value in calculated.items():
        _same(saved.get(key), value, label + "/" + key)
    if "question_families" in saved:
        _same(saved["question_families"], families, label + "/question_families")
    _require(saved.get("used_for_method_selection", False) is False, f"Held-out used for method choice: {label}")
    return calculated


def _verify_delivery(item):
    """Check the entire saved delivery, including source qualifications/credit."""
    _require(item.get("required_delivery_must_be_attached") is True
             and item.get("standalone_core_delivery_allowed") is False,
             "Missing required-delivery contract")
    text = item.get("complete_required_delivery_text")
    record = item.get("required_delivery_record")
    _require(type(text) is str and text.strip() and type(record) is dict, "Missing delivered content")
    _same(record.get("reference_unit_id"), item["reference_unit_id"], "delivery unit ID")
    _same(record.get("passage_id"), item.get("passage_id"), "delivery passage ID")
    key = "display_text" if "display_text" in record else "complete_display_text"
    _same(record.get(key), text, "complete delivered bytes")
    _same(record.get(key + "_sha256"), _digest(text.encode("utf-8")), "complete delivery text SHA-256")
    source = record.get("source_delivery_bundle")
    _require(type(source) is dict, "Missing source delivery companion")
    _same(source.get("reference_unit_id"), item["reference_unit_id"], "source companion unit ID")
    _same(source.get("display_text"), text, "source companion delivery bytes")
    expected = record.get("source_delivery_record_sha256", record.get("source_delivery_bundle_record_sha256"))
    # Source bundles were frozen with UTF-8, sorted/indented JSON plus a newline.
    canonical = (json.dumps(source, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _same(expected, _digest(canonical), "source companion record SHA-256")
    context = source.get("required_context")
    if context is not None:
        contexts = [context] if type(context) is str else list(context.values()) if type(context) is dict else None
        _require(contexts is not None, "Invalid required context")
        _require(all(value in text for value in contexts if type(value) is str and value),
                 "Required qualification absent from delivery")
    _require(record.get("required_context_and_usage_credit_are_indivisible", record.get("required_delivery_is_indivisible")) is True,
             "Indivisible delivery contract absent")
    return True


def _summary_rows(saved, question_rows, kind, name):
    rows = []
    base = {"population_kind": kind, "population": name, "split": "held_out",
            "route": saved["route"], "population_questions": len(question_rows),
            "source": "saved_step23_primary_metrics_verified", "calculation_status": "verified"}
    for metric in METRICS:
        evidence = metric == METRICS[2]
        denominator = saved["complete_evidence_scored_denominator" if evidence else "ranking_scored_denominator"]
        source_field = ("complete_evidence_set_covered_at_5" if evidence else
                        "recall_at_5" if metric == METRICS[0] else "reciprocal_rank_at_5")
        values = [row[source_field] for row in question_rows if row[source_field] is not None]
        numerator = sum(values) if evidence else math.fsum(values)
        rows.append({**base, "metric": metric, "value": saved[metric], "numerator": numerator,
                     "numerator_kind": "covered_questions" if evidence else "sum_of_query_scores",
                     "denominator": denominator, "unit": "proportion"})
    for metric, count in (
        ("returned_candidates", sum(row["outcome_status"] == "completed" and row["returned_unit_count"] > 0 for row in question_rows)),
        ("no_match", sum(row["outcome_status"] == "completed" and row["returned_unit_count"] == 0 for row in question_rows)),
        ("execution_error", sum(row["outcome_status"] == "failed" for row in question_rows)),
        ("not_run", sum(row["outcome_status"] == "not_run" for row in question_rows)),
        ("empty_relevant_set", sum(row["relevant_unit_count"] == 0 for row in question_rows)),
    ):
        rows.append({**base, "metric": metric, "value": count / len(question_rows) if question_rows else None,
                     "numerator": count, "numerator_kind": "questions", "denominator": len(question_rows), "unit": "proportion"})
    return rows


def analyze_retrieval(root):
    """Return traceable saved held-out results; absent sources are unavailable.

    ``root`` is the project root containing native ``artifacts/`` and ``results/``.
    Invalid present evidence raises :class:`RetrievalEvidenceError`. Optional
    Step 33 snapshots, when present, must exactly bind the native evaluation.
    """
    root = Path(root).resolve()
    inputs = {}
    limitations = [
        "Saved Step23 ranking is a single-query eleven-unit pilot, distinct from the planner's two-query merged packet.",
        "Frozen relevance/complete-evidence judgments were assistant reviewed; no independent human benchmark review is recorded.",
        "Ranking relevance and returned candidates do not establish answerability, abstention accuracy, or planner evidence use.",
        "Verified delivered companions concern the saved retrieval result; generation prompt inclusion and full model context budget are not established here.",
        "No new retrieval uncertainty procedure, hypothesis test, model call, index replay, or encoding is introduced.",
    ]
    summary_path = EVALUATION / SUMMARY_NAME
    snapshot_summary = REVIEW / "reference_snapshot/retrieval_summary.json"
    if not (root / summary_path).is_file():
        if (root / snapshot_summary).is_file():
            summary_path = snapshot_summary
        else:
            return {"status": "unavailable", "summary": {"reason": "saved_retrieval_summary_missing"},
                    "summary_rows": [], "question_rows": [], "input_sha256": {},
                    "limitations": limitations + ["Native Step23 evaluation summary and Step33 retrieval snapshot are absent."]}
    summary = _read(root, summary_path, inputs)
    _require(type(summary) is dict and summary.get("schema_version") == "step23-heldout-evaluation-producer-1", "Unexpected retrieval summary schema")
    _require(summary.get("heldout_questions") == 30 and type(summary["heldout_questions"]) is int, "Expected thirty held-out retrieval questions")
    _require(summary.get("held_out_used_for_method_selection") is False
             and summary.get("method_selection_performed") is False, "Held-out selection leakage")
    _require(summary.get("heldout_evaluation_verified") is True, "Saved held-out evaluation unverified")
    source_hashes = summary.get("output_hashes")
    _require(type(source_hashes) is dict, "Missing retrieval summary payload bindings")

    step33_verified = False
    review_manifest = REVIEW / "manifest.json"
    if (root / review_manifest).is_file():
        review = _read(root, review_manifest, inputs)
        for native_name, snapshot_name in ((SUMMARY_NAME, "retrieval_summary.json"), ("frozen_method_evaluation.json", "frozen_method_evaluation.json")):
            rel = REVIEW / "reference_snapshot" / snapshot_name
            expected = review.get("files", {}).get("reference_snapshot/" + snapshot_name)
            if not (root / rel).is_file():
                limitations.append(f"Step33 snapshot file unavailable: {rel.as_posix()}")
                continue
            _bound_read(root, rel, expected, inputs)
            if native_name == SUMMARY_NAME:
                _same(inputs[rel.as_posix()], inputs[summary_path.as_posix()], "Step33 adopted summary hash")
            else:
                _same(inputs[rel.as_posix()], source_hashes.get((EVALUATION / native_name).as_posix()), "Step33 adopted frozen evaluation hash")
            native_binding = review.get("source_file_sha256", {}).get((EVALUATION / native_name).as_posix())
            _same(native_binding, expected, "Step33 native source/snapshot hash")
        step33_verified = all((root / (REVIEW / "reference_snapshot" / f)).is_file()
                              for f in ("retrieval_summary.json", "frozen_method_evaluation.json"))
    else:
        limitations.append("Step33 review manifest absent: native Step23 identities can be checked, but Step33 adoption cannot be reverified.")

    missing = [str(EVALUATION / name) for name in REQUIRED_PAYLOADS if not (root / EVALUATION / name).is_file()]
    if missing:
        return {"status": "unavailable", "summary": {"reason": "native_heldout_records_missing", "missing_paths": missing,
                "heldout_questions_reported": summary["heldout_questions"], "reported_route_metrics": summary.get("route_metrics"),
                "step33_adoption_verified": step33_verified}, "summary_rows": [], "question_rows": [],
                "input_sha256": inputs, "limitations": limitations + ["No per-question verification or replacement scores were produced."]}
    data = {name: _bound_read(root, EVALUATION / name, source_hashes.get((EVALUATION / name).as_posix()), inputs)
            for name in REQUIRED_PAYLOADS}
    manifest = data["heldout_manifest.json"]
    for name in REQUIRED_PAYLOADS:
        if name != "heldout_manifest.json":
            _same(manifest.get("payload_hashes", {}).get(name), inputs[(EVALUATION / name).as_posix()], "Heldout manifest binding/" + name)
    config = data["heldout_evaluation_config.json"]
    frozen = data["frozen_method_evaluation.json"]
    route = summary.get("selected_route")
    _require(route in ("semantic", "lexical"), "Unknown selected route")
    for name, obj in (("config", config), ("manifest", manifest), ("frozen", frozen)):
        for key in ("heldout_evaluation_id", "selected_route", "selection_freeze_sha256", "corpus_id", "benchmark_preparation_id"):
            if key == "selection_freeze_sha256" and key not in obj:
                continue
            _same(obj.get(key), summary.get(key), name + "/" + key)
        _require(obj.get("method_selection_performed") is False, "Method selection performed in heldout artifact")
    _require(config.get("ranking_k") == 5 and type(config["ranking_k"]) is int, "Unexpected ranking cutoff")
    _require(frozen.get("selected_route_changed_after_heldout") is False, "Route changed after held-out exposure")
    policy_path = Path(config.get("metric_source_relative_path", "")).parent / "retrieval_metric_policy.json"
    if (root / policy_path).is_file():
        policy = _bound_read(root, policy_path, summary.get("metric_policy_sha256"), inputs)
        _require(policy.get("cutoff") == 5 and policy.get("held_out_may_select_method") is False
                 and policy.get("means_use_unrounded_values") is True,
                 "Unexpected frozen ranking calculation policy")
        _same(policy.get("empty_relevant_set", {}).get("automatic_zero_or_perfect_score"), False,
              "empty relevant set score policy")
    else:
        limitations.append("Separate metric-policy file is absent; arithmetic was checked against the hash-bound saved config, metrics and heldout scoring.")
    selection_path = Path(config.get("selection_freeze_relative_path", ""))
    selection = None
    if (root / selection_path).is_file():
        selection = _bound_read(root, selection_path, config.get("selection_freeze_sha256"), inputs)
        _same(selection.get("selected_route"), route, "development-selected route")
        _same(selection.get("held_out_queries_used_for_selection"), 0, "held-out queries used for selection")
        _same(selection.get("selection", {}).get("held_out_used_for_selection"), False, "method choice split")
    else:
        limitations.append("Separate development method-freeze file is absent; adopted selection identity remains bound by the saved heldout config.")
    scoring = frozen.get("heldout_scoring")
    _require(type(scoring) is dict and scoring.get("held_out_used_for_method_selection") is False,
             "Missing held-out scoring or selection leakage")
    _require(scoring.get("replicated_verification_rankings_added_to_metric_denominators") is False,
             "Replays added to held-out denominator")
    questions = _index(config.get("heldout_questions"), "frozen questions")
    judgments = _index(config.get("heldout_metric_judgments"), "frozen judgments")
    queries = _index(data["heldout_queries.jsonl"], "executed queries")
    metrics = _index(data["heldout_per_query_metrics.jsonl"], "saved metrics")
    rankings = _index(data["heldout_rankings.jsonl"], "saved rankings")
    frozen_metrics = _index(scoring.get("per_query_metrics"), "frozen metrics")
    _require(len(questions) == 30, "Frozen held-out question count differs from thirty")
    if selection is not None:
        for development in selection.get("selection", {}).get("routes", {}).values():
            development_ids = {row.get("query_id") for row in development.get("per_query", [])}
            _require(not (set(questions) & development_ids), "Development queries overlap held-out queries")
    for label, index in (("judgments", judgments), ("queries", queries), ("metrics", metrics), ("rankings", rankings), ("frozen metrics", frozen_metrics)):
        _require(set(index) == set(questions), "Unaligned held-out " + label)
    _require(type(scoring.get("outcomes")) is dict and set(scoring["outcomes"]) == set(questions), "Unaligned frozen outcomes")
    corpus = set(_ids(config.get("corpus_unit_ids"), "corpus units"))
    _require(bool(corpus), "Empty retrieval corpus")
    _same(len(corpus), summary.get("reference_units"), "reference unit count")
    _require(Counter(q.get("category") for q in questions.values()) == {c: 10 for c in CATEGORIES}, "Held-out category population mismatch")
    _require(len({q.get("question_id") for q in questions.values()}) == 30, "Duplicate/missing question IDs")
    _require(sorted(q.get("partition_ordinal") for q in questions.values()) == list(range(1, 31)), "Invalid held-out ordinals")

    question_rows = []
    for query_id, question in sorted(questions.items(), key=lambda pair: pair[1]["partition_ordinal"]):
        judgment, metric, ranking = judgments[query_id], metrics[query_id], rankings[query_id]
        _require(question.get("split") == "held_out", "Development question in held-out population")
        _require(type(question.get("question_family_id")) is str and question["question_family_id"], "Missing question family")
        for key in ("text", "text_sha256"):
            _same(queries[query_id].get(key), question.get(key), "query text identity/" + key)
        _same(_digest(question["text"].encode("utf-8")), question["text_sha256"], "query text SHA-256")
        _same(judgment["category"], question["category"], "question/judgment category")
        for key in ("question_id", "question_family_id", "partition_ordinal", "route"):
            _same(metric.get(key), route if key == "route" else question[key], "saved metric identity/" + key)
        _same(ranking.get("route"), route, "ranking route")
        result = ranking.get("result")
        _require(type(result) is dict and result.get("route") == route, "Invalid ranking result")
        _same(result.get("requested_k"), 5, "requested ranking cutoff")
        items = result.get("results")
        _require(type(items) is list and all(type(item) is dict for item in items), "Invalid ranked items")
        ranked_ids = _ids([item.get("reference_unit_id") for item in items], "delivered ranked IDs", corpus)
        _same(result.get("returned_distinct_reference_units"), len(ranked_ids), "returned distinct units")
        _same(metric.get("ranked_unit_ids"), ranked_ids, "ranked IDs/metric alignment")
        status = result.get("status")
        if status in ("ranked", "no_match"):
            outcome_status = "completed"
            _require((status == "ranked") == bool(items), "Ranking status/results mismatch")
        elif status in ("error", "failed"):
            outcome_status = "failed"
        elif status == "not_run":
            outcome_status = "not_run"
        else:
            raise RetrievalEvidenceError("Unknown native retrieval status: " + repr(status))
        outcome = {"status": outcome_status, "ranked_unit_ids": ranked_ids}
        _same(scoring["outcomes"][query_id], outcome, "frozen outcome")
        checked = _score(judgment, outcome, corpus)
        for key, value in checked.items():
            _same(metric.get(key), value, "per-query arithmetic/" + query_id + "/" + key)
        _same(metric, frozen_metrics[query_id], "per-query saved/frozen metric")
        _same(metric.get("relevant_unit_ids"), judgment["relevant_unit_ids"], "frozen relevance IDs")
        _same(metric.get("missing_relevant_unit_ids_at_5"), sorted(set(judgment["relevant_unit_ids"]) - set(ranked_ids)), "missing relevant IDs")
        for rank, item in enumerate(items, 1):
            _same(item.get("rank"), rank, "saved item rank")
            _require(type(item.get("score")) in (int, float) and math.isfinite(item["score"]), "Invalid ranking score")
            _verify_delivery(item)
        covered_delivery = (any(set(group).issubset(ranked_ids) for group in judgment["complete_evidence_sets"])
                            if outcome_status == "completed" and judgment["complete_evidence_sets"] else None)
        question_rows.append({**metric, "complete_evidence_sets": judgment["complete_evidence_sets"],
                              "complete_required_delivery_verified": outcome_status == "completed",
                              "delivered_complete_evidence_set_covered_at_5": covered_delivery,
                              "generation_prompt_delivery_verified": False,
                              "source_rankings_path": (EVALUATION / "heldout_rankings.jsonl").as_posix(),
                              "source_metrics_path": (EVALUATION / "heldout_per_query_metrics.jsonl").as_posix(),
                              "calculation_status": "verified"})
    families = len({row["question_family_id"] for row in question_rows})
    _same(families, summary.get("heldout_families"), "held-out family count")
    _same(families, 15, "expected held-out families")
    aggregate = _check_aggregate(scoring.get("aggregate", {}), question_rows, "heldout aggregate", families)
    _same(set(scoring["aggregate"].get("ranking_eligible_query_ids", [])),
          set(row["query_id"] for row in question_rows if row["relevant_unit_count"]), "eligible query IDs")
    _same(set(scoring["aggregate"].get("ranking_scored_query_ids", [])),
          set(row["query_id"] for row in question_rows if row["recall_at_5"] is not None), "scored query IDs")
    _same(aggregate["ranking_selection_denominator"], summary.get("ranking_eligible_questions"), "summary eligible denominator")
    _same(aggregate["empty_relevant_set_queries"], summary.get("empty_relevant_sets"), "summary empty relevance count")
    _same(aggregate["complete_evidence_scored_denominator"], summary.get("supported_coverage_denominator"), "summary coverage denominator")
    summary_rows = []
    for kind, saved_rows, field, names in (
        ("all_heldout", summary.get("route_metrics"), None, ["all"]),
        ("support_status", summary.get("support_metrics"), "support_status", SUPPORTS),
        ("category", summary.get("category_metrics"), "category", CATEGORIES),
    ):
        _require(type(saved_rows) is list and len(saved_rows) == len(names), "Missing saved " + kind + " metrics")
        _same(scoring.get("route_metrics" if field is None else "support_metrics" if field == "support_status" else "category_metrics"), saved_rows,
              "summary/frozen " + kind + " metrics")
        for name in names:
            matches = [row for row in saved_rows if field is None or row.get(field) == name]
            _require(len(matches) == 1, "Duplicate/missing saved population " + name)
            saved = matches[0]
            _same(saved.get("route"), route, "summary selected route")
            subset = [row for row in question_rows if field is None or row[field] == name]
            _check_aggregate(saved, subset, kind + "/" + name, len({row["question_family_id"] for row in subset}))
            summary_rows.extend(_summary_rows(saved, subset, kind, name))
    counts = dict(Counter(row["support_status"] for row in question_rows))
    limitations.append("Original Step35 prose planned 20 answerable/10 unsupported questions. The frozen source actually has "
                       f"{counts.get('supported', 0)} supported, {counts.get('partially_supported', 0)} partially supported and "
                       f"{counts.get('unsupported', 0)} unsupported; its saved ranking denominator is "
                       f"{aggregate['ranking_scored_denominator']} and empty relevance count is {aggregate['empty_relevant_set_queries']}. "
                       "Saved primary metrics and denominators are preserved; support/category slices are explicitly labeled.")
    return {"status": "verified" if step33_verified else "verified_native_step23_adoption_unavailable",
            "summary": {"heldout_evaluation_id": summary["heldout_evaluation_id"], "selected_route": route,
                        "heldout_questions": len(question_rows), "question_families": families,
                        "support_status_counts": counts, "ranking_scored_denominator": aggregate["ranking_scored_denominator"],
                        "empty_relevant_sets": aggregate["empty_relevant_set_queries"],
                        "supported_coverage_denominator": aggregate["complete_evidence_scored_denominator"],
                        "reported_route_metrics": summary["route_metrics"], "step33_adoption_verified": step33_verified,
                        "delivered_required_companions_verified": True, "generation_prompt_delivery_verified": False,
                        "original_step35_planned_answerable": 20, "original_step35_planned_unsupported": 10,
                        "protocol_population_discrepancy": aggregate["ranking_scored_denominator"] != 20 or counts.get("unsupported") != 10,
                        "primary_metrics_preserved": True, "new_queries_or_encodings": 0},
            "summary_rows": summary_rows, "question_rows": question_rows,
            "input_sha256": inputs, "limitations": limitations}
