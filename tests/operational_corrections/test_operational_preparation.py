"""Check receipt integrity and candidate preparation with authored offline fixtures."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).with_name("operational_preparation.py")
if not SOURCE.is_file():
    SOURCE = ROOT / "src/champion_athletic_map/operational_preparation.py"
spec = importlib.util.spec_from_file_location("operational_preparation_under_test", SOURCE)
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
    # These sealed examples test software bookkeeping; none represents a model observation.
    root = tmp_path
    public = {"profile_id": "software:operational-preparation", "schema_version": "athlete-profile-input-2",
        "input": {"planning_window": {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"},
            "athlete_request": "Please organize two additional basketball practices.",
            "food_question": 'For the food "Fictional food", how many grams of protein are recorded for 100 g?'}}
    identity = {"fixture_only": True, "public_record": public, "public_record_sha256": API.sha(API.canonical(public)),
        "module_and_config_sha256": {}}
    digest = API.sha(API.canonical(identity))
    probe_id = "contract_" + digest[:20]
    jobs = [{"job_id": "software_v" + str(n), "planner_version": n} for n in range(1, 5)]
    manifest = {**identity, "manifest_id": digest, "probe_id": probe_id,
        "case_review_config_path": "artifacts/software_review.json", "public_schema_path": "artifacts/software_schema.json", "jobs": jobs}
    manifest_path = "artifacts/pilot/shared_guidance/" + probe_id + "/probe_manifest.json"
    write(root / manifest_path, manifest)
    reports = []
    packet = {"packet_id": "software-matched-packet", "payload": {"food_lookup": []}, "fixture_only": True}
    for n in range(1, 5):
        folder = root / "results/pilot/probes" / probe_id / "jobs" / ("software_v" + str(n))
        response = {"response_type": "plan", "explanation": "A software fixture only.",
            "food_facts": [{"statement": public["input"]["food_question"] if n in (2, 3) else "Unknown"}]}
        outcome = {"planner_version": n, "completion_valid": n != 4, "format_valid": n != 4,
            "response": {"authoritative_public_input": deepcopy(public["input"]),
                "model_output": {"parsed_object": response, "raw_text": API.canonical(response).decode("utf-8")}}}
        write(folder / "outcome.json", outcome)
        record = {"manifest_id": digest, "job_id": "software_v" + str(n), "planner_version": n,
            "public_record_sha256": manifest["public_record_sha256"], "outcome_sha256": API.sha((folder / "outcome.json").read_bytes())}
        if n != 1:
            record["reference_record"] = {"packet": deepcopy(packet)}
        write(folder / "job_record.json", seal(record))
        reports.append({"planner_version": n, "job_id": record["job_id"],
            "outcome_path": (folder / "outcome.json").relative_to(root).as_posix(),
            "assessment": {"designated_outcome_sha256": API.sha(API.canonical(outcome)),
                "required_violations": [], "required_unknowns": [], "checks": [{"check_id": "existing_commitments", "status": "unknown"}]}})
    summary = {"recorded_jobs": 4, "independent_assessment_completed": True, "injected_test_dependencies": False,
        "protocol_frozen": False, "probe_id": probe_id, "manifest_id": digest, "reports": reports,
        "fixture_only": True}
    write(root / "results/step31_contract_probe_summary.json", summary)
    return root


def test_complete_receipts_and_matched_reference_values_are_loaded_without_changes(saved):
    before = files(saved)
    result = API.load_saved(saved)
    assert len(result["cases"]) == 4 and len(result["input_sha256"]) == 10
    assert result["truth_packet"]["packet_id"] == "software-matched-packet"
    assert files(saved) == before


@pytest.mark.parametrize("change", ["outcome", "seal", "packet"])
def test_changed_saved_receipts_are_rejected_without_repair(saved, change):
    summary_path = saved / "results/step31_contract_probe_summary.json"
    summary = API.read(summary_path)
    report = summary["reports"][1]
    outcome_path = saved / report["outcome_path"]
    record_path = outcome_path.with_name("job_record.json")
    if change == "outcome":
        outcome_path.write_bytes(outcome_path.read_bytes() + b" ")
    else:
        record = API.read(record_path)
        if change == "seal":
            record["job_record_sha256"] = "0" * 64
        else:
            record["reference_record"]["packet"]["payload"]["extra"] = "different reference content"
            record = seal(record)
        write(record_path, record)
    before = files(saved)
    with pytest.raises(ValueError):
        API.load_saved(saved)
    assert files(saved) == before


@pytest.mark.parametrize("change", ["request", "result_context"])
def test_changed_native_request_is_not_treated_as_verified_source(saved, change):
    summary_path = saved / "results/step31_contract_probe_summary.json"
    summary = API.read(summary_path)
    report = summary["reports"][1]
    outcome_path = saved / report["outcome_path"]
    outcome = API.read(outcome_path)
    request = {"model": "software-only", "messages": [{"role": "user", "content": "Original request"}]}
    outcome.update(call_id="software_native", request_sha256=API.sha(API.wire(request)), input_configuration={"fixture_only": True})
    write(outcome_path, outcome)
    report["assessment"]["designated_outcome_sha256"] = API.sha(API.canonical(outcome))
    record_path = outcome_path.with_name("job_record.json")
    record = API.read(record_path)
    record["outcome_sha256"] = API.sha(outcome_path.read_bytes())
    write(record_path, seal(record))
    write(summary_path, summary)
    folder = saved / "results/integration/model_calls/software_native"
    folder.mkdir(parents=True)
    (folder / "request.json").write_bytes(API.wire({"request": request, "input_configuration": outcome["input_configuration"]}))
    write(folder / "result.json", outcome)
    assert "software_native" in API.load_saved(saved)["leaves"]
    if change == "request":
        request["messages"][0]["content"] = "Changed request"
        (folder / "request.json").write_bytes(API.wire({"request": request, "input_configuration": outcome["input_configuration"]}))
    else:
        changed = API.read(folder / "result.json")
        changed["context"] = {"input_ceiling_after_output_and_margin": 99999}
        write(folder / "result.json", changed)
    before = files(saved)
    with pytest.raises(ValueError, match="native model-call request"):
        API.load_saved(saved)
    assert files(saved) == before


def test_source_table_counter_handles_complete_controls_and_byte_pieces():
    counter = API.SourceTableCounter({"vocab": {"a": 1, "b": 2, "ab": 3, "Ġ": 4}, "merges": [["a", "b"]]},
        {"tokenizer.ggml.tokens": ["<|x|>"], "tokenizer.ggml.token_type": [3]})
    assert counter.count("ab<|x|>ab") == 3
    assert counter.count("a b") == 3
    with pytest.raises(ValueError):
        counter.count("x" * 200001)
    with pytest.raises(ValueError):
        API.recorded_render({"messages": [{"role": "user", "content": "Missing system message"}]})


def test_candidate_preparation_is_repeatable_and_preserves_original_saved_work(saved, monkeypatch):
    monkeypatch.setattr(__import__("sys"), "dont_write_bytecode", True)
    names = ("contract_probe", "request_contracts", "contract_runtime", "pilot_schedule", "llm", "independent_food",
        "operational_preparation", "operational_runtime", "food_reference_encoding", "food_answer_audit")
    for name in names:
        source = SOURCE if name == "operational_preparation" else ROOT / "src/champion_athletic_map" / (name + ".py")
        if not source.is_file():
            source = Path(__file__).with_name(name + ".py")
        target = saved / "src/champion_athletic_map" / (name + ".py")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    integration = API.read(ROOT / "artifacts/language_model/integration_config.json")
    config3 = API.read(ROOT / "artifacts/planners/version3_config.json")
    directory = integration["contracts_directory"]
    paths = ["artifacts/language_model/integration_config.json", "artifacts/planners/version3_config.json", config3["note_schema_path"]]
    paths += [directory + "/" + name for name in ("public_input.py", "public_profile_record_schema.json", "planner_response_schema.json")]
    for relative in paths:
        target = saved / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    document = saved / "docs/operational_corrections.md"
    document.parent.mkdir(parents=True)
    document.write_text("Authored software fixture; no observed model quality.\n")
    manifest_path = next((saved / "artifacts/pilot/shared_guidance").glob("*/probe_manifest.json"))
    manifest = API.read(manifest_path)
    manifest["module_and_config_sha256"] = {"src/champion_athletic_map/" + name + ".py":
        API.sha((saved / "src/champion_athletic_map" / (name + ".py")).read_bytes()) for name in names}
    public_path = directory + "/public_profile_record_schema.json"
    manifest["module_and_config_sha256"][public_path] = API.sha((saved / public_path).read_bytes())
    # The sealed fixture's manifest digest must follow its changed declared source identity.
    identity = {key: value for key, value in manifest.items() if key not in
        ("probe_id", "manifest_id", "case_review_config_path", "public_schema_path", "jobs")}
    digest = API.sha(API.canonical(identity))
    old_id = manifest["manifest_id"]
    new_id = "contract_" + digest[:20]
    old_probe = saved / "results/pilot/probes" / manifest["probe_id"]
    new_probe = old_probe.with_name(new_id)
    old_probe.rename(new_probe)
    manifest.update(manifest_id=digest, probe_id=new_id)
    new_manifest_path = manifest_path.parent.with_name(new_id) / "probe_manifest.json"
    write(new_manifest_path, manifest)
    summary_path = saved / "results/step31_contract_probe_summary.json"
    summary = API.read(summary_path)
    summary.update(manifest_id=digest, probe_id=new_id)
    for report in summary["reports"]:
        report["outcome_path"] = report["outcome_path"].replace("contract_" + old_id[:20], new_id)
        record_path = (saved / report["outcome_path"]).with_name("job_record.json")
        record = API.read(record_path)
        record["manifest_id"] = digest
        write(record_path, seal(record))
    write(summary_path, summary)
    monkeypatch.setattr(API, "measure_blocked_request", lambda *args: {"local_candidate_fits": True, "fixture_only": True,
        "new_backend_render_confirmed": False})
    before = files(saved)
    first = API.prepare(saved)
    second = API.prepare(saved)
    assert first["configuration_id"] == second["configuration_id"]
    assert first["candidate_files"] == second["candidate_files"]
    assert first["question_echo_only_answers"] == 2
    assert first["new_model_calls"] == first["http_requests"] == first["query_encodings"] == 0
    assert first["candidate_only"] is True and first["new_runtime_executed"] is False
    assert all((saved / name).read_bytes() == content for name, content in before.items())


def test_unexecuted_software_evidence_does_not_start_preparation(saved):
    before = files(saved)
    with pytest.raises(ValueError, match="software checks"):
        API.prepare(saved, software_evidence={"status": "passed", "passed": 0, "files": {}})
    assert files(saved) == before

pytestmark = pytest.mark.requirement("31:bounded-lossless-operational-corrections")
