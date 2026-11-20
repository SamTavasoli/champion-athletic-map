"""Bound optional identifiers and factor repeated food fields in private requests."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import MethodType


RUNTIME_VERSION = "bounded-lossless-reference-runtime-1"
FOOD_FIELD_LIMITS = {"food_id": 64, "source_ref": 512}
_COMPONENTS = tuple("src/champion_athletic_map/" + name + ".py" for name in
    ("operational_runtime", "food_reference_encoding", "contract_runtime"))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=False, allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("An operational runtime source leaves the project.")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("operational_" + path.stem, path))
    exec(compile(path.read_bytes(), str(path), "exec"), result.__dict__)
    return result


def identity_view(value):
    if isinstance(value, dict):
        return {key: identity_view(item) for key, item in value.items()
            if key not in ("construction_seconds", "reference_tools_construction_seconds")}
    if isinstance(value, list):
        return [identity_view(item) for item in value]
    return value


def bounded_food_schema(schema):
    """Limit only optional food identifier strings; retain all existing variants."""
    result, locations = deepcopy(schema), []
    def walk(value):
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            fields = value.get("properties")
            if isinstance(fields, dict) and "food_facts" in fields:
                alternatives = fields["food_facts"].get("anyOf", [fields["food_facts"]])
                arrays = [item for item in alternatives if isinstance(item, dict) and item.get("type") == "array"]
                if len(arrays) != 1:
                    raise ValueError("Food facts need their original unambiguous array branch.")
                facts = arrays[0].get("items", {}).get("properties", {})
                for name, limit in FOOD_FIELD_LIMITS.items():
                    item = facts.get(name)
                    if not isinstance(item, dict):
                        raise ValueError("A food identifier schema changed.")
                    strings = [branch for branch in item.get("anyOf", [item])
                        if isinstance(branch, dict) and branch.get("type") == "string"]
                    if len(strings) != 1:
                        raise ValueError("A food identifier needs one original string branch.")
                    strings[0]["maxLength"] = min(strings[0].get("maxLength", limit), limit)
                locations.append(True)
            for item in value.values():
                walk(item)
    walk(result)
    if not locations:
        raise ValueError("The response schema has no original food-facts fields.")
    return result


def bounded_contracts(bundle):
    result = deepcopy(bundle)
    for name in ("local_response_schema", "native_response_schema"):
        result[name] = bounded_food_schema(result[name])
    result["policy"].update(operational_food_field_limits=deepcopy(FOOD_FIELD_LIMITS),
        identifier_bounds_establish_source_validity=False,
        local_response_schema_sha256=sha(canonical(result["local_response_schema"])),
        native_response_schema_sha256=sha(canonical(result["native_response_schema"])))
    return result


def encoded_request(prepared, payload, configuration, *, codec, strict_decode, budget):
    payload, configuration = deepcopy(payload), dict(configuration)
    view = strict_decode(payload["messages"][1]["content"].encode("utf-8"))
    if not isinstance(view, dict) or "athlete_input" not in view or "reference_data" not in view or "response_type" in view:
        raise ValueError("Reference encoding requires the original complete model input view.")
    encoded = codec.encode_view(view)
    if canonical(codec.decode_view(encoded)) != canonical(view):
        raise ValueError("Food reference encoding changed original model input values.")
    changed = canonical(encoded) != canonical(view)
    if changed:
        payload["messages"][0]["content"] += "\n\n" + codec.ENCODING_NOTICE
        payload["messages"][1]["content"] = canonical(encoded).decode("utf-8")
    configuration.update(food_reference_encoding=codec.ENCODING_VERSION if changed else "unchanged",
        food_reference_encoding_version=codec.ENCODING_VERSION, lossless_food_reference_roundtrip_verified=True,
        message_sha256=[sha(item["content"].encode("utf-8")) for item in payload["messages"]])
    if changed:
        configuration["user_serialization"] = "compact_json_with_complete_food_nutrient_table"
    budget(payload)
    return prepared, payload, configuration


def encoded_role(previous, codec, strict_decode):
    class FoodReferenceRole(type(previous)):
        def prepare_request(self, *args, **kwargs):
            prepared, payload, configuration = super().prepare_request(*args, **kwargs)
            return encoded_request(prepared, payload, configuration, codec=codec,
                strict_decode=strict_decode, budget=self._budget_view)
    replacement = FoodReferenceRole.__new__(FoodReferenceRole)
    replacement.__dict__ = dict(previous.__dict__)
    return replacement


def build_runtime(root, review_config, public_schema, *, public_record, runtime_builder=None):
    """Construct a prospective runtime; perform no generation or reference encoding job."""
    root = Path(root).resolve()
    sources = {relative: sha((root / relative).read_bytes()) for relative in _COMPONENTS}
    base_api, codec = load(root, _COMPONENTS[2]), load(root, _COMPONENTS[1])
    builder = runtime_builder or base_api.build_runtime
    runtime = builder(root, deepcopy(review_config), deepcopy(public_schema), public_record=deepcopy(public_record))
    planners = runtime.planners
    if set(planners) != {1, 2, 3, 4}:
        raise ValueError("The operational runtime requires all four saved workflows.")
    engine, drafting = planners[4].planner, planners[4].planner.drafting
    nodes = [("v1", planners[1]), ("v2", planners[2]), ("v3", planners[3]),
        ("v4", planners[4]), ("v4.evaluated", engine), ("v4.drafting", drafting)]
    clients = [planners[number].client for number in range(1, 5)]
    policy, base_manifest = deepcopy(runtime.reference_policy), deepcopy(runtime.manifest)
    if (len({id(client) for client in clients}) != 4 or engine.client is not clients[3] or drafting.client is not clients[3]
            or any(node.instructions != nodes[0][1].instructions for _, node in nodes)
            or base_manifest.get("effective_reference_policy") != policy):
        raise ValueError("The common contract runtime graph changed.")
    expected_roles = [(label + ".roles", node.roles) for label, node in nodes if hasattr(node, "roles")]
    if (len(expected_roles) != 3 or len(runtime.roles) != 3
            or [(row["label"], id(row["target"])) for row in runtime.roles] != [(label, id(role)) for label, role in expected_roles]):
        raise ValueError("The operational role tracing inventory changed.")
    before = runtime.request_contracts
    if any(canonical(client.response_schema) != canonical(before["local_response_schema"])
            or wire(client.output_schema) != wire(before["native_response_schema"]) for client in clients):
        raise ValueError("The four final response contracts differ from the recorded base.")
    for _, node in nodes:
        if ("reference_policy" in node.config and node.config["reference_policy"] != policy
                or hasattr(node, "roles") and node.roles.reference_policy != policy):
            raise ValueError("A planner or role differs from the common reference policy.")
    bundle = bounded_contracts(before)
    adapters, strict_decoders = {}, {}
    for node in (planners[2], planners[3], engine):
        shared = node._adapter
        namespace = getattr(getattr(node.client.prepare_request, "__func__", None), "__globals__", None)
        if namespace is not shared.__dict__ or not callable(shared._decode):
            raise ValueError("A reference-enabled client uses another private decoder.")
        adapters[id(node.client)] = shared
        strict_decoders[id(node.client)] = shared._decode
    if len({id(item) for item in adapters.values()}) != 3 or planners[1]._adapter in adapters.values():
        raise ValueError("The baseline and reference-enabled adapters must stay isolated.")
    for _, node in nodes:
        if hasattr(node, "roles") and node.roles.shared is not adapters[id(node.client)]:
            raise ValueError("A role uses another private shared decoder.")
    replacements = {id(role): encoded_role(role, codec, strict_decoders[id(role.client)]) for _, role in expected_roles}
    old_v2_prepare = planners[2].client.prepare_request
    def prepared_v2(self, *args, **kwargs):
        prepared, payload, configuration = old_v2_prepare(*args, **kwargs)
        return encoded_request(prepared, payload, configuration, codec=codec,
            strict_decode=strict_decoders[id(self)], budget=self._budget_view)
    identity = {"runtime_version": RUNTIME_VERSION, "base_runtime_identity": identity_view(base_manifest),
        "component_sha256": sources, "food_field_limits": deepcopy(FOOD_FIELD_LIMITS),
        "contract_bundle_sha256": sha(canonical(bundle)),
        "native_schema_ordered_wire_sha256": sha(wire(bundle["native_response_schema"])),
        "food_reference_encoding": codec.ENCODING_VERSION, "encoding_notice_sha256": sha(codec.ENCODING_NOTICE.encode("utf-8")),
        "injected_runtime_builder": runtime_builder is not None}
    identifier = sha(canonical(identity))
    effective_policy = {**policy, "source_configuration_sha256": identifier}
    for client in clients:
        client.response_schema, client.output_schema = deepcopy(bundle["local_response_schema"]), deepcopy(bundle["native_response_schema"])
    planners[2].client.prepare_request = MethodType(prepared_v2, planners[2].client)
    for client_id, shared in adapters.items():
        original = strict_decoders[client_id]
        def decoded(data, original=original):
            value = original(data)
            if isinstance(value, dict) and "athlete_input" in value and "reference_data" in value and "response_type" not in value:
                return codec.decode_view(value)
            return value
        shared._decode = decoded
    for _, node in nodes:
        node.config = deepcopy(node.config)
        if "reference_policy" in node.config:
            node.config["reference_policy"] = deepcopy(effective_policy)
        if hasattr(node, "roles"):
            node.roles = replacements[id(node.roles)]
            node.roles.reference_policy = deepcopy(effective_policy)
    runtime.roles = [{**row, "target": replacements[id(row["target"])]} for row in runtime.roles]
    runtime.reference_policy, runtime.request_contracts = deepcopy(effective_policy), deepcopy(bundle)
    runtime.manifest = {**base_manifest, "runtime_version": RUNTIME_VERSION, "base_runtime_manifest": base_manifest,
        "operational_configuration": identity, "operational_configuration_sha256": identifier,
        "effective_reference_policy": deepcopy(effective_policy),
        "verified_file_sha256": {**base_manifest.get("verified_file_sha256", {}), **sources},
        "native_schema_ordered_wire_sha256": identity["native_schema_ordered_wire_sha256"],
        "food_field_limits": deepcopy(FOOD_FIELD_LIMITS), "contract_policy": deepcopy(bundle["policy"]),
        "reference_encoding": codec.ENCODING_VERSION, "reference_encoding_applied_to_versions": [2, 3, 4],
        "baseline_reference_access_changed": False, "all_reference_values_and_qualifications_preserved": True,
        "food_local_parse_contract_retained": True, "candidate_and_check_encoding_retained": True,
        "three_role_trace_targets_preserved": True, "legacy_files_modified": False,
        "acceptance_policy_changed": False, "output_and_context_limits_changed": False,
        "constructor_test_doubles": bool(base_manifest.get("constructor_test_doubles")) or runtime_builder is not None,
        "model_calls_during_construction": 0, "query_encoding_during_construction": 0,
        "new_native_backend_contract_verified": False, "operational_generation_ready": False}
    return runtime
