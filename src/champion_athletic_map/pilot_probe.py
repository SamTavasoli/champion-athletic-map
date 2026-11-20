"""Run one configuration-bound development case through four local workflows."""

from contextlib import nullcontext
from datetime import datetime, timezone
import csv
import hashlib
import importlib.metadata
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
from time import perf_counter
from uuid import uuid4


PROBE_VERSION = "step31-operational-probe-1"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def save(path, value, *, immutable=False):
    path = Path(path)
    data = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        if path.read_bytes() != data:
            raise ValueError("An earlier probe artifact differs and was preserved: " + path.name)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".probe-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_module(root, name):
    path = Path(root) / "src/champion_athletic_map" / (name + ".py")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("probe_" + name, path))
    result.__spec__.loader.exec_module(result)
    return result


def bound(root, relative, expected):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or sha(path.read_bytes()) != expected:
        raise ValueError("A probe dependency changed: " + relative)
    return path.read_bytes()


def environment():
    packages = {}
    for name in ("numpy", "pandas", "jsonschema", "scikit-learn", "tokenizers", "regex", "torch", "sentence-transformers"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": sys.version, "platform": platform.platform(), "packages": packages}


def prepare_probe(root, *, environment_record=None):
    """Fix the case, configuration and balanced order before submitting requests."""
    root = Path(root).resolve()
    summary = json.loads((root / "results/step31_case_review_summary.json").read_bytes())
    if (summary.get("reviewed_cases") != 20 or summary.get("public_profiles_versioned") != 20
            or summary.get("software_evidence", {}).get("status") != "passed"
            or summary.get("protocol_frozen") is not False):
        raise ValueError("Step 31-2 must contain the completed case and schedule software checks.")
    for relative, expected in summary["review_files"].items():
        bound(root, relative, expected)
    for relative, expected in summary["software_evidence"]["files"].items():
        bound(root, relative, expected)
    files = summary["review_files"]
    def read_suffix(suffix):
        name = next(name for name in files if name.endswith(suffix))
        return name, bound(root, name, files[name])
    config_path, raw = read_suffix("/case_review_config.json")
    config = json.loads(raw)
    schema_path, raw = read_suffix("/public_profile_schema.json")
    schema = json.loads(raw)
    _, raw = read_suffix("/public_profiles.jsonl")
    profiles = [json.loads(line) for line in raw.splitlines() if line.strip()]
    _, raw = read_suffix("/private_case_review.json")
    reviews = {row["profile_id"]: row for row in json.loads(raw)["rows"]}
    for relative, expected in config["component_sha256"].items():
        bound(root, relative, expected)
    for relative, expected in config["parent_preparation_files"].items():
        bound(root, relative, expected)
    # This choice uses stated development facts, before any new probe outcome.
    eligible = [record for record in profiles if record["input"].get("age") == 13
        and (record["input"].get("space") or {}).get("court_access") == "full_court"
        and record["input"].get("food_question") and record["input"].get("participants_available") is not None
        and record["input"].get("equipment") and record["input"].get("availability")]
    if not eligible:
        raise ValueError("The recorded operational-probe selection rule has no matching development case.")
    public = eligible[0]
    review = reviews[public["profile_id"]]
    if review.get("review_disposition") != "include_as_provisional_diagnostic_case":
        raise ValueError("This selected case has no recorded development diagnostic review.")
    job_path = next(name for name in config["parent_preparation_files"] if name.endswith("/planned_pilot_jobs.csv"))
    jobs = [row for row in csv.DictReader(io.StringIO((root / job_path).read_text(encoding="utf-8")))
        if row["profile_id"] == public["profile_id"]]
    jobs.sort(key=lambda row: int(row["position_in_case"]))
    if len(jobs) != 4 or {int(row["planner_version"]) for row in jobs} != {1, 2, 3, 4}:
        raise ValueError("The probe must preserve this case's four prepared workflow positions.")
    sources = {path.relative_to(root).as_posix(): sha(path.read_bytes())
        for path in sorted((root / "src/champion_athletic_map").rglob("*.py"))}
    for name in ("version1_config.json", "version2_config.json", "version3_config.json", "version4_config.json",
            "version4_candidate_focused_config.json", "shared_reference_source_config.json"):
        relative = "artifacts/planners/" + name
        sources[relative] = sha((root / relative).read_bytes())
    integration_path = "artifacts/language_model/integration_config.json"
    sources[integration_path] = sha((root / integration_path).read_bytes())
    integration = json.loads((root / integration_path).read_bytes())
    identity = {"schema_version": PROBE_VERSION, "mode": "provisional_unscored_operational_probe",
        "case_review_id": summary["case_review_id"], "case_review_files": files,
        "public_record": public, "public_record_sha256": sha(canonical(public)),
        "selection_policy": "first_selected_age13_full_court_case_with_stated_resources_and_explicit_food_question",
        "prepared_jobs": jobs, "module_and_config_sha256": sources,
        "environment": environment_record if environment_record is not None else environment(),
        "model_configuration": integration,
        "limits": {"jobs": 4, "maximum_generation_submissions": 15, "maximum_revisions_v4": 2,
            "reference_encoder_processes_per_fresh_reference_job": 1, "fresh_reference_jobs": 3,
            "timeouts_seconds": integration["timeouts_seconds"], "workflow_deadline_seconds": None},
        "timing_policy": {"application_response_cache": "off_for_new_jobs_verified_reuse_for_continuation",
            "native_prompt_cache": "observe_if_reported_otherwise_unknown",
            "reference_preparation": "fresh_for_each_new_reference_enabled_job",
            "primary_job_elapsed": "before_fresh_reference_preparation_through_saved_terminal_outcome",
            "interrupted_job_elapsed": "unavailable_current_observed_segment_retained",
            "setup_and_independent_assessment_outside_primary_timing": True},
        "accepted_study_profiles": 0, "independent_quality_scoring": "pending", "protocol_frozen": False}
    fingerprint = sha(canonical(identity))
    probe_id = "probe_" + fingerprint[:20]
    manifest = {**identity, "probe_id": probe_id, "manifest_id": fingerprint,
        "case_review_config_path": config_path, "public_schema_path": schema_path,
        "jobs": [{"job_id": "p31p_" + fingerprint[:16] + "_v" + row["planner_version"],
            "call_id": "p31p_" + fingerprint[:16] + "_v" + row["planner_version"],
            "planner_version": int(row["planner_version"]), "position_in_case": int(row["position_in_case"]),
            "parent_prepared_job_id": row["job_id"]} for row in jobs]}
    pointer = root / "results/pilot/probes/first_operational_probe.json"
    if pointer.exists() and json.loads(pointer.read_bytes()).get("manifest_id") != fingerprint:
        raise ValueError("This probe already has another recorded configuration. Preserve it and record an explicit amendment before changing the run.")
    manifest_path = root / "artifacts/pilot/probes" / probe_id / "probe_manifest.json"
    save(manifest_path, manifest, immutable=True)
    save(pointer, {"manifest_id": fingerprint, "probe_id": probe_id,
        "manifest_path": manifest_path.relative_to(root).as_posix()}, immutable=True)
    return manifest


def result_view(result):
    output = ((result.get("response") or {}).get("model_output") or {}).get("parsed_object")
    return {"response_type": result.get("response_type") or (output.get("response_type") if isinstance(output, dict) else None),
        "format_valid": result.get("format_valid") is True, "completion_valid": result.get("completion_valid") is True,
        "status": result.get("status"), "terminal_state": result.get("terminal_state"),
        "internal_review": "passed" if result.get("internally_accepted") is True else
            "needs review" if result.get("terminal_state") == "revision_limit_reached" else
            "not completed" if result.get("planner_version") == 4 else None,
        "revisions_used": result.get("revisions_used", 0), "failed_stage": result.get("failed_stage"),
        "error": result.get("error"), "independent_quality_assessment": "pending"}


def saved_references(root, work, manifest):
    """Verify completed preparation without loading the encoder or model."""
    if not work.exists():
        return None
    completion = work / "completed.json"
    if not completion.is_file():
        if (work / "failure.json").is_file():
            return None
        raise ValueError("The saved reference preparation has no conclusive completion record.")
    value = json.loads(completion.read_bytes())
    body = {key: item for key, item in value.items() if key != "completion_record_sha256"}
    if value.get("completion_record_sha256") != sha(canonical(body)) or value.get("configuration_id") != manifest["manifest_id"]:
        raise ValueError("The saved reference completion identity changed.")
    for relative, expected in value["artifact_sha256"].items():
        path = (work / relative).resolve()
        if not path.is_relative_to(work.resolve()) or sha(path.read_bytes()) != expected:
            raise ValueError("A saved reference preparation artifact changed.")
    request = json.loads((work / "request.json").read_bytes())
    packet = json.loads((work / "packet.json").read_bytes())
    if (request.get("public_record") != manifest["public_record"] or request.get("configuration_id") != manifest["manifest_id"]
            or value.get("request_sha256") != sha(canonical(request)) or packet.get("packet_id") != value.get("packet_id")):
        raise ValueError("Saved reference evidence belongs to another public case or configuration.")
    return {"packet": packet, "trace": json.loads((work / "trace.json").read_bytes()), "cache_reused": True,
        "packet_path": (work / "packet.json").relative_to(root).as_posix(),
        "reference_record_path": completion.relative_to(root).as_posix(),
        "preparation_seconds": value["preparation_seconds"], "counts": value["counts"],
        "new_counts": {key: 0 for key in value["counts"]}, "request_sha256": value["request_sha256"],
        "configuration_id": value["configuration_id"]}


def seal_record(record):
    value = dict(record)
    value["job_record_sha256"] = sha(canonical(record))
    return value


def verify_job(root, manifest, job, folder, record):
    body = {key: value for key, value in record.items() if key != "job_record_sha256"}
    result = json.loads((folder / "outcome.json").read_bytes())
    if (record.get("job_record_sha256") != sha(canonical(body)) or record.get("manifest_id") != manifest["manifest_id"]
            or record.get("job_id") != job["job_id"] or record.get("planner_version") != job["planner_version"]
            or record.get("public_record_sha256") != manifest["public_record_sha256"]
            or record.get("outcome_sha256") != sha((folder / "outcome.json").read_bytes())
            or record.get("outcome") != result_view(result)):
        raise ValueError("A completed probe job's identity or outcome record changed.")
    references = saved_references(root, folder.parents[1] / "references" / job["job_id"], manifest)
    if job["planner_version"] != 1 and result.get("failed_stage") != "reference_preparation" and references is None:
        raise ValueError("A reference-enabled outcome has no verified completed reference preparation.")
    embedded = record.get("reference_record")
    if bool(embedded) != bool(references) or embedded and any(embedded.get(key) != references.get(key)
            for key in ("packet", "trace", "request_sha256", "configuration_id", "counts", "preparation_seconds")):
        raise ValueError("The job's embedded reference summary differs from its saved preparation.")
    return result


def execute_probe(root, manifest, *, runtime_factory=None, references_factory=None, trace_module=None,
                  clock=perf_counter, emit=print, software_evidence=None):
    root = Path(root).resolve()
    if software_evidence is not None:
        if software_evidence.get("status") != "passed" or software_evidence.get("passed", 0) <= 0:
            raise ValueError("The probe software checks must pass before live execution.")
        for relative, expected in software_evidence["files"].items():
            bound(root, relative, expected)
    for relative, expected in manifest["module_and_config_sha256"].items():
        bound(root, relative, expected)
    for relative, expected in manifest["case_review_files"].items():
        bound(root, relative, expected)
    folder = root / "results/pilot/probes" / manifest["probe_id"]
    folder.mkdir(parents=True, exist_ok=True)
    trace_api = trace_module or load_module(root, "pilot_trace")
    trace = trace_api.PilotTrace(root, folder, manifest_id=manifest["manifest_id"], max_generation_submissions=15)
    trace.assert_safe()
    before = trace.summary()
    runtime = reference_preparer = None
    setup = {"status": "not_needed_for_whole_job_reuse", "elapsed_seconds": 0}
    records, reused, new_encoder_processes, stop_reason = [], 0, 0, None
    canonical_packet_id = None
    probe_owner = "pilot_" + manifest["manifest_id"][:20] + "_" + uuid4().hex[:8]
    with trace_api.execution_gate(root, probe_owner, manifest_sha256=manifest["manifest_id"], trace=trace):
        for job in manifest["jobs"]:
            version, job_id = job["planner_version"], job["job_id"]
            job_folder = folder / "jobs" / job_id
            job_request = {"manifest_id": manifest["manifest_id"], "job": job,
                "public_record_sha256": manifest["public_record_sha256"]}
            terminal = job_folder / "job_record.json"
            if terminal.is_file():
                if json.loads((job_folder / "job_request.json").read_bytes()) != job_request:
                    raise ValueError("A completed probe job belongs to different inputs.")
                record = json.loads(terminal.read_bytes())
                verify_job(root, manifest, job, job_folder, record)
                if record.get("reference_record"):
                    reference_record = record["reference_record"]
                    canonical_packet_id = canonical_packet_id or reference_record["packet"]["packet_id"]
                    if reference_record["packet"]["packet_id"] != canonical_packet_id:
                        raise ValueError("The matched reference packets differ.")
                records.append(record)
                reused += 1
                print_job(record, reused=True, emit=emit)
                if record.get("stop_probe"):
                    stop_reason = record["stop_probe"]
                    break
                continue
            if (job_folder / "outcome.json").is_file():
                if json.loads((job_folder / "job_request.json").read_bytes()) != job_request:
                    raise ValueError("A saved terminal outcome belongs to different inputs.")
                result = json.loads((job_folder / "outcome.json").read_bytes())
                reference_record = saved_references(root, folder / "references" / job_id, manifest) if version != 1 else None
                if version != 1 and reference_record is None and result.get("failed_stage") != "reference_preparation":
                    raise ValueError("The saved outcome has no verified reference preparation.")
                stop_reason = ("reference_preparation_needs_attention" if result.get("failed_stage") == "reference_preparation"
                    else "unresolved_backend_outcome" if result.get("status") == "unresolved" else None)
                record = seal_record({"schema_version": PROBE_VERSION, "manifest_id": manifest["manifest_id"],
                    "job_id": job_id, "call_id": job["call_id"], "planner_version": version,
                    "position_in_case": job["position_in_case"], "public_record_sha256": manifest["public_record_sha256"],
                    "outcome_sha256": sha((job_folder / "outcome.json").read_bytes()), "outcome": result_view(result),
                    "elapsed_seconds": None, "this_execution_segment_seconds": None, "prior_attempt_interrupted": True,
                    "recovered_from_saved_outcome": True, "reference_record": reference_record, "stop_probe": stop_reason,
                    "independent_quality_assessment": "pending", "protocol_frozen": False})
                save(terminal, record, immutable=True)
                records.append(record)
                reused += 1
                if reference_record:
                    packet_id = reference_record["packet"]["packet_id"]
                    if canonical_packet_id is not None and packet_id != canonical_packet_id:
                        raise ValueError("The matched reference packets differ.")
                    canonical_packet_id = packet_id
                print_job(record, reused=True, emit=emit)
                if stop_reason:
                    break
                continue
            trace.assert_safe()
            if runtime is None:
                started_setup = clock()
                config = json.loads((root / manifest["case_review_config_path"]).read_bytes())
                schema = json.loads((root / manifest["public_schema_path"]).read_bytes())
                make_runtime = runtime_factory or load_module(root, "pilot_runtime").build_runtime
                runtime = make_runtime(root, config, schema)
                make_references = references_factory or load_module(root, "pilot_references").FreshReferencePreparer
                reference_preparer = make_references(root, runtime.tools, runtime.planners[2].client, runtime.reference_policy)
                setup = {"status": "completed", "elapsed_seconds": clock() - started_setup,
                    "runtime_manifest": runtime.manifest, "reference_setup": reference_preparer.setup_record}
                save(folder / "setup" / (uuid4().hex[:12] + ".json"), setup, immutable=True)
            interrupted = job_folder.exists()
            job_folder.mkdir(parents=True, exist_ok=True)
            save(job_folder / "job_request.json", job_request, immutable=True)
            attempt_id = uuid4().hex[:12]
            save(job_folder / "attempts" / (attempt_id + "_started.json"),
                {"manifest_id": manifest["manifest_id"], "interrupted_prior_attempt": interrupted,
                 "recorded_at": datetime.now(timezone.utc).isoformat()}, immutable=True)
            began = clock()
            reference_record = None
            failed_stage = None
            result = None
            try:
                if version != 1:
                    failed_stage = "reference_preparation"
                    reference_record = reference_preparer.prepare(manifest["public_record"], folder / "references" / job_id,
                        job_id=job_id, configuration_id=manifest["manifest_id"], expected_packet_id=canonical_packet_id)
                    packet = reference_record["packet"]
                    canonical_packet_id = canonical_packet_id or packet["packet_id"]
                    if packet["packet_id"] != canonical_packet_id:
                        raise ValueError("The matched reference packets differ.")
                    count = reference_record.get("new_counts", {}).get("query_encoder_processes")
                    new_encoder_processes = None if count is None or new_encoder_processes is None else new_encoder_processes + count
                failed_stage = "workflow"
                with trace.instrument(runtime.planners[version], job_id, version):
                    if version == 1:
                        result = runtime.planners[version].generate(manifest["public_record"], job["call_id"])
                    else:
                        result = runtime.planners[version].generate(manifest["public_record"], packet, job["call_id"])
                if not isinstance(result, dict):
                    raise TypeError("The workflow returned no terminal result object.")
                failed_stage = None
            except Exception as error:
                result = {"status": "unresolved" if trace.is_uncertain() else "blocked",
                    "planner_version": version, "completion_valid": False, "format_valid": False,
                    "failed_stage": failed_stage, "error": type(error).__name__ + ": " + str(error)}
                if failed_stage == "reference_preparation":
                    stop_reason = "reference_preparation_needs_attention"
                    new_encoder_processes = None
            uncertain = result.get("status") == "unresolved" or trace.is_uncertain()
            if uncertain:
                stop_reason = "unresolved_backend_outcome"
            save(job_folder / "outcome.json", result, immutable=True)
            ended = clock()
            record = seal_record({"schema_version": PROBE_VERSION, "manifest_id": manifest["manifest_id"],
                "job_id": job_id, "call_id": job["call_id"], "planner_version": version,
                "position_in_case": job["position_in_case"], "public_record_sha256": manifest["public_record_sha256"],
                "outcome_sha256": sha((job_folder / "outcome.json").read_bytes()), "outcome": result_view(result),
                "elapsed_seconds": None if interrupted else ended - began,
                "this_execution_segment_seconds": ended - began, "prior_attempt_interrupted": interrupted,
                "reference_record": reference_record, "stop_probe": stop_reason,
                "independent_quality_assessment": "pending", "protocol_frozen": False})
            save(terminal, record, immutable=True)
            records.append(record)
            print_job(record, reused=False, emit=emit)
            if stop_reason:
                break
            trace.raise_if_uncertain()
    after = trace.summary()
    summary = {"schema_version": PROBE_VERSION, "probe_id": manifest["probe_id"], "manifest_id": manifest["manifest_id"],
        "status": "stopped_for_review" if stop_reason else "four_jobs_recorded_with_quality_pending",
        "scheduled_probe_jobs": 4, "recorded_probe_jobs": len(records), "unsubmitted_prepared_jobs": 80,
        "representative_pilot_jobs_run": 0,
        "whole_jobs_reused_this_execution": reused, "new_generation_transport_attempts":
            after["generation_transport_attempts"] - before["generation_transport_attempts"],
        "new_render_transport_attempts": after["render_transport_attempts"] - before["render_transport_attempts"],
        "new_metadata_transport_attempts": after["metadata_transport_attempts"] - before["metadata_transport_attempts"],
        "new_reference_encoder_processes": new_encoder_processes,
        "cumulative_trace": after, "setup_this_execution": setup, "jobs": records,
        "responses_with_valid_format": sum(row["outcome"]["format_valid"] for row in records),
        "completed_workflows": sum(row["outcome"]["completion_valid"] for row in records),
        "stop_reason": stop_reason, "independent_quality_assessment": "pending",
        "accepted_study_profiles": 0, "representative_pilot_completed": False, "protocol_frozen": False,
        "operational_generation_ready": False, "app_generation_enabled": False}
    summary["software_evidence"] = software_evidence or {"status": "not_recorded_by_this_invocation"}
    execution_id = uuid4().hex[:12]
    summary["runtime_usage"] = save_usage(root, folder / "executions" / execution_id, after)
    save(folder / "executions" / (execution_id + ".json"), summary, immutable=True)
    save(root / "results/step31_first_probe_summary.json", summary)
    return summary


def print_job(record, *, reused=False, emit=print):
    value, seconds = record["outcome"], record["elapsed_seconds"]
    parts = ["Planner " + str(record["planner_version"]) + ": " + str(value["response_type"] or value["status"] or "unavailable"),
        "Format: " + ("valid" if value["format_valid"] else "needs review")]
    if record["planner_version"] == 4:
        parts.append("Internal review: " + str(value["internal_review"]))
    parts.append("Time: " + (str(round(seconds, 1)) + " s" if seconds is not None else "incomplete observation"))
    if reused:
        parts.append("saved")
    emit(" | ".join(parts))
    if value.get("error"):
        emit("  " + str(value.get("failed_stage") or "Issue") + ": " + str(value["error"])[:180])


def save_usage(root, folder, trace):
    """Keep native usage and observed role timing in separate columns."""
    folder.mkdir(parents=True, exist_ok=True)
    fields = ["call_id", "status", "prompt_eval_count", "eval_count", "prompt_eval_cached_count",
        "native_total_duration_ns", "native_load_duration_ns", "observed_first_role_wall_seconds",
        "first_observation_cached", "local_input_tokens_with_boundary_reserve", "input_ceiling_after_output_and_margin",
        "rendered_body_tokens", "runner_context_length", "runner_size_vram_bytes"]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for call_id, item in sorted(trace["role_usage"].items()):
        usage = item["usage"]
        saved = root / "results/integration/model_calls" / call_id / "result.json"
        result = json.loads(saved.read_bytes()) if saved.is_file() else {}
        context = result.get("context") or {}
        runner = (result.get("runtime") or {}).get("runner") or {}
        writer.writerow({"call_id": call_id, "status": item["status"],
            **{key: usage.get(key) for key in ("prompt_eval_count", "eval_count", "prompt_eval_cached_count")},
            "native_total_duration_ns": usage.get("total_duration"), "native_load_duration_ns": usage.get("load_duration"),
            "observed_first_role_wall_seconds": item["observed_first_role_wall_seconds"],
            "first_observation_cached": item["first_observation_cached"],
            **{key: context.get(key) for key in ("local_input_tokens_with_boundary_reserve", "input_ceiling_after_output_and_margin", "rendered_body_tokens")},
            "runner_context_length": runner.get("context_length"), "runner_size_vram_bytes": runner.get("size_vram")})
    path = folder / "runtime_usage.csv"
    path.write_bytes(output.getvalue().encode("utf-8"))
    return {"path": path.relative_to(root).as_posix(), "sha256": sha(path.read_bytes()), "rows": len(trace["role_usage"]),
        "native_cache_unknown_when_blank": True, "runner_vram_is_not_total_gpu_utilization": True}


def print_summary(summary):
    print("Recorded jobs:", str(summary["recorded_probe_jobs"]) + "/4", "| New model submissions:", summary["new_generation_transport_attempts"],
        "| Saved jobs reused:", summary["whole_jobs_reused_this_execution"])
    print("Plan quality: awaiting independent checks | Full pilot and protocol: pending")
    if summary["stop_reason"]:
        print("Stopped:", summary["stop_reason"])
    print("Saved: results/step31_first_probe_summary.json")
