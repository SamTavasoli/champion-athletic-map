"""Source-linked arithmetic helpers; importing or calling them activates no app tool."""
from dataclasses import asdict, dataclass
from decimal import Context, Decimal, DecimalException, localcontext
import re

_UNITS = {"1008": "KCAL", "1003": "G", "1004": "G", "1005": "G", "1079": "G"}
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
TECHNICAL_LIMITS = {"decimal_precision": 50, "max_significant_digits": 50,
                    "min_adjusted_exponent": -1000, "max_adjusted_exponent": 1000,
                    "max_numeric_text_length": 128}


@dataclass(frozen=True)
class _FoodIdentity:
    fdc_id: str
    description: str
    source_data_type: str
    catalog_release: str


def _identifier(value, label):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[0-9]+", str(value).strip()):
        raise ValueError(label + " must be a positive integer identifier.")
    identifier = str(int(str(value).strip()))
    if identifier == "0":
        raise ValueError(label + " must be positive.")
    return identifier


def _identity(food):
    fields = [str(food.get(key, "")).strip() for key in ("description", "source_data_type", "catalog_release")]
    if not all(fields) or any(food.get(key) is None for key in ("description", "source_data_type", "catalog_release")):
        raise ValueError("Food description, data type, and release must be recorded.")
    if fields[1:] != ["sr_legacy_food", "2018-04"]:
        raise ValueError("These helpers require the selected SR Legacy April 2018 reference.")
    result = asdict(_FoodIdentity(_identifier(food.get("fdc_id"), "fdc_id"), *fields))
    for field in ("NDB_number", "source_record_url", "source_archive_sha256", "source_food_table"):
        if field in food:
            result[field] = None if food[field] is None else str(food[field])
    return result


def _number(value, label, positive=True):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(label + " must be a finite number.")
    text = str(value).strip()
    if len(text) > TECHNICAL_LIMITS["max_numeric_text_length"] or not _NUMBER.fullmatch(text):
        raise ValueError(label + " has an unsupported numeric representation.")
    number = Decimal(text)
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ValueError(label + (" must be positive and finite." if positive else " must be nonnegative and finite."))
    if len(number.as_tuple().digits) > TECHNICAL_LIMITS["max_significant_digits"] or not (
            TECHNICAL_LIMITS["min_adjusted_exponent"] <= number.adjusted() <= TECHNICAL_LIMITS["max_adjusted_exponent"]):
        raise ValueError(label + " exceeds the helper's technical numeric limits.")
    return number


def _text(value):
    if value == 0:
        return "0"
    text = format(value, "f") if -50 <= value.adjusted() <= 50 else str(value)
    return text.rstrip("0").rstrip(".") if "." in text and "E" not in text and "e" not in text else text


def food_fact(food, nutrient, grams="100"):
    """Return one eligible fact or its field-level unavailability; requested mass is positive."""
    identity = _identity(food)
    if _identifier(nutrient.get("fdc_id"), "nutrient fdc_id") != identity["fdc_id"]:
        raise ValueError("Nutrient and food identities differ.")
    mass = _number(grams, "Requested edible mass")
    nutrient_id = _identifier(nutrient.get("nutrient_id"), "nutrient_id")
    status = nutrient.get("numeric_status")
    unit = None if nutrient.get("unit_name") is None else str(nutrient["unit_name"])
    reason = status if isinstance(status, str) else "missing_or_invalid_numeric_status"
    result = {**identity, "status": "unavailable", "reason": reason,
              "grams": _text(mass), "amount": None, "unit": unit,
              "nutrient_id": nutrient_id, "nutrient_name": None if nutrient.get("nutrient_name") is None else str(nutrient["nutrient_name"]),
              "source_food_nutrient_id": None if nutrient.get("source_food_nutrient_id") is None else str(nutrient["source_food_nutrient_id"]),
              "amount_per_100g_raw": str(nutrient.get("amount_per_100g_raw", "")),
              "reference_mass_g": None if nutrient.get("reference_mass_g") is None else str(nutrient["reference_mass_g"]),
              "reference_basis": None if nutrient.get("reference_basis") is None else str(nutrient["reference_basis"])}
    for field in ("source_footnote", "source_derivation_id", "source_derivation_code", "source_derivation_description"):
        if field in nutrient:
            result[field] = None if nutrient[field] is None else str(nutrient[field])
    if status != "available":
        return result
    if nutrient_id not in _UNITS or unit != _UNITS[nutrient_id]:
        result["reason"] = "unexpected_unit_or_unsupported_nutrient"
        return result
    if nutrient.get("reference_basis") != "edible_food":
        result["reason"] = "unverified_reference_basis"
        return result
    try:
        reference = _number(nutrient.get("reference_mass_g"), "Reference mass")
        amount = _number(nutrient.get("amount_per_100g_raw"), "Recorded nutrient amount", positive=False)
        source_id = _identifier(nutrient.get("source_food_nutrient_id"), "source_food_nutrient_id")
    except (ValueError, DecimalException):
        result["reason"] = "invalid_available_source_record"
        return result
    if reference != 100:
        result["reason"] = "unsupported_reference_mass"
        return result
    try:
        with localcontext(Context(prec=TECHNICAL_LIMITS["decimal_precision"])):
            calculated = amount * mass / reference
    except DecimalException as error:
        raise ValueError("The nutrient calculation cannot be represented.") from error
    if calculated == 0 and amount != 0:
        raise ValueError("The nutrient calculation underflowed its numeric context.")
    result.update(status="available", reason=None, amount=_text(calculated), source_food_nutrient_id=source_id)
    return result


def household_mass(food, portion, quantity="1", mode="complete_record"):
    """Return grams for copies of a complete record, or quantities of its same defined unit."""
    identity = _identity(food)
    if _identifier(portion.get("fdc_id"), "portion fdc_id") != identity["fdc_id"]:
        raise ValueError("Portion and food identities differ.")
    if mode not in {"complete_record", "same_defined_unit"}:
        raise ValueError("Unknown household conversion mode.")
    flag = portion.get("household_numeric_screen_pass")
    if not (flag is True or isinstance(flag, str) and flag.strip().casefold() == "true"):
        raise ValueError("The portion has not passed its numeric screen.")
    if portion.get("household_eligibility", "available") != "available":
        raise ValueError("The portion is unavailable for household conversion.")
    if "footnote" not in portion or portion["footnote"] is None:
        raise ValueError("The portion footnote state is unknown.")
    modifier = str(portion.get("modifier") or "").strip()
    footnote = str(portion.get("footnote") or "").strip()
    if not modifier or footnote:
        raise ValueError("A missing measure description or unreviewed footnote prevents conversion.")
    count = _number(quantity, "Requested quantity")
    amount = _number(portion.get("amount_raw"), "Recorded portion quantity")
    weight = _number(portion.get("gram_weight_raw"), "Recorded portion gram weight")
    portion_id = _identifier(portion.get("portion_id"), "portion_id")
    measure_id = _identifier(portion.get("measure_unit_id"), "measure_unit_id")
    try:
        with localcontext(Context(prec=TECHNICAL_LIMITS["decimal_precision"])):
            mass = count * weight if mode == "complete_record" else count / amount * weight
    except DecimalException as error:
        raise ValueError("The portion calculation cannot be represented.") from error
    if mass <= 0:
        raise ValueError("The portion calculation underflowed its numeric context.")
    return {**identity, "status": "available", "grams": _text(mass), "quantity": _text(count), "mode": mode,
            "portion_id": portion_id, "amount_raw": str(portion["amount_raw"]),
            "gram_weight_raw": str(portion["gram_weight_raw"]), "modifier": modifier,
            "measure_unit_id": measure_id,
            "unit_name": None if portion.get("unit_name") is None else str(portion["unit_name"]), "footnote": footnote}
