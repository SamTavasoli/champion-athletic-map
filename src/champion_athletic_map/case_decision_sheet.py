"""Prepare a concrete private case recommendation sheet before recorded team review."""

from collections import Counter
from copy import deepcopy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from html import escape

VERSION = "final-case-decision-sheet-proposals-1"
RESOLUTION_ID = "710346229bae42991886e12dc9c3dc840392fe5234766fe40fe32ca229c4be5b"
RESOLUTION_MANIFEST_SHA256 = "0d523f628cd5624ddb5b1277e002d45698c0afee98ce889b63309f915a75223a"
RESOLUTION_RELATIVE = "results/final_case_review/review_cb1efb8523e7c29384d3/resolutions_710346229bae42991886"
OLD_GOAL = "Develop more consistent basketball conditioning"
NEW_GOAL = "Control my dribble while changing pace"


def require(value, message):
    if not value:
        raise ValueError(message)


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def lines(path):
    return [json.loads(line) for line in Path(path).read_bytes().splitlines() if line.strip()]


def jsonl(rows):
    return b"".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                              allow_nan=False).encode("utf-8") + b"\n" for row in rows)


def csv_data(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def module(root, name):
    path = Path(root) / "src/champion_athletic_map" / name
    spec = importlib.util.spec_from_file_location("case_sheet_" + path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def save_once(path, data):
    path = Path(path)
    if path.exists():
        require(path.read_bytes() == data, "A saved case-review file has local changes and was preserved: " + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)


def load_resolution(root):
    folder = Path(root) / RESOLUTION_RELATIVE
    require(digest((folder / "manifest.json").read_bytes()) == RESOLUTION_MANIFEST_SHA256,
            "The uploaded Step 33-3 resolution package is required.")
    manifest = json.loads((folder / "manifest.json").read_bytes())
    require(manifest["resolution_id"] == RESOLUTION_ID and manifest["accepted_cases"] == 0
            and manifest["final_planner_execution_authorized"] is False,
            "The source resolution version differs from the reviewed proposals.")
    for name, expected in manifest["files"].items():
        path = (folder / name).resolve()
        require(path.is_relative_to(folder.resolve()) and digest(path.read_bytes()) == expected,
                "A bound resolution file changed: " + name)
    return folder, manifest


def apply_recommendations(previous, source, conditioning, corrections):
    """Select a review version; no choice becomes an accepted case or model input."""
    public = {row["profile_id"]: deepcopy(row) for row in previous}
    old = {row["profile_id"]: row for row in previous}
    activity_rows = json.loads((source / "activity_resolution_proposals.json").read_bytes())["cases"]
    activity_by_id = {row["profile_id"]: deepcopy(row) for row in activity_rows}
    conditioning_ids = {row["profile_id"] for row in conditioning["case_decision_proposals"]}
    correction_ids = {row["profile_id"] for row in corrections["cases"]}
    require(len(conditioning_ids) == 11 and len(correction_ids) == 20 and not conditioning_ids & correction_ids,
            "The material goal choices and activity corrections do not join.")
    choices = []
    for pid in conditioning_ids:
        before = old[pid]
        row = activity_by_id[pid]
        alternative = row["optional_material_goal_reauthoring"]
        require(alternative["selected"] is False and before["input"]["goals"] == [OLD_GOAL],
                "A conditioning alternative was already selected or has a different goal.")
        record = deepcopy(alternative["proposed_public_record"])
        require(record["input"]["goals"] == [NEW_GOAL]
                and record["input"]["athlete_request"] == before["input"]["athlete_request"].replace(OLD_GOAL, NEW_GOAL),
                "The material goal alternative changed more than its stated request goal.")
        public[pid] = record
        activity_by_id[pid] = {"profile_id": pid, "status": "material_skill_goal_version_recommended_for_review",
            "proposed_public_record": record, "private_witness": deepcopy(alternative["private_witness"]),
            "patches": deepcopy(alternative["patches"]), "selected_for_review_version": True,
            "accepted": False, "team_review_status": "pending", "previous_activity_proposal": row,
            "goal_change_is_not_a_conditioning_solution": True}
        choices.append({"profile_id": pid, "choice_kind": "material_goal_and_optional_venue_reauthoring",
            "rationale": "Recommend the explicitly narrower approved-catalog basketball-skill benchmark. The original conditioning request is not fulfilled by this change.",
            "patches": deepcopy(alternative["patches"]), "accepted": False})
    for row in corrections["cases"]:
        pid = row["profile_id"]
        public[pid] = deepcopy(row["proposed_public_record"])
        activity_by_id[pid] = {**deepcopy(row), "selected_for_review_version": True,
            "accepted": False, "team_review_status": "pending"}
        choices.append({"profile_id": pid,
            "choice_kind": "direct_direction_change_source_example" if row["source_activity_changed"] else "court_fact_consistency",
            "rationale": row["rationale"], "patches": deepcopy(row["patches"]), "accepted": False})
    require(len(activity_by_id) == 150 and all(row.get("private_witness") for row in activity_by_id.values()),
            "A planning recommendation lacks its private source example.")
    result = [public[row["profile_id"]] for row in previous]
    return result, list(activity_by_id.values()), sorted(choices, key=lambda r: r["profile_id"])


def check_case_versions(previous, proposed, metadata, decisions):
    before = {row["profile_id"]: row for row in previous}
    after = {row["profile_id"]: row for row in proposed}
    require(len(before) == len(after) == len(proposed) == 200 and before.keys() == after.keys(),
            "A case identity or the total case count changed.")
    decision_by_id = {row["profile_id"]: row for row in decisions}
    changed = []
    for pid, record in after.items():
        previous_record = before[pid]
        require(record.keys() == previous_record.keys() and record["schema_version"] == previous_record["schema_version"]
                and record["input"].keys() == previous_record["input"].keys(),
                "Private fields or a changed wrapper entered a public case.")
        if metadata[pid]["scenario_intent"] != "feasible":
            require(record == previous_record, "A challenge case changed.")
        rebuilt = deepcopy(previous_record)
        for patch in decision_by_id.get(pid, {}).get("patches", []):
            require(patch["op"] == "replace" and patch["path"] in
                    {"/input/goals", "/input/athlete_request", "/input/space", "/input/participants_available"},
                    "An unsupported field changed in the review version.")
            key = patch["path"].split("/")[-1]
            require(rebuilt["input"][key] == patch["old"], "A case patch has a stale previous value.")
            rebuilt["input"][key] = deepcopy(patch["new"])
        require(rebuilt == record, "The review version contains an unrecorded case amendment.")
        for key in ("age", "school_grade", "basketball_background", "availability", "existing_commitments", "equipment",
                    "planning_window", "schedule_coverage", "reported_limitations", "time_limits", "food_question"):
            require(previous_record["input"].get(key) == record["input"].get(key),
                    "An unrelated or verified fact changed: " + key)
        if record != previous_record:
            changed.append({"profile_id": pid, "previous_record_sha256": digest(packed(previous_record)),
                "proposed_record_sha256": digest(packed(record)),
                "public_field_changes": [{"field": "/input/" + key, "previous": previous_record["input"][key],
                                          "proposed": record["input"][key]} for key in record["input"]
                                         if record["input"][key] != previous_record["input"][key]],
                "team_decision": None, "origin": "new_explicit_fictional_case_recommendation"})
    goal_changes = [pid for pid in after if before[pid]["input"]["goals"] != after[pid]["input"]["goals"]]
    require(len(goal_changes) == 11 and all(before[pid]["input"]["goals"] == [OLD_GOAL]
        and after[pid]["input"]["goals"] == [NEW_GOAL] for pid in goal_changes),
        "The proposed conditioning-scope change is not exactly the reviewed 11 cases.")
    return changed


def normalize_witnesses(root, source_package, profiles, activities):
    constructor = module(root, "activity_resolutions.py")
    screen = module(root, "activity_screening.py")
    drills = json.loads((source_package / "reference_snapshot/adopted_drills.json").read_bytes())["records"]
    by_source = {drill["catalog_candidate_id"]: (i, drill) for i, drill in enumerate(drills)}
    by_id = {r["profile_id"]: r for r in profiles}
    witnesses = []
    for row in activities:
        pid, witness = row["profile_id"], deepcopy(row["private_witness"])
        public = by_id[pid]["input"]
        if "earlier_selected_example" in witness:
            earlier = witness["earlier_selected_example"]
            selected_id = earlier["source_activity"]
            index, drill = by_source[selected_id]
            witness = {"source_evidence": {field: {"path": "reference_snapshot/adopted_drills.json#/records/" + str(index) + "/" + field,
                "value": deepcopy(drill.get(field))} for field in constructor.EVIDENCE_FIELDS},
                "source_record_sha256": digest(constructor.encode(drill)),
                "elapsed_interpretation": constructor.single_elapsed(drill["source_prescription"], screen.parse_elapsed_prescription),
                "witness_slots": deepcopy(earlier["witness_slots"]),
                "complete_source_base_preserved": True, "source_weekly_frequency_claimed": False,
                "goal_relation": "Retained complete source-base action example. Goal relevance and source prerequisites remain a recorded case-review decision.",
                "earlier_example_preserved": deepcopy(earlier)}
        selected_id = witness["source_evidence"]["catalog_candidate_id"]["value"]
        index, drill = by_source[selected_id]
        for key, fact in witness["source_evidence"].items():
            require(fact["path"] == "reference_snapshot/adopted_drills.json#/records/" + str(index) + "/" + key
                    and drill.get(key) == fact["value"], "A private witness source fact changed.")
        parsed = constructor.single_elapsed(drill["source_prescription"], screen.parse_elapsed_prescription)
        require(parsed["kind"] == "single_explicit_elapsed_dose", "A private example lacks one complete elapsed source base.")
        for slot in witness["witness_slots"]:
            duration = screen.minute(slot["end_time"]) - screen.minute(slot["start_time"])
            require(duration == parsed["calendar_minutes"] == slot["duration_minutes"], "The private witness source dose differs.")
        if selected_id == "JR-REVIEW-0051" and "actors" not in witness:
            witness["actors"] = constructor.actors("rhythm", public["participants_available"])
        witness.update({"privacy": "private_case_review_only_not_planner_input", "profile_id": pid,
            "public_record_sha256": digest(packed(by_id[pid])), "case_accepted": False,
            "case_level_prerequisite_and_goal_review": "pending",
            "complete_accepted_feasibility_proof_claimed": False})
        row["private_witness"] = witness
        row["proposed_public_record"] = deepcopy(by_id[pid])
        witnesses.append({"profile_id": pid, "public_record_sha256": digest(packed(by_id[pid])), "witness": witness})
    require(len(witnesses) == len({r["profile_id"] for r in witnesses}) == 150,
            "The 150 private source examples are incomplete.")
    return witnesses


def project_choices():
    return [
        {"decision_id": "benchmark_scope", "recommendation": "Use the approved-catalog basketball-skill case set; recommend the 11 explicitly recorded conditioning-to-pace-control goal changes.",
         "consequence": "Conditioning is not evaluated. The planning set has 13 goal types; pace-control cases increase from 10 to 21. All 200 identities and 150/20/15/15 case counts are retained."},
        {"decision_id": "activity_and_case_facts", "recommendation": "Review the 12 directly matching direction-change examples and eight consistent court-space proposals, together with the earlier resource and coverage proposals.",
         "consequence": "New people, venue or support facts remain explicit fictional authoring choices. Source curriculum labels, skill prerequisites and goal fit require case-level decisions."},
        {"decision_id": "case_families", "recommendation": "Retain one case family per separately authored base and keep each base's versions together. Recommend no merge or exclusion solely from the resemblance flags, including the nine limited legacy comparisons.",
         "consequence": "All historical warnings remain evidence. Complete legacy equality is unassessable; retained bases do not establish independence from the common recipe or real-athlete generalization."},
        {"decision_id": "paired_uncertainty_design", "recommendation": "Use all four workflow outcomes in the same 2,000 paired family resamples with seed 42; predeclare a separate sensitivity analysis over the 14 original request-pattern design groups.",
         "consequence": "These are proposed choices before final outcomes. The common scoring protocol, applicability decisions and final freeze still need completion."},
    ]


def execute(root, emit=print):
    root = Path(root).resolve()
    require("/results/final_case_review/" in (root / ".gitignore").read_text(encoding="utf-8-sig").splitlines(),
            "The private case-review folder exclusion is required.")
    source = module(root, "case_corrections.py").load_package(root)
    return prepare_from_verified_source(root, source, emit=emit)


def prepare_from_verified_source(root, source, emit=print):
    root = Path(root).resolve()
    resolution_root, manifest = load_resolution(root)
    previous = lines(resolution_root / "proposed_public_profiles.jsonl")
    conditioning = module(root, "conditioning_case_review.py").build_conditioning_review(resolution_root, source["package_root"])
    corrections = module(root, "activity_case_audit.py").propose_activity_corrections(resolution_root,
        source["package_root"], root / "src/champion_athletic_map/activity_resolutions.py")
    profiles, activities, choices = apply_recommendations(previous, resolution_root, conditioning, corrections)
    amendments = check_case_versions(previous, profiles, source["metadata"], choices)
    from jsonschema import Draft202012Validator, FormatChecker
    schema = root / "artifacts/pilot/case_review_794f10d9d10a5fde/public_profile_schema.json"
    validator = Draft202012Validator(json.loads(schema.read_bytes()), format_checker=FormatChecker())
    for record in profiles:
        validator.validate(record)
    witnesses = normalize_witnesses(root, source["package_root"], profiles, activities)
    challenge = module(root, "challenge_case_review.py").build_challenge_review(profiles, source["metadata"])
    core = module(root, "case_resolutions.py")
    correction_folder, _, _, prior_register, food = core.load_corrections(root)
    rules = module(root, "case_rule_review.py").build_rule_review(source["package_root"], correction_folder,
                                                               public_profiles=profiles)
    emit("Preparing the case choices and their review evidence…")
    family_helper = module(root, "case_relationship_proposals.py")
    screen = module(root, "family_reconciliation.py")
    scratch_parent = source["package_root"] / "decision_work"
    scratch_parent.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix="review_", dir=scratch_parent) as scratch:
        families = family_helper.prepare_relationship_proposals(source["package_root"], correction_folder,
            root, scratch, profiles_override=profiles, compare_populations=screen.compare_populations)
    generator = family_helper.module(root / screen.PROTECTED / "protected_generator.py", "decision_original_pair_screen")
    families["fresh_candidate_candidate_screen"] = core.compare_current_candidates(profiles, generator)
    family_choices = module(root, "family_decision_builder.py").build_family_decisions(resolution_root,
        source["package_root"], public_profiles=profiles, current_family_evidence=families)
    require(family_choices["summary"]["current_relationship_rescreens_complete"] is True,
            "The revised case-family evidence is incomplete.")
    return save_package(root, source, resolution_root, manifest, previous, profiles, activities,
        witnesses, choices, amendments, conditioning, corrections, challenge, rules, families,
        family_choices, food, prior_register)


def save_package(root, source, resolution_root, manifest, previous, profiles, activities,
        witnesses, choices, amendments, conditioning, corrections, challenge, rules, families,
        family_choices, food, prior_register):
    planning_ids = {r["profile_id"] for r in activities}
    counts_before = Counter(r["input"]["goals"][0] for r in previous if r["profile_id"] in planning_ids)
    counts_after = Counter(r["input"]["goals"][0] for r in profiles if r["profile_id"] in planning_ids)
    require(len(counts_before) == 14 and len(counts_after) == 13 and counts_after.get(OLD_GOAL, 0) == 0
            and counts_before[NEW_GOAL] == 10 and counts_after[NEW_GOAL] == 21,
            "The recommended goal-composition change differs from its recorded scope choice.")
    identity = {"schema_version": VERSION, "source_resolution_id": RESOLUTION_ID,
        "source_resolution_manifest_sha256": RESOLUTION_MANIFEST_SHA256,
        "recommended_population_sha256": digest(jsonl(profiles)),
        "private_witnesses_sha256": digest(packed(witnesses)), "case_choices_sha256": digest(packed(choices)),
        "current_family_evidence_sha256": digest(packed(families)),
        "source_hashes": {name: digest((root / "src/champion_athletic_map" / name).read_bytes()) for name in
            ("case_decision_sheet.py", "conditioning_case_review.py", "activity_case_audit.py",
             "challenge_case_review.py", "family_decision_builder.py")}}
    sheet_id = digest(packed(identity))
    relative = source["package_root"].relative_to(root).as_posix() + "/decision_sheet_" + sheet_id[:20]
    folder = root / relative
    activities_payload = {"schema_version": "recommended-case-activity-examples-1", "cases": activities,
        "summary": {"source_linked_activity_examples": 150, "examples_accepted": 0,
            "material_goal_changes_recommended": 11, "direction_change_examples_replaced": 12,
            "earlier_court_facts_reconciled": 8}}
    html = module(root, "case_resolution_report.py").render(profiles, source["metadata"], activities_payload,
        amendments, rules, families, food, prior_register).decode("utf-8")
    html = html.replace("Step 33-3 — Case decisions", "Step 33-4 — Team case decisions")
    html = html.replace("The current resource facts are retained.",
        "The earlier proposed resource facts are carried forward for team review and remain unaccepted.")
    html = html.replace("Proposed fictional resource facts", "Proposed fictional case facts")
    old_scope = "The optional conditioning alternatives change the goal and remain unselected."
    require(old_scope in html, "The reviewed case-page wording changed.")
    html = html.replace(old_scope, "This review version recommends the 11 explicit changes from conditioning to pace-control skills. Those changes are awaiting the team's scope decision; conditioning is not evaluated by the revised case set.")
    html = html.replace("The nine incomplete legacy comparisons remain open.",
        "We recommend retaining the nine legacy-linked cases as separately authored bases. Their incomplete-source comparison warnings remain recorded; this does not establish independence.")
    panel = '<section class="panel"><h2>Decisions for this review version</h2><ol>'
    for choice in project_choices():
        panel += '<li><p><strong>' + escape(choice["recommendation"]) + '</strong><br>' + escape(choice["consequence"]) + '</p></li>'
    panel += ('</ol><p>Use <a href="working/project_decisions.csv">working/project_decisions.csv</a> for these shared choices and '
        '<a href="working/team_decisions.csv">working/team_decisions.csv</a> for each case. '
        'The team decision columns are blank. Record the actual preparer and a distinct teammate who reviewed the current version.</p>'
        '<p>For planning cases, review the complete activity source, goal fit, stated resources and skill prerequisites. '
        'For the 50 challenge cases, check the expected clarification, contradiction or scope boundary below.</p></section>')
    html = html.replace('<div class="toolbar">', panel + '<div class="toolbar">', 1)
    # Add the explicit challenge proofs without mixing them into public records.
    challenge_by_id = {r["profile_id"]: r for r in challenge["cases"]}
    for record in profiles:
        pid = record["profile_id"]
        if pid not in challenge_by_id:
            continue
        marker = '<p class="small">' + escape(pid, quote=True) + '</p>'
        proof = challenge_by_id[pid]
        html = html.replace(marker, marker + '<p><strong>Expected response:</strong> ' + escape(proof["expected_response_type"]) +
            '. ' + escape(proof["rationale"]) + '</p><details><summary>Challenge facts and review criteria</summary><pre>' +
            escape(json.dumps(proof, ensure_ascii=False, indent=2), quote=True) + '</pre></details>', 1)
    previous_by_id = {r["profile_id"]: r for r in previous}
    activity_by_id = {r["profile_id"]: r for r in activities}
    family_by_id = {r["profile_id"]: r for r in family_choices["case_family_recommendations"]}
    case_rows = []
    for index, record in enumerate(profiles, 1):
        pid = record["profile_id"]
        activity = activity_by_id.get(pid)
        proof = challenge_by_id.get(pid)
        evidence = (activity or {}).get("private_witness", {}).get("source_evidence", {})
        case_rows.append({"case_number": index, "profile_id": pid,
            "current_proposed_record_sha256": digest(packed(record)),
            "previous_step33_3_record_sha256": digest(packed(previous_by_id[pid])),
            "proposed_category": source["metadata"][pid]["scenario_intent"],
            "proposed_response_type": "plan" if activity else proof["expected_response_type"],
            "age": record["input"]["age"], "goal": "; ".join(record["input"].get("goals") or []),
            "source_activity": evidence.get("drill_name", {}).get("value", ""),
            "source_curriculum_level": evidence.get("source_curriculum_level", {}).get("value", ""),
            "reported_experience": record["input"].get("basketball_background", {}).get("experience_level", ""),
            "source_dose": evidence.get("source_prescription", {}).get("value", ""),
            "case_changed_from_step33_3": record != previous_by_id[pid],
            "recommendation": "review_revised_basketball_skill_case" if previous_by_id[pid]["input"]["goals"] != record["input"]["goals"]
                else "review_source_example_and_case_facts" if activity else "retain_supported_challenge_case",
            "proposed_family_id": family_by_id[pid]["proposed_authored_base_family_id"] or "",
            "case_fact_decision": "", "goal_and_source_prerequisite_decision": "", "witness_and_rule_decision": "",
            "food_decision": "", "family_decision": "", "prepared_by": "", "reviewed_by": "", "team_decision": "", "notes": ""})
    global_rows = [{**choice, "team_decision": "", "prepared_by": "", "reviewed_by": "", "notes": ""}
                   for choice in project_choices()]
    native_working = resolution_root / "working/team_decisions.csv"
    prior_working = native_working.read_bytes() if native_working.is_file() else b""
    immutable = {"recommended_public_profiles.jsonl": jsonl(profiles), "private_activity_examples.json": packed(witnesses),
        "private_activity_proposals.json": packed(activities_payload), "case_choice_recommendations.json": packed(choices),
        "case_amendments.json": packed(amendments), "conditioning_scope_review.json": packed(conditioning),
        "activity_corrections_review.json": packed(corrections), "challenge_case_review.json": packed(challenge),
        "private_rule_bounds.json": packed(rules), "current_family_evidence.json": packed(families),
        "family_decision_recommendations.json": packed(family_choices),
        "private_food_expectations.json": (resolution_root / "private_food_expectations.json").read_bytes(),
        "prior_step33_3_team_decisions.csv": prior_working,
        "review_decisions.html": html.encode("utf-8"), "team_decisions_TEMPLATE.csv": csv_data(case_rows),
        "project_decisions_TEMPLATE.csv": csv_data(global_rows),
        "goal_composition.json": packed({"previous": dict(sorted(counts_before.items())),
            "recommended": dict(sorted(counts_after.items())), "conditioning_evaluated_by_recommended_set": False,
            "scope_decision_adopted": False})}
    immutable["README.md"] = ("# Step 33-4 — Team case decisions\n\nOpen review_decisions.html. This review version recommends replacing the11 conditioning goals with pace-control basketball skills, "
        "using12 directly matching direction-change examples, and reconciling8 earlier court-space facts. "
        "The conditioning requests are not solved by these changes; the recommended final benchmark excludes conditioning. "
        "The 200 identities, provisional150/20/15/15 case balance,50 challenge cases and20 verified food answers are preserved. "
        "Original versions remain in the earlier review packages.\n\n"
        "Use working/project_decisions.csv for the shared scope/family/sampling choices and working/team_decisions.csv for each current case. "
        "The current team fields are blank; record actual preparation and review by a distinct teammate, including source prerequisites and goal fit. "
        "The sheet contains recommendations rather than adopted cases. Source-linked short examples and conditional numerical bounds are not complete accepted feasibility proofs. "
        "Legacy-source warnings and common design dependence remain evidence even when the recommended operational convention retains separately authored families.\n\n"
        "No final generation is enabled. Accepted-record validation, the common scoring/applicability protocol and final freeze still need completion. "
        "Private expected behaviors, source choices, witnesses, food answers and family metadata must stay out of prompts, RAG and Version4 internal evaluation. "
        "Repeat runs preserve edits in this package's working files; the earlier team files remain untouched.\n").encode("utf-8")
    summary = {"schema_version": VERSION, "status": "case_and_scope_recommendations_ready_for_team_decisions",
        "decision_sheet_id": sheet_id, "package_directory": relative, "notes_path": relative + "/review_decisions.html",
        "working_directory": relative + "/working", "recommended_case_versions": 200,
        "source_linked_skill_examples": 150, "material_goal_changes_recommended": 11,
        "conditioning_coverage_in_recommended_case_set": 0, "direct_direction_change_examples_replaced": 12,
        "earlier_court_facts_reconciled": 8, "public_case_versions_changed_from_step33_3": len(amendments),
        "challenge_cases_preserved": 50, "verified_food_answers_preserved": 20,
        "family_recommendations": len(family_choices["case_family_recommendations"]),
        "team_review": "pending", "cases_accepted": 0, "scope_choice_adopted": False,
        "family_choices_adopted": False, "new_model_calls": 0, "final_planner_execution_authorized": False,
        "summary_path": "results/step33_case_decision_sheet_summary.json"}
    receipt = {**identity, "decision_sheet_id": sheet_id, "package_directory": relative,
        "files": {name: digest(data) for name, data in immutable.items()}, "mutable_directory": "working/",
        "accepted_cases": 0, "final_planner_execution_authorized": False}
    files = {**immutable, "manifest.json": packed(receipt), "summary.json": packed(summary)}
    for name, data in files.items():
        if (folder / name).exists():
            require((folder / name).read_bytes() == data, "An immutable decision-sheet file differs: " + name)
    for name, data in files.items():
        save_once(folder / name, data)
    for name in ("team_decisions", "project_decisions"):
        working = folder / "working" / (name + ".csv")
        if not working.exists():
            save_once(working, immutable[name + "_TEMPLATE.csv"])
    load_resolution(root)
    for path, expected in source["bindings"].items():
        require(digest((root / path).read_bytes()) == expected, "An original source changed during preparation.")
    save_once(root / summary["summary_path"], packed(summary))
    return summary
