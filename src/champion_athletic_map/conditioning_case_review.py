"""Review the eleven held goals and their explicit, unselected authoring alternatives.

This produces private decision evidence. It does not select an alternative,
accept a case, revise the benchmark, or make a model request.
"""
from collections import Counter
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re

OLD_GOAL = "Develop more consistent basketball conditioning"
NEW_GOAL = "Control my dribble while changing pace"
SOURCE_FIELDS = ("drill_name", "primary_goal", "instructions")


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _lines(path):
    return [json.loads(line) for line in Path(path).read_bytes().splitlines() if line.strip()]


def _minutes(value):
    _require(isinstance(value, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value), "An activity time is invalid.")
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _elapsed_kind(value):
    if not isinstance(value, str):
        return "not_a_single_explicit_elapsed_occurrence"
    plain = r"\s*\d+(?:\.\d+)?(?:\s*[–-]\s*\d+(?:\.\d+)?)?\s+(?:minutes?|seconds?)\s*"
    if re.fullmatch(plain, value, re.I):
        return "bare_explicit_elapsed_occurrence"
    if re.fullmatch(r"\s*1\s*[x×]\s*" + plain, value, re.I):
        return "exactly_one_explicit_elapsed_occurrence"
    return "not_a_single_explicit_elapsed_occurrence"


def build_conditioning_review(resolution_root, source_root):
    resolution_root, source_root = Path(resolution_root), Path(source_root)
    manifest = json.loads((resolution_root / "manifest.json").read_bytes())
    source_manifest = json.loads((source_root / "manifest.json").read_bytes())
    _require(manifest.get("accepted_cases") == 0 and manifest.get("final_planner_execution_authorized") is False,
             "The resolution source unexpectedly claims case acceptance.")
    for name, expected in manifest["files"].items():
        path = (resolution_root / name).resolve()
        _require(path.is_relative_to(resolution_root.resolve()) and _sha(path.read_bytes()) == expected,
                 "A resolution source changed: " + name)
    drill_file = source_root / "reference_snapshot/adopted_drills.json"
    _require(_sha(drill_file.read_bytes()) == source_manifest["files"]["reference_snapshot/adopted_drills.json"],
             "The approved catalogue snapshot changed.")
    drills = json.loads(drill_file.read_bytes())["records"]
    _require(len(drills) == 136 and len({d["catalog_candidate_id"] for d in drills}) == 136,
             "The approved activity population changed.")
    public_records = _lines(resolution_root / "proposed_public_profiles.jsonl")
    profiles = {r["profile_id"]: r for r in public_records}
    activities = json.loads((resolution_root / "activity_resolution_proposals.json").read_bytes())
    held = [r for r in activities["cases"] if r["status"].startswith("held_")]
    _require(len(profiles) == len(public_records) == 200 and len(held) == 11,
             "The reviewed conditioning population changed.")

    catalogue_review = []
    for index, drill in enumerate(drills):
        supporting_fields = [key for key in SOURCE_FIELDS if re.search(
            r"\b(?:conditioning|endurance|stamina|aerobic|cardiovascular|cardio|fitness)\b", str(drill.get(key, "")), re.I)]
        catalogue_review.append({"catalog_candidate_id": drill["catalog_candidate_id"], "drill_name": drill["drill_name"],
            "source_record_sha256": _sha(_packed(drill)),
            "source_path": "reference_snapshot/adopted_drills.json#/records/" + str(index),
            "source_goal": drill["primary_goal"], "source_prescription": drill["source_prescription"],
            "source_curriculum_level": drill.get("source_curriculum_level"),
            "single_elapsed_interpretation": _elapsed_kind(drill["source_prescription"]),
            "explicit_conditioning_support_fields": supporting_fields,
            "direct_conditioning_support_found": bool(supporting_fields),
            "qualification": "No direct wording support is not evidence that physical activity has no conditioning effect. This review does not relabel another skill base or add intensity/dose claims."})
    direct = [r for r in catalogue_review if r["direct_conditioning_support_found"]]
    timed_direct = [r for r in direct if r["single_elapsed_interpretation"] != "not_a_single_explicit_elapsed_occurrence"]
    _require(len(direct) == 1 and direct[0]["catalog_candidate_id"] == "JR-REVIEW-0053" and not timed_direct,
             "The catalogue has new direct conditioning evidence; revisit the saved decision.")

    decisions = []
    alternatives = {}
    for row in held:
        pid = row["profile_id"]
        current = profiles[pid]
        before = current["input"]
        _require(before["goals"] == [OLD_GOAL] and row["proposed_public_record"] is None and row["private_witness"] is None,
                 "A held conditioning case was silently changed.")
        option = row["optional_material_goal_reauthoring"]
        _require(option["selected"] is False and option["requires_blueprint_and_family_review"] is True,
                 "The optional goal change is no longer an unselected authoring proposal.")
        proposed = option["proposed_public_record"]
        after = proposed["input"]
        rebuilt = deepcopy(current)
        paths = []
        for patch in option["patches"]:
            _require(patch["op"] == "replace" and patch["applied_to_source"] is False
                     and patch["path"] in {"/input/goals", "/input/athlete_request", "/input/space"},
                     "The material goal alternative contains an unrelated patch.")
            key = patch["path"].rsplit("/", 1)[1]
            _require(key not in paths and rebuilt["input"][key] == patch["old"], "An alternative patch is stale or duplicated.")
            rebuilt["input"][key] = deepcopy(patch["new"])
            paths.append(key)
        _require(rebuilt == proposed and set(after) == set(before) and set(proposed) == set(current),
                 "The alternate public record has unrecorded changes.")
        _require(after["goals"] == [NEW_GOAL] and after["athlete_request"] == before["athlete_request"].replace(OLD_GOAL, NEW_GOAL),
                 "The alternate request changed beyond its explicit goal replacement.")
        for key in set(before) - {"goals", "athlete_request", "space"}:
            _require(before[key] == after[key], "An alternative changed a protected case fact: " + key)
        _require(after["participants_available"] >= 1 and sum(e["quantity"] for e in after["equipment"]
            if e["name"].casefold() == "basketball") >= 1, "The individual base lacks a stated participant or ball.")
        _require(after["space"]["court_access"] in {"half_court", "full_court"}, "The source court-space fact remains absent.")
        witness = option["private_witness"]
        source = witness["source_evidence"]
        for key, fact in source.items():
            match = re.fullmatch(r"reference_snapshot/adopted_drills.json#/records/(\d+)/(.+)", fact["path"])
            _require(match is not None and match[2] == key and drills[int(match[1])].get(key) == fact["value"],
                     "The alternative source evidence changed.")
        _require(source["catalog_candidate_id"]["value"] == "JR-REVIEW-0051"
            and source["source_prescription"]["value"] == "3 minutes"
            and source["source_curriculum_level"]["value"] == "MVP", "The alternate activity source changed.")
        _require(witness["elapsed_interpretation"]["seconds"] == 180
            and witness["source_weekly_frequency_claimed"] is False
            and witness["complete_source_base_preserved"] is True, "The alternate source dose or base changed.")
        requested = int(re.search(r"\b([12])\s+(?:additional|extra)\s+practice\s+blocks?\b", after["athlete_request"], re.I)[1])
        slots = witness["witness_slots"]
        _require(len(slots) == requested <= after["time_limits"]["max_additional_sessions_per_week"], "The alternate requested block count is not preserved.")
        for slot in slots:
            start, end = _minutes(slot["start_time"]), _minutes(slot["end_time"])
            _require(end - start == slot["duration_minutes"] == 3 <= after["time_limits"]["max_session_minutes"], "The alternate elapsed dose does not fit its session cap.")
            window = after["availability"][int(slot["availability_ref"].rsplit("/", 1)[1])]
            _require(slot["date"] == window["date"] and _minutes(window["start_time"]) <= start < end <= _minutes(window["end_time"]),
                     "The alternate witness leaves the unchanged availability.")
            for event in after["existing_commitments"]:
                _require(event["date"] != slot["date"] or max(start, _minutes(event["start_time"])) >= min(end, _minutes(event["end_time"])),
                         "The alternate witness overlaps an existing event.")
        _require(sum(s["duration_minutes"] for s in slots) <= after["time_limits"]["max_additional_minutes_per_week"], "The alternate exceeds the unchanged weekly cap.")
        for drill in drills:
            _require(drill["catalog_candidate_id"] not in after["athlete_request"] and drill["drill_name"] not in after["athlete_request"],
                     "A private witness identity entered the alternate public request.")
        alternatives[pid] = proposed
        decisions.append({"profile_id": pid, "current_record_sha256": _sha(_packed(current)),
            "optional_record_sha256": _sha(_packed(proposed)), "age": before["age"],
            "reported_experience": before["basketball_background"]["experience_level"],
            "source_curriculum_level": source["source_curriculum_level"]["value"],
            "source_label_is_not_an_invented_minimum_experience_gate": True,
            "original_goal": OLD_GOAL, "optional_goal": NEW_GOAL,
            "suggested_choice": "select_material_goal_reauthoring_only_if_catalog_skill_scope_is_explicitly_adopted",
            "conditioning_goal_fulfilled_by_alternative": False,
            "optional_patch_fields": paths,
            "space_before": before["space"], "space_optional": after["space"],
            "verified_food_question_preserved": before.get("food_question") == after.get("food_question"),
            "case_category_age_events_availability_limits_coverage_preserved": True,
            "source_dose_and_temporal_alternative_validated": True,
            "remaining_specific_review": ["Accept the deliberate goal and any venue change as new fictional authoring facts.",
                "Review goal relevance and the source's skill prerequisites for the stated experience; the source label alone is not clearance or a hard exclusion.",
                "Accept the full private witness and complete case/rule evidence; source-dose consistency alone is not an accepted feasible-case result.",
                "Rebind all case/private-record hashes and recheck population relationships after any selected change."],
            "team_choice": None, "selected": False, "case_approved": False})
    goal_counts = Counter(r["input"]["goals"][0] for r in public_records if r["profile_id"] in {a["profile_id"] for a in activities["cases"]})
    optional_counts = goal_counts.copy()
    optional_counts[OLD_GOAL] -= len(held)
    optional_counts[NEW_GOAL] += len(held)
    optional_counts = Counter({key: value for key, value in optional_counts.items() if value})
    return {"schema_version": "conditioning-case-authoring-review-1",
        "source_resolution_id": manifest["resolution_id"],
        "source_resolution_manifest_sha256": _sha((resolution_root / "manifest.json").read_bytes()),
        "source_catalogue_sha256": source_manifest["files"]["reference_snapshot/adopted_drills.json"],
        "summary": {"approved_catalogue_records_examined": len(drills), "direct_conditioning_records": len(direct),
            "direct_conditioning_records_with_single_elapsed_dose": len(timed_direct), "held_original_cases": len(held),
            "validated_optional_material_goal_alternatives": len(decisions),
            "optional_space_amendments": sum("space" in d["optional_patch_fields"] for d in decisions),
            "reported_experience_counts": dict(Counter(d["reported_experience"] for d in decisions)),
            "held_case_age_counts": dict(sorted(Counter(d["age"] for d in decisions).items())),
            "food_questions_in_held_cases_preserved": sum(bool(profiles[d["profile_id"]]["input"].get("food_question")) for d in decisions),
            "planning_goal_kinds_before": len(goal_counts), "planning_goal_kinds_if_alternatives_selected": len(optional_counts),
            "material_alternatives_selected": 0, "cases_approved": 0, "new_model_calls": 0},
        "recommendation": {
            "recommended_smallest_scope_decision": "For an approved-catalogue basketball-skill benchmark, explicitly adopt the11 material goal reauthorings before freezing, update goal-composition metadata and disclose that conditioning is not evaluated. Do not describe this as fixing the original conditioning requests.",
            "this_is_a_proposal_not_an_adopted_scope_change": True,
            "alternative_if_conditioning_is_required": "Retain the11originalconditioningrequests and expand/review the conditioning resource evidence. The current approved catalogue does not provide the required singleelapsed-dose witness. Do not fabricate line-to-minute conversion or an intensity target.",
            "not_recommended": "Silently remove11cases, silently changegoals, relabel a transition/skill game as conditioning, invent a duration for five lines, or count unselected alternatives as accepted cases.",
            "preserved_if_optional_changes_are_selected": ["All200caseidentities", "150planning/20missing/15conflict/15scope provisional categories", "age allocation", "existing commitments and available windows", "time limits and schedule coverage", "all20verifiedfoodexpectations"],
            "required_followup_if_selected": ["Record explicit materialcase-authoring/scope choice.", "Export newly versioned public records and matching private evidence hashes.", "Recheck source prerequisites, full witnesses and case-level rule evidence.", "Rescreen revised candidate relationships, retaining618historicalflags and unresolved legacy evidence.", "Obtain the required actual team preparation/distinctreviewer decisions and freeze the final protocol before execution."],
            "scope_limit": "The skillbenchmark result would not establish conditioning planning, exercise effectiveness, medical suitability, or operational readiness."},
        "planning_goal_counts_before": dict(sorted(goal_counts.items())),
        "planning_goal_counts_if_all_optional_changes_selected": dict(sorted(optional_counts.items())),
        "catalogue_screen": catalogue_review, "case_decision_proposals": decisions,
        "direct_conditioning_source_evidence": [{"source_path": r["source_path"],
            "record": drills[int(r["source_path"].rsplit("/", 1)[1])]} for r in direct],
        "private_review_only": True, "source_inputs_changed": False, "final_planner_execution_authorized": False}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("resolution_root")
    parser.add_argument("source_root")
    parser.add_argument("output")
    args = parser.parse_args()
    result = build_conditioning_review(args.resolution_root, args.source_root)
    Path(args.output).write_bytes(_packed(result))
    print(json.dumps(result["summary"], indent=2))
