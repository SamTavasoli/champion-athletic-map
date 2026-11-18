"""Build a bounded, reproducible context from complete public reference units."""

import hashlib
import json
import re
from copy import deepcopy


QUERY_VERSION = "public-two-query-1"
_FOOD_KEYS = {"food_id", "search_text", "grams", "portion_id", "multiplier"}
_NOTICE = "Only listed complete units were delivered; other available material may be omitted. Reference availability does not establish answerability or rule compliance."


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _public(prepared):
    public = prepared["public_input"]
    text = _json(public)
    if (prepared.get("schema_version") != "step24-prepared-public-input-1"
            or text != prepared["model_visible_json"]
            or hashlib.sha256(text.encode()).hexdigest() != prepared["audit"]["public_input_sha256"]):
        raise ValueError("The prepared public facts changed.")
    return public


def _short(value, limit):
    if value is None:
        return "unknown"
    if not isinstance(value, str):
        value = _json(value)
    return " ".join(value.split())[:limit]


def make_queries(prepared):
    """Use brief public fields; the frozen query encoder checks its own limit."""
    p = _public(prepared)
    names = None if p.get("equipment") is None else [item.get("name") for item in p["equipment"] if isinstance(item, dict)]
    commitments = p.get("existing_commitments")
    kinds = None if commitments is None else sorted({str(item.get("activity_kind") or "unknown") for item in commitments})
    first = "; ".join(("Basketball practice", _short(p["athlete_request"], 32),
        "goals " + _short(p.get("goals"), 24), "experience " + _short(p.get("basketball_background"), 12),
        "equipment " + _short(names, 24), "space " + _short((p.get("space") or {}).get("court_access"), 12),
        "people " + _short(p.get("participants_available"), 4)))
    second = "; ".join(("Youth basketball participation, rest and recovery",
        "age " + _short(p.get("age"), 4), "grade " + _short(p.get("school_grade"), 4),
        "commitments " + _short(kinds, 42), "request " + _short(p["athlete_request"], 45)))
    return [first[:180], second[:180]]


def merge_results(two_lists):
    """Keep each query's order and take distinct units in round-robin order."""
    if len(two_lists) != 2 or any(not isinstance(rows, list) or len(rows) > 5 for rows in two_lists):
        raise ValueError("Expected two ranked lists with at most five units each.")
    merged, seen = [], set()
    for index in range(max(map(len, two_lists), default=0)):
        for rows in two_lists:
            if index < len(rows):
                item = rows[index]
                unit = item.get("reference_unit_id")
                if not isinstance(unit, str) or not unit:
                    raise ValueError("A ranked unit has no stable source ID.")
                if unit not in seen:
                    merged.append(deepcopy(item))
                    seen.add(unit)
    return merged


def _tool(result):
    fields = ("status", "data", "issues", "source_refs", "data_version")
    if not isinstance(result, dict) or any(key not in result for key in fields):
        raise ValueError("A required reference lookup returned an invalid record.")
    if result["status"] in ("execution_error", "technical_error", "error", "failed"):
        raise RuntimeError("Reference preparation failed: " + "; ".join(result.get("issues") or []))
    return deepcopy({key: result[key] for key in fields})


def _food_requests(question):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate food argument")
            result[key] = value
        return result
    try:
        parsed = json.loads(question, object_pairs_hook=unique,
                            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite food value")))
        if parsed == []:
            return [], "explicit_public_json_arguments"
        requests = parsed if isinstance(parsed, list) else [parsed]
        if requests and all(isinstance(item, dict) and item and set(item) <= _FOOD_KEYS for item in requests):
            return requests, "explicit_public_json_arguments"
    except (TypeError, ValueError):
        pass
    literal = re.fullmatch(
        r'For the food "([^"\r\n]+)", how many (?:grams of protein|kilocalories of energy) are recorded for ([0-9]+(?:\.[0-9]+)?) g\?',
        question)
    if literal and literal[1].strip():
        return [{"search_text": literal[1], "grams": literal[2]}], "literal_quoted_name_and_grams"
    return [{"search_text": question}], "description_only_no_quantity_inference"


def _rule_groups(rows):
    groups = {}
    for row in rows:
        if row.get("record_kind") not in ("structured_reference", "general_guidance"):
            continue
        if row.get("applicability_assessment", {}).get("status") == "not_applicable":
            continue
        identifier = row["candidate_rule_id"]
        concept = re.sub(r"^NBA_(A12_14|G9_12)_", "NBA_", identifier)
        unknown = row.get("applicability_assessment", {}).get("status") == "unknown"
        groups.setdefault((concept, unknown), []).append(deepcopy(row))
    def priority(entry):
        (concept, unknown), items = entry
        required = any(str(item.get("reviewed_enforcement") or "").startswith("required") for item in items)
        topic = next((i for i, text in enumerate(("MAX_HOURS", "MIN_REST", "SLEEP", "PRACTICE_LENGTH")) if text in concept), 4)
        return unknown, not required, topic, concept
    return [sorted(items, key=lambda item: item["candidate_rule_id"]) for _, items in sorted(groups.items(), key=priority)]


def _overlap(data):
    policy = data.get("project_overlap_policy") or {}
    public = {key: deepcopy(policy[key]) for key in ("policy_id", "origin", "population_matching", "unknown_grade", "advisory_ranges") if key in policy}
    if policy.get("overlapping_required_bounds"):
        public["overlapping_required_bounds"] = policy["overlapping_required_bounds"].replace("; do not score aliases twice", "")
    return public


def build_packet(prepared, tools, ranked_lists, count_tokens, policy):
    """Pack complete guidance, requested food facts and retrieved source units."""
    p = _public(prepared)
    limit, rule_limit = policy.get("max_packet_tokens", 2200), policy.get("max_rule_bundles", 2)
    source_hash = policy.get("source_configuration_sha256")
    if (type(limit) is not int or limit < 1 or type(rule_limit) is not int or not 0 <= rule_limit <= 2
            or not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash)):
        raise ValueError("The reference policy needs bounded limits and a source-configuration hash.")
    def tokens(value):
        result = count_tokens(_json(value))
        if type(result) is not int or result < 0:
            raise ValueError("The packet token count is invalid.")
        return result
    def fits(value):
        return tokens(value) <= limit
    rule_result = _tool(tools.get_planning_rules(p.get("age"), p.get("school_grade")))
    data = rule_result["data"] or {}
    trace = {"queries": make_queries(prepared), "ranked_lists": deepcopy(ranked_lists), "rule_lookup": rule_result,
             "food_lookups": [], "catalog_lookups": [], "omissions": []}
    merged = merge_results(ranked_lists)
    payload = {"references": [], "planning_rules": {"status": rule_result["status"], "rules": [], "validator_execution_ready": False},
               "catalog_records": [], "context_limitations": [_NOTICE]}
    question = p.get("food_question")
    food_mode = "not_requested"
    if isinstance(question, str) and question.strip():
        requests, food_mode = _food_requests(question)
        payload["food_lookup"] = []
        for arguments in requests[:2]:
            result = _tool(tools.lookup_food(**arguments))
            trace["food_lookups"].append({"arguments": arguments, "result": result})
            payload["food_lookup"].append(result)
        trace["omissions"].extend({"kind": "food", "position": i, "reason": "two_food_limit"} for i in range(2, len(requests)))
    if not fits(payload):
        raise ValueError("The complete requested food context exceeds the packet budget.")

    references = []
    for item in merged:
        unit = tools.complete_reference(item)
        reference = {key: deepcopy(unit[key]) for key in ("reference_unit_id", "passage_id", "complete_required_delivery_text")}
        if (reference["reference_unit_id"] != item["reference_unit_id"]
                or not isinstance(reference["passage_id"], str) or not reference["passage_id"]
                or not isinstance(reference["complete_required_delivery_text"], str)
                or not reference["complete_required_delivery_text"].strip()):
            raise ValueError("A complete reference does not match its ranked source unit.")
        references.append(reference)
    # We reserve a whole source unit before filling the rule allowance.
    for reference in references:
        trial = deepcopy(payload)
        trial["references"] = [reference]
        if fits(trial):
            payload = trial
            break
    if references and not payload["references"]:
        raise ValueError("No complete retrieved source unit fits the packet budget.")

    groups = _rule_groups(data.get("rules") or [])
    kept_groups = 0
    for group in groups:
        trial = deepcopy(payload)
        trial["planning_rules"]["rules"].extend(group)
        if any(row["candidate_rule_id"].startswith("NBA_") for row in group):
            trial["planning_rules"]["population_qualifications"] = _overlap(data)
        reason = "rule_bundle_limit" if kept_groups >= rule_limit else "whole_rule_bundle_exceeds_budget"
        if kept_groups < rule_limit and fits(trial):
            payload, kept_groups = trial, kept_groups + 1
        else:
            trace["omissions"].extend({"kind": "rule", "id": row["candidate_rule_id"], "reason": reason} for row in group)
    delivered = {row["reference_unit_id"] for row in payload["references"]}
    for reference in references:
        if reference["reference_unit_id"] in delivered:
            continue
        trial = deepcopy(payload)
        trial["references"].append(reference)
        if fits(trial):
            payload = trial
            delivered.add(reference["reference_unit_id"])
        else:
            trace["omissions"].append({"kind": "reference", "id": reference["reference_unit_id"], "reason": "whole_reference_exceeds_budget"})

    linked, seen = [], set()
    for item in merged:
        if item["reference_unit_id"] not in delivered:
            continue
        for metadata in (item, item.get("metadata") or {}):
            for kind, keys in (("drill", ("linked_drill_ids", "drill_ids")), ("exercise", ("linked_exercise_ids", "exercise_ids"))):
                for key in keys:
                    identifiers = metadata.get(key) or []
                    if not isinstance(identifiers, list) or any(not isinstance(value, str) or not value.strip() for value in identifiers):
                        raise ValueError("Linked catalog IDs must be a list of nonblank strings.")
                    for identifier in identifiers:
                        if (kind, identifier) not in seen:
                            seen.add((kind, identifier))
                            linked.append((kind, identifier))
    canonical = set()
    for index, (kind, identifier) in enumerate(linked):
        if index >= 10:
            trace["omissions"].append({"kind": "catalog", "id": identifier, "reason": "ten_lookup_limit"})
            continue
        result = _tool((tools.get_drill if kind == "drill" else tools.get_exercise)(identifier))
        trace["catalog_lookups"].append({"kind": kind, "id": identifier, "result": result})
        identity = (kind, (result["data"] or {}).get("canonical_drill_id", identifier))
        if identity in canonical:
            continue
        canonical.add(identity)
        trial = deepcopy(payload)
        trial["catalog_records"].append({"kind": kind, "requested_id": identifier, **result})
        if fits(trial):
            payload = trial
        else:
            trace["omissions"].append({"kind": "catalog", "id": identifier, "reason": "whole_catalog_record_exceeds_budget"})
    if not fits(payload):
        raise ValueError("The complete packet exceeds its token allowance.")
    packet = {"schema_version": "shared-reference-packet-1", "public_input_sha256": prepared["audit"]["public_input_sha256"],
              "payload": payload, "preparation": {"builder_policy": policy.get("policy_version", "shared-planning-references-1"),
              "source_configuration_sha256": source_hash, "query_templates_version": QUERY_VERSION,
              "selected_reference_ids": [row["reference_unit_id"] for row in payload["references"]],
              "delivered_rule_ids": [row["candidate_rule_id"] for row in payload["planning_rules"]["rules"]],
              "omission_count": len(trace["omissions"]), "food_lookup_mode": food_mode,
              "packet_text_tokens": tokens(payload), "max_packet_tokens": limit, "max_rule_bundles": rule_limit,
              "rule_checks_executed": False, "full_prompt_budget_verified": False}}
    packet["packet_id"] = "reference-packet:" + hashlib.sha256(_json(packet).encode()).hexdigest()
    trace["excluded_policy_rule_ids"] = [row["candidate_rule_id"] for row in data.get("rules") or [] if row.get("record_kind") not in ("structured_reference", "general_guidance")]
    trace["tool_calls"] = {"rules": 1, "food": len(trace["food_lookups"]), "catalog": len(trace["catalog_lookups"])}
    return packet, trace
