"""Check case lineage, public amendments and retained readiness limitations."""

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


PROJECT = Path(__file__).resolve().parents[2]
HERE = PROJECT / "src/champion_athletic_map"


def module(name):
    path = HERE / (name + ".py")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("test_" + name, path))
    result.__spec__.loader.exec_module(result)
    return result


review = module("pilot_case_review")
selection = module("pilot_selection")
preparation = module("pilot_preparation")


@pytest.fixture
def prepared(tmp_path):
    # This fixture builds a synthetic preparation record; no runtime observation is fabricated.
    directories = [selection.POOL_DIRECTORY, selection.RETAINED_REVISION_DIRECTORY,
        "artifacts/evaluation/profile_contract_d3addc8aa60b70ab"]
    for relative in directories:
        shutil.copytree(PROJECT / relative, tmp_path / relative)
    source_files = ["pilot_selection", "pilot_readiness", "pilot_preparation", "pilot_case_review", "pilot_schedule",
        "planning_checks", "rule_checks"]
    for name in source_files:
        target = tmp_path / "src/champion_athletic_map" / (name + ".py")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HERE / (name + ".py"), target)
    pointer_path = "artifacts/language_model/active_resource_release.json"
    pointer = json.loads((PROJECT / pointer_path).read_bytes())
    for relative in [pointer_path] + [pointer["release_directory"] + "/" + name for name in
            ("manifest.json", "adopted_drills.json", "adopted_rules.json")]:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / relative, target)
    review_path = tmp_path / "artifacts/pilot/case_review_source_v1.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PROJECT / "artifacts/pilot/case_review_source_v1.json", review_path)
    pool = selection.load_pool(tmp_path)
    chosen = selection.select_pilot(pool["public_records"], pool["metadata"], seed=42)
    jobs = selection.assign_jobs(chosen, seed=42)
    config = {"source_provenance": pool["provenance"], "fixture_not_runtime_evidence": True,
        "module_sha256": {"src/champion_athletic_map/" + name + ".py": review.sha((HERE / (name + ".py")).read_bytes())
            for name in ("pilot_selection", "pilot_readiness", "pilot_preparation")}}
    identity = review.sha(preparation.packed({"configuration": config, "public_records": chosen["public_records"], "jobs": jobs}))
    folder = "artifacts/pilot/preparation_" + identity[:16]
    outputs = {folder + "/preparation_config.json": preparation.packed(config),
        folder + "/public_profiles.jsonl": b"".join(selection._canonical(row) + b"\n" for row in chosen["public_records"]),
        folder + "/planned_pilot_jobs.csv": preparation.csv_bytes(jobs),
        folder + "/case_review_queue.csv": preparation.csv_bytes(chosen["review_rows"]),
        folder + "/provisional_selection.csv": preparation.csv_bytes(chosen["manifest"])}
    for relative, data in outputs.items():
        preparation.save(tmp_path, relative, data, immutable=True)
    summary = {"preparation_id": "pilot-preparation:" + identity,
        "selected_drafts": 20, "planned_jobs": 80, "pilot_jobs_run": 0, "protocol_frozen": False,
        "local_model_status": "matched_metadata", "reference_files_status": "verified",
        "fixture_not_runtime_evidence": True,
        "preparation_files": {name: review.sha(data) for name, data in outputs.items()}}
    preparation.save(tmp_path, "results/step31_pilot_preparation_summary.json", preparation.packed(summary))
    return tmp_path, chosen, summary


def test_public_amendments_preserve_every_original_fact_and_separate_private_review(prepared):
    root, chosen, _ = prepared
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = review.prepare(root)
    path = next(name for name in result["review_files"] if name.endswith("/public_profiles.jsonl"))
    records = [json.loads(line) for line in (root / path).read_bytes().splitlines()]
    assert len(records) == 20 and result["complete_schedule_fictional_cases"] == 19
    for old, new in zip(chosen["public_records"], records):
        assert set(new) == {"profile_id", "schema_version", "input"}
        assert new["schema_version"] == "athlete-profile-input-2"
        assert set(new["input"]) == set(old["input"]) | {"schedule_coverage"}
        assert {k: v for k, v in new["input"].items() if k != "schedule_coverage"} == old["input"]
        assert new["input"]["schedule_coverage"]["existing_commitments_complete"] == (old["input"]["existing_commitments"] is not None)
        assert not (set(new["input"]) & selection.PRIVATE_FIELDS)
    assert all(path.read_bytes() == data for path, data in before.items())
    assert result["model_generation_calls"] == result["http_requests"] == result["pilot_jobs_run"] == 0
    assert result["accepted_study_profiles"] == result["human_reviews_claimed"] == 0
    assert not result["protocol_frozen"] and not result["independent_scoring_ready"]
    assert len(result["unresolved_feasibility_witness_ids"]) == 10


def test_repeated_review_reuses_identical_outputs_and_does_not_run_jobs(prepared):
    root, _, _ = prepared
    first = review.prepare(root)
    assert review.prepare(root) == first
    assert all(review.sha((root / name).read_bytes()) == digest for name, digest in first["review_files"].items())
    assert not (root / "results/pilot/run_records.jsonl").exists()


def test_authoring_decision_is_not_inferred_from_a_present_commitment_list(prepared):
    root, chosen, _ = prepared
    path = root / "artifacts/pilot/case_review_source_v1.json"
    value = json.loads(path.read_bytes())
    identifier = chosen["public_records"][0]["profile_id"]
    assert chosen["public_records"][0]["input"]["existing_commitments"] is not None
    value["public_authoring_decisions"][identifier]["existing_commitments_complete"] = False
    path.write_bytes(review.packed(value))
    result = review.prepare(root)
    assert result["complete_schedule_fictional_cases"] == 18
    assert result["unknown_existing_schedule_cases"] == 2


def test_missing_schedule_cannot_receive_a_true_attestation(prepared):
    root, _, _ = prepared
    path = root / "artifacts/pilot/case_review_source_v1.json"
    value = json.loads(path.read_bytes())
    value["public_authoring_decisions"]["athlete:47b01a8b4b719f44fd8ad604"]["existing_commitments_complete"] = True
    path.write_bytes(review.packed(value))
    with pytest.raises(ValueError, match="unknown existing schedule"):
        review.prepare(root)


def test_changed_preparation_input_is_preserved_and_rejected(prepared):
    root, _, summary = prepared
    path = root / next(name for name in summary["preparation_files"] if name.endswith("/public_profiles.jsonl"))
    path.write_bytes(path.read_bytes() + b"\n")
    changed = path.read_bytes()
    with pytest.raises(ValueError, match="saved pilot input differs"):
        review.prepare(root)
    assert path.read_bytes() == changed


@pytest.mark.parametrize("change", ["canonical", "source_choice", "release"])
def test_review_requires_exact_source_and_adopted_resource_bindings(prepared, change):
    root, _, _ = prepared
    path = root / "artifacts/pilot/case_review_source_v1.json"
    value = json.loads(path.read_bytes())
    if change == "canonical":
        value["rows"][0]["source_public_canonical_sha256"] = "0" * 64
    elif change == "source_choice":
        value["rows"][0]["witness"]["source_choices"][0]["record_canonical_sha256"] = "0" * 64
    else:
        value["adopted_drills_sha256"] = "0" * 64
    path.write_bytes(review.packed(value))
    with pytest.raises(ValueError):
        review.prepare(root)
    assert not (root / "results/step31_case_review_summary.json").exists()


def test_existing_different_versioned_output_is_never_overwritten(prepared):
    root, _, _ = prepared
    first = review.prepare(root)
    path = root / next(name for name in first["review_files"] if name.endswith("/public_profiles.jsonl"))
    path.write_bytes(b"preserved earlier contents\n")
    with pytest.raises(ValueError, match="differs and was preserved"):
        review.prepare(root)
    assert path.read_bytes() == b"preserved earlier contents\n"


pytestmark = pytest.mark.requirement("31:case-review-lineage")
