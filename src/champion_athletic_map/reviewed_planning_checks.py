"""Prospective conservative corrections supported by the saved development review."""

from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import importlib.util
from pathlib import Path
import re
from types import SimpleNamespace


VERSION = "reviewed-development-checks-1"
_NUMBERS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
            "five": 5, "six": 6, "seven": 7, "a": 1, "an": 1}
_LIMITS = ("max_additional_sessions_per_week", "max_additional_minutes_per_week", "max_session_minutes")
_SPACE_LITERALS = {"full court", "full basketball court", "half court", "half basketball court",
                   "single hoop area", "basketball court", "clear court space", "designated practice area",
                   "clear practice area", "clear space", "no space needed"}


def _module(root, name):
    path = Path(root).resolve() / "src/champion_athletic_map" / (name + ".py")
    if not path.is_file() and name in {"food_fact_focus"}:
        path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("reviewed_" + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def _combine(values):
    values = list(values)
    return ("violated" if "violated" in values else "unknown" if "unknown" in values else
            "met" if "met" in values else "not_applicable")


def _span(value):
    if not isinstance(value, dict):
        return None
    times = [value.get(key) for key in ("start_time", "end_time")]
    if any(not isinstance(v, str) or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", v) is None for v in times):
        return None
    a, b = [int(v[:2]) * 60 + int(v[3:]) for v in times]
    return (a, b) if b > a else None


def _space_alias(value):
    if not isinstance(value, str):
        return value
    normalized = " ".join(value.casefold().replace("-", " ").replace("_", " ").split())
    return normalized if normalized in _SPACE_LITERALS else value


def _activities(response):
    rows = []
    for day in response.get("weekly_schedule") or [] if isinstance(response, dict) else []:
        if not isinstance(day, dict):
            continue
        for activity in day.get("activities") or []:
            if isinstance(activity, dict):
                rows.append({**deepcopy(activity), "date": day.get("date")})
    return rows


def resource_scope(public, response, activity):
    """Only an unambiguously new root or its new component uses extra-session supplies."""
    refs = activity.get("existing_commitment_refs")
    if refs != []:
        return "existing_link_or_unresolved_reference"
    rows = _activities(response)
    identifiers = Counter(row.get("activity_id") for row in rows if isinstance(row.get("activity_id"), str))
    current, visited = activity, set()
    while True:
        identifier = current.get("activity_id")
        if not isinstance(identifier, str) or identifiers[identifier] != 1 or identifier in visited:
            return "unresolved_activity_identity"
        visited.add(identifier)
        relation = current.get("relationship")
        if not isinstance(relation, dict):
            return "unresolved_activity_relationship"
        if relation.get("kind") == "separate_session" and relation.get("parent_activity_id") is None:
            if current.get("existing_commitment_refs") != []:
                return "component_of_existing_or_unresolved_event"
            for commitment in public.get("existing_commitments") or []:
                # A root reproducing a supplied event but missing its link remains ambiguous.
                if (commitment.get("date") == current.get("date")
                        and isinstance(commitment.get("description"), str)
                        and commitment["description"].casefold().strip() == str(current.get("description", "")).casefold().strip()
                        and _span(commitment) is not None and _span(commitment) == _span(current.get("timing"))):
                    return "unlinked_supplied_event"
            return "new_training"
        if relation.get("kind") != "part_of_activity":
            return "unresolved_activity_relationship"
        parent = relation.get("parent_activity_id")
        matches = [row for row in rows if row.get("activity_id") == parent]
        if len(matches) != 1 or matches[0].get("date") != current.get("date"):
            return "unresolved_component_parent"
        current = matches[0]


def _number_in(text, number):
    choices = [str(number)] + [word for word, value in _NUMBERS.items() if value == number and word not in {"a", "an"}]
    return re.search(r"\b(?:" + "|".join(re.escape(v) for v in choices) + r")\b", text) is not None


def _applicable(rule, public):
    if rule.get("enabled_for_planner") is not True or rule.get("adoption_status") != "adopted_by_team_delegation":
        return False
    if type(public.get("age")) is not int or not 13 <= public["age"] <= 17:
        return False
    conditions = rule.get("source_population_conditions") or {}
    for field, prefix in (("age", "age"), ("school_grade", "grade")):
        low, high = conditions.get(prefix + "_min"), conditions.get(prefix + "_max")
        if low is None and high is None:
            continue
        actual = public.get(field)
        if type(actual) is not int or (low is not None and actual < low) or (high is not None and actual > high):
            return False
    return True


def conflict_proofs(public, facts, rules, *, complete_coverage):
    """Recognize only explicit count/duration bounds and adopted daily-rest conflicts."""
    request = str(public.get("athlete_request", "")).casefold()
    count, duration = facts.get("requested_sessions"), facts.get("requested_duration")
    if count is None and duration is not None and re.search(r"\b(?:a|an|one|1)\s+[0-9]+[- ]minute", request):
        count = 1
    limits, proofs = public.get("time_limits") or {}, []
    for kind, observed, key in (("session_count", count, _LIMITS[0]),
                                ("weekly_minutes", count * duration if type(count) is int and type(duration) is int else None, _LIMITS[1]),
                                ("session_minutes", duration, _LIMITS[2])):
        bound = limits.get(key)
        if type(observed) is int and type(bound) is int and observed > bound:
            proofs.append({"kind": kind, "observed": observed, "bound": bound, "source": "/time_limits/" + key})
    available = public.get("availability")
    if type(duration) is int and isinstance(available, list):
        spans = [_span(row) for row in available]
        if not spans:
            proofs.append({"kind": "availability", "observed": duration, "bound": 0, "source": "/availability"})
        elif all(v is not None for v in spans) and duration > max(b - a for a, b in spans):
            proofs.append({"kind": "availability", "observed": duration, "bound": max(b - a for a, b in spans), "source": "/availability"})
    daily = bool(re.search(r"\b(?:every day|daily)\b", request) and re.search(r"\b(?:without rest|no rest)\b", request))
    if daily and complete_coverage:
        for rule in rules:
            if (rule.get("candidate_rule_id", "").endswith("_MIN_REST") and _applicable(rule, public)
                    and rule.get("reviewed_operator") == ">=" and type(rule.get("reviewed_threshold")) is int
                    and rule["reviewed_threshold"] > 0 and str(rule.get("reviewed_enforcement", "")).startswith("required")):
                proofs.append({"kind": "minimum_rest", "observed": 0, "bound": rule["reviewed_threshold"],
                               "source": "rule:" + rule["candidate_rule_id"]})
    return proofs


def _matches_clause(text, proof):
    if re.search(r"\b(?:does not|do not|not|no|doesn't|don't)\s+(?:actually\s+)?(?:conflict|conflicts|exceed|exceeds|violate|violates)\b", text):
        return False
    if not re.search(r"\b(?:conflict|conflicts|exceed|exceeds|cannot|can't|requires?|required|incompatible|without|violat\w*|only)\b", text):
        return False
    if proof["kind"] == "minimum_rest":
        return bool(re.search(r"\brest\b", text) and re.search(r"\b(?:every day|daily|without rest)\b", text)
                    and _number_in(text, proof["bound"]))
    concepts = {"session_count": r"\bsessions?\b", "weekly_minutes": r"\b(?:minutes?|time limit|training time)\b",
                "session_minutes": r"\bminutes?\b", "availability": r"\b(?:availability|available|window|windows)\b"}
    return bool(re.search(concepts[proof["kind"]], text) and _number_in(text, proof["bound"])
                and (_number_in(text, proof["observed"]) or proof["bound"] == 0))


def _matches_proof(text, proof):
    # A number in an unrelated sentence cannot validate a generic conflict claim.
    return any(_matches_clause(clause, proof) for clause in re.split(r"[.!?;\n]", text))


def _numeric_limit_correction(public, response, context, row):
    if not isinstance(response, dict) or response.get("response_type") != "plan" or context.get("accounting_status") == "met":
        return
    roots = [v for v in _activities(response) if (v.get("relationship") or {}).get("kind") == "separate_session"
             and (v.get("relationship") or {}).get("parent_activity_id") is None
             and resource_scope(public, response, v) == "new_training"]
    ids = Counter(v.get("activity_id") for v in _activities(response) if isinstance(v.get("activity_id"), str))
    try:
        start = date.fromisoformat(public["planning_window"]["start_date"])
        days = {(start + timedelta(days=i)).isoformat() for i in range(7)}
    except (KeyError, TypeError, ValueError):
        days = set()
    roots = [v for v in roots if v.get("date") in days and ids[v.get("activity_id")] == 1]
    intervals, untimed, durations = {}, {}, []
    for root in roots:
        timing, duration, day = _span(root.get("timing")), root.get("duration_minutes"), root["date"]
        stated_timing = root.get("timing")
        if (timing is None and isinstance(stated_timing, dict)
                and all(isinstance(stated_timing.get(key), str)
                        and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", stated_timing[key])
                        for key in ("start_time", "end_time"))):
            continue
        if type(duration) is not int or duration < 0 or timing is not None and duration != timing[1] - timing[0]:
            continue
        durations.append(duration)
        if timing:
            intervals.setdefault(day, []).append(timing)
        else:
            untimed[day] = max(untimed.get(day, 0), duration)
    minutes = 0
    for day in set(intervals) | set(untimed):
        merged = []
        for a, b in sorted(intervals.get(day, [])):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        minutes += max(sum(b - a for a, b in merged), untimed.get(day, 0))
    observed = dict(zip(_LIMITS, (len(roots), minutes, max(durations, default=0))))
    overrun = {key: {"lower_bound": observed[key], "limit": public["time_limits"][key]} for key in _LIMITS
               if type((public.get("time_limits") or {}).get(key)) is int and observed[key] > public["time_limits"][key]}
    row.update(status="violated" if overrun else "unknown",
               reason="A separate numeric lower bound exceeds a supplied additional-training limit." if overrun else
                      "Activity accounting is incomplete; no independent numeric overrun is established.",
               observed={"numeric_lower_bounds": observed, "proven_overruns": overrun,
                         "graph_status_retained_separately": context.get("accounting_status")})


def _review_checker(checker, root):
    core = checker.check.__func__.__globals__
    original_basis, original_core, original_resources = core["_basis"], core["core_checks"], core["_resources"]
    schedule = _module(root, "pilot_schedule")
    focus, food = _module(root, "food_fact_focus"), _module(root, "independent_food")
    active = {}

    def basis(public, response):
        result = original_basis(public, response)
        facts = result[3]
        if response.get("response_type") != "constraint_conflict" or facts.get("outside_scope") or facts.get("essential_missing"):
            return result
        proofs = conflict_proofs(public, facts, checker.resources["rules"], complete_coverage=schedule.coverage_status(public))
        explanation = " ".join([str(response.get("explanation", "")), *[str(v) for v in response.get("unresolved_issues") or []]]).casefold()
        matched = [proof for proof in proofs if _matches_proof(explanation, proof)]
        if matched:
            return "met", "The explanation identifies a demonstrated public conflict: " + ", ".join(p["source"] for p in matched) + ".", True, facts
        return "unknown", "No demonstrated public conflict is established by the explanation under the reviewed literal evidence policy.", False, facts

    def resources(public, rows, released):
        response = active.get("response")
        # Components can prescribe new equipment even when their root declaration fits.
        candidates = list(rows)
        candidates.extend({"activity": activity, "date": activity.get("date")} for activity in _activities(response)
                          if isinstance(activity.get("relationship"), dict)
                          and activity["relationship"].get("kind") == "part_of_activity")
        included = [deepcopy(row) for row in candidates if resource_scope(public, response, {**row["activity"], "date": row.get("date")}) == "new_training"]
        for row in included:
            declared = row["activity"].get("resources")
            if isinstance(declared, dict):
                declared["space"] = _space_alias(declared.get("space"))
        status, reason, parts = original_resources(public, included, released)
        if len(included) != len(candidates):
            status = _combine((status, "unknown"))
            parts = {key: _combine((value, "unknown")) for key, value in parts.items()}
            reason += " Existing-linked or unresolved event resources are outside the additional-training supply proof."
        return status, reason, parts

    def checked_core(public, response, resources_, candidate_id, format_valid):
        active["response"] = response
        try:
            rows, context = original_core(public, response, resources_, candidate_id, format_valid)
        finally:
            active.clear()
        by_id = {row["check_id"]: row for row in rows}
        _numeric_limit_correction(public, response, context, by_id["additional_training_limits"])
        for alias, dependencies in {"rule:USER_AVAILABLE_TIME": ("availability_and_collisions", "additional_training_limits"),
                                    "rule:POLICY_REQUIRED_INFORMATION": ("response_type_basis",),
                                    "rule:POLICY_SCOPE": ("response_type_basis",)}.items():
            if alias not in by_id or alias == "rule:POLICY_SCOPE" and (response or {}).get("response_type") != "constraint_conflict":
                continue
            source = [by_id[key] for key in dependencies]
            by_id[alias].update(status=_combine(v["status"] for v in source),
                                reason="; ".join(dict.fromkeys(v["reason"] for v in source)))
        context["pilot_core_statuses"] = {row["check_id"]: row["status"] for row in rows}
        for row in rows:
            row.setdefault("data_versions", {})["reviewed_planning_checks"] = VERSION
        return rows, context

    core["_basis"], core["_resources"], core["core_checks"] = basis, resources, checked_core
    original_external = checker.external

    def external(public, response, packet, resources, candidate_id, context=None):
        rows = original_external(public, response, packet, resources, candidate_id, context)
        focused = focus.assess_food(public, response or {}, packet, base_assess_food=food.assess_food)
        for row in rows:
            if row["check_id"] == "food_facts_numeric":
                required = [v for v in focused if v["check_id"] in {"food_answer_completeness", "food_numeric_correctness"}]
                row.update(status=_combine(v["status"] for v in required),
                           reason="; ".join(dict.fromkeys(v["reason"] for v in required)),
                           observed={"reviewed_food_checks": deepcopy(required)})
        return rows

    checker.external = external
    checker.reviewed_planning_policy = {"version": VERSION, "prospective_only": True,
        "universal_semantic_validation": False, "old_source_files_changed": False}
    return checker


def make_checker(root, client, policy, resources=None):
    root = Path(root).resolve()
    original = _module(root, "pilot_schedule").make_checker(root, client, policy, resources=resources)
    return _review_checker(original, root)


def make_assessor(root, public_schema):
    root = Path(root).resolve()
    assessor = _module(root, "food_answer_audit").make_assessor(root, public_schema)
    assessor.calendar = _review_checker(assessor.calendar, root)
    focus = _module(root, "food_fact_focus")
    frozen_food, frozen_resources, original_assess = assessor.food, assessor.resources, assessor.assess
    original_space_kind = frozen_resources._space_kind
    frozen_resources._space_kind = lambda value: original_space_kind(_space_alias(value))
    current = {}
    assessor.food = SimpleNamespace(assess_food=lambda public, response, packet:
        focus.assess_food(public, response, packet, base_assess_food=frozen_food.assess_food))

    def resources(public, activities, contracts):
        classified = [(activity, resource_scope(public, current.get("response"), activity)) for activity in activities]
        included = [activity for activity, scope in classified if scope == "new_training"]
        report = deepcopy(frozen_resources.assess_resources(public, included, contracts))
        ambiguous = [(activity, scope) for activity, scope in classified if scope != "new_training"]
        if ambiguous:
            for row in report["checks"]:
                row.update(status=_combine((row["status"], "unknown")),
                           reason=row["reason"] + " Existing-linked or unresolved event resources are not evidence of an additional-training shortage.")
            report["per_activity"].extend({"activity_index": len(included) + index,
                "activity_id": activity.get("activity_id"), "resource_scope": scope,
                "declared_status": "unknown", "requirements_status": "unknown",
                "contract_id": None, "source_catalog_id": None, "eligibility_status": "unknown", "catalog_id_required": False,
                "reasons": ["Existing-event or unresolved component resources require separate context; graph/commitment checks remain active."]}
                for index, (activity, scope) in enumerate(ambiguous))
            for row in report["checks"]:
                field = "declared_status" if row["check_id"] == "declared_resource_consistency" else "requirements_status"
                row["observed"] = {"activities": len(report["per_activity"]), "scope_unresolved": len(ambiguous),
                    **{status: sum(activity[field] == status for activity in report["per_activity"])
                       for status in ("met", "violated", "unknown")}}
        report["coverage"]["reviewed_event_scope"] = VERSION
        return report

    assessor.resources = SimpleNamespace(assess_resources=resources)

    def assess(public_record, outcome, truth_packet, *, assessment_id):
        if current:
            raise ValueError("The reviewed assessor handles one outcome at a time.")
        raw = ((outcome.get("response") or {}).get("model_output") or {}).get("raw_text")
        parsed = assessor.client.response.parse_response_text(raw if isinstance(raw, str) else "", assessor.client.response_schema)
        current["response"] = parsed.get("parsed_object")
        try:
            result = original_assess(public_record, outcome, truth_packet, assessment_id=assessment_id)
        finally:
            current.clear()
        result["reviewed_planning_checks_version"] = VERSION
        result["old_saved_assessments_replaced"] = False
        result["human_review_claimed"] = False
        return result

    assessor.assess = assess
    assessor.dependency_sha256["src/champion_athletic_map/reviewed_planning_checks.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    assessor.dependency_sha256["src/champion_athletic_map/food_fact_focus.py"] = hashlib.sha256(Path(focus.__file__).read_bytes()).hexdigest()
    return assessor
