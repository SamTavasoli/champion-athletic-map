"""Prepare private food-answer expectations from the unchanged recorded reference."""

from collections import Counter
import csv
from decimal import Context, Decimal, localcontext
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys

VERSION = "private-recorded-food-expectations-1"
FOOD = "data/processed/usda_sr_legacy_2018_04/reference_ee67cf780262d24b"
SOURCE_VERSION = "sr-legacy-2018-04:ee67cf780262d24b"
EXPECTED = {
    "step14_food_reference_summary.json": "ee67cf780262d24bf02bcc7230104e65bcbfe6508b44f3c36eb03100d85295af",
    "usda_foods.csv": "a4334b0ca87fd8881da84ab34fc50976e4d44cd1b1888adfbb210365d2976352",
    "usda_food_nutrients.csv": "a4b4f7b9049e24ebd34551578e9e858e24739bacd6b9db2383e2ed9e5e4a27ff",
    "usda_food_reference.py": "b665381f328e9ebfefbe8c42ef01e6905a7085dc4789290939194b4488b69136",
    "usda_nutrient_definitions.json": "ad24c61b8acba1a3305101be092d98128e43fc9bbdd2c82d882598251474c2a9",
}
QUESTION = re.compile(r'^For the recorded food identity "(?P<description>[^"]+)", how many '
    r'(?P<measure>grams of protein|kilocalories of energy) are listed for '
    r'(?P<grams>[0-9]+(?:\.[0-9]+)?) g\?$')
RUNTIME_QUESTION = re.compile(r'^For the food "(?P<description>[^"]+)", how many '
    r'(?P<measure>grams of protein|kilocalories of energy) are recorded for '
    r'(?P<grams>[0-9]+(?:\.[0-9]+)?) g\?$')
NUTRIENTS = {"grams of protein": ("1003", "Protein", "G"),
             "kilocalories of energy": ("1008", "Energy", "KCAL")}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _strict_json(data):
    def unique(items):
        result = {}
        for key, value in items:
            _require(key not in result, "A food reference has duplicate JSON keys.")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("A food reference contains a nonfinite value.")))


def _path(root, relative):
    parts = PurePosixPath(relative)
    _require(not parts.is_absolute() and not set(parts.parts) & {".", ".."}
             and "\\" not in relative and ":" not in relative, "Invalid food-reference path.")
    path = root / relative
    _require(path.resolve() == path and path.is_relative_to(root), "A food reference leaves its recorded project path.")
    return path


def parse_food_question(question):
    """Accept only the recorded-identity grammar used by these final case drafts."""
    match = (QUESTION.fullmatch(question) or RUNTIME_QUESTION.fullmatch(question)) if isinstance(question, str) else None
    if match is None:
        return None
    values = match.groupdict()
    mass = Decimal(values["grams"])
    if not mass.is_finite() or mass <= 0:
        return None
    nutrient_id, nutrient_name, unit = NUTRIENTS[values["measure"]]
    return {"description": values["description"], "grams": values["grams"],
            "nutrient_id": nutrient_id, "nutrient_name": nutrient_name, "unit": unit}


def _questions(profiles):
    result = []
    ids = set()
    for record in profiles:
        value = record.get("input", {}).get("food_question")
        if value is None or value == "":
            continue
        identifier = record.get("profile_id")
        _require(isinstance(identifier, str) and identifier and identifier not in ids,
                 "Food expectations need unique, nonempty profile IDs.")
        ids.add(identifier)
        result.append((identifier, value))
    return result


def _runtime_question(parsed):
    if parsed is None:
        return None
    measure = "grams of protein" if parsed["nutrient_id"] == "1003" else "kilocalories of energy"
    return ('For the food "' + parsed["description"] + '", how many ' + measure
            + ' are recorded for ' + parsed["grams"] + ' g?')


def canonical_runtime_question(question):
    """Propose the supported literal wording while preserving identity and quantity."""
    return _runtime_question(parse_food_question(question))


def _summary(cases, source_bindings, **extra):
    counts = dict(Counter(row["status"] for row in cases))
    route_counts = dict(Counter(row.get("runtime_description_lookup", {}).get("status", "not_verified") for row in cases))
    return {"schema_version": VERSION, "source_version": SOURCE_VERSION,
            "cases": cases, "counts": counts, "requested_cases": len(cases),
            "verified_cases": counts.get("verified", 0), "source_bindings": source_bindings,
            "runtime_lookup_status_counts": route_counts,
            "runtime_ready_cases": sum(row["status"] == "verified" and row.get("runtime_description_lookup", {}).get("status") == "unique_target" for row in cases),
            "private_expectations_only": True, "public_input_values_changed": False,
            "model_calls": 0, "new_query_encodings": 0, "team_approvals_created": 0, **extra}


def evaluate_food_questions(profiles, foods, nutrients, food_fact, *, source_bindings=None,
                            source_version=SOURCE_VERSION):
    """Use exact identities and the frozen arithmetic helper, never fuzzy guesses."""
    cases = []
    for identifier, question in _questions(profiles):
        result = {"profile_id": identifier, "question": question, "status": "unverified",
                  "reason": None, "expected_fact": None, "match_policy": "exact_full_recorded_description"}
        parsed = parse_food_question(question)
        result["proposed_runtime_question"] = _runtime_question(parsed)
        result["original_question_preserved"] = True
        if parsed is None:
            result.update(status="unsupported_question", reason="The question does not match the frozen case grammar.")
            cases.append(result)
            continue
        result["requested"] = parsed
        route_matches = [row for row in foods if isinstance(row.get("description"), str)
                         and parsed["description"].casefold().strip() in row["description"].casefold()]
        result["runtime_description_lookup"] = {"status": "unique_target" if len(route_matches) == 1
            and route_matches[0].get("description") == parsed["description"] else "not_found" if not route_matches else "ambiguous_or_nonexact",
            "candidate_food_ids": [str(row.get("fdc_id")) for row in route_matches],
            "policy": "Existing ReferenceTools full-description substring search after canonical literal parsing"}
        matches = [row for row in foods if row.get("description") == parsed["description"]]
        result["matching_food_ids"] = [str(row.get("fdc_id")) for row in matches]
        if len(matches) != 1:
            result.update(status="not_found" if not matches else "ambiguous_food",
                          reason="An exact, unique recorded food identity is required.")
            cases.append(result)
            continue
        food = matches[0]
        rows = [row for row in nutrients if str(row.get("fdc_id")) == str(food.get("fdc_id"))
                and str(row.get("nutrient_id")) == parsed["nutrient_id"]]
        if len(rows) != 1:
            result.update(status="nutrient_not_found" if not rows else "ambiguous_nutrient",
                          reason="An exact, unique source nutrient row is required.")
            cases.append(result)
            continue
        nutrient = rows[0]
        if (nutrient.get("unit_name") != parsed["unit"]
                or str(nutrient.get("nutrient_name", "")).casefold() != parsed["nutrient_name"].casefold()):
            result.update(status="nutrient_definition_mismatch", reason="Recorded nutrient name or unit differs from the question.")
            cases.append(result)
            continue
        try:
            fact = food_fact(food, nutrient, grams=parsed["grams"])
            if fact.get("status") != "available":
                result.update(status="source_value_unavailable", reason=fact.get("reason"), unavailable_fact=fact)
            elif not isinstance(food.get("source_record_url"), str) or not food["source_record_url"].strip():
                result.update(status="source_attribution_missing", reason="A source record URL is required for the expected answer.")
            else:
                with localcontext(Context(prec=50)):
                    check = Decimal(nutrient["amount_per_100g_raw"]) * Decimal(parsed["grams"]) / Decimal("100")
                _require(Decimal(fact["amount"]) == check and Decimal(fact["grams"]) == Decimal(parsed["grams"])
                         and fact["nutrient_id"] == parsed["nutrient_id"] and fact["unit"] == parsed["unit"]
                         and fact.get("fdc_id") == str(int(food["fdc_id"])) and fact.get("description") == parsed["description"]
                         and fact.get("source_food_nutrient_id") == str(int(nutrient["source_food_nutrient_id"])),
                         "The saved food helper disagrees with its exact source calculation.")
                result.update(status="verified", expected_fact={**fact, "source_ref": food["source_record_url"],
                    "reference_version": source_version, "exact_arithmetic_crosscheck": True})
        except (ValueError, TypeError, KeyError, ArithmeticError) as error:
            result.update(status="invalid_source_value", reason=str(error))
        cases.append(result)
    return _summary(cases, dict(source_bindings or {}), source_version=source_version,
                    reference_files_verified=bool(source_bindings), numerical_values_created_by_model=False)


def _csv(data):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    _require(reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)), "Invalid food-reference CSV header.")
    rows = list(reader)
    _require(all(None not in row and all(value is not None for value in row.values()) for row in rows),
             "Malformed food-reference CSV row.")
    return rows


def build_food_expectations(root, profiles):
    """Verify the actual local reference before producing any private numeric answer."""
    root = Path(root).resolve()
    missing, content, bindings = [], {}, {}
    for filename, expected in EXPECTED.items():
        relative = FOOD + "/" + filename
        path = _path(root, relative)
        if not path.is_file():
            missing.append(relative)
            continue
        data = path.read_bytes()
        _require(hashlib.sha256(data).hexdigest() == expected, "A frozen food-reference file changed: " + relative)
        content[filename], bindings[relative] = data, expected
    if missing:
        cases = [{"profile_id": identifier, "question": question, "status": "reference_unavailable",
                  "reason": "One or more frozen food-reference files are missing locally.", "expected_fact": None,
                  "proposed_runtime_question": _runtime_question(parse_food_question(question)),
                  "original_question_preserved": True}
                 for identifier, question in _questions(profiles)]
        return _summary(cases, bindings, reference_files_verified=False, missing_files=missing,
                        native_food_values_verified=False, numerical_values_created_by_model=False)
    producer = _strict_json(content["step14_food_reference_summary.json"])
    for filename in EXPECTED:
        if filename != "step14_food_reference_summary.json":
            _require(producer["artifacts"][filename]["sha256"] == EXPECTED[filename],
                     "The food producer and frozen reference bindings disagree.")
    _strict_json(content["usda_nutrient_definitions.json"])
    helper_path = _path(root, FOOD + "/usda_food_reference.py")
    name = "step33_recorded_food_" + EXPECTED["usda_food_reference.py"][:16]
    spec = importlib.util.spec_from_file_location(name, helper_path)
    helper = importlib.util.module_from_spec(spec)
    sys.modules[name] = helper
    spec.loader.exec_module(helper)
    result = evaluate_food_questions(profiles, _csv(content["usda_foods.csv"]),
        _csv(content["usda_food_nutrients.csv"]), helper.food_fact, source_bindings=bindings)
    for relative, expected in bindings.items():
        _require(hashlib.sha256(_path(root, relative).read_bytes()).hexdigest() == expected,
                 "A frozen food-reference file changed during calculation.")
    result["native_food_values_verified"] = result["requested_cases"] > 0 and result["verified_cases"] == result["requested_cases"]
    return result
