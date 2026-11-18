"""Replay the actual saved sixteen-outcome corpus without any transport."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import urllib.request

import pytest

HERE = Path(__file__).resolve().parent
ROOT = next((p for p in HERE.parents if (p / "src/champion_athletic_map/pilot_probe.py").is_file()),
            HERE.parent / "work_step30/project/folder-before-step-30")
SOURCE = HERE / "offline_corrections.py"
if not SOURCE.is_file():
    SOURCE = ROOT / "src/champion_athletic_map/offline_corrections.py"
INPUT = ROOT if (ROOT / "results/step31_reviewed_probe_summary.json").is_file() else HERE / "review_input"


def load(path, name):
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    result.__spec__.loader.exec_module(result)
    return result


API = load(SOURCE, "offline_corrections_tested")


@pytest.fixture(autouse=True)
def no_transport(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Offline correction attempted transport or an external worker.")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", blocked)
    monkeypatch.setattr(subprocess, "run", blocked)
    monkeypatch.setattr(subprocess.Popen, "__init__", blocked)


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("offline_correction")
    wanted = {API.SOURCE_SUMMARY}
    summary = API.read(INPUT / API.SOURCE_SUMMARY)
    for case in summary["cases"]:
        for report in case["reports"]:
            path = Path(report["outcome_path"])
            wanted.update(str(path.parent / name) for name in ("outcome.json", "job_record.json", "job_request.json"))
            folder = path.parent.parents[1]
            wanted.add(str(folder / "http_events.jsonl"))
            if report["planner_version"] != 1:
                reference = INPUT / folder / "references" / report["job_id"]
                wanted.update(p.relative_to(INPUT).as_posix() for p in reference.rglob("*") if p.is_file())
            if report["planner_version"] == 4:
                outcome = API.read(INPUT / path)
                revisions = {r["result"]["call_id"] for r in outcome["roles"] if r["stage"] == "revision"}
                events = [json.loads(line) for line in (INPUT / folder / "http_events.jsonl").read_text().splitlines()]
                wanted.update(e["request_path"].replace("\\", "/") for e in events
                              if e.get("call_id") in revisions and e.get("phase") == "render" and e["event"] == "http_started")
    for relative in wanted:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(INPUT / relative, target)
    for name in (*API.NEW_COMPONENTS, *API.OLD_COMPONENTS):
        source = HERE / (name + ".py")
        if not source.is_file():
            source = ROOT / "src/champion_athletic_map" / (name + ".py")
        target = root / "src/champion_athletic_map" / (name + ".py")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    tokenizer = next((ROOT / "artifacts/language_model/tokenizers").glob("*/tokenizer_manifest.json"))
    manifest = API.read(tokenizer)
    assets = {tokenizer.relative_to(ROOT).as_posix(), manifest["source_native_metadata"]["relative_path"],
              "src/champion_athletic_map/llm.py"}
    assets.update((tokenizer.parent / name).relative_to(ROOT).as_posix() for name in manifest["payload_hashes"])
    for relative in assets:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return root


def test_actual_five_revisions_fit_and_sixteen_food_outcomes_stay_separate(project):
    result = API.execute(project)
    assert result["saved_outcomes_checked"] == result["food_outcomes_checked"] == 16
    assert result["saved_revision_requests_checked"] == result["candidate_revision_requests_fitting_locally"] == 5
    assert result["original_revision_requests_over_budget"] == 3
    assert [r["old_body_tokens"] for r in result["revision_measurements"]] == [6784, 6628, 6333, 5763, 5738]
    assert [r["new_input_tokens_including_boundary"] for r in result["revision_measurements"]] == [5194, 5122, 4844, 4337, 4312]
    assert all(r["original_model_check_view_preserved_exactly"] for r in result["revision_measurements"])
    assert all(r["full_check_report_rows"] == 41 for r in result["revision_measurements"])
    assert all(r["saved_independent_report_rows"] == 43 for r in result["revision_measurements"])
    assert [r["original_model_check_view_rows"] for r in result["revision_measurements"]] == [16, 30, 16, 18, 18]
    assert all(r["original_model_check_view_distinct_ids"] == 41 for r in result["revision_measurements"])
    assert result["food_requested_outcomes"] == 4
    assert result["food_field_completeness_met"] == 0
    assert result["food_numeric_content_met"] == result["food_correct_fact_elsewhere"] == result["food_no_designated_response"] == 1
    food = API.read(project / result["food_validation_path"])["outcomes"]
    v2 = next(r for r in food if r["case_index"] == 13 and r["planner_version"] == 2)
    assert v2["diagnostic"]["numeric_answer_status"] == "met"
    assert v2["diagnostic"]["field_answer_status"] == "violated"
    for row in food:
        old = next(q for q in row["original_food_findings"] if q["check_id"] == "food_source_grounding")
        new = next(q for q in row["prospective_food_findings"] if q["check_id"] == "food_source_grounding")
        assert old == new
    assert result["new_model_calls"] == result["http_requests"] == result["query_encoder_processes"] == result["jobs_started"] == 0
    assert result["new_backend_render_confirmed"] is False and result["final_scores_created"] is False
    API.verify(project, result["input_sha256"])


def test_repeated_preparation_keeps_source_hashes_and_archives_observations(project):
    first = API.execute(project)
    before = {name: (project / name).read_bytes() for name in first["input_sha256"]}
    second = API.execute(project)
    assert first == second
    evidence = {"status": "passed", "passed": 1, "files": {}, "elapsed_seconds": 0.1}
    third = API.execute(project, software_evidence=evidence)
    evidence["elapsed_seconds"] = 0.2
    fourth = API.execute(project, software_evidence=evidence)
    assert first["correction_id"] == third["correction_id"] == fourth["correction_id"]
    assert third["software_evidence"] != fourth["software_evidence"]
    assert all((project / name).read_bytes() == data for name, data in before.items())


def test_modified_captured_render_request_is_rejected(project):
    result = API.read(project / API.SUMMARY)
    path = project / result["revision_measurements"][0]["captured_request_path"]
    before = path.read_bytes()
    try:
        value = API.read(path)
        value["messages"][0]["content"] += " Changed."
        path.write_bytes(API.canonical(value))
        with pytest.raises(ValueError, match="transport hash"):
            API.execute(project)
    finally:
        path.write_bytes(before)


def test_render_only_flag_cannot_be_changed_even_with_updated_capture_hash(project):
    result = API.read(project / API.SUMMARY)
    request_path = project / result["revision_measurements"][0]["captured_request_path"]
    events_path = request_path.parent.parent / "http_events.jsonl"
    old_request, old_events = request_path.read_bytes(), events_path.read_bytes()
    try:
        request = API.read(request_path)
        request["_debug_render_only"] = False
        request_path.write_bytes(API.canonical(request))
        events = [json.loads(line) for line in old_events.splitlines()]
        for event in events:
            if event.get("request_path", "").replace("\\", "/") == request_path.relative_to(project).as_posix():
                event["request_sha256"] = API.sha(request_path.read_bytes())
        events_path.write_bytes(b"".join(API.canonical(e) + b"\n" for e in events))
        with pytest.raises(ValueError, match="render-only"):
            API.execute(project)
    finally:
        request_path.write_bytes(old_request)
        events_path.write_bytes(old_events)


def test_changed_designated_outcome_is_not_repaired_or_substituted(project):
    summary = API.read(project / API.SOURCE_SUMMARY)
    path = project / summary["cases"][0]["reports"][0]["outcome_path"]
    before = path.read_bytes()
    try:
        value = API.read(path)
        value["unexpected_change"] = True
        path.write_bytes(API.canonical(value))
        with pytest.raises(ValueError, match="designated saved outcome"):
            API.execute(project)
    finally:
        path.write_bytes(before)


def test_failed_software_evidence_cannot_create_a_candidate(project):
    before = (project / API.SUMMARY).read_bytes()
    with pytest.raises(ValueError, match="software checks"):
        API.execute(project, software_evidence={"status": "failed", "passed": 0})
    assert (project / API.SUMMARY).read_bytes() == before


pytestmark = pytest.mark.requirement("31:saved-probe-offline-corrections")
