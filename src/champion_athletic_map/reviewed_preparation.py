"""Prepare prospective reviewed reference inputs from the completed saved pilot."""

from copy import deepcopy
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from uuid import uuid4


VERSION = "reviewed-workflow-offline-preparation-1"
SUMMARY = "results/step31_reviewed_workflow_preparation_summary.json"
_NEW = ("selected_drill_context", "food_fact_focus", "reviewed_planning_checks", "reviewed_runtime", "reviewed_preparation")
_OLD = ("operational_runtime", "operational_preparation", "food_reference_encoding", "contract_runtime",
        "request_contracts", "pilot_references", "reference_context", "reference_preparation",
        "independent_plan_assessment", "independent_resources", "independent_food", "food_answer_audit",
        "pilot_schedule", "planning_checks", "rule_checks", "unified_references", "reference_tools", "llm")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("A saved preparation input has duplicate JSON keys.")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("A saved preparation value is nonfinite.")))


def checked(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("A reviewed preparation input is unavailable: " + str(relative))
    return path


def verify(root, bindings):
    for relative, expected in bindings.items():
        if sha(checked(root, relative).read_bytes()) != expected:
            raise ValueError("A reviewed preparation input changed: " + relative)


def module(root, name):
    path = checked(root, "src/champion_athletic_map/" + name + ".py")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("reviewed_preparation_" + name, path))
    result.__spec__.loader.exec_module(result)
    return result


def file_module(path):
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("reviewed_public_input", path))
    result.__spec__.loader.exec_module(result)
    return result


def save_once(path, value):
    data = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("An earlier reviewed preparation differs and was preserved: " + path.name)
    else:
        with path.open("xb") as handle:
            handle.write(data)


def pinned_counter(root):
    """Read only the original native tokenizer tables; perform no model request."""
    adapter = checked(root, "src/champion_athletic_map/llm.py")
    candidates = [node.value.value for node in ast.parse(adapter.read_bytes()).body
                  if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                  and any(isinstance(target, ast.Name) and target.id == "TOKENIZER_SHA" for target in node.targets)]
    if len(candidates) != 1:
        raise ValueError("The pinned native tokenizer identity is unavailable.")
    manifests = [path for path in (root / "artifacts/language_model/tokenizers").glob("*/tokenizer_manifest.json")
                 if sha(path.read_bytes()) == candidates[0]]
    if len(manifests) != 1:
        raise ValueError("The recorded native tokenizer manifest is unavailable.")
    path = manifests[0]
    manifest = read(path)
    bindings = {path.relative_to(root).as_posix(): sha(path.read_bytes())}
    for name, expected in manifest["payload_hashes"].items():
        child = (path.parent / name).resolve()
        if not child.is_relative_to(path.parent):
            raise ValueError("A native tokenizer payload leaves its recorded directory.")
        bindings[child.relative_to(root).as_posix()] = expected
    native = manifest["source_native_metadata"]
    bindings[native["relative_path"]] = native["sha256"]
    verify(root, bindings)
    api = module(root, "operational_preparation")
    model = read(path.parent / "normal_bpe_tokenizer.json")["model"]
    return api.SourceTableCounter(model, read(root / native["relative_path"])["model_info"]), bindings


def _parents(root):
    review_name, pilot_name = "results/step31_saved_reply_review_summary.json", "results/step31_development_pilot_summary.json"
    review, pilot = read(checked(root, review_name)), read(checked(root, pilot_name))
    if (review.get("schema_version") != "saved-pilot-assistant-content-review-1"
            or review.get("outcomes_reviewed") != 80 or review.get("new_model_calls") != 0
            or review.get("formal_assessments_changed") is not False
            or review.get("source_summary_sha256") != sha((root / pilot_name).read_bytes())
            or pilot.get("completed_cases") != 20 or pilot.get("recorded_jobs") != 80
            or pilot.get("development_pilot_completed") is not True
            or pilot.get("injected_test_dependencies") is not False):
        raise ValueError("The completed pilot and saved-reply review are required before preparation.")
    cases = pilot.get("cases") or []
    if len(cases) != 20 or {c["case_index"] for c in cases} != set(range(1, 21)):
        raise ValueError("The saved pilot case roster is incomplete or duplicated.")
    bindings = deepcopy(review["source_sha256"])
    bindings[review_name] = sha((root / review_name).read_bytes())
    bindings[pilot_name] = sha((root / pilot_name).read_bytes())
    verify(root, bindings)
    rows = []
    for case in sorted(cases, key=lambda c: c["case_index"]):
        reports = case.get("reports") or []
        if len(reports) != 4 or {r["planner_version"] for r in reports} != {1, 2, 3, 4}:
            raise ValueError("The saved pilot has a missing or duplicated planner outcome.")
        report = next(row for row in reports if row["planner_version"] == 2)
        parts = Path(report["outcome_path"]).parts
        if len(parts) < 7 or parts[:3] != ("results", "pilot", "probes"):
            raise ValueError("A designated pilot outcome leaves the expected saved-results tree.")
        probe = parts[3]
        manifest_name = "artifacts/pilot/shared_guidance/" + probe + "/probe_manifest.json"
        manifest = read(checked(root, manifest_name))
        if (manifest["public_record"]["profile_id"] != case["profile_id"]
                or manifest["overall_manifest_id"] != pilot["manifest_id"]
                or sha(canonical(manifest["public_record"])) != manifest["public_record_sha256"]):
            raise ValueError("A pilot public input differs from its original manifest.")
        schema_name = manifest["public_schema_path"]
        expected_schema = manifest["case_review_files"].get(schema_name)
        if not isinstance(expected_schema, str):
            raise ValueError("The original pilot public-schema binding is unavailable.")
        verify(root, {schema_name: expected_schema})
        bindings[schema_name] = expected_schema
        verify(root, manifest["module_and_config_sha256"])
        bindings.update(manifest["module_and_config_sha256"])
        reference_folder = root / "results/pilot/probes" / probe / "references" / report["job_id"]
        packet_name = (reference_folder / "packet.json").relative_to(root).as_posix()
        trace_name = (reference_folder / "builder_trace.json").relative_to(root).as_posix()
        if packet_name not in bindings or trace_name not in bindings or manifest_name not in bindings:
            raise ValueError("A saved case lacks its reviewed reference-source bindings.")
        rows.append({"case_index": case["case_index"], "profile_id": case["profile_id"],
            "manifest": manifest, "manifest_path": manifest_name,
            "old_packet": read(root / packet_name), "old_builder_trace": read(root / trace_name),
            "packet_path": packet_name, "builder_trace_path": trace_name})
    return pilot, rows, bindings


def execute(root, *, software_evidence=None, tools_factory=None, counter_factory=None):
    """Record new candidate packets without encoding queries or contacting a backend."""
    root = Path(root).resolve()
    software_evidence = deepcopy(software_evidence)
    pilot, rows, bindings = _parents(root)
    if software_evidence is not None:
        if software_evidence.get("status") != "passed" or software_evidence.get("passed", 0) <= 0:
            raise ValueError("The new software checks must pass before packet preparation.")
        verify(root, software_evidence.get("files") or {})
    components = {"src/champion_athletic_map/" + name + ".py":
                  sha(checked(root, "src/champion_athletic_map/" + name + ".py").read_bytes())
                  for name in (*_NEW, *_OLD)}
    builder, food = module(root, "selected_drill_context"), module(root, "food_fact_focus")
    catalog = builder.load_approved_catalog(root)
    pointer_name = "artifacts/language_model/active_resource_release.json"
    pointer = read(checked(root, pointer_name))
    bindings[pointer_name] = sha((root / pointer_name).read_bytes())
    release_name = pointer["release_directory"] + "/manifest.json"
    bindings[release_name] = pointer["manifest_sha256"]
    release = read(checked(root, release_name))
    for name, expected in release["file_hashes"].items():
        if Path(name).name != name or name in (".", ".."):
            raise ValueError("An approved release payload must be a sibling file.")
        bindings[pointer["release_directory"] + "/" + name] = expected
    v1_name, integration_name = "artifacts/planners/version1_config.json", "artifacts/language_model/integration_config.json"
    for name in (v1_name, integration_name):
        bindings[name] = sha(checked(root, name).read_bytes())
    v1, integration = read(root / v1_name), read(root / integration_name)
    contract_summary_name = integration["contracts_directory"] + "/step24_7_shared_contract_summary.json"
    contract_summary = read(checked(root, contract_summary_name))
    bindings[contract_summary_name] = sha((root / contract_summary_name).read_bytes())
    for relative in (integration["contracts_directory"] + "/public_input.py",):
        expected = contract_summary["output_hashes"].get(relative)
        if not isinstance(expected, str):
            raise ValueError("The saved shared public-input source binding is unavailable.")
        verify(root, {relative: expected})
        bindings[relative] = expected
    public_api = file_module(root / integration["contracts_directory"] / "public_input.py")
    tools = (tools_factory(root, deepcopy(v1), deepcopy(integration)) if tools_factory else
             module(root, "unified_references").UnifiedReferenceTools(root, v1, integration))
    if hasattr(tools, "source_bindings"):
        bindings.update(deepcopy(tools.source_bindings))
    counter_result = counter_factory(root) if counter_factory else pinned_counter(root)
    counter, counter_bindings = counter_result
    bindings.update(counter_bindings)
    verify(root, bindings)
    count_tokens = counter.count
    prepared_rows = []
    for row in rows:
        schema_name = row["manifest"]["public_schema_path"]
        bindings[schema_name] = sha(checked(root, schema_name).read_bytes())
        prepared = public_api.prepare_public_input(row["manifest"]["public_record"], read(root / schema_name))
        observed = count_tokens(canonical(row["old_packet"]["payload"]).decode("utf-8"))
        if observed != row["old_packet"]["preparation"]["packet_text_tokens"]:
            raise ValueError("The pinned offline counter does not reproduce a saved packet count.")
        prepared_rows.append((row, prepared))
    identity = {"schema_version": VERSION, "source_pilot_id": pilot["pilot_id"],
        "input_sha256": bindings, "component_sha256": components,
        "injected_test_dependencies": tools_factory is not None or counter_factory is not None,
        "packet_budget_basis": builder.BUDGET_BASIS,
        "future_case_indices": [13, 3, 4, 12],
        "entrypoints": {"runtime": "reviewed_runtime.build_runtime",
                        "references": "reviewed_runtime.build_reference_preparer",
                        "assessor": "reviewed_runtime.make_assessor"}}
    digest = sha(canonical(identity))
    workflow_id = "workflow_" + digest[:20]
    policy = {"policy_version": "reviewed-planning-references-1", "max_packet_tokens": 2200,
        "max_rule_bundles": 2, "source_configuration_sha256": digest,
        "resource_release_manifest_sha256": catalog["release_manifest_sha256"],
        "active_resource_pointer_sha256": catalog["active_resource_pointer_sha256"]}
    manifest = {**identity, "manifest_id": digest, "workflow_id": workflow_id,
        "reference_policy": policy, "candidate_only": True,
        "prepared_packets_are_offline_diagnostics_only": True,
        "future_runtime_policy_must_be_bound_per_actual_public_record": True,
        "future_jobs_started": 0, "new_model_calls": 0, "query_encoder_processes": 0,
        "backend_count_agreement_verified": False, "full_prompt_budgets_verified": False,
        "operational_generation_ready": False, "app_generation_enabled": False}
    manifest_name = "artifacts/pilot/reviewed_workflow/" + workflow_id + "/manifest.json"
    save_once(root / manifest_name, manifest)
    case_results = []
    for row, prepared in prepared_rows:
        folder = root / "results/pilot/reviewed_workflow" / workflow_id / "offline_cases" / ("case_" + str(row["case_index"]).zfill(2))
        packet, trace = builder.build_packet(prepared, tools, deepcopy(row["old_builder_trace"]["ranked_lists"]), count_tokens, policy)
        builder.validate_packet(packet, prepared, policy, count_tokens)
        focus = food.make_food_focus(prepared["public_input"], packet["payload"])
        record = {"case_index": row["case_index"], "profile_id": row["profile_id"],
            "packet_id": packet["packet_id"], "catalog_selection": deepcopy(packet["payload"].get("catalog_selection")),
            "delivered_drill_records": len(packet["payload"].get("catalog_records") or []),
            "packet_tokens": packet["preparation"]["packet_text_tokens"], "packet_budget": policy["max_packet_tokens"],
            "packet_fits_local_budget": packet["preparation"]["packet_text_tokens"] <= policy["max_packet_tokens"],
            "food_focus_status": focus["status"], "requested_food_facts": len(focus["requested_facts"]),
            "packet_path": (folder / "packet.json").relative_to(root).as_posix(),
            "trace_path": (folder / "trace.json").relative_to(root).as_posix(),
            "food_focus_path": (folder / "food_focus.json").relative_to(root).as_posix(),
            "model_answer_supplied": False, "full_prompt_budget_verified": False, "backend_verified": False}
        save_once(folder / "packet.json", packet)
        save_once(folder / "trace.json", trace)
        save_once(folder / "food_focus.json", focus)
        save_once(folder / "case.json", record)
        case_results.append(record)
    verify(root, {**bindings, **components})
    status = "reviewed_inputs_prepared_offline"
    result = {"schema_version": VERSION, "workflow_id": workflow_id, "manifest_id": digest,
        "status": status, "candidate_only": True, "manifest_path": manifest_name,
        "cases_prepared": len(case_results), "cases_with_delivered_drills": sum(r["delivered_drill_records"] > 0 for r in case_results),
        "cases_without_delivered_drills": sum(r["delivered_drill_records"] == 0 for r in case_results),
        "food_focus_cases_available": sum(r["food_focus_status"] == "available" for r in case_results),
        "food_focus_cases_unresolved": sum(r["food_focus_status"] == "unresolved" for r in case_results),
        "all_packet_budgets_fit_locally": all(r["packet_fits_local_budget"] for r in case_results),
        "original_packet_counts_reproduced": len(prepared_rows), "source_bindings_checked": len(bindings),
        "source_summary_sha256": sha((root / "results/step31_development_pilot_summary.json").read_bytes()),
        "input_sha256": bindings, "component_sha256": components, "cases": case_results,
        "software_evidence": software_evidence,
        "injected_test_dependencies": tools_factory is not None or counter_factory is not None,
        "original_results_changed": False, "new_model_calls": 0, "http_requests": 0,
        "query_encoder_processes": 0, "future_jobs_started": 0,
        "backend_count_agreement_verified": False, "full_prompt_budgets_verified": False,
        "operational_generation_ready": False, "app_generation_enabled": False,
        "human_ratings_created": 0, "final_scores_created": False}
    result_path = root / SUMMARY
    # Software observations may change on a rerun; each complete record stays immutable.
    record_name = "results/pilot/reviewed_workflow/" + workflow_id + "/preparations/" + sha(canonical(result))[:20] + ".json"
    save_once(root / record_name, result)
    if result_path.exists():
        previous = read(result_path)
        previous_id = previous.get("workflow_id")
        if not isinstance(previous_id, str) or not previous_id.startswith("workflow_") or Path(previous_id).name != previous_id:
            raise ValueError("An existing reviewed summary has an invalid identity and was preserved.")
        previous_name = "results/pilot/reviewed_workflow/" + previous_id + "/preparations/" + sha(canonical(previous))[:20] + ".json"
        save_once(root / previous_name, previous)
    data = canonical(result) + b"\n"
    if not result_path.exists() or result_path.read_bytes() != data:
        temporary = result_path.with_name(result_path.name + ".tmp_" + uuid4().hex[:12])
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, result_path)
    return result
