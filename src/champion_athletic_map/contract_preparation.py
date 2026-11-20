"""Prepare prospective response requirements from verified saved development replies."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator


VERSION = "request-contract-preparation-1"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def module(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("A contract dependency leaves the project.")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("response_contract_" + path.stem, path))
    result.__spec__.loader.exec_module(result)
    return result


def bound(root, relative, expected):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or sha(path.read_bytes()) != expected:
        raise ValueError("A saved contract dependency changed: " + relative)
    return path.read_bytes()


def save_once(path, value):
    data = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("An earlier contract candidate differs and was preserved.")
    else:
        with path.open("xb") as handle:
            handle.write(data)


def load_replies(root):
    root = Path(root).resolve()
    source_path = "results/step31_shared_guidance_summary.json"
    source = read(root / source_path)
    if (source.get("recorded_jobs") != 4 or source.get("independent_assessment_completed") is not True
            or source.get("injected_test_dependencies") is not False or source.get("protocol_frozen") is not False):
        raise ValueError("The completed four-planner development results are required.")
    if len(source["reports"]) != 4 or {item["planner_version"] for item in source["reports"]} != {1, 2, 3, 4}:
        raise ValueError("The saved review must contain one designated outcome per planner.")
    bindings = {source_path: sha((root / source_path).read_bytes())}
    replies, publics, packets = [], [], []
    for report in source["reports"]:
        relative = report["outcome_path"]
        path = (root / relative).resolve()
        if not path.is_relative_to(root / "results/pilot/probes" / source["probe_id"] / "jobs"):
            raise ValueError("A designated reply is outside its recorded development job.")
        raw = path.read_bytes()
        outcome = json.loads(raw)
        if sha(canonical(outcome)) != report["assessment"]["designated_outcome_sha256"]:
            raise ValueError("A saved model outcome differs from its independent assessment.")
        record = read(path.with_name("job_record.json"))
        body = {key: value for key, value in record.items() if key != "job_record_sha256"}
        public = (outcome.get("response") or {}).get("authoritative_public_input")
        if not isinstance(public, dict):
            raise ValueError("A saved reply lacks its original public input.")
        public_record = {"profile_id": source["profile_id"], "schema_version": "athlete-profile-input-2", "input": public}
        if (record.get("job_record_sha256") != sha(canonical(body))
                or record.get("manifest_id") != source["manifest_id"]
                or record.get("planner_version") != report["planner_version"]
                or record.get("job_id") != report["job_id"]
                or record.get("outcome_sha256") != sha(raw)
                or record.get("public_record_sha256") != sha(canonical(public_record))):
            raise ValueError("A saved job identity, public input or outcome binding changed.")
        bindings[relative] = sha(raw)
        record_path = path.with_name("job_record.json").relative_to(root).as_posix()
        bindings[record_path] = sha((root / record_path).read_bytes())
        publics.append(public_record)
        if report["planner_version"] != 1:
            packet = (record.get("reference_record") or {}).get("packet")
            if not isinstance(packet, dict):
                raise ValueError("A reference-supported reply lacks its recorded packet.")
            packets.append(packet)
        replies.append({"planner_version": report["planner_version"], "outcome": outcome})
    if (any(canonical(public) != canonical(publics[0]) for public in publics[1:])
            or len(packets) != 3 or any(canonical(packet) != canonical(packets[0]) for packet in packets[1:])):
        raise ValueError("The saved jobs do not share the original public case and matched reference content.")
    return {"public_record": publics[0], "replies": replies, "input_sha256": bindings,
        "source_probe_id": source["probe_id"], "truth_packet_sha256": sha(canonical(packets[0]))}


def errors(schema, value):
    return [{"path": "/" + "/".join(map(str, item.absolute_path)), "code": item.validator,
        "message": item.message[:400]} for item in Draft202012Validator(schema).iter_errors(value)]


def prepare(root, *, software_evidence=None):
    root = Path(root).resolve()
    if software_evidence is not None:
        if (software_evidence.get("status") != "passed" or software_evidence.get("passed", 0) <= 0
                or not software_evidence.get("files")):
            raise ValueError("The contract software checks must execute successfully first.")
        for relative, expected in software_evidence["files"].items():
            bound(root, relative, expected)
    source = load_replies(root)
    integration_path = "artifacts/language_model/integration_config.json"
    integration = read(root / integration_path)
    directory = integration["contracts_directory"]
    contract_summary = read(root / directory / "step24_7_shared_contract_summary.json")
    response_path = directory + "/planner_response_schema.json"
    public_path = directory + "/public_profile_record_schema.json"
    response_schema = json.loads(bound(root, response_path, contract_summary["output_hashes"][response_path]))
    public_schema = json.loads(bound(root, public_path, contract_summary["output_hashes"][public_path]))
    public_module_path = directory + "/public_input.py"
    bound(root, public_module_path, contract_summary["output_hashes"][public_module_path])
    schedule = module(root, "src/champion_athletic_map/pilot_schedule.py")
    public = module(root, public_module_path).prepare_public_input(source["public_record"],
        schedule.build_input_schema(public_schema))["public_input"]
    version3 = read(root / "artifacts/planners/version3_config.json")
    note_schema = json.loads(bound(root, version3["note_schema_path"], version3["note_schema_sha256"]))
    adapter = module(root, "src/champion_athletic_map/llm.py")
    api = module(root, "src/champion_athletic_map/request_contracts.py")
    bundle = api.build_contracts(public, response_schema, adapter._schema_order(adapter._generation_schema(response_schema)), note_schema)
    for key in ("local_response_schema", "native_response_schema", "food_note_schema"):
        Draft202012Validator.check_schema(bundle[key])
    final_reviews, food_reviews = [], []
    for item in source["replies"]:
        outcome = item["outcome"]
        text = ((outcome.get("response") or {}).get("model_output") or {}).get("raw_text")
        value = adapter._decode(text.encode("utf-8")) if isinstance(text, str) else None
        final_reviews.append({"planner_version": item["planner_version"],
            "new_local_contract_errors": errors(bundle["local_response_schema"], value),
            "original_reply_modified": False, "prospective_validation_only": True})
        stages = outcome.get("stages") or []
        if item["planner_version"] == 4:
            stages = (outcome.get("draft_result") or {}).get("stages") or []
        for stage in stages:
            if stage.get("stage") != "food":
                continue
            output = ((stage.get("result") or {}).get("response") or {}).get("model_output") or {}
            note = output.get("parsed_object")
            food_reviews.append({"planner_version": item["planner_version"],
                "contribution_status": note.get("contribution_status") if isinstance(note, dict) else None,
                "empty_provided_note": isinstance(note, dict) and note.get("contribution_status") == "provided"
                    and note.get("recommendations") == [],
                "new_food_contract_errors": errors(bundle["food_note_schema"], note),
                "original_note_modified": False})
    dependencies = ["src/champion_athletic_map/" + name + ".py" for name in
        ("request_contracts", "contract_runtime", "contract_preparation", "shared_guidance_runtime", "pilot_schedule", "llm")]
    dependencies += [response_path, public_path, public_module_path, version3["note_schema_path"],
        "artifacts/planners/version3_config.json", integration_path, "docs/request_bound_response_contract.md"]
    identity = {"schema_version": VERSION, "source_probe_id": source["source_probe_id"],
        "public_input_sha256": sha(canonical(public)), "input_sha256": source["input_sha256"],
        "component_sha256": {relative: sha((root / relative).read_bytes()) for relative in dependencies},
        "contracts_sha256": sha(canonical(bundle)), "policy": bundle["policy"],
        "candidate_only": True, "app_and_global_configuration_changed": False,
        "next_runtime_factory": "src/champion_athletic_map/contract_runtime.py:build_runtime",
        "original_independent_scoring_parser_changed": False,
        "backend_grammar_compatibility": "pending_new_native_schema_test", "new_model_calls": 0}
    digest = sha(canonical(identity))
    folder = root / "artifacts/pilot/request_contracts" / ("contracts_" + digest[:20])
    save_once(folder / "configuration.json", identity)
    save_once(folder / "contracts.json", bundle)
    review = {"final_replies": final_reviews, "food_notes": food_reviews,
        "old_results_changed": False, "new_model_calls": 0,
        "strict_rejection_of_saved_failures_is_not_proof_of_better_future_generation": True}
    save_once(folder / "saved_reply_review.json", review)
    summary = {**identity, "configuration_id": digest, "saved_replies_reviewed": len(final_reviews),
        "saved_food_notes_reviewed": len(food_reviews),
        "saved_empty_food_notes_rejected": sum(item["empty_provided_note"] and bool(item["new_food_contract_errors"]) for item in food_reviews),
        "new_runtime_executed": False, "new_generation_quality_verified": False,
        "representative_pilot_completed": False, "final_scores_computed": False,
        "accepted_study_profiles": 0, "protocol_frozen": False,
        "contract_files": {path.relative_to(root).as_posix(): sha(path.read_bytes()) for path in folder.iterdir() if path.is_file()},
        "software_evidence": software_evidence or {"status": "not_recorded_by_this_invocation"}}
    target = root / "results/step31_response_contract_summary.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical(summary) + b"\n")
    return summary


def print_summary(summary):
    print("Saved replies reviewed:", summary["saved_replies_reviewed"], "| Empty food notes rejected:", summary["saved_empty_food_notes_rejected"])
    print("Explicit food response: required | Earlier results: preserved")
    print("New model calls: 0 | New generation and backend checks: pending")
    print("Saved: results/step31_response_contract_summary.json")
