"""Compose request-specific output contracts without changing saved workflows."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path


RUNTIME_VERSION = "request-contract-runtime-1"
_COMPONENTS = tuple("src/champion_athletic_map/" + name + ".py" for name in
    ("contract_runtime", "request_contracts", "shared_guidance_runtime"))
_OLD_FORMAT_SENTENCE = "Omit irrelevant questions, unresolved_issues, food_facts, and evidence_refs."
_NEW_FORMAT_SENTENCE = (
    "Omit irrelevant questions, unresolved_issues and evidence_refs. When a food question is supplied, "
    "include a nonempty food_facts array near the start of the answer. Answer that question using "
    "supported food, amount, nutrient, value and units, or state exactly what cannot be verified. "
    "An explicit unknown statement is allowed; do not invent a recorded nutrient value.")
COMMON_NOTICE = (
    "Follow the supplied request-specific output contract. A plan must retain all seven dates "
    "in order and the original planning window. Include explicit food-question handling when "
    "requested; an honest unknown is preferable to an invented value. Required output presence "
    "does not establish factual correctness or permission to change athlete facts.")
FOOD_NOTICE = (
    "This is the food-facts role. Address athlete_input.food_question directly, without replacing "
    "it with calendar advice. Use the supplied food lookup only when it supports the requested "
    "food, amount, nutrient and units. Put the supported answer in recommendations. Otherwise use "
    "limited_information or outside_scope as appropriate and put the specific unresolved food "
    "question or limitation in unresolved_issues. Do not invent a nutrient value or citation.")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=False, allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("A request-contract source leaves the project.")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("request_contract_" + path.stem, path))
    exec(compile(path.read_bytes(), str(path), "exec"), result.__dict__)
    return result


def identity_view(value):
    """Retain configuration fields while excluding nested construction observations."""
    if isinstance(value, dict):
        return {key: identity_view(item) for key, item in value.items()
            if key not in ("construction_seconds", "reference_tools_construction_seconds")}
    if isinstance(value, list):
        return [identity_view(item) for item in value]
    return value


def food_role(previous, original_schema, new_schema):
    """Preserve an existing isolated role and strengthen only its food stage."""
    if not isinstance(getattr(previous, "__dict__", None), dict):
        raise ValueError("The food role must expose its existing isolated state.")
    old, effective = deepcopy(original_schema), deepcopy(new_schema)
    class FoodContractRole(type(previous)):
        def _food_arguments(self, args, kwargs):
            if kwargs.get("stage") != "food":
                return args, kwargs
            supplied = kwargs.get("output_schema")
            if supplied != old and supplied != effective:
                raise ValueError("The food role received a different note contract.")
            arguments, options = list(args), dict(kwargs)
            options["output_schema"] = deepcopy(effective)
            text = arguments[2] if len(arguments) > 2 else options.get("instructions")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("The food role needs its original nonblank instructions.")
            if not text.endswith("\n\n" + FOOD_NOTICE):
                text += "\n\n" + FOOD_NOTICE
            if len(arguments) > 2:
                arguments[2] = text
            else:
                options["instructions"] = text
            return tuple(arguments), options

        def prepare_request(self, *args, **kwargs):
            arguments, options = self._food_arguments(args, kwargs)
            prepared, payload, configuration = super().prepare_request(*arguments, **options)
            if options.get("stage") == "food":
                configuration = {**configuration, "note_schema_version": "food-note-request-contract-1",
                    "role_policy": "food-note-request-contract-1", "request_contract_runtime": RUNTIME_VERSION}
            return prepared, payload, configuration

        def generate(self, *args, **kwargs):
            # The original transport also parses using this exact effective schema.
            arguments, options = self._food_arguments(args, kwargs)
            return super().generate(*arguments, **options)

    replacement = FoodContractRole.__new__(FoodContractRole)
    replacement.__dict__ = dict(previous.__dict__)
    return replacement


class BoundPublicInput:
    """Delegate original public handling while rejecting use for a different case."""
    def __init__(self, original, expected_sha256):
        self._original, self._expected_sha256 = original, expected_sha256

    def __getattr__(self, name):
        return getattr(self._original, name)

    def prepare_public_input(self, *args, **kwargs):
        prepared = self._original.prepare_public_input(*args, **kwargs)
        if sha(canonical(prepared["public_input"])) != self._expected_sha256:
            raise ValueError("The request contract belongs to a different public athlete input.")
        return prepared


def build_runtime(root, review_config, public_schema, *, public_record, runtime_builder=None):
    """Build only; reference preparation and all model calls remain explicit."""
    root = Path(root).resolve()
    sources = {relative: sha((root / relative).read_bytes()) for relative in _COMPONENTS}
    builder = runtime_builder or load(root, _COMPONENTS[2]).build_runtime
    runtime = builder(root, deepcopy(review_config), deepcopy(public_schema))
    planners = runtime.planners
    if set(planners) != {1, 2, 3, 4}:
        raise ValueError("The contract runtime requires all four saved planners.")
    engine, drafting = planners[4].planner, planners[4].planner.drafting
    nodes = [("v1", planners[1]), ("v2", planners[2]), ("v3", planners[3]),
        ("v4", planners[4]), ("v4.evaluated", engine), ("v4.drafting", drafting)]
    clients = [planners[number].client for number in range(1, 5)]
    instructions = planners[1].instructions
    base_policy, base_manifest = deepcopy(runtime.reference_policy), deepcopy(runtime.manifest)
    if (len({id(client) for client in clients}) != 4 or not isinstance(instructions, str) or not instructions.strip()
            or any(node.instructions != instructions for _, node in nodes)
            or planners[4].client is not engine.client or drafting.client is not engine.client
            or any(node.client.input_schema != public_schema for _, node in nodes)):
        raise ValueError("The shared planner instructions, public schema or client graph changed.")
    if (base_manifest.get("effective_reference_policy") != base_policy
            or base_manifest.get("effective_instructions_sha256") != sha(instructions.encode("utf-8"))):
        raise ValueError("The base runtime differs from its recorded policy or instructions.")
    for _, node in nodes:
        if (not isinstance(node.config, dict)
                or "reference_policy" in node.config and node.config["reference_policy"] != base_policy
                or hasattr(node, "roles") and node.roles.reference_policy != base_policy):
            raise ValueError("A shared planner or role reference policy differs.")
    expected_roles = [(label + ".roles", node.roles) for label, node in nodes if hasattr(node, "roles")]
    if (len(expected_roles) != 3 or len(runtime.roles) != 3
            or [(item["label"], id(item["target"])) for item in runtime.roles]
                != [(label, id(role)) for label, role in expected_roles]):
        raise ValueError("The complete role tracing inventory changed.")
    local, native = clients[0].response_schema, clients[0].output_schema
    if (any(canonical(client.response_schema) != canonical(local) or wire(client.output_schema) != wire(native)
            for client in clients[1:]) or planners[3].note_schema != drafting.note_schema):
        raise ValueError("The original response or specialist contracts differ across planners.")
    prepared = [client.public.prepare_public_input(deepcopy(public_record), client.input_schema) for client in clients]
    public = prepared[0]["public_input"]
    if any(canonical(value["public_input"]) != canonical(public) for value in prepared[1:]):
        raise ValueError("The planners project different public facts.")
    contracts = load(root, _COMPONENTS[1]).build_contracts(public, local, native, planners[3].note_schema)

    # Verify every private adapter before changing any instruction or schema.
    globals_by_client = {}
    for client in clients:
        function = getattr(client.prepare_request, "__func__", None)
        namespace = getattr(function, "__globals__", None)
        text = namespace.get("RESPONSE_FORMAT") if isinstance(namespace, dict) else None
        if not isinstance(text, str) or text.count(_OLD_FORMAT_SENTENCE) != 1:
            raise ValueError("The original private response-format guidance changed.")
        globals_by_client[id(client)] = namespace
    if len({id(value) for value in globals_by_client.values()}) != 4:
        raise ValueError("The four clients must retain isolated adapter namespaces.")
    format_texts = [value["RESPONSE_FORMAT"] for value in globals_by_client.values()]
    if len(set(format_texts)) != 1:
        raise ValueError("The private response-format guidance differs across planners.")
    for _, node in nodes:
        namespace = globals_by_client[id(node.client)]
        if hasattr(node, "_adapter") and node._adapter.__dict__ is not namespace:
            raise ValueError("A planner uses a different private shared adapter.")
        if hasattr(node, "roles") and node.roles.shared.__dict__ is not namespace:
            raise ValueError("A role uses a different private shared adapter.")
    replacements = {}
    for node in (planners[3], drafting):
        replacements[id(node.roles)] = food_role(node.roles, node.note_schema, contracts["food_note_schema"])

    final_instructions = instructions + "\n\n" + COMMON_NOTICE
    identity = {"runtime_version": RUNTIME_VERSION, "base_runtime_identity": identity_view(base_manifest),
        "component_sha256": sources, "public_input_sha256": sha(canonical(public)),
        "contract_policy": deepcopy(contracts["policy"]),
        "native_schema_ordered_wire_sha256": sha(wire(contracts["native_response_schema"])),
        "effective_instructions_sha256": sha(final_instructions.encode("utf-8")),
        "effective_format_guidance_sha256": sha(format_texts[0].replace(_OLD_FORMAT_SENTENCE, _NEW_FORMAT_SENTENCE, 1).encode("utf-8")),
        "format_guidance_replacement_sha256": sha(_NEW_FORMAT_SENTENCE.encode("utf-8")),
        "food_guidance_sha256": sha(FOOD_NOTICE.encode("utf-8")),
        "injected_runtime_builder": runtime_builder is not None}
    configuration_id = sha(canonical(identity))
    policy = {**base_policy, "source_configuration_sha256": configuration_id}
    for client in clients:
        namespace = globals_by_client[id(client)]
        namespace["RESPONSE_FORMAT"] = namespace["RESPONSE_FORMAT"].replace(_OLD_FORMAT_SENTENCE, _NEW_FORMAT_SENTENCE, 1)
        client.response_schema = deepcopy(contracts["local_response_schema"])
        client.output_schema = deepcopy(contracts["native_response_schema"])
        client.public = BoundPublicInput(client.public, identity["public_input_sha256"])
    for _, node in nodes:
        node.instructions = final_instructions
        node.config = deepcopy(node.config)
        if "reference_policy" in node.config:
            node.config["reference_policy"] = deepcopy(policy)
        if hasattr(node, "roles"):
            node.roles = replacements.get(id(node.roles), node.roles)
            node.roles.reference_policy = deepcopy(policy)
    runtime.roles = [{**item, "target": replacements.get(id(item["target"]), item["target"])} for item in runtime.roles]
    runtime.reference_policy = deepcopy(policy)
    runtime.request_contracts = deepcopy(contracts)
    runtime.manifest = {**base_manifest, "runtime_version": RUNTIME_VERSION,
        "base_runtime_manifest": base_manifest, "request_contract_configuration": identity,
        "request_contract_configuration_sha256": configuration_id,
        "effective_reference_policy": deepcopy(policy),
        "effective_instructions_sha256": identity["effective_instructions_sha256"],
        "verified_file_sha256": {**base_manifest.get("verified_file_sha256", {}), **sources},
        "public_input_sha256": identity["public_input_sha256"], "contract_policy": deepcopy(contracts["policy"]),
        "bound_public_input_guard": True,
        "native_schema_ordered_wire_sha256": identity["native_schema_ordered_wire_sha256"],
        "four_final_response_contracts_equal": True, "common_instructions_applied_to_all_six_nodes": True,
        "food_role_contracts_equal": True, "three_role_trace_targets_preserved": True,
        "evaluator_revision_role_retained": True, "legacy_files_modified": False,
        "athlete_facts_changed": False, "food_lookup_values_injected": False,
        "acceptance_policy_changed": False, "output_and_context_limits_changed": False,
        "constructor_test_doubles": bool(base_manifest.get("constructor_test_doubles")) or runtime_builder is not None,
        "model_calls_during_construction": 0, "query_encoding_during_construction": 0,
        "native_backend_contract_verified": False, "operational_generation_ready": False}
    return runtime
