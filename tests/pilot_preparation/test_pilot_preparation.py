"""Check that preparation preserves facts and keeps unverified work pending."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT = Path(__file__).resolve().parents[2]
HERE = PROJECT / "src/champion_athletic_map"


def load(name):
    path = HERE / (name + ".py")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("test_" + name, path))
    result.__spec__.loader.exec_module(result)
    return result


preparation = load("pilot_preparation")
selection = load("pilot_selection")


@pytest.fixture
def setup(tmp_path):
    modules = tmp_path / "src/champion_athletic_map"
    modules.mkdir(parents=True)
    for name in ("pilot_preparation", "pilot_selection", "pilot_readiness"):
        (modules / (name + ".py")).write_bytes((HERE / (name + ".py")).read_bytes())
    pool = selection.load_pool(PROJECT)
    chosen = SimpleNamespace(load_pool=lambda root: deepcopy(pool),
        select_pilot=selection.select_pilot, assign_jobs=selection.assign_jobs)
    calls = []

    def local(root, folder, **options):
        calls.append((root, folder, options))
        folder.mkdir(parents=True)
        return {"checks": [{"check_id": "step30_execution", "status": "passed", "required": True,
            "reason": "Authored test prerequisite", "evidence": "synthetic test"},
            {"check_id": "fixture_local_metadata", "status": "pending", "required": False,
             "reason": "No real service was contacted in this test.", "evidence": "synthetic test"}],
            "model_generation_calls": 0, "query_encoder_processes": 0, "metadata_requests": 0,
            "local_model_status": "test_not_observed", "reference_files_status": "test_not_observed",
            "metadata_evidence_dir": folder.relative_to(root).as_posix()}

    ready = SimpleNamespace(check_step30=lambda root: [{"check_id": "step30_execution", "status": "passed",
        "required": True, "reason": "Authored test prerequisite", "evidence": "synthetic test"}],
        check_local_readiness=local)
    return tmp_path, chosen, ready, calls


def test_preparation_separates_public_facts_from_provisional_reviews(setup):
    root, chosen, ready, calls = setup
    summary = preparation.prepare(root, selection_module=chosen, readiness_module=ready)
    assert (summary["selected_drafts"], summary["planned_jobs"], summary["pilot_jobs_run"]) == (20, 80, 0)
    assert summary["food_request_profiles"] == 6
    assert summary["logical_generation_budget"]["minimum_completed_workflows"] == 192
    assert summary["logical_generation_budget"]["maximum_configured_completed_workflows"] == 272
    files = summary["preparation_files"]
    public_path = next(path for path in files if path.endswith("public_profiles.jsonl"))
    rows = [json.loads(line) for line in (root / public_path).read_bytes().splitlines()]
    original = {r["profile_id"]: r for r in chosen.load_pool(root)["public_records"]}
    assert len(rows) == 20
    assert all(record == original[record["profile_id"]] for record in rows)
    assert all(set(record) == {"profile_id", "schema_version", "input"} for record in rows)
    assert len(calls) == 1


def test_preparation_keeps_semantic_prerequisites_and_study_approval_pending(setup):
    root, chosen, ready, _ = setup
    summary = preparation.prepare(root, selection_module=chosen, readiness_module=ready)
    assert summary["accepted_study_profiles"] == summary["adopted_families"] == summary["human_reviews_claimed"] == 0
    assert summary["model_generation_calls"] == summary["query_encoder_processes"] == 0
    assert summary["case_review"] == "pending"
    assert summary["protocol_frozen"] is summary["operational_generation_ready"] is False
    assert set(summary["pending_prerequisites"]) >= {
        "pilot_case_review", "complete_planning_checks", "independent_scoring"}
    assert len({row["check_id"] for row in summary["checks"]}) == len(summary["checks"])
    assert not (root / "artifacts/application/pilot_runtime_approval.json").exists()


def test_repeated_preparation_keeps_one_immutable_selection_and_distinct_observations(setup):
    root, chosen, ready, calls = setup
    first = preparation.prepare(root, selection_module=chosen, readiness_module=ready)
    before = {name: (root / name).read_bytes() for name in first["preparation_files"]}
    second = preparation.prepare(root, selection_module=chosen, readiness_module=ready)
    assert first["preparation_id"] == second["preparation_id"]
    assert first["preparation_files"] == second["preparation_files"]
    assert first["metadata_evidence_directory"] != second["metadata_evidence_directory"]
    assert all((root / name).read_bytes() == value for name, value in before.items())
    assert len(calls) == 2


def test_unsuccessful_step30_stops_before_selection_or_metadata_requests(setup):
    root, chosen, ready, calls = setup
    ready.check_step30 = lambda root: [{"check_id": "step30_execution", "status": "blocked", "required": True}]
    summary = preparation.prepare(root, selection_module=chosen, readiness_module=ready)
    assert summary["status"] == "step30_prerequisite_needs_attention"
    assert summary["selected_drafts"] == summary["planned_jobs"] == summary["pilot_jobs_run"] == 0
    assert not calls
    assert not (root / "artifacts/pilot").exists()


def test_existing_edited_selection_file_is_preserved(setup):
    root, chosen, ready, calls = setup
    summary = preparation.prepare(root, selection_module=chosen, readiness_module=ready)
    name = next(name for name in summary["preparation_files"] if name.endswith("case_review_queue.csv"))
    path = root / name
    edited = path.read_bytes() + b"An authored test edit.\n"
    path.write_bytes(edited)
    with pytest.raises(ValueError, match="preserved"):
        preparation.prepare(root, selection_module=chosen, readiness_module=ready)
    assert path.read_bytes() == edited
    assert len(calls) == 1

pytestmark = pytest.mark.requirement('31.1:preparation-state')
