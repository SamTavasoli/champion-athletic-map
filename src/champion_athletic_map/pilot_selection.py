"""Prepare a provisional development pilot without changing its public inputs."""

from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import random


SELECTION_VERSION = "step31-development-selection-1"
POOL_DIRECTORY = "results/profile_preparation/development_drafts_7b7f2fc781077cdc"
RETAINED_REVISION_DIRECTORY = "results/profile_preparation/development_revision_67aa5ba7a8169ba3"
SCHEMA_PATH = "artifacts/evaluation/profile_contract_d3addc8aa60b70ab/profile_input_schema.json"
QUOTAS = {
    13: {"feasible": 2, "missing_information": 1, "conflicting_constraints": 1},
    14: {"feasible": 2, "missing_information": 1, "outside_scope": 1},
    15: {"feasible": 2, "conflicting_constraints": 1, "outside_scope": 1},
    16: {"feasible": 2, "missing_information": 1, "conflicting_constraints": 1},
    17: {"feasible": 2, "missing_information": 1, "outside_scope": 1},
}
ORDERS = {"A": (1, 2, 4, 3), "B": (2, 3, 1, 4),
          "C": (3, 4, 2, 1), "D": (4, 1, 3, 2)}
PUBLIC_FIELDS = {"age", "athlete_request", "availability", "basketball_background", "equipment",
    "existing_commitments", "food_question", "goals", "history", "participants_available",
    "planning_window", "reported_limitations", "school_grade", "space", "time_limits"}
PRIVATE_FIELDS = {"family_id", "proposed_family_id", "partition", "scenario_category", "scenario_intent",
    "category_intent", "expected_response_type", "required_checks", "required_check_mask", "feasibility_record",
    "review_decisions", "source_lineage", "scenario_type", "scenario_note", "acceptance_status"}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _read_json(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate key in a preparation record.")
            value[key] = item
        return value

    def nonfinite(value):
        raise ValueError("Nonfinite number in a preparation record.")

    return json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)


def _validate_public(record):
    if (not isinstance(record, dict) or set(record) != {"profile_id", "schema_version", "input"}
            or record.get("schema_version") != "athlete-profile-input-1"
            or not isinstance(record.get("profile_id"), str) or not record["profile_id"].strip()
            or not isinstance(record.get("input"), dict) or set(record["input"]) - PUBLIC_FIELDS):
        raise ValueError("Expected the unchanged public profile record contract.")

    def inspect(value):
        if isinstance(value, dict):
            if set(value) & PRIVATE_FIELDS:
                raise ValueError("Private review information cannot enter a public profile.")
            for item in value.values():
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    inspect(record["input"])
    _canonical(record)
    age = record["input"].get("age")
    if type(age) is not int or age not in QUOTAS:
        raise ValueError("Pilot selection needs a reported age from 13 through 17.")


def load_pool(root):
    """Verify the existing 100 development drafts and return their separate metadata."""
    root = Path(root).resolve()
    folder = root / POOL_DIRECTORY
    summary_path = folder / "step16_development_drafts_summary.json"
    summary_bytes = summary_path.read_bytes()
    summary = _read_json(summary_bytes)
    if summary.get("development_drafts") != 100 or summary.get("status") != "development_drafts_prepared_review_pending":
        raise ValueError("The recorded 100-draft development pool is unavailable.")
    for relative, expected in summary["artifacts"].items():
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder.resolve()) or _sha(path.read_bytes()) != expected:
            raise ValueError("A development preparation artifact changed: " + relative)
    records = [_read_json(line) for line in (folder / "development_draft_inputs.jsonl").read_bytes().splitlines() if line.strip()]
    if len(records) != 100:
        raise ValueError("The development pool must retain its 100 recorded drafts.")
    for record in records:
        _validate_public(record)
    if len({record["profile_id"] for record in records}) != len(records):
        raise ValueError("Development profile IDs are duplicated.")
    revision_folder = root / RETAINED_REVISION_DIRECTORY
    revision_summary_path = revision_folder / "step16_development_revision_summary.json"
    revision_summary_bytes = revision_summary_path.read_bytes()
    revision_summary = _read_json(revision_summary_bytes)
    revision_relative = revision_summary_path.relative_to(root).as_posix()
    if (summary.get("parent_revision_digest") != revision_summary.get("revision_digest")
            or _sha(revision_summary_bytes) != summary["input_hashes"].get(revision_relative)):
        raise ValueError("The development pool's retained revision binding changed.")
    for relative, expected in revision_summary["artifacts"].items():
        path = (revision_folder / relative).resolve()
        if not path.is_relative_to(revision_folder.resolve()) or _sha(path.read_bytes()) != expected:
            raise ValueError("A retained development revision artifact changed: " + relative)
    revised = [_read_json(line) for line in (revision_folder / "development_draft_inputs.jsonl").read_bytes().splitlines() if line.strip()]
    indexed = {record["profile_id"]: record for record in records}
    if len(revised) != 7 or len({record["profile_id"] for record in revised}) != 7:
        raise ValueError("The recorded seven retained development revisions are unavailable.")
    if any(indexed.get(record["profile_id"]) != record for record in revised):
        raise ValueError("The expanded pool no longer preserves the seven revised public records.")
    with (folder / "development_draft_review_queue.csv").open(encoding="utf-8", newline="") as handle:
        metadata = list(csv.DictReader(handle))
    if (len(metadata) != 100 or len({row["profile_id"] for row in metadata}) != 100
            or {row["profile_id"] for row in metadata} != {row["profile_id"] for row in records}
            or any(row.get("partition") != "development" for row in metadata)):
        raise ValueError("The private development metadata does not match its public records.")
    schema_path = root / SCHEMA_PATH
    if _sha(schema_path.read_bytes()) != summary["input_hashes"][SCHEMA_PATH]:
        raise ValueError("The development public input schema changed.")
    from jsonschema import Draft202012Validator, FormatChecker
    validator = Draft202012Validator(_read_json(schema_path.read_bytes()), format_checker=FormatChecker())
    for record in records:
        validator.validate(record)
    provenance = {"pool_directory": POOL_DIRECTORY, "pool_records": 100,
        "pool_summary_sha256": _sha(summary_bytes),
        "public_pool_sha256": summary["artifacts"]["development_draft_inputs.jsonl"],
        "private_metadata_sha256": summary["artifacts"]["development_draft_review_queue.csv"],
        "public_schema_sha256": summary["input_hashes"][SCHEMA_PATH],
        "retained_revision_directory": RETAINED_REVISION_DIRECTORY,
        "retained_revision_summary_sha256": _sha(revision_summary_bytes),
        "retained_revision_public_sha256": revision_summary["artifacts"]["development_draft_inputs.jsonl"],
        "retained_revision_records_verified": 7,
        "source_status": summary["status"], "selection_version": SELECTION_VERSION}
    return {"public_records": records, "metadata": metadata, "provenance": provenance}


def _minute(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return None
    try:
        hour, minute = int(value[:2]), int(value[3:])
    except ValueError:
        return None
    return hour * 60 + minute if 0 <= hour < 24 and 0 <= minute < 60 else None


def _specificity(public):
    """Rank stated facts only; this is not a feasibility or medical assessment."""
    value = public["input"]
    windows = value.get("availability")
    valid_windows = (isinstance(windows, list) and all(isinstance(row, dict) for row in windows)
        and len({row.get("date") for row in windows}) >= 2)
    if valid_windows:
        valid_windows = all(_minute(row.get("start_time")) is not None
            and _minute(row.get("end_time")) is not None
            and _minute(row["end_time"]) > _minute(row["start_time"]) for row in windows)
    equipment = value.get("equipment")
    known_equipment = isinstance(equipment, list) and bool(equipment) and all(
        isinstance(row, dict) and type(row.get("quantity")) is int and row["quantity"] > 0 for row in equipment)
    space = value.get("space") or {}
    limits = value.get("time_limits") or {}
    checks = [bool(valid_windows), bool(known_equipment),
        type(value.get("participants_available")) is int and value["participants_available"] > 0,
        bool(space.get("usable_area_description")) and space.get("court_access") is not None
            and type(space.get("hoop_access")) is bool and isinstance(space.get("restrictions"), list),
        isinstance(value.get("existing_commitments"), list), value.get("reported_limitations") == [],
        isinstance(value.get("goals"), list) and bool(value["goals"]),
        all(type(limits.get(key)) is int and limits[key] > 0 for key in
            ("max_additional_sessions_per_week", "max_additional_minutes_per_week", "max_session_minutes"))]
    return {"fully_stated_selection_fields": all(checks), "stated_field_groups": sum(checks)}


def _food(record):
    value = record["input"].get("food_question")
    return isinstance(value, str) and bool(value.strip())


def select_pilot(publics, metadata, seed=42):
    """Choose the prespecified intent quotas without approving their categories."""
    if type(seed) is not int:
        raise ValueError("The selection seed must be an integer.")
    records = {}
    for record in publics:
        _validate_public(record)
        if record["profile_id"] in records:
            raise ValueError("Pilot candidates have duplicate IDs.")
        records[record["profile_id"]] = deepcopy(record)
    rows = {}
    for row in metadata:
        identifier = row.get("profile_id")
        if identifier in rows or identifier not in records or row.get("partition") != "development":
            raise ValueError("Pilot selection requires matching development-only metadata.")
        if not isinstance(row.get("proposed_family_id"), str) or not row["proposed_family_id"].strip():
            raise ValueError("A candidate has no proposed family identity.")
        if row.get("scenario_intent") not in {intent for quotas in QUOTAS.values() for intent in quotas}:
            raise ValueError("A development draft has an unknown scenario intent.")
        rows[identifier] = deepcopy(row)
    if set(rows) != set(records):
        raise ValueError("Every public candidate needs its separate development metadata.")
    groups = {}
    for identifier, record in records.items():
        key = (record["input"]["age"], rows[identifier].get("scenario_intent"))
        groups.setdefault(key, []).append(identifier)
    slots = []
    for age, quotas in QUOTAS.items():
        for intent, count in quotas.items():
            if len(groups.get((age, intent), [])) < count:
                raise ValueError("The development pool cannot fill the recorded age/intent quotas.")
            slots.extend([(age, intent)] * count)
    # Scarce challenge slots go first; feasible candidates retain a fact-specificity preference.
    slots.sort(key=lambda key: (key[1] == "feasible", len(groups[key]), key[0], key[1]))
    if len({r["proposed_family_id"] for r in rows.values()}) < 20:
        raise ValueError("The provisional pilot needs 20 distinct proposed families.")
    if sum(_food(record) for record in records.values()) < 2:
        raise ValueError("The provisional pilot needs at least two explicit food questions.")
    ranks = {identifier: _sha(_canonical({"seed": seed, "profile_id": identifier})) for identifier in records}
    selected, families = [], set()

    def choose(position, foods):
        if position == len(slots):
            return foods >= 2
        age, intent = slots[position]

        def rank(identifier):
            quality = _specificity(records[identifier]) if intent == "feasible" else {
                "fully_stated_selection_fields": False, "stated_field_groups": 0}
            return (-int(quality["fully_stated_selection_fields"]), -quality["stated_field_groups"],
                -int(foods < 2 and _food(records[identifier])), ranks[identifier], identifier)

        for identifier in sorted(groups[(age, intent)], key=rank):
            family = rows[identifier]["proposed_family_id"]
            if identifier in selected or family in families:
                continue
            selected.append(identifier)
            families.add(family)
            if choose(position + 1, foods + int(_food(records[identifier]))):
                return True
            families.remove(family)
            selected.pop()
        return False

    if not choose(0, 0):
        raise ValueError("The recorded quota, food and distinct-family constraints cannot be filled together.")
    order = {"feasible": 0, "missing_information": 1, "conflicting_constraints": 2, "outside_scope": 3}
    selected.sort(key=lambda identifier: (records[identifier]["input"]["age"],
        order[rows[identifier]["scenario_intent"]], ranks[identifier]))
    manifest, reviews = [], []
    for index, identifier in enumerate(selected, 1):
        record, source = records[identifier], rows[identifier]
        manifest.append({"pilot_index": index, "profile_id": identifier, "age": record["input"]["age"],
            "scenario_intent": source["scenario_intent"], "category_status": "intent_not_verified",
            "proposed_family_id": source["proposed_family_id"], "family_status": "proposal_not_adopted",
            "food_question_present": _food(record), "public_record_sha256": _sha(_canonical(record)),
            "selection_specificity": _specificity(record), "selection_status": "provisional_development_only"})
        reviews.append({"profile_id": identifier, "preparer": "", "second_reviewer": "",
            "case_review": "pending", "category_review": "pending", "family_review": "pending",
            "feasibility_record": "not_prepared", "expected_behavior": "not_prepared",
            "schedule_completeness": "not_attested_by_selection", "acceptance_status": "not_accepted"})
    policy = {"selection_version": SELECTION_VERSION, "seed": seed, "target_quotas": deepcopy(QUOTAS),
        "selection_basis": "public_input_specificity_and_private_draft_intents_only",
        "tie_break": "sha256_of_seed_and_profile_id", "minimum_food_questions": 2,
        "distinct_proposed_families": 20, "public_inputs_changed": False,
        "model_outputs_used_for_selection": False, "accepted_study_profiles": 0,
        "review_status": "pending_case_family_and_feasibility_review"}
    return {"public_records": [deepcopy(records[identifier]) for identifier in selected],
        "manifest": manifest, "review_rows": reviews, "selection": policy}


def assign_jobs(selection, seed=42):
    """Prepare 80 ordered jobs; no request is submitted and no review is implied."""
    if type(seed) is not int:
        raise ValueError("The order seed must be an integer.")
    manifest = selection["manifest"]
    if len(manifest) != 20 or len({row["profile_id"] for row in manifest}) != 20:
        raise ValueError("Balanced job preparation requires 20 distinct selected profiles.")
    publics = selection.get("public_records") or []
    records = {record["profile_id"]: record for record in publics}
    if len(publics) != 20 or set(records) != {row["profile_id"] for row in manifest}:
        raise ValueError("Prepared jobs must match the selected public profiles.")
    for row in manifest:
        record = records[row["profile_id"]]
        _validate_public(record)
        if row["age"] != record["input"]["age"] or row["public_record_sha256"] != _sha(_canonical(record)):
            raise ValueError("A selected public profile changed before job preparation.")
    by_age = {age: sorted([row for row in manifest if row["age"] == age], key=lambda row: row["profile_id"]) for age in QUOTAS}
    if any(len(rows) != 4 for rows in by_age.values()):
        raise ValueError("Balanced job preparation requires four selected profiles per age.")
    rng, assigned = random.Random(seed), {}
    for age in sorted(by_age):
        labels = list(ORDERS)
        rng.shuffle(labels)
        assigned.update({row["profile_id"]: label for row, label in zip(by_age[age], labels)})
    jobs = []
    for case in sorted(manifest, key=lambda row: row["pilot_index"]):
        label = assigned[case["profile_id"]]
        for position, version in enumerate(ORDERS[label], 1):
            identity = {"selection_version": SELECTION_VERSION, "seed": seed,
                "profile_id": case["profile_id"], "public_record_sha256": case["public_record_sha256"],
                "planner_version": version}
            jobs.append({"scheduled_index": len(jobs) + 1, "job_id": "pilot-prepared-" + _sha(_canonical(identity))[:24],
                "pilot_index": case["pilot_index"], "profile_id": case["profile_id"], "age": case["age"],
                "planner_version": version, "order_label": label, "position_in_case": position,
                "public_record_sha256": case["public_record_sha256"], "status": "planned_not_submitted"})
    return jobs
