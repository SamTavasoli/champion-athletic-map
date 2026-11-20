"""Read-only, source-bound resources for the additive live demonstration.

No project runtime is imported and no source file is written. Resource matches
are narrow equipment/roles/space matches, not certification of age suitability,
supervision, medical safety, training load, or fulfillment of a skill goal.
"""

from collections import Counter
from copy import deepcopy
import csv
from decimal import Context, Decimal, DecimalException, localcontext
import hashlib
import io
import json
from pathlib import Path
import re


ACTIVE = "artifacts/language_model/active_resource_release.json"
CONTRACTS = "artifacts/evaluation/independent_assessment/reviewed_resource_contracts.json"
CONTRACTS_SHA = "bd6db60775d34b3bea351987d2c4139b83b5d9d9afb63ad539e1f6a3f693a416"
FOOD = "data/processed/usda_sr_legacy_2018_04/reference_ee67cf780262d24b"
# Frozen bindings recorded by the existing project's verified input inventory.
FOOD_HASHES = {
    "step14_food_reference_summary.json": "ee67cf780262d24bf02bcc7230104e65bcbfe6508b44f3c36eb03100d85295af",
    "usda_food_reference.py": "b665381f328e9ebfefbe8c42ef01e6905a7085dc4789290939194b4488b69136",
    "usda_foods.csv": "a4334b0ca87fd8881da84ab34fc50976e4d44cd1b1888adfbb210365d2976352",
    "usda_food_nutrients.csv": "a4b4f7b9049e24ebd34551578e9e858e24739bacd6b9db2383e2ed9e5e4a27ff",
    "usda_food_portions.csv": "e8d4fe83ac1f1fc35db06b066ce8a61751dd4756668ff2adcaaaf8a5f3c7d6a2",
    "usda_nutrient_definitions.json": "ad24c61b8acba1a3305101be092d98128e43fc9bbdd2c82d882598251474c2a9",
}
FIT_SCOPE = (
    "Source-described base equipment, participant roles and court context only. "
    "Age suitability, supervision, safety, training load and goal fulfillment remain unassessed."
)
COURTS = {"none": 0, "single_hoop_area": 1, "half_court": 2, "full_court": 3}
GOALS = {
    "dribbling": ("dribbl", "ball control", "ball handling", "ball-handling", "crossover"),
    "shooting": ("shoot", "shot", "free.throw"),
    "passing": ("pass",),
    "footwork": ("footwork", "pivot", "stopping"),
    "defense": ("defens", "closeout", "boxing out"),
    "finishing": ("finish", "lay.up", "layup", "floater"),
}
_ALIASES = {"ball": "basketball", "balls": "basketball", "basketballs": "basketball",
            "basket": "hoop", "baskets": "hoop", "hoops": "hoop",
            "basketball hoop": "hoop", "cone": "marker", "cones": "marker", "markers": "marker"}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _json(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON resource key: " + key)
            value[key] = item
        return value
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite resource value")))


def _read(root, relative, bindings, expected=None):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("A resource path must be project-relative")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("A resource path leaves the project")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError("Source hash mismatch: " + relative)
    if relative in bindings and bindings[relative] != digest:
        raise ValueError("A resource changed during loading: " + relative)
    bindings[relative] = digest
    return data


def _plain(text):
    return re.sub(r"\s+", " ", str(text).casefold().replace("–", "-").replace("—", "-")).strip().rstrip(".")


def _source_people(row):
    """Recognize explicit individual/pair/fixed roles; leave vague groups unknown."""
    text = _plain(row.get("participants", ""))
    if re.search(r"\bcoach\b|cue|leader|queue|\bline", text):
        return None
    if text in {"individual base activity", "individual base action", "individual ball-handlers"}:
        return 1
    if text in {"pairs", "partners", "shooting/rebounding partners", "shooting/passing partners", "two players per pair"}:
        return 2
    explicit = {
        "two active players per pair: attacker and defender": 2,
        "two active players: attacker and defender": 2,
        "three players": 3,
        "three active players: one attacker and two defenders": 3,
        "three active players: shooter, passer, and rebounder, rotating roles": 3,
        "four active players: three attackers and one defender": 4,
        "two teams of four": 8,
        "two teams of three active players": 6,
        "two teams of five": 10,
    }
    return explicit.get(text)


def _source_equipment(row):
    """Recognize complete, countable descriptions, never unspecified plural balls."""
    text = _plain(row.get("equipment", ""))
    one = {"basketball", "ball", "basketball.", "basketball, with sharing possible",
           "basketball per active player; sharing permitted", "basketball per active player; sharing permitted in base activity",
           "one basketball per player", "one basketball per pair"}
    hoop = {"basketball; basket", "ball; basket", "basketball and hoop", "basketball and a hoop",
            "ball per pair; basket", "one basketball per pair and access to a hoop"}
    if text in one:
        return {"basketball": 1}
    if text in hoop:
        return {"basketball": 1, "hoop": 1}
    if text == "two balls; basket":
        return {"basketball": 2, "hoop": 1}
    if text == "two basketballs per pair":
        return {"basketball": 2}
    return None


def _source_space(row):
    text = _plain(row.get("space", ""))
    if text in {"full court", "full basketball court", "court spanning both baselines, with free-throw and midcourt markings",
                "baseline start with movement to the opposite basket and back",
                "court with baseline, free-throw lines, half-court and opposite baseline"}:
        return "full_court"
    if text in {"beside basket", "basket area", "within a few feet of basket", "locations around a basket"}:
        return "single_hoop_area"
    # Only these recorded court contexts have a supported compact mapping.
    # New, conditional and negated descriptions stay unknown.
    if text in {"court space", "court", "baseline", "paint", "arc", "half court", "basketball court",
                "open court space", "court standing space", "court sideline", "court movement space",
                "court with hoop", "court with spacing between partners", "half court or three-point area",
                "half-court with sideline and baseline; up to two groups per half-court",
                "half-court with baseline; up to four pairs per half-court",
                "three-point line with top and wing spots plus access to the basket",
                "playing space inside the three-point line",
                "players spaced at least a lane width apart on the court; hoop attack follows"}:
        return "half_court"
    return None


def _normalize_drill(row, contract=None):
    people, equipment, space = _source_people(row), _source_equipment(row), _source_space(row)
    basis = "literal_source_setup" if all(x is not None for x in (people, equipment, space)) else "incomplete_source_setup"
    sharing = False
    if contract:
        people = contract["minimum_participants"]
        equipment = dict(contract["minimum_equipment"])
        context = contract["positive_space_context"]
        space = "single_hoop_area" if context == "hoop_area" else "half_court"
        if context == "hoop_area":
            equipment["hoop"] = 1
        basis = contract["contract_id"]
        sharing = people == 1 and "sharing" in row.get("instructions", "").casefold()
    equipment_list = None if equipment is None else [name for name, count in sorted(equipment.items()) for _ in range(count)]
    return {
        "id": row["catalog_candidate_id"], "name": row["drill_name"], "goal": row.get("primary_goal"),
        "instructions": row["instructions"], "equipment": equipment_list, "participants": people,
        "space": space, "source_url": row["source_url"], "source_prescription": row.get("source_prescription"),
        "age_constraints": {"minimum": None, "maximum": None, "suitability": "unknown"},
        "resource_requirements": {"equipment_counts": equipment, "participants": people, "space": space,
                                  "sharing_explicit": sharing, "basis": basis, "scope": FIT_SCOPE},
        "source_record": deepcopy(row),
    }


def _normalize_rule(row):
    # A complete existing source field, with no model or editorial rewrite.
    return {"id": row["candidate_rule_id"], "statement": row["display_name"],
            "source_url": row.get("source_url", ""),
            "qualifications": deepcopy(row.get("corrections_and_qualifications", [])),
            "enforcement": row.get("reviewed_enforcement"),
            "source_values": deepcopy(row.get("reviewed_threshold")),
            "source_unit": row.get("reviewed_unit")}


def _load_food(root, bindings):
    missing = [FOOD + "/" + name for name in FOOD_HASHES if not (root / FOOD / name).is_file()]
    if missing:
        # A partial snapshot must not disable basketball/rule lookup or become
        # a reason to manufacture demonstration food rows.
        return {"status": "unavailable", "rows": [], "nutrients": [], "missing_files": missing,
                "reason": "Frozen USDA dependencies are missing; food facts require the original complete reference."}
    payloads = {name: _read(root, FOOD + "/" + name, bindings, expected) for name, expected in FOOD_HASHES.items()}
    summary = _json(payloads["step14_food_reference_summary.json"])
    for name in FOOD_HASHES:
        if name != "step14_food_reference_summary.json":
            declared = summary.get("artifacts", {}).get(name, {}).get("sha256")
            if declared != FOOD_HASHES[name]:
                raise ValueError("Frozen food producer binding differs: " + name)
    rows = list(csv.DictReader(io.StringIO(payloads["usda_foods.csv"].decode("utf-8-sig"))))
    nutrients = list(csv.DictReader(io.StringIO(payloads["usda_food_nutrients.csv"].decode("utf-8-sig"))))
    ids = set()
    for row in rows:
        if (not str(row.get("fdc_id", "")).isdigit() or row["fdc_id"] in ids
                or not row.get("description") or row.get("source_data_type") != "sr_legacy_food"
                or row.get("catalog_release") != "2018-04"):
            raise ValueError("Invalid frozen food identity")
        ids.add(row["fdc_id"])
    if any(row.get("fdc_id") not in ids for row in nutrients):
        raise ValueError("A frozen nutrient has no food identity")
    return {"status": "available", "rows": rows, "nutrients": nutrients, "missing_files": [],
            "version": "sr-legacy-2018-04:" + FOOD_HASHES["step14_food_reference_summary.json"][:16],
            "nutrient_definitions": _json(payloads["usda_nutrient_definitions.json"])}


def load_resources(root: Path) -> dict:
    """Verify original frozen sources and return canonical, additive demo views."""
    root = Path(root).resolve()
    bindings = {}
    active = _json(_read(root, ACTIVE, bindings))
    if type(active) is not dict or set(active) != {"release_directory", "manifest_sha256"}:
        raise ValueError("Invalid active resource pointer")
    directory = active["release_directory"]
    manifest = _json(_read(root, directory + "/manifest.json", bindings, active["manifest_sha256"]))
    hashes = manifest.get("file_hashes")
    required = {"adopted_drills.json", "adopted_rules.json", "decisions.json"}
    if not isinstance(hashes, dict) or not required.issubset(hashes):
        raise ValueError("Approved resource manifest is incomplete")
    payloads = {}
    for name, digest in hashes.items():
        if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
            raise ValueError("Release payloads must be sibling files")
        payloads[name] = _json(_read(root, directory + "/" + name, bindings, digest))
    source_drills = payloads["adopted_drills.json"].get("records")
    source_rules = payloads["adopted_rules.json"].get("records")
    if not isinstance(source_drills, list) or not isinstance(source_rules, list):
        raise ValueError("Adopted records must be lists")
    by_id = {}
    held = set(payloads["decisions.json"].get("held_drill_ids", []))
    for row in source_drills:
        identifier = row.get("catalog_candidate_id") if isinstance(row, dict) else None
        if (not isinstance(identifier, str) or not identifier or identifier in by_id or identifier in held
                or row.get("approval_decision") != "approved_for_prototype"
                or not isinstance(row.get("instructions"), str) or not row["instructions"].strip()
                or not isinstance(row.get("source_url"), str) or not row["source_url"].startswith("https://")):
            raise ValueError("Invalid approved drill record")
        by_id[identifier] = row
    contracts = {}
    if (root / CONTRACTS).is_file():
        reviewed = _json(_read(root, CONTRACTS, bindings, CONTRACTS_SHA))
        if reviewed.get("resource_release_id") != manifest.get("release_id"):
            raise ValueError("Reviewed contracts refer to another resource release")
        for relative, expected in reviewed["source_file_sha256"].items():
            _read(root, relative, bindings, expected)
        for contract in reviewed["contracts"]:
            identifier = contract["source_catalog_id"]
            if identifier not in by_id or hashlib.sha256(_canonical(by_id[identifier])).hexdigest() != contract["source_record_sha256"]:
                raise ValueError("Reviewed contract source record differs")
            contracts[identifier] = contract
    rules, raw_rules, rule_ids = [], [], set()
    for row in source_rules:
        identifier = row.get("candidate_rule_id") if isinstance(row, dict) else None
        if not isinstance(identifier, str) or not identifier or identifier in rule_ids or row.get("enabled_for_planner") is not True:
            raise ValueError("Invalid adopted rule record")
        rule_ids.add(identifier)
        raw_rules.append(deepcopy(row))
        # The demonstration makes no age/grade or complete-schedule findings.
        # Keep its compact recovery context general and explicitly advisory.
        if identifier == "AAP_WEEKLY_SPORT_REST":
            rules.append(_normalize_rule(row))
    return {"drills": [_normalize_drill(row, contracts.get(identifier)) for identifier, row in by_id.items()],
            "rules": rules, "raw_rules": raw_rules, "food": _load_food(root, bindings), "source_files": bindings,
            "release_id": manifest["release_id"], "resource_fit_scope": FIT_SCOPE,
            "rule_context": {key: deepcopy(value) for key, value in payloads["adopted_rules.json"].items() if key != "records"}}


def _inventory(items):
    if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
        return None
    result = Counter()
    for item in items:
        text = _plain(item)
        match = re.fullmatch(r"(?:(\d+)\s+)?(.+)", text)
        if not match:
            return None
        number, name = match.groups()
        name = _ALIASES.get(name, name)
        # Presence alone establishes one object; a plural checkbox does not
        # establish the quantity needed by a two-marker or two-ball drill.
        quantity = int(number) if number is not None else 1
        if quantity < 0 or quantity > 1000:
            return None
        result[name] += quantity
    return result


def candidates(resources, goal, equipment: list[str], participants: int, court: str, age: int) -> list:
    """Return approved basketball base variants with explicit resource matches.

    Participant input is available people, not a source-derived prescription.
    Extra people are accepted only where the source explicitly permits sharing;
    unreported queues, coaches, resources and solo adaptations remain unknown.
    """
    inventory = _inventory(equipment)
    goal = _plain(goal)
    if (goal not in GOALS or inventory is None or type(participants) is not int or participants < 1
            or court not in COURTS or type(age) is not int or not 13 <= age <= 17):
        return []
    result = []
    for drill in resources.get("drills", []):
        raw = drill.get("source_record", {})
        if raw.get("scope") != "basketball_drill_candidate" or raw.get("approval_decision") != "approved_for_prototype":
            continue
        text = _plain(str(drill.get("goal", "")) + " " + drill.get("name", ""))
        if not any(re.search(pattern, text) for pattern in GOALS[goal]):
            continue
        facts = drill.get("resource_requirements", {})
        need, people, space = facts.get("equipment_counts"), facts.get("participants"), facts.get("space")
        if not isinstance(need, dict) or type(people) is not int or space not in COURTS:
            continue
        if (participants < people or (participants != people and not facts.get("sharing_explicit"))
                or COURTS[court] < COURTS[space] or any(inventory[name] < count for name, count in need.items())):
            continue
        item = deepcopy(drill)
        item["resource_match"] = "source_explicit_base_setup"
        item["eligibility_status"] = "unknown_beyond_resource_fit"
        result.append(item)
    return result


def food_options(resources) -> list:
    """Return exact frozen food identities, with no invented demonstration rows."""
    if resources.get("food", {}).get("status") != "available":
        return []
    return [{"id": row["fdc_id"], "name": row["description"]} for row in resources["food"]["rows"]]


def _decimal(value, label, positive=True):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(label + " must be a finite number")
    text = str(value).strip()
    if len(text) > 128 or not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", text):
        raise ValueError(label + " has an invalid numeric representation")
    number = Decimal(text)
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ValueError(label + " must be positive and finite" if positive else label + " must be nonnegative and finite")
    if len(number.as_tuple().digits) > 50 or not -1000 <= number.adjusted() <= 1000:
        raise ValueError(label + " exceeds the frozen helper's numeric limits")
    return number


def _number_text(value):
    if value == 0:
        return "0"
    text = format(value, "f") if -50 <= value.adjusted() <= 50 else str(value)
    return text.rstrip("0").rstrip(".") if "." in text and "e" not in text.lower() else text


def food_facts(resources, food_id, grams="100") -> dict:
    """Scale eligible frozen USDA fields by edible grams using Decimal only."""
    unavailable = {"status": "unavailable", "description": None, "grams": None, "nutrients": [], "source_refs": []}
    food = resources.get("food", {})
    if food.get("status") != "available":
        return {**unavailable, "reason": food.get("reason", "Frozen USDA reference is unavailable")}
    try:
        mass = _decimal(grams, "Requested edible mass")
    except (ValueError, DecimalException) as error:
        return {**unavailable, "status": "invalid_arguments", "reason": str(error)}
    identifier = str(food_id).strip() if not isinstance(food_id, bool) else ""
    matches = [row for row in food["rows"] if row["fdc_id"] == identifier]
    if not matches:
        matches = [row for row in food["rows"] if row["description"].casefold() == identifier.casefold()]
    if len(matches) != 1:
        return {**unavailable, "status": "ambiguous" if matches else "not_found", "grams": _number_text(mass),
                "reason": "Select one exact frozen food ID or description"}
    row = matches[0]
    nutrients = []
    units = {"1008": "KCAL", "1003": "G", "1004": "G", "1005": "G", "1079": "G"}
    for nutrient in food["nutrients"]:
        if nutrient.get("fdc_id") != row["fdc_id"]:
            continue
        item = {**deepcopy(nutrient), "name": nutrient.get("nutrient_name"), "amount": None,
                "unit": nutrient.get("unit_name"), "status": "unavailable", "reason": nutrient.get("numeric_status")}
        if nutrient.get("numeric_status") == "available":
            try:
                if (nutrient.get("nutrient_id") not in units or units[nutrient["nutrient_id"]] != nutrient.get("unit_name")
                        or nutrient.get("reference_basis") != "edible_food"
                        or _decimal(nutrient.get("reference_mass_g"), "Reference mass") != 100
                        or not str(nutrient.get("source_food_nutrient_id", "")).isdigit()
                        or int(nutrient["source_food_nutrient_id"]) <= 0):
                    raise ValueError("Unverified nutrient unit, identity or reference basis")
                amount = _decimal(nutrient.get("amount_per_100g_raw"), "Source amount", positive=False)
                with localcontext(Context(prec=50)):
                    scaled = amount * mass / Decimal(100)
                if scaled == 0 and amount != 0:
                    raise ValueError("Nutrient calculation underflow")
                item.update(amount=_number_text(scaled), status="available", reason=None)
            except (ValueError, DecimalException) as error:
                item["reason"] = str(error)
        nutrients.append(item)
    return {"status": "available", "food_id": row["fdc_id"], "description": row["description"],
            "grams": _number_text(mass), "nutrients": nutrients,
            "source_refs": [row["source_record_url"]] if row.get("source_record_url") else [],
            "source_record": deepcopy(row), "data_version": food.get("version"),
            "scope": "Food composition arithmetic only; no nutrition target or meal prescription."}
