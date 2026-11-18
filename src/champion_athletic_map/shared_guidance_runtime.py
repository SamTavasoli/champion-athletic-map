"""Compose a prospective shared task clarification without changing old planners."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path


RUNTIME_VERSION = "shared-guidance-runtime-1"
GUIDANCE_PATH = "docs/prompts/shared_task_addendum_candidate.txt"
_COMPONENTS = (
    "src/champion_athletic_map/pilot_runtime.py",
    "src/champion_athletic_map/continuation_runtime.py",
    "src/champion_athletic_map/review_encoding.py",
    GUIDANCE_PATH,
    "src/champion_athletic_map/shared_guidance_runtime.py",
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("A shared-guidance source leaves the project.")
    source = path.read_bytes()
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("shared_guidance_" + path.stem, path))
    exec(compile(source, str(path), "exec"), result.__dict__)
    return result


def build_runtime(root, review_config, public_schema, *, runtime_builder=None):
    """Build isolated planner objects; leave generation and reference encoding explicit."""
    root = Path(root).resolve()
    sources = {relative: sha((root / relative).read_bytes()) for relative in _COMPONENTS}
    guidance = (root / GUIDANCE_PATH).read_text(encoding="utf-8")
    if not guidance.strip():
        raise ValueError("The prospective shared task clarification is empty.")
    builder = runtime_builder or load(root, _COMPONENTS[0]).build_runtime
    runtime = builder(root, deepcopy(review_config), deepcopy(public_schema))
    base_manifest = deepcopy(runtime.manifest)
    planners = runtime.planners
    if set(planners) != {1, 2, 3, 4}:
        raise ValueError("The prospective runtime requires all four saved planners.")
    outer, engine = planners[4], planners[4].planner
    nodes = [("v1", planners[1]), ("v2", planners[2]), ("v3", planners[3]),
             ("v4", outer), ("v4.evaluated", engine), ("v4.drafting", engine.drafting)]
    previous = planners[1].instructions
    base_policy = deepcopy(runtime.reference_policy)
    if (not isinstance(previous, str) or not previous.strip()
            or any(node.instructions != previous for _, node in nodes)):
        raise ValueError("The saved planner instruction graph differs across workflows.")
    if (len({id(node.client) for _, node in nodes}) != 4
            or outer.client is not engine.client or engine.drafting.client is not engine.client
            or any(node.client.input_schema != public_schema for _, node in nodes)):
        raise ValueError("The saved shared clients or public schemas differ across workflows.")
    for _, node in nodes:
        if not isinstance(node.config, dict):
            raise ValueError("A saved planner configuration is unavailable.")
        if "reference_policy" in node.config and node.config["reference_policy"] != base_policy:
            raise ValueError("A saved planner reference policy differs from the common policy.")
        if hasattr(node, "roles") and node.roles.reference_policy != base_policy:
            raise ValueError("A saved role reference policy differs from the common policy.")
    expected_roles = [(label + ".roles", node.roles) for label, node in nodes if hasattr(node, "roles")]
    inventory = runtime.roles
    if (len(expected_roles) != 3 or len(inventory) != 3
            or [(row["label"], id(row["target"])) for row in inventory]
                != [(label, id(role)) for label, role in expected_roles]):
        raise ValueError("The complete role inventory differs from the saved workflow graph.")
    if (base_manifest.get("effective_reference_policy") != base_policy
            or base_manifest.get("effective_instructions_sha256") != sha(previous.encode("utf-8"))):
        raise ValueError("The constructed base runtime does not match its recorded instructions and policy.")

    # Construction times are observations, not part of a request configuration identity.
    base_identity = {key: value for key, value in base_manifest.items()
        if key not in ("construction_seconds", "reference_tools_construction_seconds")}
    instructions = previous + "\n\n" + guidance
    identity = {"runtime_version": RUNTIME_VERSION, "base_runtime_identity": base_identity,
        "component_sha256": sources, "guidance_sha256": sha(guidance.encode("utf-8")),
        "effective_instructions_sha256": sha(instructions.encode("utf-8")),
        "review_encoding": "complete-check-columns-1",
        "injected_runtime_builder": runtime_builder is not None}
    configuration_id = sha(canonical(identity).encode("utf-8"))
    policy = {**base_policy, "source_configuration_sha256": configuration_id}

    # The proven review representation retains the existing candidate encoding layer.
    continuation = load(root, _COMPONENTS[1])
    codec = load(root, _COMPONENTS[2])
    if codec.ENCODING_VERSION != identity["review_encoding"]:
        raise ValueError("The prospective review encoding differs from the saved policy.")
    role_type = continuation.encoded_role_type(type(engine.roles), codec)
    replacement = role_type(root, engine.client, engine._adapter, engine.integration)
    replacement.reference_policy = deepcopy(policy)
    for _, node in nodes:
        node.instructions = instructions
        node.config = deepcopy(node.config)
        if "reference_policy" in node.config:
            node.config["reference_policy"] = deepcopy(policy)
        if hasattr(node, "roles"):
            node.roles.reference_policy = deepcopy(policy)
    engine.roles = replacement
    runtime.roles = [{**row, "target": replacement if row["target"] is inventory[1]["target"] else row["target"]}
        for row in inventory]
    runtime.reference_policy = deepcopy(policy)
    runtime.manifest = {**base_manifest, "runtime_version": RUNTIME_VERSION,
        "base_runtime_manifest": base_manifest, "shared_guidance_configuration": identity,
        "shared_guidance_configuration_sha256": configuration_id,
        "shared_guidance_path": GUIDANCE_PATH, "shared_guidance_sha256": identity["guidance_sha256"],
        "effective_instructions_sha256": identity["effective_instructions_sha256"],
        "effective_reference_policy": deepcopy(policy),
        "verified_file_sha256": {**base_manifest.get("verified_file_sha256", {}), **sources},
        "review_encoding": codec.ENCODING_VERSION, "review_encoding_cost_basis": "pinned_native_token_count",
        "candidate_encoding_retained": True, "shared_guidance_applied_to_all_six_nodes": True,
        "legacy_files_modified": False, "acceptance_policy_changed": False,
        "output_and_context_limits_changed": False,
        "constructor_test_doubles": bool(base_manifest.get("constructor_test_doubles")) or runtime_builder is not None,
        "model_calls_during_construction": 0, "query_encoding_during_construction": 0}
    return runtime
