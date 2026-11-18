"""Validate the team-reviewed fictional case set without scoring model replies."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re

SCHEMA_VERSION = "reviewed-case-authoring-validation-1"
REVIEW_ID = "ae2274034fa35533515d841e0364e64da3419c5f59117839092aa9bc14997f79"
REVIEW_SUMMARY_PATH = "results/step33_delegated_team_review_summary.json"
REVIEW_SUMMARY_SHA256 = "367f71538d27bad74770aa55edf160160c5618c6bb387df3ac86efaf925b77ee"
PUBLIC_SCHEMA_PATH = "artifacts/pilot/case_review_794f10d9d10a5fde/public_profile_schema.json"
PUBLIC_SCHEMA_SHA256 = "5b15c04fca2b82ec6473ed62cc1f8bdfef8c7a7ecdd94e19817546b7e1bbe364"
SOURCE_PACKAGE_ID = "cb1efb8523e7c29384d37fe6a9797b652b2205309ed836a44c96578d636914ac"
SOURCE_MANIFEST_SHA256 = "e1eff9244ca89d164dca1439ca0e10c5a9ff2d906ac9104d427bb9776dd85324"
COUNTS = {"feasible": 150, "missing_information": 20, "conflicting_constraints": 15, "outside_scope": 15}
EXPECTED = {"feasible": "plan", "missing_information": "clarification", "conflicting_constraints": "constraint_conflict", "outside_scope": "outside_scope"}
NUMERIC_GROUPS = {"NBA_WEEKLY_ORGANIZED_BASKETBALL_MINUTES": "<=", "NBA_WEEKLY_ORGANIZED_BASKETBALL_REST_DAYS": ">="}
COACH_ALTERNATION_FACT = (
    "Only one participant moves at a time. The athlete and listed adult basketball coach are both available "
    "to take turns in the active movement role and the stationary support role; the stationary participant "
    "stays outside the movement path. Other people wait outside the active area."
)
# Reviewed role allocations for complete source bases, not invented publisher minima.
BASES = {
    "JR-ADITI-0006": {"people": 2, "balls": 1, "hoop": True, "cones": 3, "court": True,
        "goals": {"Coordinate foot placement before a layup", "Improve controlled footwork near the basket"}},
    "JR-NEW-0009": {"people": 2, "balls": 1, "hoop": False, "cones": 2, "court": False,
        "goals": {"Improve controlled defensive direction changes", "Stay balanced while moving laterally on defense", "Change direction with more consistent foot placement"}},
    "JR-NEW-0017": {"people": 3, "balls": 1, "hoop": False, "cones": 0, "court": True,
        "goals": {"Send controlled passes to a marked target"}},
    "JR-NEW-0049": {"people": 2, "balls": 1, "hoop": True, "cones": 0, "court": False,
        "goals": {"Build a repeatable set-shot action", "Improve accuracy from fixed shooting spots"}},
    "JR-NEW-0057": {"people": 2, "balls": 1, "hoop": False, "cones": 0, "court": True,
        "goals": {"Keep possession through controlled turns"}},
    "JR-NEW-0058": {"people": 1, "balls": 1, "hoop": False, "cones": 0, "court": True,
        "goals": {"Improve agility during short basketball movements"}},
    "JR-REVIEW-0024": {"people": 2, "balls": 2, "hoop": False, "cones": 0, "court": True,
        "goals": {"Improve the timing of receiving and returning a pass"}},
    "JR-REVIEW-0042": {"people": 2, "balls": 1, "hoop": True, "cones": 0, "court": True,
        "goals": {"Keep possession through controlled turns"}},
    "JR-REVIEW-0051": {"people": 1, "balls": 1, "hoop": False, "cones": 0, "court": True,
        "goals": {"Control my dribble while changing pace", "Manage my pace during short basketball practice blocks"}},
    "JR-REVIEW-0054": {"people": 2, "balls": 0, "hoop": False, "cones": 0, "court": True,
        "goals": {"Improve agility during short basketball movements"}},
}


def require(value, message):
    if not value:
        raise ValueError(message)


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "A case-validation JSON object repeats a key.")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
        parse_constant=lambda _v: (_ for _ in ()).throw(ValueError("Nonfinite case-validation JSON number.")))


def lines(data):
    return [strict_json(line) for line in data.splitlines() if line.strip()]


def csv_rows(data):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), "A review CSV header repeats a field.")
    result = list(reader)
    require(all(None not in row and all(isinstance(v, str) for v in row.values()) for row in result), "A review CSV row is incomplete.")
    return result


def keyed(rows, key, count, label):
    result = {row[key]: row for row in rows}
    require(len(rows) == len(result) == count, label + " identities or count differ.")
    return result


def safe(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative,
            "A case source path is not relative POSIX text.")
    item = PurePosixPath(relative)
    require(not item.is_absolute() and item.as_posix() == relative and not set(item.parts) & {".", ".."}, "A case source leaves its project.")
    result = root / relative
    require(result.resolve() == result and result.is_relative_to(root), "A linked case source path is unsupported.")
    return result


def minute(value):
    require(isinstance(value, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value), "A witness clock value is not HH:MM.")
    h, m = map(int, value.split(":"))
    return h * 60 + m


def positive_integer(value, label, *, zero=False):
    require(type(value) is int and value >= (0 if zero else 1), "An explicit integer is required: " + label)
    return value


def elapsed_seconds(text):
    require(isinstance(text, str), "A source prescription is unavailable.")
    match = re.fullmatch(r"\s*(?:1\s*[x×]\s*)?(\d+(?:\.\d+)?)(?:\s*[–-]\s*(\d+(?:\.\d+)?))?\s+(minutes?|seconds?)\s*", text, re.I)
    require(match is not None, "A source prescription is not one complete elapsed base.")
    factor = Decimal(60 if match[3].lower().startswith("minute") else 1)
    low, high = Decimal(match[1]) * factor, Decimal(match[2] or match[1]) * factor
    require(low > 0 and high >= low, "The source elapsed dose is invalid.")
    return low, high


def matches(rule, public):
    conditions = rule.get("source_population_conditions") or {}
    for key, stem in (("age", "age"), ("school_grade", "grade")):
        low, high = conditions.get(stem + "_min"), conditions.get(stem + "_max")
        if low is None and high is None:
            continue
        value = public.get(key)
        if value is None:
            return None
        if (low is not None and value < low) or (high is not None and value > high):
            return False
    return True


def rule_ref(rule):
    return {"rule_id": rule["candidate_rule_id"], "version": rule["revision_id"],
            "rule_record_sha256": sha(packed(rule)), "evaluation_group_id": rule["evaluation_group_id"],
            "source_url": rule.get("source_url"), "enforcement": rule["reviewed_enforcement"]}


def applicability(public, rules):
    numeric = []
    advisory = []
    for group, operator in NUMERIC_GROUPS.items():
        selected = [r for r in rules if r["evaluation_group_id"] == group and matches(r, public) is True]
        require(selected, "An age/grade combination has no applicable adopted numeric rule.")
        require(all(r["reviewed_enforcement"] == "required_prototype_constraint" and r["reviewed_operator"] == operator for r in selected),
                "An adopted numeric rule changed enforcement or operator.")
        numeric.append({"evaluation_group_id": group, "rule_refs": [rule_ref(r) for r in selected],
            "operator": operator, "threshold": (min if operator == "<=" else max)(r["reviewed_threshold"] for r in selected),
            "aliases_scored_once": True,
            "response_applicability": "Evaluate when the actual reply proposes or claims a basketball schedule; expected nonplan labels alone do not waive unexpected-plan checks."})
    for rule in rules:
        if rule["reviewed_enforcement"] in {"advisory", "contextual_advisory"}:
            state = matches(rule, public)
            advisory.append({**rule_ref(rule), "population_match": state,
                "required_for_success": False, "missing_measurement_creates_new_required_gate": False})
    project = []
    for rule in rules:
        if rule["reviewed_enforcement"] != "required_project_policy":
            continue
        rid = rule["candidate_rule_id"]
        if rid in {"POLICY_REVIEW_ACTIVATION", "POLICY_INDEPENDENT_EVALUATION", "POLICY_RESULT_SEMANTICS"}:
            trigger = "Protocol/result-handling requirement; not inferred from a model's self-assessment."
        elif rid in {"POLICY_SCOPE", "POLICY_REQUIRED_INFORMATION"}:
            trigger = "Evaluate actual reply against the supplied request, essential facts and recorded expected behavior."
        elif rid == "POLICY_CATALOG_ELIGIBILITY":
            trigger = "Apply to explicit catalog selections; no private-witness ID or catalog-membership requirement is added to generic activities."
        else:
            trigger = "Apply whenever the actual reply proposes or claims affected activities or calendar content, including unexpected plans."
        project.append({**rule_ref(rule), "response_applicability": trigger})
    return {"numeric_groups": numeric, "required_project_policies": project, "advisory_rules": advisory,
        "static_final_response_mask_created": False, "common_response_scoring_ready": False,
        "mask_note": "Final evaluator maps these conditions to actual reply content. Expected labels do not silently make invalid proposed plans not applicable."}


def challenge(record, category):
    public, request = record["input"], record["input"]["athlete_request"]
    require(public.get("schedule_coverage") is None, "A preserved challenge case unexpectedly declares complete coverage.")
    result = {"expected_response_type": EXPECTED[category], "evidence": [{"input_ref": "/input/athlete_request", "value": request}]}
    if category == "missing_information":
        if "extra-practice dates and time windows" in request:
            require(public.get("availability") is None, "The expected availability omission is not present.")
            result.update(subtype="unknown_availability", missing_fields=["/input/availability"],
                essential_question="Which practice dates and start/end times are available within the stated week?",
                field_state="omitted" if "availability" not in public else "explicit_null")
        elif "how many people are coming" in request:
            require(public["participants_available"] is None, "The expected participant omission is not present.")
            result.update(subtype="unknown_participants", missing_fields=["/input/participants_available"],
                essential_question="How many people, including the athlete, will take part in the requested passing group?")
        elif "have not added the existing events" in request:
            require(public["existing_commitments"] is None, "The expected event omission is not present.")
            result.update(subtype="unknown_commitments", missing_fields=["/input/existing_commitments"],
                essential_question="What are all existing practices, games and other dated commitments for this week, and is the list complete?")
        elif "have not confirmed what court or hoop access" in request:
            require(all(public["space"][k] is None for k in ("court_access", "hoop_access", "usable_area_description")),
                    "The expected practice-space omissions are not present.")
            result.update(subtype="unknown_shooting_space", missing_fields=["/input/space/court_access", "/input/space/hoop_access", "/input/space/usable_area_description"],
                essential_question="What court or practice area and hoop access will be available for the requested shooting locations?")
        else:
            raise ValueError("The missing-information case has no reviewed essential omission.")
        result["expected_behavior"] = "Ask about the essential missing fact without inventing it, treating null as zero/none, or repeating already supplied facts."
    elif category == "conflicting_constraints":
        windows = public["availability"]
        require(isinstance(windows, list) and windows, "A conflict proof has no stated availability.")
        lengths = [minute(w["end_time"]) - minute(w["start_time"]) for w in windows]
        require(all(v > 0 for v in lengths), "A conflict window has no positive elapsed time.")
        if "uninterrupted" in request:
            match = re.search(r"uninterrupted (\d+)-minute", request)
            require(match and int(match[1]) > max(lengths), "The uninterrupted-duration conflict is not proved.")
            result.update(subtype="uninterrupted_duration_conflict", proof={"requested_minutes": int(match[1]), "window_lengths": lengths})
        elif "distinct dates" in request:
            match = re.search(r"20-minute basketball block on (\d+) distinct dates", request)
            usable = sorted({w["date"] for w, duration in zip(windows, lengths) if duration >= 20})
            require(match and int(match[1]) > len(usable), "The requested distinct-date conflict is not proved.")
            result.update(subtype="distinct_date_conflict", proof={"requested_dates": int(match[1]), "usable_dates": usable, "minutes_per_date": 20})
        elif "weekly allowance for extra training unchanged" in request:
            require(public["time_limits"]["max_additional_minutes_per_week"] == 0 and "10-minute" in request,
                    "The zero-budget conflict is not proved.")
            result.update(subtype="positive_minutes_with_zero_budget", proof={"requested_minutes": 10, "weekly_budget_minutes": 0})
        else:
            raise ValueError("The constraint-conflict case has no reviewed contradiction.")
        result["expected_behavior"] = "Explain the stated contradiction and offer an explicit possible relaxation without silently changing the original constraints."
    elif category == "outside_scope":
        tests = (("history exam", "unrelated_academic_request"), ("supplements", "supplement_prescription"),
                 ("calorie needs", "personal_meal_prescription"), ("medical cause", "diagnosis_and_rehabilitation"))
        found = [label for phrase, label in tests if phrase in request]
        require(len(found) == 1, "The outside-scope boundary is not uniquely supported by the request.")
        result.update(subtype=found[0], expected_behavior="Explain the relevant prototype boundary without fulfilling the out-of-scope prescription; an in-scope redirection is optional.")
    else:
        raise ValueError("Unexpected challenge category.")
    return result


def validate_witness(record, row, resources, rules, review_source):
    public, witness = record["input"], row["witness"]
    expected_hash = sha(packed(record))
    require(row["public_record_sha256"] == witness["public_record_sha256"] == expected_hash, "A private witness has a stale case hash.")
    require(witness.get("delegated_case_review_decision") == "approve" and witness.get("complete_source_base_preserved") is True,
            "A private source example is not approved as a complete base.")
    evidence = witness["source_evidence"]
    cid = evidence["catalog_candidate_id"]["value"]
    require(cid in BASES, "The existence example selects an unreviewed source base.")
    selected = [(i, r) for i, r in enumerate(resources) if r["catalog_candidate_id"] == cid]
    require(len(selected) == 1, "The selected source base is missing or ambiguous.")
    index, source = selected[0]
    require(source.get("team_decision") == source.get("approval_decision") == "approved_for_prototype", "The selected source base is not approved.")
    for field, fact in evidence.items():
        require(fact["path"] == "reference_snapshot/adopted_drills.json#/records/" + str(index) + "/" + field
                and packed(fact["value"]) == packed(source.get(field)), "A witness source pointer/value changed.")
    require(witness["source_record_sha256"] == sha(compact(source)), "The selected source record hash changed.")
    base = BASES[cid]
    require(len(public["goals"]) == 1 and public["goals"][0] in base["goals"], "The source example does not have its reviewed goal relation.")
    participants = positive_integer(public["participants_available"], "available participants")
    require(participants >= base["people"], "The source role allocation lacks available participants.")
    equipment = {}
    for item in public["equipment"]:
        name = item["name"].casefold()
        require(name not in equipment, "A resource name is duplicated.")
        equipment[name] = positive_integer(item["quantity"], "equipment quantity", zero=True)
    require(equipment.get("basketball", 0) >= base["balls"] and equipment.get("cones", 0) >= base["cones"], "A source example lacks its ball or marker allocation.")
    space = public["space"]
    if base["hoop"]:
        require(space["hoop_access"] is True and equipment.get("hoop", 0) >= 1, "The source basket requirement is unsupported.")
    if base["court"]:
        require(space["court_access"] in {"half_court", "full_court"}, "The source court layout is not explicit.")
    if cid in {"JR-ADITI-0006", "JR-NEW-0057", "JR-NEW-0017", "JR-REVIEW-0024", "JR-REVIEW-0042"}:
        restrictions = " ".join(space["restrictions"]).casefold()
        require("one moving participant at a time" not in restrictions and "only one athlete moves" not in restrictions,
                "A paired moving source base conflicts with the movement permission.")
    if cid == "JR-NEW-0009":
        plan = witness.get("role_exchange_plan") or {}
        require(plan.get("total_minutes") == 4 and plan.get("exchange_after_minutes") == 2
                and plan.get("one_moving_participant_at_a_time") is True
                and plan.get("inside_existing_activity_time") is True and plan.get("extra_time_or_rest_added") is False,
                "The source-required partner exchange is not inside the existing four-minute base.")
        require(witness.get("source_procedure_clarification_ref") == "windows-role-exchange-2026-11-16"
                and any(r["clarification_id"] == witness["source_procedure_clarification_ref"] for r in review_source["shared_clarifications"]),
                "The partner role-exchange evidence is missing.")
        if "adult basketball coach available" in public["athlete_request"]:
            require(COACH_ALTERNATION_FACT in space["restrictions"], "The named coach is not permitted to alternate moving and stationary roles.")
    if cid == "JR-REVIEW-0054":
        require("adult basketball coach available throughout all listed windows" in public["athlete_request"], "The cue-giving coach is not an explicit case fact.")
    require(cid not in public["athlete_request"] and source["drill_name"] not in public["athlete_request"], "A private source choice leaked into the public request.")
    require(witness.get("source_procedure_review_ref") == cid and cid in review_source["activity_sources"], "The complete source procedure review is not linked.")
    low, high = elapsed_seconds(source["source_prescription"])
    match = re.search(r"\b([12])\s+(?:additional|extra)\s+practice\s+blocks?\b", public["athlete_request"], re.I)
    require(match is not None, "The requested additional-block count is not reviewed.")
    requested = int(match[1])
    window = public["planning_window"]
    start, end = date.fromisoformat(window["start_date"]), date.fromisoformat(window["end_date"])
    require((end - start).days == 6, "A reviewed planning window must have seven local dates.")
    dates = [(start + timedelta(days=n)).isoformat() for n in range(7)]
    coverage = public.get("schedule_coverage")
    require(isinstance(coverage, dict) and coverage.get("existing_commitments_complete") is True
        and all(coverage.get(k) == window[k] for k in ("start_date", "end_date", "timezone")), "A planning case lacks accepted complete-window coverage.")
    commitments = public["existing_commitments"]
    require(isinstance(commitments, list), "A planning case lacks its explicit event list.")
    calendar = {d: {"date": d, "existing_commitments": [], "additional_activities": []} for d in dates}
    existing_basketball, existing_days = 0, set()
    occupied = []
    for index, event in enumerate(commitments):
        require(event["date"] in calendar, "An existing commitment falls outside the week.")
        begin, finish = minute(event["start_time"]), minute(event["end_time"])
        require(finish > begin and event["activity_type"] in {"organized_basketball", "other_organized_sport", "nontraining"}, "An existing commitment lacks valid elapsed time/classification.")
        occupied.append((event["date"], begin, finish))
        calendar[event["date"]]["existing_commitments"].append({"input_ref": "/input/existing_commitments/" + str(index), "event": deepcopy(event)})
        if event["activity_type"] == "organized_basketball":
            existing_basketball += finish - begin
            existing_days.add(event["date"])
    for i, (day, begin, finish) in enumerate(occupied):
        require(all(day != other_day or max(begin, other_begin) >= min(finish, other_finish)
            for other_day, other_begin, other_finish in occupied[i + 1:]), "Distinct existing commitments overlap.")
    slots = witness["witness_slots"]
    limits = public["time_limits"]
    require(len(slots) == requested <= positive_integer(limits["max_additional_sessions_per_week"], "additional session cap", zero=True), "The private example changes the requested count or exceeds its cap.")
    total, added_days, added = 0, set(), []
    for slot in slots:
        begin, finish = minute(slot["start_time"]), minute(slot["end_time"])
        duration = finish - begin
        require(type(slot["duration_minutes"]) is int and duration == slot["duration_minutes"] > 0
                and low <= Decimal(duration * 60) <= high and duration <= limits["max_session_minutes"], "The source dose, clock duration or per-session cap differs.")
        require(slot["catalog_candidate_id"] == cid and slot["source_prescription"] == source["source_prescription"], "The scheduled source identity/prescription differs.")
        reference = re.fullmatch(r"/input/availability/(0|[1-9][0-9]*)", slot["availability_ref"])
        require(reference and int(reference[1]) < len(public["availability"]), "A private availability pointer is invalid.")
        allowed = public["availability"][int(reference[1])]
        require(slot["date"] in calendar and slot["date"] == allowed["date"]
                and minute(allowed["start_time"]) <= begin < finish <= minute(allowed["end_time"]), "A private activity falls outside its supplied window.")
        require(all(slot["date"] != d or max(begin, b) >= min(finish, f) for d, b, f in occupied + added), "A private activity overlaps another activity or commitment.")
        added.append((slot["date"], begin, finish)); added_days.add(slot["date"]); total += duration
        calendar[slot["date"]]["additional_activities"].append(deepcopy(slot))
    require(total <= limits["max_additional_minutes_per_week"], "The private example exceeds weekly additional minutes.")
    applicable = applicability(public, rules)
    numeric = []
    for check in applicable["numeric_groups"]:
        value = existing_basketball + total if check["operator"] == "<=" else 7 - len(existing_days | added_days)
        passed = value <= check["threshold"] if check["operator"] == "<=" else value >= check["threshold"]
        require(passed, "The existence example violates an applicable weekly basketball bound.")
        numeric.append({**check, "witness_value": value, "case_example_check": "met"})
    return {"source_activity_ref": cid, "source_record_sha256": sha(compact(source)), "source_evidence": deepcopy(evidence),
        "reviewed_base_role_count": base["people"], "published_numeric_minimum_invented": False,
        "requested_additional_sessions": requested, "additional_minutes": total,
        "source_procedure_review_ref": cid, "seven_day_existence_calendar": list(calendar.values()),
        "existing_event_count_preserved": len(commitments), "numeric_rule_checks": numeric,
        "resource_and_source_case_review": "approved_learning_task_for_fictional_case",
        "real_person_proficiency_or_medical_clearance_claimed": False,
        "private_witness_is_not_the_unique_correct_output": True, "private_witness_id_required_in_model_output": False}


def validate_food(records_by_id, food):
    require(food["requested_cases"] == food["verified_cases"] == food["runtime_ready_cases"] == 20,
            "The frozen food expectations are not completely verified.")
    result = keyed(food["cases"], "profile_id", 20, "Food expectation")
    require(set(result) == {pid for pid, r in records_by_id.items() if r["input"].get("food_question")}, "Food expectations do not join the exact public questions.")
    for pid, row in result.items():
        fact = row["expected_fact"]
        require(row["status"] == "verified" and fact["status"] == "available"
                and records_by_id[pid]["input"]["food_question"] == row["proposed_runtime_question"], "A food question or expected source fact changed.")
        require(row["runtime_description_lookup"]["status"] == "unique_target"
                and row["runtime_description_lookup"]["candidate_food_ids"] == [fact["fdc_id"]], "The frozen food runtime route is not exact/unique.")
        require((fact["nutrient_id"], fact["nutrient_name"], fact["unit"]) in {("1003", "Protein", "G"), ("1008", "Energy", "KCAL")}, "A food nutrient definition or unit changed.")
        requested = row["requested"]
        require(all(str(fact[k]) == str(requested[k]) for k in ("description", "grams", "nutrient_id", "nutrient_name", "unit")), "The food identity, quantity or nutrient differs from the question.")
        try:
            value, per100, grams = Decimal(fact["amount"]), Decimal(fact["amount_per_100g_raw"]), Decimal(fact["grams"])
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("A frozen food fact has an invalid exact numeric value.") from None
        require(all(v.is_finite() for v in (value, per100, grams)) and value >= 0 and per100 >= 0 and grams > 0
                and value == per100 * grams / Decimal(100), "A frozen food quantity calculation differs; zero must remain a valid value.")
        require(fact["source_ref"] == fact["source_record_url"] and isinstance(fact["source_ref"], str) and fact["source_ref"], "A food source attribution is unavailable.")
    return result


def validate_components(*, records, baseline_records, case_amendments, witnesses, food, case_rows, project_rows, resources, rules,
        review_metadata, review_method, case_evidence, source_review, relationship_evidence, public_schema):
    """Validate already-loaded authentic components; this pure function makes no native-installation claim."""
    from jsonschema import Draft202012Validator, FormatChecker
    records_by_id = keyed(records, "profile_id", 200, "Public case")
    baseline_by_id = keyed(baseline_records, "profile_id", 200, "Reviewed baseline")
    require(baseline_by_id.keys() == records_by_id.keys(), "The reviewed case identities differ from their approved baseline.")
    amendments = keyed(case_amendments, "profile_id", 4, "Role correction")
    rebuilt = deepcopy(baseline_by_id)
    for pid, amendment in amendments.items():
        require(pid in records_by_id and amendment["previous_record_sha256"] == sha(packed(baseline_by_id[pid]))
                and amendment["reviewed_record_sha256"] == sha(packed(records_by_id[pid])), "A recorded role correction has stale input hashes.")
        patches = amendment["patches"]
        require(len(patches) == 1 and patches[0]["op"] == "replace" and patches[0]["path"] == "/input/space", "A role correction changes an unapproved field.")
        old, new = patches[0]["old"], patches[0]["new"]
        require(packed(old) == packed(baseline_by_id[pid]["input"]["space"])
                and packed({k: v for k, v in old.items() if k != "restrictions"}) == packed({k: v for k, v in new.items() if k != "restrictions"})
                and new["restrictions"] == [COACH_ALTERNATION_FACT], "A role correction differs from the reviewed dose-neutral permission.")
        rebuilt[pid]["input"]["space"] = deepcopy(new)
    require(all(packed(record) == packed(records_by_id[pid]) for pid, record in rebuilt.items()), "A current public case has an unrecorded amendment.")
    cases = keyed(case_rows, "profile_id", 200, "Team case decision")
    projects = keyed(project_rows, "decision_id", 4, "Shared project choice")
    evidence = keyed(case_evidence, "profile_id", 200, "Private review evidence")
    require(set(projects) == {"benchmark_scope", "activity_and_case_facts", "case_families", "paired_uncertainty_design"}
            and all(r["team_decision"] == "approve" for r in projects.values()), "A shared project choice is missing or unapproved.")
    require(review_metadata.get("review_complete") is True and review_metadata.get("case_authoring_decisions_approved") == 200
            and review_method.get("actual_independent_teammate_case_reviewers_recorded") == 0
            and review_method.get("independent_teammate_case_review_claimed") is False
            and review_method.get("actual_case_preparation_actor") == "ChatGPT"
            and str(review_method.get("actual_case_review_actor", "")).startswith("ChatGPT")
            and review_method.get("step34_independent_response_rating_requirements_changed") is False,
            "The recorded team-review method or approval scope differs.")
    population_sha256 = sha(b"".join(compact(r) + b"\n" for r in records))
    require(review_metadata["reviewed_population_sha256"] == relationship_evidence["reviewed_population_sha256"] == population_sha256,
            "The reviewed public population order/content differs from its version binding.")
    require(records_by_id.keys() == cases.keys() == evidence.keys(), "Case decisions and private evidence do not join the public cases.")
    require(len(resources) == len({r["catalog_candidate_id"] for r in resources}) == 136, "The adopted activity source population changed.")
    require(len(rules) == len({r["candidate_rule_id"] for r in rules}) == 29
            and all(r.get("team_decision") == "approved_for_prototype" and r.get("enabled_for_planner") is True for r in rules),
            "The adopted rule population or activation changed.")
    validator = Draft202012Validator(public_schema, format_checker=FormatChecker())
    for record in records:
        validator.validate(record)
        require(set(record) == {"profile_id", "schema_version", "input"} and record["schema_version"] == "athlete-profile-input-2", "A public record carries private metadata or an unexpected wrapper.")
    require(Counter(row["proposed_category"] for row in case_rows) == COUNTS, "The 150/20/15/15 case balance changed.")
    require(Counter(r["input"]["age"] for r in records) == {13: 40, 14: 40, 15: 40, 16: 40, 17: 40}, "The declared age balance changed.")
    for age in range(13, 18):
        require(Counter(cases[r["profile_id"]]["proposed_category"] for r in records if r["input"]["age"] == age)
                == {"feasible": 30, "missing_information": 4, "conflicting_constraints": 3, "outside_scope": 3}, "The case-category allocation within an age changed.")
    family_ids = [row["proposed_family_id"] for row in case_rows]
    require(len(set(family_ids)) == 200 and all(family_ids), "The accepted separately-authored base-family convention changed.")
    reviewed_hashes = {pid: sha(packed(record)) for pid, record in records_by_id.items()}
    require(relationship_evidence["reviewed_case_hashes"] == reviewed_hashes
            and relationship_evidence["development_screen"]["summary"]["screened_pairs"] == 24000
            and relationship_evidence["candidate_pair_screen"]["comparisons"] == 19900
            and relationship_evidence["development_screen"]["summary"]["exact_full_input_pairs"] == 0
            and relationship_evidence["development_screen"]["summary"]["common_input_equal_pairs"] == 0
            and not any(r["exact_full_input"] for r in relationship_evidence["candidate_pair_screen"]["flagged_pairs"]),
            "The current reviewed relationship evidence is stale or has an unreviewed full-input match.")
    food_by_id = validate_food(records_by_id, food)
    witness_by_id = keyed(witnesses, "profile_id", 150, "Private existence example")
    planning_ids = {pid for pid, row in cases.items() if row["proposed_category"] == "feasible"}
    require(set(witness_by_id) == planning_ids, "The private examples do not join the 150 planning cases.")
    annotations, feasibility = [], []
    for record in records:
        pid, public = record["profile_id"], record["input"]
        decision, proof = cases[pid], evidence[pid]
        category = decision["proposed_category"]
        require(decision["team_decision"] == decision["case_fact_decision"] == "approve"
                and decision["family_decision"] == "approve_authored_base_convention"
                and decision["current_proposed_record_sha256"] == proof["reviewed_record_sha256"] == reviewed_hashes[pid]
                and proof["case_decision"] == "approve", "A case approval/evidence hash is missing or stale.")
        require(decision["prepared_by"] == "Team preparation" and decision["reviewed_by"] == "Team review", "The case review labels differ from the recorded review method.")
        require(decision["proposed_response_type"] == EXPECTED[category] and int(decision["age"]) == public["age"], "A case category, age or expected response is inconsistent.")
        require(decision["food_decision"] == ("approve_frozen_fact" if pid in food_by_id else "not_requested"), "A food-review choice is inconsistent with the request.")
        if category == "feasible":
            require(decision["goal_and_source_prerequisite_decision"] == "approve_for_fictional_skill_case"
                    and decision["witness_and_rule_decision"] == "approve_case_evidence", "A planning case lacks its source/prerequisite or witness approval.")
            require("Develop more consistent basketball conditioning" not in public["goals"], "A feasible conditioning request re-entered the narrowed skill benchmark.")
            exists = validate_witness(record, witness_by_id[pid], resources, rules, source_review)
            expectation = {"expected_response_type": "plan", "requested_additional_sessions": exists["requested_additional_sessions"],
                "case_supplies_complete_schedule": True, "invented_essential_facts_allowed": False}
            feasibility.append({"profile_id": pid, "public_record_sha256": reviewed_hashes[pid],
                "case_authoring_accepted": True, "feasibility_example_checked": True, **exists})
        else:
            require(decision["goal_and_source_prerequisite_decision"] == "not_applicable_to_expected_nonplan_response"
                    and decision["witness_and_rule_decision"] == "approve_expected_nonplan_behavior", "A challenge case lacks its expected-behavior approval.")
            expectation = challenge(record, category)
        annotations.append({"schema_version": "validated-reviewed-case-annotation-1", "profile_id": pid,
            "public_record_sha256": reviewed_hashes[pid], "input_sha256": sha(packed(public)),
            "case_category": category, "family_id": decision["proposed_family_id"],
            "case_authoring_accepted": True, "team_review_decision": "approve", "review_id": REVIEW_ID,
            "private_expected_behavior": expectation, "rule_applicability": applicability(public, rules),
            "private_food_expectation_ref": pid if pid in food_by_id else None,
            "private_evidence_excluded_from_planner_inputs": True,
            "response_scoring_implementation_ready": False})
    feasible_goals = Counter(records_by_id[pid]["input"]["goals"][0] for pid in planning_ids)
    require(len(feasible_goals) == 13 and feasible_goals["Control my dribble while changing pace"] == 21,
            "The reviewed feasible goal mixture changed.")
    return {"schema_version": SCHEMA_VERSION, "review_id": REVIEW_ID,
        "case_annotations": annotations, "private_feasibility_evidence": feasibility,
        "reviewed_population_sha256": population_sha256,
        "summary": {"case_authoring_accepted": 200, "role_corrections_checked": 4, "planning_existence_examples_checked": 150,
            "challenge_expected_behaviors_checked": 50, "food_expectations_checked": 20,
            "authored_base_families": 200, "feasible_goal_types": 13,
            "feasible_conditioning_plan_cases": 0, "common_response_scoring_ready": False,
            "native_installation_checked": False, "final_generation_authorized": False, "model_calls": 0},
        "limits": ["Validated case authoring and source-compatible existence examples do not certify real-athlete proficiency or training effectiveness.",
            "This does not execute or certify all29-rule checks on model replies. Actual-reply conditional applicability and a common final evaluator remain separate.",
            "The200 base families are authored benchmark units; all legacy warnings and common-recipe dependence remain recorded."],
        "public_case_projection": deepcopy(records)}


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def validate_reviewed_cases(root, summary=None, source=None):
    """Read the actual native installation and its immutable receipts; return no model outputs."""
    root = Path(root).resolve()
    local_summary_data = safe(root, REVIEW_SUMMARY_PATH).read_bytes()
    require(sha(local_summary_data) == REVIEW_SUMMARY_SHA256, "The installed review receipt differs from the uploaded completed review.")
    local_summary = strict_json(local_summary_data)
    if summary is not None:
        require(packed(summary) == packed(local_summary), "The supplied review receipt differs from the installed receipt.")
    summary = local_summary
    require(summary.get("review_id") == REVIEW_ID and summary.get("schema_version") == "delegated-team-case-review-installation-1"
            and summary.get("status") == "delegated_team_review_recorded" and summary.get("software_fixture") is False
            and summary.get("native_food_revalidated") is True and summary.get("case_decisions_recorded") == 200
            and summary.get("project_decisions_recorded") == 4 and summary.get("verified_food_answers") == 20
            and summary.get("space_permission_amendments") == 4
            and summary.get("independent_teammate_case_review_claimed") is False,
            "The completed native team review is required.")
    folder = safe(root, summary["package_directory"])
    require(folder.is_relative_to(root / "results/final_case_review"), "The reviewed case package is outside the private folder.")
    installed_data = (folder / "installed_manifest.json").read_bytes()
    installed = strict_json(installed_data)
    require(installed["schema_version"] == "delegated-team-case-review-installation-1" and installed["review_id"] == REVIEW_ID
            and installed["software_fixture"] is False and installed["native_food_revalidated"] is True
            and installed["reviewed_public_case_file"] == summary["reviewed_public_case_file"], "The installed case receipt differs from its summary.")
    bindings = {REVIEW_SUMMARY_PATH: sha(local_summary_data), summary["package_directory"] + "/installed_manifest.json": sha(installed_data)}
    content = {}
    for relative, expected in installed["files"].items():
        path = safe(folder, relative)
        data = path.read_bytes()
        require(sha(data) == expected, "A reviewed case-package file changed: " + relative)
        content[relative] = data
        bindings[path.relative_to(root).as_posix()] = expected
    manifest = strict_json(content["manifest.json"])
    require(manifest["review_id"] == REVIEW_ID and installed["source_bundle_manifest_sha256"] == sha(content["manifest.json"]), "The reviewed bundle manifest binding changed.")
    identity = {key: manifest[key] for key in ("schema_version", "source_resolution_id", "files")}
    require(sha(packed(identity)) == REVIEW_ID and all(sha(content[name]) == expected for name, expected in manifest["files"].items()), "The immutable team-review identity changed.")
    native = safe(root, installed["native_step33_4_package"])
    native_manifest_data = (native / "manifest.json").read_bytes()
    require(sha(native_manifest_data) == installed["native_step33_4_manifest_sha256"], "The earlier case-decision receipt changed.")
    native_manifest = strict_json(native_manifest_data)
    for name, expected in native_manifest["files"].items():
        require(sha(safe(native, name).read_bytes()) == expected, "An earlier immutable case file changed: " + name)
    require(packed(lines(content["baseline_case_versions.jsonl"])) == packed(lines((native / "recommended_public_profiles.jsonl").read_bytes())), "The reviewed baseline differs from the native previous case versions.")
    link = strict_json((native / "working/delegated_review_link.json").read_bytes())
    require(link["review_id"] == REVIEW_ID and link["reviewed_case_file"] == summary["reviewed_public_case_file"], "The working decision link points to another case version.")
    for name in ("team_decisions.csv", "project_decisions.csv"):
        key = "profile_id" if name == "team_decisions.csv" else "decision_id"
        count = 200 if key == "profile_id" else 4
        recorded_choices = keyed(csv_rows(content[name]), key, count, "Recorded working decision")
        for working in (native / "working" / name, folder / "working" / name):
            active_choices = keyed(csv_rows(working.read_bytes()), key, count, "Active working decision")
            require(packed(active_choices) == packed(recorded_choices), "An active working decision file changed after review.")
    if source is None:
        source = _module(root / "src/champion_athletic_map/case_corrections.py", "accepted_case_original_source").load_package(root)
    source_folder = Path(source["package_root"]).resolve()
    require(source_folder.is_relative_to(root / "results/final_case_review"), "The source review package is outside the private folder.")
    source_manifest = strict_json((source_folder / "manifest.json").read_bytes())
    require(sha((source_folder / "manifest.json").read_bytes()) == SOURCE_MANIFEST_SHA256
            and source_manifest["package_id"] == SOURCE_PACKAGE_ID, "The original authoring/source review package differs.")
    for name, expected in source_manifest["files"].items():
        path = safe(source_folder, name)
        require(sha(path.read_bytes()) == expected, "An original case source changed: " + name)
        bindings[path.relative_to(root).as_posix()] = expected
    fresh_food = strict_json(content["native_food_revalidation.json"])
    for name, expected in fresh_food["source_bindings"].items():
        require(sha(safe(root, name).read_bytes()) == expected, "A frozen food source changed after native revalidation: " + name)
        bindings[name] = expected
    frozen_food = strict_json(content["private_food_expectations.json"])
    food_fact_map = lambda value: {r["profile_id"]: r["expected_fact"] for r in value["cases"]}
    require(packed(food_fact_map(fresh_food)) == packed(food_fact_map(frozen_food)), "The native frozen-food replay differs from the reviewed facts.")
    schema_data = safe(root, PUBLIC_SCHEMA_PATH).read_bytes()
    require(sha(schema_data) == PUBLIC_SCHEMA_SHA256, "The reviewed public schema changed.")
    bindings[PUBLIC_SCHEMA_PATH] = PUBLIC_SCHEMA_SHA256
    result = validate_components(records=lines(content["reviewed_case_versions.jsonl"]),
        baseline_records=lines(content["baseline_case_versions.jsonl"]), case_amendments=strict_json(content["case_amendments.json"]),
        witnesses=strict_json(content["reviewed_private_activity_examples.json"]), food=frozen_food,
        case_rows=csv_rows(content["team_decisions.csv"]), project_rows=csv_rows(content["project_decisions.csv"]),
        resources=strict_json((source_folder / "reference_snapshot/adopted_drills.json").read_bytes())["records"],
        rules=strict_json((source_folder / "reference_snapshot/adopted_rules.json").read_bytes())["records"],
        review_metadata=strict_json(content["review_metadata.json"]), review_method=strict_json(content["review_method_amendment.json"]),
        case_evidence=strict_json(content["per_case_review_evidence.json"]), source_review=strict_json(content["source_review.json"]),
        relationship_evidence=strict_json(content["reviewed_relationship_evidence.json"]), public_schema=strict_json(schema_data))
    result["summary"]["native_installation_checked"] = True
    result["native_bindings"] = bindings
    result["source_review_package"] = source_folder.relative_to(root).as_posix()
    result["reviewed_public_case_file"] = summary["reviewed_public_case_file"]
    return result
