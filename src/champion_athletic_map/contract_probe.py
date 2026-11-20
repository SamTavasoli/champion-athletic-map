"""Run a separate development case with public request-bound response contracts."""

import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
from types import SimpleNamespace

from jsonschema import Draft202012Validator


VERSION = "request-contract-development-probe-1"
PROFILE_ID = "athlete:46a43835d1a3112756ee7181"
POINTER = "results/pilot/contract_probe/development_probe.json"
SUMMARY = "results/step31_contract_probe_summary.json"
GENERATION_SUMMARY = "results/pilot/contract_probe/generation_summary.json"
DOCUMENT = "docs/request_contract_backend_probe.md"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=False, allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def module(root, name):
    path = root / "src/champion_athletic_map" / (name + ".py")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("contract_probe_" + name, path))
    result.__spec__.loader.exec_module(result)
    return result


def verify(root, bindings):
    for relative, expected in bindings.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError("A saved contract-probe dependency changed: " + relative)


def case_contracts(root, public_record, public_schema):
    """Rebuild this case's schemas without reading retrieval results or food values."""
    integration = read(root / "artifacts/language_model/integration_config.json")
    directory = integration["contracts_directory"]
    path = root / directory / "public_input.py"
    spec = importlib.util.spec_from_file_location("contract_probe_public", path)
    public = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(public)
    prepared = public.prepare_public_input(public_record, public_schema)
    local = read(root / directory / "planner_response_schema.json")
    config = read(root / "artifacts/planners/version3_config.json")
    note = read(root / config["note_schema_path"])
    adapter = module(root, "llm")
    return module(root, "request_contracts").build_contracts(prepared["public_input"], local,
        adapter._schema_order(adapter._generation_schema(local)), note)


def prepare(root, *, environment_record=None):
    root = Path(root).resolve()
    prior_path = "results/step31_response_contract_summary.json"
    prior = read(root / prior_path)
    evidence = prior.get("software_evidence") or {}
    if (prior.get("candidate_only") is not True or prior.get("new_runtime_executed") is not False
            or prior.get("new_model_calls") != 0 or evidence.get("status") != "passed"
            or evidence.get("passed", 0) <= 0 or not evidence.get("files") or not prior.get("contract_files")):
        raise ValueError("Step 31-7 must contain its completed prospective contract checks.")
    verify(root, {**prior["input_sha256"], **prior["component_sha256"], **prior["contract_files"], **evidence["files"]})
    probe = module(root, "pilot_probe")
    source_pointer_path = "results/pilot/probes/first_operational_probe.json"
    pointer = read(root / source_pointer_path)
    source = read(root / pointer["manifest_path"])
    body = {key: value for key, value in source.items() if key not in
        ("probe_id", "manifest_id", "case_review_config_path", "public_schema_path", "jobs")}
    if pointer.get("manifest_id") != source["manifest_id"] or sha(canonical(body)) != source["manifest_id"]:
        raise ValueError("The original case-review source manifest changed.")
    verify(root, {**source["case_review_files"], **source["module_and_config_sha256"]})
    review_files = source["case_review_files"]
    profiles_path = next(name for name in review_files if name.endswith("/public_profiles.jsonl"))
    profiles = [json.loads(line) for line in (root / profiles_path).read_bytes().splitlines() if line.strip()]
    selected = [item for item in profiles if item["profile_id"] == PROFILE_ID]
    if len(selected) != 1 or selected[0]["profile_id"] == source["public_record"]["profile_id"]:
        raise ValueError("The new age-16 development case is unavailable.")
    public = selected[0]
    facts = public["input"]
    count, _ = module(root, "independent_plan_assessment").requested_count(facts)
    if (facts.get("age") != 16 or count != 2 or len(facts.get("availability") or []) != 2
            or (facts.get("time_limits") or {}).get("max_additional_sessions_per_week") != 2
            or not facts.get("food_question")):
        raise ValueError("The selected public case lost its recorded diagnostic features.")
    review = read(root / source["case_review_config_path"])
    verify(root, review["parent_preparation_files"])
    jobs_path = next(name for name in review["parent_preparation_files"] if name.endswith("/planned_pilot_jobs.csv"))
    jobs = [item for item in csv.DictReader(io.StringIO((root / jobs_path).read_text(encoding="utf-8")))
        if item["profile_id"] == PROFILE_ID]
    jobs.sort(key=lambda item: int(item["position_in_case"]))
    if len(jobs) != 4 or {int(item["planner_version"]) for item in jobs} != {1, 2, 3, 4}:
        raise ValueError("The new case needs its original four prepared workflow positions.")
    bundle = case_contracts(root, public, read(root / source["public_schema_path"]))
    bindings = {**source["module_and_config_sha256"], **prior["component_sha256"]}
    for path in sorted((root / "src/champion_athletic_map").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        digest = sha(path.read_bytes())
        if relative in bindings and bindings[relative] != digest:
            raise ValueError("An original workflow source changed: " + relative)
        bindings[relative] = digest
    bindings[DOCUMENT] = sha((root / DOCUMENT).read_bytes())
    parent_files = {prior_path: sha((root / prior_path).read_bytes()), source_pointer_path: sha((root / source_pointer_path).read_bytes()),
        pointer["manifest_path"]: sha((root / pointer["manifest_path"]).read_bytes()), **prior["contract_files"],
        **prior["input_sha256"], **evidence["files"]}
    identity = {"schema_version": VERSION, "mode": "new_request_contract_unscored_development_probe",
        "parent_probe_id": source["probe_id"], "parent_contract_configuration_id": prior["configuration_id"],
        "parent_files": parent_files, "case_review_id": source["case_review_id"], "case_review_files": review_files,
        "public_record": public, "public_record_sha256": sha(canonical(public)),
        "selection_policy": "fixed_new_age16_case_two_requested_two_available_food_question",
        "prepared_jobs": jobs, "module_and_config_sha256": bindings, "model_configuration": source["model_configuration"],
        "environment": environment_record if environment_record is not None else probe.environment(),
        "limits": source["limits"], "timing_policy": source["timing_policy"],
        "case_contracts_sha256": sha(canonical(bundle)),
        "native_schema_ordered_wire_sha256": sha(wire(bundle["native_response_schema"])),
        "active_guidance_scope": "this_new_request_contract_probe_only_all_four_workflows",
        "original_results_replaced": False, "output_repairs": 0, "automatic_retries": 0,
        "accepted_study_profiles": 0, "protocol_frozen": False}
    digest = sha(canonical(identity))
    probe_id = "contract_" + digest[:20]
    manifest = {**identity, "probe_id": probe_id, "manifest_id": digest,
        "case_review_config_path": source["case_review_config_path"], "public_schema_path": source["public_schema_path"],
        "jobs": [{"job_id": "p31c_" + digest[:16] + "_v" + item["planner_version"],
            "call_id": "p31c_" + digest[:16] + "_v" + item["planner_version"],
            "planner_version": int(item["planner_version"]), "position_in_case": int(item["position_in_case"]),
            "parent_prepared_job_id": item["job_id"]} for item in jobs]}
    path = "artifacts/pilot/shared_guidance/" + probe_id + "/probe_manifest.json"
    if (root / POINTER).exists() and read(root / POINTER).get("manifest_id") != digest:
        raise ValueError("This contract probe already has another configuration; its results were preserved.")
    probe.save(root / path, manifest, immutable=True)
    probe.save(root / POINTER, {"manifest_id": digest, "manifest_path": path}, immutable=True)
    return manifest


def native_evidence(root, reports, bundle):
    """Separate saved request/reply observations from unsupported grammar guarantees."""
    expected = sha(wire(bundle["native_response_schema"]))
    rows = []
    for report in reports:
        outcome = read(root / report["outcome_path"])
        call_id = outcome.get("call_id")
        row = {"planner_version": report["planner_version"], "call_id": call_id,
            "candidate_native_schema_submitted": None, "reply_conforms_to_candidate_native_schema": None,
            "saved_configuration_matches_designated_configuration": None,
            "recorded_native_wire_hash_matches": None,
            "saved_request_matches_designated_request_sha256": None,
            "completed_native_reply_observed": False, "evidence_files": {}}
        text = (((outcome.get("response") or {}).get("model_output") or {}).get("raw_text"))
        if isinstance(text, str):
            try:
                # Use the original strict decoder rather than normalizing a model reply.
                parsed = module(root, "llm")._decode(text.encode("utf-8"))
                row["reply_conforms_to_candidate_native_schema"] = Draft202012Validator(bundle["native_response_schema"]).is_valid(parsed)
            except (ValueError, TypeError, UnicodeError):
                row["reply_conforms_to_candidate_native_schema"] = False
        if isinstance(call_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", call_id):
            folder = root / "results/integration/model_calls" / call_id
            request, backend = folder / "request.json", folder / "backend_response.json"
            if request.is_file():
                saved_request = read(request)
                submitted = saved_request.get("request") or {}
                schema = submitted.get("format")
                configuration = saved_request.get("input_configuration") or {}
                row["candidate_native_schema_submitted"] = isinstance(schema, dict) and canonical(schema) == canonical(bundle["native_response_schema"])
                row["recorded_native_wire_hash_matches"] = configuration.get("output_schema_sha256") == expected
                row["saved_configuration_matches_designated_configuration"] = bool(configuration) and configuration == outcome.get("input_configuration")
                row["saved_request_matches_designated_request_sha256"] = sha(wire(submitted)) == outcome.get("request_sha256")
                row["evidence_files"][request.relative_to(root).as_posix()] = sha(request.read_bytes())
            if backend.is_file():
                saved = read(backend)
                row["completed_native_reply_observed"] = (saved.get("done") is True and saved.get("done_reason") == "stop"
                    and type(saved.get("eval_count")) is int and saved["eval_count"] > 0
                    and (saved.get("message") or {}).get("role") == "assistant"
                    and (saved.get("message") or {}).get("content") == text)
                row["evidence_files"][backend.relative_to(root).as_posix()] = sha(backend.read_bytes())
        rows.append(row)
    observed = sum(item["candidate_native_schema_submitted"] is True
        and item["recorded_native_wire_hash_matches"] is True
        and item["saved_configuration_matches_designated_configuration"] is True
        and item["saved_request_matches_designated_request_sha256"] is True
        and item["completed_native_reply_observed"] for item in rows)
    return {"status": "saved_native_request_and_reply_observed" if observed else "unverified",
        "designated_replies_with_candidate_native_evidence": observed, "designated_replies_assessed": len(rows), "per_planner": rows,
        "ordered_wire_hash_basis": "preserved_request_wire_bytes_and_pre_serialization_input_configuration",
        "native_chronology_or_unique_dates_guaranteed": False, "semantic_correctness_established": False,
        "observation_is_universal_backend_compatibility_proof": False}


def execute(root, manifest, *, software_evidence, runtime_factory=None, references_factory=None,
            trace_module=None, assessor_factory=None, emit=print):
    root = Path(root).resolve()
    verify(root, {**manifest["parent_files"], **manifest["module_and_config_sha256"], **manifest["case_review_files"]})
    bundle = case_contracts(root, manifest["public_record"], read(root / manifest["public_schema_path"]))
    if (sha(canonical(bundle)) != manifest["case_contracts_sha256"]
            or sha(wire(bundle["native_response_schema"])) != manifest["native_schema_ordered_wire_sha256"]):
        raise ValueError("The prospective native or local request contract changed.")
    previous = module(root, "shared_guidance_probe")
    previous.VERSION, previous.POINTER, previous.SUMMARY, previous.GENERATION_SUMMARY = VERSION, POINTER, SUMMARY, GENERATION_SUMMARY
    original_module = previous.module
    def router(project, name):
        if name == "shared_guidance_runtime":
            return SimpleNamespace(build_runtime=lambda root, review, schema: module(root, "contract_runtime").build_runtime(
                root, review, schema, public_record=manifest["public_record"]))
        return original_module(project, name)
    previous.module = router
    summary = previous.execute(root, manifest, software_evidence=software_evidence, runtime_factory=runtime_factory,
        references_factory=references_factory, trace_module=trace_module, assessor_factory=assessor_factory, emit=lambda text: None)
    summary.update(parent_contract_configuration_id=manifest["parent_contract_configuration_id"],
        request_contract_native_evidence=native_evidence(root, summary["reports"], bundle),
        local_contract_candidate_preserved=True)
    previous.module(root, "pilot_probe").save(root / SUMMARY, summary)
    previous.print_summary(summary, emit=emit)
    return summary
