"""Highlight requested packet facts and audit narrowly equivalent question echoes.

This module never fills a response, changes a schema, retrieves a food record or
repairs a supplied value. Call the focus encoder only for reference-enabled
planners. The complete original reference payload remains in the model view.
"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re
import unicodedata


VERSION = "requested-food-fact-focus-1"
AUDIT_VERSION = "equivalent-quote-food-question-audit-1"
FINAL_FOOD_GUIDANCE = (
    "Answer the athlete's food question directly when a source-linked requested_food_facts item is supplied. "
    "Use the supplied food identity, grams, nutrient, amount and unit without changing the value, "
    "and preserve its source qualifications. Put the answer in food_facts with its food_id and source_ref. "
    "A clear sentence is '<grams> g <food_description> contains <amount> <unit> <nutrient_name>.' "
    "If no supported requested value is available, state that it is unknown rather than inventing a value. "
    "Repeating the food question, even with different quotation marks, is not an answer."
)
FOOD_ROLE_GUIDANCE = (
    "Read requested_food_facts as well as the complete reference_data. When an available requested fact is "
    "supplied, include its numerical answer and source attribution in the existing note fields allowed by "
    "your schema so the final planner can answer it. Preserve the supplied food, mass, nutrient, unit and "
    "source qualifications. Do not claim that an available supplied value is missing. If the focus is "
    "unresolved, retain that uncertainty; do not invent a value or repeat the question as an answer."
)
_QUOTES = str.maketrans({"'": '"', "\u2018": '"', "\u2019": '"', "\u201a": '"',
                        "\u201b": '"', "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"'})
_QUESTION = re.compile(
    r'For the food "([^"\r\n]+)", how many (grams of protein|kilocalories of energy) '
    r'are recorded for ([0-9]+(?:\.[0-9]+)?) g\?'
)
_IDENTIFIERS = {"food_id", "source_ref", "evidence_refs", "activity_id", "parent_activity_id",
                "existing_commitment_refs", "response_type", "date", "start_date", "end_date", "timezone",
                "start_time", "end_time", "relationship"}


def _normal(text):
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def is_question_echo(statement, question):
    """Only NFC, case, whitespace and equivalent quote code points may differ.

    Numeric values, units, food words and all other punctuation remain intact.
    This is not a paraphrase detector or a numeric-answer recognizer.
    """
    return (isinstance(statement, str) and isinstance(question, str) and bool(question.strip())
            and _normal(statement.translate(_QUOTES)) == _normal(question.translate(_QUOTES)))


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (ValueError, InvalidOperation):
        return None


def _unresolved(result, reason):
    result["status"] = "unresolved"
    result["unresolved"] = [{"reason": reason}]
    return result


def make_food_focus(public_input, payload):
    """Return one exact requested fact from the supplied *unencoded payload*.

    Supported questions use the same literal food/mass/nutrient grammar as the
    existing food assessor. No fuzzy identity, aliases, quantity conversion,
    rounding or external lookup is introduced. Duplicate matching records or
    nutrients remain ambiguous even if their values happen to agree.
    """
    result = {"schema_version": VERSION, "status": "not_requested", "requested_facts": [], "unresolved": []}
    if not isinstance(public_input, dict):
        return _unresolved(result, "public_input_unavailable")
    question = public_input.get("food_question")
    if question is None or question == "":
        return result
    if not isinstance(question, str):
        return _unresolved(result, "food_question_not_text")
    if not question.strip():
        return result
    match = _QUESTION.fullmatch(unicodedata.normalize("NFC", question))
    if match is None:
        return _unresolved(result, "unsupported_literal_food_question")
    grams = _decimal(match[3])
    if grams is None or grams <= 0:
        return _unresolved(result, "requested_mass_not_positive_finite")
    nutrient_id, nutrient_name, unit = (("1003", "Protein", "G") if match[2] == "grams of protein"
                                      else ("1008", "Energy", "KCAL"))
    values = payload.get("food_lookup") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        return _unresolved(result, "supplied_food_lookup_unavailable")
    matches = [(i, row) for i, row in enumerate(values) if isinstance(row, dict)
               and isinstance(row.get("data"), dict) and isinstance(row["data"].get("description"), str)
               and _normal(row["data"]["description"]) == _normal(match[1])]
    if len(matches) != 1:
        return _unresolved(result, "food_identity_missing_or_ambiguous")
    index, lookup = matches[0]
    data = lookup["data"]
    if lookup.get("status") != "found":
        return _unresolved(result, "food_lookup_not_found")
    food_id = data.get("food_id")
    if not isinstance(food_id, str) or not food_id.strip():
        return _unresolved(result, "source_food_identifier_unavailable")
    if _decimal(data.get("grams")) != grams:
        return _unresolved(result, "supplied_food_mass_differs")
    nutrients = data.get("nutrients")
    if not isinstance(nutrients, list):
        return _unresolved(result, "supplied_nutrients_unavailable")
    candidates = [(j, row) for j, row in enumerate(nutrients) if isinstance(row, dict)
                  and str(row.get("nutrient_id")) == nutrient_id]
    if len(candidates) != 1:
        return _unresolved(result, "requested_nutrient_missing_or_ambiguous")
    nutrient_index, source = candidates[0]
    if (source.get("status") != "available" or not isinstance(source.get("nutrient_name"), str)
            or _normal(source["nutrient_name"]) != _normal(nutrient_name) or source.get("unit") != unit):
        return _unresolved(result, "requested_nutrient_status_name_or_unit_unsupported")
    if (str(source.get("fdc_id")) != food_id or source.get("description") != data["description"]
            or _decimal(source.get("grams")) != grams):
        return _unresolved(result, "nutrient_food_identity_or_mass_differs")
    amount, raw, basis_mass = map(_decimal, (source.get("amount"), source.get("amount_per_100g_raw"),
                                           source.get("reference_mass_g")))
    if amount is None or raw is None or amount < 0 or raw < 0 or basis_mass != Decimal(100):
        return _unresolved(result, "source_value_or_reference_mass_unsupported")
    with localcontext() as context:
        context.prec = max(28, len(amount.as_tuple().digits) + 3,
                           len(raw.as_tuple().digits) + len(grams.as_tuple().digits)) + 2
        if amount * basis_mass != raw * grams:
            return _unresolved(result, "supplied_scaled_amount_disagrees_with_reference_basis")
    if not isinstance(source.get("reference_basis"), str) or not source["reference_basis"].strip():
        return _unresolved(result, "source_reference_basis_unavailable")
    for key in ("source_footnote", "reason", "qualifier", "value_qualifier", "amount_qualifier"):
        if source.get(key) is not None and not isinstance(source[key], str):
            return _unresolved(result, "source_qualifier_not_text")
    if any(source.get(key) not in (None, "", "=") for key in ("qualifier", "value_qualifier", "amount_qualifier")):
        return _unresolved(result, "qualified_value_requires_interpretation")
    ref = source.get("source_record_url")
    if (not isinstance(ref, str) or not ref.startswith(("https://", "http://"))
            or not isinstance(lookup.get("source_refs"), list) or ref not in lookup["source_refs"]):
        return _unresolved(result, "source_attribution_unavailable_or_inconsistent")
    core = {"amount", "unit", "grams", "nutrient_id", "nutrient_name", "description", "fdc_id", "source_record_url"}
    # These locators already remain at source_path in the unchanged complete
    # packet. Keep value qualifications, basis, derivation text and all other
    # source metadata in the focus; avoid repeating long archive/table locators.
    trace_locators = {"NDB_number", "source_archive_sha256", "source_food_table",
                      "source_food_nutrient_id", "source_derivation_id"}
    qualifiers = {key: deepcopy(value) for key, value in source.items() if key not in core | trace_locators}
    result.update(status="available", requested_facts=[{
        "food_id": food_id, "source_ref": ref, "food_description": data["description"],
        "grams": str(source["grams"]), "nutrient_id": nutrient_id, "nutrient_name": source["nutrient_name"],
        "amount": str(source["amount"]), "unit": source["unit"], "source_qualifiers": qualifiers,
        "source_path": f"/food_lookup/{index}/data/nutrients/{nutrient_index}"
    }])
    return result


def attach_food_focus(view):
    """Augment a private reference-enabled model view; preserve its complete data."""
    copied = deepcopy(view)
    if not isinstance(copied, dict) or "reference_data" not in copied:
        return copied
    copied["requested_food_facts"] = make_food_focus(copied.get("athlete_input"), copied["reference_data"])
    return copied


def assess_food(public, response, packet, *, base_assess_food):
    """Audit copied question-only prose while retaining the frozen food assessor.

    Only an assessment copy is edited. Unknown statements, wrong values and
    all other unsupported wording keep the base assessor's treatment.
    """
    if not isinstance(public, dict) or not callable(base_assess_food):
        raise ValueError("The food audit needs public input and the frozen food assessor.")
    question = public.get("food_question")
    echoes = []
    def visit(value, path=""):
        if isinstance(value, dict):
            return {key: deepcopy(item) if key in _IDENTIFIERS else
                    visit(item, path + "/" + str(key).replace("~", "~0").replace("/", "~1"))
                    for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item, path + "/" + str(i)) for i, item in enumerate(value)]
        if is_question_echo(value, question):
            echoes.append(path)
            return ""
        return deepcopy(value)
    checks = deepcopy(base_assess_food(public, visit(response), packet))
    if not isinstance(checks, list) or any(not isinstance(row, dict) for row in checks):
        raise ValueError("The frozen food assessor returned no complete finding list.")
    metadata = {"version": AUDIT_VERSION, "question_echo_paths": echoes, "question_echo_count": len(echoes),
                "normalization": "NFC_casefold_whitespace_equivalent_quotes_only", "assessment_copy_only": True,
                "saved_reply_changed": False, "food_answer_or_value_inserted": False,
                "other_unsupported_prose_reclassified": False,
                "question_sha256": hashlib.sha256(question.encode()).hexdigest() if isinstance(question, str) else None}
    for row in checks:
        row["food_answer_audit"] = deepcopy(metadata)
        if echoes and row.get("check_id") == "food_answer_completeness" and row.get("status") == "violated":
            row["reason"] = "The reply repeats the food question with no numerical answer; equivalent quotation changes do not supply an answer."
    return checks
