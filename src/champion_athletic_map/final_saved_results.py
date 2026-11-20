"""Read and verify the designated final results without generating or rescoring replies."""

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath

VERSION = "verified-final-saved-results-1"
STATUSES = {"met", "violated", "unknown", "not_applicable"}
METRIC_BOOLS = ("category_response_success", "automated_declared_checks_pass",
    "complete_request_fulfillment_verified", "strict_format_valid", "designated_workflow_completed")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative,
            "A saved-result path must be relative to the project.")
    parts = PurePosixPath(relative)
    require(not parts.is_absolute() and not set(parts.parts) & {".", ".."} and parts.as_posix() == relative,
            "A saved-result path leaves the project.")
    path = root / relative
    require(path.resolve() == path, "A saved-result file has an unexpected linked location.")
    return path


def strict_json(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "A saved-result JSON object repeats a key.")
            value[key] = item
        return value
    return json.loads(data, object_pairs_hook=unique,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("A saved-result number is not finite.")))


def module(root, name):
    path = checked(root, "src/champion_athletic_map/" + name + ".py")
    spec = importlib.util.spec_from_file_location("saved_final_results_" + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def verify_contracts(manifest):
    contracts = manifest["case_contracts"]
    body = deepcopy(contracts)
    declared = body.pop("contracts_id", None)
    require(declared == sha(packed(body)) and declared == manifest["case_contracts_id"],
            "The frozen final response-contract identity changed.")
    bindings = {row["profile_id"]: row for row in contracts["case_bindings"]}
    require(len(bindings) == len(contracts["case_bindings"]) == 200,
            "The final contract roster is missing or repeats a case.")
    require(set(bindings) == {row["profile_id"] for row in manifest["profiles"]},
            "The final contract and public case rosters differ.")
    for record in manifest["profiles"]:
        binding = bindings[record["profile_id"]]
        require(binding["public_record_canonical_sha256"] == sha(canonical(record))
            and binding["public_input_canonical_sha256"] == sha(canonical(record["input"])),
            "A final response contract refers to another public case version.")
        bundle = contracts["contract_bundles"][binding["contract_bundle_id"]]
        require(sha(canonical(bundle)) == binding["contract_bundle_id"]
                and sha(canonical(bundle["local_response_schema"])) == binding["local_response_schema_sha256"],
                "A final response contract uses a different local schema.")
    return bindings


def validate_checks(report):
    checks, parents = report.get("checks"), report.get("parent_checks")
    require(isinstance(checks, list) and checks and isinstance(parents, list) and parents,
            "A final assessment lacks its complete check evidence.")
    for rows in (checks, parents):
        require(len({row["check_id"] for row in rows}) == len(rows)
            and all(row.get("status") in STATUSES and type(row.get("required")) is bool
                    and isinstance(row.get("reason"), str) and row["reason"] for row in rows),
            "A final assessment has duplicate, missing or invalid check evidence.")
    require(set(report.get("expected_check_ids", [])) == {row["check_id"] for row in checks},
            "A saved assessment is missing declared check coverage.")
    coverage = report.get("parent_coverage")
    require(isinstance(coverage, dict), "A final assessment lacks parent-check coverage.")
    for label, required in (("required", True), ("advisory", False)):
        selected = [row for row in parents if row["required"] is required]
        counts = {status: sum(row["status"] == status for row in selected) for status in STATUSES}
        denominator = counts["met"] + counts["violated"] + counts["unknown"]
        expected = ((counts["met"] + counts["violated"]) / denominator if denominator else None)
        actual = coverage.get(label)
        require(isinstance(actual, dict) and all(actual.get(key) == value for key, value in counts.items())
                and actual.get("parent_checks") == len(selected)
                and actual.get("applicable_denominator") == denominator
                and actual.get("determinate_coverage") == expected,
                "A saved parent-check coverage total differs from its evidence.")


def validate_assessment(report, job, record, annotation, outcome, binding):
    require(report.get("assessment_execution") == "completed"
            and report.get("assessment_id") == job["job_id"],
            "A designated final assessment is unfinished or belongs to another job.")
    require(report.get("public_record_sha256") == sha(packed(record))
            and report.get("designated_outcome_sha256") == sha(canonical(outcome)),
            "A final assessment belongs to another case or designated reply.")
    require(report.get("exact_effective_case_schema_used") is True
            and report.get("public_case_frozen_binding_checked") is True
            and report.get("contract_bundle_id") == binding["contract_bundle_id"]
            and report.get("effective_local_schema_sha256") == binding["local_response_schema_sha256"],
            "A final assessment uses an earlier or different response contract.")
    metrics = report.get("final_metrics")
    require(isinstance(metrics, dict) and metrics.get("applicable_category") == annotation["case_category"]
            and all(type(metrics.get(key)) is bool for key in METRIC_BOOLS),
            "The complete final metric fields are missing or have invalid values.")
    require(type(metrics.get("automated_feasible_plan_success")) is bool
            if annotation["case_category"] == "feasible"
            else metrics.get("automated_feasible_plan_success") is None,
            "The full-verification measure has the wrong applicability.")
    require(metrics["designated_workflow_completed"] is (outcome.get("completion_valid") is True),
            "The saved completion measure differs from the designated workflow outcome.")
    validate_checks(report)


def verified_transport_counts(root, runner, manifest, case_index, execution):
    """Count complete journal observations and reconcile the saved transport receipt."""
    child = runner.transport_manifest(manifest, case_index)
    folder = "results/pilot/probes/" + child["probe_id"]
    relative = folder + "/http_events.jsonl"
    require(execution.get("transport_trace_path") == relative,
            "A final case refers to a different transport journal.")
    data = checked(root, relative).read_bytes()
    require(bool(data.strip()) and data.endswith(b"\n"),
            "A completed final case has an empty or unfinished transport journal.")
    events = [strict_json(line) for line in data.splitlines()]
    require(all(isinstance(row, dict) and row.get("manifest_id") == child["manifest_id"] for row in events),
            "A final transport journal contains another case or manifest.")
    starts = [row for row in events if row.get("event") == "http_started"]
    ends = [row for row in events if row.get("event") in {"http_finished", "http_exception"}]
    start_ids = [row.get("http_id") for row in starts]
    end_ids = [row.get("http_id") for row in ends]
    require(starts and all(isinstance(value, str) and value for value in start_ids + end_ids)
            and len(set(start_ids)) == len(start_ids) and len(set(end_ids)) == len(end_ids)
            and set(start_ids) == set(end_ids)
            and all(row.get("phase") in {"metadata", "render", "generation"} for row in starts)
            and all(row.get("unresolved") is not True for row in ends),
            "A final transport journal has missing, duplicate or unresolved request records.")
    counts = {phase + "_transport_attempts": sum(row["phase"] == phase for row in starts)
              for phase in ("metadata", "render", "generation")}
    files = {relative: sha(data)}
    summary_path = folder + "/transport_engine_summary.json"
    supplied = execution.get("transport_summary_path")
    require(supplied is None or supplied == summary_path, "A final case refers to a different transport summary.")
    path = checked(root, summary_path)
    if path.exists():
        raw = path.read_bytes()
        receipt = strict_json(raw)
        totals = receipt.get("cumulative_trace") or {}
        require(receipt.get("manifest_id") == child["manifest_id"]
                and totals.get("manifest_id") == child["manifest_id"]
                and all(type(totals.get(key)) is int and totals[key] == value for key, value in counts.items())
                and totals.get("http_requests") == len(starts)
                and totals.get("http_without_terminal_event") == []
                and totals.get("uncertain") is False,
                "The final transport summary disagrees with its complete request journal.")
        files[summary_path] = sha(raw)
        summary_present = True
    else:
        # A crash after the fourth terminal job but before the engine summary
        # can be recovered read-only. The caller still verifies all four native
        # job records and the complete journal, without inventing a zero count.
        require(execution.get("recovered_without_submission") is True,
                "A completed final case has no saved transport summary.")
        summary_present = False
    return {"counts": counts, "source_file_sha256": files,
            "transport_summary_present": summary_present,
            "recovered_journal_without_engine_summary": not summary_present}


def load_saved_comparison(root, *, summary_path="results/step33_final_comparison_summary.json", software_fixture=False):
    """Verify 800 saved outcomes and their existing assessments; write nothing."""
    root = Path(root).resolve()
    require(type(software_fixture) is bool, "The saved-result scope must be explicit.")
    if software_fixture:
        require(summary_path.startswith("results/testing/"),
                "Software result fixtures must remain in their explicit testing namespace.")
    files = {}
    def read(relative):
        path = checked(root, relative)
        data = path.read_bytes()
        files[relative] = sha(data)
        return strict_json(data)
    summary = read(summary_path)
    require(summary.get("software_fixture") is software_fixture
            and summary.get("status") == "final_jobs_recorded"
            and summary.get("completed_cases") == 200 and summary.get("recorded_jobs") == 800
            and summary.get("assessed_jobs") == 800 and summary.get("unresolved_jobs") == 0
            and summary.get("stop_reason") is None,
            "The final comparison is not 200 completed cases with 800 conclusive assessed outcomes.")
    runner = module(root, "final_comparison_runner")
    ledger_api = module(root, "common_response_preparation")
    manifest = read(summary["run_manifest_path"])
    require(manifest.get("software_fixture") is software_fixture
            and manifest.get("manifest_id") == summary.get("manifest_id")
            and manifest.get("package_directory") == summary.get("package_directory")
            and manifest.get("manifest_path") == summary["run_manifest_path"]
            and manifest.get("protocol", {}).get("final_protocol_frozen") is True,
            "The saved final comparison summary refers to another run or an unfinished protocol.")
    if software_fixture:
        require("software_fixture" in manifest["package_directory"],
                "A test result manifest lacks its explicit software-fixture namespace.")
    records, annotations = runner.validate_manifest(root, manifest)
    files.update(manifest["source_sha256"])
    for relative, digest in manifest.get("protocol", {}).get("review_source_sha256", {}).items():
        require(sha(checked(root, relative).read_bytes()) == digest,
                "The preselected team-review sample or rubric changed after setup.")
        files[relative] = digest
    if not software_fixture:
        setup = read("results/step33_final_run_setup_summary.json")
        require(setup.get("setup_id") == summary.get("setup_id")
                and setup.get("run_manifest_path") == summary["run_manifest_path"]
                and setup.get("software_fixture") is False and setup.get("final_protocol_frozen") is True,
                "The final outcomes differ from the recorded native run setup.")
    bindings = verify_contracts(manifest)
    ledger = ledger_api.pending_ledger({"annotations": manifest["annotations"], "jobs": manifest["planned_jobs"]})
    by_job = {row["job_id"]: row for row in ledger}
    rows, packets, packet_hashes, fixture_calls = [], [], set(), 0
    journal_calls, recovered_journals = 0, 0
    for number in range(1, 201):
        directory = manifest["package_directory"] + "/cases/case_" + str(number).zfill(3)
        execution = read(directory + "/execution.json")
        require(execution.get("stop_reason") is None and len(execution.get("outcomes", [])) == 4,
                "A saved final case is partial or stopped for review.")
        if not software_fixture:
            trace = verified_transport_counts(root, runner, manifest, number, execution)
            files.update(trace["source_file_sha256"])
            journal_calls += trace["counts"]["generation_transport_attempts"]
            recovered_journals += trace["recovered_journal_without_engine_summary"]
        packet = runner.validate_execution(root, manifest, number, execution)
        fixture_calls += execution["new_model_submissions"]
        if isinstance(packet, dict) and packet.get("packet_id"):
            digest = sha(canonical(packet))
            if digest not in packet_hashes:
                packet_hashes.add(digest)
                packets.append(deepcopy(packet))
        jobs = {row["job_id"]: row for row in manifest["planned_jobs"][(number - 1) * 4:number * 4]}
        for saved in execution["outcomes"]:
            job = jobs[saved["planned_job_id"]]
            record, outcome = records[job["profile_id"]], saved["outcome"]
            note = annotations[job["profile_id"]]
            require(outcome.get("status") != "unresolved" and saved.get("backend_completion_unresolved") is not True,
                    "An unresolved model attempt cannot become a designated completed outcome.")
            supplied = (outcome.get("response") or {}).get("authoritative_public_input")
            require(supplied is None or canonical(supplied) == canonical(record["input"]),
                    "A designated outcome contains different authoritative athlete information.")
            base = directory + "/assessment_" + str(job["planner_version"])
            paths = [base + ".json"]
            retries = sorted(checked(root, directory).glob("assessment_" + str(job["planner_version"]) + "_retry_*.json"))
            require([path.stem.rsplit("_", 1)[-1] for path in retries]
                    == [str(index).zfill(4) for index in range(1, len(retries) + 1)],
                    "The saved assessment retry history is missing or out of order.")
            paths.extend(path.relative_to(root).as_posix() for path in retries)
            current = by_job[job["job_id"]]
            for path in paths:
                report = read(path)
                current = ledger_api.record_assessment(current, outcome, report)
            validate_assessment(report, job, record, note, outcome, bindings[job["profile_id"]])
            require(current.get("metric_state") == "assessed", "A final result still has an incomplete external assessment.")
            by_job[job["job_id"]] = current
            seconds = saved.get("elapsed_seconds")
            require(seconds is None or type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0,
                    "A final elapsed-time observation is invalid.")
            output = ((outcome.get("response") or {}).get("model_output") or {})
            raw = output.get("raw_text")
            require(raw is None or isinstance(raw, str), "A designated raw reply is not text.")
            parsed = output.get("parsed_object")
            response_type = outcome.get("response_type") or (parsed.get("response_type") if isinstance(parsed, dict) else None)
            outcome_hash = sha(canonical(outcome))
            transport_path = saved.get("transport_record_path")
            if isinstance(transport_path, str):
                files[transport_path] = sha(checked(root, transport_path).read_bytes())
                outcome_path = (Path(transport_path).parent / "outcome.json").as_posix()
                files[outcome_path] = sha(checked(root, outcome_path).read_bytes())
            rows.append({"job_id": job["job_id"], "profile_id": job["profile_id"],
                "planner_version": job["planner_version"], "case_category": note["case_category"],
                "family_id": note["family_id"], "public_input": deepcopy(record["input"]),
                "public_record_sha256": sha(packed(record)), "designated_outcome_sha256": outcome_hash,
                "outcome_sha256": outcome_hash, "raw_text": raw,
                "raw_text_sha256": sha(raw.encode("utf-8")) if isinstance(raw, str) else None,
                "response_type": response_type,
                "format_valid": report["final_metrics"]["strict_format_valid"],
                "completion_valid": report["final_metrics"]["designated_workflow_completed"],
                "workflow_status": outcome.get("status"), "workflow_error": outcome.get("error"),
                "failed_stage": outcome.get("failed_stage"), "terminal_state": outcome.get("terminal_state"),
                "outcome_format_flag": outcome.get("format_valid"), "elapsed_seconds": seconds,
                "final_metrics": deepcopy(report["final_metrics"]), "parent_checks": deepcopy(report["parent_checks"]),
                "parent_coverage": deepcopy(report["parent_coverage"]), "checks": deepcopy(report["checks"]),
                "resources": deepcopy(report.get("resources")), "usage": deepcopy(outcome.get("usage")),
                "internal_review": ({key: deepcopy(outcome.get(key)) for key in
                    ("internally_accepted", "terminal_state", "revisions_used", "failed_stage", "error")}
                    if job["planner_version"] == 4 else None),
                "transport_record_path": transport_path,
                "transport_record_sha256": saved.get("transport_record_sha256"),
                "assessment_path": paths[-1], "assessment_sha256": sha(canonical(report))})
    ledger = [by_job[job["job_id"]] for job in manifest["planned_jobs"]]
    counts = ledger_api.ledger_counts(ledger)
    require(counts == summary["counts"], "The final summary totals differ from the saved designated assessments.")
    ledger_path = manifest["package_directory"] + "/ledger_latest.jsonl"
    data = checked(root, ledger_path).read_bytes()
    files[ledger_path] = sha(data)
    saved_ledger = [strict_json(line) for line in data.splitlines() if line.strip()]
    require(saved_ledger == ledger, "The saved final results table differs from its designated outcomes and assessments.")
    progress = read(manifest["package_directory"] + "/progress_summary.json")
    require(all(summary.get(key) == value for key, value in progress.items()),
            "The final summary pointer differs from the run's saved progress record.")
    cumulative = fixture_calls if software_fixture else runner._native_submissions(root, manifest)
    require(type(cumulative) is int and 0 <= cumulative <= manifest["maximum_generation_submissions_total"],
            "The recorded cumulative model-submission count exceeds its bound.")
    require(software_fixture or cumulative == journal_calls,
            "The complete journal counts disagree with the cumulative submission total.")
    return {"schema_version": VERSION, "rows": rows, "manifest": manifest, "summary": summary,
        "ledger": ledger, "reference_packets": packets, "source_file_sha256": files,
        "cumulative_model_submissions": cumulative,
        "cumulative_submission_count_source": "software_fixture_receipts" if software_fixture else "native_transport_journals",
        "last_batch_model_submissions": summary.get("new_model_submissions"),
        "verification": {"cases_verified": 200, "designated_outcomes_verified": 800,
            "existing_assessments_verified": 800, "current_ledger_matches_saved_assessments": True,
            "native_transport_journals_verified": 0 if software_fixture else 200,
            "recovered_journals_without_engine_summary": recovered_journals,
            "response_contract_bindings_verified": 200, "new_model_calls": 0,
            "responses_reassessed": 0, "new_query_encodings": 0,
            "earlier_drafts_substituted": False, "software_fixture": software_fixture}}
