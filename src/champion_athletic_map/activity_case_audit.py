"""Audit the actual source-linked witness proposals without approving cases.

This helper treats curriculum labels as source context, not an invented athlete
eligibility scale. It identifies unsupported resource assertions separately from
proven conflicts and prepares explicit fictional fact proposals for review.
"""

from collections import Counter
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def records(path):
    return [json.loads(line) for line in Path(path).read_bytes().splitlines() if line.strip()]


def minute(value):
    hour, mins = map(int, value.split(":"))
    require(0 <= hour <= 23 and 0 <= mins <= 59, "Invalid local witness clock.")
    return hour * 60 + mins


def elapsed_bounds(text):
    # A single occurrence may carry its exact elapsed dose. Repetitions, games,
    # per-side prescriptions and qualified repeated doses are not flattened.
    match = re.fullmatch(r"\s*(?:1\s*[x×]\s*)?(\d+(?:\.\d+)?)\s*(?:[–-]\s*(\d+(?:\.\d+)?))?\s+(minutes?|seconds?)\s*", text, re.I)
    require(match is not None, "The selected complete source dose has no single elapsed interpretation.")
    lower = Decimal(match[1])
    upper = Decimal(match[2]) if match[2] else lower
    multiplier = 60 if match[3].lower().startswith("minute") else 1
    require(0 < lower <= upper, "Invalid source elapsed range.")
    return lower * multiplier, upper * multiplier


def source_fact(index, drill, field):
    return {"path": f"reference_snapshot/adopted_drills.json#/records/{index}/{field}",
            "value": deepcopy(drill.get(field))}


def selected(row):
    witness = row.get("private_witness")
    if not witness:
        return None, None
    if row["status"] == "earlier_source_linked_example_retained":
        earlier = witness["earlier_selected_example"]
        return earlier["source_activity"], earlier["witness_slots"]
    return witness["source_evidence"]["catalog_candidate_id"]["value"], witness["witness_slots"]


def court_amendment(public):
    proposed = deepcopy(public["space"])
    proposed["court_access"] = "half_court"
    proposed["usable_area_description"] = (
        "A marked basketball half-court floor with baseline, sidelines, key, wing positions and three-point line is available throughout all listed windows. There is a separate waiting area. "
        + ("The listed hoop is available." if proposed["hoop_access"] else "No hoop access is provided."))
    return {"op": "replace", "path": "/input/space", "old": deepcopy(public["space"]),
            "new": proposed, "origin": "new_explicit_fictional_resource_authoring_proposal",
            "applied_to_source": False, "selected": False,
            "rationale": "Apply the same court-space interpretation to retained and newly prepared witnesses for the same source base; the former single-hoop area was not an explicit court fact."}


def audit_activity_proposals(resolution_root, source_root):
    resolution_root, source_root = Path(resolution_root).resolve(), Path(source_root).resolve()
    bound = {}
    for label, folder in (("resolutions", resolution_root), ("original", source_root)):
        manifest = json.loads((folder / "manifest.json").read_bytes())
        for relative, expected in manifest["files"].items():
            path = (folder / relative).resolve()
            require(path.is_relative_to(folder), "An audit source path leaves its folder.")
            require(digest(path.read_bytes()) == expected, "A bound audit source changed: " + relative)
            bound[label + "/" + relative] = expected
    activities = json.loads((resolution_root / "activity_resolution_proposals.json").read_bytes())
    profiles = {r["profile_id"]: r for r in records(resolution_root / "proposed_public_profiles.jsonl")}
    drills = json.loads((source_root / "reference_snapshot/adopted_drills.json").read_bytes())["records"]
    by_id = {d["catalog_candidate_id"]: (i, d) for i, d in enumerate(drills)}
    require(len(profiles) == 200 and len(drills) == 136 and len(activities["cases"]) == 150,
            "The audit population is incomplete.")
    # These are documented actor allocations for the ten selected complete
    # source bases; they are not newly asserted published numeric minima.
    actors = {"JR-NEW-0009": 2, "JR-ADITI-0006": 2, "JR-NEW-0057": 2,
              "JR-NEW-0049": 2, "JR-REVIEW-0051": 1, "JR-NEW-0017": 3,
              "JR-REVIEW-0024": 2, "JR-NEW-0058": 1, "JR-REVIEW-0054": 2,
              "JR-REVIEW-0042": 2}
    court_sources = {"JR-ADITI-0006", "JR-NEW-0057", "JR-REVIEW-0051", "JR-NEW-0017",
                     "JR-REVIEW-0024", "JR-NEW-0058", "JR-REVIEW-0054", "JR-REVIEW-0042"}
    hoop_sources = {"JR-ADITI-0006", "JR-NEW-0049", "JR-REVIEW-0042"}
    rows = []
    for row in activities["cases"]:
        pid = row["profile_id"]
        record, public = profiles[pid], profiles[pid]["input"]
        cid, slots = selected(row)
        result = {"profile_id": pid, "current_public_record_sha256": digest(packed(record)),
                  "activity_proposal_status": row["status"], "source_activity": cid,
                  "case_approved": False, "team_decision": None,
                  "hard_conflicts": [], "resource_evidence_questions": [], "goal_review_notes": [],
                  "reported_experience": public["basketball_background"]["experience_level"],
                  "recommended_public_patches": []}
        if cid is None:
            result.update(disposition="retain_existing_conditioning_hold",
                          rationale="The original conditioning goal is preserved while its separate material goal alternative remains unselected.")
            rows.append(result)
            continue
        index, drill = by_id[cid]
        require(cid in actors, "A selected source base has not been independently interpreted.")
        result["source_evidence"] = {field: source_fact(index, drill, field) for field in
            ("catalog_candidate_id", "drill_name", "primary_goal", "participants", "minimum_participants",
             "equipment", "space", "instructions", "source_prescription", "source_curriculum_level", "use_conditions")}
        result["source_curriculum_level"] = drill.get("source_curriculum_level")
        lower, upper = elapsed_bounds(drill["source_prescription"])
        requested = re.search(r"\b([12])\s+(?:additional|extra)\s+practice\s+blocks?\b", public["athlete_request"], re.I)
        require(requested is not None and len(slots) == int(requested[1]), "The source witness changes the requested block count.")
        total = 0
        for slot in slots:
            require(slot["catalog_candidate_id"] == cid and slot["source_prescription"] == drill["source_prescription"],
                    "The witness changed its selected source or prescription.")
            start, end = minute(slot["start_time"]), minute(slot["end_time"])
            duration = end - start
            require(duration == slot["duration_minutes"] and lower <= Decimal(duration * 60) <= upper,
                    "A selected witness changes the complete source elapsed dose.")
            require(duration <= public["time_limits"]["max_session_minutes"], "A source witness exceeds a session limit.")
            availability = public["availability"][int(slot["availability_ref"].rsplit("/", 1)[1])]
            require(slot["date"] == availability["date"] and minute(availability["start_time"]) <= start < end <= minute(availability["end_time"]),
                    "A source witness is outside stated availability.")
            for event in public["existing_commitments"]:
                require(slot["date"] != event["date"] or max(start, minute(event["start_time"])) >= min(end, minute(event["end_time"])),
                        "A source witness overlaps a preserved existing event.")
            total += duration
        require(total <= public["time_limits"]["max_additional_minutes_per_week"] and len(slots) <= public["time_limits"]["max_additional_sessions_per_week"],
                "A source witness exceeds weekly limits.")
        result["complete_source_dose_and_schedule_checked"] = True
        result["actor_allocation"] = {"minimum_roles_for_this_proposed_complete_base": actors[cid],
                                     "published_numeric_minimum_claimed": False}
        if public["participants_available"] < actors[cid]:
            result["hard_conflicts"].append("The proposed complete base lacks its allocated actor roles.")
        equipment = {item["name"].casefold(): item["quantity"] for item in public["equipment"]}
        if equipment.get("basketball", 0) < (0 if cid == "JR-REVIEW-0054" else 2 if cid == "JR-REVIEW-0024" else 1):
            result["hard_conflicts"].append("The source base lacks its stated ball requirement.")
        if cid in hoop_sources and (public["space"]["hoop_access"] is not True or equipment.get("hoop", 0) < 1):
            result["hard_conflicts"].append("The selected complete base lacks basket access.")
        if cid in {"JR-NEW-0009", "JR-ADITI-0006"} and equipment.get("cones", 0) < (2 if cid == "JR-NEW-0009" else 3):
            result["hard_conflicts"].append("The complete source marker allocation is missing.")
        if cid in court_sources and public["space"]["court_access"] not in {"half_court", "full_court"}:
            result["resource_evidence_questions"].append({"kind": "court_fact_not_established_consistently",
                "source_space": drill["space"], "current_space": deepcopy(public["space"]),
                "qualification": "A single-hoop open area is not a proven physical conflict, but the new witness builder requires an explicit court for the same source. Apply one interpretation consistently."})
            result["recommended_public_patches"].append(court_amendment(public))
        if cid == "JR-REVIEW-0054" and "adult basketball coach available throughout all listed windows" not in public["athlete_request"]:
            result["hard_conflicts"].append("A cue-giving coach is not an explicit case resource.")
        restrictions = " ".join(public["space"].get("restrictions", [])).casefold()
        if cid in {"JR-ADITI-0006", "JR-NEW-0057", "JR-NEW-0017", "JR-REVIEW-0024", "JR-REVIEW-0042"} and "one moving participant at a time" in restrictions:
            result["hard_conflicts"].append("The retained one-mover restriction conflicts with the complete paired/group source roles.")
        if cid == "JR-NEW-0009" and public["space"]["court_access"] == "none" and "stationary peer support person" not in restrictions:
            result["resource_evidence_questions"].append({"kind": "stationary_support_permission_missing",
                "qualification": "The partner role cannot silently override an others-wait restriction."})
        goal = public["goals"][0]
        if cid in {"JR-NEW-0058", "JR-REVIEW-0054"} and goal == "Change direction with more consistent foot placement":
            result["goal_review_notes"].append("The complete base directly trains stopping/balance; it does not itself explicitly rehearse a change of direction. Treat it as a component-relevant proposal, or choose a directly matching complete base before claiming a full goal-specific witness.")
        if cid == "JR-NEW-0017":
            result["goal_review_notes"].append("Passing to top/wing receivers is explicit; cone-marked receiving positions are an editorial setup. Do not call it a published target-accuracy test.")
        if cid == "JR-ADITI-0006":
            result["goal_review_notes"].append("The source includes a reacting lay-up cut and decision-making. The complete base is action-relevant near the basket; no standalone foot-placement progression is published here.")
        if cid == "JR-NEW-0049":
            result["goal_review_notes"].append("The source deliberately varies location, stance and reads. It is shooting-relevant, but does not establish a single fixed-spot or repeatable set-shot technique prescription.")
        result["skill_review"] = {"curriculum_label_is_not_an_inferred_athlete_eligibility_rule": True,
            "label_only_automatic_rejection": False,
            "reported_beginner_with_mvp_or_allstar_source": result["reported_experience"] == "beginner" and drill.get("source_curriculum_level") in {"MVP", "All-Star"},
            "decision_needed": "Review the complete base's actual skills and role demands against the fictional case. Do not infer capacity or incapacity from curriculum and experience labels alone."}
        result["disposition"] = "hold_for_proven_resource_conflict" if result["hard_conflicts"] else "reconcile_explicit_court_fact_before_acceptance" if result["resource_evidence_questions"] else "retain_source_linked_proposal_for_case_review"
        result["rationale"] = "Exact complete source dose and schedule are supported. Goal fit, source prerequisites and case acceptance are separate decisions; this audit creates no acceptance."
        rows.append(result)
    selected_rows = [r for r in rows if r["source_activity"]]
    return {"schema_version": "step33-independent-activity-review-1", "source_bindings": bound,
        "cases": rows, "summary": {"planning_cases_reviewed": len(rows), "selected_source_witnesses_reviewed": len(selected_rows),
            "earlier_witnesses_reviewed": sum(r["activity_proposal_status"] == "earlier_source_linked_example_retained" for r in rows),
            "new_source_witnesses_reviewed": sum(r["source_activity"] is not None and r["activity_proposal_status"] != "earlier_source_linked_example_retained" for r in rows),
            "selected_complete_source_bases": len({r["source_activity"] for r in selected_rows}),
            "proven_resource_conflict_cases": sum(bool(r["hard_conflicts"]) for r in rows),
            "court_fact_consistency_corrections_proposed": sum(bool(r["recommended_public_patches"]) for r in rows),
            "source_relevant_stopping_component_goal_questions": sum(r["source_activity"] in {"JR-NEW-0058", "JR-REVIEW-0054"} and bool(r["goal_review_notes"]) for r in rows),
            "beginners_with_mvp_or_allstar_source_label_review_only": sum(r.get("skill_review", {}).get("reported_beginner_with_mvp_or_allstar_source", False) for r in rows),
            "original_conditioning_holds_retained": sum(r["source_activity"] is None for r in rows),
            "team_approvals_created": 0, "public_changes_applied": 0, "new_model_calls": 0},
        "recommendations": [
            "Apply one court-space interpretation to both retained49 and newly prepared90. Propose eight explicit fictional court facts rather than silently calling single-hoop areas half courts.",
            "Retain complete source procedures and exact elapsed prescriptions; do not repair rep/game prescriptions into minutes.",
            "Review the12 stopping-component proposals against their explicit change-of-direction goal before treating them as complete goal-specific existence witnesses.",
            "Curriculum labels are context, not a published age/experience eligibility map;18 beginner/MVP-or-All-Star pairings require skill review, not automatic rejection or clearance.",
            "No audit recommendation is case acceptance, family adoption or a generated-plan score. Preserve all50 challenge cases and20 verified food facts."],
        "final_planner_execution_authorized": False, "case_acceptance_created": False}


def propose_activity_corrections(resolution_root, source_root, helper_path):
    """Propose12 direct lateral-response witnesses and8 consistent court facts.

    The source-linked choices remain private. Only explicit resource fact
    amendments appear in the proposed public record; goals and requests stay
    byte-for-byte equivalent to the previously proposed public case.
    """
    resolution_root, source_root, helper_path = map(Path, (resolution_root, source_root, helper_path))
    audit = audit_activity_proposals(resolution_root, source_root)
    manifest = json.loads((resolution_root / "manifest.json").read_bytes())
    require(digest(helper_path.read_bytes()) == manifest["source_hashes"]["activity_resolutions.py"],
            "The reviewed activity constructor changed.")
    spec = importlib.util.spec_from_file_location("reviewed_activity_constructor", helper_path)
    constructor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(constructor)
    screen_path = helper_path.parent / "activity_screening.py"
    # A host source checkout may keep the earlier generic screen in another
    # folder; callers should colocate the two installed project helpers.
    require(screen_path.is_file(), "The installed activity screen must accompany the constructor.")
    screen = constructor.load_helper(screen_path)
    profiles = {r["profile_id"]: r for r in records(resolution_root / "proposed_public_profiles.jsonl")}
    old_activities = json.loads((resolution_root / "activity_resolution_proposals.json").read_bytes())
    old_by_id = {r["profile_id"]: r for r in old_activities["cases"]}
    drills = json.loads((source_root / "reference_snapshot/adopted_drills.json").read_bytes())["records"]
    by_id = {d["catalog_candidate_id"]: (i, d) for i, d in enumerate(drills)}
    rows = []
    for item in audit["cases"]:
        direction = item["source_activity"] in {"JR-NEW-0058", "JR-REVIEW-0054"} and bool(item["goal_review_notes"])
        court = bool(item["recommended_public_patches"])
        if not direction and not court:
            continue
        require(not (direction and court), "An unexpected overlapping activity correction needs review.")
        pid = item["profile_id"]
        previous = profiles[pid]
        public = previous["input"]
        if direction:
            selected_id, kind = "JR-NEW-0009", "lateral"
        else:
            selected_id = item["source_activity"]
            kind = {"JR-REVIEW-0051": "rhythm", "JR-NEW-0057": "turns"}[selected_id]
        proposed, _patches, origins = constructor.patch_public(public, kind)
        coach_available = "adult basketball coach available throughout all listed windows" in public["athlete_request"]
        if direction and coach_available:
            # Keep the existing coach and headcount. The former cue-only
            # permission becomes an explicit stationary support permission.
            proposed["space"]["restrictions"] = [
                "Only one athlete moves at a time; the listed adult coach may provide stationary practice support outside the movement path, including sending and receiving a ball. Other people wait outside the active area."]
            origins.append({"fact": "stationary support permission for the already available adult coach",
                "origin": "new_explicit_fictional_role_permission_proposal",
                "reason": "The source calls for a partner, not a peer-age category. Retain the declared coach and make the expanded stationary support permission explicit; no extra person is invented."})
        index, drill = by_id[selected_id]
        witness = constructor.make_witness(proposed, drill, index, kind, screen)
        if direction:
            support = "coach_1" if coach_available else "peer_1"
            witness["actors"] = [
                {"actor": "athlete", "role": "laterally moving defender responding to the rolled ball",
                 "origin": "existing_athlete_fact", "real_identity_inferred": False},
                {"actor": support, "role": "stationary ball-rolling partner outside the movement path",
                 "origin": "allocation_from_existing_declared_coach_and_new_support_permission" if coach_available else
                           "new_fictional_partner_headcount_fact" if public["participants_available"] == 1 else
                           "allocation_from_existing_available_headcount",
                 "real_identity_inferred": False}]
            witness["goal_relation"] = (
                "The complete source base explicitly rehearses lateral defensive movement in response to a partner's rolled ball. "
                "This is an editorial direct-action relation to controlled direction changes and foot placement; the source does not guarantee improved agility or prescribe an extra progression.")
        else:
            witness["actors"] = constructor.actors(kind, public["participants_available"])
        patches = [{"op": "replace", "path": "/input/" + key, "old": deepcopy(public[key]),
                    "new": deepcopy(proposed[key]), "origin": "new_explicit_fictional_resource_authoring_proposal",
                    "applied_to_source": False} for key in public if proposed[key] != public[key]]
        record = dict(deepcopy(previous), input=proposed)
        require(set(record["input"]) == set(public), "A correction added a private public-input property.")
        require(all(p["path"] in {"/input/space", "/input/participants_available"} for p in patches),
                "The minimal activity correction changed a non-resource field.")
        require(proposed["goals"] == public["goals"] and proposed["athlete_request"] == public["athlete_request"],
                "The activity correction changed the original task or goal.")
        require(all(proposed.get(key) == public.get(key) for key in
                    ("food_question", "age", "school_grade", "equipment", "planning_window", "schedule_coverage", "availability",
                     "existing_commitments", "time_limits", "reported_limitations", "basketball_background")),
                "An unrelated or verified fact changed during activity correction.")
        equipment = {v["name"].casefold(): v["quantity"] for v in proposed["equipment"]}
        require(proposed["participants_available"] >= (1 if kind == "rhythm" else 2), "A complete source role lacks a person.")
        require(equipment.get("basketball", 0) >= 1, "A selected source base lacks its ball.")
        if direction:
            require(equipment.get("cones", 0) >= 2, "The lateral source requires two markers.")
            require(witness["layout_allocation"]["marker_gap_feet"] == 6, "The proposed gap must remain within source6–8feet.")
        else:
            require(proposed["space"]["court_access"] in {"half_court", "full_court"}, "The court correction is incomplete.")
        for field, evidence in witness["source_evidence"].items():
            require(evidence == source_fact(index, drill, field), "A replacement witness changed a source fact.")
        low, high = elapsed_bounds(drill["source_prescription"])
        for slot in witness["witness_slots"]:
            duration = minute(slot["end_time"]) - minute(slot["start_time"])
            require(low <= Decimal(duration * 60) <= high and duration == slot["duration_minutes"],
                    "The replacement witness changed the complete elapsed source dose.")
            window = proposed["availability"][int(slot["availability_ref"].rsplit("/", 1)[1])]
            require(slot["date"] == window["date"] and minute(window["start_time"]) <= minute(slot["start_time"]) < minute(slot["end_time"]) <= minute(window["end_time"]),
                    "The replacement source witness falls outside availability.")
            require(duration <= proposed["time_limits"]["max_session_minutes"], "The source witness exceeds per-session cap.")
            for event in proposed["existing_commitments"]:
                require(event["date"] != slot["date"] or max(minute(slot["start_time"]), minute(event["start_time"])) >= min(minute(slot["end_time"]), minute(event["end_time"])),
                        "The source witness overlaps an unchanged existing event.")
        requested = int(re.search(r"\b([12])\s+(?:additional|extra)\s+practice\s+blocks?\b", proposed["athlete_request"], re.I)[1])
        require(len(witness["witness_slots"]) == requested <= proposed["time_limits"]["max_additional_sessions_per_week"],
                "The replacement source witness changes block count or exceeds frequency cap.")
        require(sum(slot["duration_minutes"] for slot in witness["witness_slots"]) <= proposed["time_limits"]["max_additional_minutes_per_week"],
                "The replacement source witness exceeds weekly minutes.")
        for source_drill in drills:
            require(source_drill["catalog_candidate_id"] not in proposed["athlete_request"]
                    and source_drill["drill_name"] not in proposed["athlete_request"], "A private source choice leaked into the public request.")
        rows.append({"profile_id": pid, "status": "direct_direction_change_witness_proposed" if direction else "retained_witness_court_fact_reconciliation_proposed",
            "selected": False, "approved": False, "team_review_status": "pending", "case_acceptance_created": False,
            "previous_public_record_sha256": digest(packed(previous)), "proposed_public_record_sha256": digest(packed(record)),
            "proposed_public_record": record, "patches": patches, "fact_origins": origins,
            "previous_activity_proposal": deepcopy(old_by_id[pid]), "private_witness": witness,
            "source_activity_changed": direction, "previous_source_activity": item["source_activity"],
            "proposed_source_activity": selected_id,
            "rationale": "Use a complete explicit lateral-response base for the unchanged direction-change goal." if direction else
                         "Apply the same explicit court-space fact to the retained source witness as to newer witnesses.",
            "goal_relation_is_editorial_not_effectiveness_guarantee": True,
            "skill_prerequisites_and_complete_case_acceptance_remain_separate": True})
    require(len(rows) == 20 and sum(r["source_activity_changed"] for r in rows) == 12,
            "The intended12direction and8court corrections do not join.")
    return {"schema_version": "step33-specific-activity-corrections-1", "cases": rows,
        "source_resolution_id": manifest["resolution_id"], "source_bindings": audit["source_bindings"],
        "reviewed_constructor_sha256": digest(helper_path.read_bytes()),
        "summary": {"activity_corrections_prepared": len(rows), "direct_lateral_response_replacements": 12,
            "earlier_court_fact_reconciliations": 8, "cases_with_new_public_resource_facts": sum(bool(r["patches"]) for r in rows),
            "new_partner_headcount_facts": sum(any(p["path"] == "/input/participants_available" for p in r["patches"]) for r in rows),
            "existing_coach_stationary_support_permissions": sum(any("already available adult coach" in f.get("fact", "") for f in r["fact_origins"]) for r in rows),
            "goals_changed": 0, "requests_changed": 0, "verified_food_facts_changed": 0,
            "case_approvals_created": 0, "new_model_calls": 0},
        "final_planner_execution_authorized": False}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("resolution_root")
    parser.add_argument("source_root")
    parser.add_argument("output")
    args = parser.parse_args()
    result = audit_activity_proposals(args.resolution_root, args.source_root)
    Path(args.output).write_bytes(packed(result))
    print(json.dumps(result["summary"], indent=2))
