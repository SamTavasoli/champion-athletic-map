"""Verify saved-case loading and immutable offline assessment output with sealed fixtures."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import urllib.request

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load(name):
    path = ROOT / "src/champion_athletic_map" / (name + ".py")
    spec = importlib.util.spec_from_file_location("saved_run_test_" + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


API, PROBE = load("independent_assessment_run"), load("pilot_probe")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(API.canonical(value) + b"\n")


def files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def saved(tmp_path, monkeypatch):
    # Synthetic sealed records exercise the real saved-job/reference validators.
    # No fixture record represents a new observed model or encoder execution.
    root = tmp_path
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    names = ["pilot_probe", "independent_assessment_run", "independent_plan_assessment", "independent_resources", "independent_food"]
    for name in names:
        relative = "src/champion_athletic_map/" + name + ".py"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    for relative in ("artifacts/evaluation/independent_assessment/reviewed_resource_contracts.json",
            "docs/independent_development_assessment_policy.md", "docs/prompts/shared_task_addendum_candidate.txt"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    def no_network(*args, **kwargs):
        raise AssertionError("An offline saved-assessment test attempted network transport.")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", no_network)
    public = {"profile_id": "software:saved-assessment", "schema_version": "athlete-profile-input-2",
        "input": {"age": 13, "athlete_request": "Please plan two extra basketball sessions."}}
    schema_path = "artifacts/test/public_schema.json"
    write(root / schema_path, {"type": "object", "fixture_only": True})
    core_path = "src/champion_athletic_map/pilot_probe.py"
    identity = {"fixture_only": True, "public_record": public,
        "public_record_sha256": API.sha(API.canonical(public)),
        "module_and_config_sha256": {core_path: API.sha((root / core_path).read_bytes())},
        "case_review_files": {schema_path: API.sha((root / schema_path).read_bytes())}}
    digest = API.sha(API.canonical(identity))
    jobs = [{"job_id": "software_v" + str(n), "planner_version": n, "call_id": "software_v" + str(n)} for n in (1, 2, 3, 4)]
    manifest = {**identity, "manifest_id": digest, "probe_id": "probe_" + digest[:20], "jobs": jobs,
        "case_review_config_path": "artifacts/test/unused_config.json", "public_schema_path": schema_path}
    manifest_path = "artifacts/pilot/probes/" + manifest["probe_id"] + "/probe_manifest.json"
    write(root / manifest_path, manifest)
    write(root / "results/pilot/probes/first_operational_probe.json", {"manifest_id": digest, "manifest_path": manifest_path})
    folder = root / "results/pilot/probes" / manifest["probe_id"]
    packet_body = {"schema_version": "shared-reference-packet-1", "public_input_sha256": API.sha(API.canonical(public["input"])),
        "payload": {"references": [], "food_lookup": []}, "preparation": {"fixture_only": True}}
    packet = {**packet_body, "packet_id": "reference-packet:" + API.sha(API.canonical(packet_body))}
    for job in jobs:
        n = job["planner_version"]
        reference = None
        if n != 1:
            work = folder / "references" / job["job_id"]
            request = {"public_record": public, "configuration_id": digest, "fixture_only": True}
            for name, value in (("request.json", request), ("packet.json", packet), ("trace.json", {"fixture_only": True})):
                write(work / name, value)
            complete = {"configuration_id": digest, "request_sha256": API.sha(API.canonical(request)),
                "packet_id": packet["packet_id"], "preparation_seconds": 0.0, "counts": {"query_encoder_processes": 0},
                "artifact_sha256": {p.name: API.sha(p.read_bytes()) for p in work.iterdir()}, "fixture_only": True}
            complete["completion_record_sha256"] = API.sha(API.canonical(complete))
            write(work / "completed.json", complete)
            reference = PROBE.saved_references(root, work, manifest)
        outcome = {"planner_version": n, "status": "failed" if n == 4 else "returned",
            "completion_valid": n != 4, "format_valid": n != 4, "response_type": None if n == 4 else "plan",
            "terminal_state": "execution_error" if n == 4 else None,
            "response": None if n == 4 else {"authoritative_public_input": deepcopy(public["input"]),
                "model_output": {"raw_text": '{"response_type":"plan","explanation":"Software fixture."}'}},
            "fixture_only": True}
        work = folder / "jobs" / job["job_id"]
        write(work / "outcome.json", outcome)
        record = {"manifest_id": digest, "job_id": job["job_id"], "planner_version": n,
            "public_record_sha256": manifest["public_record_sha256"], "outcome_sha256": API.sha((work / "outcome.json").read_bytes()),
            "outcome": PROBE.result_view(outcome), "reference_record": reference, "fixture_only": True}
        write(work / "job_record.json", PROBE.seal_record(record))
    amendment_identity = {"source_manifest_id": digest, "source_probe_id": manifest["probe_id"], "fixture_only": True}
    amended_digest = API.sha(API.canonical(amendment_identity))
    amendment = {**amendment_identity, "manifest_id": amended_digest, "amendment_id": "continuation_" + amended_digest[:20],
        "call_prefix": "software_amended"}
    write(root / "artifacts/pilot/continuations" / amendment["amendment_id"] / "manifest.json", amendment)
    amended_result = {"planner_version": 4, "status": "returned", "completion_valid": True, "format_valid": True,
        "response": {"authoritative_public_input": deepcopy(public["input"]), "model_output": {"raw_text": "Separate amended fixture."}},
        "fixture_only": True}
    work = root / "results/pilot/continuations" / amendment["amendment_id"]
    write(work / "outcome.json", {"manifest_id": amended_digest, "result": amended_result, "fixture_only": True})
    write(work / "completed.json", {"manifest_id": amended_digest, "outcome_sha256": API.sha((work / "outcome.json").read_bytes())})
    write(root / "results/step31_v4_continuation_summary.json", {"manifest_id": amended_digest,
        "amendment_id": amendment["amendment_id"], "result": amended_result, "fixture_only": True})
    return SimpleNamespace(root=root, manifest=manifest, manifest_path=manifest_path, folder=folder, jobs=jobs)


def test_real_loader_keeps_four_originals_and_amended_v4_separate_without_writes(saved):
    before = files(saved.root)
    source = API.load_saved_cases(saved.root)
    indexed = {row["assessment_id"]: row for row in source["cases"]}
    assert set(indexed) == {"original_v1", "original_v2", "original_v3", "original_v4", "amended_v4"}
    assert indexed["original_v4"]["outcome"]["completion_valid"] is False
    assert indexed["original_v4"]["outcome"]["response"] is None
    assert indexed["amended_v4"]["outcome"]["completion_valid"] is True
    assert indexed["amended_v4"]["record_kind"] == "separate_development_continuation"
    assert files(saved.root) == before
    assert not (saved.root / "results/integration/model_calls").exists()


@pytest.mark.parametrize("change", ["damaged_outcome", "damaged_reference", "public_input", "duplicate_version"])
def test_real_loader_rejects_changed_sources_or_duplicate_arms(saved, change):
    job = saved.jobs[0]
    work = saved.folder / "jobs" / job["job_id"]
    if change == "damaged_outcome":
        path = work / "outcome.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "damaged_reference":
        path = saved.folder / "references" / saved.jobs[1]["job_id"] / "packet.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "public_input":
        outcome = API.read(work / "outcome.json")
        outcome["response"]["authoritative_public_input"]["age"] = 14
        write(work / "outcome.json", outcome)
        record = API.read(work / "job_record.json")
        record.pop("job_record_sha256")
        record["outcome_sha256"] = API.sha((work / "outcome.json").read_bytes())
        record["outcome"] = PROBE.result_view(outcome)
        write(work / "job_record.json", PROBE.seal_record(record))
    else:
        value = deepcopy(saved.manifest)
        value["jobs"][2] = deepcopy(value["jobs"][1])
        write(saved.root / saved.manifest_path, value)
    before = files(saved.root)
    with pytest.raises(ValueError):
        API.load_saved_cases(saved.root)
    assert files(saved.root) == before


class DeterministicAssessor:
    dependency_sha256 = {}
    def __init__(self, root, schema):
        self.root = root
    def assess(self, public, outcome, packet, *, assessment_id):
        return {"assessment_id": assessment_id, "assessment_execution": "completed",
            "overall": "fixture_completed" if outcome["completion_valid"] else "fixture_failed",
            "checks": [], "designated_outcome_sha256": API.sha(API.canonical(outcome)), "fixture_only": True}


def test_run_is_idempotent_with_fresh_software_evidence_and_preserves_inputs(saved):
    before = files(saved.root)
    evidence = {"status": "passed", "passed": 1, "fixture_only": True,
        "files": {"src/champion_athletic_map/independent_assessment_run.py":
            API.sha((saved.root / "src/champion_athletic_map/independent_assessment_run.py").read_bytes())}}
    first = API.run(saved.root, assessor_factory=DeterministicAssessor,
        software_evidence={**evidence, "execution": "first"})
    second = API.run(saved.root, assessor_factory=DeterministicAssessor,
        software_evidence={**evidence, "execution": "second"})
    assert first["assessment_id"] == second["assessment_id"]
    assert first["assessment_file_sha256"] == second["assessment_file_sha256"]
    assert first["reports"] == second["reports"]
    assert second["software_evidence"]["execution"] == "second"
    assert second["original_outcomes_assessed"] == 4 and second["amended_outcomes_assessed"] == 1
    assert second["new_model_calls"] == second["http_requests"] == second["query_encodings"] == 0
    assert second["final_scoring_ready"] is False and second["protocol_frozen"] is False
    assert all((saved.root / name).read_bytes() == data for name, data in before.items())
    assert not (saved.root / "results/integration/model_calls").exists()


@pytest.mark.parametrize("evidence", [
    {"status": "passed", "passed": 0, "files": {}},
    {"status": "passed", "passed": 1, "files": {
        "src/champion_athletic_map/independent_assessment_run.py": "0" * 64}},
])
def test_unexecuted_or_changed_software_evidence_cannot_authorize_assessment(saved, evidence):
    before = files(saved.root)
    with pytest.raises(ValueError):
        API.run(saved.root, assessor_factory=DeterministicAssessor, software_evidence=evidence)
    assert files(saved.root) == before


def test_changed_immutable_assessment_is_preserved_and_rejected(saved):
    result = API.run(saved.root, assessor_factory=DeterministicAssessor)
    path = saved.root / result["assessment_file"]
    path.write_bytes(path.read_bytes() + b" ")
    changed = path.read_bytes()
    with pytest.raises(ValueError, match="earlier assessment differs"):
        API.run(saved.root, assessor_factory=DeterministicAssessor)
    assert path.read_bytes() == changed

pytestmark = pytest.mark.requirement("31:independent-assessment-components")
