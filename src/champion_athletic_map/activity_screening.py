"""Screen every approved base for private case-review proposals, without accepting cases."""

from collections import Counter
import csv
from decimal import Decimal
from datetime import date, timedelta
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re



def parse_elapsed_prescription(text):
    """Recognize one explicit elapsed dose; never infer elapsed time from repetitions or sets."""
    if not isinstance(text, str):
        return {"kind": "unresolved", "source_text": text, "seconds": None, "minutes": None, "calendar_minutes": None}
    matched = re.fullmatch(r"\s*(\d+(?:\.\d+)?)(?:\s*[–-]\s*(\d+(?:\.\d+)?))?\s+(minutes?|seconds?)\s*", text, re.I)
    if not matched:
        return {"kind": "unresolved", "source_text": text, "seconds": None, "minutes": None, "calendar_minutes": None,
                "reason": "Games, makes, repetitions, repeated bouts, per-side doses and missing prescriptions are not converted to elapsed block time."}
    low, high = Decimal(matched[1]), Decimal(matched[2] or matched[1])
    if not (0 < low <= high):
        return {"kind": "unresolved", "source_text": text, "seconds": None, "minutes": None, "calendar_minutes": None}
    factor = 60 if matched[3].lower().startswith("minute") else 1
    seconds, upper = low * factor, high * factor
    minutes = seconds / 60
    return {"kind": "single_explicit_elapsed_dose", "source_text": text,
            "seconds": float(seconds), "maximum_source_seconds": float(upper), "minutes": float(minutes),
            "calendar_minutes": int(minutes) if minutes == minutes.to_integral_value() else None,
            "choice": "Use the lower endpoint of the stated range; this is an authoring proposal within the original dose, not a new source prescription."}


# Editorial goal-to-base relations identify action relevance, not measured effectiveness.
GOAL_BASES = {
    "Build a repeatable set-shot action": ["JR-ADITI-0011", "JR-NEW-0049", "JR-REVIEW-0030", "JR-NEW-0016", "JR-REVIEW-0046", "JR-REVIEW-0014", "JR-ADITI-0014", "JR-NEW-0024"],
    "Improve accuracy from fixed shooting spots": ["JR-REVIEW-0030", "JR-NEW-0016", "JR-NEW-0049", "JR-ADITI-0011", "JR-REVIEW-0046", "JR-REVIEW-0014", "JR-ADITI-0014", "JR-REVIEW-0039"],
    "Coordinate foot placement before a layup": ["JR-NEW-0005", "JR-NEW-0007", "JR-NEW-0006", "JR-ADITI-0003", "JR-REVIEW-0021", "JR-REVIEW-0060", "JR-NEW-0014"],
    "Change direction with more consistent foot placement": ["JR-NEW-0058", "JR-REVIEW-0054", "JR-ADITI-0012", "JR-NEW-0057", "JR-NEW-0003", "JR-REVIEW-0066", "JR-REVIEW-0050"],
    "Improve controlled defensive direction changes": ["JR-NEW-0009", "JR-ADITI-0008", "JR-NEW-0036", "JR-NEW-0019", "JR-REVIEW-0009", "JR-NEW-0037", "JR-REVIEW-0005"],
    "Stay balanced while moving laterally on defense": ["JR-NEW-0009", "JR-ADITI-0008", "JR-NEW-0036", "JR-NEW-0019", "JR-REVIEW-0009", "JR-REVIEW-0056"],
    "Send controlled passes to a marked target": ["JR-REVIEW-0045", "JR-REVIEW-0026", "JR-REVIEW-0031", "JR-NEW-0013", "JR-NEW-0031", "JR-REVIEW-0035", "JR-NEW-0017", "JR-NEW-0008"],
    "Improve the timing of receiving and returning a pass": ["JR-REVIEW-0045", "JR-REVIEW-0035", "JR-REVIEW-0024", "JR-NEW-0008", "JR-REVIEW-0026", "JR-NEW-0017", "JR-NEW-0033"],
    "Develop more consistent basketball conditioning": ["JR-REVIEW-0053", "JR-NEW-0052", "JR-NEW-0047", "JR-NEW-0060", "JR-ADITI-0002", "JR-NEW-0043", "JR-REVIEW-0016"],
    "Manage my pace during short basketball practice blocks": ["JR-REVIEW-0051", "JR-NEW-0044", "JR-REVIEW-0050", "JR-NEW-0058", "JR-ADITI-0009", "JR-REVIEW-0062"],
    "Control my dribble while changing pace": ["JR-REVIEW-0051", "JR-NEW-0044", "JR-REVIEW-0050", "JR-NEW-0058", "JR-REVIEW-0062", "JR-ADITI-0009", "JR-REVIEW-0032", "JR-NEW-0002"],
    "Keep possession through controlled turns": ["JR-NEW-0003", "JR-NEW-0004", "JR-REVIEW-0042", "JR-REVIEW-0050", "JR-REVIEW-0066", "JR-NEW-0057"],
    "Improve controlled footwork near the basket": ["JR-NEW-0007", "JR-NEW-0005", "JR-NEW-0014", "JR-REVIEW-0066", "JR-REVIEW-0021", "JR-ADITI-0003", "JR-REVIEW-0060"],
    "Improve agility during short basketball movements": ["JR-ADITI-0012", "JR-NEW-0058", "JR-REVIEW-0054", "JR-NEW-0052", "JR-NEW-0001", "JR-REVIEW-0066"],
}


def active_lower_bound(roles, numeric):
    if type(numeric) is int and numeric > 0:
        return numeric, "Published numeric minimum"
    text = roles.casefold()
    if "individual" in text or "no mandatory partner" in text:
        return 1, "Published individual base action; optional partner progressions remain excluded"
    for phrase, total in [("two teams of five", 10), ("two teams of four", 8), ("three teams of four", 12),
                          ("two teams of three", 6), ("two trios", 6), ("groups of five", 5),
                          ("five-player", 5), ("teams of four", 4), ("four active", 4),
                          ("three active", 3), ("three players", 3), ("groups of three", 3),
                          ("three-player", 3), ("trios", 3), ("two active", 2),
                          ("two players per pair", 2), ("partner", 2), ("pairs", 2)]:
        if phrase in text:
            return total, "Lower bound from explicit source roles: " + phrase
    return None, "Source does not establish a complete participant count"


def screen(public, drill, index, relevant):
    evidence = {key: {"path": f"reference_snapshot/adopted_drills.json#/records/{index}/{key}", "value": drill.get(key)}
                for key in ["drill_name", "primary_goal", "instructions", "participants", "minimum_participants", "equipment", "space", "source_prescription", "use_conditions"]}
    known, unknown, blocked = [], [], []
    roles = str(drill.get("participants") or "")
    instruction = str(drill.get("instructions") or "")
    equipment_text = str(drill.get("equipment") or "")
    layout = str(drill.get("space") or "")
    p = public["participants_available"]
    count, count_basis = active_lower_bound(roles, drill.get("minimum_participants"))
    if count is None:
        unknown.append("Confirm full player count and rotation/line roles from the source; no numeric default is assumed.")
    elif p < count:
        blocked.append({"code": "insufficient_people_for_stated_roles", "available": p, "source_lower_bound": count, "basis": count_basis})
    else:
        known.append({"code": "stated_people_cover_source_role_lower_bound", "available": p, "source_lower_bound": count, "basis": count_basis})
    if re.search(r"\bcoach\b|cue.giver|cue.leader|leader cues|caller|cue-giving", roles + " " + instruction, re.I):
        unknown.append("Confirm the source's coach/cue-giver/leader role. A headcount alone does not establish that role or supervision.")
    eq = {row["name"].casefold(): row["quantity"] for row in public["equipment"]}
    ball_count = eq.get("basketball", 0)
    needs_ball = bool(re.search(r"\bbasketballs?\b|\bballs?\b", equipment_text, re.I)) and not re.search(r"no (?:basket)?ball", equipment_text, re.I)
    if needs_ball:
        per_unit = 2 if re.search(r"\btwo (?:basket)?balls?\b", equipment_text, re.I) else 1
        explicit = per_unit
        if "per player" in equipment_text.casefold() or "per active player" in equipment_text.casefold():
            explicit = per_unit * (count or 1) if "sharing" not in equipment_text.casefold() else per_unit
        if ball_count < explicit:
            blocked.append({"code": "insufficient_balls_for_explicit_base_requirement", "available": ball_count, "required_lower_bound": explicit})
        else:
            known.append({"code": "published_ball_lower_bound_available", "available": ball_count, "required_lower_bound": explicit})
        if count is None:
            unknown.append("Confirm per-line/per-group/per-player ball quantities for the final group setup.")
    if re.search(r"cones?|markers?|chair|bib|removable", equipment_text, re.I):
        marker_lower = 5 if "five" in equipment_text.casefold() else 3 if "three" in equipment_text.casefold() else 2 if "two" in equipment_text.casefold() else None
        if marker_lower is not None and eq.get("cones", 0) < marker_lower:
            blocked.append({"code": "insufficient_explicit_markers", "available_cones": eq.get("cones", 0), "source_lower_bound": marker_lower})
        elif marker_lower is not None:
            known.append({"code": "source_marker_lower_bound_available", "available_cones": eq.get("cones", 0), "source_lower_bound": marker_lower})
        else:
            unknown.append("Confirm exact marker/object type and count from the source; unspecified chairs/bibs/marker counts are not supplied by default.")
    needs_hoop = bool(re.search(r"\bhoop\b|\bbaskets?\b", equipment_text + " " + layout, re.I))
    space = public["space"]
    if needs_hoop and space.get("hoop_access") is not True:
        blocked.append({"code": "source_basket_unavailable", "profile_hoop_access": space.get("hoop_access")})
    elif needs_hoop:
        known.append({"code": "basket_access_stated"})
    court = space.get("court_access")
    full = bool(re.search(r"full (?:basketball )?court|opposite (?:baseline|basket)|both baselines|both baskets", layout, re.I))
    half_or_marked = bool(re.search(r"half.?court|baseline|sideline|three.point|free.throw|\bkey\b|\bwing\b|\bpaint\b|\barc\b|\blane\b|\bblock\b", layout, re.I))
    if full and court != "full_court":
        blocked.append({"code": "required_full_court_layout_not_supplied", "court_access": court})
    elif full:
        known.append({"code": "full_court_context_stated"})
    elif half_or_marked and court in ("full_court", "half_court"):
        known.append({"code": "court_context_for_source_markings_stated", "qualification": "Review actual source markings/clearance; no missing numeric floor dimensions are invented."})
    elif half_or_marked:
        unknown.append("Confirm the source's actual marked-court layout or record an explicit reviewed adaptation; a single hoop or open zone does not establish court markings.")
    elif "court" in layout.casefold() and court == "none":
        unknown.append("The published base is described in court space. Confirm the non-court zone preserves the base layout; no shortened-area adaptation is assumed.")
    else:
        known.append({"code": "no_conflicting_source_layout_requirement_identified", "qualification": "This does not certify unrecorded dimensions, surface or safety clearance."})
    if "one moving participant at a time" in " ".join(space.get("restrictions") or []).casefold() and count is not None and count > 1:
        unknown.append("Confirm whether the source's simultaneous partner/group roles can satisfy the one-mover restriction; do not silently adopt turn-taking/solo changes.")
    elapsed = parse_elapsed_prescription(drill.get("source_prescription"))
    if elapsed["kind"] != "single_explicit_elapsed_dose":
        unknown.append("The exact source prescription does not establish a single elapsed block. Keep its games/repetitions/sets/each-way qualification; do not fabricate duration or rest.")
    elif elapsed["calendar_minutes"] is None:
        unknown.append("This source dose is shorter than an integer-minute calendar block; a separately justified allocation is needed, not rounding the source dose upward.")
    if not relevant:
        unknown.append("No direct action-to-goal relation was selected by this editorial mapping; this record is not a proposed main activity for this case.")
    return {"catalog_candidate_id": drill["catalog_candidate_id"], "source_index": index, "drill_name": drill["drill_name"],
            "source_evidence": evidence, "goal_relation": "editorial_action_match_pending_team_review" if relevant else "not_selected_as_direct_goal_match",
            "known_checks": known, "unknown_conditions": unknown, "hard_blockers": blocked, "elapsed_prescription": elapsed,
            "base_case_approval": False, "full_case_feasibility_proved": False,
            "status": "known_source_conflict" if blocked else "requires_fact_or_allocation_review" if unknown else "known_context_and_elapsed_base_example_available"}


def minute(value):
    hour, minutes = map(int, value.split(":"))
    return hour * 60 + minutes


def clock(value):
    return f"{value//60:02d}:{value%60:02d}"


def time_witness(public):
    requested = int(re.search(r"\b([12])\s+(?:additional|extra)\s+practice\s+blocks?\b", public["athlete_request"], re.I)[1])
    limits = public["time_limits"]
    start = date.fromisoformat(public["planning_window"]["start_date"])
    end = date.fromisoformat(public["planning_window"]["end_date"])
    days = [(start + timedelta(days=i)).isoformat() for i in range((end-start).days + 1)]
    assert len(days) == 7
    blockers = {day: [(minute(event["start_time"]), minute(event["end_time"])) for event in public["existing_commitments"] if event["date"] == day] for day in days}
    free = []
    for index, window in enumerate(public["availability"]):
        assert window["date"] in days
        pieces = [(minute(window["start_time"]), minute(window["end_time"]))]
        for left, right in sorted(blockers[window["date"]]):
            remaining = []
            for first, last in pieces:
                if right <= first or left >= last:
                    remaining.append((first,last))
                else:
                    if first < left:
                        remaining.append((first,left))
                    if right < last:
                        remaining.append((right,last))
            pieces = remaining
        free.extend((window["date"], left, right, index) for left,right in pieces if right > left)
    free.sort()
    witness = None
    if requested <= limits["max_additional_sessions_per_week"]:
        options = sorted(combinations(free, requested), key=lambda rows:(len({row[0] for row in rows}) != requested, rows))
        for rows in options:
            duration = min(limits["max_session_minutes"],limits["max_additional_minutes_per_week"]//requested,*(right-left for day,left,right,index in rows))
            if duration <= 0:
                continue
            slots = [{"date":day,"start_time":clock(left),"end_time":clock(left+duration),"duration_minutes":duration,"availability_ref":f"/input/availability/{index}"} for day,left,right,index in rows]
            if any(a["date"] == b["date"] and max(minute(a["start_time"]),minute(b["start_time"])) < min(minute(a["end_time"]),minute(b["end_time"])) for a,b in combinations(slots,2)):
                continue
            witness = slots
            break
    assert witness is not None
    return {"requested_additional_blocks":requested,"temporal_feasibility":{"witness":witness}}


def build_activity_review(package_root):
    ROOT = Path(package_root).resolve()
    profiles = [json.loads(line) for line in (ROOT / "source_public_profiles.jsonl").read_bytes().splitlines()]
    metadata = {row["profile_id"]: row for row in csv.DictReader((ROOT / "source_manifest.csv").open(encoding="utf-8", newline=""))}
    drills = json.loads((ROOT / "reference_snapshot/adopted_drills.json").read_bytes())["records"]
    temporal = {row["profile_id"]: time_witness(row["input"]) for row in profiles if metadata[row["profile_id"]]["scenario_intent"] == "feasible"}
    original_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("source_public_profiles.jsonl", "source_manifest.csv", "reference_snapshot/adopted_drills.json", "reference_snapshot/adopted_rules.json")}
    assert len(drills) == 136
    cases, screen_totals = [], Counter()
    for profile in profiles:
        identifier, public = profile["profile_id"], profile["input"]
        if metadata[identifier]["scenario_intent"] != "feasible":
            continue
        direct = list(dict.fromkeys(candidate for goal in public["goals"] for candidate in GOAL_BASES[goal]))
        examined = [screen(public, drill, index, drill["catalog_candidate_id"] in direct) for index, drill in enumerate(drills)]
        screen_totals.update(candidate["status"] for candidate in examined)
        candidates = [candidate for candidate in examined if candidate["catalog_candidate_id"] in direct]
        candidates.sort(key=lambda row: (bool(row["hard_blockers"]), len(row["unknown_conditions"]),
                                          row["elapsed_prescription"]["calendar_minutes"] is None, direct.index(row["catalog_candidate_id"])))
        selected = candidates[:3]
        usable = next((candidate for candidate in candidates if not candidate["hard_blockers"] and not candidate["unknown_conditions"]), None)
        example = None
        if usable is not None:
            duration = usable["elapsed_prescription"]["calendar_minutes"]
            slots = []
            for slot in temporal[identifier]["temporal_feasibility"]["witness"]:
                if duration > slot["duration_minutes"]:
                    slots = []
                    break
                slots.append({"date": slot["date"], "start_time": slot["start_time"], "end_time": clock(minute(slot["start_time"]) + duration),
                              "duration_minutes": duration, "availability_ref": slot["availability_ref"],
                              "catalog_candidate_id": usable["catalog_candidate_id"], "source_prescription": usable["elapsed_prescription"]["source_text"],
                              "relationship": "separate_session", "prescription_repetitions_added": False})
            if len(slots) == temporal[identifier]["requested_additional_blocks"]:
                assert sum(slot["duration_minutes"] for slot in slots) <= public["time_limits"]["max_additional_minutes_per_week"]
                example = {"status": "source_linked_calendar_example_pending_team_review", "witness_slots": slots,
                           "source_activity": usable["catalog_candidate_id"], "new_fictional_coverage_assumed_for_proposal": True,
                           "source_weekly_frequency_claimed": False, "invented_rest_or_dose": False,
                           "qualification": "Dates/frequency are case-authoring choices. Base action and elapsed dose stay within source. Source prerequisites, actual clearance and case-level adopted rule checks still need team review.",
                           "case_approved": False}
        changes = []
        first = selected[0]
        codes = {item["code"] for item in first["hard_blockers"]}
        if "insufficient_people_for_stated_roles" in codes:
            minimum = next(item["source_lower_bound"] for item in first["hard_blockers"] if item["code"] == "insufficient_people_for_stated_roles")
            changes.append({"field": "/input/participants_available", "original": public["participants_available"], "proposed_minimum": minimum,
                            "applied": False, "condition": "Only if the case author deliberately changes this fictional resource fact and a teammate reviews it; otherwise choose another supported base or keep the case on hold."})
        if "source_basket_unavailable" in codes:
            changes.append({"field": "/input/space", "applied": False,
                            "proposal": "If retaining this basket-dependent base, author actual hoop and suitable space access explicitly; otherwise use a source-supported no-hoop base. Do not silently change the original resource restriction."})
        cases.append({"profile_id": identifier, "source_record_sha256": metadata[identifier]["record_sha256"], "draft_category": "feasible",
                      "approved": False, "team_review_status": "pending", "review_origin": "source_and_software_analysis",
                      "catalog_records_examined": len(examined), "direct_goal_bases_screened": len(candidates),
                      "goal_mapping_is_editorial_not_effectiveness_evidence": True, "candidate_options": selected,
                      "selected_example": example, "proposed_fictional_fact_changes": changes,
                      "status": "activity_example_prepared_pending_team_review" if example else "activity_or_fact_confirmation_needed",
                      "remaining_decisions": ["Review the new fictional schedule-completeness fact, the source use conditions and skill prerequisites, and the case's adopted rule/check mask before accepting any case."]
                          + ([] if example else list(dict.fromkeys(first["unknown_conditions"] + ["Resolve identified source-base conflicts or choose a different supported base; a shortlist finding is not a catalog-wide impossibility proof."])))})
    assert len(cases) == 150 and len({row["profile_id"] for row in cases}) == 150
    result = {"schema_version": "step33-activity-correction-proposals-1", "source_package_id": json.loads((ROOT / "manifest.json").read_bytes())["package_id"],
              "source_file_sha256": {name: original_hashes[name] for name in ["source_public_profiles.jsonl", "source_manifest.csv", "reference_snapshot/adopted_drills.json", "reference_snapshot/adopted_rules.json"]},
              "screening_policy": "All 136 source records are examined against each case. Editorial action mappings select relevant candidates; at most three best supported bases are shown. This is not exhaustive certification of all possible adaptations or medical suitability.",
              "summary": {"cases_covered": len(cases), "approved_bases_examined_per_case": len(drills), "case_record_screens": len(cases)*len(drills),
                          "case_screen_status_counts": dict(screen_totals), "source_linked_activity_calendar_examples": sum(row["selected_example"] is not None for row in cases),
                          "activity_or_fact_confirmation_needed": sum(row["selected_example"] is None for row in cases), "case_approvals_created": 0, "planner_model_calls": 0},
              "cases": cases}
    for relative, digest in original_hashes.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
    return result
