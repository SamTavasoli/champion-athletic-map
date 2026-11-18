"""Pure validation and paired agreement summaries for a fixed human-review rubric."""

import math

VERSION = "human-review-metrics-1"
DIMENSIONS = (
    "response_suitability", "profile_fit", "practicality_completeness",
    "evidence_accuracy", "clarity",
)
_REQUIRED = {"response_id", "reviewer_id", "dimension", "rating_status",
             "score", "comment", "not_applicable_reason"}
_STATUSES = ("rated", "not_applicable", "missing")


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonblank text.")
    return value


def _dimension(value):
    if not isinstance(value, str) or value not in DIMENSIONS:
        raise ValueError("Invalid review dimension.")
    return value


def _ids(values):
    if not isinstance(values, list):
        raise ValueError("Expected an identifier list.")
    result = [_text(value) for value in values]
    if len(set(result)) != len(result):
        raise ValueError("Expected unique identifiers.")
    return result


def validate_rating_entry(entry):
    """Validate supplied fields without inserting defaults or changing source values."""
    if (not isinstance(entry, dict) or not _REQUIRED.issubset(entry)
            or not set(entry).issubset(_REQUIRED | {"evidence_refs"})):
        raise ValueError("Invalid review entry fields.")
    _text(entry["response_id"])
    _text(entry["reviewer_id"])
    _dimension(entry["dimension"])
    if entry["comment"] is not None:
        _text(entry["comment"])
    if "evidence_refs" in entry:
        if not isinstance(entry["evidence_refs"], list):
            raise ValueError("Expected evidence references as a list.")
        for reference in entry["evidence_refs"]:
            _text(reference)
    status, score, reason = entry["rating_status"], entry["score"], entry["not_applicable_reason"]
    if not isinstance(status, str) or status not in _STATUSES:
        raise ValueError("Invalid rating status.")
    if status == "rated":
        if (type(score) not in (int, float) or score not in (0, 1, 2)
                or not math.isfinite(score) or reason is not None):
            raise ValueError("Rated entries require an integer score from zero through two.")
    elif status == "not_applicable":
        if entry["dimension"] != "evidence_accuracy" or score is not None:
            raise ValueError("Non-applicability is restricted to evidence accuracy without a score.")
        _text(reason)
    elif score is not None or reason is not None:
        raise ValueError("Missing ratings require no score or non-applicability reason.")
    return True


def summarize_reviewer_agreement(records, response_ids, reviewer_ids, dimension):
    """Pair by response ID; use only joint numeric pairs for weighted kappa."""
    roster, reviewers = _ids(response_ids), _ids(reviewer_ids)
    _dimension(dimension)
    if len(reviewers) != 2 or not isinstance(records, list):
        raise ValueError("Expected two reviewers and a review-entry list.")
    response_set, reviewer_set, entries = set(roster), set(reviewers), {}
    for entry in records:
        validate_rating_entry(entry)
        if (entry["dimension"] != dimension or entry["response_id"] not in response_set
                or entry["reviewer_id"] not in reviewer_set):
            raise ValueError("Review entry falls outside the declared comparison roster or dimension.")
        key = (entry["response_id"], entry["reviewer_id"])
        if key in entries:
            raise ValueError("Duplicate response and reviewer pair.")
        entries[key] = entry
    per_reviewer = {reviewer: {"status_counts": dict.fromkeys(_STATUSES, 0),
        "numeric_score_counts": dict.fromkeys(("0", "1", "2"), 0),
        "not_recorded": 0, "recorded_missing": 0} for reviewer in reviewers}
    states = dict.fromkeys(("both_not_applicable", "one_reviewer_not_applicable",
        "na_with_numeric_peer", "na_with_missing_peer", "pairs_with_missing", "missing_rating_entries"), 0)
    status_crosstab = {row: dict.fromkeys(_STATUSES, 0) for row in _STATUSES}
    confusion = [[0, 0, 0] for _ in range(3)]
    for response_id in roster:
        pair, scores = [], []
        for reviewer in reviewers:
            entry = entries.get((response_id, reviewer))
            status = entry["rating_status"] if entry is not None else "missing"
            counts = per_reviewer[reviewer]
            counts["status_counts"][status] += 1
            counts["not_recorded"] += int(entry is None)
            counts["recorded_missing"] += int(entry is not None and status == "missing")
            score = int(entry["score"]) if status == "rated" else None
            if score is not None:
                counts["numeric_score_counts"][str(score)] += 1
            pair.append(status)
            scores.append(score)
        status_crosstab[pair[0]][pair[1]] += 1
        na_count, missing_count = pair.count("not_applicable"), pair.count("missing")
        states["both_not_applicable"] += int(na_count == 2)
        states["one_reviewer_not_applicable"] += int(na_count == 1)
        states["na_with_numeric_peer"] += int(na_count == 1 and "rated" in pair)
        states["na_with_missing_peer"] += int(na_count == 1 and missing_count == 1)
        states["pairs_with_missing"] += int(missing_count > 0)
        states["missing_rating_entries"] += missing_count
        if pair == ["rated", "rated"]:
            confusion[scores[0]][scores[1]] += 1
    rows = [sum(row) for row in confusion]
    columns = [sum(row[j] for row in confusion) for j in range(3)]
    n_joint = sum(rows)
    exact = sum(confusion[i][i] for i in range(3))
    observed = expected = kappa = None
    unavailable = "no_joint_numeric_ratings"
    if n_joint:
        observed = sum(confusion[i][j] * abs(i - j) for i in range(3) for j in range(3)) / (2 * n_joint)
        expected = sum(rows[i] * columns[j] * abs(i - j) for i in range(3) for j in range(3)) / (2 * n_joint**2)
        unavailable = "zero_expected_disagreement" if expected == 0 else None
        if expected:
            kappa = 1 - observed / expected
    return {"version": VERSION, "dimension": dimension, "reviewer_order": list(reviewers),
        "score_order": [0, 1, 2], "n_expected_responses": len(roster),
        "n_joint_numeric": n_joint, "n_exact_matches": exact,
        "exact_agreement": exact / n_joint if n_joint else None,
        "joint_numeric_confusion": confusion, "observed_linear_disagreement": observed,
        "expected_linear_disagreement": expected, "linear_weighted_kappa": kappa,
        "kappa_unavailable_reason": unavailable, "state_counts": states,
        "status_crosstab": status_crosstab,
        "per_reviewer": per_reviewer,
        "joint_numeric_marginals": {reviewers[0]: dict(zip(("0", "1", "2"), rows)),
                                    reviewers[1]: dict(zip(("0", "1", "2"), columns))},
        "state_count_note": "State counts overlap; one-reviewer NA can also have a missing peer. "
            "Missing counts include recorded-missing and not-recorded roster slots; not_recorded is separate. "
            "Per-reviewer score counts include all numeric ratings; agreement uses only joint numeric pairs."}
