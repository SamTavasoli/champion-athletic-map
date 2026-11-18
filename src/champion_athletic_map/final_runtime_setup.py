"""Bind the prospective final runtime to the frozen public response contracts.

Construction performs no model request or reference query. The final runner is
still responsible for each actual request's backend rendering and token budget.
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


VERSION = "frozen-final-public-runtime-1"
SOURCE = "src/champion_athletic_map/final_runtime_setup.py"
REQUESTS = "src/champion_athletic_map/final_request_checks.py"
BASE = "src/champion_athletic_map/corrected_runtime.py"


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=False,
                      allow_nan=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def module(root, relative):
    path = (root / relative).resolve()
    require(path.is_relative_to(root), "A final-runtime component leaves the project.")
    spec = importlib.util.spec_from_file_location("final_setup_" + path.stem, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def validate_case_bindings(profiles, case_contracts):
    """Check all public versions and schemas without constructing 200 clients."""
    identity = deepcopy(case_contracts)
    declared = identity.pop("contracts_id", None)
    require(declared == sha(packed(identity)), "The frozen response-contract identity differs.")
    require(isinstance(profiles, list) and len(profiles) == 200,
            "The final runtime needs the frozen 200-case roster.")
    require(all(isinstance(row, dict) and set(row) == {"profile_id", "schema_version", "input"}
                for row in profiles), "Only public case wrappers may enter final runtime setup.")
    require(len({row["profile_id"] for row in profiles}) == 200,
            "The final public case roster has duplicate identifiers.")
    rows = case_contracts.get("case_bindings")
    require(isinstance(rows, list) and len(rows) == 200, "The frozen response bindings are incomplete.")
    bindings = {row["profile_id"]: row for row in rows}
    require(len(bindings) == 200 and set(bindings) == {row["profile_id"] for row in profiles},
            "The response contracts and public case roster differ.")
    for record in profiles:
        binding = bindings[record["profile_id"]]
        require(binding["public_record_canonical_sha256"] == sha(canonical(record))
                and binding["public_input_canonical_sha256"] == sha(canonical(record["input"])),
                "A final runtime case differs from its frozen public version.")
        bundle = case_contracts["contract_bundles"][binding["contract_bundle_id"]]
        require(binding["contract_bundle_id"] == sha(canonical(bundle))
                and binding["local_response_schema_sha256"] == sha(canonical(bundle["local_response_schema"]))
                and binding["native_response_schema_sha256"] == sha(canonical(bundle["native_response_schema"])),
                "A final local or native response schema differs from its frozen binding.")
        text = bundle["native_schema_ordered_wire_json"]
        require(sha(text.encode("utf-8")) == binding["native_schema_ordered_wire_sha256"]
                == bundle["native_schema_ordered_wire_sha256"]
                and canonical(json.loads(text)) == canonical(bundle["native_response_schema"]),
                "The native schema's ordered wire form differs from its frozen binding.")
    return bindings


@contextmanager
def without_network():
    """Fail construction if any component attempts a connection."""
    attempts = []
    def blocked(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError("Final-runtime construction cannot access the network.")
    with patch("socket.create_connection", blocked), patch("socket.socket.connect", blocked), patch("socket.socket.connect_ex", blocked):
        yield attempts
    require(not attempts, "A runtime constructor attempted network access.")


def patch_public_checker(checker, request_api):
    """Use the same public literal evidence in V4, without private case labels."""
    core = checker.check.__func__.__globals__
    require(callable(core.get("_request_facts")) and callable(core.get("_basis")),
            "The internal public checker extension point changed.")
    original_facts, original_basis = core["_request_facts"], core["_basis"]
    core["_request_facts"] = lambda public: request_api.request_facts(public, original_facts(public))
    def basis(public, response):
        facts = core["_request_facts"](public)
        kind = response.get("response_type")
        if facts.get("outside_scope"):
            return ("met" if kind == "outside_scope" else "violated",
                "The public request asks for a service outside the basketball-planning prototype.", kind == "outside_scope", facts)
        proof = request_api.response_conflict_basis(public, response)
        if proof is not None:
            return proof["status"], proof["reason"], proof["supported_nonplan"], facts
        missing = facts.get("essential_missing") or []
        if missing:
            if kind != "clarification":
                return "violated", "Essential public information remains missing: " + ", ".join(missing) + ".", False, facts
            questions = " ".join(response.get("questions") or []).casefold()
            terms = {"age": ("age", "old"), "availability": ("availab", "date", "time", "window"),
                "participants": ("participant", "people", "person", "group", "how many"),
                "existing_commitments": ("existing", "event", "practice", "game", "commitment", "schedule"),
                "court_or_hoop": ("court", "hoop", "basket", "space", "area")}
            supported = all(field in terms and any(term in questions for term in terms[field]) for field in missing)
            return ("met" if supported else "unknown", "Clarification addresses the essential missing public facts." if supported else
                "The questions do not establish all essential missing public facts.", supported, facts)
        return original_basis(public, response)
    core["_basis"] = basis
    checker.final_public_request_policy = {"version": request_api.VERSION,
        "private_case_annotations_used": False, "acceptance_check_ids_or_thresholds_changed": False}


def inspect_graph(runtime, record, bundle, case_contracts, public_schema):
    """Validate every live planner/client/role alias used by the saved workflows."""
    planners = runtime.planners
    require(set(planners) == {1, 2, 3, 4}, "The final runtime needs all four planner workflows.")
    require(type(planners[4]).__name__ == "CandidateFocusedEvaluatedPlanner",
            "The final runtime must use the recorded candidate-focused Planner 4.")
    engine, drafting = planners[4].planner, planners[4].planner.drafting
    nodes = [("v1", planners[1]), ("v2", planners[2]), ("v3", planners[3]),
        ("v4", planners[4]), ("v4.evaluated", engine), ("v4.drafting", drafting)]
    clients = [planners[number].client for number in range(1, 5)]
    require(len({id(client) for client in clients}) == 4
            and engine.client is clients[3] and drafting.client is clients[3],
            "The final runtime client graph differs from the four recorded clients.")
    require(len(runtime.clients) == 4 and {id(row["target"]) for row in runtime.clients} == {id(c) for c in clients},
            "The final client tracing inventory is incomplete.")
    require(runtime.checker is engine.checker and runtime.checker.client is clients[3],
            "The internal checker is not bound to the final Planner 4 client.")
    require(all(canonical(node.client.input_schema) == canonical(public_schema) for _, node in nodes),
            "A final node uses a different public input schema.")
    instructions = nodes[0][1].instructions
    require(isinstance(instructions, str) and instructions.strip()
            and all(node.instructions == instructions for _, node in nodes),
            "The final planners do not share the same complete task instructions.")
    ordered_native = json.loads(bundle["native_schema_ordered_wire_json"])
    restored = False
    for client in clients:
        require(canonical(client.response_schema) == canonical(bundle["local_response_schema"])
                and canonical(client.output_schema) == canonical(ordered_native),
                "A constructed runtime uses another effective response contract.")
        restored |= wire(client.output_schema) != bundle["native_schema_ordered_wire_json"]
        client.output_schema = deepcopy(ordered_native)
        prepared = client.public.prepare_public_input(deepcopy(record), client.input_schema)
        require(canonical(prepared["public_input"]) == canonical(record["input"]),
                "A final planner changed the public athlete facts.")
    require(all(wire(client.output_schema) == bundle["native_schema_ordered_wire_json"] for client in clients),
            "The runtime did not retain the frozen ordered native response contract.")
    expected_roles = [(label + ".roles", node.roles) for label, node in nodes if hasattr(node, "roles")]
    require(len(expected_roles) == len(runtime.roles) == 3
            and [(row["label"], id(row["target"])) for row in runtime.roles]
                == [(label, id(role)) for label, role in expected_roles],
            "The final specialist and evaluator role tracing inventory differs.")
    require(runtime.manifest.get("effective_reference_policy") == runtime.reference_policy
            and all(("reference_policy" not in node.config or node.config["reference_policy"] == runtime.reference_policy)
                    and (not hasattr(node, "roles") or node.roles.reference_policy == runtime.reference_policy)
                    for _, node in nodes), "The final nodes do not share their recorded reference policy.")
    for node in (planners[3], drafting):
        require(canonical(node.note_schema) == canonical(case_contracts["base_specialist_note_schema"]),
                "A final specialist uses another base note schema.")
        shared = node.roles.shared
        base_wire = wire(shared._schema_order(shared._generation_schema(node.note_schema)))
        require(base_wire == case_contracts["base_specialist_note_native_schema_ordered_wire_json"],
                "A specialist's ordered native note schema differs.")
        require(callable(getattr(node.roles, "_food_arguments", None)),
                "The food role lost its request-specific contract binding.")
        _arguments, options = node.roles._food_arguments((), {"stage": "food",
            "output_schema": deepcopy(node.note_schema), "instructions": "Schema preparation check."})
        require(canonical(options["output_schema"]) == canonical(bundle["food_note_schema"])
                and wire(shared._schema_order(shared._generation_schema(options["output_schema"])))
                    == bundle["food_note_native_schema_ordered_wire_json"],
                "The conditional food role differs from its frozen schema.")
    require(canonical(engine.evaluator_schema) == canonical(case_contracts["evaluator_schema"])
            and wire(engine.roles.shared._schema_order(engine.roles.shared._generation_schema(engine.evaluator_schema)))
                == case_contracts["evaluator_native_schema_ordered_wire_json"],
            "The evaluator schema differs from the frozen contract.")
    require(getattr(runtime.tools.core, "_query_runtime", object()) is None,
            "A reference query runtime was loaded during final construction.")
    require(runtime.manifest.get("model_calls_during_construction") == 0
            and runtime.manifest.get("query_encoding_during_construction") == 0,
            "The runtime construction receipt reports a model or query call.")
    return {"planner_nodes_verified": 6, "distinct_clients_verified": 4,
        "role_targets_verified": 3, "internal_checker_client_verified": True,
        "all_public_projections_equal": True, "all_effective_response_contracts_equal": True,
        "native_schema_order_restored_from_frozen_wire": bool(restored),
        "specialist_food_and_evaluator_schema_bindings_verified": True,
        "local_instruction_tokenization_may_occur": True,
        "reference_query_runtime_loaded": False, "actual_request_budget_verified": False}


def build_runtime(root, review_config, public_schema, *, public_record, case_contracts, runtime_builder=None):
    """Construct the amended final runtime for exactly one authoritative public case."""
    root = Path(root).resolve()
    require(isinstance(public_record, dict) and set(public_record) == {"profile_id", "schema_version", "input"},
            "Final runtime construction accepts public input only.")
    identity = deepcopy(case_contracts)
    require(identity.pop("contracts_id", None) == sha(packed(identity)),
            "The frozen response-contract identity differs.")
    candidates = [row for row in case_contracts["case_bindings"] if row["profile_id"] == public_record["profile_id"]]
    require(len(candidates) == 1, "The public case needs one frozen response binding.")
    binding = candidates[0]
    require(binding["public_record_canonical_sha256"] == sha(canonical(public_record))
            and binding["public_input_canonical_sha256"] == sha(canonical(public_record["input"])),
            "The runtime request differs from its frozen public case.")
    bundle = case_contracts["contract_bundles"][binding["contract_bundle_id"]]
    require(binding["contract_bundle_id"] == sha(canonical(bundle))
            and binding["local_response_schema_sha256"] == sha(canonical(bundle["local_response_schema"]))
            and binding["native_response_schema_sha256"] == sha(canonical(bundle["native_response_schema"])),
            "A frozen contract bundle or effective schema differs.")
    ordered = bundle["native_schema_ordered_wire_json"]
    require(sha(ordered.encode("utf-8")) == binding["native_schema_ordered_wire_sha256"]
            == bundle["native_schema_ordered_wire_sha256"]
            and canonical(json.loads(ordered)) == canonical(bundle["native_response_schema"]),
            "The native schema's ordered wire form differs from its frozen binding.")
    builder = runtime_builder or module(root, BASE).build_runtime
    with without_network():
        runtime = builder(root, deepcopy(review_config), deepcopy(public_schema), public_record=deepcopy(public_record))
    graph = inspect_graph(runtime, public_record, bundle, case_contracts, public_schema)
    previous_manifest = deepcopy(runtime.manifest)
    requests = module(root, REQUESTS)
    patch_public_checker(runtime.checker, requests)
    source_bindings = {relative: sha((root / relative).read_bytes()) for relative in (SOURCE, REQUESTS, BASE)}
    amendment = {"runtime_version": VERSION, "base_runtime_version": previous_manifest.get("runtime_version"),
        "source_sha256": source_bindings, "contracts_id": case_contracts["contracts_id"],
        "public_input_sha256": sha(canonical(public_record["input"])),
        "contract_bundle_id": binding["contract_bundle_id"],
        "effective_instructions_sha256": sha(runtime.planners[1].instructions.encode("utf-8")),
        "public_request_checker_amendment": requests.VERSION,
        "amendment_scope": "Literal practice-block counts/durations, demonstrated distinct-date conflicts and public missing-information/scope basis in the isolated V4 checker; unchanged thresholds and acceptance IDs.",
        "original_case_settings_preserved": True, "private_case_annotations_used": False,
        "case_population_or_model_changed": False, "output_or_context_limits_changed": False,
        "reference_access_or_instruction_text_changed": False,
        "injected_runtime_builder": runtime_builder is not None}
    runtime.manifest = {**previous_manifest, "runtime_version": VERSION,
        "base_runtime_manifest": previous_manifest, "final_runtime_amendment": amendment,
        "final_runtime_amendment_sha256": sha(canonical(amendment)), "final_graph_checks": graph,
        "constructor_test_doubles": bool(previous_manifest.get("constructor_test_doubles")) or runtime_builder is not None,
        "final_protocol_frozen": False, "final_planner_execution_authorized": False,
        "operational_generation_ready": False, "model_calls_during_construction": 0,
        "query_encoding_during_construction": 0}
    return runtime


def verify_representative_graphs(root, review_config, public_schema, profiles, case_contracts,
                                 *, runtime_builder=None, software_fixture=False):
    """Inspect one complete graph per unique final contract, retaining exact scope."""
    bindings = validate_case_bindings(profiles, case_contracts)
    representatives = {}
    for record in profiles:
        representatives.setdefault(bindings[record["profile_id"]]["contract_bundle_id"], record)
    require(len(representatives) == 2, "The recorded final cases use food-present and food-absent contract variants.")
    runtimes, rows = {}, []
    for bundle_id, record in representatives.items():
        runtime = build_runtime(root, review_config, public_schema, public_record=record,
                                case_contracts=case_contracts, runtime_builder=runtime_builder)
        if not software_fixture:
            require(runtime.manifest.get("constructor_test_doubles") is False,
                    "A software constructor fixture cannot establish the native final runtime graph.")
        runtimes[bundle_id] = runtime
        rows.append({"profile_id": record["profile_id"], "public_input_sha256": sha(canonical(record["input"])),
            "contract_bundle_id": bundle_id, "graph": deepcopy(runtime.manifest["final_graph_checks"]),
            "runtime_amendment": deepcopy(runtime.manifest["final_runtime_amendment"]),
            "runtime_amendment_sha256": runtime.manifest["final_runtime_amendment_sha256"]})
    report = {"schema_version": VERSION, "frozen_public_bindings_verified": 200,
        "representative_runtime_graphs_verified": len(rows), "graph_checks": rows,
        "all_200_runtime_graphs_constructed": False, "native_runtime_graphs_verified": not software_fixture,
        "software_fixture": software_fixture, "model_calls": 0, "reference_query_encodings": 0,
        "metadata_requests": 0, "current_backend_identity_verified": False,
        "actual_200_case_request_budgets_verified": False,
        "complete_final_packets_prepared": False, "final_protocol_frozen": False,
        "final_planner_execution_authorized": False}
    return {"report": report, "runtimes": runtimes}
