"""Compose the four saved planners with one recorded, in-memory pilot boundary."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace


RUNTIME_VERSION = "pilot-runtime-1"
_CONFIGS = {1: "artifacts/planners/version1_config.json", 2: "artifacts/planners/version2_config.json",
    3: "artifacts/planners/version3_config.json", 4: "artifacts/planners/version4_config.json"}
_CANDIDATE = "artifacts/planners/version4_candidate_focused_config.json"
_WORKFLOWS = {1: ("src/champion_athletic_map/planners/llm_only.py", "LLMOnlyPlanner"),
    2: ("src/champion_athletic_map/planners/rag.py", "RAGPlanner"),
    3: ("src/champion_athletic_map/planners/specialists.py", "SpecialistPlanner"),
    4: ("src/champion_athletic_map/planners/candidate_focused.py", "CandidateFocusedEvaluatedPlanner")}


def _packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _read(root, relative, bindings, expected=None):
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("A pilot runtime dependency must be project-relative.")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("A pilot runtime dependency leaves the project.")
    data = path.read_bytes()
    digest = _sha(data)
    if expected is not None and digest != expected:
        raise ValueError("A saved pilot runtime dependency changed: " + relative)
    if relative in bindings and bindings[relative] != digest:
        raise ValueError("A pilot runtime dependency has inconsistent bindings.")
    bindings[relative] = digest
    return data


def _module(root, relative, bindings, expected=None):
    source = _read(root, relative, bindings, expected)
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("pilot_runtime_" + Path(relative).stem, root / relative))
    exec(compile(source, str(root / relative), "exec"), result.__dict__)
    return result


def _declared_files(root, value, bindings):
    if not isinstance(value, dict):
        return
    if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
        _read(root, value["path"], bindings, value["sha256"])
    for relative, expected in value.get("module_sha256", {}).items():
        _read(root, relative, bindings, expected)
    for key, relative in value.items():
        if key.endswith("_path") and isinstance(relative, str) and key[:-5] + "_sha256" in value:
            _read(root, relative, bindings, value[key[:-5] + "_sha256"])
        elif isinstance(relative, dict):
            _declared_files(root, relative, bindings)


def build_runtime(root, review_config, public_schema, *, constructors=None, schedule_module=None):
    """Construct only; calls, query-runtime loading, and encoding remain explicit."""
    started = perf_counter()
    root, bindings = Path(root).resolve(), {}
    review_config, public_schema = deepcopy(review_config), deepcopy(public_schema)
    if review_config.get("public_schema_sha256") != _sha(_packed(public_schema)):
        raise ValueError("The pilot public schema differs from its reviewed binding.")
    schedule_path = "src/champion_athletic_map/pilot_schedule.py"
    for relative, expected in review_config.get("component_sha256", {}).items():
        _read(root, relative, bindings, expected)
    expected_schedule = review_config.get("component_sha256", {}).get(schedule_path)
    if not isinstance(expected_schedule, str):
        raise ValueError("The reviewed pilot checker binding is required.")
    _read(root, schedule_path, bindings, expected_schedule)
    schedule = schedule_module or _module(root, schedule_path, bindings, expected_schedule)
    if review_config.get("common_task_addendum") != schedule.COMMON_TASK_ADDENDUM:
        raise ValueError("The pilot task addendum differs from its case review.")
    configs = {version: json.loads(_read(root, relative, bindings)) for version, relative in _CONFIGS.items()}
    candidate = json.loads(_read(root, _CANDIDATE, bindings))
    for config in [*configs.values(), candidate]:
        _declared_files(root, config, bindings)
    _read(root, _CONFIGS[1], bindings, configs[2]["baseline_config_sha256"])
    _read(root, _CONFIGS[2], bindings, configs[3]["baseline_v2_config_sha256"])
    _read(root, _CONFIGS[3], bindings, configs[4]["baseline_v3_config_sha256"])
    _read(root, _CONFIGS[4], bindings, candidate["source_config_sha256"])
    _read(root, "artifacts/language_model/integration_config.json", bindings, configs[1]["integration_config_sha256"])
    _read(root, "src/champion_athletic_map/llm.py", bindings, configs[1]["adapter_sha256"])
    _read(root, "src/champion_athletic_map/reference_packets.py", bindings, configs[1]["reference_packets_sha256"])
    expected_sources = {**configs[2]["module_sha256"], **configs[3]["module_sha256"], **candidate["module_sha256"],
        _WORKFLOWS[1][0]: configs[2]["baseline_workflow_sha256"]}
    factories = {}
    for version, (relative, name) in _WORKFLOWS.items():
        _read(root, relative, bindings, expected_sources[relative])
        factories[version] = (constructors[version] if constructors is not None
            else getattr(_module(root, relative, bindings, expected_sources[relative]), name))
    planners = {version: factories[version](root) for version in range(1, 5)}
    outer, evaluated, drafting = planners[4], planners[4].planner, planners[4].planner.drafting
    nodes = [("v1", 1, planners[1]), ("v2", 2, planners[2]), ("v3", 3, planners[3]),
             ("v4", 4, outer), ("v4.evaluated", 4, evaluated), ("v4.drafting", 4, drafting)]
    original_instructions = planners[1].instructions
    if any(node.instructions != original_instructions for _, _, node in nodes):
        raise ValueError("The planners do not share their original task instructions.")
    base_policy = configs[2]["reference_policy"]
    if any(configs[v]["reference_policy"] != base_policy for v in (3, 4)):
        raise ValueError("The saved reference-supported planners have different reference policies.")
    effective_identity = {"runtime_version": RUNTIME_VERSION, "review_config_sha256": _sha(_packed(review_config)),
        "public_schema_sha256": review_config["public_schema_sha256"],
        "common_task_addendum_sha256": _sha(schedule.COMMON_TASK_ADDENDUM.encode("utf-8")),
        "schedule_checker_version": schedule.CHECKER_VERSION, "source_reference_policy": base_policy,
        "source_bindings": deepcopy(bindings)}
    policy = {**deepcopy(base_policy), "source_configuration_sha256": _sha(_packed(effective_identity))}
    clients, roles, seen_clients = [], [], set()
    for label, version, node in nodes:
        node.instructions = original_instructions + "\n\n" + schedule.COMMON_TASK_ADDENDUM
        if "reference_policy" in node.config:
            node.config = deepcopy(node.config)
            node.config["reference_policy"] = deepcopy(policy)
        if id(node.client) not in seen_clients:
            node.client.input_schema = deepcopy(public_schema)
            seen_clients.add(id(node.client))
            clients.append({"label": label + ".client", "planner_version": version, "target": node.client})
        if hasattr(node, "roles"):
            node.roles.reference_policy = deepcopy(policy)
            roles.append({"label": label + ".roles", "planner_version": version, "target": node.roles})
    if len(clients) != 4 or len(roles) != 3 or outer.client is not evaluated.client or drafting.client is not evaluated.client:
        raise ValueError("The saved planner object graph changed; its complete tracing inventory needs review.")
    checker = schedule.make_checker(root, evaluated.client, evaluated.policy, resources=evaluated.checker.resources)
    if checker.client.input_schema != public_schema:
        raise ValueError("The pilot checker and planner public schemas differ.")
    # Schema validation uses the same amended public client; it performs no transport.
    checker.client = evaluated.client
    evaluated.checker = checker
    tools_started = perf_counter()
    tools_relative = "src/champion_athletic_map/unified_references.py"
    tools_module = _module(root, tools_relative, bindings, configs[2]["module_sha256"][tools_relative])
    tools = tools_module.UnifiedReferenceTools(root, planners[1].config, planners[1].integration)
    tools_seconds = perf_counter() - tools_started
    for relative, expected in tools.source_bindings.items():
        _read(root, relative, bindings, expected)
    manifest = {**effective_identity, "verified_file_sha256": bindings,
        "effective_reference_policy": deepcopy(policy), "original_instructions_sha256": _sha(original_instructions.encode("utf-8")),
        "effective_instructions_sha256": _sha(planners[1].instructions.encode("utf-8")),
        "client_inventory": [{k: v for k, v in row.items() if k != "target"} for row in clients],
        "role_inventory": [{k: v for k, v in row.items() if k != "target"} for row in roles],
        "checker_policy": deepcopy(checker.pilot_schedule_policy), "legacy_files_modified": False,
        "constructor_test_doubles": constructors is not None or schedule_module is not None,
        "construction_seconds": perf_counter() - started, "reference_tools_construction_seconds": tools_seconds,
        "model_calls_during_construction": 0, "query_encoding_during_construction": 0}
    return SimpleNamespace(planners=planners, clients=clients, roles=roles, reference_policy=policy,
        checker=checker, tools=tools, client=planners[2].client, manifest=manifest)
