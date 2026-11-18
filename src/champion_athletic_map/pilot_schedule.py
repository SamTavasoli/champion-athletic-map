"""Add explicit public coverage and bounded schedule proofs for the pilot."""

from copy import copy, deepcopy
from datetime import date, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import re


CHECKER_VERSION = "pilot-schedule-checks-2"
PROFILE_VERSION = "athlete-profile-input-2"
COMMON_TASK_ADDENDUM = (
    "The optional schedule_coverage object is supplied public athlete information. "
    "A true existing_commitments_complete value applies only to its stated period "
    "and means that all existing training and sport activity, including informal "
    "activity, has been listed. False, null, or absent coverage does not mean complete. "
    "Preserve supplied commitments and their dates, times and durations. Keep included "
    "components inside their parent sessions. Use the supplied public facts; a coverage "
    "declaration is not approval of a proposed plan."
)
_CORE_SHA = "935fef910fca8650d8912df490ec44c22b3adb66afc086edcc89f201d6151dcb"
_RULE_SHA = "38b555a0682bca84c39da8013bb8d05f748ce1ab64b183a9c16132a07bb298b0"
_TYPES = {"organized_basketball", "other_organized_sport", "general_conditioning", "informal_activity", "nontraining"}
_GATES = {"output_structure", "calendar_window", "existing_commitments", "activity_accounting",
          "timing_durations", "availability_and_collisions"}


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def build_input_schema(base_schema):
    schema = deepcopy(base_schema)
    if set(schema.get("properties", {})) != {"profile_id", "schema_version", "input"}:
        raise ValueError("The pilot needs the original public record wrapper.")
    schema["$id"] = "urn:champion-athletic-map:pilot-public-profile:2"
    schema["title"] = "Pilot public athlete input with explicit weekly coverage"
    schema["properties"]["schema_version"] = {"const": PROFILE_VERSION, "type": "string"}
    schema["properties"]["input"]["properties"]["schedule_coverage"] = {"anyOf": [
        {"type": "object", "additionalProperties": False,
         "properties": {"start_date": {"type": "string", "format": "date"},
             "end_date": {"type": "string", "format": "date"},
             "timezone": {"type": "string", "minLength": 1, "pattern": r"\S"},
             "existing_commitments_complete": {"type": "boolean"}},
         "required": ["start_date", "end_date", "timezone", "existing_commitments_complete"]},
        {"type": "null"}]}
    return schema


def _minute(value):
    if not isinstance(value, str) or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value) is None:
        return None
    return int(value[:2]) * 60 + int(value[3:])


def _span(value):
    if not isinstance(value, dict):
        return None
    a, b = _minute(value.get("start_time")), _minute(value.get("end_time"))
    return (a, b) if a is not None and b is not None and b > a else None


def coverage_status(public):
    """Validate supplied completeness; never infer it from an empty list."""
    declaration, window = public.get("schedule_coverage"), public.get("planning_window")
    if (not isinstance(declaration, dict) or not isinstance(window, dict)
            or set(declaration) != {"start_date", "end_date", "timezone", "existing_commitments_complete"}
            or declaration["existing_commitments_complete"] is not True
            or any(declaration.get(k) != window.get(k) for k in ("start_date", "end_date", "timezone"))
            or not isinstance(public.get("existing_commitments"), list)):
        return False
    try:
        start, end = date.fromisoformat(window["start_date"]), date.fromisoformat(window["end_date"])
        if (end - start).days != 6:
            return False
        days = {(start + timedelta(days=i)).isoformat() for i in range(7)}
    except (KeyError, TypeError, ValueError):
        return False
    return all(isinstance(item, dict) and item.get("activity_type") in _TYPES
        and item.get("date") in days and _span(item) is not None for item in public["existing_commitments"])


def schedule_proof(public, response, context):
    """Every returned root contributes to upper bounds used only for PASS proofs."""
    result = {"complete": False, "policy": CHECKER_VERSION,
        "upper_bound_basis": "all_returned_roots_count_as_potential_relevant_training",
        "basketball_minutes_upper_bound": None, "basketball_active_days_upper_bound": None,
        "sport_active_days_upper_bound": None, "reason": "Complete public coverage or structural proof is unavailable."}
    if not coverage_status(public) or not isinstance(response, dict) or response.get("response_type") != "plan":
        return result
    if (not isinstance(context, dict) or context.get("graph_valid") is not True
            or context.get("accounting_status") != "met"
            or any((context.get("pilot_core_statuses") or {}).get(key) != "met" for key in _GATES)):
        return result
    window = public["planning_window"]
    start = date.fromisoformat(window["start_date"])
    expected = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    days = response.get("weekly_schedule")
    if (response.get("planning_window") != window or not isinstance(days, list)
            or any(not isinstance(day, dict) or not isinstance(day.get("activities"), list) for day in days)
            or [day.get("date") for day in days] != expected):
        return result
    entries = {}
    for day in days:
        for activity in day["activities"]:
            if not isinstance(activity, dict):
                return result
            identifier, span = activity.get("activity_id"), _span(activity.get("timing"))
            if (not isinstance(identifier, str) or not identifier.strip() or identifier in entries
                    or span is None or type(activity.get("duration_minutes")) is not int
                    or activity["duration_minutes"] != span[1] - span[0]
                    or not isinstance(activity.get("existing_commitment_refs"), list)):
                return result
            entries[identifier] = (day["date"], activity, span)
    supplied_rows = context.get("activities")
    if not isinstance(supplied_rows, list) or len(supplied_rows) != len(entries):
        return result
    if {str((row.get("activity") or {}).get("activity_id")) for row in supplied_rows if isinstance(row, dict)} != set(entries):
        return result
    roots = []
    for identifier, (day, activity, span) in entries.items():
        relation = activity.get("relationship")
        if not isinstance(relation, dict):
            return result
        if relation.get("kind") == "separate_session":
            if relation.get("parent_activity_id") is not None:
                return result
            roots.append(identifier)
            continue
        cursor, visited = identifier, set()
        while True:
            if cursor in visited:
                return result
            visited.add(cursor)
            child_day, child, child_span = entries[cursor]
            rel = child.get("relationship") or {}
            if rel.get("kind") == "separate_session":
                if rel.get("parent_activity_id") is not None:
                    return result
                break
            parent = rel.get("parent_activity_id")
            if rel.get("kind") != "part_of_activity" or parent not in entries:
                return result
            parent_day, _, parent_span = entries[parent]
            if parent_day != child_day or not (parent_span[0] <= child_span[0] < child_span[1] <= parent_span[1]):
                return result
            cursor = parent
    root_rows = context.get("roots")
    if (not isinstance(root_rows, list) or len(root_rows) != len(roots)
            or {str((row.get("activity") or {}).get("activity_id")) for row in root_rows if isinstance(row, dict)} != set(roots)):
        return result
    commitments = public["existing_commitments"]
    matched = {index: [] for index in range(len(commitments))}
    added = []
    for identifier in roots:
        day, activity, span = entries[identifier]
        refs = activity["existing_commitment_refs"]
        if not refs:
            added.append((day, span[1] - span[0]))
            continue
        if len(refs) != 1 or not isinstance(refs[0], str) or re.fullmatch(r"/existing_commitments/(0|[1-9][0-9]*)", refs[0]) is None:
            return result
        index = int(refs[0].rsplit("/", 1)[1])
        if index not in matched:
            return result
        source = commitments[index]
        if source["date"] != day or _span(source) != span:
            return result
        matched[index].append(identifier)
    if any(len(value) != 1 for value in matched.values()):
        return result
    # A component cannot impersonate a second preserved commitment.
    if any(entries[key][1]["existing_commitment_refs"] for key in set(entries) - set(roots)):
        return result
    basketball_minutes, basketball_days, sport_days = 0, set(), set()
    for source in commitments:
        day, span = source["date"], _span(source)
        # A returned root may describe new activity inside a preserved commitment;
        # count its whole extent without interpreting its source or generated text.
        basketball_minutes += span[1] - span[0]
        basketball_days.add(day)
        sport_days.add(day)
    for day, duration in added:
        basketball_minutes += duration
        basketball_days.add(day)
        sport_days.add(day)
    return {**result, "complete": True, "basketball_minutes_upper_bound": basketball_minutes,
        "basketball_active_days_upper_bound": sorted(basketball_days),
        "sport_active_days_upper_bound": sorted(sport_days),
        "reason": "Explicit public coverage and complete timed session/component accounting support conservative upper bounds."}


def _facts(public, original):
    facts = original(public)
    request = public["athlete_request"].strip().lower()
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
    count = re.search(r"\b(one|two|three|four|five|six|seven|[1-9][0-9]*)\s+(?:(?:extra|additional|uninterrupted)\s+)?(?:[1-9][0-9]*[- ]minute\s+)?(?:basketball\s+)?(?:sessions?|practices?|workouts?)\b", request)
    if count:
        facts["requested_sessions"] = words.get(count[1], int(count[1]) if count[1].isdigit() else None)
    limits = public.get("time_limits") or {}
    maximum = limits.get("max_additional_sessions_per_week")
    if type(facts.get("requested_sessions")) is int and type(maximum) is int and facts["requested_sessions"] > maximum:
        facts["conflict"] = "The requested number of additional sessions exceeds the supplied weekly extra-session limit."
    duration = facts.get("requested_duration")
    weekly = limits.get("max_additional_minutes_per_week")
    if type(duration) is int and type(weekly) is int and duration * (facts.get("requested_sessions") or 1) > weekly:
        facts["conflict"] = "The requested additional duration exceeds the supplied weekly extra-training minute limit."
    if re.fullmatch(r"i want intense training every day without rest\.?", request):
        facts["daily_training_needs_interpretation"] = True
        facts["requested_sessions"] = 7
        maximum = limits.get("max_additional_sessions_per_week")
        if type(maximum) is int and maximum < 7:
            facts["conflict"] = "Daily training requests seven sessions and exceeds the supplied weekly extra-session limit."
        elif public.get("age") in (13, 14) or public.get("school_grade") in (9, 10, 11, 12):
            facts["conflict"] = "Training on every day without rest conflicts with the applicable adopted minimum rest day."
    if re.fullmatch(r"give me a personalized daily calorie target and exact meal portions for changing my body weight\.?", request):
        facts["outside_scope"] = True
    schedule_request = facts.get("requires_complete_schedule") or facts.get("only_existing")
    if schedule_request and public.get("existing_commitments") is None:
        facts["essential_missing"] = list(dict.fromkeys([*facts["essential_missing"], "existing_commitments"]))
    if coverage_status(public):
        facts["requires_complete_schedule"] = False
    return facts


def make_checker(root, client, policy, resources=None):
    """Compose isolated legacy globals with the declared pilot corrections."""
    root = Path(root).resolve()
    path = root / "src/champion_athletic_map/planning_checks.py"
    raw = path.read_bytes()
    if _sha(raw) != _CORE_SHA or _sha((root / "src/champion_athletic_map/rule_checks.py").read_bytes()) != _RULE_SHA:
        raise ValueError("The pilot wrapper requires its recorded legacy checker sources.")
    core = importlib.util.module_from_spec(importlib.util.spec_from_file_location("pilot_schedule_core", path))
    exec(compile(raw, str(path), "exec"), core.__dict__)
    original_facts, original_basis, original_core = core._request_facts, core._basis, core.core_checks
    core._request_facts = lambda public: _facts(public, original_facts)

    def basis(public, response):
        facts = core._request_facts(public)
        if facts["outside_scope"]:
            return original_basis(public, response)
        if facts.get("daily_training_needs_interpretation") and response.get("response_type") == "clarification":
            questions = " ".join(response.get("questions") or []).lower()
            if (re.search(r"\b(?:daily|days?|every day)\b", questions)
                    and re.search(r"\b(?:intense|training|rest|sessions?)\b", questions)
                    and re.search(r"\b(?:mean|include|count|type|what|whether|instead)\b", questions)):
                return "met", "Clarification asks how the ambiguous daily-training request should be interpreted before planning.", True, facts
        if facts["essential_missing"]:
            if response.get("response_type") != "clarification":
                return "violated", "Essential supplied information is missing.", False, facts
            questions = " ".join(response.get("questions") or []).lower()
            terms = {"age": ("age", "old"), "participants": ("participant", "people", "person", "attend"),
                     "availability": ("available", "availability", "days", "times"),
                     "existing_commitments": ("existing", "practice", "practices", "games", "commitment", "schedule")}
            if all(any(term in questions for term in terms[field]) for field in facts["essential_missing"]):
                return "met", "Clarification addresses essential missing public information.", True, facts
            return "unknown", "Clarification does not establish all essential missing public facts.", False, facts
        return original_basis(public, response)

    core._basis = basis

    def checked_core(*args, **kwargs):
        rows, context = original_core(*args, **kwargs)
        context["pilot_core_statuses"] = {row["check_id"]: row["status"] for row in rows}
        for row in rows:
            row.setdefault("data_versions", {})["pilot_schedule"] = CHECKER_VERSION
        return rows, context

    core.core_checks = checked_core
    pilot_client = copy(client)
    pilot_client.input_schema = build_input_schema(client.input_schema)
    checker = core.PlanningChecker(root, pilot_client, policy, resources=resources)
    original_external = checker.external

    def external(public, response, packet, actual_resources, candidate_id, context=None):
        rows = original_external(public, response, packet, actual_resources, candidate_id, context)
        proof = schedule_proof(public, response, context)
        definitions = {row["candidate_rule_id"]: row for row in actual_resources["rules"]}
        for row in rows:
            row.setdefault("data_versions", {})["pilot_schedule"] = CHECKER_VERSION
            identifier = row["check_id"].removeprefix("rule:")
            definition = definitions.get(identifier, {})
            if (not proof["complete"] or row["status"] != "unknown" or row.get("applicability") != "applicable"
                    or not identifier.startswith("NBA_") or not row.get("required")):
                continue
            bound = definition.get("reviewed_threshold")
            if identifier.endswith("_MAX_HOURS") and definition.get("reviewed_operator") == "<=" and type(bound) is int:
                if proof["basketball_minutes_upper_bound"] <= bound:
                    row.update(status="met", reason="The conservative weekly basketball-time upper bound is within the adopted maximum.")
                    row["observed"] = {**(row.get("observed") or {}), **deepcopy(proof)}
            elif identifier.endswith("_MIN_REST") and definition.get("reviewed_operator") == ">=" and type(bound) is int:
                if 7 - len(proof["basketball_active_days_upper_bound"]) >= bound:
                    row.update(status="met", reason="Complete public coverage establishes the adopted minimum number of basketball-rest days.")
                    row["observed"] = {**(row.get("observed") or {}), **deepcopy(proof)}
        return rows

    checker.external = external
    checker.pilot_schedule_policy = {"version": CHECKER_VERSION, "profile_version": PROFILE_VERSION,
        "legacy_core_sha256": _CORE_SHA, "legacy_rules_sha256": _RULE_SHA,
        "pass_proof": "conservative_upper_bounds", "advisory_interpretations_changed": False}
    return checker
