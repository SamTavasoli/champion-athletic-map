"""Select the team response-review sample before final replies are generated."""

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import random

VERSION = "final-team-response-review-preparation-1"
CONTRACT_FOLDER = "artifacts/evaluation/human_review_9e637c0f3932c371"
CATEGORIES = ("feasible", "missing_information", "conflicting_constraints", "outside_scope")
DIMENSIONS = ("response_suitability", "profile_fit", "practicality_completeness", "evidence_accuracy", "clarity")
SLOT_IDS = ("reviewer-slot-A", "reviewer-slot-B")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def jsonl(rows):
    return b"".join(canonical(row) + b"\n" for row in rows)


def path_inside(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative,
            "A review dependency must be project-relative POSIX text.")
    parsed = PurePosixPath(relative)
    require(not parsed.is_absolute() and not set(parsed.parts) & {".", ".."} and parsed.as_posix() == relative,
            "A review dependency leaves the project.")
    result = root / relative
    require(result.resolve() == result, "A review dependency has an unexpected linked location.")
    return result


def load_review_contract(root, expected_bindings):
    """Read only the frozen review contract, not its unrelated classifier inputs."""
    root = Path(root).resolve()
    names = ("human_review_config.json", "human_rating_entry_schema.json", "human_review_rubric.md")
    values, bindings = {}, {}
    for name in names:
        relative = CONTRACT_FOLDER + "/" + name
        digest = expected_bindings.get(relative)
        require(isinstance(digest, str), "The frozen team-review contract binding is missing: " + name)
        data = path_inside(root, relative).read_bytes()
        require(sha(data) == digest, "A frozen team-review contract changed: " + name)
        bindings[relative] = digest
        values[name] = data
    config = json.loads(values["human_review_config.json"])
    validate_contract(config)
    return {"config": config, "rating_entry_schema": json.loads(values["human_rating_entry_schema.json"]),
            "source_bindings": bindings, "rubric_sha256": bindings[CONTRACT_FOLDER + "/human_review_rubric.md"]}


def validate_contract(config):
    require(isinstance(config, dict), "The frozen team-review contract is required.")
    sample = config.get("planned_review_sample") or {}
    require(sample.get("profiles") == 40 and sample.get("profiles_per_age") == 8
        and sample.get("ages") == list(range(13, 18))
        and sample.get("per_age_categories") == {"feasible": 5, "missing_information": 1, "conflicting_constraints": 1, "outside_scope": 1}
        and sample.get("independent_reviewers_per_response") == 2
        and sample.get("planner_versions") == 4 and sample.get("initial_sampling_seed") == 42,
        "The accepted team-review sample definition has changed.")
    dimensions = config.get("dimensions")
    require(isinstance(dimensions, list) and tuple(row.get("id") for row in dimensions) == DIMENSIONS
        and all(isinstance(row.get("anchors"), list) and len(row["anchors"]) == 3
                and all(isinstance(anchor, str) and anchor for anchor in row["anchors"]) for row in dimensions),
        "The accepted five-dimension review rubric has changed.")
    require(config.get("score_values") == [0, 1, 2]
        and config.get("combined_quality_score") is None and config.get("new_passing_threshold") is None,
        "The team-review scale or threshold policy has changed.")


def select_sample(profiles, annotations, *, seed=42):
    """Choose within public-age/private-category strata before inspecting responses."""
    require(type(seed) is int and seed == 42, "The recorded review sampling seed is 42.")
    require(isinstance(profiles, list) and isinstance(annotations, list)
        and len(profiles) == len(annotations) == 200, "The frozen 200-case roster is required.")
    records = {row["profile_id"]: row for row in profiles}
    notes = {row["profile_id"]: row for row in annotations}
    require(len(records) == len(notes) == 200 and records.keys() == notes.keys(), "The review case rosters differ.")
    for pid, record in records.items():
        require(set(record) == {"profile_id", "schema_version", "input"}, "Private case fields entered the public review input.")
        require(notes[pid].get("case_authoring_accepted") is True
            and notes[pid].get("public_record_sha256") == sha(packed(record))
            and notes[pid].get("case_category") in CATEGORIES
            and isinstance(notes[pid].get("family_id"), str), "A review case lacks its exact accepted authoring annotation.")
    rng, selected = random.Random(seed), []
    for age in range(13, 18):
        for category in CATEGORIES:
            candidates = sorted(pid for pid, record in records.items()
                if record["input"].get("age") == age and notes[pid]["case_category"] == category)
            required = 5 if category == "feasible" else 1
            require(len(candidates) >= required, "A required age/category review stratum is too small.")
            for pid in rng.sample(candidates, required):
                selected.append({"profile_id": pid, "age": age, "case_category": category,
                    "family_id": notes[pid]["family_id"], "public_record_sha256": sha(packed(records[pid]))})
    require(len(selected) == len({row["profile_id"] for row in selected}) == 40,
            "The team-review sample is not 40 distinct accepted profiles.")
    return selected


def neutral_rubric(config):
    lines = ["# Team response-review rubric", "", "We keep the five dimensions separate. Scores are 0, 1 or 2. No combined score or passing threshold is added.", "", "| Dimension | 0 | 1 | 2 |", "|---|---|---|---|"]
    for row in config["dimensions"]:
        lines.append("| " + " | ".join([row["name"], *row["anchors"]]) + " |")
    lines += ["", "Missing entries stay unscored. Only evidence accuracy may be not applicable, with a reason, when the reply contains no substantive factual or instructional claim. An omitted requested fact still affects completeness.", "", "We rate readable replies exactly as returned, including wrong or malformed replies. A wrong answer can still be clear. Executed empty or uninterpretable replies receive zero for the four non-evidence dimensions under the rubric; unfinished jobs stay pending. This preparation does not enter any ratings.", "", "Two actual teammates rate independently after development practice. Initial ratings are locked before discussion, and any consensus is stored separately. Reviewer identities and calibration are still pending. Case-choice approval did not complete or waive these response ratings.", "", "We judge the request that was actually made. A relevant clarification, conflict explanation or scope response need not invent a training calendar. We review substantive claims even when citations are absent, and distinguish an unsupported claim from a contradicted one.", "", "We report each dimension separately, with exact agreement and linearly weighted Cohen's kappa using the fixed 0/1/2 order. Missing and not-applicable states remain outside the numeric scale. Undefined agreement statistics stay unavailable with a reason.", "", "The sample deliberately includes challenge cases. Its ratings do not represent a random sample of all 800 planned jobs. Workflow labels and check results are withheld, although complete blinding cannot be guaranteed.", ""]
    return "\n".join(lines).encode("utf-8")


def prepare_components(profiles, annotations, planned_jobs, review_config, *, case_freeze_id, reference_access):
    """Return pending review files without reading model outputs or assigning people."""
    validate_contract(review_config)
    require(isinstance(case_freeze_id, str) and case_freeze_id, "The accepted case freeze identity is required.")
    require(isinstance(reference_access, list), "Neutral reference access must be declared separately.")
    require(all(isinstance(row, dict) and set(row) <= {"label", "path", "sha256", "source_url", "description"}
        and isinstance(row.get("label"), str) and row["label"] for row in reference_access),
        "Reference access contains an unexpected field or no neutral label.")
    selected = select_sample(profiles, annotations)
    require(len(planned_jobs) == len({row["job_id"] for row in planned_jobs}) == 800,
            "The complete paired final job roster is required.")
    require(all(row.get("execution_state") == "not_started" and row.get("designated_final_outcome") is None
        for row in planned_jobs), "The team-review sample must be selected before final outputs.")
    jobs = {(row["profile_id"], row["planner_version"]): row for row in planned_jobs}
    require(len(jobs) == 800, "The paired job roster repeats a profile/version combination.")
    records = {row["profile_id"]: row for row in profiles}
    require(set(jobs) == {(pid, version) for pid in records for version in range(1, 5)},
            "The planned review roster differs from the complete four-version case roster.")
    require(all(job.get("public_record_sha256", sha(packed(records[pid]))) == sha(packed(records[pid]))
        for (pid, _version), job in jobs.items()), "A planned review job refers to an earlier public case version.")
    key, forms = [], []
    rng = random.Random(42)
    pairs = [(row["profile_id"], version) for row in selected for version in range(1, 5)]
    rng.shuffle(pairs)
    for position, (pid, version) in enumerate(pairs, 1):
        require((pid, version) in jobs, "A sampled case is missing one of its four planned outcomes.")
        identifier = "response-" + sha(canonical({"case_freeze_id": case_freeze_id, "position": position,
            "masking_purpose": "team-response-review-v1"}))[:20]
        key.append({"response_id": identifier, "profile_id": pid, "planner_version": version,
            "job_id": jobs[(pid, version)]["job_id"], "public_record_sha256": sha(packed(records[pid])),
            "designated_outcome_sha256": None, "response_text_sha256": None})
        forms.append({"response_id": identifier, "athlete_input": deepcopy(records[pid]["input"]),
            "response_state": "pending_final_outcome", "response_text": None, "response_citations": None})
    templates = []
    assignments = []
    for slot in SLOT_IDS:
        order = [row["response_id"] for row in forms]
        rng.shuffle(order)
        assignments.append({"reviewer_slot_id": slot, "assigned_reviewer_id": None,
            "assigned_reviewer_name": None, "independent_reviewer_verified": False,
            "calibration_state": "not_completed", "presentation_order": order,
            "initial_ratings_locked": False})
        for response_id in order:
            for dimension in DIMENSIONS:
                templates.append({"response_id": response_id, "reviewer_slot_id": slot,
                    "reviewer_id": None, "dimension": dimension, "rating_status": "missing",
                    "score": None, "comment": None, "not_applicable_reason": None,
                    "evidence_refs": [], "template_only": True})
    summary = {"schema_version": VERSION, "sample_profiles": 40, "planned_response_forms": 160,
        "planned_independent_reviews": 320, "planned_dimension_entries": 1600,
        "sampling_seed": 42, "sample_chosen_before_final_outputs": True,
        "actual_assigned_reviewers": 0, "reviewer_identities_pending": True,
        "development_calibration_completed": False, "development_calibration_selection": "pending",
        "actual_response_ratings": 0, "initial_ratings_locked": False,
        "neutral_reference_access_declared": bool(reference_access),
        "packet_setup_prepared": True, "response_packets_populated": False,
        "team_response_review_ready_to_rate": False, "final_review_complete": False,
        "actual_team_review_claimed": False, "model_calls": 0}
    definition = {"schema_version": VERSION, "case_freeze_id": case_freeze_id,
        "review_config_sha256": sha(packed(review_config)), "sampling_seed": 42,
        "sampling_recipe": "Ascending ages13through17; category order feasible,missing_information,conflicting_constraints,outside_scope; sort opaqueIDs within each stratum and sample without replacement with one random.Random(42).",
        "sample_composition": {"feasible": 25, "missing_information": 5, "conflicting_constraints": 5, "outside_scope": 5},
        "reviewer_slots": list(SLOT_IDS), "reviewer_slots_are_people": False,
        "all_four_planner_outcomes_included": True, "masking_is_complete_guarantee": False,
        "source_rows_or_private_categories_in_public_forms": False,
        "response_binding_policy": "Fill only from each job's designated saved terminal outcome; preserve exact reply text and citations, including malformed readable replies. Do not substitute earlier drafts.",
        "rating_activation_policy": "Assign two distinct actual teammates, complete development practice, bind the designated replies, and verify neutral reference access before accepting ratings. Keep the initial independent exports locked before discussion; consensus separate.",
        "goal_ratings_are_automatic_goal_verification": False,
        "case_approval_waives_response_review": False,
        "response_ratings_do_not_change_the_frozen_automated_primary_definition": True,
        "private_files": ["private_review_sample.jsonl", "private_response_key.jsonl", "private_reviewer_assignments.json"],
        "public_packet_files": ["review_forms_pending.jsonl", "review_rubric.md", "reference_access.json"],
        "template_files_are_actual_ratings": False,
        "summary": summary}
    files = {"private_review_sample.jsonl": jsonl(selected), "private_response_key.jsonl": jsonl(key),
        "private_reviewer_assignments.json": packed(assignments), "review_forms_pending.jsonl": jsonl(forms),
        "rating_templates_pending.jsonl": jsonl(templates), "review_rubric.md": neutral_rubric(review_config),
        "reference_access.json": packed(reference_access), "review_preparation.json": packed(definition)}
    return {"files": files, "summary": summary, "definition": definition}
