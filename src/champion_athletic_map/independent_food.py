"""Assess food-answer coverage, recorded numbers and supplied attribution separately."""

from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re


VERSION = "independent-food-assessment-1"
CHECK_IDS = ("food_answer_completeness", "food_numeric_correctness", "food_source_grounding")
NUM = r"-?[0-9]+(?:\.[0-9]+)?"
UNITS = {"g": "G", "gram": "G", "grams": "G", "kcal": "KCAL", "kilocalorie": "KCAL", "kilocalories": "KCAL"}
# This assessor-side alias is tied to the exact frozen food identity, never a model declaration.
REVIEWED_ALIASES = {("167762", "strawberries, raw"): ("raw strawberries",)}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _normal(value):
    return " ".join(str(value).casefold().split())


def _decimal(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _rows(packet):
    values = ((packet or {}).get("payload") or {}).get("food_lookup") or []
    return [row for row in values if isinstance(row, dict) and row.get("status") == "found"
        and isinstance(row.get("data"), dict) and isinstance(row["data"].get("description"), str)]


def _names(data):
    description = data["description"]
    key = (str(data.get("food_id")), _normal(description))
    return (description, *REVIEWED_ALIASES.get(key, ()))


def _target(public, lookups):
    question = public.get("food_question")
    if not isinstance(question, str) or not question.strip():
        return None
    # Both literal quote styles have occurred in the fictional preparation records.
    text = question.replace('\\"', '"')
    match = re.fullmatch(r'For the food "([^"\r\n]+)", how many (grams of protein|kilocalories of energy) are recorded for (' + NUM + r') g\?', text)
    if match is None:
        return None
    grams = _decimal(match[3])
    if grams is None or grams <= 0:
        return None
    descriptions = {row["data"]["description"] for row in lookups
        if any(_normal(name) == _normal(match[1]) for name in _names(row["data"]))}
    return {"food_description": next(iter(descriptions)) if len(descriptions) == 1 else match[1], "grams": grams,
        "nutrient": "protein" if match[2] == "grams of protein" else "energy"}


def _text_items(response):
    """Read explicit fact statements and explanatory text; preserve attribution context."""
    if not isinstance(response, dict):
        return []
    items = []
    if isinstance(response.get("explanation"), str) and response["explanation"].strip():
        items.append({"path": "/explanation", "text": response["explanation"], "food_id": None, "source_ref": None})
    for index, fact in enumerate(response.get("food_facts") or []):
        if isinstance(fact, dict) and isinstance(fact.get("statement"), str) and fact["statement"].strip():
            items.append({"path": "/food_facts/" + str(index) + "/statement", "text": fact["statement"],
                "food_id": fact.get("food_id"), "source_ref": fact.get("source_ref")})
    def other_text(value, path=""):
        if isinstance(value, dict):
            for key, item in value.items():
                if (path == "" and key in ("explanation", "food_facts")) or key in ("food_id", "source_ref", "evidence_refs"):
                    continue
                other_text(item, path + "/" + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                other_text(item, path + "/" + str(index))
        elif isinstance(value, str) and value.strip():
            items.append({"path": path, "text": value, "food_id": None, "source_ref": None})
    other_text(response)
    return items


def _food_material(text, lookups):
    return bool(re.search(r"\b(?:food|protein|nutrient|calories?|kilocalories?|kcal)\b", text, re.I)
        or any(_normal(name) in _normal(text) for row in lookups for name in _names(row["data"])))


def _parse(text, lookups):
    claims = []
    text = text.strip()
    if re.search(r"\b(?:about|approximately|approx|around|roughly|rounded)\b|[~≈]", text, re.I):
        return []
    for row in lookups:
        data = row["data"]
        for name in _names(data):
            food = re.escape(name)
            forms = [
                r"(?P<grams>" + NUM + r")\s*(?:g|grams?)\s+(?:of\s+)?" + food + r"\s*(?:contains|has|provides|—|:)\s*(?P<amount>" + NUM + r")\s*(?P<unit>g|grams?|kcal|kilocalories?)\s+(?P<nutrient>[^.;\n]+)",
                r"(?P<nutrient>[^.;\n]+?)\s+in\s+(?P<grams>" + NUM + r")\s*(?:g|grams?)\s+(?:of\s+)?" + food + r"\s*(?:is|:|=)\s*(?P<amount>" + NUM + r")\s*(?P<unit>g|grams?|kcal|kilocalories?)",
                food + r"\s*(?:contains|has|provides)\s*(?P<amount>" + NUM + r")\s*(?P<unit>g|grams?|kcal|kilocalories?)\s+(?P<nutrient>[^.;\n]+?)\s+per\s+(?P<grams>" + NUM + r")\s*(?:g|grams?)",
            ]
            for pattern in forms:
                match = re.fullmatch(r"\s*(?:" + pattern + r")\s*\.?\s*", text, re.I)
                if match:
                    claims.append({"food_id": str(data.get("food_id")), "food_description": data["description"],
                        "grams": match["grams"], "amount": match["amount"], "unit": UNITS[match["unit"].casefold()],
                        "nutrient": match["nutrient"].strip(), "lookup": row})
    unique = {}
    for claim in claims:
        key = canonical({key: value for key, value in claim.items() if key != "lookup"})
        if key in unique and canonical(unique[key]["lookup"]["data"]) != canonical(claim["lookup"]["data"]):
            unique[key]["ambiguous_truth"] = True
        else:
            unique.setdefault(key, claim)
    return list(unique.values())


def _compare(claim):
    if claim.get("ambiguous_truth"):
        return "unknown", "More than one distinct frozen food record matches this numeric identity.", None
    data = claim["lookup"]["data"]
    candidates = [row for row in data.get("nutrients", []) if isinstance(row, dict)
        and _normal(row.get("nutrient_name")) == _normal(claim["nutrient"]) and row.get("status") == "available"]
    if len(candidates) != 1:
        return "unknown", "The claimed nutrient does not have one available frozen reference value.", None
    source = candidates[0]
    grams, amount, base_grams, base_amount = map(_decimal, (claim["grams"], claim["amount"], data.get("grams"), source.get("amount")))
    if any(value is None for value in (grams, amount, base_grams, base_amount)) or base_grams <= 0:
        return "unknown", "A reference quantity or numeric value cannot be compared as a finite decimal.", None
    observed = {"claimed_grams": str(grams), "claimed_amount": str(amount), "claimed_unit": claim["unit"],
        "source_grams": str(base_grams), "source_amount": str(base_amount), "source_unit": source.get("unit"),
        "comparison": "exact_decimal_cross_multiplication_no_undeclared_rounding"}
    with localcontext() as context:
        context.prec = max(28, len(amount.as_tuple().digits) + len(base_grams.as_tuple().digits),
            len(base_amount.as_tuple().digits) + len(grams.as_tuple().digits)) + 2
        values_equal = amount * base_grams == base_amount * grams
    if grams <= 0 or amount < 0 or claim["unit"] != str(source.get("unit")).upper() or not values_equal:
        return "violated", "The recognized claim changes the recorded quantity-scaled value or nutrient unit.", observed
    return "met", "The recognized numeric claim agrees exactly with the frozen quantity-scaled value and unit.", observed


def assess_food(public_input, response, reference_packet):
    """Use the same assessment-side food truth for every planner version."""
    lookups = _rows(reference_packet)
    required = isinstance(public_input.get("food_question"), str) and bool(public_input["food_question"].strip())
    target = _target(public_input, lookups)
    items, claims, unsupported = _text_items(response), [], []
    food_material = False
    for item in items:
        for segment in re.split(r"(?<=[.!?])\s+|\n+", item["text"]):
            if not segment.strip():
                continue
            quantified = bool(re.search(NUM + r"\s*(?:g|grams?|kcal|kilocalories?)\b", segment, re.I))
            material = item["path"].startswith("/food_facts/") or _food_material(segment, lookups) or required and quantified
            food_material = food_material or material
            parsed = _parse(segment, lookups)
            if len(parsed) == 1:
                claims.append({**parsed[0], "statement": segment, "path": item["path"],
                    "declared_food_id": item["food_id"], "declared_source_ref": item["source_ref"]})
            elif material and (quantified or len(parsed) > 1):
                unsupported.append({"path": item["path"], "text": segment, "reason": "unverified_or_ambiguous_numeric_wording"})
    truth_sha = hashlib.sha256(canonical(lookups).encode("utf-8")).hexdigest()
    def record(identifier, status, reason, observed, is_required):
        return {"check_id": identifier, "status": status, "reason": reason, "observed": observed,
            "required": is_required, "version": VERSION, "assessment_food_truth_sha256": truth_sha}
    complete_observed = {"question_present": required, "question_grammar_supported": target is not None,
        "recognized_claim_count": len(claims), "unsupported_numeric_segments": unsupported}
    if not required:
        complete_status, complete_reason = "not_applicable", "No explicit food question requires an answer."
    elif target is None:
        complete_status, complete_reason = "unknown", "The public food question is outside this assessor's declared literal question grammar."
    elif any(_normal(claim["food_description"]) == _normal(target["food_description"])
            and _normal(claim["nutrient"]) == target["nutrient"] and _decimal(claim["grams"]) == target["grams"] for claim in claims):
        complete_status, complete_reason = "met", "A recognized claim answers the requested food, nutrient and quantity; numeric accuracy is assessed separately."
    elif unsupported or food_material and not claims:
        complete_status, complete_reason = "unknown", "Food-related wording exists, but answer completeness cannot be established under the declared grammar."
    else:
        complete_status, complete_reason = "violated", "The response omits a recognized answer to the requested food, nutrient and quantity."
    completeness = record(CHECK_IDS[0], complete_status, complete_reason, complete_observed, required)
    comparisons = []
    for claim in claims:
        status, reason, observed = _compare(claim)
        comparisons.append({"status": status, "reason": reason, "statement": claim["statement"], "path": claim["path"], "comparison": observed})
    numeric_needed = required or bool(claims) or bool(unsupported)
    statuses = [row["status"] for row in comparisons]
    if "violated" in statuses:
        numeric_status, numeric_reason = "violated", "At least one recognized numeric food claim disagrees with the frozen facts."
    elif unsupported or not claims and numeric_needed or "unknown" in statuses:
        numeric_status, numeric_reason = "unknown", "No complete supported numeric comparison covers every potentially numeric food claim."
    elif claims:
        numeric_status, numeric_reason = "met", "All recognized numeric food claims agree with the assessment-side frozen facts."
    else:
        numeric_status, numeric_reason = "not_applicable", "No food question or numeric food claim requires comparison."
    numeric = record(CHECK_IDS[1], numeric_status, numeric_reason,
        {"comparisons": comparisons, "unsupported_numeric_segments": unsupported,
         "citation_ids_required_for_numeric_correctness": False}, numeric_needed)
    supplied, grounding_issues, supported, resolved = [], [], 0, 0
    attribution_conflict = False
    response_refs = (response.get("evidence_refs") or []) if isinstance(response, dict) else []
    response_refs = [value for value in response_refs if isinstance(value, str)]
    known_refs = {}
    for lookup in lookups:
        for source_ref in lookup.get("source_refs") or []:
            known_refs.setdefault(source_ref, set()).add(str(lookup["data"].get("food_id")))
    for claim in claims:
        given_id, source_ref = claim["declared_food_id"], claim["declared_source_ref"]
        attribution_path = claim["path"]
        matching_refs = set(response_refs) & set(claim["lookup"].get("source_refs") or [])
        if source_ref is None and len(matching_refs) == 1:
            source_ref = next(iter(matching_refs))
            attribution_path = "/evidence_refs"
        if given_id is None and source_ref is None:
            continue
        supplied.append({"path": attribution_path, "food_id": given_id, "source_ref": source_ref})
        if given_id is not None and str(given_id) != claim["food_id"]:
            grounding_issues.append("A supplied food ID differs from the recognized food's frozen identity.")
            attribution_conflict = True
        elif source_ref is None:
            grounding_issues.append("A food ID alone does not provide an explicit source reference.")
        elif source_ref not in (claim["lookup"].get("source_refs") or []):
            if source_ref in known_refs:
                grounding_issues.append("A supplied food reference identifies another frozen food record.")
                attribution_conflict = True
            else:
                grounding_issues.append("A supplied source reference is outside the frozen food evidence.")
        else:
            resolved += 1
            compared, _, _ = _compare(claim)
            if compared == "met":
                supported += 1
            elif compared == "violated":
                attribution_conflict = True
                grounding_issues.append("The supplied frozen source contradicts the recognized numeric claim.")
            else:
                grounding_issues.append("The source identity resolves, but its support for this numeric claim remains unknown.")
    recognized_paths = {claim["path"] for claim in claims}
    for item in items:
        if item["path"] not in recognized_paths and (item["food_id"] is not None or item["source_ref"] is not None):
            supplied.append({"path": item["path"], "food_id": item["food_id"], "source_ref": item["source_ref"]})
            grounding_issues.append("A supplied food attribution appears in wording outside the verified numeric grammar.")
    if not supplied:
        grounding_status, grounding_reason = "not_applicable", "No recognized food claim supplies an explicit identity/source attribution to assess."
    elif attribution_conflict:
        grounding_status, grounding_reason = "violated", "At least one supplied food attribution conflicts with the frozen record."
    elif grounding_issues or unsupported:
        grounding_status, grounding_reason = "unknown", "The supplied attribution does not establish complete source support."
    else:
        grounding_status, grounding_reason = "met", "All supplied food attributions resolve to their recognized frozen food records."
    grounding = record(CHECK_IDS[2], grounding_status, grounding_reason,
        {"supplied_attributions": supplied, "issues": grounding_issues, "recognized_numeric_claims": len(claims),
         "source_identity_resolved_claims": resolved, "source_supported_claims": supported,
         "unparsed_potential_numeric_segments": len(unsupported),
         "all_recognized_numeric_claims_supported": bool(claims) and not unsupported and supported == len(claims),
         "attribution_presence": "present" if supplied else "unassigned_response_references" if response_refs else "absent",
         "unattributed_recognized_claims": max(0, len(claims) - sum(item["path"] in recognized_paths or item["path"] == "/evidence_refs" for item in supplied)),
         "scope": "validity_of_supplied_grounding_claims; N/A_does_not_mean_full_attribution_coverage"}, False)
    return [completeness, numeric, grounding]
