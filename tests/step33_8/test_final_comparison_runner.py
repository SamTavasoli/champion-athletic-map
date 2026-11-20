"""We exercise final batching with fictional fixtures and no model transport."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from champion_athletic_map import final_comparison_runner as runner


@pytest.fixture
def setup(tmp_path):
    package = tmp_path / "src/champion_athletic_map"
    package.mkdir(parents=True)
    original = Path(runner.__file__).with_name("common_response_preparation.py")
    shutil.copyfile(original, package / original.name)
    (tmp_path / "review.json").write_text("{}\n")
    (tmp_path / "schema.json").write_text("{}\n")
    profiles, annotations, jobs = [], [], []
    sequence = 0
    for category, count in runner.CATEGORIES.items():
        for number in range(count):
            sequence += 1
            record = {"profile_id": "software-" + str(sequence), "schema_version": "software-fixture-only",
                      "input": {"athlete_request": "Fictional software request.", "age": 15}}
            digest = runner.sha(runner.packed(record))
            profiles.append(record)
            annotations.append({"profile_id": record["profile_id"], "public_record_sha256": digest,
                "case_category": category, "family_id": "software-family-" + str(sequence), "case_authoring_accepted": True})
            order = (1, 2, 4, 3) if sequence % 2 else (4, 1, 3, 2)
            jobs.extend({"job_id": "final-planned-job:software" + str(sequence) + "v" + str(version),
                "profile_id": record["profile_id"], "planner_version": version,
                "case_sequence": sequence, "position_in_case": position,
                "public_record_sha256": digest} for position, version in enumerate(order, 1))
    freeze = {"profiles": profiles, "annotations": annotations, "jobs": jobs,
        "summary": {"case_freeze_id": "software-freeze", "package_directory": "results/testing/software-freeze", "software_fixture": True},
        "contracts": {"contracts_id": "software-contracts"}, "settings": {"timing_policy": {"test": "no-clock-observation"},
            "budgets": {"maximum_submissions_per_case_without_food": 13, "maximum_submissions_per_case_with_food": 15,
                "maximum_configured_completed_submissions_for_200_cases_with_20_food_questions": 2640}}}
    common = {"common_checker_software_ready": True, "case_freeze_id": "software-freeze", "preparation_id": "software-common"}
    manifest = runner.prepare_manifest(tmp_path, freeze=freeze, common_summary=common,
        review_config_path="review.json", public_schema_path="schema.json", source_sha256={},
        protocol={"final_protocol_frozen": True}, software_fixture=True)
    return tmp_path, manifest


class Assessor:
    def __init__(self, root, manifest):
        self.manifest = manifest

    def assess(self, public_record, outcome, truth_packet, *, assessment_id, case_annotation):
        completed = outcome.get("completion_valid") is True
        feasible = case_annotation["case_category"] == "feasible"
        return {"assessment_id": assessment_id, "assessment_execution": "completed",
            "designated_outcome_sha256": runner.sha(runner.canonical(outcome)),
            "public_record_sha256": runner.sha(runner.packed(public_record)),
            "final_metrics": {"applicable_category": case_annotation["case_category"],
                "automated_feasible_plan_success": completed if feasible else None,
                "category_response_success": completed, "strict_format_valid": completed,
                "designated_workflow_completed": completed,
                "automated_declared_checks_pass": completed, "complete_request_fulfillment_verified": completed}}


def execute(root, manifest, index):
    selected = manifest["planned_jobs"][(index - 1) * 4:index * 4]
    packet = {"packet_id": "software-packet-" + str(index), "payload": {"references": [], "food_lookup": []}}
    return {"outcomes": [{"planned_job_id": row["job_id"], "planner_version": row["planner_version"],
        "outcome": {"completion_valid": True, "format_valid": True, "response_type": "plan", "software_fixture": True},
        "reference_packet": None if row["planner_version"] == 1 else deepcopy(packet), "elapsed_seconds": 1.0} for row in selected],
        "new_model_submissions": 4, "new_reference_encodings": 3, "stop_reason": None, "software_fixture": True}


def run(root, manifest, **kwargs):
    return runner.run_next_batch(root, manifest, software_evidence={"status": "passed", "passed": 1, "files": {}},
        case_executor=execute, assessor_factory=Assessor, execution_authorized=True, emit=lambda _: None, **kwargs)


def test_preparation_keeps_all_800_jobs_unexecuted(setup):
    root, manifest = setup
    assert len(manifest["planned_jobs"]) == 800
    assert manifest["execution_authorized_by_preparation"] is False
    assert not (root / manifest["package_directory"] / "cases").exists()


def test_final_run_requires_explicit_run_call(setup):
    root, manifest = setup
    with pytest.raises(ValueError, match="explicit run call"):
        runner.run_next_batch(root, manifest, software_evidence={}, case_executor=execute, assessor_factory=Assessor)


def test_saved_results_are_reused_without_repeating_jobs(setup):
    root, manifest = setup
    first = run(root, manifest, max_cases=1)
    second = run(root, manifest, max_cases=1)
    assert first["completed_cases"] == 1 and first["recorded_jobs"] == 4
    assert second["completed_cases"] == 2 and second["recorded_jobs"] == 8
    assert second["saved_cases_reused"] == 1 and second["new_model_submissions"] == 4
    assert all(row["all_cases_denominator"] == 200 for row in second["counts"].values())


def test_interrupted_case_is_never_automatically_resubmitted(setup):
    root, manifest = setup
    folder = root / manifest["package_directory"] / "cases/case_001"
    runner.save_once(folder / "started.json", {"manifest_id": manifest["manifest_id"], "case_index": 1})
    summary = run(root, manifest, max_cases=1)
    assert summary["stop_reason"] == "interrupted_final_case_preserved_without_resubmission"
    assert summary["new_model_submissions"] == summary["recorded_jobs"] == 0


def test_packet_mismatch_stops_and_preserves_started_record(setup):
    root, manifest = setup
    def unequal(root, manifest, index):
        result = execute(root, manifest, index)
        next(row for row in result["outcomes"] if row["planner_version"] == 3)["reference_packet"]["payload"]["changed"] = True
        return result
    summary = runner.run_next_batch(root, manifest, software_evidence={"status": "passed", "passed": 1, "files": {}},
        case_executor=unequal, assessor_factory=Assessor, execution_authorized=True, max_cases=1, emit=lambda _: None)
    assert summary["stop_reason"] == "final_execution_needs_review"
    assert not (root / manifest["package_directory"] / "cases/case_001/execution.json").exists()


def test_failed_model_outcome_remains_in_fixed_denominator(setup):
    root, manifest = setup
    def failed(root, manifest, index):
        result = execute(root, manifest, index)
        result["outcomes"][0]["outcome"]["completion_valid"] = False
        return result
    summary = runner.run_next_batch(root, manifest, software_evidence={"status": "passed", "passed": 1, "files": {}},
        case_executor=failed, assessor_factory=Assessor, execution_authorized=True, max_cases=1, emit=lambda _: None)
    assert summary["completed_cases"] == 1 and summary["assessed_jobs"] == 4
    assert summary["counts"]["1"]["feasible_failures"] == 1
    assert summary["counts"]["1"]["feasible_plan_denominator"] == 150


def test_unresolved_backend_attempt_is_incomplete_not_a_terminal_failure(setup):
    root, manifest = setup
    def unresolved(root, manifest, index):
        result = execute(root, manifest, index)
        row = result["outcomes"][-1]
        row["backend_completion_unresolved"] = True
        row["outcome"].update(status="unresolved", completion_valid=False)
        result["stop_reason"] = "unresolved_backend_outcome"
        return result
    summary = runner.run_next_batch(root, manifest, software_evidence={"status": "passed", "passed": 1, "files": {}},
        case_executor=unresolved, assessor_factory=Assessor, execution_authorized=True, max_cases=1, emit=lambda _: None)
    assert summary["recorded_jobs"] == 4 and summary["assessed_jobs"] == 3
    assert summary["unresolved_jobs"] == 1 and summary["completed_cases"] == 0
    assert summary["stop_reason"] == "unresolved_backend_outcome"
    assert summary["counts"]["3"]["feasible_failures"] == 0
    assert summary["counts"]["3"]["feasible_incomplete"] == 150


def test_scheduled_version_order_and_windows_safe_call_ids(setup):
    _, manifest = setup
    child = runner.transport_manifest(manifest, 1)
    assert [job["planner_version"] for job in child["jobs"]] == [1, 2, 4, 3]
    assert all(":" not in job["job_id"] + job["call_id"] for job in child["jobs"])
    assert [job["planned_job_id"] for job in child["jobs"]] == [row["job_id"] for row in manifest["planned_jobs"][:4]]


def test_missing_case_or_workflow_is_rejected(setup):
    _, manifest = setup
    with pytest.raises(ValueError, match="fixed 200 cases and 800"):
        runner.validate_roster(manifest["profiles"], manifest["annotations"], manifest["planned_jobs"][:-1])


def test_nonfood_case_cannot_submit_fourteen_generations(setup):
    root, manifest = setup
    execution = execute(root, manifest, 1)
    execution["new_model_submissions"] = 14
    with pytest.raises(ValueError, match="bounded generation"):
        runner.validate_execution(root, manifest, 1, execution)


@pytest.mark.parametrize("lookups", [[], [{"status": "not_found", "data": None}],
    [{"status": "found", "data": {"description": ""}}]])
def test_missing_external_food_truth_is_incomplete_not_model_failure(setup, lookups):
    root, manifest = setup
    record = deepcopy(manifest["profiles"][0])
    record["input"]["food_question"] = "How much protein is recorded in a fictional food?"
    note = manifest["annotations"][0]
    completed = {"completion_valid": True}
    report = runner._assess_saved(Assessor(root, manifest), record, completed,
        {"payload": {"references": [], "food_lookup": lookups}}, assessment_id="software-food", annotation=note)
    assert report["assessment_execution"] == "error" and report["final_metrics"] is None
    assert report["model_error_claimed"] is False
    failed = runner._assess_saved(Assessor(root, manifest), record, {"completion_valid": False},
        {"payload": {"references": [], "food_lookup": []}}, assessment_id="software-failed-workflow", annotation=note)
    assert failed["assessment_execution"] == "completed"
    assert failed["final_metrics"]["automated_feasible_plan_success"] is False


def test_fixture_manifest_cannot_select_native_executor(setup):
    root, manifest = setup
    with pytest.raises(ValueError, match="software-fixture namespace"):
        runner.run_next_batch(root, manifest, software_evidence={"status": "passed", "passed": 1, "files": {}}, execution_authorized=True)


def test_changed_frozen_order_is_rejected(setup):
    root, manifest = setup
    changed = deepcopy(manifest)
    changed["planned_jobs"][0]["position_in_case"] = 2
    with pytest.raises(ValueError, match="manifest identity"):
        runner.validate_manifest(root, changed)


def test_external_error_retry_uses_saved_outcomes_without_model_work(setup):
    root, manifest = setup
    class InterruptedAssessor(Assessor):
        def assess(self, *args, **kwargs):
            return {"assessment_execution": "error", "error": "Synthetic external check interruption."}
    first = runner.run_next_batch(root, manifest, software_evidence={"status": "passed", "passed": 1, "files": {}},
        case_executor=execute, assessor_factory=InterruptedAssessor, execution_authorized=True, max_cases=1, emit=lambda _: None)
    folder = root / manifest["package_directory"] / "cases/case_001"
    original = (folder / "assessment_1.json").read_bytes()
    def never_execute(*args):
        raise AssertionError("An external-assessment retry must never start model work.")
    second = runner.run_next_batch(root, manifest, software_evidence={"status": "passed", "passed": 1, "files": {}},
        case_executor=never_execute, assessor_factory=Assessor, execution_authorized=True,
        retry_assessments=True, max_cases=1, emit=lambda _: None)
    assert first["assessed_jobs"] == 0 and first["recorded_jobs"] == 4
    assert second["assessed_jobs"] == 4 and second["new_model_submissions"] == 0
    assert second["new_cases_attempted"] == 0 and second["assessment_only_retry"] is True
    assert (folder / "assessment_1.json").read_bytes() == original
    assert (folder / "assessment_1_retry_0001.json").is_file()
    rows = [json.loads(line) for line in
        (root / manifest["package_directory"] / "ledger_latest.jsonl").read_bytes().splitlines()]
    assert rows[0]["assessment_history"][0]["error"] == "Synthetic external check interruption."


@pytest.fixture
def native_saved_case(setup):
    """Write fictional transport receipts using the actual saved-job verifier only."""
    root, manifest = setup
    shutil.copyfile(Path(runner.__file__).with_name("pilot_probe.py"), root / "src/champion_athletic_map/pilot_probe.py")
    engine = runner.module(root, "pilot_probe")
    manifest = deepcopy(manifest)
    manifest["software_fixture"] = False
    child = runner.transport_manifest(manifest, 1)
    folder = root / "results/pilot/probes" / child["probe_id"]
    execution = execute(root, manifest, 1)
    execution["software_fixture"] = False
    for job, row in zip(child["jobs"], execution["outcomes"]):
        work = folder / "jobs" / job["job_id"]
        result = row["outcome"]
        result["response"] = {"authoritative_public_input": child["public_record"]["input"]}
        runner.save_once(work / "outcome.json", result)
        references = None
        if job["planner_version"] != 1:
            ref_folder = folder / "references" / job["job_id"]
            request = {"public_record": child["public_record"], "configuration_id": child["manifest_id"]}
            runner.save_once(ref_folder / "request.json", request)
            runner.save_once(ref_folder / "packet.json", row["reference_packet"])
            runner.save_once(ref_folder / "trace.json", {})
            receipt = {"configuration_id": child["manifest_id"], "request_sha256": runner.sha(runner.canonical(request)),
                "packet_id": row["reference_packet"]["packet_id"], "preparation_seconds": 1.0,
                "counts": {"query_encoder_processes": 1},
                "artifact_sha256": {name: runner.sha((ref_folder / name).read_bytes()) for name in ("request.json", "packet.json", "trace.json")}}
            receipt["completion_record_sha256"] = runner.sha(runner.canonical(receipt))
            runner.save_once(ref_folder / "completed.json", receipt)
            references = engine.saved_references(root, ref_folder, child)
        record = engine.seal_record({"manifest_id": child["manifest_id"], "job_id": job["job_id"],
            "planner_version": job["planner_version"], "public_record_sha256": child["public_record_sha256"],
            "outcome_sha256": runner.sha((work / "outcome.json").read_bytes()), "outcome": engine.result_view(result),
            "reference_record": references, "elapsed_seconds": 1.0})
        runner.save_once(work / "job_record.json", record)
        row["transport_record_path"] = (work / "job_record.json").relative_to(root).as_posix()
        row["transport_record_sha256"] = runner.sha((work / "job_record.json").read_bytes())
    return root, manifest, execution


def test_native_saved_execution_matches_actual_immutable_receipts(native_saved_case):
    root, manifest, execution = native_saved_case
    assert runner.validate_execution(root, manifest, 1, execution)["packet_id"] == "software-packet-1"
    recovered = runner._recover_complete_native_case(root, manifest, 1)
    assert recovered["new_model_submissions"] == recovered["new_reference_encodings"] == 0
    assert recovered["recovered_without_submission"] is True


@pytest.mark.parametrize("changed", ["outcome", "packet", "elapsed"])
def test_native_receipt_cannot_change_designated_reply_packet_or_timing(native_saved_case, changed):
    root, manifest, execution = native_saved_case
    altered = deepcopy(execution)
    row = next(row for row in altered["outcomes"] if row["planner_version"] == 2)
    if changed == "outcome":
        row["outcome"]["completion_valid"] = False
    elif changed == "packet":
        row["reference_packet"]["payload"]["changed"] = True
    else:
        row["elapsed_seconds"] = 0.01
    with pytest.raises(ValueError, match="immutable designated transport"):
        runner.validate_execution(root, manifest, 1, altered)
