"""Prepare versioned case corrections and private expected-answer evidence."""

from copy import deepcopy
import csv
from decimal import Decimal
import hashlib
import html
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys

VERSION = "final-case-correction-proposals-1"
PACKAGE_ID = "cb1efb8523e7c29384d37fe6a9797b652b2205309ed836a44c96578d636914ac"
MANIFEST_SHA256 = "e1eff9244ca89d164dca1439ca0e10c5a9ff2d906ac9104d427bb9776dd85324"
CATEGORIES = {"feasible": "plan", "missing_information": "clarification",
              "conflicting_constraints": "constraint_conflict", "outside_scope": "outside_scope"}


def require(value, message):
    if not value:
        raise ValueError(message)


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def jsonl(values):
    return b"".join((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8") for value in values)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def path_for(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative, "Invalid correction source path.")
    value = PurePosixPath(relative)
    require(not value.is_absolute() and value.as_posix() == relative and not set(value.parts) & {".", ".."}, "Invalid correction source path.")
    path = root / relative
    require(path.resolve() == path and path.is_file(), "Missing or linked correction source: " + relative)
    return path


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON field in case evidence.")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("Nonfinite JSON value.")))


def save_once(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == data, "A saved correction file changed: " + str(path))
    else:
        with path.open("xb") as handle:
            handle.write(data)


def load_package(root):
    summary = read(path_for(root, "results/step33_preparation_summary.json"))
    require(summary.get("schema_version") == "final-case-review-preparation-1"
            and summary.get("injected_test_dependencies") is False
            and summary.get("software_fixture") is not True
            and summary.get("status") == "review_package_prepared_not_accepted"
            and summary.get("review_cases") == 200
            and summary.get("final_planner_execution_authorized") is False,
            "The completed Step 33-1 review preparation is required.")
    manifest_path = path_for(root, summary["manifest_path"])
    require(sha(manifest_path.read_bytes()) == summary["manifest_sha256"] == MANIFEST_SHA256,
            "The reviewed case package changed.")
    manifest = read(manifest_path)
    require(manifest.get("package_id") == summary.get("package_id") == PACKAGE_ID,
            "This correction set belongs to a different review package.")
    package_root = manifest_path.parent
    bindings = {}
    for name, expected in manifest["files"].items():
        path = path_for(root, package_root.relative_to(root).as_posix() + "/" + name)
        require(sha(path.read_bytes()) == expected, "A reviewed case source changed: " + name)
        bindings[path.relative_to(root).as_posix()] = expected
    profiles = [json.loads(line) for line in (package_root / "source_public_profiles.jsonl").read_bytes().splitlines() if line.strip()]
    with (package_root / "source_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    metadata = {row["profile_id"]: row for row in rows}
    require(len(profiles) == len(metadata) == 200 and {row["profile_id"] for row in profiles} == set(metadata), "Candidate case IDs do not join.")
    for profile in profiles:
        require(sha(packed(profile)) == metadata[profile["profile_id"]]["record_sha256"], "A case input changed.")
    resources = read(package_root / "reference_snapshot/adopted_drills.json")
    return {"package_root": package_root, "manifest": manifest, "profiles": profiles,
            "metadata": metadata, "resources": resources, "bindings": bindings}


def propose_public_record(original, draft_category, *, food_question_amendment=None):
    require(draft_category in CATEGORIES and original.get("schema_version") == "athlete-profile-input-1", "Unexpected source case category or schema.")
    require("schedule_coverage" not in original["input"], "Existing schedule coverage needs a separate amendment.")
    proposed = deepcopy(original)
    proposed["schema_version"] = "athlete-profile-input-2"
    decisions = []
    if draft_category == "feasible":
        require(isinstance(original["input"].get("existing_commitments"), list), "A planning case with unknown commitments cannot be made complete automatically.")
        coverage = {**deepcopy(original["input"]["planning_window"]), "existing_commitments_complete": True}
        proposed["input"]["schedule_coverage"] = coverage
        decisions.append({"field": "/input/schedule_coverage", "source_value": "not_declared",
            "proposed_value": coverage, "origin": "new_explicit_fictional_authoring_proposal",
            "rationale": "To retain the intended planning scenario, propose that the listed fictional week is complete. This is a new case fact, not an inference from the old event list.",
            "team_decision": None})
        fact_origin = "new_fictional_fact_pending_team_review"
    else:
        proposed["input"]["schedule_coverage"] = None
        fact_origin = "unknown_preserved"
    if food_question_amendment is not None:
        question = original["input"].get("food_question")
        match = re.fullmatch(r'For the recorded food identity "([^"\r\n]+)", how many (grams of protein|kilocalories of energy) are listed for ([0-9]+(?:\.[0-9]+)?) g\?', question or "")
        require(match is not None, "Unsupported food question cannot be silently rewritten.")
        description, measure, grams = match.groups()
        expected = f'For the food "{description}", how many {measure} are recorded for {grams} g?'
        require(food_question_amendment == expected, "The food wording proposal changed a food identity, nutrient or quantity.")
        proposed["input"]["food_question"] = expected
        decisions.append({"field": "/input/food_question", "source_value": question,
            "proposed_value": expected, "origin": "runtime_compatible_wording_proposal",
            "rationale": "Use the existing structured-lookup question format while preserving the exact food identity, nutrient and quantity.", "team_decision": None})
    retained = deepcopy(proposed["input"])
    retained.pop("schedule_coverage")
    if food_question_amendment is not None:
        retained["food_question"] = original["input"]["food_question"]
    require(retained == original["input"], "A proposal silently changed an original case fact.")
    return {"profile_id": original["profile_id"], "source_record_sha256": sha(packed(original)),
        "proposed_record_sha256": sha(packed(proposed)), "proposed_public_record": proposed,
        "draft_category": draft_category, "proposed_expected_response": CATEGORIES[draft_category],
        "expected_response_status": "conditional_on_accepted_case_facts_and_required_evidence" if draft_category == "feasible" else "source_supported_proposal_not_yet_adopted",
        "schedule_fact_origin": fact_origin, "authoring_decisions": decisions,
        "approved": False, "authorized_for_model_use": False, "team_review_status": "pending",
        "prepared_by": None, "reviewed_by": None, "team_decision": None,
        "adopted_category": None, "adopted_family_id": None}


def load_helper(root, filename):
    path = path_for(root, "src/champion_athletic_map/" + filename)
    spec = importlib.util.spec_from_file_location("case_correction_" + path.stem, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


def execute(root, *, activity_path, emit=print, dependencies=None):
    root = Path(root).resolve()
    require(dependencies is None or not (set(dependencies) - {"food", "families"}), "Unexpected correction test dependency.")
    injected = dependencies is not None
    deps = dict(dependencies or {})
    source = load_package(root)
    ignore = path_for(root, ".gitignore").read_text(encoding="utf-8-sig")
    require("/results/final_case_review/" in ignore.splitlines(), "The private case-review directory needs its recorded repository exclusion.")
    activity = read(path_for(root, activity_path))
    return assemble_corrections(root, source, activity, activity_path, deps, injected, emit)


def minute(value):
    require(isinstance(value, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value), "Invalid witness clock value.")
    return int(value[:2]) * 60 + int(value[3:])


def source_elapsed_seconds(text):
    """Read one explicit elapsed dose; repetitions and qualified bouts stay unknown."""
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)(?:\s*[-–—]\s*([0-9]+(?:\.[0-9]+)?))?\s*(minutes?|mins?|seconds?|secs?)\s*", text or "", re.IGNORECASE)
    if match is None:
        return None
    lower = Decimal(match.group(1))
    upper = Decimal(match.group(2) or match.group(1))
    if not (0 < lower <= upper):
        return None
    return lower * (60 if match.group(3).lower().startswith("min") else 1)


def validate_activity_review(source, activity):
    require(activity.get("source_package_id") == source["manifest"]["package_id"], "Activity proposals belong to another case package.")
    indexed = {row["profile_id"]: row for row in activity["cases"]}
    expected = {identifier for identifier, row in source["metadata"].items() if row["scenario_intent"] == "feasible"}
    require(len(indexed) == len(activity["cases"]) == 150 and set(indexed) == expected, "Activity proposals do not cover the same 150 planning cases.")
    public = {row["profile_id"]: row["input"] for row in source["profiles"]}
    catalog = {row["catalog_candidate_id"]: row for row in source["resources"]["records"]}
    for identifier, row in indexed.items():
        require(row.get("approved") is False and row["source_record_sha256"] == source["metadata"][identifier]["record_sha256"], "An activity proposal changed its original case or approval status.")
        options = {item["catalog_candidate_id"]: item for item in row["candidate_options"]}
        require(len(options) == len(row["candidate_options"]) <= 3, "Activity proposal IDs are duplicated or unbounded.")
        for name, option in options.items():
            require(name in catalog and option.get("base_case_approval") is False, "An activity is not part of the approved source snapshot.")
            index = option.get("source_index")
            require(type(index) is int and 0 <= index < len(source["resources"]["records"])
                    and source["resources"]["records"][index]["catalog_candidate_id"] == name, "An activity source index does not resolve to its recorded ID.")
            for field, evidence in option["source_evidence"].items():
                require(field in catalog[name] and evidence["value"] == catalog[name][field]
                        and evidence["path"] == f"reference_snapshot/adopted_drills.json#/records/{index}/{field}", "An activity proposal changed a source fact or reference.")
        example = row.get("selected_example")
        if example is None:
            continue
        require(example.get("case_approved") is False and example.get("invented_rest_or_dose") is False, "An activity example claims unrecorded approval or dose.")
        slots = example["witness_slots"]
        current = public[identifier]
        request = current["athlete_request"]
        counts = re.findall(r"\b([12])\s+(?:additional|extra)\s+practice\s+blocks?\b", request)
        require(len(counts) == 1 and len(slots) == int(counts[0]), "An activity example changed the requested block count.")
        total, occupied = 0, []
        for slot in slots:
            name = slot["catalog_candidate_id"]
            require(name in options, "The example uses a base outside its evidence shortlist.")
            option = options[name]
            require(not option["hard_blockers"] and not option["unknown_conditions"], "The example silently assumes an unresolved resource requirement.")
            elapsed = option["elapsed_prescription"]
            require(elapsed.get("kind") == "single_explicit_elapsed_dose" and elapsed.get("calendar_minutes") == slot["duration_minutes"]
                    and slot["source_prescription"] == catalog[name]["source_prescription"], "The example invented elapsed time from repetitions, games or makes.")
            require(isinstance(elapsed.get("seconds"), (float, int)) and elapsed["seconds"] == slot["duration_minutes"] * 60,
                    "The source elapsed dose does not exactly match the calendar allocation.")
            source_seconds = source_elapsed_seconds(catalog[name]["source_prescription"])
            require(source_seconds is not None and source_seconds == Decimal(str(slot["duration_minutes"])) * 60,
                    "The source prescription does not support this elapsed allocation; repetitions, games and qualified doses stay unresolved.")
            start, end = minute(slot["start_time"]), minute(slot["end_time"])
            require(type(slot["duration_minutes"]) is int and end - start == slot["duration_minutes"] > 0, "The example has invalid elapsed time.")
            windows = [window for window in current["availability"] if window["date"] == slot["date"] and minute(window["start_time"]) <= start < end <= minute(window["end_time"])]
            require(windows, "An activity example is outside the available windows.")
            for event in current["existing_commitments"]:
                require(event["date"] != slot["date"] or end <= minute(event["start_time"]) or start >= minute(event["end_time"]), "An activity example overlaps an existing commitment.")
            require(all(date != slot["date"] or end <= left or start >= right for date, left, right in occupied), "Activity blocks overlap.")
            occupied.append((slot["date"], start, end))
            total += slot["duration_minutes"]
            cap = current["time_limits"].get("max_session_minutes")
            require(cap is None or slot["duration_minutes"] <= cap, "An activity example exceeds the session cap.")
        limits = current["time_limits"]
        require((limits.get("max_additional_minutes_per_week") is None or total <= limits["max_additional_minutes_per_week"])
                and (limits.get("max_additional_sessions_per_week") is None or len(slots) <= limits["max_additional_sessions_per_week"]), "An activity example exceeds a weekly cap.")
    return indexed


def csv_data(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def make_notes(proposals, activities, food, families):
    escape = lambda value: html.escape(str(value), quote=True)
    food_by_id = {row["profile_id"]: row for row in food["cases"]}
    cards = []
    for row in proposals:
        identifier = row["profile_id"]
        parts = ['<article><h2>' + escape(identifier) + '</h2><p><b>Proposed response:</b> ' + escape(row["proposed_expected_response"]) + ' · Team review pending</p>']
        if row["authoring_decisions"]:
            parts.append('<h3>Proposed case changes</h3><ul>' + ''.join('<li>' + escape(value["rationale"]) + '</li>' for value in row["authoring_decisions"]) + '</ul>')
        else:
            parts.append('<p>The challenge facts remain unchanged. Schedule coverage stays unknown.</p>')
        if identifier in activities:
            choice = activities[identifier]
            example = choice.get("selected_example")
            if example:
                parts.append('<h3>Source-linked activity example</h3><table><tr><th>Date</th><th>Time</th><th>Minutes</th><th>Approved source ID</th></tr>' + ''.join('<tr><td>' + escape(slot["date"]) + '</td><td>' + escape(slot["start_time"]) + '–' + escape(slot["end_time"]) + '</td><td>' + escape(slot["duration_minutes"]) + '</td><td>' + escape(slot["catalog_candidate_id"]) + '</td></tr>' for slot in example["witness_slots"]) + '</table><p>' + escape(example["qualification"]) + '</p>')
            else:
                parts.append('<p><b>Activity evidence still needed.</b> Review the source options and specific fact or allocation decisions below.</p>')
            parts.append('<details><summary>Activity options and remaining decisions</summary><pre>' + escape(json.dumps(choice, ensure_ascii=False, indent=2)) + '</pre></details>')
        if identifier in food_by_id:
            parts.append('<details><summary>Private food answer and runtime lookup check</summary><pre>' + escape(json.dumps(food_by_id[identifier], ensure_ascii=False, indent=2)) + '</pre></details>')
        parts.append('<details><summary>Proposed public record — not an accepted model input</summary><pre>' + escape(json.dumps(row["proposed_public_record"], ensure_ascii=False, indent=2)) + '</pre></details></article>')
        cards.append(''.join(parts))
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Step 33-2 — Case corrections</title><style>body{font:16px/1.6 system-ui,sans-serif;max-width:1100px;margin:30px auto;padding:0 20px;background:#f5f7f8;color:#172735}article,.panel{background:white;border:1px solid #d6e1e6;border-radius:9px;padding:24px;margin:22px 0}h1{font-size:32px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.5 monospace}details{padding:12px;border:1px solid #d6e1e6;border-radius:6px;margin:12px 0}summary{cursor:pointer;font-weight:600}table{border-collapse:collapse;width:100%}th,td{text-align:left;border-bottom:1px solid #ddd;padding:8px}input{font:inherit;padding:10px;width:95%}</style>'
        '<h1>Step 33-2 — Proposed case corrections</h1><section class="panel"><p>We prepared explicit schedule-coverage proposals for the 150 planning cases and preserved the 50 challenge cases. The 20 recorded-food questions use the existing lookup wording, with their identities, nutrients and quantities preserved.</p>'
        '<p><b>Food values verified:</b> ' + str(food["verified_cases"]) + '/' + str(food["requested_cases"]) + '. <b>Runtime lookups ready:</b> ' + str(food.get("runtime_ready_cases", 0)) + '/' + str(food["requested_cases"]) + '.</p><p>Activity examples are proposals with source-linked doses and known resource checks. They are not case approvals. Cases still needing facts or activity evidence remain visible.</p><p>Current development relationships were rechecked using the original screen. Its flags and the earlier 618 review leads remain proposals; families and exclusions have not been adopted.</p><p>Use <b>working/team_decisions.csv</b> for team decisions. This folder and its private food answers stay outside planner prompts and retrieval.</p><p><input id="find" placeholder="Find a case, source ID or issue" aria-label="Find a case"></p></section>'
        + ''.join(cards) + '<script>document.getElementById("find").addEventListener("input",function(){const q=this.value.toLowerCase();document.querySelectorAll("article").forEach(x=>x.hidden=!x.textContent.toLowerCase().includes(q));});</script></html>').encode("utf-8")


def assemble_corrections(root, source, activity, activity_path, deps, injected, emit):
    activities = validate_activity_review(source, activity)
    food_helper = None if "food" in deps else load_helper(root, "food_expectations.py")
    food_runner = deps.get("food") or food_helper.build_food_expectations
    emit("Checking the recorded food answers…")
    food = food_runner(root, source["profiles"])
    food_by_id = {row["profile_id"]: row for row in food["cases"]}
    expected_food_ids = {row["profile_id"] for row in source["profiles"] if row["input"].get("food_question")}
    require(len(food_by_id) == len(food["cases"]) == food["requested_cases"] == 20 and set(food_by_id) == expected_food_ids,
            "The food expectation records do not join the 20 case questions.")
    proposals = []
    for original in source["profiles"]:
        identifier = original["profile_id"]
        amendment = food_by_id.get(identifier, {}).get("proposed_runtime_question")
        require(identifier not in food_by_id or isinstance(amendment, str), "A food wording proposal is missing.")
        proposals.append(propose_public_record(original, source["metadata"][identifier]["scenario_intent"], food_question_amendment=amendment))
    public_versions = [row["proposed_public_record"] for row in proposals]
    family_runner = deps.get("families") or load_helper(root, "family_reconciliation.py").screen_families
    emit("Rechecking relationships with the current development cases…")
    families = family_runner(root, public_versions, source["package_root"])
    require(families.get("current_development_rescreen_completed") is True, "The current development relationship screen did not complete.")
    require({row["profile_id"] for row in families["case_proposals"]} == {row["profile_id"] for row in proposals}, "Family review does not cover the 200 cases.")
    proposed_hashes = {row["profile_id"]: row["proposed_record_sha256"] for row in proposals}
    require(len(families["case_proposals"]) == 200 and all(row.get("candidate_record_sha256") == proposed_hashes[row["profile_id"]]
            for row in families["case_proposals"]), "The relationship screen used a different case version.")
    identity = {"schema_version": VERSION, "source_package_id": source["manifest"]["package_id"],
        "source_file_sha256": source["bindings"], "activity_review_sha256": sha(packed(activity)),
        "food_source_bindings": food.get("source_bindings", {}), "family_source_bindings": families.get("source_file_sha256", {}),
        "injected_test_dependencies": injected, "source_hashes": {name: sha((root / "src/champion_athletic_map" / name).read_bytes()) for name in ("case_corrections.py", "food_expectations.py", "family_reconciliation.py")}}
    correction_id = sha(packed(identity))
    relative = source["package_root"].relative_to(root).as_posix() + "/" + ("software_fixture_" if injected else "") + "corrections_" + correction_id[:20]
    folder = root / relative
    examples = [{"profile_id": identifier, "example": row["selected_example"]} for identifier, row in activities.items() if row.get("selected_example")]
    immutable = {"proposed_public_profiles.jsonl": jsonl(public_versions), "correction_register.jsonl": jsonl(proposals),
        "activity_options.json": packed(activity), "source_linked_activity_examples.jsonl": jsonl(examples),
        "private_food_expectations.json": packed(food), "family_rescreen.json": packed(families),
        "correction_notes.html": make_notes(proposals, activities, food, families)}
    decisions = [{"profile_id": row["profile_id"], "source_record_sha256": row["source_record_sha256"],
        "proposed_record_sha256": row["proposed_record_sha256"], "proposed_category": row["draft_category"],
        "proposed_response_type": row["proposed_expected_response"], "schedule_authoring_decision": "", "activity_witness_decision": "",
        "food_expected_answer_decision": "", "family_decision": "", "prepared_by": "", "reviewed_by": "", "team_decision": "", "notes": ""} for row in proposals]
    immutable["team_decisions_TEMPLATE.csv"] = csv_data(decisions)
    immutable["README.md"] = ("# Step 33-2 — Proposed case corrections\n\nOpen correction_notes.html. We propose explicit new fictional schedule-completeness facts for the 150 planning cases; no old event list was treated as a completeness declaration. The 50 challenge cases retain their facts and unknown coverage. The 20 food-question wording proposals preserve food identity, nutrient and quantity while matching the existing lookup.\n\nSource-linked activity examples retain the recorded elapsed dose and stated requirements. Other cases list the facts, allocations or adaptations still needing review. No case or activity example is approved by this preparation. Private numerical food expectations and family findings are evaluation evidence, never planner inputs. Read each recorded status; an unavailable or ambiguous fact is not verified.\n\nUse working/team_decisions.csv to record team review. Its entries are preserved on repeat runs. Do not edit the immutable files. Existing Step 33-1 working files remain untouched. Team acceptance, complete case-level checks, final family decisions and the final protocol freeze remain separate. These proposed profiles are not authorized model inputs.\n").encode("utf-8")
    summary_path = "results/step33_2_fixture_summary.json" if injected else "results/step33_case_corrections_summary.json"
    summary = {"schema_version": VERSION, "status": "case_corrections_prepared_for_team_review", "correction_id": correction_id,
        "package_directory": relative, "notes_path": relative + "/correction_notes.html", "working_directory": relative + "/working",
        "cases_prepared": 200, "new_fictional_schedule_proposals": 150, "challenge_cases_preserved": 50,
        "food_question_wording_proposals": 20, "food_expected_values_verified": food["verified_cases"],
        "food_questions": food["requested_cases"], "food_runtime_ready": food.get("runtime_ready_cases", 0),
        "source_linked_activity_examples": len(examples), "activity_review_still_needed": 150 - len(examples),
        "family_screened_pairs": families["summary"]["screened_pairs"],
        "current_development_flagged_cases": families["summary"]["candidates_with_current_development_flags"],
        "team_approvals_created": 0, "final_planner_execution_authorized": False, "new_model_calls": 0,
        "injected_test_dependencies": injected, "summary_path": summary_path}
    manifest = {**identity, "correction_id": correction_id, "package_directory": relative,
        "files": {name: sha(data) for name, data in immutable.items()}, "mutable_directory": "working/",
        "accepted_cases": 0, "final_planner_execution_authorized": False}
    save_once(folder / "manifest.json", packed(manifest))
    for name, data in immutable.items():
        save_once(folder / name, data)
    working = folder / "working/team_decisions.csv"
    working.parent.mkdir(parents=True, exist_ok=True)
    if not working.exists():
        with working.open("xb") as handle:
            handle.write(immutable["team_decisions_TEMPLATE.csv"])
    for name, expected in source["bindings"].items():
        require(sha(path_for(root, name).read_bytes()) == expected, "A source case changed during preparation.")
    save_once(folder / "summary.json", packed(summary))
    save_once(root / summary_path, packed(summary))
    return summary
