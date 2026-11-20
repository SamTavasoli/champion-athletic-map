"""Read and bind the intended model/workflow settings without constructing a runtime."""

from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

VERSION = "final-planner-runtime-settings-1"
MODEL = "llama3.1:8b"
MODEL_DIGEST = "46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e"
CONFIGS = tuple("artifacts/planners/version" + str(number) + "_config.json" for number in range(1, 5))
CANDIDATE = "artifacts/planners/version4_candidate_focused_config.json"
INTEGRATION = "artifacts/language_model/integration_config.json"
REFERENCE = "artifacts/planners/shared_reference_source_config.json"
NATIVE_REVIEW = "results/step31_case_review_summary.json"
HISTORICAL_V4_POINTER = "artifacts/planners/active_version4_development.json"
PUBLIC_SCHEMA = "artifacts/pilot/case_review_794f10d9d10a5fde/public_profile_schema.json"
CONTRACTS = "artifacts/language_model/shared_contracts/contracts_3293242853ce2cf7"
SOURCE_MODULES = tuple("src/champion_athletic_map/" + name + ".py" for name in (
    "corrected_runtime", "bounded_revision", "food_response_validation", "live_reviewed_runtime",
    "reviewed_runtime", "reviewed_planning_checks", "operational_runtime", "food_reference_encoding",
    "contract_runtime", "request_contracts", "shared_guidance_runtime", "pilot_runtime", "pilot_schedule",
    "llm", "role_adapter", "evaluated_role_adapter", "review_encoding", "context_encoding",
    "reference_tools", "reference_packets", "reference_context", "reference_preparation", "unified_references",
    "unified_data", "pilot_references", "selected_drill_context", "food_fact_focus", "planning_checks", "rule_checks"))
WORKFLOW_MODULES = tuple("src/champion_athletic_map/planners/" + name + ".py" for name in (
    "llm_only", "rag", "specialists", "evaluated_specialists", "candidate_focused"))
METADATA_FILES = CONFIGS + (CANDIDATE, INTEGRATION, REFERENCE, PUBLIC_SCHEMA, HISTORICAL_V4_POINTER,
    "artifacts/planners/version3_note_schema.json", "artifacts/planners/version4_evaluator_schema.json",
    "artifacts/planners/version4_acceptance_policy.json", "artifacts/language_model/active_resource_release.json",
    "artifacts/language_model/approved_resources/team-approved-f0dcb9e9943e381b/manifest.json")
METADATA_FILES += tuple(CONTRACTS + "/" + name for name in (
    "planner_response_schema.json", "public_profile_record_schema.json", "shared_io_policy.json",
    "step24_7_shared_contract_summary.json", "verified_inputs.json", "public_input.py", "response_contract.py"))
TEXT_FILES = ("docs/prompts/shared_task_addendum_candidate.txt",)
ORDERS = {"A": [1, 2, 4, 3], "B": [2, 3, 1, 4], "C": [3, 4, 2, 1], "D": [4, 1, 3, 2]}


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def _json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "A runtime-settings JSON object repeats a key.")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("A runtime-settings value is not finite.")))


def _path(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative,
            "A runtime-setting path is not project-relative POSIX text.")
    value = PurePosixPath(relative)
    require(not value.is_absolute() and value.as_posix() == relative and not set(value.parts) & {".", ".."},
            "A runtime-setting path leaves the project.")
    path = root / relative
    require(path.resolve() == path and path.is_file(), "A runtime-setting source is missing or linked: " + relative)
    return path


def collect_runtime_settings(root, *, expected_bindings=None, include_native_case_config=True):
    """Bind saved settings only; no imports, client objects, model requests or query encoding.

    expected_bindings comes from the reviewed delivery's source inventory. The
    explicit metadata-only host mode cannot be represented as final readiness.
    """
    root = Path(root).resolve()
    require(isinstance(expected_bindings, dict) and expected_bindings,
            "The reviewed runtime source bindings are required.")
    bindings = {}
    def read(relative, expected=None):
        path = _path(root, relative)
        data = path.read_bytes()
        digest = sha(data)
        fixed = expected_bindings.get(relative)
        require(fixed is None or fixed == digest, "A reviewed runtime source changed: " + relative)
        require(expected is None or expected == digest, "A declared runtime source changed: " + relative)
        require(relative not in bindings or bindings[relative] == digest, "Runtime source bindings disagree.")
        bindings[relative] = digest
        return data
    for relative, expected in expected_bindings.items():
        require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected), "A runtime source binding is invalid.")
        # Delivery inventories contain code, prompts and configuration only.
        require(relative.startswith(("src/champion_athletic_map/", "docs/prompts/", "artifacts/planners/",
            "artifacts/language_model/", "artifacts/pilot/")), "An unrelated dataset path entered the runtime inventory.")
        read(relative, expected)
    for relative in SOURCE_MODULES + WORKFLOW_MODULES + METADATA_FILES + TEXT_FILES:
        require(relative in expected_bindings, "A required runtime source lacks its reviewed binding: " + relative)
    configs = {number: _json(read(relative)) for number, relative in enumerate(CONFIGS, 1)}
    candidate, integration, reference = (_json(read(relative)) for relative in (CANDIDATE, INTEGRATION, REFERENCE))
    require(configs[2]["baseline_config_sha256"] == bindings[CONFIGS[0]]
            and configs[3]["baseline_v2_config_sha256"] == bindings[CONFIGS[1]]
            and configs[4]["baseline_v3_config_sha256"] == bindings[CONFIGS[2]]
            and candidate["source_config_path"] == CONFIGS[3]
            and candidate["source_config_sha256"] == bindings[CONFIGS[3]],
            "The saved workflow configuration lineage differs.")
    require(configs[1]["integration_config_sha256"] == bindings[INTEGRATION],
            "The model integration configuration differs from the saved baseline.")
    require(integration["contracts_directory"] == CONTRACTS
            and configs[1]["response_schema_sha256"] == bindings[CONTRACTS + "/planner_response_schema.json"],
            "The common original response contract differs from the saved baseline.")
    contract_receipt = _json(read(CONTRACTS + "/step24_7_shared_contract_summary.json"))
    require(contract_receipt["status"] == "shared_io_contract_candidates_software_checked",
            "The original common contract receipt has changed status.")
    for relative in METADATA_FILES:
        if relative.startswith(CONTRACTS + "/") and relative in contract_receipt["output_hashes"]:
            require(bindings[relative] == contract_receipt["output_hashes"][relative],
                    "An original common contract source differs from its receipt: " + relative)
    require(integration["model"] == MODEL and integration["model_digest"] == MODEL_DIGEST
            and integration["quantization"] == "Q4_K_M"
            and integration["options"] == {"num_ctx": 8192, "num_predict": 2048, "seed": 42, "temperature": 0},
            "The intended model or sampling limits changed.")
    require(integration["automatic_repairs"] == integration["automatic_retries"] == 0
            and integration["concurrent_model_requests"] == 1 and integration["fresh_messages_per_job"] is True
            and integration["stream"] is False and integration["output_mode"] == "native_json_schema"
            and integration["boundary_reserve_tokens"] == 2 and integration["safety_margin_tokens"] == 256
            and integration["reference_packet_tokens"] == 2200,
            "The shared request, repair or budget policy changed.")
    require(configs[1]["generation_budget_per_job"] == configs[2]["generation_budget_per_job"] == 1
            and configs[3]["maximum_calls_without_food"] == 3 and configs[3]["maximum_calls_with_food"] == 4
            and configs[4]["maximum_calls_without_food"] == 8 and configs[4]["maximum_calls_with_food"] == 9
            and candidate["maximum_revisions"] == 2 and candidate["evaluator_output_tokens"] == 768
            and candidate["coordinator_output_tokens"] == 2048,
            "The saved workflow call or output limits changed.")
    require(configs[3]["role_output_tokens"] == {"training": 512, "recovery": 512, "food": 512, "coordinator": 2048}
            and configs[3]["stage_order"] == ["training", "recovery", "food", "coordinator"],
            "The saved specialist stages or token limits changed.")
    require(reference["route"] == "semantic" and reference["results_per_query"] == 5
            and reference["max_packet_tokens"] == 2200 and reference["max_rule_bundles"] == 2
            and reference["model_digest"] == MODEL_DIGEST,
            "The shared reference-selection settings changed.")

    # Verify configuration-declared source code, schema and prompt files. Source
    # datasets/ranking queries are recorded as declarations, never opened here.
    def declared(value):
        if isinstance(value, list):
            for item in value:
                declared(item)
        elif isinstance(value, dict):
            for key in ("module_sha256", "builder_sha256"):
                for relative, expected in value.get(key, {}).items():
                    require(relative.endswith(".py"), "A declared code binding is not a Python source.")
                    read(relative, expected)
            if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
                read(value["path"], value["sha256"])
            for key, relative in value.items():
                if key.endswith("_path") and isinstance(relative, str) and key[:-5] + "_sha256" in value:
                    if relative.startswith(("src/", "docs/prompts/", "artifacts/planners/", "artifacts/language_model/shared_contracts/")):
                        read(relative, value[key[:-5] + "_sha256"])
                elif isinstance(relative, (dict, list)) and key not in {"source_sha256", "dataset", "development_selection"}:
                    declared(relative)
    for value in [*configs.values(), candidate, reference]:
        declared(value)
    pointer = _json(read("artifacts/language_model/active_resource_release.json"))
    release = pointer["release_directory"] + "/manifest.json"
    read(release, pointer["manifest_sha256"])
    require(integration["active_resource_release"] == "team-approved-f0dcb9e9943e381b",
            "The approved resource release differs from the configured release.")
    native_view = None
    if include_native_case_config:
        saved = _json(read(NATIVE_REVIEW))
        require(saved.get("reviewed_cases") == 20 and saved.get("public_profiles_versioned") == 20
                and saved.get("software_evidence", {}).get("status") == "passed"
                and saved.get("software_fixture") is not True and saved.get("injected_test_dependencies") is not True,
                "The original native common input-schema configuration is required.")
        native_files = saved["review_files"]
        config_paths = [name for name in native_files if name.endswith("/case_review_config.json")]
        schema_paths = [name for name in native_files if name.endswith("/public_profile_schema.json")]
        require(len(config_paths) == len(schema_paths) == 1 and schema_paths[0] == PUBLIC_SCHEMA,
                "The common native case-review configuration paths differ.")
        review_config = _json(read(config_paths[0], native_files[config_paths[0]]))
        public_schema = _json(read(PUBLIC_SCHEMA, native_files[PUBLIC_SCHEMA]))
        require(review_config["public_schema_sha256"] == sha(packed(public_schema)),
                "The native public input contract binding differs.")
        for relative, expected in review_config["component_sha256"].items():
            require(relative.startswith("src/champion_athletic_map/") and relative.endswith(".py"),
                    "An unrelated native case-configuration component was requested.")
            read(relative, expected)
        native_view = {"configuration_path": config_paths[0], "configuration_sha256": bindings[config_paths[0]],
            "public_schema_path": PUBLIC_SCHEMA, "public_schema_sha256": bindings[PUBLIC_SCHEMA],
            "common_task_addendum_sha256": sha(review_config["common_task_addendum"].encode("utf-8")),
            "original_development_configuration_reused_for_common_contract_only": True,
            "private_development_annotations_or_public_case_records_read": False}

    stale = _json(read(HISTORICAL_V4_POINTER))
    settings = {"schema_version": VERSION, "runtime_factory": "corrected_runtime.build_runtime",
        "runtime_version": "bounded-revision-food-validation-runtime-1",
        "runtime_stack": ["corrected_runtime", "live_reviewed_runtime", "reviewed_runtime", "operational_runtime",
            "contract_runtime", "shared_guidance_runtime", "pilot_runtime"],
        "model": {key: deepcopy(integration[key]) for key in ("model", "model_digest", "quantization", "endpoint",
            "options", "output_mode", "schema_serialization", "stream", "timeouts_seconds")},
        "budgets": {"configured_context_tokens": 8192, "final_output_reserve_tokens": 2048,
            "safety_margin_tokens": 256, "boundary_reserve_tokens": 2,
            "counted_input_ceiling_with_final_output_reserve": 5888,
            "rendered_body_ceiling_before_boundary_reserve": 5886,
            "specialist_output_tokens": 512, "v4_evaluator_output_tokens": 768,
            "v4_maximum_revisions": 2, "maximum_submissions_per_case_without_food": 13,
            "maximum_submissions_per_case_with_food": 15,
            "maximum_configured_completed_submissions_for_200_cases_with_20_food_questions": 2640,
            "full_prompt_and_backend_count_checks_required_per_actual_request": True},
        "workflows": [{"planner_version": number, "workflow_class": name, "config_path": CONFIGS[number - 1],
            "reference_access": "none" if number == 1 else "same_case_same_complete_packet",
            "classifier_access": False} for number, name in ((1, "LLMOnlyPlanner"), (2, "RAGPlanner"),
                (3, "SpecialistPlanner"), (4, "CandidateFocusedEvaluatedPlanner"))],
        "v4_override_config": CANDIDATE,
        "historical_active_v4_pointer": {"path": HISTORICAL_V4_POINTER,
            "configured_class": stale.get("workflow_class"), "used_for_final_runtime_selection": False,
            "reason": "The later corrected runtime explicitly composes the candidate-focused workflow; the older development pointer is retained unchanged."},
        "reference_policy": {"versions": [2, 3, 4], "baseline_has_no_reference_access": True,
            "route": "semantic", "results_per_query": 5, "max_packet_tokens": 2200, "max_rule_bundles": 2,
            "whole_approved_variants_and_qualifications_retained": True,
            "drill_selection_from_public_request_and_stated_resources_only": True,
            "readiness_implied_by_catalog_identity": False, "private_witnesses_or_expected_answers_allowed": False},
        "request_policy": {"automatic_retries": 0, "automatic_repairs": 0, "concurrent_model_requests": 1,
            "fresh_messages_per_job": True, "cache_or_resume_results_may_not_replace_new_final_jobs": True,
            "saved_terminal_outcomes_may_be_verified_and_reused_only_for_the_same_final_job": True},
        "balanced_order_recipe": {"seed": 42, "orders": deepcopy(ORDERS),
            "same_case_all_four_workflows": True,
            "final_800_job_schedule_prepared_by_case_protocol_not_by_development_job_reuse": True},
        "timing_policy": {"reference_preparation": "fresh_for_each_new_reference_enabled_job",
            "primary_job_elapsed": "before_fresh_reference_preparation_through_saved_terminal_outcome",
            "setup_and_independent_assessment_outside_primary_timing": True,
            "native_prompt_cache": "observe_if_reported_otherwise_unknown",
            "interrupted_job_elapsed": "unavailable_current_observed_segment_retained"},
        "declared_source_data_bindings": deepcopy(reference["source_sha256"]),
        "source_data_bindings_reverified_by_this_metadata_only_step": False,
        "native_case_configuration": native_view, "source_file_sha256": bindings,
        "native_case_configuration_verified": include_native_case_config,
        "shared_contract_jsonschema_version": contract_receipt["jsonschema_version"],
        "runtime_constructed": False, "current_backend_identity_verified": False,
        "current_runner_context_verified": False, "current_200_case_request_budgets_verified": False,
        "model_calls": 0, "reference_query_encodings": 0,
        "final_planner_execution_authorized": False,
        "inventory_only_host_mode": not include_native_case_config,
        "readiness_limit": "A settings snapshot does not complete case acceptance, the common scoring protocol, runtime construction or backend/per-request preflight."}
    settings["settings_id"] = sha(packed(settings))
    return settings


def build_case_contracts(root, profiles, inventory):
    """Derive the exact effective case contracts using only reviewed public facts.

    Only verified pure source functions are compiled. No runtime factory, client,
    tokenizer, encoder, retrieval service or backend is constructed or called.
    The ordered native schema is also kept as text so a sorted audit writer
    cannot silently change the backend's grammar-property ordering on reload.
    """
    from datetime import date, timedelta
    import copy
    from jsonschema import Draft202012Validator, FormatChecker

    root = Path(root).resolve()
    require(isinstance(inventory, dict) and inventory.get("schema_version") == VERSION,
            "Case contracts require the collected runtime-settings inventory.")
    identity = deepcopy(inventory)
    identifier = identity.pop("settings_id", None)
    require(identifier == sha(packed(identity)), "The runtime-settings inventory changed.")
    bindings = inventory["source_file_sha256"]
    require(isinstance(profiles, list) and len(profiles) == 200,
            "The case contract snapshot requires exactly 200 reviewed public profiles.")

    def read(relative):
        require(relative in bindings, "A case-contract source lacks a reviewed binding: " + relative)
        data = _path(root, relative).read_bytes()
        require(sha(data) == bindings[relative], "A case-contract source changed: " + relative)
        return data

    def pure_functions(relative, names, namespace, constants=()):
        tree = ast.parse(read(relative), filename=relative)
        definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        require({node.name for node in definitions} == set(names), "A required pure contract function changed.")
        extracted = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in constants:
                    extracted[node.targets[0].id] = ast.literal_eval(node.value)
        require(set(extracted) == set(constants), "A required pure contract constant changed.")
        namespace.update(extracted)
        selected = ast.fix_missing_locations(ast.Module(body=definitions, type_ignores=[]))
        exec(compile(selected, relative, "exec"), namespace)
        return namespace

    base_local = _json(read(CONTRACTS + "/planner_response_schema.json"))
    public_schema = _json(read(PUBLIC_SCHEMA))
    base_note = _json(read("artifacts/planners/version3_note_schema.json"))
    evaluator_schema = _json(read("artifacts/planners/version4_evaluator_schema.json"))
    Draft202012Validator.check_schema(public_schema)
    validator = Draft202012Validator(public_schema, format_checker=FormatChecker())
    original = pure_functions("src/champion_athletic_map/llm.py",
        ("_schema_order", "_generation_schema"), {"copy": copy})
    contracts = pure_functions("src/champion_athletic_map/request_contracts.py",
        ("canonical", "sha", "_object", "_array", "_required", "_window", "_has_keyword", "_food_note", "build_contracts"),
        {"deepcopy": deepcopy, "date": date, "timedelta": timedelta, "hashlib": hashlib, "json": json},
        constants=("VERSION", "KINDS"))
    operational = pure_functions("src/champion_athletic_map/operational_runtime.py",
        ("canonical", "sha", "bounded_food_schema", "bounded_contracts"),
        {"deepcopy": deepcopy, "hashlib": hashlib, "json": json}, constants=("FOOD_FIELD_LIMITS",))
    base_native = original["_schema_order"](original["_generation_schema"](base_local))
    canonical = contracts["canonical"]
    wire = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=False, allow_nan=False)
    bundles, rows, seen = {}, [], set()
    for record in profiles:
        require(isinstance(record, dict) and set(record) == {"profile_id", "schema_version", "input"},
                "A case contract received private annotations or an unexpected wrapper field.")
        profile_id = record["profile_id"]
        require(isinstance(profile_id, str) and profile_id not in seen, "Reviewed case identifiers must be distinct.")
        seen.add(profile_id)
        validator.validate(record)
        # This is the unchanged public_input.py projection after schema validation.
        public = _json(canonical(record["input"]))
        bundle = operational["bounded_contracts"](
            contracts["build_contracts"](public, base_local, base_native, base_note))
        native_wire = wire(bundle["native_response_schema"])
        bundle["native_schema_ordered_wire_json"] = native_wire
        bundle["native_schema_ordered_wire_sha256"] = sha(native_wire.encode("utf-8"))
        food_native = original["_schema_order"](original["_generation_schema"](bundle["food_note_schema"]))
        bundle["food_note_native_schema_ordered_wire_json"] = wire(food_native)
        bundle["food_note_native_schema_ordered_wire_sha256"] = sha(wire(food_native).encode("utf-8"))
        bundle_id = sha(canonical(bundle))
        require(bundle_id not in bundles or canonical(bundles[bundle_id]) == canonical(bundle),
                "Derived contract identities disagree.")
        if bundle_id not in bundles:
            for name in ("local_response_schema", "native_response_schema", "food_note_schema"):
                Draft202012Validator.check_schema(bundle[name])
        bundles[bundle_id] = bundle
        rows.append({"profile_id": profile_id, "public_record_canonical_sha256": sha(canonical(record)),
            "public_input_canonical_sha256": sha(canonical(public)), "contract_bundle_id": bundle_id,
            "local_response_schema_sha256": bundle["policy"]["local_response_schema_sha256"],
            "native_response_schema_sha256": bundle["policy"]["native_response_schema_sha256"],
            "native_schema_ordered_wire_sha256": bundle["native_schema_ordered_wire_sha256"],
            "food_note_schema_sha256": bundle["policy"]["food_note_schema_sha256"],
            "food_question_present": bundle["policy"]["food_question_present"]})
    recipe_sources = ("src/champion_athletic_map/llm.py", "src/champion_athletic_map/request_contracts.py",
        "src/champion_athletic_map/operational_runtime.py", "src/champion_athletic_map/contract_runtime.py",
        "src/champion_athletic_map/corrected_runtime.py", "src/champion_athletic_map/food_response_validation.py",
        CONTRACTS + "/public_input.py", CONTRACTS + "/planner_response_schema.json", PUBLIC_SCHEMA,
        "artifacts/planners/version3_note_schema.json", "artifacts/planners/version4_evaluator_schema.json")
    result = {"schema_version": "final-case-response-contracts-1", "runtime_settings_id": identifier,
        "recipe": "llm._schema_order(_generation_schema(base_local)); request_contracts.build_contracts(public_input,base_local,base_native,base_note); operational_runtime.bounded_contracts",
        "recipe_source_sha256": {name: bindings[name] for name in recipe_sources},
        "case_bindings": rows, "contract_bundles": bundles,
        "base_specialist_note_schema": base_note, "evaluator_schema": evaluator_schema,
        "same_final_response_contract_for_planners": [1, 2, 3, 4],
        "food_note_contract_used_only_when_food_specialist_runs": True,
        "native_schema_restored_from_ordered_wire_json_required": True,
        "full_runtime_graph_constructed_or_compared": False,
        "current_backend_schema_compatibility_verified": False,
        "private_annotations_or_expected_answers_read": False,
        "model_calls": 0, "reference_query_encodings": 0,
        "source_functions_only_no_runtime_clients_constructed": True,
        "final_scoring_or_execution_authorized": False}
    for label, schema in (("base_specialist_note", base_note), ("evaluator", evaluator_schema)):
        native = original["_schema_order"](original["_generation_schema"](schema))
        result[label + "_native_schema_ordered_wire_json"] = wire(native)
        result[label + "_native_schema_ordered_wire_sha256"] = sha(wire(native).encode("utf-8"))
    result["contracts_id"] = sha(packed(result))
    return result
