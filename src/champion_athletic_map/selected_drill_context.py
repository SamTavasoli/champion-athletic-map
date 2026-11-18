"""Select complete approved drill references directly from the active release."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

VERSION = "public-goal-drill-context-1"
BUDGET_BASIS = "lossless-food-model-view-1"
QUERY_VERSION = "public-two-query-1"
_NOTICE = "References are evidence, not a feasibility, age-eligibility or safety certification. Use only complete reviewed variants and retain their conditions; ask about missing facts."
_FOOD_KEYS = {"food_id", "search_text", "grams", "portion_id", "multiplier"}
_DRILL_FIELDS = ("catalog_candidate_id", "drill_name", "scope", "approved_variant", "instructions", "primary_goal",
    "primary_goal_provenance", "secondary_skills", "equipment", "participants", "minimum_participants", "space",
    "source_prescription", "duration_minutes", "rest_seconds", "solo_adaptation", "source_curriculum_level", "source_url",
    "source_representation", "publisher_attribution", "content_provenance", "content_use_scope", "use_conditions",
    "age_eligibility_inferred", "medical_suitability_certified")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate reference key.")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite reference value.")))


def _public(prepared):
    public = prepared["public_input"]
    text = _json(public)
    if (prepared.get("schema_version") != "step24-prepared-public-input-1"
            or text != prepared["model_visible_json"]
            or _sha(text.encode()) != prepared["audit"]["public_input_sha256"]):
        raise ValueError("The prepared public input changed.")
    return public


def _short(value, limit):
    value = "unknown" if value is None else value if isinstance(value, str) else _json(value)
    return " ".join(value.split())[:limit]


def make_queries(prepared):
    p = _public(prepared)
    names = None if p.get("equipment") is None else [x.get("name") for x in p["equipment"]]
    kinds = None if p.get("existing_commitments") is None else sorted({str(x.get("activity_kind") or "unknown") for x in p["existing_commitments"]})
    return ["; ".join(("Basketball practice", _short(p["athlete_request"], 32), "goals " + _short(p.get("goals"), 24),
        "experience " + _short(p.get("basketball_background"), 12), "equipment " + _short(names, 24),
        "space " + _short((p.get("space") or {}).get("court_access"), 12), "people " + _short(p.get("participants_available"), 4)))[:180],
        "; ".join(("Youth basketball participation, rest and recovery", "age " + _short(p.get("age"), 4),
        "grade " + _short(p.get("school_grade"), 4), "commitments " + _short(kinds, 42), "request " + _short(p["athlete_request"], 45)))[:180]]


def model_payload(payload):
    """Same reversible nutrient factoring as food_reference_encoding.encode_view."""
    result = deepcopy(payload)
    for lookup in result.get("food_lookup", []):
        data = lookup.get("data")
        if not isinstance(data, dict):
            continue
        rows = data.get("nutrients")
        if not isinstance(rows, list) or len(rows) < 2 or any(type(row) is not dict for row in rows):
            continue
        shared = {key: deepcopy(value) for key, value in rows[0].items()
                  if all(key in row and _json(row[key]) == _json(value) for row in rows[1:])}
        if not shared:
            continue
        encoded = {"encoding": "shared-fields-1", "shared": shared,
                   "rows": [{key: deepcopy(value) for key, value in row.items() if key not in shared} for row in rows]}
        if len(_json(encoded).encode("utf-8")) < len(_json(rows).encode("utf-8")):
            data["nutrients"] = encoded
    return result


def load_approved_catalog(root):
    """Verify the pointer, manifest and every release payload before ranking IDs."""
    root = Path(root).resolve()
    pointer_path = root / "artifacts/language_model/active_resource_release.json"
    pointer = _read(pointer_path)
    if set(pointer) != {"release_directory", "manifest_sha256"}:
        raise ValueError("Invalid active resource pointer.")
    relative = pointer["release_directory"]
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("The resource release leaves the project.")
    folder = (root / relative).resolve()
    if folder == root or not folder.is_relative_to(root):
        raise ValueError("The resource release leaves the project.")
    manifest_path = (folder / "manifest.json").resolve()
    if not manifest_path.is_relative_to(folder):
        raise ValueError("The resource manifest leaves its release.")
    raw = manifest_path.read_bytes()
    if _sha(raw) != pointer["manifest_sha256"]:
        raise ValueError("The active resource manifest changed.")
    manifest = _read(manifest_path)
    hashes = manifest.get("file_hashes")
    if not isinstance(hashes, dict) or not {"adopted_drills.json", "decisions.json", "adopted_rules.json"} <= set(hashes):
        raise ValueError("The approved release is incomplete.")
    for name, expected in hashes.items():
        if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
            raise ValueError("Invalid release payload path.")
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or _sha(path.read_bytes()) != expected:
            raise ValueError("An approved release payload changed: " + name)
    drills = _read(folder / "adopted_drills.json")
    decisions = _read(folder / "decisions.json")
    held, records = set(decisions["held_drill_ids"]), {}
    for row in drills["records"]:
        identifier = row.get("catalog_candidate_id")
        if not isinstance(identifier, str) or identifier in records or identifier in held:
            raise ValueError("Approved drill IDs are duplicated or held.")
        records[identifier] = row
    return {"records": records, "held_ids": sorted(held), "release_id": manifest["release_id"],
            "release_manifest_sha256": pointer["manifest_sha256"], "active_resource_pointer_sha256": _sha(pointer_path.read_bytes()),
            "adopted_drills_sha256": hashes["adopted_drills.json"]}


_CONCEPT = {"defensive": "defense", "defender": "defense", "defend": "defense", "shooting": "shoot",
    "shot": "shoot", "shots": "shoot", "finishing": "finish", "layup": "finish", "layups": "finish",
    "passing": "pass", "passes": "pass", "dribbling": "control", "dribble": "control", "handling": "control",
    "ballhandling": "control", "direction": "agility", "directions": "agility", "crossover": "agility",
    "lateral": "agility", "laterally": "agility", "sliding": "agility", "slide": "agility", "jab": "agility",
    "awareness": "position", "positioning": "position", "spacing": "position", "conditioning": "endurance"}
_STOP = set("a an additional and as at availability ball be basketball by can daily every extra for from give goal help i improve in including is it limits listed me my of on only organize plan please practice practices priority provide provided request resources session sessions stated stay the this time to training two use using want week weekly with work".split())
_SKILLS = {"agility", "control", "defense", "footwork", "shoot", "finish", "pass", "position", "endurance",
           "rebound", "rebounding", "coordination", "balance", "decision", "decisions", "speed", "strength"}


def _terms(value):
    return {_CONCEPT.get(w, w) for w in re.findall(r"[a-z]+", str(value).lower().replace("lay-up", "layup")) if w not in _STOP}


def _conditions(public, row):
    """Screen explicit conflicts only; narrative or missing conditions stay unknown."""
    conflicts, unknowns = [], []
    inventory = public.get("equipment")
    known = {str(x.get("name", "")).lower(): x.get("quantity") for x in inventory or []}
    equip, space, people = (str(row.get(k) or "").lower() for k in ("equipment", "space", "participants"))
    supplied = public.get("space") or {}
    if re.search(r"\b(?:baskets?|hoops?|paint|key|wings?)\b", equip + " " + space) and supplied.get("hoop_access") is False:
        conflicts.append("The source requires basket/court positions but hoop access is explicitly false.")
    court = supplied.get("court_access")
    if "full court" in space.replace("-", " ") and court in ("none", "single_hoop_area", "half_court"):
        conflicts.append("The source requires a full court which is not available.")
    elif any(word in space for word in ("court", "baseline", "sideline", "key", "wing")) and court in ("none", "single_hoop_area"):
        conflicts.append("The source court/line setup is not available; no space adaptation is approved here.")
    if re.search(r"\bball|basketball", equip) and "optional" not in equip and "no ball" not in equip:
        value = known.get("basketball", known.get("ball", 0 if isinstance(inventory, list) else None))
        if type(value) is int and value < 1:
            conflicts.append("The required basketball is explicitly unavailable.")
        elif value is None:
            unknowns.append("The basketball quantity is not confirmed.")
        if "per player" in equip and "sharing" not in equip:
            n = public.get("participants_available")
            if type(value) is int and type(n) is int and n > value:
                conflicts.append("Source basketball-per-player requirement exceeds supplied balls; no sharing variant was approved.")
    if any(word in equip for word in ("marker", "cone")):
        value = known.get("cones", known.get("markers", 0 if isinstance(inventory, list) else None))
        minimum = 2 if "two" in equip else 5 if "five" in equip else 3 if "three" in equip else None
        if minimum is not None and type(value) is int and value < minimum:
            conflicts.append("Explicit source marker/cone requirement exceeds supply.")
        elif minimum is None or type(value) is not int:
            unknowns.append("The required marker/cone quantity is not fully established.")
    n = public.get("participants_available")
    minimum = row.get("minimum_participants")
    if minimum is None and any(word in people for word in ("partner", "pair", "two players")):
        minimum = 2
    if minimum is None:
        for word, number in (("five", 5), ("four", 4), ("three", 3), ("two", 2)):
            if re.search(r"\b" + word + r"[ -](?:active[ -])?players?\b", people):
                minimum = number
                break
    if minimum is None and any(word in people for word in ("individual", "one player", "one participant")):
        minimum = 1
    if minimum is None and "players and coach" in people:
        minimum = 2
    if type(n) is not int:
        unknowns.append("Participant availability is unknown.")
    elif type(minimum) is int and n < minimum:
        conflicts.append("Available people cannot fill the explicit source roles.")
    elif minimum is None:
        unknowns.append("The complete source staffing requirement is not numerically established.")
    if "coach" in people:
        unknowns.append("Source coach/cue-leader availability has not been established.")
    if supplied.get("restrictions"):
        unknowns.append("Narrative space restrictions and one-active-player role arrangements require review.")
    unknowns.append("Age eligibility, supervision, skill prerequisites and complete feasibility are not certified by reference selection.")
    return {"known_conflicts": conflicts, "unknowns": list(dict.fromkeys(unknowns)), "feasibility_certified": False}


def rank_drills(public, catalog):
    goal = _terms(" ".join(public.get("goals") or []) + " " + public["athlete_request"]) & _SKILLS
    rows, excluded = [], []
    for identifier, row in sorted(catalog["records"].items()):
        if (row.get("approval_decision") != "approved_for_prototype" or row.get("scope") != "basketball_drill_candidate"
                or row.get("age_eligibility_inferred") is not False or row.get("medical_suitability_certified") is not False):
            excluded.append({"id": identifier, "reason": "Not an approved basketball base variant with unclaimed age/medical suitability."})
            continue
        hits = goal & _terms(" ".join(str(row.get(k) or "") for k in ("primary_goal", "drill_name", "instructions", "secondary_skills")))
        score = 6 * len(goal & _terms(row.get("primary_goal"))) + 3 * len(goal & _terms(row.get("drill_name"))) + len(hits)
        conditions = _conditions(public, row)
        if not hits or conditions["known_conflicts"]:
            excluded.append({"id": identifier, "reason": "No public-goal match." if not hits else "Known public/source resource conflict.", **conditions})
            continue
        rows.append({"id": identifier, "public_term_matches": sorted(hits), "relevance_score": score, **conditions})
    rows.sort(key=lambda x: (-x["relevance_score"], len(x["unknowns"]), x["id"]))
    return rows, excluded


def _tool(result):
    keys = ("status", "data", "issues", "source_refs", "data_version")
    if not isinstance(result, dict) or not set(keys) <= set(result):
        raise ValueError("A reference lookup returned an invalid envelope.")
    if result["status"] in {"execution_error", "technical_error", "error", "failed"}:
        raise RuntimeError("A reference lookup failed: " + "; ".join(result.get("issues") or []))
    return deepcopy({key: result[key] for key in keys})


def _food_requests(question):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate public food argument.")
            result[key] = value
        return result
    try:
        parsed = json.loads(question, object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite public food argument.")))
        requests = parsed if isinstance(parsed, list) else [parsed]
        if requests == [] or all(isinstance(x, dict) and x and set(x) <= _FOOD_KEYS for x in requests):
            return requests, "explicit_public_json_arguments"
    except (TypeError, ValueError):
        pass
    match = re.fullmatch(r'For the food "([^"\r\n]+)", how many (?:grams of protein|kilocalories of energy) are recorded for ([0-9]+(?:\.[0-9]+)?) g\?', question)
    return ([{"search_text": match[1], "grams": match[2]}], "literal_quoted_name_and_grams") if match else ([{"search_text": question}], "description_only_no_quantity_inference")


def _rule_groups(rows):
    groups = {}
    for row in rows:
        if row.get("record_kind") not in ("structured_reference", "general_guidance") or row.get("applicability_assessment", {}).get("status") == "not_applicable":
            continue
        concept = re.sub(r"^NBA_(A12_14|G9_12)_", "NBA_", row["candidate_rule_id"])
        groups.setdefault(concept, []).append(deepcopy(row))
    def key(item):
        concept, group = item
        return (not any(str(r.get("reviewed_enforcement") or "").startswith("required") for r in group),
                next((i for i, text in enumerate(("MAX_HOURS", "MIN_REST", "SLEEP", "PRACTICE_LENGTH")) if text in concept), 4), concept)
    return [sorted(g, key=lambda x: x["candidate_rule_id"]) for _, g in sorted(groups.items(), key=key)]


def build_packet(prepared, tools, ranked_lists, count_tokens, policy):
    public = _public(prepared)
    limit, rule_limit = policy.get("max_packet_tokens", 2200), policy.get("max_rule_bundles", 2)
    if type(limit) is not int or limit != 2200 or type(rule_limit) is not int or not 0 <= rule_limit <= 2:
        raise ValueError("The reviewed packet keeps the 2200-token limit and at most two whole rule bundles.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(policy.get("source_configuration_sha256"))):
        raise ValueError("The reference source configuration hash is required.")
    catalog = load_approved_catalog(tools.root)
    for key in ("resource_release_manifest_sha256", "active_resource_pointer_sha256"):
        actual = catalog["release_manifest_sha256" if key.startswith("resource_release") else key]
        if key in policy and policy[key] != actual:
            raise ValueError("The active approved release differs from the reference policy.")
    def tokens(value):
        n = count_tokens(_json(model_payload(value)))
        if type(n) is not int or n < 0:
            raise ValueError("Invalid packet token count.")
        return n
    def fits(value):
        return tokens(value) <= limit
    rule_result = _tool(tools.get_planning_rules(public.get("age"), public.get("school_grade")))
    data = rule_result["data"] or {}
    payload = {"references": [], "catalog_records": [], "planning_rules": {"status": rule_result["status"], "rules": [], "validator_execution_ready": False},
               "context_limitations": [_NOTICE], "catalog_selection": {"status": "not_requested", "feasibility_certified": False}}
    trace = {"queries": make_queries(prepared), "ranked_lists": deepcopy(ranked_lists), "rule_lookup": rule_result,
             "food_lookups": [], "catalog_lookups": [], "omissions": [], "drill_selection": {}, "approved_release": {k: v for k, v in catalog.items() if k != "records"}}
    food_mode = "not_requested"
    if isinstance(public.get("food_question"), str) and public["food_question"].strip():
        requests, food_mode = _food_requests(public["food_question"])
        payload["food_lookup"] = []
        for arguments in requests[:2]:
            result = _tool(tools.lookup_food(**arguments)); payload["food_lookup"].append(result)
            trace["food_lookups"].append({"arguments": arguments, "result": result})
        trace["omissions"].extend({"kind": "food", "position": i, "reason": "two_food_limit"} for i in range(2, len(requests)))
    if not fits(payload):
        raise ValueError("Complete requested food facts do not fit the lossless model-view budget.")
    medical = bool(re.search(r"injury rehabilitation|(?:personalized|exact) daily calorie|exact meal portions|diagnos", public["athlete_request"], re.I))
    ranking, excluded = rank_drills(public, catalog) if not medical else ([], [])
    trace["drill_selection"] = {"basis": "Public request/goals and explicit resource conflicts only; relevance is not eligibility.", "ranked": ranking,
                                "excluded": excluded, "not_requested_reason": "Medical/dietary prescription request; no drill prescription context selected." if medical else None}
    if not medical:
        payload["catalog_selection"]["status"] = "unavailable"
        for candidate in ranking[:5]:
            identifier = candidate["id"]
            result = _tool(tools.get_drill(identifier))
            trace["catalog_lookups"].append({"kind": "drill", "id": identifier, "result": result})
            row = catalog["records"][identifier]
            expected = {key: deepcopy(row[key]) for key in _DRILL_FIELDS if key in row}
            expected.update(requested_drill_id=identifier, canonical_drill_id=identifier, alias_resolved=False)
            if result["status"] != "found" or result["data"] != expected or result["data_version"] != catalog["release_id"]:
                raise ValueError("The public drill lookup differs from its verified complete approved variant.")
            trial = deepcopy(payload)
            trial["catalog_records"] = [{"kind": "drill", "requested_id": identifier, **result}]
            trial["catalog_selection"] = {"status": "delivered_conditionally", "feasibility_certified": False}
            if fits(trial):
                payload = trial
                trace["drill_selection"]["selected_id"] = identifier
                break
            trace["omissions"].append({"kind": "catalog", "id": identifier, "reason": "whole_approved_variant_exceeds_budget"})
        if not payload["catalog_records"]:
            payload["catalog_selection"]["reason"] = "No complete goal-relevant approved variant without a known resource conflict fits; do not invent a substitute or infer eligibility."
            if not fits(payload):
                raise ValueError("The explicit unavailable-drill notice exceeds the packet allowance.")
    # Whole rule groups retain their original qualifications; a whole drill has priority over generic context.
    kept = 0
    for group in _rule_groups(data.get("rules") or []):
        trial = deepcopy(payload); trial["planning_rules"]["rules"].extend(group)
        if any(x["candidate_rule_id"].startswith("NBA_") for x in group):
            trial["planning_rules"]["population_qualifications"] = deepcopy(data.get("project_overlap_policy") or {})
        if kept < rule_limit and fits(trial):
            payload, kept = trial, kept + 1
        else:
            trace["omissions"].extend({"kind": "rule", "id": x["candidate_rule_id"], "reason": "rule_bundle_limit" if kept >= rule_limit else "whole_rule_bundle_exceeds_budget"} for x in group)
    if len(ranked_lists) != 2 or any(not isinstance(x, list) or len(x) > 5 for x in ranked_lists):
        raise ValueError("Two ranked lists of at most five complete units are required.")
    seen = set()
    for index in range(max(map(len, ranked_lists), default=0)):
        for ranked in ranked_lists:
            if index >= len(ranked):
                continue
            item = ranked[index]; identifier = item["reference_unit_id"]
            if identifier in seen:
                continue
            seen.add(identifier)
            unit = tools.complete_reference(item)
            reference = {key: deepcopy(unit[key]) for key in ("reference_unit_id", "passage_id", "complete_required_delivery_text")}
            if reference["reference_unit_id"] != identifier or any(not isinstance(x, str) or not x.strip() for x in reference.values()):
                raise ValueError("A complete source reference changed.")
            trial = deepcopy(payload); trial["references"].append(reference)
            if fits(trial):
                payload = trial
            else:
                trace["omissions"].append({"kind": "reference", "id": identifier, "reason": "whole_reference_exceeds_budget"})
    packet = {"schema_version": "shared-reference-packet-1", "public_input_sha256": prepared["audit"]["public_input_sha256"], "payload": payload,
        "preparation": {"builder_policy": policy["policy_version"], "source_configuration_sha256": policy["source_configuration_sha256"],
            "query_templates_version": QUERY_VERSION, "drill_selection_version": VERSION, "packet_budget_basis": BUDGET_BASIS,
            "packet_text_tokens": tokens(payload), "max_packet_tokens": limit, "max_rule_bundles": rule_limit,
            "resource_release_id": catalog["release_id"], "release_manifest_sha256": catalog["release_manifest_sha256"],
            "active_resource_pointer_sha256": catalog["active_resource_pointer_sha256"],
            "selected_reference_ids": [x["reference_unit_id"] for x in payload["references"]],
            "delivered_catalog_ids": [x["requested_id"] for x in payload["catalog_records"]],
            "delivered_rule_ids": [x["candidate_rule_id"] for x in payload["planning_rules"]["rules"]],
            "omission_count": len(trace["omissions"]), "food_lookup_mode": food_mode, "rule_checks_executed": False,
            "feasibility_certified": False, "full_prompt_budget_verified": False}}
    packet["packet_id"] = "reference-packet:" + _sha(_json(packet).encode())
    trace["tool_calls"] = {"rules": 1, "food": len(trace["food_lookups"]), "catalog": len(trace["catalog_lookups"])}
    validate_packet(packet, prepared, policy, count_tokens)
    return packet, trace


def validate_packet(packet, prepared, policy, count_tokens):
    _public(prepared)
    body = {key: value for key, value in packet.items() if key != "packet_id"}
    p = packet.get("preparation") or {}
    n = count_tokens(_json(model_payload(packet["payload"])))
    if (type(n) is not int or n < 0 or n > policy["max_packet_tokens"]
            or packet.get("schema_version") != "shared-reference-packet-1"
            or packet.get("public_input_sha256") != prepared["audit"]["public_input_sha256"]
            or packet.get("packet_id") != "reference-packet:" + _sha(_json(body).encode())
            or p.get("builder_policy") != policy["policy_version"]
            or p.get("source_configuration_sha256") != policy["source_configuration_sha256"]
            or p.get("packet_budget_basis") != BUDGET_BASIS or p.get("drill_selection_version") != VERSION
            or p.get("packet_text_tokens") != n or p.get("max_packet_tokens") != policy["max_packet_tokens"]
            or p.get("feasibility_certified") is not False):
        raise ValueError("The reviewed complete packet changed or exceeds its lossless model-view budget.")
    for policy_key, saved_key in (("resource_release_manifest_sha256", "release_manifest_sha256"),
                                  ("active_resource_pointer_sha256", "active_resource_pointer_sha256")):
        if policy_key in policy and p.get(saved_key) != policy[policy_key]:
            raise ValueError("The packet belongs to a different approved resource release.")
    return True
