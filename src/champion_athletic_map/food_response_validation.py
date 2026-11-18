"""Validate a small declared food-claim grammar without changing model replies.

Numeric agreement anywhere in a reply is distinct from answering in the required
food_facts field. Unsupported assertions stay unknown; questions and food/mass
headings are not numeric assertions. This is not a general prose truth judge.
"""

from copy import deepcopy
from decimal import Decimal, DecimalException, InvalidOperation, localcontext
import re
import unicodedata


VERSION = "field-specific-food-response-validation-1"
CHECK_IDS = ("food_answer_completeness", "food_numeric_correctness", "food_source_grounding")
NUM = r"-?[0-9]+(?:\.[0-9]+)?"
ASSERTED_NUMBER = (r"(?:" + NUM + r"|NaN|[+-]?Inf(?:inity)?|zero|one|two|three|four|five|six|seven|eight|nine|ten|half|quarter|unknown)")
MASS = r"(?:g|grams?)"
UNIT = r"(?:kilocalories?|milligrams?|calories?|grams?|kcal|mg|cal|g)"
UNITS = {"g": "G", "gram": "G", "grams": "G", "mg": "MG", "milligram": "MG", "milligrams": "MG",
         "kcal": "KCAL", "kilocalorie": "KCAL", "kilocalories": "KCAL", "cal": "CAL", "calorie": "CAL", "calories": "CAL"}
QUOTES = str.maketrans({"'": '"', "\u2018": '"', "\u2019": '"', "\u201c": '"', "\u201d": '"'})
QUESTION = re.compile(r'For the food "([^"\r\n]+)", how many (grams of protein|kilocalories of energy) '
                      r'are recorded for (' + NUM + r') g\?')
PREFIX = re.compile(r"(?:the food facts array includes the requested information,\s*stating that\s*|"
                    r"(?:the (?:supplied |recorded )?(?:food )?reference|the supplied data)\s+(?:states|records|reports)\s+that\s*|"
                    r"according to the (?:supplied |recorded )?(?:food )?reference,\s*)?", re.I)
HEDGE = re.compile(r"\b(?:approximately|approx|about|around|roughly|probably|maybe|might|could|estimated|not|never)\b|[~≈<>≤≥]", re.I)
UNCERTAINTY = re.compile(r"\b(?:unknown|unverified|unavailable|not known|not available|not provided|not recorded|cannot verify|can't verify|cannot determine)\b", re.I)


def _normal(text):
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (ValueError, InvalidOperation):
        return None


def _echo(text, question):
    return (isinstance(text, str) and isinstance(question, str) and bool(question.strip())
            and _normal(text.translate(QUOTES)) == _normal(question.translate(QUOTES)))


def _lookups(packet):
    payload = packet.get("payload", {}) if isinstance(packet, dict) else {}
    values = payload.get("food_lookup", []) if isinstance(payload, dict) else []
    return [row for row in values if isinstance(row, dict) and isinstance(row.get("data"), dict)
            and isinstance(row["data"].get("description"), str) and row["data"]["description"].strip()] if isinstance(values, list) else []


def _texts(response):
    if not isinstance(response, dict):
        return []
    items = []
    def visit(value, path=""):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"food_id", "source_ref", "evidence_refs", "activity_id", "parent_activity_id"}:
                    continue
                visit(item, path + "/" + str(key).replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                visit(item, path + "/" + str(i))
        elif isinstance(value, str) and value.strip():
            items.append((path, value))
    visit(response)
    return items


def _numeric_assertion(text):
    """Mass-only titles and question/request mentions contain no asserted value."""
    return bool(re.search(r"\b(?:contains?|provides?|has|is|equals?)\s+(?:about\s+|approximately\s+)?"
                          r"[<>~≈≤≥]?\s*" + ASSERTED_NUMBER + r"\s*" + UNIT + r"\b", text, re.I)
                or re.search(r"\b(?:protein|energy)\s*(?:(?:amount|content)\s*)?"
                             r"(?:(?:totals?|is|equals?)\s*|[:=]\s*)?" + ASSERTED_NUMBER + r"\s*" + UNIT + r"\b", text, re.I)
                or re.search(ASSERTED_NUMBER + r"\s*" + UNIT + r"\s+(?:of\s+)?(?:protein|energy)\b", text, re.I))


def _parse_segment(text, names, food_field=False):
    text = text.strip()
    if text.endswith("?") or re.match(r"^(?:is|does|do|how|what|whether)\b", text, re.I):
        return [], None, "question"
    if any(re.fullmatch(r"(?:protein|energy)\s+(?:in|for)\s+" + NUM + r"\s*" + MASS
                        + r"\s+(?:of\s+)?" + re.escape(name) + r"\.?", text, re.I) for name in names):
        return [], None, "food_nutrient_mass_subject_title"
    if not _numeric_assertion(text):
        if food_field and re.search(NUM + r"\s*" + UNIT + r"\b", text, re.I) and not re.search(r"\b(?:asks?|asked|question|requests?|requested)\b", text, re.I):
            return [], "incomplete_quantified_food_field", None
        return [], None, "nonassertive_food_subject_or_other_text"
    if HEDGE.search(text):
        return [], "hedged_negated_or_qualified_numeric_wording", None
    matches = []
    for name in names:
        food = re.escape(name)
        patterns = [
            r"(?P<grams>" + NUM + r")\s*" + MASS + r"\s+(?:of\s+)?" + food
            + r"\s*,?\s*(?:contains|has|provides)\s+(?P<amount>" + NUM + r")\s*(?P<unit>" + UNIT
            + r")\s+(?:of\s+)?(?P<nutrient>protein|energy)\b",
            r"(?P<nutrient>protein|energy)\s+in\s+(?P<grams>" + NUM + r")\s*" + MASS
            + r"\s+(?:of\s+)?" + food + r"\s*,?\s*(?:is|:|=)\s*(?P<amount>" + NUM
            + r")\s*(?P<unit>" + UNIT + r")\b",
            food + r"\s+(?:contains|has|provides)\s+(?P<amount>" + NUM + r")\s*(?P<unit>" + UNIT
            + r")\s+(?:of\s+)?(?P<nutrient>protein|energy)\s+per\s+(?P<grams>" + NUM + r")\s*" + MASS + r"\b",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.I):
                matches.append({"start": match.start(), "end": match.end(), "food_description": name,
                    "grams": match["grams"], "amount": match["amount"],
                    "unit": UNITS[match["unit"].casefold()], "nutrient": match["nutrient"].casefold()})
    unique = {(m["start"], m["end"], m["food_description"], m["grams"], m["amount"], m["unit"], m["nutrient"]): m for m in matches}
    matches = sorted(unique.values(), key=lambda m: (m["start"], m["end"]))
    if not matches:
        return [], "unsupported_numeric_assertion", None
    if not PREFIX.fullmatch(text[:matches[0]["start"]].strip()):
        return [], "unsupported_assertion_prefix", None
    for left, right in zip(matches, matches[1:]):
        if left["end"] > right["start"] or not re.fullmatch(r"\s*(?:,?\s*(?:and|but|also))\s*", text[left["end"]:right["start"]], re.I):
            return [], "overlapping_or_unresolved_multiple_claims", None
    if not re.fullmatch(r"\s*[.!]?\s*", text[matches[-1]["end"]:]):
        return [], "unsupported_assertion_suffix", None
    return matches, None, None


def _compare(claim, lookups):
    rows = [row for row in lookups if _normal(row["data"]["description"]) == _normal(claim["food_description"])]
    if len(rows) != 1 or rows[0].get("status") != "found":
        return "unknown", "source_food_identity_missing_or_ambiguous", None
    lookup = rows[0]
    data = lookup["data"]
    nutrients = data.get("nutrients")
    if not isinstance(nutrients, list):
        return "unknown", "source_nutrients_unavailable", None
    source_rows = [row for row in nutrients if isinstance(row, dict)
                   and isinstance(row.get("nutrient_name"), str) and _normal(row["nutrient_name"]) == claim["nutrient"]]
    if len(source_rows) != 1:
        return "unknown", "source_nutrient_missing_or_ambiguous", None
    source = source_rows[0]
    expected_id = "1003" if claim["nutrient"] == "protein" else "1008"
    if source.get("status") != "available" or str(source.get("nutrient_id")) != expected_id:
        return "unknown", "source_nutrient_not_available_with_expected_identity", None
    if (not isinstance(data.get("food_id"), str) or not data["food_id"].strip() or str(source.get("fdc_id")) != data["food_id"]
            or source.get("description") != data["description"]):
        return "unknown", "source_food_identity_inconsistent", None
    grams, source_grams, row_grams = map(_decimal, (claim["grams"], data.get("grams"), source.get("grams")))
    if grams is None or grams <= 0 or grams != source_grams or grams != row_grams:
        return "unknown", "claim_mass_not_exactly_covered_by_supplied_record", None
    if claim["unit"] != source.get("unit"):
        return "unknown", "claim_unit_not_exactly_covered_by_supplied_record", None
    for key in ("qualifier", "value_qualifier", "amount_qualifier"):
        if source.get(key) not in (None, "", "="):
            return "unknown", "source_value_has_unresolved_qualifier", None
    footnote = source.get("source_footnote")
    if footnote is not None and (not isinstance(footnote, str) or HEDGE.search(footnote)):
        return "unknown", "source_footnote_has_unresolved_qualification", None
    amount, expected = _decimal(claim["amount"]), _decimal(source.get("amount"))
    if amount is None or expected is None or expected < 0:
        return "unknown", "source_or_claim_value_not_finite", None
    if source.get("reason") is not None and (not isinstance(source["reason"], str) or HEDGE.search(source["reason"])):
        return "unknown", "source_reason_has_unresolved_qualification", None
    if "amount_per_100g_raw" in source or "reference_mass_g" in source:
        raw, basis = _decimal(source.get("amount_per_100g_raw")), _decimal(source.get("reference_mass_g"))
        if raw is None or raw < 0 or basis != Decimal(100):
            return "unknown", "source_reference_basis_not_supported", None
        try:
            with localcontext() as context:
                context.prec = max(28, len(expected.as_tuple().digits) + 3,
                                   len(raw.as_tuple().digits) + len(grams.as_tuple().digits)) + 2
                if expected * basis != raw * grams:
                    return "unknown", "source_scaled_value_inconsistent", None
        except DecimalException:
            return "unknown", "source_reference_arithmetic_not_supported", None
    observed = {"food_id": data["food_id"], "food_description": data["description"], "grams": str(grams),
                "nutrient": claim["nutrient"], "claimed_amount": str(amount), "source_amount": str(expected),
                "unit": claim["unit"], "source_ref": source.get("source_record_url"),
                "source_footnote": footnote, "comparison": "exact_decimal_same_recorded_mass_and_unit"}
    return ("met", "recognized_claim_matches_supplied_record", observed) if amount == expected else (
        "violated", "recognized_claim_changes_supplied_recorded_value", observed)


def diagnose_food(public, response, packet):
    """Return supplemental diagnostics; no response, source or score is edited."""
    public = public if isinstance(public, dict) else {}
    question = public.get("food_question")
    required = isinstance(question, str) and bool(question.strip())
    target_match = QUESTION.fullmatch(question) if required else None
    target = ({"food_description": target_match[1], "grams": target_match[3],
               "nutrient": "protein" if target_match[2] == "grams of protein" else "energy"}
              if target_match and _decimal(target_match[3]) is not None and _decimal(target_match[3]) > 0 else None)
    lookups = _lookups(packet)
    names = sorted({row["data"]["description"] for row in lookups}, key=len, reverse=True)
    claims, unsupported, echoes, ignored, uncertain_fields = [], [], [], [], []
    for path, text in _texts(response):
        field = bool(re.fullmatch(r"/food_facts/[0-9]+/statement", path))
        if _echo(text, question):
            echoes.append(path)
            continue
        if field and UNCERTAINTY.search(text) and not _numeric_assertion(text):
            uncertain_fields.append(path)
            continue
        for segment in re.split(r"(?<=[.!?])\s+|[;\n]+", text):
            if not segment.strip():
                continue
            parsed, issue, ignored_reason = _parse_segment(segment, names, food_field=field)
            if issue:
                unsupported.append({"path": path, "text": segment, "reason": issue, "in_required_field": field})
            elif ignored_reason:
                ignored.append({"path": path, "text": segment, "reason": ignored_reason})
            for claim in parsed:
                status, reason, observed = _compare(claim, lookups)
                claims.append({**{k: v for k, v in claim.items() if k not in {"start", "end"}},
                    "path": path, "text": segment, "in_required_field": field,
                    "comparison_status": status, "comparison_reason": reason, "comparison": observed})
    def matches_target(claim):
        return bool(target and _normal(claim["food_description"]) == _normal(target["food_description"])
                    and _decimal(claim["grams"]) == _decimal(target["grams"])
                    and claim["nutrient"] == target["nutrient"])
    field_claims = [c for c in claims if c["in_required_field"] and matches_target(c)]
    if not required:
        completeness = "not_applicable"
    elif target is None:
        completeness = "unknown"
    elif any(c["comparison_status"] != "unknown" for c in field_claims):
        completeness = "met"
    elif field_claims or uncertain_fields or any(u["in_required_field"] for u in unsupported):
        completeness = "unknown"
    else:
        completeness = "violated"
    numeric_needed = required or bool(claims) or bool(unsupported)
    if any(c["comparison_status"] == "violated" for c in claims):
        numeric = "violated"
    elif unsupported or any(c["comparison_status"] == "unknown" for c in claims) or numeric_needed and not claims:
        numeric = "unknown"
    elif claims:
        numeric = "met"
    else:
        numeric = "not_applicable"
    return {"version": VERSION, "question_present": required, "designated_reply_present": isinstance(response, dict),
        "question_grammar_supported": target is not None, "target": target,
        "field_answer_status": completeness, "numeric_answer_status": numeric,
        "required_field_target_claim_count": len(field_claims),
        "supported_elsewhere": any(not c["in_required_field"] and matches_target(c) and c["comparison_status"] == "met" for c in claims),
        "recognized_claims": claims, "unsupported_assertions": unsupported, "echo_paths": echoes,
        "uncertain_food_field_paths": uncertain_fields, "ignored_nonassertions": ignored,
        "source_issues": [c["comparison_reason"] for c in claims if c["comparison_status"] == "unknown"],
        "no_reply_or_value_inserted": True, "saved_response_changed": False}


def assess_food(public, response, packet, *, base_assess_food=None):
    """Return the original three check IDs with field and numeric checks separate."""
    diagnostic = diagnose_food(public, response, packet)
    required = diagnostic["question_present"]
    completeness_reason = {
        "met": "The food_facts statement explicitly answers the requested food, mass and nutrient; numerical accuracy is checked separately.",
        "violated": "The required food_facts statement omits a complete answer. A correct answer elsewhere does not fill this required field.",
        "unknown": "The required food_facts answer cannot be established under the declared claim grammar and supplied source conditions.",
        "not_applicable": "No explicit food question requires a food_facts answer."}[diagnostic["field_answer_status"]]
    numeric_reason = {
        "met": "Every recognized numeric food assertion agrees exactly with the supplied food, mass, nutrient value and unit; no unsupported numeric assertion remains.",
        "violated": "At least one recognized numeric food assertion changes the supplied recorded value.",
        "unknown": "The supplied records and declared grammar do not establish every potentially asserted numeric food value.",
        "not_applicable": "No food question or asserted numeric food claim requires comparison."}[diagnostic["numeric_answer_status"]]
    checks = [{"check_id": CHECK_IDS[0], "status": diagnostic["field_answer_status"], "reason": completeness_reason,
               "required": required, "version": VERSION, "observed": {
                   "question_present": required, "question_grammar_supported": diagnostic["question_grammar_supported"],
                   "field_target_claim_count": diagnostic["required_field_target_claim_count"],
                   "supported_elsewhere": diagnostic["supported_elsewhere"], "question_echo_paths": diagnostic["echo_paths"],
                   "uncertain_food_field_paths": diagnostic["uncertain_food_field_paths"]}},
              {"check_id": CHECK_IDS[1], "status": diagnostic["numeric_answer_status"], "reason": numeric_reason,
               "required": required or bool(diagnostic["recognized_claims"] or diagnostic["unsupported_assertions"]),
               "version": VERSION, "observed": {"claims": [{key: deepcopy(c[key]) for key in
                    ("path", "comparison_status", "comparison_reason", "comparison")} for c in diagnostic["recognized_claims"]],
                    "unsupported_assertions": [{"path": c["path"], "reason": c["reason"]} for c in diagnostic["unsupported_assertions"]],
                    "supported_elsewhere": diagnostic["supported_elsewhere"]}}]
    grounding = None
    if callable(base_assess_food):
        grounding = next((deepcopy(c) for c in base_assess_food(deepcopy(public), deepcopy(response), deepcopy(packet))
                          if c.get("check_id") == CHECK_IDS[2]), None)
    if grounding is None:
        grounding = {"check_id": CHECK_IDS[2], "status": "unknown" if diagnostic["recognized_claims"] else "not_applicable",
                     "reason": "Source attribution is assessed separately; numeric agreement alone does not establish explicit grounding.",
                     "required": False, "version": VERSION, "observed": {"grounding_not_inferred_from_numeric_agreement": True}}
    checks.append(grounding)
    for check in checks:
        check["food_response_validation_version"] = VERSION
        check["food_answer_audit"] = {"version": VERSION, "question_echo_paths": diagnostic["echo_paths"],
                                      "question_echo_count": len(diagnostic["echo_paths"]), "saved_reply_changed": False,
                                      "food_answer_or_value_inserted": False}
    return checks
