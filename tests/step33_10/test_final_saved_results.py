"""Check saved-result joins using fictional, explicitly marked software receipts."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from champion_athletic_map import final_saved_results as saved
from champion_athletic_map import final_comparison_runner as runner
from champion_athletic_map import common_response_preparation as ledger_api


def write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(saved.canonical(value) + b"\n")


def check_row(identifier, status):
    return {"check_id": identifier, "status": status, "required": True, "reason": "Fictional software evidence."}


def parent_coverage(rows):
    def coverage(required):
        selected = [row for row in rows if row["required"] is required]
        counts = {status: sum(row["status"] == status for row in selected) for status in saved.STATUSES}
        n = counts["met"] + counts["violated"] + counts["unknown"]
        return {**counts, "parent_checks": len(selected), "applicable_denominator": n,
            "determinate_coverage": (counts["met"] + counts["violated"]) / n if n else None}
    return {"required": coverage(True), "advisory": coverage(False)}


@pytest.fixture
def complete(tmp_path):
    package = tmp_path / "src/champion_athletic_map"
    package.mkdir(parents=True)
    for source in (Path(runner.__file__), Path(ledger_api.__file__)):
        shutil.copyfile(source, package / source.name)
    write(tmp_path, "results/testing/review.json", {})
    write(tmp_path, "results/testing/schema.json", {})
    records, annotations, jobs, bindings = [], [], [], []
    schema = {"type": "object"}
    bundle = {"local_response_schema": schema}
    bundle_id = saved.sha(saved.canonical(bundle))
    seq = 0
    for category, count in runner.CATEGORIES.items():
        for _number in range(count):
            seq += 1
            record = {"profile_id": "fictional-final-case-" + str(seq),
                "schema_version": "software-fixture-only", "input": {"age": 15,
                    "athlete_request": "A fictional software request."}}
            digest = saved.sha(saved.packed(record))
            records.append(record)
            annotations.append({"profile_id": record["profile_id"], "public_record_sha256": digest,
                "case_category": category, "family_id": "software-family-" + str(seq),
                "case_authoring_accepted": True})
            for version in range(1, 5):
                jobs.append({"job_id": "final-planned-job:software" + str(seq) + "v" + str(version),
                    "profile_id": record["profile_id"], "planner_version": version, "case_sequence": seq,
                    "position_in_case": version, "public_record_sha256": digest})
            bindings.append({"profile_id": record["profile_id"],
                "public_record_canonical_sha256": saved.sha(saved.canonical(record)),
                "public_input_canonical_sha256": saved.sha(saved.canonical(record["input"])),
                "contract_bundle_id": bundle_id, "local_response_schema_sha256": saved.sha(saved.canonical(schema))})
    contracts = {"case_bindings": bindings, "contract_bundles": {bundle_id: bundle}}
    contracts["contracts_id"] = saved.sha(saved.packed(contracts))
    freeze = {"profiles": records, "annotations": annotations, "jobs": jobs,
        "summary": {"case_freeze_id": "software-freeze", "package_directory": "results/testing/software_fixture_cases",
            "software_fixture": True}, "contracts": contracts,
        "settings": {"timing_policy": {}, "budgets": {"maximum_submissions_per_case_without_food": 13,
            "maximum_submissions_per_case_with_food": 15,
            "maximum_configured_completed_submissions_for_200_cases_with_20_food_questions": 2640}}}
    manifest = runner.prepare_manifest(tmp_path, freeze=freeze,
        common_summary={"common_checker_software_ready": True, "case_freeze_id": "software-freeze", "preparation_id": "software-checks"},
        review_config_path="results/testing/review.json", public_schema_path="results/testing/schema.json",
        source_sha256={}, protocol={"final_protocol_frozen": True}, software_fixture=True)
    ledger = ledger_api.pending_ledger({"annotations": annotations, "jobs": jobs})
    by_job = {row["job_id"]: row for row in ledger}
    for number, record in enumerate(records, 1):
        note = annotations[number - 1]
        kind = {"feasible": "plan", "missing_information": "clarification",
                "conflicting_constraints": "constraint_conflict", "outside_scope": "outside_scope"}[note["case_category"]]
        directory = manifest["package_directory"] + "/cases/case_" + str(number).zfill(3)
        packet = {"packet_id": "software-packet-" + str(number), "payload": {"references": [], "food_lookup": []}}
        outcomes = []
        for job in jobs[(number - 1) * 4:number * 4]:
            outcome = {"completion_valid": True, "format_valid": True, "response_type": kind,
                "response": {"authoritative_public_input": deepcopy(record["input"]),
                    "model_output": {"raw_text": json.dumps({"response_type": kind, "explanation": "Fictional reply."}),
                        "parsed_object": {"response_type": kind}}}}
            outcomes.append({"planned_job_id": job["job_id"], "planner_version": job["planner_version"],
                "outcome": outcome, "reference_packet": None if job["planner_version"] == 1 else deepcopy(packet),
                "elapsed_seconds": 1.25})
            checks = [check_row("output_structure", "met"),
                      check_row("public_goal_fulfillment", "unknown" if kind == "plan" else "not_applicable")]
            metrics = {"automated_feasible_plan_success": False if kind == "plan" else None,
                "category_response_success": kind != "plan", "automated_declared_checks_pass": True,
                "complete_request_fulfillment_verified": kind != "plan", "strict_format_valid": True,
                "designated_workflow_completed": True, "applicable_category": note["case_category"]}
            report = {"assessment_id": job["job_id"], "assessment_execution": "completed",
                "public_record_sha256": job["public_record_sha256"],
                "designated_outcome_sha256": saved.sha(saved.canonical(outcome)),
                "exact_effective_case_schema_used": True, "public_case_frozen_binding_checked": True,
                "contract_bundle_id": bundle_id, "effective_local_schema_sha256": saved.sha(saved.canonical(schema)),
                "checks": checks, "expected_check_ids": [row["check_id"] for row in checks],
                "parent_checks": checks, "parent_coverage": parent_coverage(checks), "final_metrics": metrics}
            write(tmp_path, directory + "/assessment_" + str(job["planner_version"]) + ".json", report)
            by_job[job["job_id"]] = ledger_api.record_assessment(by_job[job["job_id"]], outcome, report)
        write(tmp_path, directory + "/execution.json", {"outcomes": outcomes, "stop_reason": None,
            "new_model_submissions": 4, "new_reference_encodings": 3, "software_fixture": True})
    ledger = [by_job[job["job_id"]] for job in jobs]
    path = tmp_path / manifest["package_directory"] / "ledger_latest.jsonl"
    path.write_bytes(b"".join(saved.canonical(row) + b"\n" for row in ledger))
    progress = {"status": "final_jobs_recorded", "software_fixture": True, "completed_cases": 200,
        "recorded_jobs": 800, "assessed_jobs": 800, "unresolved_jobs": 0, "stop_reason": None,
        "manifest_id": manifest["manifest_id"], "new_model_submissions": 4, "counts": ledger_api.ledger_counts(ledger)}
    write(tmp_path, manifest["package_directory"] + "/progress_summary.json", progress)
    summary_path = "results/testing/final_comparison_summary.json"
    summary = {**progress, "run_manifest_path": manifest["manifest_path"], "package_directory": manifest["package_directory"]}
    write(tmp_path, summary_path, summary)
    return tmp_path, summary_path, manifest


def load(complete):
    root, summary_path, _manifest = complete
    return saved.load_saved_comparison(root, summary_path=summary_path, software_fixture=True)


def first_path(complete, filename):
    root, _summary_path, manifest = complete
    return root / manifest["package_directory"] / "cases/case_001" / filename


def test_complete_result_set_has_fixed_roster_and_cumulative_counts(complete):
    result = load(complete)
    assert len(result["rows"]) == len(result["ledger"]) == 800
    assert result["cumulative_model_submissions"] == 800
    assert result["last_batch_model_submissions"] == 4
    assert result["verification"]["new_model_calls"] == result["verification"]["responses_reassessed"] == 0
    assert result["rows"][0]["raw_text"] == '{"response_type": "plan", "explanation": "Fictional reply."}'


def test_edited_designated_raw_reply_is_rejected(complete):
    path = first_path(complete, "execution.json")
    value = saved.strict_json(path.read_bytes())
    value["outcomes"][0]["outcome"]["response"]["model_output"]["raw_text"] = "changed reply"
    path.write_bytes(saved.canonical(value))
    with pytest.raises(ValueError, match="different saved outcome"):
        load(complete)


def test_old_or_missing_response_schema_binding_is_rejected(complete):
    path = first_path(complete, "assessment_1.json")
    value = saved.strict_json(path.read_bytes())
    value["effective_local_schema_sha256"] = "wrong-schema"
    path.write_bytes(saved.canonical(value))
    with pytest.raises(ValueError, match="different response contract"):
        load(complete)


def test_duplicate_outcome_cannot_fill_a_missing_workflow(complete):
    path = first_path(complete, "execution.json")
    value = saved.strict_json(path.read_bytes())
    value["outcomes"][-1] = deepcopy(value["outcomes"][0])
    path.write_bytes(saved.canonical(value))
    with pytest.raises(ValueError, match="repeats a designated"):
        load(complete)


def test_missing_assessment_does_not_become_a_model_failure(complete):
    first_path(complete, "assessment_1.json").unlink()
    with pytest.raises(FileNotFoundError):
        load(complete)


def test_unresolved_backend_result_is_not_completed(complete):
    path = first_path(complete, "execution.json")
    value = saved.strict_json(path.read_bytes())
    value["outcomes"][0]["outcome"]["status"] = "unresolved"
    path.write_bytes(saved.canonical(value))
    with pytest.raises(ValueError, match="unresolved model attempt"):
        load(complete)


def test_changed_final_ledger_is_rejected(complete):
    root, _summary, manifest = complete
    path = root / manifest["package_directory"] / "ledger_latest.jsonl"
    rows = [saved.strict_json(line) for line in path.read_bytes().splitlines()]
    rows[0]["automated_declared_checks_pass"] = False
    path.write_bytes(b"".join(saved.canonical(row) + b"\n" for row in rows))
    with pytest.raises(ValueError, match="results table differs"):
        load(complete)


def test_fixture_cannot_be_read_as_native_result(complete):
    root, summary_path, _manifest = complete
    with pytest.raises(ValueError, match="not 200 completed"):
        saved.load_saved_comparison(root, summary_path=summary_path)


def test_missing_check_coverage_is_rejected(complete):
    path = first_path(complete, "assessment_1.json")
    value = saved.strict_json(path.read_bytes())
    value["expected_check_ids"].append("missing-software-check")
    path.write_bytes(saved.canonical(value))
    with pytest.raises(ValueError, match="declared check coverage"):
        load(complete)


def journal_fixture(root):
    child = {"probe_id": "software-fixture-journal", "manifest_id": "software-child"}
    api = SimpleNamespace(transport_manifest=lambda _manifest, _index: child)
    folder = "results/pilot/probes/" + child["probe_id"]
    trace_path = folder + "/http_events.jsonl"
    receipt_path = folder + "/transport_engine_summary.json"
    events = []
    for phase in ("metadata", "render", "generation"):
        events.extend({"event": kind, "manifest_id": child["manifest_id"], "http_id": "software-" + phase,
                       "phase": phase} for kind in ("http_started", "http_finished"))
    path = root / trace_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(saved.canonical(row) + b"\n" for row in events))
    totals = {phase + "_transport_attempts": 1 for phase in ("metadata", "render", "generation")}
    receipt = {"manifest_id": child["manifest_id"], "cumulative_trace": {**totals,
        "manifest_id": child["manifest_id"], "http_requests": 3,
        "http_without_terminal_event": [], "uncertain": False}}
    write(root, receipt_path, receipt)
    execution = {"transport_trace_path": trace_path, "transport_summary_path": receipt_path}
    return api, execution, events, receipt


def test_missing_or_unfinished_journal_never_becomes_zero_submissions(tmp_path):
    api, execution, _events, _receipt = journal_fixture(tmp_path)
    path = tmp_path / execution["transport_trace_path"]
    path.unlink()
    with pytest.raises(FileNotFoundError):
        saved.verified_transport_counts(tmp_path, api, {}, 1, execution)
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="empty or unfinished"):
        saved.verified_transport_counts(tmp_path, api, {}, 1, execution)


def test_journal_totals_bind_receipt_and_recovery_keeps_observed_count(tmp_path):
    api, execution, _events, receipt = journal_fixture(tmp_path)
    result = saved.verified_transport_counts(tmp_path, api, {}, 1, execution)
    assert result["counts"]["generation_transport_attempts"] == 1
    assert len(result["source_file_sha256"]) == 2
    receipt["cumulative_trace"]["generation_transport_attempts"] = 0
    write(tmp_path, execution["transport_summary_path"], receipt)
    with pytest.raises(ValueError, match="disagrees"):
        saved.verified_transport_counts(tmp_path, api, {}, 1, execution)
    (tmp_path / execution["transport_summary_path"]).unlink()
    with pytest.raises(ValueError, match="no saved transport summary"):
        saved.verified_transport_counts(tmp_path, api, {}, 1, execution)
    execution["recovered_without_submission"] = True
    recovered = saved.verified_transport_counts(tmp_path, api, {}, 1, execution)
    assert recovered["counts"]["generation_transport_attempts"] == 1
    assert recovered["recovered_journal_without_engine_summary"] is True


def test_duplicate_missing_or_unresolved_http_records_are_rejected(tmp_path):
    api, execution, events, _receipt = journal_fixture(tmp_path)
    variations = [events + [deepcopy(events[0])], events[:-1], deepcopy(events)]
    variations[-1][-1]["unresolved"] = True
    for rows in variations:
        (tmp_path / execution["transport_trace_path"]).write_bytes(
            b"".join(saved.canonical(row) + b"\n" for row in rows))
        with pytest.raises(ValueError, match="request records"):
            saved.verified_transport_counts(tmp_path, api, {}, 1, execution)
