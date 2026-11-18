"""Prepare private activity witnesses and explicit fictional resource amendments for team review.

Inputs remain immutable. The public proposal contains resource facts only; source
names, activity IDs, source doses and witness schedules stay in the private review.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from itertools import combinations
import hashlib
import importlib.util
import json
from pathlib import Path
import re


# These generic action relations are editorial choices, not effectiveness claims.
ACTION_CHOICES = {
    "Build a repeatable set-shot action": ("JR-NEW-0049", "shooting"),
    "Improve accuracy from fixed shooting spots": ("JR-NEW-0049", "shooting"),
    "Coordinate foot placement before a layup": ("JR-ADITI-0006", "layup"),
    "Improve controlled footwork near the basket": ("JR-ADITI-0006", "layup"),
    "Improve controlled defensive direction changes": ("JR-NEW-0009", "lateral"),
    "Stay balanced while moving laterally on defense": ("JR-NEW-0009", "lateral"),
    "Change direction with more consistent foot placement": ("JR-REVIEW-0054", "stopping"),
    "Improve agility during short basketball movements": ("JR-REVIEW-0054", "stopping"),
    "Control my dribble while changing pace": ("JR-REVIEW-0051", "rhythm"),
    "Manage my pace during short basketball practice blocks": ("JR-REVIEW-0051", "rhythm"),
    "Keep possession through controlled turns": ("JR-NEW-0057", "turns"),
    "Improve the timing of receiving and returning a pass": ("JR-REVIEW-0024", "catch_return"),
    "Send controlled passes to a marked target": ("JR-NEW-0017", "passing_positions"),
}
HELD_GOAL = "Develop more consistent basketball conditioning"
EVIDENCE_FIELDS = ("catalog_candidate_id", "drill_name", "primary_goal", "instructions", "participants", "minimum_participants", "equipment", "space", "source_prescription", "use_conditions", "approved_variant", "source_curriculum_level", "source_evidence_id", "source_url", "source_section_sha256")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_helper(path):
    spec = importlib.util.spec_from_file_location("step33_activity_screen", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def single_elapsed(text, original_parser):
    """Accept bare elapsed doses and exactly one explicitly timed occurrence only."""
    original = original_parser(text)
    if original.get("kind") == "single_explicit_elapsed_dose":
        return dict(original, interpretation="original_bare_single_elapsed_parser")
    if not isinstance(text, str):
        return original
    match = re.fullmatch(r"\s*1\s*[x×]\s*(\d+(?:\.\d+)?)(?:\s*[–-]\s*(\d+(?:\.\d+)?))?\s+(minutes?|seconds?)\s*", text, re.I)
    if not match:
        return original
    body = match[1] + (("–" + match[2]) if match[2] else "") + " " + match[3]
    parsed = original_parser(body)
    require(parsed["kind"] == "single_explicit_elapsed_dose", "Invalid single-occurrence interpretation.")
    return dict(parsed, source_text=text, interpretation="exactly_one_explicit_elapsed_occurrence", multiplier=1,
                source_prescription_changed=False, rest_invented=False)


def patch_public(public, kind):
    proposed, changes, origins = deepcopy(public), [], []
    needed_people = {"shooting": 2, "layup": 2, "lateral": 2, "stopping": 2,
                     "rhythm": 1, "turns": 2, "catch_return": 2, "passing_positions": 3}[kind]
    if proposed["participants_available"] < needed_people:
        old = proposed["participants_available"]
        proposed["participants_available"] = needed_people
        origins.append({"fact": "available headcount", "origin": "new_fictional_authoring_proposal",
                        "reason": "Add the missing peer or coach explicitly; no person is inferred from the old case.",
                        "additional_people": needed_people - old})
    if kind == "stopping":
        proposed["athlete_request"] += " One other person included in this headcount is an adult basketball coach available throughout all listed windows to give movement cues."
        origins.append({"fact": "cue-giving coach", "origin": "new_fictional_authoring_proposal",
                        "reason": "A headcount does not establish the source's coach role."})
    if kind == "catch_return":
        ball = next(item for item in proposed["equipment"] if item["name"].casefold() == "basketball")
        if ball["quantity"] < 2:
            ball["quantity"] = 2
            origins.append({"fact": "second basketball", "origin": "new_fictional_authoring_proposal",
                            "reason": "The complete paired source base requires two balls, including simultaneous dribbling."})
    marked_court = kind in {"layup", "stopping", "rhythm", "turns", "catch_return", "passing_positions"}
    space = proposed["space"]
    if marked_court and space["court_access"] not in {"half_court", "full_court"}:
        original_court = space["court_access"]
        space["court_access"] = "half_court"
        space["usable_area_description"] = ("A marked basketball half-court floor with baseline, sidelines, key, wing positions and three-point line is available throughout all listed windows. There is a separate waiting area. "
                                             + ("The listed hoop is available." if space["hoop_access"] else "No hoop access is provided."))
        if kind == "rhythm":
            # This individual action can retain the existing one-mover/waiting limits.
            if original_court == "none":
                space["usable_area_description"] += " The original 7 m by 5 m marked practice zone is retained within this floor area."
        elif kind == "stopping":
            space["restrictions"] = ["Only one athlete moves at a time; the coach may give cues from a stationary support position outside the movement path. Other people wait outside the active area."]
        else:
            space["restrictions"] = ["The active court area is available for the listed peer group to move together; other people wait outside the active area."]
        origins.append({"fact": "marked court floor and permitted active layout", "origin": "new_fictional_authoring_proposal",
                        "reason": "Replace the former non-court or single-hoop-only fact explicitly. This is a material venue amendment, not confirmation that the original space was sufficient."})
    if kind == "lateral" and space["court_access"] == "none":
        # Preserve the original one-moving-participant limit. The old waiting-only
        # restriction cannot silently become permission for an active support role.
        space["restrictions"] = ["Use the marked practice zone with one moving participant at a time.",
                                 "One stationary peer support person may stand outside the movement zone to send and receive a ball. Other people remain in the separate waiting area."]
        space["usable_area_description"] += " A stationary support position outside the movement zone has a clear ball path to the zone."
        origins.append({"fact": "stationary peer support position", "origin": "new_fictional_authoring_proposal",
                        "reason": "The source needs a partner; retain one moving person and make permission for a stationary partner explicit instead of silently altering the waiting rule."})
    for key in public:
        if public[key] != proposed[key]:
            changes.append({"op": "replace", "path": "/input/" + key, "old": deepcopy(public[key]), "new": deepcopy(proposed[key]),
                            "origin": "new_fictional_authoring_proposal", "applied_to_source": False})
    return proposed, changes, origins


def goal_relation(kind):
    return {
        "shooting": "The complete base includes shooting from varied positions and stances; it is an action-relevant shooting example, not evidence of improved accuracy or form.",
        "layup": "The complete base includes drives and a teammate's lay-up cut. This is an action-relevant near-basket/lay-up example, not a replacement standalone footwork drill or an effectiveness guarantee.",
        "lateral": "The complete base explicitly uses lateral defensive slides in response to a partner's rolled ball.",
        "stopping": "The complete base combines running on a cue with controlled stopping/balance on the called foot or feet. This is an editorial relation to controlled foot placement/agility, not source evidence of training effectiveness.",
        "rhythm": "The complete individual base explicitly changes body height, pace and movement rhythm while controlling the ball. No conditioning or intensity target is added.",
        "turns": "The complete partnered base changes hands before a jab in the opposite direction and exchanges roles. Its connection to controlled turns is editorial; no extra pivot progression is added.",
        "catch_return": "The complete paired base catches and returns a tossed second ball while keeping a dribble. This is receiving/return timing and coordination, not a claim that every conventional pass technique is trained.",
        "passing_positions": "The complete source sequence delivers passes to top/wing receiving positions. Existing cones may mark those positions as an editorial setup choice; the source does not prescribe a target-accuracy test. Keep this goal relation explicitly pending team review.",
    }[kind]


def actors(kind, before_count):
    role_sets = {
        "shooting": [("athlete", "shooting/passing partner"), ("peer_1", "shooting/passing partner")],
        "layup": [("athlete", "ball-handler in one active line"), ("peer_1", "reacting teammate in the other active line; swap lines")],
        "lateral": [("athlete", "laterally moving defender"), ("peer_1", "stationary ball-rolling partner outside the movement path")],
        "stopping": [("athlete", "runner responding to foot/balance cues"), ("coach_1", "cue-giving adult coach in stationary support position")],
        "rhythm": [("athlete", "individual ball-handler with one ball")],
        "turns": [("athlete", "ball-handler"), ("peer_1", "partner/defender; exchange roles and work both hands")],
        "catch_return": [("athlete", "dribbler and catcher/returner of second ball"), ("peer_1", "second-ball tossing partner; exchange roles")],
        "passing_positions": [("athlete", "top passer/rotating cutter"), ("peer_1", "one wing receiver/queue"), ("peer_2", "opposite-wing replacer/queue")],
    }
    result = []
    for index, (actor, role) in enumerate(role_sets[kind]):
        origin = "existing_athlete_fact" if index == 0 else "new_fictional_coach_role_fact" if kind == "stopping" else "allocation_from_existing_headcount" if index < before_count else "new_fictional_peer_headcount_fact"
        result.append({"actor": actor, "role": role, "origin": origin, "real_identity_inferred": False})
    return result


def make_witness(public, drill, source_index, kind, helper):
    elapsed = single_elapsed(drill["source_prescription"], helper.parse_elapsed_prescription)
    duration = elapsed.get("calendar_minutes")
    require(type(duration) is int and duration > 0, "Selected source dose is not an exact positive integer-minute occurrence.")
    temporal = helper.time_witness(public)
    slots = []
    for slot in temporal["temporal_feasibility"]["witness"]:
        require(duration <= slot["duration_minutes"], "Source dose does not fit an original free block.")
        new = dict(slot, end_time=helper.clock(helper.minute(slot["start_time"]) + duration), duration_minutes=duration,
                   catalog_candidate_id=drill["catalog_candidate_id"], source_prescription=drill["source_prescription"], relationship="separate_session",
                   source_prescription_modified=False, prescribed_sets_repeated=False, rest_added=False)
        slots.append(new)
    require(len(slots) == temporal["requested_additional_blocks"], "Wrong requested block count.")
    require(sum(s["duration_minutes"] for s in slots) <= public["time_limits"]["max_additional_minutes_per_week"], "Weekly cap exceeded.")
    source = {field: {"path": f"reference_snapshot/adopted_drills.json#/records/{source_index}/{field}", "value": deepcopy(drill.get(field))} for field in EVIDENCE_FIELDS}
    return {"privacy": "private_team_review_only_do_not_add_to_public_request", "source_evidence": source,
            "source_record_sha256": digest(encode(drill)), "elapsed_interpretation": elapsed,
            "witness_slots": slots, "source_weekly_frequency_claimed": False,
            "weekly_frequency_origin": "fictional case-authoring choice from original requested block count",
            "complete_source_base_preserved": True, "goal_relation": goal_relation(kind),
            "layout_allocation": ({"marker_gap_feet": 6, "gap_is_within_published_6_to_8_feet": True,
                                  "one_locomoting_person": True, "stationary_support_person": True,
                                  "clearance_is_case_authoring_fact_not_medical_certification": True} if kind == "lateral" else
                                 {"receiving_positions_may_be_marked_with_existing_cones": True, "target_accuracy_test_invented": False,
                                  "three_position_role_allocation_is_editorial_not_published_numeric_minimum": True} if kind == "passing_positions" else None),
            "remaining_scope": "Source-compatible action/resource witness only. Source use conditions, actual skill prerequisites, case-level adopted rules and final team case acceptance remain pending; medical/age eligibility is not inferred."}


def build_activity_resolutions(corrections_root, source_root, helper_path):
    corrections_root, source_root = Path(corrections_root), Path(source_root)
    helper = load_helper(helper_path)
    cm = json.loads((corrections_root / "manifest.json").read_bytes())
    require(cm["accepted_cases"] == 0 and cm["final_planner_execution_authorized"] is False, "Unexpected source acceptance state.")
    # A bound native correction package is required; no fallback candidate data.
    bound = {str(corrections_root / name): sha for name, sha in cm["files"].items()}
    source_bound = {}
    for name, sha in cm["source_file_sha256"].items():
        marker = source_root.name + "/"
        relative = name.split(marker, 1)[1] if marker in name else name
        source_bound[str(source_root / relative)] = sha
    bound.update(source_bound)
    for name, sha in bound.items():
        require(digest(Path(name).read_bytes()) == sha, "Bound input differs: " + name)
    options = json.loads((corrections_root / "activity_options.json").read_bytes())
    profiles = {row["profile_id"]: row for line in (corrections_root / "proposed_public_profiles.jsonl").read_bytes().splitlines() if (row := json.loads(line))}
    source_profiles = {row["profile_id"]: row for line in (source_root / "source_public_profiles.jsonl").read_bytes().splitlines() if (row := json.loads(line))}
    drills = json.loads((source_root / "reference_snapshot/adopted_drills.json").read_bytes())["records"]
    by_id = {d["catalog_candidate_id"]: (i, d) for i, d in enumerate(drills)}
    require(len(profiles) == 200 and len(drills) == len(by_id) == 136, "Unexpected native case/catalogue counts.")
    held = [row for row in options["cases"] if row["selected_example"] is None]
    require(len(held) == 101, "Expected exactly the native 101 remaining activity cases.")
    rows = []
    for old in held:
        identifier = old["profile_id"]
        before_record = profiles[identifier]
        public = before_record["input"]
        goal = public["goals"][0]
        relevant = set(helper.GOAL_BASES[goal])
        screens = [helper.screen(public, drill, index, drill["catalog_candidate_id"] in relevant) for index, drill in enumerate(drills)]
        base = {"profile_id": identifier, "draft_category": "feasible", "category_changed": False,
                "original_source_record_sha256": old["source_record_sha256"], "native_proposed_record_sha256": digest(encode(before_record)),
                "catalog_records_examined": len(screens), "generic_screen_status_counts": dict(Counter(s["status"] for s in screens)),
                "original_shortlist_candidate_ids": [x["catalog_candidate_id"] for x in old["candidate_options"]],
                "approved": False, "team_review_status": "pending", "source_inputs_changed": False,
                "option_keep_original": {"patches": [], "status": "keep_original_and_hold", "team_decision_recorded": False},
                "activity_witness_is_private": True, "full_case_feasibility_proved": False}
        if goal == HELD_GOAL:
            # A separately labelled optional change demonstrates the scientific cost
            # of replacing this goal, without selecting or applying that change.
            alternative = deepcopy(public)
            alternative_goal = "Control my dribble while changing pace"
            alternative["goals"] = [alternative_goal]
            alternative["athlete_request"] = alternative["athlete_request"].replace(HELD_GOAL, alternative_goal)
            alternative, alt_changes, alt_origins = patch_public(alternative, "rhythm")
            # Recompute full old/new patches against the unchanged native proposal.
            all_changes = [{"op": "replace", "path": "/input/" + key, "old": deepcopy(public[key]), "new": deepcopy(alternative[key]),
                            "origin": "optional_material_case_reauthoring", "applied_to_source": False} for key in public if public[key] != alternative[key]]
            alt_index, alt_drill = by_id["JR-REVIEW-0051"]
            base.update(status="held_no_direct_conditioning_source_with_single_elapsed_dose",
                        held_reason="The source base explicitly labelled conditioning uses 1 x 5 lines; other direct choices use games or unspecified elapsed time. No rep/line/game count is converted to minutes. A transition basketball game is not silently relabelled as a source-prescribed conditioning block.",
                        proposed_public_record=None, patches=[], private_witness=None,
                        source_evidence=[{"path": f"reference_snapshot/adopted_drills.json#/records/{i}/{f}", "value": deepcopy(d.get(f))}
                                         for cid in helper.GOAL_BASES[goal] for i, d in [by_id[cid]] for f in ("catalog_candidate_id", "drill_name", "primary_goal", "source_prescription", "instructions")],
                        optional_material_goal_reauthoring={"selected": False, "requires_blueprint_and_family_review": True,
                            "changes_scenario_intent": True, "denominator_effect_not_authorized": True,
                            "reason": "This changes the research case from conditioning to pace-control ball handling. Keep the original goal and hold unless the team deliberately accepts and rechecks that material case-authoring change.",
                            "proposed_public_record": dict(deepcopy(before_record), input=alternative), "patches": all_changes,
                            "fact_origins": alt_origins, "private_witness": make_witness(alternative, alt_drill, alt_index, "rhythm", helper)})
        else:
            require(goal in ACTION_CHOICES, "Unreviewed goal: " + goal)
            selected, kind = ACTION_CHOICES[goal]
            index, drill = by_id[selected]
            proposed, changes, origins = patch_public(public, kind)
            witness = make_witness(proposed, drill, index, kind, helper)
            witness["actors"] = actors(kind, public["participants_available"])
            base.update(status="existing_facts_witness_proposed" if not changes else "explicit_fictional_resource_amendment_proposed",
                        proposed_public_record=dict(deepcopy(before_record), input=proposed), patches=changes,
                        fact_origins=origins, private_witness=witness,
                        selected_outside_original_shortlist=selected not in base["original_shortlist_candidate_ids"],
                        selected_outside_original_goal_mapping=selected not in relevant,
                        source_semantic_interpretation="Structured minimum/duration nulls do not erase explicit roles or dose text. Roles are allocated from the complete source text; no numeric source minimum or training outcome is invented.")
        rows.append(base)
    summary = {"native_remaining_cases": len(rows), "catalog_records_examined_per_case": len(drills), "case_catalogue_screens": len(rows) * len(drills),
               "concrete_activity_witness_proposals": sum(row["private_witness"] is not None for row in rows),
               "existing_facts_witness_proposals": sum(row["status"] == "existing_facts_witness_proposed" for row in rows),
               "explicit_fictional_resource_amendment_proposals": sum(row["status"] == "explicit_fictional_resource_amendment_proposed" for row in rows),
               "original_goal_cases_held": sum(row["private_witness"] is None for row in rows),
               "optional_material_goal_reauthorings_not_selected": sum("optional_material_goal_reauthoring" in row for row in rows),
               "public_field_patch_counts": dict(Counter(p["path"] for row in rows for p in row["patches"])),
               "earlier_49_activity_examples_unchanged": True, "verified_food_expectations_unchanged": True,
               "challenge_cases_changed": 0, "case_approvals_created": 0, "new_model_calls": 0, "new_reference_queries": 0,
               "category_counts_retained": {"feasible": 150, "missing_information": 20, "conflicting_constraints": 15, "outside_scope": 15}}
    require(summary["concrete_activity_witness_proposals"] == 90 and summary["original_goal_cases_held"] == 11, "Unexpected proposal counts.")
    result = {"schema_version": "step33-activity-resource-resolution-proposals-1", "source_correction_id": cm["correction_id"],
              "source_package_id": cm["source_package_id"], "input_sha256": {("corrections/" + Path(p).relative_to(corrections_root).as_posix()) if Path(p).is_relative_to(corrections_root) else ("source/" + Path(p).relative_to(source_root).as_posix()): sha for p, sha in bound.items()},
              "summary": summary, "case_status": "proposals_pending_team_review_not_case_acceptance",
              "privacy": "This whole file is a private team-review artifact. Export only a selected reviewed proposed_public_record to future planner input; never attach its source choices, witness/gold, or private evidence.",
              "dose_interpretation_correction": {"proposal": "Accept an exactly-one multiplier before one explicit elapsed dose.",
                  "accepted_examples": ["1 × 3 minutes", "1 x 2 minutes"],
                  "still_not_accepted_as_single_elapsed": ["2 x 1 minute", "3 minutes each side", "1 x 3 minutes with variations", "1 x 5 lines", "2 games"],
                  "original_source_text_retained": True, "multi_set_totals_or_rests_invented": False},
              "cases": rows}
    validate_activity_resolutions(result, profiles, source_profiles, drills, helper)
    for name, sha in bound.items():
        require(digest(Path(name).read_bytes()) == sha, "A bound input changed during preparation: " + name)
    return result


def validate_activity_resolutions(result, profiles, source_profiles, drills, helper):
    """Independent structural, source, timing and public/private boundary checks."""
    count = 0
    for row in result["cases"]:
        identifier = row["profile_id"]
        before = profiles[identifier]
        alternatives = [(row.get("proposed_public_record"), row.get("private_witness"), row.get("patches", []))]
        if "optional_material_goal_reauthoring" in row:
            alt = row["optional_material_goal_reauthoring"]
            alternatives.append((alt["proposed_public_record"], alt["private_witness"], alt["patches"]))
        for proposal, witness, patches in alternatives:
            if proposal is None:
                require(witness is None and patches == [], "Held case gained a hidden witness or patch.")
                continue
            p = proposal["input"]
            q = before["input"]
            require(set(proposal) == set(before) and proposal["schema_version"] == before["schema_version"], "Unreviewed public schema change.")
            require(set(p) == set(q), "Private/helper fields leaked into the public input.")
            rebuilt = deepcopy(before)
            for patch in patches:
                key = patch["path"].removeprefix("/input/")
                require(rebuilt["input"][key] == patch["old"], "Patch old value differs.")
                rebuilt["input"][key] = deepcopy(patch["new"])
            require(rebuilt == proposal, "Public proposal has changes absent from the patch register.")
            for key in ("age", "school_grade", "planning_window", "availability", "existing_commitments", "time_limits", "reported_limitations", "schedule_coverage", "food_question", "basketball_background"):
                require(p.get(key) == q.get(key), "An unrelated or verified public fact changed: " + key)
            for d in drills:
                require(d["catalog_candidate_id"] not in p["athlete_request"] and d["drill_name"] not in p["athlete_request"], "Private source witness leaked to the public request.")
            kind = next((kind for cid, kind in ACTION_CHOICES.values() if cid == witness["source_evidence"]["catalog_candidate_id"]["value"]), None)
            require(kind is not None, "Witness activity has no reviewed action relation.")
            minimum_people = {"shooting": 2, "layup": 2, "lateral": 2, "stopping": 2, "rhythm": 1, "turns": 2, "catch_return": 2, "passing_positions": 3}[kind]
            require(p["participants_available"] >= minimum_people, "The full source-role allocation lacks people.")
            equipment = {item["name"].casefold(): item["quantity"] for item in p["equipment"]}
            require(equipment.get("basketball", 0) >= (0 if kind == "stopping" else 2 if kind == "catch_return" else 1), "The full source base lacks basketballs.")
            if kind in {"shooting", "layup"}:
                require(p["space"]["hoop_access"] is True and equipment.get("hoop", 0) >= 1, "The source basket requirement is missing.")
            if kind in {"layup", "lateral"}:
                require(equipment.get("cones", 0) >= (3 if kind == "layup" else 2), "Source marker count is unavailable.")
            if kind in {"layup", "stopping", "rhythm", "turns", "catch_return", "passing_positions"}:
                require(p["space"]["court_access"] in {"half_court", "full_court"}, "Source court layout has been replaced by an unsupported non-court adaptation.")
            if kind == "stopping":
                require("adult basketball coach available throughout all listed windows" in p["athlete_request"], "The required coach is not an explicit public resource fact.")
            restrictions = " ".join(p["space"].get("restrictions", [])).casefold()
            if kind in {"layup", "turns", "catch_return", "passing_positions"}:
                require("one moving participant at a time" not in restrictions, "Simultaneous source roles conflict with the retained movement restriction.")
            if kind == "lateral" and p["space"]["court_access"] == "none":
                require("one moving participant at a time" in restrictions and "stationary peer support person" in restrictions,
                        "A stationary support permission or the original one-mover bound is missing.")
            source = witness["source_evidence"]
            for field, evidence in source.items():
                match = re.fullmatch(r"reference_snapshot/adopted_drills.json#/records/(\d+)/(.+)", evidence["path"])
                require(match is not None and field == match[2] and drills[int(match[1])].get(field) == evidence["value"], "Source evidence mismatch.")
            dose = witness["elapsed_interpretation"]
            require(dose["source_text"] == source["source_prescription"]["value"], "Source prescription changed.")
            interpreted = single_elapsed(dose["source_text"], helper.parse_elapsed_prescription)
            require(interpreted == dose, "Dose interpretation differs.")
            requested = int(re.search(r"\b([12])\s+(?:additional|extra)\s+practice\s+blocks?\b", p["athlete_request"], re.I)[1])
            slots = witness["witness_slots"]
            require(len(slots) == requested <= p["time_limits"]["max_additional_sessions_per_week"], "Wrong witness block count/cap.")
            for slot in slots:
                start, end = helper.minute(slot["start_time"]), helper.minute(slot["end_time"])
                require((end - start) * 60 == dose["seconds"] and slot["duration_minutes"] == end - start <= p["time_limits"]["max_session_minutes"], "Dose/timing/cap mismatch.")
                window = p["availability"][int(slot["availability_ref"].rsplit("/", 1)[1])]
                require(slot["date"] == window["date"] and helper.minute(window["start_time"]) <= start < end <= helper.minute(window["end_time"]), "Witness is outside original availability.")
                for event in p["existing_commitments"]:
                    require(event["date"] != slot["date"] or max(start, helper.minute(event["start_time"])) >= min(end, helper.minute(event["end_time"])), "Witness overlaps a preserved event.")
            for left, right in combinations(slots, 2):
                require(left["date"] != right["date"] or max(helper.minute(left["start_time"]), helper.minute(right["start_time"])) >= min(helper.minute(left["end_time"]), helper.minute(right["end_time"])), "Witness slots overlap.")
            require(sum(s["duration_minutes"] for s in slots) <= p["time_limits"]["max_additional_minutes_per_week"], "Weekly cap exceeded.")
            count += 1
    require(count == 101, "Missing primary or explicitly optional witness.")
    for bad in ["2 x 1 minute", "3 minutes each side", "1 x 5 lines", "1 x 3 minutes with variations", "1 × 90 seconds each line", "3 × 1 minute each", "20 makes"]:
        require(single_elapsed(bad, helper.parse_elapsed_prescription)["kind"] != "single_explicit_elapsed_dose", "Repeated/qualified dose was flattened.")
    require(single_elapsed("1 × 3 minutes", helper.parse_elapsed_prescription)["calendar_minutes"] == 3, "Exact one-occurrence dose was lost.")
    return {"witness_proposals_checked": count, "source_and_public_boundaries_checked": True}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("corrections_root")
    parser.add_argument("source_root")
    parser.add_argument("helper_path")
    parser.add_argument("output")
    args = parser.parse_args()
    result = build_activity_resolutions(args.corrections_root, args.source_root, args.helper_path)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], sort_keys=True))
