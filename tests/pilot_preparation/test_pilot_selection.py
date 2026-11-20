"""Check our provisional selection and planned order without running a model."""

from collections import Counter, defaultdict
from copy import deepcopy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


PROJECT = Path(__file__).resolve().parents[2]
HERE = PROJECT / "src/champion_athletic_map"
spec = importlib.util.spec_from_file_location("step31_pilot_selection_checks", HERE / "pilot_selection.py")
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)


@pytest.fixture(scope="module")
def pool():
    return selection.load_pool(PROJECT)


@pytest.fixture(scope="module")
def chosen(pool):
    return selection.select_pilot(pool["public_records"], pool["metadata"], seed=42)


def test_verified_pool_has_one_hundred_development_records_and_seven_retained_revisions(pool):
    assert len(pool["public_records"]) == len(pool["metadata"]) == 100
    assert pool["provenance"]["retained_revision_records_verified"] == 7
    assert Counter(record["input"]["age"] for record in pool["public_records"]) == {age: 20 for age in range(13, 18)}
    assert {row["partition"] for row in pool["metadata"]} == {"development"}


def test_selection_matches_the_prespecified_twenty_profile_coverage(chosen):
    assert len(chosen["public_records"]) == len(chosen["manifest"]) == len(chosen["review_rows"]) == 20
    observed = Counter((row["age"], row["scenario_intent"]) for row in chosen["manifest"])
    assert observed == {(13, "feasible"): 2, (13, "missing_information"): 1, (13, "conflicting_constraints"): 1,
        (14, "feasible"): 2, (14, "missing_information"): 1, (14, "outside_scope"): 1,
        (15, "feasible"): 2, (15, "conflicting_constraints"): 1, (15, "outside_scope"): 1,
        (16, "feasible"): 2, (16, "missing_information"): 1, (16, "conflicting_constraints"): 1,
        (17, "feasible"): 2, (17, "missing_information"): 1, (17, "outside_scope"): 1}
    assert len({row["proposed_family_id"] for row in chosen["manifest"]}) == 20
    assert sum(row["food_question_present"] for row in chosen["manifest"]) >= 2


def test_feasible_intents_prefer_fully_stated_selection_fields(chosen):
    feasible = [row for row in chosen["manifest"] if row["scenario_intent"] == "feasible"]
    assert len(feasible) == 10
    assert all(row["selection_specificity"]["fully_stated_selection_fields"] is True for row in feasible)


def test_public_inputs_remain_unchanged_and_separate_from_private_review(pool, chosen):
    original = {record["profile_id"]: record for record in pool["public_records"]}
    for record in chosen["public_records"]:
        assert record == original[record["profile_id"]]
        assert set(record) == {"profile_id", "schema_version", "input"}
        assert not set(record["input"]) & selection.PRIVATE_FIELDS
        assert "schedule_completeness" not in record["input"]
    assert chosen["selection"]["accepted_study_profiles"] == 0
    assert chosen["selection"]["model_outputs_used_for_selection"] is False
    assert {row["category_status"] for row in chosen["manifest"]} == {"intent_not_verified"}
    assert {row["family_status"] for row in chosen["manifest"]} == {"proposal_not_adopted"}
    assert all(row["preparer"] == row["second_reviewer"] == "" for row in chosen["review_rows"])
    assert {row["acceptance_status"] for row in chosen["review_rows"]} == {"not_accepted"}


def test_seeded_selection_is_stable_under_input_order_and_does_not_modify_sources(pool, chosen):
    before = deepcopy(pool)
    repeated = selection.select_pilot(list(reversed(pool["public_records"])), list(reversed(pool["metadata"])), seed=42)
    assert repeated == chosen
    assert pool == before
    repeated["public_records"][0]["input"]["goals"].append("An isolated test edit")
    assert pool == before


def test_balanced_jobs_are_eighty_unique_plans_not_submitted_requests(chosen):
    before = deepcopy(chosen)
    jobs = selection.assign_jobs(chosen, seed=42)
    assert len(jobs) == len({row["job_id"] for row in jobs}) == 80
    assert Counter(row["planner_version"] for row in jobs) == {1: 20, 2: 20, 3: 20, 4: 20}
    assert Counter((row["planner_version"], row["position_in_case"]) for row in jobs) == {
        (version, position): 5 for version in range(1, 5) for position in range(1, 5)}
    assert {row["status"] for row in jobs} == {"planned_not_submitted"}
    by_case = defaultdict(list)
    for row in jobs:
        by_case[row["profile_id"]].append(row)
    for age in range(13, 18):
        assert {rows[0]["order_label"] for rows in by_case.values() if rows[0]["age"] == age} == {"A", "B", "C", "D"}
    for rows in by_case.values():
        assert tuple(row["planner_version"] for row in rows) == selection.ORDERS[rows[0]["order_label"]]
        assert [row["position_in_case"] for row in rows] == [1, 2, 3, 4]
    assert chosen == before
    assert selection.assign_jobs(chosen, seed=42) == jobs


def test_job_preparation_rejects_changed_public_facts(chosen):
    changed = deepcopy(chosen)
    changed["public_records"][0]["input"]["athlete_request"] += " Changed after selection."
    with pytest.raises(ValueError, match="changed before job preparation"):
        selection.assign_jobs(changed)


@pytest.mark.parametrize("place", ["record", "input", "nested"])
def test_private_metadata_is_rejected_at_the_public_boundary(pool, place):
    records = deepcopy(pool["public_records"])
    if place == "record":
        records[0]["scenario_intent"] = "feasible"
    elif place == "input":
        records[0]["input"]["family_id"] = "private-family"
    else:
        records[0]["input"]["basketball_background"]["expected_response_type"] = "plan"
    with pytest.raises(ValueError, match="public|Private"):
        selection.select_pilot(records, pool["metadata"])


def test_insufficient_stratum_is_reported_without_relaxing_quotas(pool):
    records = [r for r in pool["public_records"] if r["input"]["age"] != 17]
    identifiers = {r["profile_id"] for r in records}
    rows = [r for r in pool["metadata"] if r["profile_id"] in identifiers]
    with pytest.raises(ValueError, match="age/intent quotas"):
        selection.select_pilot(records, rows)


def test_repeated_families_cannot_be_counted_as_twenty_distinct_families(pool):
    rows = deepcopy(pool["metadata"])
    for row in rows:
        row["proposed_family_id"] = "one-family"
    with pytest.raises(ValueError, match="20 distinct proposed families"):
        selection.select_pilot(pool["public_records"], rows)


def test_missing_food_coverage_is_not_silently_accepted(pool):
    records = deepcopy(pool["public_records"])
    for record in records:
        record["input"]["food_question"] = None
    with pytest.raises(ValueError, match="two explicit food questions"):
        selection.select_pilot(records, pool["metadata"])


def _copy_pool(destination):
    for relative in (selection.POOL_DIRECTORY, selection.RETAINED_REVISION_DIRECTORY):
        shutil.copytree(PROJECT / relative, destination / relative)
    schema = destination / selection.SCHEMA_PATH
    schema.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PROJECT / selection.SCHEMA_PATH, schema)


def test_changed_development_artifact_is_rejected_before_selection(tmp_path):
    _copy_pool(tmp_path)
    path = tmp_path / selection.POOL_DIRECTORY / "development_draft_review_queue.csv"
    path.write_bytes(path.read_bytes() + b"Unexpected extra row\n")
    with pytest.raises(ValueError, match="artifact changed"):
        selection.load_pool(tmp_path)


def test_changed_retained_revision_is_rejected_before_selection(tmp_path):
    _copy_pool(tmp_path)
    path = tmp_path / selection.RETAINED_REVISION_DIRECTORY / "development_draft_inputs.jsonl"
    path.write_bytes(path.read_bytes() + b"{}\n")
    with pytest.raises(ValueError, match="retained development revision artifact changed"):
        selection.load_pool(tmp_path)


def test_metadata_partition_cannot_introduce_a_held_out_record(pool):
    rows = deepcopy(pool["metadata"])
    rows[0]["partition"] = "test"
    with pytest.raises(ValueError, match="development-only metadata"):
        selection.select_pilot(pool["public_records"], rows)


def test_duplicate_profile_identity_is_rejected(pool):
    records = deepcopy(pool["public_records"])
    records.append(deepcopy(records[0]))
    with pytest.raises(ValueError, match="duplicate IDs"):
        selection.select_pilot(records, pool["metadata"])

pytestmark = pytest.mark.requirement('31.2:development-selection')
