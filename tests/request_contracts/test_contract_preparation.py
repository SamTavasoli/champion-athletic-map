"""Verify the saved-reply loader with sealed, explicitly synthetic fixtures."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/champion_athletic_map/contract_preparation.py"
spec = importlib.util.spec_from_file_location("contract_preparation_under_test", SOURCE)
API = importlib.util.module_from_spec(spec)
spec.loader.exec_module(API)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(API.canonical(value) + b"\n")


def files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts}


def seal(record):
    body = {key: value for key, value in record.items() if key != "job_record_sha256"}
    return {**body, "job_record_sha256": API.sha(API.canonical(body))}


@pytest.fixture
def saved(tmp_path):
    # These records exercise receipt validation; none represents a model run.
    public = {"profile_id": "software-only-contract-case", "schema_version": "athlete-profile-input-2",
        "input": {"age": 15, "athlete_request": "Organize two additional basketball practices.",
            "food_question": "A fictional recorded food question?"}}
    packet = {"packet_id": "software-only-reference-packet", "fixture_only": True,
        "payload": {"food_lookup": [{"status": "not_available", "data": None}]}}
    summary = {"recorded_jobs": 4, "independent_assessment_completed": True,
        "injected_test_dependencies": False, "protocol_frozen": False,
        "profile_id": public["profile_id"], "probe_id": "software_only_contract_probe",
        "manifest_id": "a" * 64, "reports": [], "fixture_only": True}
    paths = {}
    for version in range(1, 5):
        job_id = "software_v" + str(version)
        path = tmp_path / "results/pilot/probes" / summary["probe_id"] / "jobs" / job_id / "outcome.json"
        outcome = {"planner_version": version, "fixture_only": True,
            "completion_valid": True, "format_valid": True,
            "response": {"authoritative_public_input": deepcopy(public["input"]),
                "model_output": {"raw_text": "{}", "parsed_object": {}}}}
        write(path, outcome)
        record = {"manifest_id": summary["manifest_id"], "planner_version": version, "job_id": job_id,
            "outcome_sha256": API.sha(path.read_bytes()), "public_record_sha256": API.sha(API.canonical(public)),
            "fixture_only": True}
        if version != 1:
            record["reference_record"] = {"packet": deepcopy(packet), "fixture_only": True}
        write(path.with_name("job_record.json"), seal(record))
        summary["reports"].append({"planner_version": version, "job_id": job_id,
            "outcome_path": path.relative_to(tmp_path).as_posix(),
            "assessment": {"designated_outcome_sha256": API.sha(API.canonical(outcome))}})
        paths[version] = path
    summary_path = tmp_path / "results/step31_shared_guidance_summary.json"
    write(summary_path, summary)
    return SimpleNamespace(root=tmp_path, public=public, packet=packet, summary=summary,
        summary_path=summary_path, paths=paths)


def test_verified_reply_loader_binds_all_nine_sources_without_changing_them(saved):
    before = files(saved.root)
    result = API.load_replies(saved.root)
    assert result["public_record"] == saved.public
    assert [item["planner_version"] for item in result["replies"]] == [1, 2, 3, 4]
    assert result["truth_packet_sha256"] == API.sha(API.canonical(saved.packet))
    assert len(result["input_sha256"]) == 9
    assert set(result["input_sha256"]) == set(before)
    assert all(result["input_sha256"][path] == API.sha(data) for path, data in before.items())
    assert files(saved.root) == before


@pytest.mark.parametrize("change", ["designated_object", "raw_file_hash", "job_seal"])
def test_changed_designated_outcome_file_or_job_seal_is_rejected_and_preserved(saved, change):
    path = saved.paths[2]
    if change == "designated_object":
        value = json.loads(path.read_bytes())
        value["format_valid"] = False
        write(path, value)
    elif change == "raw_file_hash":
        path.write_bytes(path.read_bytes() + b" ")
    else:
        record_path = path.with_name("job_record.json")
        record = json.loads(record_path.read_bytes())
        record["job_record_sha256"] = "0" * 64
        write(record_path, record)
    before = files(saved.root)
    with pytest.raises(ValueError):
        API.load_replies(saved.root)
    assert files(saved.root) == before


def test_a_resealed_changed_public_input_is_still_rejected_against_other_jobs(saved):
    path = saved.paths[3]
    value = json.loads(path.read_bytes())
    value["response"]["authoritative_public_input"]["age"] = 16
    write(path, value)
    record_path = path.with_name("job_record.json")
    record = json.loads(record_path.read_bytes())
    record["outcome_sha256"] = API.sha(path.read_bytes())
    public = deepcopy(saved.public)
    public["input"] = value["response"]["authoritative_public_input"]
    record["public_record_sha256"] = API.sha(API.canonical(public))
    write(record_path, seal(record))
    saved.summary["reports"][2]["assessment"]["designated_outcome_sha256"] = API.sha(API.canonical(value))
    write(saved.summary_path, saved.summary)
    before = files(saved.root)
    with pytest.raises(ValueError, match="share the original public case"):
        API.load_replies(saved.root)
    assert files(saved.root) == before


def test_a_resealed_changed_reference_packet_is_rejected_against_matched_jobs(saved):
    path = saved.paths[4].with_name("job_record.json")
    record = json.loads(path.read_bytes())
    record["reference_record"]["packet"]["payload"]["food_lookup"] = []
    write(path, seal(record))
    before = files(saved.root)
    with pytest.raises(ValueError, match="matched reference content"):
        API.load_replies(saved.root)
    assert files(saved.root) == before


@pytest.mark.parametrize("change", ["missing", "duplicate"])
def test_missing_or_duplicated_planner_report_cannot_supply_complete_review(saved, change):
    if change == "missing":
        saved.summary["reports"].pop()
    else:
        saved.summary["reports"][3] = deepcopy(saved.summary["reports"][2])
    write(saved.summary_path, saved.summary)
    before = files(saved.root)
    with pytest.raises(ValueError, match="one designated outcome per planner"):
        API.load_replies(saved.root)
    assert files(saved.root) == before


pytestmark = pytest.mark.requirement("31:saved-response-contract-preparation")
