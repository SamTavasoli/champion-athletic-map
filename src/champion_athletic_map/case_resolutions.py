"""Prepare private, versioned case proposals without adopting or running them."""

from copy import deepcopy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from itertools import combinations

VERSION = "final-case-resolution-proposals-1"
CORRECTION_ID = "331ea7ad69567f8f6472045a4da9abf41bcacd6b84eec788dd54fcf385e44976"
CORRECTION_MANIFEST_SHA256 = "bf081aca57d00a260bf6f1dc55d7fee485696b886d186f9917465f01d59bfaca"
CORRECTION_RELATIVE = "results/final_case_review/review_cb1efb8523e7c29384d3/corrections_331ea7ad69567f8f6472"
COACH_FACT = " One other person included in this headcount is an adult basketball coach available throughout all listed windows to give movement cues."


def require(condition, message):
    if not condition:
        raise ValueError(message)


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_module(root, filename):
    path = Path(root) / "src/champion_athletic_map" / filename
    spec = importlib.util.spec_from_file_location("case_resolution_" + path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def lines(path):
    return [json.loads(line) for line in Path(path).read_bytes().splitlines() if line.strip()]


def jsonl(rows):
    return b"".join(json.dumps(row, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
                    for row in rows)


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def save_once(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == data, "A saved review file has local changes and was preserved: " + str(path))
    else:
        with path.open("xb") as handle:
            handle.write(data)


def load_corrections(root):
    root = Path(root).resolve()
    folder = root / CORRECTION_RELATIVE
    manifest_path = folder / "manifest.json"
    require(manifest_path.is_file() and sha(manifest_path.read_bytes()) == CORRECTION_MANIFEST_SHA256,
            "The completed, uploaded Step 33-2 package is required.")
    manifest = json.loads(manifest_path.read_bytes())
    require(manifest["correction_id"] == CORRECTION_ID and manifest["injected_test_dependencies"] is False
            and manifest["accepted_cases"] == 0 and manifest["final_planner_execution_authorized"] is False,
            "The source corrections are not the reviewed proposal version.")
    for name, expected in manifest["files"].items():
        path = (folder / name).resolve()
        require(path.is_relative_to(folder), "A correction path leaves its review folder.")
        require(path.is_file() and sha(path.read_bytes()) == expected, "A saved correction changed: " + name)
    profiles = lines(folder / "proposed_public_profiles.jsonl")
    register = lines(folder / "correction_register.jsonl")
    require(len(profiles) == len(register) == 200 and len({r["profile_id"] for r in profiles}) == 200,
            "The source correction population is incomplete.")
    food = json.loads((folder / "private_food_expectations.json").read_bytes())
    require(food["requested_cases"] == food["verified_cases"] == food["runtime_ready_cases"] == 20,
            "The verified food evidence is incomplete.")
    return folder, manifest, profiles, register, food


def validate_population(originals, previous, proposed, metadata, permitted_changes):
    """Keep identity, challenge facts and food questions separate from private evidence."""
    old = {r["profile_id"]: r for r in previous}
    new = {r["profile_id"]: r for r in proposed}
    original = {r["profile_id"]: r for r in originals}
    require(len(new) == len(proposed) == 200 and new.keys() == old.keys() == original.keys(),
            "The proposed population changed case identities or size.")
    changes = []
    challenge_count = 0
    for pid, record in new.items():
        before = old[pid]
        require(set(record) == set(before) and record["schema_version"] == before["schema_version"],
                "A proposed activity amendment changed the public wrapper.")
        require(set(record["input"]) == set(before["input"]),
                "Private evidence or a new property entered the public input.")
        fields = {key for key in before["input"] if before["input"][key] != record["input"][key]}
        require(fields <= permitted_changes.get(pid, set()), "A public change has no explicit authoring proposal.")
        require(record["input"].get("food_question") == before["input"].get("food_question"),
                "An activity decision changed a verified food question.")
        require(record["input"].get("goals") == before["input"].get("goals"),
                "A primary proposal changed the goal; a material alternative must remain separate.")
        if "athlete_request" in fields:
            require(record["input"]["athlete_request"] == before["input"]["athlete_request"] + COACH_FACT,
                    "The task text changed beyond the explicitly recorded coach-resource fact.")
        if metadata[pid]["scenario_intent"] != "feasible":
            require(record == before, "A challenge case changed during activity preparation.")
            challenge_count += 1
        if fields:
            changes.append({"profile_id": pid, "previous_record_sha256": sha(packed(before)),
                "proposed_record_sha256": sha(packed(record)),
                "public_field_changes": [{"field": "/input/" + key, "previous": before["input"][key],
                                         "proposed": record["input"][key]} for key in sorted(fields)],
                "origin": "explicit_new_fictional_resource_authoring_proposal",
                "team_decision": None, "applied_to_original_source": False})
    require(challenge_count == 50, "The 50 challenge cases were not preserved.")
    return changes


def make_decisions(profiles, metadata, activities, families):
    activity_by_id = {row["profile_id"]: row for row in activities["cases"]}
    family_by_id = {row["profile_id"]: row for row in families["all_case_family_proposals"]}
    return [{"profile_id": record["profile_id"], "proposed_record_sha256": sha(packed(record)),
        "proposed_category": metadata[record["profile_id"]]["scenario_intent"],
        "activity_proposal": activity_by_id.get(record["profile_id"], {}).get("status", "challenge_case_preserved"),
        "suggested_family_id": family_by_id[record["profile_id"]]["suggested_family_id"],
        "activity_choice": "", "resource_fact_decision": "", "rule_witness_decision": "",
        "food_decision": "", "relationship_decision": "", "prepared_by": "", "reviewed_by": "",
        "team_decision": "", "notes": ""} for record in profiles]


def execute(root, emit=print):
    root = Path(root).resolve()
    require("/results/final_case_review/" in (root / ".gitignore").read_text(encoding="utf-8-sig").splitlines(),
            "The private review-folder exclusion is required.")
    source = load_module(root, "case_corrections.py").load_package(root)
    return prepare_from_verified_source(root, source, emit=emit)


def prepare_from_verified_source(root, source, emit=print):
    """Build the proposals after the native entry point verifies its source package."""
    root = Path(root).resolve()
    correction_folder, correction_manifest, previous, register, food = load_corrections(root)
    activity_helper = load_module(root, "activity_resolutions.py")
    relationship_helper = load_module(root, "case_relationship_proposals.py")
    rule_helper = load_module(root, "case_rule_review.py")
    screen_helper = load_module(root, "family_reconciliation.py")
    report_helper = load_module(root, "case_resolution_report.py")
    # The builders work only with the bound private cases and approved source snapshots.
    activities = activity_helper.build_activity_resolutions(correction_folder, source["package_root"],
        root / "src/champion_athletic_map/activity_screening.py")
    activities = retain_earlier_examples(previous, activities, correction_folder)
    proposed, allowed = assemble_profiles(previous, activities)
    amendments = validate_population(source["profiles"], previous, proposed, source["metadata"], allowed)
    from jsonschema import Draft202012Validator, FormatChecker
    public_schema = root / "artifacts/pilot/case_review_794f10d9d10a5fde/public_profile_schema.json"
    validator = Draft202012Validator(json.loads(public_schema.read_bytes()), format_checker=FormatChecker())
    for record in proposed:
        validator.validate(record)
    rules = rule_helper.build_rule_review(source["package_root"], correction_folder, public_profiles=proposed)
    scratch_parent = source["package_root"] / "resolution_work"
    scratch_parent.mkdir(exist_ok=True)
    emit("Checking the proposed activities and case relationships…")
    with TemporaryDirectory(prefix="review_", dir=scratch_parent) as scratch:
        families = relationship_helper.prepare_relationship_proposals(source["package_root"], correction_folder,
            root, scratch, profiles_override=proposed,
            compare_populations=screen_helper.compare_populations)
    generator = relationship_helper.module(root / screen_helper.PROTECTED / "protected_generator.py", "resolution_pair_screen")
    families["fresh_candidate_candidate_screen"] = compare_current_candidates(proposed, generator)
    families["summary"]["current_candidate_candidate_flags"] = len(families["fresh_candidate_candidate_screen"]["flagged_pairs"])
    require({row["profile_id"]: row["candidate_record_sha256"] for row in families["all_case_family_proposals"]}
            == {row["profile_id"]: sha(packed(row)) for row in proposed},
            "A family proposal used a stale public-case hash.")
    # These proposals have no runtime or acceptance side effect.
    return save_package(root, source, correction_manifest, previous, proposed, register,
                        food, activities, amendments, rules, families, report_helper)


def assemble_profiles(previous, activities):
    by_id = {row["profile_id"]: row for row in activities["cases"]}
    allowed = {}
    proposed = []
    permitted = {"/input/participants_available", "/input/space", "/input/equipment", "/input/athlete_request"}
    for before in previous:
        pid = before["profile_id"]
        activity = by_id.get(pid)
        if activity is None or activity.get("proposed_public_record") is None:
            proposed.append(deepcopy(before))
            continue
        record = deepcopy(before)
        seen = set()
        for patch in activity["patches"]:
            require(patch["op"] == "replace" and patch["path"] in permitted
                    and patch["path"] not in seen and patch["applied_to_source"] is False,
                    "An activity patch is not a reviewed resource replacement.")
            seen.add(patch["path"])
            key = patch["path"].split("/")[-1]
            require(record["input"][key] == patch["old"], "The activity amendment has a stale previous value.")
            record["input"][key] = deepcopy(patch["new"])
        require(record == activity["proposed_public_record"], "An activity proposal contains unrecorded input edits.")
        allowed[pid] = {path.split("/")[-1] for path in seen}
        proposed.append(record)
    return proposed, allowed


def retain_earlier_examples(previous, activities, folder):
    result = deepcopy(activities)
    old = {r["profile_id"]: r for r in previous}
    options = json.loads((folder / "activity_options.json").read_bytes())
    retained = [row for row in options["cases"] if row.get("selected_example")]
    require(len(retained) == 49 and len(result["cases"]) == 101
            and not ({r["profile_id"] for r in retained} & {r["profile_id"] for r in result["cases"]}),
            "The activity proposals do not join the earlier 49 examples.")
    for row in retained:
        pid = row["profile_id"]
        result["cases"].append({"profile_id": pid, "status": "earlier_source_linked_example_retained",
            "proposed_public_record": deepcopy(old[pid]), "patches": [],
            "private_witness": {"earlier_selected_example": row["selected_example"],
                "earlier_source_candidate_options": row["candidate_options"],
                "remaining_decisions": row["remaining_decisions"]},
            "approved": False, "team_review_status": "pending",
            "full_case_feasibility_proved": False})
    require(len({r["profile_id"] for r in result["cases"]}) == 150, "The activity proposal IDs are not unique.")
    result["cases"].sort(key=lambda r: r["profile_id"])
    result["summary"].update({"total_planning_cases": 150, "earlier_examples_retained": 49,
                              "total_source_linked_activity_proposals": 139})
    return result


def compare_current_candidates(profiles, helper):
    prepared = [(r, helper.comparison_view(r)) for r in sorted(profiles, key=lambda r: r["profile_id"])]
    pairs = []
    for (left, lv), (right, rv) in combinations(prepared, 2):
        exact = left["input"] == right["input"]
        finding = helper.compare_views(lv, rv, left["input"].get("athlete_request", ""),
                                       right["input"].get("athlete_request", ""), exact_full_input=exact)
        if finding is not None:
            pairs.append({"left_profile_id": left["profile_id"], "right_profile_id": right["profile_id"],
                "left_record_sha256": sha(packed(left)), "right_record_sha256": sha(packed(right)),
                "original_screen_findings": finding, "exact_full_input": exact,
                "adopted_family_id": None, "team_decision": None})
    require(not any(row["exact_full_input"] for row in pairs),
            "New resource proposals created a complete duplicate; preserve the proposals for a separate case decision.")
    return {"screen_version": helper.SCREEN_VERSION, "comparisons": len(profiles) * (len(profiles) - 1) // 2,
        "flagged_pairs": pairs, "meaning": "Fresh similarity evidence for the amended population; no ancestry, family or independence decision is adopted."}


def save_package(root, source, correction_manifest, previous, proposed, register,
                 food, activities, amendments, rules, families, report_helper):
    identity = {"schema_version": VERSION, "source_correction_id": CORRECTION_ID,
        "source_correction_manifest_sha256": CORRECTION_MANIFEST_SHA256,
        "source_package_id": source["manifest"]["package_id"],
        "source_hashes": {name: sha((root / "src/champion_athletic_map" / name).read_bytes()) for name in
            ("case_resolutions.py", "activity_resolutions.py", "case_relationship_proposals.py",
             "case_rule_review.py", "case_resolution_report.py")},
        "proposed_population_sha256": sha(jsonl(proposed)), "activity_proposals_sha256": sha(packed(activities)),
        "relationship_proposals_sha256": sha(packed(families)), "rule_review_sha256": sha(packed(rules))}
    resolution_id = sha(packed(identity))
    relative = source["package_root"].relative_to(root).as_posix() + "/resolutions_" + resolution_id[:20]
    folder = root / relative
    previous_by_id = {r["profile_id"]: r for r in previous}
    private_register = [{"profile_id": r["profile_id"],
        "previous_correction_record_sha256": sha(packed(previous_by_id[r["profile_id"]])),
        "current_proposed_record_sha256": sha(packed(r)), "proposed_category": source["metadata"][r["profile_id"]]["scenario_intent"],
        "origin": "resource_authoring_proposal" if previous_by_id[r["profile_id"]] != r else "earlier_case_proposal_retained",
        "earlier_schedule_proposal_remains_unaccepted": True, "accepted_case": False,
        "prepared_by": None, "reviewed_by": None, "team_decision": None,
        "authorized_for_model_use": False} for r in proposed]
    immutable = {"proposed_public_profiles.jsonl": jsonl(proposed), "current_case_register.jsonl": jsonl(private_register),
        "activity_resolution_proposals.json": packed(activities), "resource_amendments.json": packed(amendments),
        "private_rule_review.json": packed(rules), "family_resolution_proposals.json": packed(families),
        "private_food_expectations.json": (root / CORRECTION_RELATIVE / "private_food_expectations.json").read_bytes(),
        "case_resolutions.html": report_helper.render(proposed, source["metadata"], activities, amendments,
                                                       rules, families, food, register),
        "team_decisions_TEMPLATE.csv": csv_bytes(make_decisions(proposed, source["metadata"], activities, families))}
    require(sha(immutable["private_food_expectations.json"]) == correction_manifest["files"]["private_food_expectations.json"],
            "Verified food evidence changed during preparation.")
    immutable["README.md"] = ("# Step 33-3 — Case decisions\n\nOpen case_resolutions.html and review working/team_decisions.csv. "
        "We retained 49 earlier activity examples and prepared 90 further source-linked proposals: seven use existing facts; "
        "83 propose explicit fictional resource facts. The 11 original conditioning requests remain held. Their optional "
        "goal changes are unselected and excluded from proposed_public_profiles.jsonl. All 50 challenge cases and the "
        "20 verified food expectations are preserved. No original case is edited.\n\n"
        "The proposed case file includes the 83 resource amendments for review; it is not an accepted or frozen model input. "
        "Goal relevance, source skill prerequisites, resource allocations and accepted full witnesses still need case-level decisions. "
        "The short source-base examples establish proposed actions, not an effective complete training program. "
        "Conditional numeric bounds cover only the applicable weekly basketball minutes/rest limits and depend on accepted complete coverage; "
        "they do not certify all29 rules, concurrent-sport suitability or model responses.\n\n"
        "The relationship report exact-replays the original authoring records, retains all618 historical flags, and rescreens "
        "the amended population. It proposes distinct authored bases while retaining shared design dependence and nine incomplete "
        "legacy-source comparisons. No family, independence or exclusion decision is adopted. The sampling-family rationale must be "
        "recorded before freezing.\n\n"
        "Record actual preparation and review by a distinct teammate before acceptance. Existing Step33-1/2 working decisions "
        "remain untouched; repeat runs preserve this working CSV too. A separate accepted export, complete common scoring checks "
        "and final protocol are required before final planner execution. Private witnesses, food answers, categories, masks and "
        "family evidence never enter prompts, RAG or Version4 internal evaluation. No model calls are made here.\n").encode("utf-8")
    summary = {"schema_version": VERSION, "status": "concrete_case_proposals_prepared_for_team_review",
        "resolution_id": resolution_id, "package_directory": relative,
        "notes_path": relative + "/case_resolutions.html", "working_directory": relative + "/working",
        "cases_prepared": 200, "source_linked_activity_proposals": 139, "planning_cases": 150,
        "new_activity_proposals_using_existing_facts": 7, "fictional_resource_amendments_proposed": len(amendments),
        "conditioning_cases_held": 11, "optional_goal_changes_selected": 0, "challenge_cases_preserved": 50,
        "verified_food_answers_preserved": food["verified_cases"],
        "conditional_numeric_rule_bounds_supported": rules["summary"]["cases_with_conditional_numeric_bounds_supported"],
        "case_family_rationales_prepared": len(families["all_case_family_proposals"]),
        "current_development_flagged_cases": families["summary"]["current_flagged_cases_reviewed"],
        "historical_flags_preserved": families["summary"]["prior_flag_rows_preserved_and_reviewed"],
        "legacy_complete_source_comparisons_unresolved": families["summary"]["unresolved_legacy_complete_source_comparisons"],
        "team_review": "pending", "cases_accepted": 0, "family_adoptions": 0,
        "new_model_calls": 0, "final_planner_execution_authorized": False,
        "summary_path": "results/step33_case_resolution_summary.json"}
    require(len(amendments) == 83 and len(private_register) == 200, "The prepared proposal counts changed.")
    manifest = {**identity, "resolution_id": resolution_id, "package_directory": relative,
        "files": {name: sha(data) for name, data in immutable.items()}, "mutable_directory": "working/",
        "accepted_cases": 0, "final_planner_execution_authorized": False}
    # Check all existing immutable destinations before creating anything.
    for name, data in {**immutable, "manifest.json": packed(manifest), "summary.json": packed(summary)}.items():
        if (folder / name).exists():
            require((folder / name).read_bytes() == data, "An existing immutable resolution differs: " + name)
    for name, data in {**immutable, "manifest.json": packed(manifest), "summary.json": packed(summary)}.items():
        save_once(folder / name, data)
    working = folder / "working/team_decisions.csv"
    if not working.exists():
        save_once(working, immutable["team_decisions_TEMPLATE.csv"])
    for name, expected in source["bindings"].items():
        require(sha((root / name).read_bytes()) == expected, "An original case source changed during preparation.")
    load_corrections(root)
    save_once(root / summary["summary_path"], packed(summary))
    return summary
