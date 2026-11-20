"""Check composition with fixtures, then exercise the real saved constructor graph."""

import builtins
from copy import deepcopy
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.request

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNTIME = load(ROOT / "src/champion_athletic_map/pilot_runtime.py", "pilot_runtime_test")
SCHEDULE = load(ROOT / "src/champion_athletic_map/pilot_schedule.py", "pilot_runtime_schedule")
CONFIGS = {n: json.loads((ROOT / path).read_bytes()) for n, path in RUNTIME._CONFIGS.items()}
CANDIDATE = json.loads((ROOT / RUNTIME._CANDIDATE).read_bytes())
INTEGRATION = json.loads((ROOT / "artifacts/language_model/integration_config.json").read_bytes())
BASE = json.loads((ROOT / INTEGRATION["contracts_directory"] / "public_profile_record_schema.json").read_bytes())
SCHEMA = SCHEDULE.build_input_schema(BASE)
REVIEW = {"public_schema_sha256": RUNTIME._sha(RUNTIME._packed(SCHEMA)),
    "common_task_addendum": SCHEDULE.COMMON_TASK_ADDENDUM,
    "component_sha256": {"src/champion_athletic_map/pilot_schedule.py":
        hashlib.sha256((ROOT / "src/champion_athletic_map/pilot_schedule.py").read_bytes()).hexdigest()}}
TASK = (ROOT / CONFIGS[1]["shared_instructions_path"]).read_text()
POINTER = json.loads((ROOT / "artifacts/language_model/active_resource_release.json").read_bytes())
RELEASE = ROOT / POINTER["release_directory"]
RULES = json.loads((RELEASE / "adopted_rules.json").read_bytes())["records"]
RESOURCES = {"rules": RULES, "release_id": "authored-runtime-test-resources", "rule_file_sha256": "1"*64,
    "drills": {}, "aliases": {}, "held_ids": set()}


def fail_call(*args, **kwargs):
    raise AssertionError("Construction attempted transport or query encoding.")


@pytest.fixture(autouse=True)
def explicit_reference_file_fixture(monkeypatch):
    # The supplied project archive omits data/unified/v1; production still uses
    # the original constructor and checks every dataset file on Sam's computer.
    original = RUNTIME._module
    class ReadOnlyToolsFixture:
        def __init__(self, root, config, integration):
            self.core = SimpleNamespace(_query_runtime=None)
            self.source_bindings = {}
        load_query_runtime = fail_call
    def module(root, relative, bindings, expected=None):
        if relative == "src/champion_athletic_map/unified_references.py":
            RUNTIME._read(root, relative, bindings, expected)
            return SimpleNamespace(UnifiedReferenceTools=ReadOnlyToolsFixture)
        return original(root, relative, bindings, expected)
    monkeypatch.setattr(RUNTIME, "_module", module)


def stub_factories():
    created = []

    def node(n, *, client=None, roles=False):
        client = client or SimpleNamespace(root=ROOT, input_schema=deepcopy(BASE), _http=fail_call)
        value = SimpleNamespace(root=ROOT, client=client, config=deepcopy(CONFIGS[n]),
            instructions=TASK, integration=deepcopy(INTEGRATION))
        if roles:
            value.roles = SimpleNamespace(client=client, reference_policy=deepcopy(CONFIGS[2]["reference_policy"]),
                generate=fail_call, _http=fail_call)
        created.append(value)
        return value

    def v4(root):
        draft = node(3, roles=True)
        inner = node(4, client=draft.client, roles=True)
        inner.drafting, inner.checker = draft, SimpleNamespace(resources=deepcopy(RESOURCES))
        inner.policy = json.loads((ROOT / CONFIGS[4]["acceptance_policy_path"]).read_bytes())
        outer = SimpleNamespace(root=ROOT, client=inner.client, planner=inner, policy=inner.policy,
            config=deepcopy(CANDIDATE), instructions=TASK, integration=deepcopy(INTEGRATION))
        created.append(outer)
        return outer

    return {1: lambda root: node(1), 2: lambda root: node(2),
            3: lambda root: node(3, roles=True), 4: v4}, created


def assert_effective_graph(runtime):
    assert set(runtime.planners) == {1, 2, 3, 4}
    assert len(runtime.clients) == 4 and len({id(row["target"]) for row in runtime.clients}) == 4
    assert len(runtime.roles) == 3 and len({id(row["target"]) for row in runtime.roles}) == 3
    v4 = runtime.planners[4]
    nodes = [runtime.planners[n] for n in (1, 2, 3)] + [v4, v4.planner, v4.planner.drafting]
    assert all(value.instructions == TASK + "\n\n" + SCHEDULE.COMMON_TASK_ADDENDUM for value in nodes)
    assert all(row["target"].input_schema == SCHEMA for row in runtime.clients)
    assert all(row["target"].reference_policy == runtime.reference_policy for row in runtime.roles)
    assert all(value.config["reference_policy"] == runtime.reference_policy
        for value in [runtime.planners[2], runtime.planners[3], v4.planner, v4.planner.drafting])
    assert v4.planner.checker is runtime.checker
    assert runtime.checker.client is v4.client is v4.planner.drafting.client
    assert runtime.checker.pilot_schedule_policy["version"] == SCHEDULE.CHECKER_VERSION
    assert runtime.client is runtime.planners[2].client
    assert runtime.tools.core._query_runtime is None
    assert runtime.reference_policy["policy_version"] == CONFIGS[2]["reference_policy"]["policy_version"]
    assert runtime.reference_policy["source_configuration_sha256"] != CONFIGS[2]["reference_policy"]["source_configuration_sha256"]
    assert len(runtime.reference_policy["source_configuration_sha256"]) == 64


def test_stub_composition_preserves_original_inputs_and_exposes_complete_inventory(monkeypatch):
    factories, created = stub_factories()
    originals = {path: (ROOT / path).read_bytes() for path in [*RUNTIME._CONFIGS.values(), RUNTIME._CANDIDATE,
        *(row[0] for row in RUNTIME._WORKFLOWS.values())]}
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fail_call)
    before_review, before_schema = deepcopy(REVIEW), deepcopy(SCHEMA)
    runtime = RUNTIME.build_runtime(ROOT, REVIEW, SCHEMA, constructors=factories)
    assert_effective_graph(runtime)
    assert REVIEW == before_review and SCHEMA == before_schema
    assert all((ROOT / path).read_bytes() == data for path, data in originals.items())
    assert runtime.manifest["legacy_files_modified"] is False
    assert runtime.manifest["model_calls_during_construction"] == runtime.manifest["query_encoding_during_construction"] == 0
    assert runtime.manifest["constructor_test_doubles"] is True
    bindings = runtime.manifest["verified_file_sha256"]
    assert all(path in bindings for path in originals)
    for path in [CONFIGS[4]["evaluator_schema_path"], CONFIGS[4]["acceptance_policy_path"], CANDIDATE["evaluator_prompt"]["path"],
        "src/champion_athletic_map/context_encoding.py"]:
        assert bindings[path] == hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


@pytest.mark.parametrize("change", ["schema", "addendum", "checker_hash"])
def test_changed_review_binding_stops_before_construction(change):
    factories, created = stub_factories()
    review, schema = deepcopy(REVIEW), deepcopy(SCHEMA)
    if change == "schema":
        schema["title"] += " changed"
    elif change == "addendum":
        review["common_task_addendum"] += " changed"
    else:
        review["component_sha256"]["src/champion_athletic_map/pilot_schedule.py"] = "0"*64
    with pytest.raises(ValueError):
        RUNTIME.build_runtime(ROOT, review, schema, constructors=factories)
    assert created == []


def test_changed_constructor_graph_is_not_silently_partially_patched():
    factories, _ = stub_factories()
    original = factories[4]
    def bad_v4(root):
        value = original(root)
        value.planner.drafting.client = SimpleNamespace(root=ROOT, input_schema=deepcopy(BASE))
        return value
    factories[4] = bad_v4
    with pytest.raises(ValueError, match="object graph changed"):
        RUNTIME.build_runtime(ROOT, REVIEW, SCHEMA, constructors=factories)


def test_runtime_policy_identity_is_stable_and_changes_with_review():
    a, _ = stub_factories()
    b, _ = stub_factories()
    first = RUNTIME.build_runtime(ROOT, REVIEW, SCHEMA, constructors=a)
    second = RUNTIME.build_runtime(ROOT, REVIEW, SCHEMA, constructors=b)
    assert first.reference_policy == second.reference_policy
    changed = {**deepcopy(REVIEW), "source_review_sha256": "f"*64}
    third = RUNTIME.build_runtime(ROOT, changed, SCHEMA, constructors=stub_factories()[0])
    assert first.reference_policy != third.reference_policy


def test_actual_saved_planner_constructors_with_explicit_native_encoder_fixture(monkeypatch):
    # The Linux test runner lacks the two pinned tokenizer packages. This stand-in
    # exercises the unchanged planner/client constructor chain without tokenizing.
    original_exec, original_version = builtins.exec, importlib.metadata.version
    native_sources = []
    class EncoderFixture:
        def __init__(self, info, model_json):
            self.info = info
        encode = fail_call
    def fixture_exec(source, global_vars=None, local_vars=None, **kwargs):
        if Path(str(getattr(source, "co_filename", ""))).name == "native_tokenizer.py":
            native_sources.append(source.co_filename)
            global_vars.update(NativeTokenizerCandidate=EncoderFixture,
                inspect_native_tables=lambda info: {"special": {text: i for i, (text, kind) in enumerate(
                    zip(info["tokenizer.ggml.tokens"], info["tokenizer.ggml.token_type"])) if kind == 3}})
            return None
        return original_exec(source, global_vars, local_vars, **kwargs)
    monkeypatch.setattr(builtins, "exec", fixture_exec)
    monkeypatch.setattr(importlib.metadata, "version", lambda name: {"regex": "2026.11.9", "tokenizers": "0.22.1"}.get(name) or original_version(name))
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fail_call)
    source_before = {path: (ROOT / path).read_bytes() for path in [*RUNTIME._CONFIGS.values(), RUNTIME._CANDIDATE,
        *(row[0] for row in RUNTIME._WORKFLOWS.values()), "src/champion_athletic_map/llm.py"]}
    runtime = RUNTIME.build_runtime(ROOT, REVIEW, SCHEMA)
    assert len(native_sources) == 4
    assert_effective_graph(runtime)
    v4 = runtime.planners[4]
    assert v4.planner.prompts["evaluator"] == (ROOT / CANDIDATE["evaluator_prompt"]["path"]).read_text()
    assert type(v4.planner.roles).__name__ == "CandidateFocusedRoleAdapter"
    assert runtime.planners[3].note_schema == v4.planner.drafting.note_schema
    assert v4.planner.config["maximum_revisions"] == 2
    assert runtime.planners[1].integration == INTEGRATION
    assert all((ROOT / path).read_bytes() == data for path, data in source_before.items())

pytestmark = pytest.mark.requirement("31:bounded-operational-probe")
