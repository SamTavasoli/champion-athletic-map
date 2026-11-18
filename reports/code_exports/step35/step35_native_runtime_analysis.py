"""Read hash-bound native runtime evidence without importing any model runtime.

HTTP generation starts are submissions/transport attempts, not proof of backend
acceptance. Logical call IDs, repeated role invocations, and cached reads remain
different quantities. Missing native evidence always stays unavailable.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

PHASES = ("metadata", "render", "generation")
TOKEN_KEYS = ("prompt_eval_count", "eval_count", "prompt_eval_cached_count")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _strict_json(raw):
    def unique(items):
        result={}
        for key,value in items:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key]=value
        return result
    def reject_nonfinite(value):
        raise ValueError("Nonfinite JSON number: " + value)
    return json.loads(raw,object_pairs_hook=unique,parse_constant=reject_nonfinite)


class _EvidenceError(ValueError):
    pass


class _MissingEvidence(_EvidenceError):
    pass


def analyze_runtime_details(root, rows, source_file_sha256, *, expected_generation_submissions=2636):
    """Return native counts, usage coverage, and input hashes; never write files.

    ``rows`` are saved_outcomes rows. ``source_file_sha256`` is the frozen
    original-file byte-hash inventory, not canonical JSON object hashes.
    ``expected_generation_submissions`` is the frozen summary's cumulative
    submission count (2636 for the actual 800-job run); tests may supply another.
    """
    root = Path(root).resolve()
    rows = list(rows)
    by_job = {r["job_id"]: r for r in rows}
    versions = sorted({r["planner_version"] for r in rows})
    observed_hashes, missing, errors, cases, calls = {}, [], [], [], []
    jobs_seen, calls_seen = set(), set()
    metrics = {v: Counter() for v in versions}
    references = defaultdict(list)
    role_invocations_global = 0
    saved_role_reads_global = 0
    receipt_cases = 0

    def read(relative, *, journal=False):
        if not isinstance(relative, str):
            raise _EvidenceError("Missing evidence path")
        p = PurePosixPath(relative)
        if p.is_absolute() or any(part in ("..", ".") for part in p.parts) or "\\" in relative or ":" in relative:
            raise _EvidenceError("Unsafe evidence path: " + relative)
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise _EvidenceError("Evidence path leaves root: " + relative)
        expected = source_file_sha256.get(relative)
        if not isinstance(expected, str):
            raise _MissingEvidence("Path is not in frozen source-file hashes: " + relative)
        if not path.is_file():
            raise _MissingEvidence("Native file is absent: " + relative)
        raw = path.read_bytes()
        if _sha(raw) != expected:
            raise _EvidenceError("File-byte SHA256 mismatch: " + relative)
        observed_hashes[relative] = expected
        try:
            if journal:
                if not raw.strip() or not raw.endswith(b"\n"):
                    raise _EvidenceError("Empty or unterminated HTTP journal: " + relative)
                return [_strict_json(line) for line in raw.splitlines()]
            return _strict_json(raw)
        except (ValueError, UnicodeError) as error:
            raise _EvidenceError("Invalid saved JSON: " + relative + ": " + str(error)) from error

    execution_paths = sorted(path for path in source_file_sha256
        if path.endswith("/execution.json") and "/cases/case_" in path)
    if len(by_job) != len(rows):
        errors.append("Duplicate designated saved job IDs")
    if not execution_paths:
        missing.append("No native case execution.json paths are bound in the supplied source-file inventory.")

    for execution_path in execution_paths:
        local_calls, local_jobs, local_references = [], [], []
        try:
            execution = read(execution_path)
            saved_rows = execution.get("outcomes")
            if execution.get("stop_reason") is not None or not isinstance(saved_rows, list) or len(saved_rows) != 4:
                raise _EvidenceError("Case is stopped or does not contain four designated outcomes: " + execution_path)
            if not all(isinstance(s, dict) and s.get("planned_job_id") in by_job for s in saved_rows):
                # Only analyze cases belonging to the requested population.
                if all(isinstance(s, dict) and s.get("planned_job_id") not in by_job for s in saved_rows):
                    continue
                raise _EvidenceError("Case mixes requested and unidentified saved jobs: " + execution_path)
            journal_path = execution.get("transport_trace_path")
            journal = read(journal_path, journal=True)
            starts, ends = {}, {}
            for event in journal:
                if not isinstance(event, dict):
                    raise _EvidenceError("Journal contains a non-object event: " + journal_path)
                target = starts if event.get("event")=="http_started" else ends if event.get("event") in ("http_finished", "http_exception") else None
                if target is not None:
                    http_id = event.get("http_id")
                    if not isinstance(http_id, str) or not http_id or http_id in target:
                        raise _EvidenceError("Missing/duplicate HTTP identifier: " + journal_path)
                    target[http_id] = event
            if not starts or set(starts) != set(ends):
                raise _EvidenceError("HTTP starts and terminal events are not one-to-one: " + journal_path)
            manifests = {event.get("manifest_id") for event in journal}
            if len(manifests)!=1 or None in manifests:
                raise _EvidenceError("Journal has missing/mixed native manifest IDs: " + journal_path)
            native_manifest = next(iter(manifests))
            native_jobs = {}
            for saved in saved_rows:
                planned = saved["planned_job_id"]
                row = by_job[planned]
                if planned in jobs_seen or planned in local_jobs:
                    raise _EvidenceError("Duplicate designated job across native cases: " + planned)
                if saved.get("planner_version") != row["planner_version"]:
                    raise _EvidenceError("Planner identity mismatch: " + planned)
                outcome = saved.get("outcome")
                if not isinstance(outcome, dict) or _sha(_canonical(outcome)) != row["designated_outcome_sha256"]:
                    raise _EvidenceError("Native execution designated outcome mismatch: " + planned)
                path = saved.get("transport_record_path")
                if path != row.get("transport_record_path") or saved.get("transport_record_sha256") != row.get("transport_record_sha256"):
                    raise _EvidenceError("Native job-record binding differs from saved outcome: " + planned)
                record = read(path)
                if observed_hashes[path] != row["transport_record_sha256"]:
                    raise _EvidenceError("Native job-record byte hash differs from designated saved binding: " + planned)
                body = {k:v for k,v in record.items() if k!="job_record_sha256"}
                if record.get("job_record_sha256") != _sha(_canonical(body)):
                    raise _EvidenceError("Native job-record canonical seal mismatch: " + planned)
                native_id = record.get("job_id")
                if (not isinstance(native_id, str) or native_id in native_jobs
                        or record.get("manifest_id") != native_manifest
                        or record.get("planner_version") != row["planner_version"]):
                    raise _EvidenceError("Native job identity mismatch: " + planned)
                native_outcome_path = str(PurePosixPath(path).parent / "outcome.json")
                native_outcome = read(native_outcome_path)
                if (record.get("outcome_sha256") != observed_hashes[native_outcome_path]
                        or _canonical(native_outcome) != _canonical(outcome)):
                    raise _EvidenceError("Native outcome file differs from execution: " + planned)
                native_jobs[native_id] = (planned, row["planner_version"])
                local_jobs.append(planned)
                local_references.append((row["planner_version"], planned, record.get("reference_record")))
            per_call = {}
            phase_counts = Counter()
            for http_id, event in starts.items():
                terminal = ends[http_id]
                identity = ("manifest_id", "job_id", "planner_version", "call_id", "stage", "phase", "endpoint")
                if any(event.get(k)!=terminal.get(k) for k in identity):
                    raise _EvidenceError("HTTP terminal identity differs from its start: " + http_id)
                if terminal.get("unresolved") is True:
                    raise _EvidenceError("Unresolved native HTTP observation: " + http_id)
                phase = event.get("phase")
                if phase not in PHASES or event.get("job_id") not in native_jobs:
                    raise _EvidenceError("Unknown phase/native job in journal: " + http_id)
                planned, version = native_jobs[event["job_id"]]
                if event.get("planner_version") != version:
                    raise _EvidenceError("HTTP planner and native job disagree: " + http_id)
                call_id, stage = event.get("call_id"), event.get("stage")
                if not isinstance(call_id,str) or not call_id or not isinstance(stage,str) or not stage:
                    raise _EvidenceError("HTTP call/stage identity is missing: " + http_id)
                if call_id in calls_seen:
                    raise _EvidenceError("Logical call ID reused across native cases: " + call_id)
                call = per_call.setdefault(call_id, {"call_id":call_id,"planned_job_id":planned,"native_job_id":event["job_id"],
                    "planner_version":version,"stage":stage,"phase_counts":Counter(),"http_errors":0})
                if (call["planned_job_id"],call["planner_version"],call["stage"]) != (planned,version,stage):
                    raise _EvidenceError("Logical call maps to different jobs/stages: " + call_id)
                call["phase_counts"][phase] += 1
                call["http_errors"] += terminal["event"]=="http_exception"
                phase_counts[phase] += 1
            if any(c["phase_counts"][phase]>1 for c in per_call.values() for phase in ("render","generation")):
                raise _EvidenceError("A logical role repeats a render/generation transport despite the frozen no-resubmission trace policy: " + journal_path)
            summary_path = execution.get("transport_summary_path")
            if summary_path is None:
                summary_path = str(PurePosixPath(journal_path).parent / "transport_engine_summary.json")
            receipt = None
            try:
                receipt = read(summary_path)
            except _MissingEvidence:
                if execution.get("recovered_without_submission") is not True:
                    raise
            role_usage = {}
            receipt_role_invocations = receipt_saved_reads = None
            if receipt is not None:
                totals = receipt.get("cumulative_trace") or {}
                if (receipt.get("manifest_id") != native_manifest or totals.get("manifest_id") != native_manifest
                        or totals.get("http_requests") != len(starts) or totals.get("http_without_terminal_event") != []
                        or totals.get("uncertain") is not False
                        or any(totals.get(phase+"_transport_attempts") != phase_counts[phase] for phase in PHASES)):
                    raise _EvidenceError("Transport summary disagrees with native journal: " + summary_path)
                generated = sorted(cid for cid,c in per_call.items() if c["phase_counts"]["generation"])
                if totals.get("generation_call_ids") != generated:
                    raise _EvidenceError("Summary generation call IDs differ from journal: " + summary_path)
                role_usage = totals.get("role_usage") or {}
                if not isinstance(role_usage,dict) or not set(role_usage).issubset(per_call):
                    raise _EvidenceError("Role usage contains an unmapped call ID: " + summary_path)
                if any(not isinstance(item,dict) or item.get("charged_once_by_call_id") is not True for item in role_usage.values()):
                    raise _EvidenceError("Role usage does not preserve once-per-call accounting: " + summary_path)
                if totals.get("unique_recorded_roles") != len(role_usage):
                    raise _EvidenceError("Summary logical-role usage count differs: " + summary_path)
                receipt_role_invocations = totals.get("role_invocations")
                receipt_saved_reads = totals.get("saved_role_reads")
                if type(receipt_role_invocations) is not int or type(receipt_saved_reads) is not int or min(receipt_role_invocations,receipt_saved_reads)<0:
                    raise _EvidenceError("Invalid role-invocation/cache-read totals: " + summary_path)
            for cid, call in sorted(per_call.items()):
                usage_item = role_usage.get(cid)
                usage = usage_item.get("usage") if isinstance(usage_item,dict) else None
                native = usage if isinstance(usage,dict) else {}
                local_calls.append({k:v for k,v in call.items() if k!="phase_counts"} | {
                    **{phase+"_transport_attempts":call["phase_counts"][phase] for phase in PHASES},
                    "role_usage_recorded":isinstance(usage_item,dict),
                    **{k:native.get(k) if type(native.get(k)) is int and native[k]>=0 else None for k in TOKEN_KEYS},
                    "native_total_duration_ns":native.get("total_duration") if _number(native.get("total_duration")) else None,
                    "observed_first_role_wall_seconds":usage_item.get("observed_first_role_wall_seconds") if isinstance(usage_item,dict) and _number(usage_item.get("observed_first_role_wall_seconds")) else None,
                    "first_observation_cached":usage_item.get("first_observation_cached") if isinstance(usage_item,dict) else None,
                    "status":usage_item.get("status") if isinstance(usage_item,dict) else None})
            # Commit a case only after all its bindings and reconciliations pass.
            jobs_seen.update(local_jobs)
            calls_seen.update(c["call_id"] for c in local_calls)
            calls.extend(local_calls)
            for version,planned,reference in local_references:
                references[version].append((planned,reference))
            for saved in saved_rows:
                metrics[by_job[saved["planned_job_id"]]["planner_version"]]["observed_jobs"] += 1
            if receipt is not None:
                receipt_cases += 1
                role_invocations_global += receipt_role_invocations
                saved_role_reads_global += receipt_saved_reads
            cases.append({"execution_path":execution_path,"native_manifest_id":native_manifest,"jobs":len(local_jobs),
                "http_requests":len(starts),**{p+"_transport_attempts":phase_counts[p] for p in PHASES},
                "summary_present":receipt is not None,"role_invocations":receipt_role_invocations,"saved_role_reads":receipt_saved_reads})
        except _MissingEvidence as error:
            missing.append(str(error))
        except (KeyError, TypeError, _EvidenceError) as error:
            errors.append(str(error))

    full = len(jobs_seen)==len(rows) and bool(rows) and not errors
    submissions = sum(c["generation_transport_attempts"] for c in calls)
    if full and expected_generation_submissions is not None and submissions != expected_generation_submissions:
        errors.append("Generation submissions disagree with frozen cumulative total: observed " + str(submissions) + ", expected " + str(expected_generation_submissions))
        full = False
    status = "invalid" if errors else "complete" if full else "partial" if jobs_seen else "unavailable"

    def aggregate(selected, scope_complete):
        answer = {"logical_roles_observed":len(selected),
            "logical_roles_with_generation_submission":sum(c["generation_transport_attempts"]>0 for c in selected),
            "observed_generation_submissions":sum(c["generation_transport_attempts"] for c in selected),
            "generation_submissions":sum(c["generation_transport_attempts"] for c in selected) if scope_complete else None,
            "observed_transport_attempts":sum(c[p+"_transport_attempts"] for c in selected for p in PHASES),
            "transport_attempts":sum(c[p+"_transport_attempts"] for c in selected for p in PHASES) if scope_complete else None,
            "http_exception_events":sum(c["http_errors"] for c in selected),
            "usage_objects":sum(c["role_usage_recorded"] for c in selected)}
        for phase in PHASES:
            answer[phase+"_transport_attempts"] = sum(c[phase+"_transport_attempts"] for c in selected) if scope_complete else None
        for key in (*TOKEN_KEYS,"native_total_duration_ns","observed_first_role_wall_seconds"):
            values=[c[key] for c in selected if c[key] is not None]
            answer[key+"_measured_calls"]=len(values)
            answer[key+"_missing_calls"]=len(selected)-len(values)
            answer[key+"_observed_sum"]=sum(values) if values else None
            answer[key+"_sum"]=sum(values) if selected and len(values)==len(selected) and scope_complete else None
        answer["token_usage_status"] = "complete" if selected and scope_complete and all(answer[k+"_missing_calls"]==0 for k in TOKEN_KEYS) else "partial" if answer["usage_objects"] else "unavailable"
        return answer

    per_planner=[]
    for version in versions:
        selected=[c for c in calls if c["planner_version"]==version]
        expected_jobs=sum(r["planner_version"]==version for r in rows)
        complete = metrics[version]["observed_jobs"]==expected_jobs and not errors
        ref_items=references[version]
        ref_records=[item for _job,item in ref_items if isinstance(item,dict)]
        prep=[r.get("preparation_seconds") for r in ref_records if _number(r.get("preparation_seconds"))]
        ref_count_keys=sorted({k for item in ref_records if isinstance(item.get("counts"),dict) for k in item["counts"]})
        references_complete=complete and len(ref_records)==expected_jobs
        ref_counts={k:sum(item["counts"][k] for item in ref_records) if all(type(item.get("counts",{}).get(k)) is int and item["counts"][k]>=0 for item in ref_records) and references_complete else None for k in ref_count_keys}
        per_planner.append({"planner_version":version,"expected_jobs":expected_jobs,"observed_jobs":metrics[version]["observed_jobs"],
            "status":"complete" if complete else status,
            **aggregate(selected,complete),"reference_records":len(ref_records),
            "reference_status":"not_applicable" if version==1 else "complete" if references_complete else "partial" if ref_records else "unavailable",
            "reference_preparation_measured_jobs":len(prep),
            "reference_preparation_seconds_observed_sum":sum(prep) if prep else None,
            "reference_preparation_seconds_sum":sum(prep) if complete and len(prep)==expected_jobs else None,
            "reference_counts":ref_counts,"reference_counts_json":json.dumps(ref_counts,sort_keys=True),
            "role_invocations":None,"saved_role_reads":None,
            "role_invocations_missing_reason":"Bound cumulative receipts provide case totals; journal call IDs identify distinct roles, not repeated cached role invocations by planner.",
            "hardware_measurements":None,"dollar_cost":None})
    stages=[]
    for version,stage in sorted({(c["planner_version"],c["stage"]) for c in calls}):
        selected=[c for c in calls if c["planner_version"]==version and c["stage"]==stage]
        stages.append({"planner_version":version,"stage":stage,**aggregate(selected,full)})
    return {"schema_version":"step35-native-runtime-readonly-1","status":status,
        "missing_reason":"; ".join(missing[:5]) if missing else None,"missing_evidence":missing,"errors":errors,
        "expected_jobs":len(rows),"observed_jobs":len(jobs_seen),"observed_cases":len(cases),
        "expected_generation_submissions":expected_generation_submissions,
        "generation_submissions":submissions if full else None,"observed_generation_submissions":submissions,
        "frozen_global_total_reconciled":full and submissions==expected_generation_submissions if expected_generation_submissions is not None else None,
        "per_planner_rows":per_planner,"stage_rows":stages,"call_rows":calls,"case_rows":cases,
        "input_sha256":observed_hashes,
        "role_invocations":role_invocations_global if full and receipt_cases==len(cases) else None,
        "saved_role_reads":saved_role_reads_global if full and receipt_cases==len(cases) else None,
        "unavailable_metrics":{"hardware_resource_measurements":None,"documented_dollar_cost":None},
        "counting_notes":["Generation http_started events count leaf transport submissions, not inferred backend acceptance.",
            "All HTTP phases contribute transport attempts; metadata and render attempts are separate from generation.",
            "Logical call IDs are deduplicated once for usage, preserving repeated/cached invocation totals separately.",
            "Receipt role usage is first-observation usage charged once by call_id; cached re-reads do not multiply tokens.",
            "Reference preparation is reported from original per-job records; new_counts from a resumed execution do not replace original counts.",
            "Observed sums from a partial population are explicitly labeled; missing counts and token usage are not zero."]}
