"""Assess saved development replies outside the generation and review workflow."""

from copy import deepcopy
import hashlib
import importlib.util
import importlib.metadata
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace


VERSION = "independent-development-assessment-1"
REPLACED_CHECKS = {"requested_session_count", "resource_feasibility", "rule:USER_EQUIPMENT_SPACE",
    "rule:USER_PARTICIPANTS", "food_facts_numeric"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def module(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("An assessment dependency leaves the project.")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("independent_" + path.stem, path))
    result.__spec__.loader.exec_module(result)
    return result


def row(identifier, status, reason, *, observed=None, required=True):
    if status not in {"met", "violated", "unknown", "not_applicable"} or not reason:
        raise ValueError("An assessment finding needs a declared status and reason.")
    return {"check_id": identifier, "status": status, "reason": reason, "observed": observed,
        "required": required, "assessment_version": VERSION}


def requested_count(public):
    """Recognize explicit additional-session wording without reading private labels."""
    text = public.get("athlete_request", "").casefold()
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
    counts = re.findall(r"\b(one|two|three|four|five|six|seven|[0-9]+)\s+(?:extra|additional)\s+(?:basketball\s+)?(?:sessions?|practices?|workouts?)\b", text)
    values = [words.get(value, int(value) if value.isdigit() else None) for value in counts]
    if len(set(values)) == 1:
        return values[0], "literal_additional_session_count"
    if len(set(values)) > 1:
        return None, "multiple_count_statements_need_interpretation"
    if re.search(r"\bno (?:extra|additional) (?:basketball )?(?:sessions?|training|practices?)\b", text):
        return 0, "explicit_no_additional_training"
    return None, "no_supported_exact_count_expression"


def added_roots(response):
    """Keep a known root lower bound while retaining malformed graph uncertainty."""
    if not isinstance(response, dict) or response.get("response_type") != "plan":
        return [], False
    days = response.get("weekly_schedule")
    if not isinstance(days, list):
        return [], False
    entries, complete = {}, True
    for day in days:
        if not isinstance(day, dict) or not isinstance(day.get("activities"), list):
            complete = False
            continue
        for activity in day["activities"]:
            if not isinstance(activity, dict) or not isinstance(activity.get("activity_id"), str):
                complete = False
                continue
            identifier = activity["activity_id"]
            if identifier in entries:
                complete = False
                continue
            entries[identifier] = {**deepcopy(activity), "date": day.get("date")}
    roots = []
    for identifier, activity in entries.items():
        relation = activity.get("relationship")
        refs = activity.get("existing_commitment_refs")
        if not isinstance(relation, dict) or not isinstance(refs, list):
            complete = False
            continue
        if relation.get("kind") == "separate_session":
            if relation.get("parent_activity_id") is not None:
                complete = False
                continue
            if refs == []:
                roots.append(activity)
            continue
        cursor, seen = identifier, set()
        while True:
            if cursor in seen or cursor not in entries:
                complete = False
                break
            seen.add(cursor)
            current = entries[cursor]
            link = current.get("relationship") or {}
            if link.get("kind") == "separate_session" and link.get("parent_activity_id") is None:
                break
            parent = link.get("parent_activity_id")
            if (link.get("kind") != "part_of_activity" or parent not in entries
                    or entries[parent]["date"] != current["date"]):
                complete = False
                break
            cursor = parent
    return roots, complete


def session_check(public, response, *, structure_valid):
    target, basis = requested_count(public)
    roots, graph_complete = added_roots(response)
    observed = {"requested_additional_sessions": target, "known_additional_roots": len(roots),
        "complete_graph": graph_complete, "count_basis": basis,
        "maximum_is_not_requested_count": (public.get("time_limits") or {}).get("max_additional_sessions_per_week")}
    if target is None:
        request = public.get("athlete_request", "").casefold()
        unresolved_count = basis.startswith("multiple") or (bool(re.search(r"\b(?:one|two|three|four|five|six|seven|[0-9]+)\b", request))
            and bool(re.search(r"\b(?:sessions?|practices?|workouts?)\b", request)))
        return row("requested_session_count", "unknown" if unresolved_count else "not_applicable",
            "The exact request needs interpretation." if unresolved_count else "No explicit exact-session count applies to this request.", observed=observed)
    if len(roots) > target:
        return row("requested_session_count", "violated", "Requested " + str(target) + " additional sessions; at least " + str(len(roots)) + " new roots are present.", observed=observed)
    if not structure_valid or not graph_complete:
        return row("requested_session_count", "unknown", "Incomplete or invalid activity structure prevents an exact additional-session count.", observed=observed)
    return row("requested_session_count", "met" if len(roots) == target else "violated",
        "Requested " + str(target) + " additional sessions; scheduled " + str(len(roots)) + ".", observed=observed)


def resource_activities(response):
    """Include newly prescribed components as well as added root sessions."""
    activities = []
    if not isinstance(response, dict):
        return activities
    for day in response.get("weekly_schedule") or []:
        if not isinstance(day, dict):
            continue
        for item in day.get("activities") or []:
            if not isinstance(item, dict):
                continue
            relation = item.get("relationship") or {}
            preserved_root = (relation.get("kind") == "separate_session"
                and isinstance(item.get("existing_commitment_refs"), list) and bool(item["existing_commitment_refs"]))
            if not preserved_root:
                activities.append({**deepcopy(item), "date": day.get("date")})
    return activities


class IndependentAssessor:
    def __init__(self, root, public_schema, *, contracts_path="artifacts/evaluation/independent_assessment/reviewed_resource_contracts.json"):
        self.root = Path(root).resolve()
        self.environment = {"python": sys.version, "jsonschema": importlib.metadata.version("jsonschema")}
        integration = json.loads((self.root / "artifacts/language_model/integration_config.json").read_bytes())
        contracts = self.root / integration["contracts_directory"]
        summary_path = contracts / "step24_7_shared_contract_summary.json"
        contract_summary = json.loads(summary_path.read_bytes())
        self.dependency_sha256 = {summary_path.relative_to(self.root).as_posix(): sha(summary_path.read_bytes())}
        for filename in ("public_input.py", "response_contract.py", "planner_response_schema.json"):
            relative = (contracts / filename).relative_to(self.root).as_posix()
            digest = sha((self.root / relative).read_bytes())
            if contract_summary["output_hashes"].get(relative) != digest:
                raise ValueError("A shared assessment parser or schema differs from its saved contract: " + relative)
            self.dependency_sha256[relative] = digest
        public = module(self.root, str((contracts / "public_input.py").relative_to(self.root)))
        response = module(self.root, str((contracts / "response_contract.py").relative_to(self.root)))
        self.client = SimpleNamespace(public=public, response=response, input_schema=deepcopy(public_schema),
            response_schema=json.loads((contracts / "planner_response_schema.json").read_bytes()))
        schedule = module(self.root, "src/champion_athletic_map/pilot_schedule.py")
        self.calendar = schedule.make_checker(self.root, self.client, {})
        self.expected_required = {identifier: True for identifier in self.calendar.expected_check_ids if identifier not in REPLACED_CHECKS}
        for definition in self.calendar.resources["rules"]:
            identifier = "rule:" + definition["candidate_rule_id"]
            if identifier in self.expected_required:
                self.expected_required[identifier] = str(definition.get("reviewed_enforcement", "")).startswith("required")
        self.expected_required.update({identifier: True for identifier in ("execution_completion", "requested_session_count",
            "declared_resource_consistency", "resource_requirements_evidence", "food_answer_completeness", "food_numeric_correctness")})
        self.expected_required["food_source_grounding"] = False
        self.resources = module(self.root, "src/champion_athletic_map/independent_resources.py")
        self.resource_contracts = self.resources.load_contracts(self.root, contracts_path)
        self.food = module(self.root, "src/champion_athletic_map/independent_food.py")

    def assess(self, public_record, outcome, truth_packet, *, assessment_id):
        public = self.client.public.prepare_public_input(public_record, self.client.input_schema)["public_input"]
        model_output = ((outcome.get("response") or {}).get("model_output") or {})
        raw = model_output.get("raw_text")
        base = self.calendar.check(public_record, {"raw_text": raw if isinstance(raw, str) else ""}, truth_packet,
            candidate_id=assessment_id)
        if base["execution_status"] != "completed" or not base.get("checks"):
            return {"assessment_id": assessment_id, "assessment_execution": "error", "checks": [],
                "error": base.get("error") or "The complete calendar checks were unavailable.",
                "overall": "assessment_error", "quality_or_safety_certified": False}
        checks = [deepcopy(value) for value in base["checks"] if value["check_id"] not in REPLACED_CHECKS]
        checks.insert(0, row("execution_completion", "met" if outcome.get("completion_valid") is True else "violated",
            "The designated saved workflow completed." if outcome.get("completion_valid") is True else
            "The designated workflow did not complete; earlier candidates are not substituted."))
        parsed = base.get("parsed_object")
        by_id = {value["check_id"]: value for value in checks}
        structure_valid = base["format_valid"] is True and by_id["activity_accounting"]["status"] == "met"
        kind = parsed.get("response_type") if isinstance(parsed, dict) else None
        supported_nonplan = kind in ("clarification", "constraint_conflict", "outside_scope") and by_id["response_type_basis"]["status"] == "met"
        if supported_nonplan:
            checks.append(row("requested_session_count", "not_applicable", "The non-plan response has a checked public basis."))
            resource_report = {"checks": [row(identifier, "not_applicable", "The supported non-plan response proposes no added activities.")
                for identifier in ("declared_resource_consistency", "resource_requirements_evidence")], "per_activity": [], "coverage": {}}
        else:
            checks.append(session_check(public, parsed, structure_valid=structure_valid))
            roots, complete = added_roots(parsed)
            resource_report = self.resources.assess_resources(public, resource_activities(parsed), self.resource_contracts)
            if not structure_valid or not complete:
                for item in resource_report["checks"]:
                    if item["status"] != "violated":
                        item.update(status="unknown", reason="Complete valid activity accounting is required for a positive resource result.")
        for item in resource_report["checks"]:
            item = deepcopy(item)
            item["required"] = True
            checks.append(item)
        food_checks = self.food.assess_food(public, parsed or {}, truth_packet)
        for item in food_checks:
            item = deepcopy(item)
            item["required"] = item["check_id"] != "food_source_grounding"
            checks.append(item)
        ids = [item["check_id"] for item in checks]
        if (len(ids) != len(set(ids)) or set(ids) != set(self.expected_required) or not checks
                or any(type(item.get("required")) is not bool or item["required"] != self.expected_required[item["check_id"]] for item in checks)
                or any(item["status"] not in ("met", "violated", "unknown", "not_applicable") or not item.get("reason") for item in checks)):
            raise ValueError("The independent assessment returned invalid or duplicate coverage.")
        violations = [item["check_id"] for item in checks if item["required"] and item["status"] == "violated"]
        unknowns = [item["check_id"] for item in checks if item["required"] and item["status"] == "unknown"]
        return {"schema_version": VERSION, "assessment_id": assessment_id, "assessment_execution": "completed",
            "raw_response_sha256": sha(raw.encode("utf-8")) if isinstance(raw, str) else None,
            "public_input_sha256": sha(canonical(public)), "designated_outcome_sha256": sha(canonical(outcome)),
            "overall": "requirements_violated" if violations else "requirements_unverified" if unknowns else "declared_checks_supported",
            "checks": checks, "required_violations": violations, "required_unknowns": unknowns,
            "expected_check_ids": list(self.expected_required), "required_flags_verified": True,
            "resources": resource_report, "shared_calendar_implementation": "pilot_schedule-checker-2",
            "internal_evaluator_used_for_verdict": False, "quality_or_safety_certified": False,
            "accepted_study_case": False, "final_study_score": None,
            "coverage_limits": ["Resource proofs cover only the separately reviewed concrete base variants.",
                "Unrecognized food prose remains unknown; source grounding is a separate measure.",
                "Goal quality, semantic coverage, population acceptance and human review are not completed by this report."]}
