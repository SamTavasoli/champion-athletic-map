"""Assess declared compatibility and narrow source-backed resource proofs separately."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re


VERSION = "independent-resource-assessment-1"
CONTRACT_VERSION = "reviewed-resource-contracts-1"
_ALIASES = {"ball": "basketball", "balls": "basketball", "basketballs": "basketball",
    "cone": "marker", "cones": "marker", "markers": "marker", "basket": "hoop",
    "basketball hoop": "hoop", "basketball hoops": "hoop", "hoops": "hoop"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def _read(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate resource-contract key.")
            value[key] = item
        return value
    return json.loads(path.read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite contract value.")))


def _path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("A resource-contract path leaves the project.")
    return path


def load_contracts(root, path):
    """Verify the contracts against the active, unchanged adopted source records."""
    root = Path(root).resolve()
    location = Path(path)
    location = location.resolve() if location.is_absolute() else _path(root, location)
    if not location.is_relative_to(root):
        raise ValueError("The resource contract must remain inside the project.")
    bundle = _read(location)
    if bundle.get("schema_version") != CONTRACT_VERSION:
        raise ValueError("An unrecognized resource contract version was supplied.")
    for relative, expected in bundle["source_file_sha256"].items():
        if sha(_path(root, relative).read_bytes()) != expected:
            raise ValueError("A reviewed resource source changed: " + relative)
    pointer = _read(root / "artifacts/language_model/active_resource_release.json")
    manifest = _read(_path(root, pointer["release_directory"] + "/manifest.json"))
    if (manifest["release_id"] != bundle["resource_release_id"]
            or sha(_path(root, pointer["release_directory"] + "/manifest.json").read_bytes()) != pointer["manifest_sha256"]):
        raise ValueError("The active resource release differs from the reviewed contracts.")
    adopted = _read(_path(root, pointer["release_directory"] + "/adopted_drills.json"))
    records = {row["catalog_candidate_id"]: row for row in adopted["records"]}
    decisions = _read(_path(root, pointer["release_directory"] + "/decisions.json"))
    seen = set()
    for contract in bundle["contracts"]:
        identifier = contract["contract_id"]
        record = records.get(contract["source_catalog_id"])
        if (identifier in seen or record is None or record.get("approval_decision") != "approved_for_prototype"
                or sha(canonical(record)) != contract["source_record_sha256"]
                or not isinstance(contract.get("description_patterns"), list) or not contract["description_patterns"]
                or contract.get("positive_space_context") not in ("court", "hoop_area", "marker_gap")):
            raise ValueError("A reviewed resource contract has an invalid source or shape.")
        seen.add(identifier)
        for pattern in contract["description_patterns"]:
            re.compile(pattern)
    if not seen or len(bundle["contracts"]) != bundle["declared_contract_count"]:
        raise ValueError("The declared resource proof coverage differs from its contracts.")
    return {**deepcopy(bundle), "held_catalog_ids": list(decisions["held_drill_ids"]),
        "catalog_aliases": deepcopy(adopted["aliases"]), "contract_file_sha256": sha(location.read_bytes()),
        "source_bindings_verified": True}


def _combine(statuses):
    values = list(statuses)
    return "violated" if "violated" in values else "unknown" if "unknown" in values else "met" if "met" in values else "not_applicable"


def _name(value):
    text = str(value).casefold().strip()
    return _ALIASES.get(text, text)


def _inventory(value):
    if not isinstance(value, list):
        return None, set(), ["Equipment quantities are not fully reported."]
    known, unknown, issues = {}, set(), []
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip():
            issues.append("An equipment item has no usable name.")
            continue
        name, quantity = _name(row["name"]), row.get("quantity")
        if type(quantity) is int and quantity >= 0:
            known[name] = known.get(name, 0) + quantity
        else:
            unknown.add(name)
    return known, unknown, issues


def _need(known, unknown, name, quantity):
    if known is None:
        return "unknown"
    if known.get(name, 0) >= quantity:
        return "met"
    return "unknown" if name in unknown else "violated"


def _space_kind(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.casefold().replace("_", " ").strip()
    if text in ("full court", "full basketball court"):
        return "full_court"
    if text in ("half court", "half basketball court"):
        return "half_court"
    if text in ("single hoop area", "within a few feet of the hoop", "close to the hoop", "beside the basket"):
        return "hoop_area"
    if text in ("basketball court", "court", "clear court space"):
        return "court"
    if text in ("designated practice area", "clear practice area", "clear space"):
        return "clear_area"
    if text in ("none", "no space needed"):
        return "none"
    return None


def _declared(public, activity):
    states, reasons = [], []
    declared = activity.get("resources")
    if not isinstance(declared, dict):
        return "unknown", ["Activity resource requirements were not fully declared."]
    supply, uncertain_supply, bad_supply = _inventory(public.get("equipment"))
    need, uncertain_need, bad_need = _inventory(declared.get("equipment"))
    if bad_supply or bad_need:
        states.append("unknown"); reasons.extend(bad_supply + bad_need)
    if need is None:
        states.append("unknown")
    else:
        for name, quantity in need.items():
            status = _need(supply, uncertain_supply, name, quantity)
            states.append(status)
            if status != "met":
                reasons.append("Declared " + name + " quantity is " + ("unavailable." if status == "violated" else "unverified."))
        if uncertain_need:
            states.append("unknown"); reasons.append("An activity equipment quantity is unknown.")
    people, available = declared.get("participants"), public.get("participants_available")
    if type(people) is not int or people < 0 or type(available) is not int or available < 0:
        states.append("unknown"); reasons.append("Activity or available participant count is unknown.")
    elif people == 0:
        states.append("violated"); reasons.append("A training activity declares zero participants.")
    elif people > available:
        states.append("violated"); reasons.append("Declared participants exceed availability.")
    else:
        states.append("met")
    space, supplied = _space_kind(declared.get("space")), public.get("space")
    if not isinstance(supplied, dict) or space is None:
        states.append("unknown"); reasons.append("Declared space requirements are outside the reviewed literal grammar.")
    else:
        court = supplied.get("court_access")
        rank = {"none": 0, "single_hoop_area": 1, "half_court": 2, "full_court": 3}
        if space in ("full_court", "half_court"):
            if court not in rank:
                states.append("unknown"); reasons.append("Court access is unknown.")
            elif rank[court] < rank[space]:
                states.append("violated"); reasons.append("Declared court access exceeds availability.")
            else:
                states.append("met")
        elif space == "court":
            states.append("met" if court in ("half_court", "full_court") else "unknown")
        elif space == "hoop_area":
            hoop = supplied.get("hoop_access")
            states.append("violated" if hoop is False else "met" if hoop is True and court in ("single_hoop_area", "half_court", "full_court") else "unknown")
            if hoop is False:
                reasons.append("The declared basket/hoop area is unavailable.")
        else:
            states.append("met" if isinstance(supplied.get("usable_area_description"), str) and supplied["usable_area_description"].strip() else "unknown")
        restrictions = supplied.get("restrictions")
        if type(restrictions) is not list or restrictions:
            states.append("unknown"); reasons.append("Space restrictions require a separate semantic review.")
    return _combine(states), list(dict.fromkeys(reasons))


def _text(value):
    return re.sub(r"\s+", " ", value.casefold().replace("–", "-").replace("—", "-").replace("’", "'")).strip().rstrip(".")


def _proof(public, activity, contract, mode):
    states, reasons = [], []
    supply, unknown_supply, bad_supply = _inventory(public.get("equipment"))
    declared = activity.get("resources")
    if not isinstance(declared, dict):
        return "unknown", ["The structured resource declaration is incomplete."]
    needed, unknown_needed, bad_needed = _inventory(declared.get("equipment"))
    if bad_supply or bad_needed:
        states.append("unknown"); reasons.extend(bad_supply + bad_needed)
    for name, quantity in contract["minimum_equipment"].items():
        actual = _need(supply, unknown_supply, name, quantity)
        stated = _need(needed, unknown_needed, name, quantity)
        states.extend((actual, stated))
        if actual != "met":
            reasons.append("The described action's reviewed " + name + " requirement is " + ("not available." if actual == "violated" else "unknown."))
        if stated != "met":
            reasons.append("The declared resources do not establish the described action's required " + name + ".")
    minimum = contract["minimum_participants"]
    if mode == "sharing" and minimum == 1:
        minimum = 2
    available, declared_people = public.get("participants_available"), declared.get("participants")
    for value, label in ((available, "Available"), (declared_people, "Declared")):
        if type(value) is not int or value < 0:
            states.append("unknown"); reasons.append(label + " participants are unknown.")
        elif value < minimum:
            states.append("violated"); reasons.append(label + " participants cannot fill the described roles.")
        else:
            states.append("met")
    if mode == "individual" and declared_people != 1:
        states.append("unknown"); reasons.append("Additional declared participants have no explicit sharing/role arrangement.")
    supplied = public.get("space")
    if not isinstance(supplied, dict):
        supplied = {}
    declared_space = _space_kind(declared.get("space"))
    if declared_space is None:
        states.append("unknown"); reasons.append("The activity's declared practice space is unverified.")
    elif declared_space == "none":
        states.append("violated"); reasons.append("The described physical activity cannot declare that no practice space is needed.")
    court, hoop = supplied.get("court_access"), supplied.get("hoop_access")
    context = contract["positive_space_context"]
    if context in ("court", "marker_gap"):
        states.append("met" if court in ("half_court", "full_court") else "unknown")
        if court not in ("half_court", "full_court"):
            reasons.append("This source-context proof does not cover the reported space adaptation.")
    else:
        if hoop is False:
            states.append("violated"); reasons.append("Close-range shooting requires a hoop which is reported unavailable.")
        elif hoop is not True or court not in ("single_hoop_area", "half_court", "full_court"):
            states.append("unknown"); reasons.append("The required close-range basket area is unverified.")
        else:
            states.append("met")
    if type(supplied.get("restrictions")) is not list or supplied.get("restrictions"):
        states.append("unknown"); reasons.append("Narrative or unreported restrictions remain outside this narrow proof.")
    return _combine(states), list(dict.fromkeys(reasons))


def assess_resources(public_input, activities, contracts):
    """Apply the same source-neutral resource criteria to every workflow output."""
    if not isinstance(public_input, dict) or not isinstance(activities, list):
        raise ValueError("Resource assessment requires a public object and a list of newly prescribed activities.")
    if contracts.get("schema_version") != CONTRACT_VERSION:
        raise ValueError("The reviewed resource contract version is required.")
    details = []
    for index, item in enumerate(activities):
        activity = item.get("activity", item) if isinstance(item, dict) else None
        if not isinstance(activity, dict):
            details.append({"activity_index": index, "activity_id": None, "declared_status": "unknown", "requirements_status": "unknown",
                "reasons": ["The activity is not a usable object."], "contract_id": None, "eligibility_status": "unknown"})
            continue
        declared_status, declared_reasons = _declared(public_input, activity)
        description = activity.get("description")
        matches = []
        if isinstance(description, str):
            text = _text(description)
            for contract in contracts["contracts"]:
                for pattern in contract["description_patterns"]:
                    found = re.fullmatch(pattern, text)
                    if found:
                        matches.append((contract, "sharing" if found.groupdict().get("sharing") else "individual" if contract["minimum_participants"] == 1 else "paired"))
                        break
        identifiers = activity.get("evidence_refs") or []
        held = {value for value in identifiers if isinstance(value, str)} & set(contracts.get("held_catalog_ids", [])) if isinstance(identifiers, list) else set()
        eligibility = "violated" if held else "not_applicable"
        contract_id, source_id, evidence_reasons = None, None, []
        if held:
            proof_status = "unknown"; evidence_reasons.append("A cited drill is held and unavailable for an eligible resource proof.")
        elif len(matches) != 1:
            proof_status = "unknown"; evidence_reasons.append("The complete activity description is outside the reviewed action/setup/role grammar; a name or source ID alone is insufficient.")
        else:
            contract, mode = matches[0]
            contract_id, source_id = contract["contract_id"], contract["source_catalog_id"]
            proof_status, evidence_reasons = _proof(public_input, activity, contract, mode)
        details.append({"activity_index": index, "activity_id": activity.get("activity_id"),
            "declared_status": declared_status, "requirements_status": proof_status,
            "contract_id": contract_id, "source_catalog_id": source_id, "eligibility_status": eligibility,
            "reasons": list(dict.fromkeys(declared_reasons + evidence_reasons)), "catalog_id_required": False})
    checks = []
    for identifier, field, reason in (("declared_resource_consistency", "declared_status", "Compatibility of the activity's declared quantities, people and space with supplied availability."),
            ("resource_requirements_evidence", "requirements_status", "Resource fit of a complete action/setup/role description under a source-bound reviewed contract.")):
        checks.append({"check_id": identifier, "status": _combine(row[field] for row in details),
            "reason": reason if details else "No newly added activity requires resource assessment; task/calendar gates are separate.",
            "observed": {"activities": len(details), "met": sum(row[field] == "met" for row in details),
                "violated": sum(row[field] == "violated" for row in details), "unknown": sum(row[field] == "unknown" for row in details)},
            "checker_version": VERSION})
    return {"checks": checks, "per_activity": details, "coverage": {"version": VERSION,
        "resource_release_id": contracts["resource_release_id"], "reviewed_contracts": len(contracts["contracts"]),
        "source_neutral_description_matching": True, "catalog_ids_required": False,
        "universal_free_text_resource_verification": False, "clinical_safety_certified": False,
        "duration_supervision_and_goal_fulfillment_assessed_here": False}}
