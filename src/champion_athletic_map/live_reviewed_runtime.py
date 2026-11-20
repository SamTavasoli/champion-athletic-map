"""Normalize a verified checker alias for a separately recorded live probe."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path


RUNTIME_VERSION = "reviewed-live-runtime-1"
FROZEN_RUNTIME = "src/champion_athletic_map/reviewed_runtime.py"
CHECKER = "src/champion_athletic_map/reviewed_planning_checks.py"
SOURCE = "src/champion_athletic_map/live_reviewed_runtime.py"
_OLD_CLAUSE = "Specify each new drill's action, setup and participant roles from complete supplied catalog variants;"
_NEW_CLAUSE = ("Describe each new session's actions, setup and participant roles; use complete supplied approved "
               "variants when available, and retain their conditions;")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def load(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("A live-runtime component leaves the project.")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("live_" + path.stem, path))
    exec(compile(path.read_bytes(), str(path), "exec"), result.__dict__)
    return result


def normalize_checker_client(checker, client):
    """Rebind only the equivalent shallow copy made by pilot_schedule.make_checker."""
    previous = checker.client
    if previous is client:
        return checker
    if (previous.public is not client.public
            or canonical(previous.input_schema) != canonical(client.input_schema)
            or canonical(previous.response_schema) != canonical(client.response_schema)):
        raise ValueError("The copied internal checker does not retain the exact public facts and response contract.")
    for name in ("response", "output_schema"):
        if hasattr(previous, name) != hasattr(client, name):
            raise ValueError("The copied checker parser or native response schema differs.")
        if hasattr(client, name):
            left, right = getattr(previous, name), getattr(client, name)
            if (left is not right if name == "response" else canonical(left) != canonical(right)):
                raise ValueError("The copied checker parser or native response schema differs.")
    checker.client = client
    return checker


def build_runtime(root, review_config, public_schema, *, public_record, runtime_builder=None):
    """Use frozen reviewed components with one verified alias and neutral shared wording."""
    root = Path(root).resolve()
    source_bindings = {name: sha((root / name).read_bytes()) for name in (SOURCE, FROZEN_RUNTIME, CHECKER)}
    api = load(root, FROZEN_RUNTIME)
    previous_load = api.load
    normalized = []
    def private_load(project, relative):
        module = previous_load(project, relative)
        if relative == CHECKER:
            original = module.make_checker
            def make_checker(*args, **kwargs):
                client = args[1] if len(args) > 1 else kwargs["client"]
                checker = original(*args, **kwargs)
                was_copy = checker.client is not client
                normalize_checker_client(checker, client)
                normalized.append(was_copy)
                return checker
            module.make_checker = make_checker
        return module
    api.load = private_load
    runtime = api.build_runtime(root, deepcopy(review_config), deepcopy(public_schema),
        public_record=deepcopy(public_record), runtime_builder=runtime_builder)
    planners = runtime.planners
    nodes = [planners[1], planners[2], planners[3], planners[4], planners[4].planner, planners[4].planner.drafting]
    previous_manifest, previous_policy = deepcopy(runtime.manifest), deepcopy(runtime.reference_policy)
    original = nodes[0].instructions
    if any(node.instructions != original for node in nodes) or original.count(_OLD_CLAUSE) != 1:
        raise ValueError("The frozen common planning guidance changed.")
    instructions = original.replace(_OLD_CLAUSE, _NEW_CLAUSE, 1)
    if not normalized or runtime.checker.client is not planners[4].client:
        raise ValueError("The live workflow did not retain its reviewed internal checker client.")
    identity = {"runtime_version": RUNTIME_VERSION,
        "frozen_reviewed_runtime_identity": api.load(root, "src/champion_athletic_map/operational_runtime.py").identity_view(previous_manifest),
        "source_sha256": source_bindings,
        "checker_client_binding": "verified_equivalent_public_and_response_contract_then_alias_to_shared_client",
        "effective_instructions_sha256": sha(instructions.encode("utf-8")),
        "neutral_catalog_clause": _NEW_CLAUSE,
        "intermediate_and_final_budget_guards_changed": False,
        "injected_runtime_builder": runtime_builder is not None}
    identifier = sha(canonical(identity))
    policy = {**previous_policy, "source_configuration_sha256": identifier}
    for node in nodes:
        node.instructions = instructions
        node.config = deepcopy(node.config)
        if "reference_policy" in node.config:
            node.config["reference_policy"] = deepcopy(policy)
        if hasattr(node, "roles"):
            node.roles.reference_policy = deepcopy(policy)
    runtime.reference_policy = deepcopy(policy)
    runtime.reference_preparer_factory, runtime.assessor_factory = build_reference_preparer, make_assessor
    runtime.manifest = {**previous_manifest, "runtime_version": RUNTIME_VERSION,
        "base_runtime_manifest": previous_manifest, "live_runtime_configuration": identity,
        "live_runtime_configuration_sha256": identifier,
        "effective_reference_policy": deepcopy(policy),
        "effective_instructions_sha256": identity["effective_instructions_sha256"],
        "verified_file_sha256": {**previous_manifest.get("verified_file_sha256", {}), **source_bindings},
        "equivalent_checker_client_alias_normalized": any(normalized),
        "baseline_catalog_access_required": False, "baseline_reference_access_changed": False,
        "budget_guards_changed": False, "output_and_context_limits_changed": False,
        "legacy_files_modified": False, "frozen_reviewed_sources_modified": False,
        "model_calls_during_construction": 0, "query_encoding_during_construction": 0,
        "operational_generation_ready": False}
    return runtime


def build_reference_preparer(root, tools, client, policy, **kwargs):
    root = Path(root).resolve()
    preparer = load(root, FROZEN_RUNTIME).build_reference_preparer(root, tools, client, policy, **kwargs)
    relative = SOURCE
    preparer.module_bindings[relative] = sha((root / relative).read_bytes())
    preparer.setup_record["module_bindings"] = deepcopy(preparer.module_bindings)
    preparer.setup_record["live_runtime_source_sha256"] = preparer.module_bindings[relative]
    return preparer


def make_assessor(root, public_schema):
    return load(Path(root).resolve(), FROZEN_RUNTIME).make_assessor(root, public_schema)


make_reference_preparer = build_reference_preparer
