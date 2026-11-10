"""Development checks for exact-source food facts; not planner research scores."""
from decimal import Decimal


def run_tests(module, foods, nutrients, portions, goldens):
    tests, comparisons = [], []
    fact, mass = module["food_fact"], module["household_mass"]

    def record(target, case_id, condition, expected, observed, kind):
        target.append({"case_id": case_id, "status": "pass" if condition else "failed", "case_type": kind,
                       "expected": str(expected), "observed": str(observed)})

    def equal(case_id, expected, observed, kind="calculation"):
        condition = Decimal(str(observed)) == Decimal(str(expected))
        record(tests, case_id, condition, expected, observed, kind)

    def reject(case_id, callback, kind="invalid_input", allow_unavailable=False):
        try:
            result = callback()
        except (ValueError, TypeError):
            record(tests, case_id, True, "rejected", "rejected", kind)
        else:
            unavailable = allow_unavailable and isinstance(result, dict) and result.get("status") == "unavailable" and result.get("amount") is None
            record(tests, case_id, unavailable, "rejected_or_unavailable" if allow_unavailable else "rejected", result, kind)

    def source_portion(row):
        return {"portion_id": row["id"], "fdc_id": row["fdc_id"], "amount_raw": row["amount"],
                "gram_weight_raw": row["gram_weight"], "modifier": row["modifier"],
                "measure_unit_id": row["measure_unit_id"], "unit_name": "undetermined",
                "footnote": row["footnote"], "household_numeric_screen_pass": True,
                "household_eligibility": "unavailable" if row["amount"] == "0" else "available"}

    # These literals were prepared independently of the calculation module.
    for source in goldens["foods"]:
        food_id = source["fdc_id"]
        record(comparisons, "food_identity:" + food_id,
               food_id in foods and foods[food_id]["description"] == source["description"],
               source["description"], foods.get(food_id, {}).get("description"), "source_identity")
        for nutrient in source["source_nutrients"]:
            key = food_id, nutrient["nutrient_id"]
            if nutrient["nutrient_id"] not in {"1008", "1003", "1004", "1005", "1079"}:
                continue
            actual = nutrients.get(key, {})
            expected = nutrient["id"], nutrient["amount"], nutrient["unit_name"]
            observed = actual.get("source_food_nutrient_id"), actual.get("amount_per_100g_raw"), actual.get("unit_name")
            record(comparisons, "source_nutrient:" + ":".join(key), observed == expected, expected, observed, "source_nutrient_record")
    for source in goldens["source_portions"]:
        expected = source_portion(source)
        actual = portions.get(source["id"], {})
        for field in ("fdc_id", "amount_raw", "gram_weight_raw", "modifier", "measure_unit_id"):
            record(comparisons, "source_portion:" + source["id"] + ":" + field,
                   actual.get(field) == expected[field], expected[field], actual.get(field), "source_portion_record")

    for case in goldens["valid_cases"]:
        food = foods[case["fdc_id"]]
        if case["mode"] == "edible_mass_g":
            grams = case["quantity"]
        else:
            mode = {"complete_source_portions": "complete_record", "same_defined_measure_units": "same_defined_unit"}[case["mode"]]
            grams = mass(food, portions[case["portion_id"]], case["quantity"], mode=mode)["grams"]
        equal(case["case_id"] + ":mass", case["expected_mass_g"], grams, "source_calculation")
        for nutrient_id, expected in case["expected_amounts"].items():
            actual = fact(food, nutrients[(food["fdc_id"], nutrient_id)], grams)
            if expected is None:
                record(tests, case["case_id"] + ":" + nutrient_id,
                       actual["status"] == "unavailable" and actual["amount"] is None,
                       "unavailable; no numeric value", actual, "missing_nutrient")
            else:
                record(tests, case["case_id"] + ":" + nutrient_id,
                       actual["status"] == "available" and Decimal(actual["amount"]) == Decimal(expected),
                       expected, actual, "source_calculation")

    banana, energy = foods["173944"], nutrients[("173944", "1008")]
    peanut, peanut_portion = foods["172470"], portions["90673"]
    equal("kcal_identity_not_kj", "89", fact(banana, energy, "100")["amount"], "unit_handling")
    reject("cross_food_nutrient", lambda: fact(banana, nutrients[("172470", "1008")], "100"), "identity")
    reject("cross_food_portion", lambda: mass(banana, peanut_portion, "1"), "identity")
    reject("kcal_field_with_kj_unit", lambda: fact(banana, {**energy, "unit_name": "kJ"}, "100"), "unit_handling", True)
    reject("unsupported_same_name_energy_id", lambda: fact(banana, {**energy, "nutrient_id": "1062", "unit_name": "kJ"}, "100"), "unit_handling", True)
    reject("wrong_reference_mass", lambda: fact(banana, {**energy, "reference_mass_g": "1"}, "100"), "basis", True)
    reject("wrong_reference_basis", lambda: fact(banana, {**energy, "reference_basis": "unknown"}, "100"), "basis", True)
    reject("different_source_type", lambda: fact({**banana, "source_data_type": "foundation_food"}, energy, "100"), "source_scope")
    reject("different_source_release", lambda: fact({**banana, "catalog_release": "2025-04"}, energy, "100"), "source_scope")
    for index, quantity in enumerate(("0", "-1", "NaN", "Infinity", "-Infinity", "unknown", True)):
        reject("invalid_mass_" + str(index), lambda q=quantity: fact(banana, energy, q))
        reject("invalid_household_count_" + str(index), lambda q=quantity: mass(peanut, peanut_portion, q))
    for raw in ("-1", "NaN", "Infinity", "bad"):
        reject("unusable_recorded_amount:" + raw, lambda r=raw: fact(banana, {**energy, "amount_per_100g_raw": r}, "100"), "invalid_source_value", True)
    reject("portion_footnote_gate", lambda: mass(peanut, {**peanut_portion, "footnote": "Unresolved source qualification"}, "1"), "portion_context")
    reject("unknown_portion_mode", lambda: mass(peanut, peanut_portion, "1", mode="generic_cup"), "portion_context")
    reject("missing_measure_description", lambda: mass(peanut, {**peanut_portion, "modifier": ""}, "1"), "portion_context")
    reject("zero_gram_weight", lambda: mass(peanut, {**peanut_portion, "gram_weight_raw": "0"}, "1"), "portion_context")
    reject("negative_source_quantity", lambda: mass(peanut, {**peanut_portion, "amount_raw": "-1"}, "1"), "portion_context")
    reject("zero_quantity_despite_stale_available_flag", lambda: mass(peanut, {**peanut_portion, "amount_raw": "0"}, "1", mode="same_defined_unit"), "portion_context")
    reject("numeric_exponent_technical_bound", lambda: fact(banana, energy, "1e1001"), "technical_numeric_limit")
    reject("numeric_digits_technical_bound", lambda: fact(banana, energy, "1" * 51), "technical_numeric_limit")
    # Arithmetic illustration is explicitly synthetic: source peanut butter is 32g.
    illustration = {**peanut_portion, "gram_weight_raw": "30", "portion_id": "999999999"}
    equal("synthetic_complete_2tbsp30g", "30", mass(peanut, illustration, "1", mode="complete_record")["grams"], "synthetic_contract")
    equal("synthetic_one_tbsp15g", "15", mass(peanut, illustration, "1", mode="same_defined_unit")["grams"], "synthetic_contract")
    equal("actual_complete_2tbsp32g", "32", mass(peanut, peanut_portion, "1", mode="complete_record")["grams"], "source_calculation")
    equal("actual_one_tbsp16g", "16", mass(peanut, peanut_portion, "1", mode="same_defined_unit")["grams"], "source_calculation")
    # The 18 bad source quantities are full-source boundary fixtures, not selected foods.
    for source in goldens["zero_amount_portion_boundary_cases"]:
        food = {"fdc_id": source["fdc_id"], "source_data_type": "sr_legacy_food", "catalog_release": "2018-04",
                "description": source["food_description"]}
        portion = source_portion(source)
        reject("zero_source_amount:" + source["id"], lambda f=food, p=portion: mass(f, p, "1", mode="same_defined_unit"), "full_source_portion_boundary")
    return tests, comparisons


if __name__ == "__main__":
    import csv
    import json
    from pathlib import Path
    import runpy
    import sys

    bundle = Path(__file__).resolve().parents[1]

    def read_csv(name):
        with (bundle / name).open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    food_rows = {r["fdc_id"]: r for r in read_csv("usda_foods.csv")}
    nutrient_rows = {(r["fdc_id"], r["nutrient_id"]): r for r in read_csv("usda_food_nutrients.csv")}
    portion_rows = {r["portion_id"]: r for r in read_csv("usda_food_portions.csv")}
    golden = json.loads((bundle / "development/usda_independent_source_goldens.json").read_text())
    results, source_checks = run_tests(runpy.run_path(str(bundle / "usda_food_reference.py")), food_rows, nutrient_rows, portion_rows, golden)
    failures = [r for r in [*results, *source_checks] if r["status"] != "pass"]
    print(f"Calculation cases: {len(results)} | Source comparisons: {len(source_checks)} | Failures: {len(failures)}")
    for row in failures:
        print(row)
    sys.exit(bool(failures))
