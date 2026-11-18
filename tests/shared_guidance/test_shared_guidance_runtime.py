"""Check the prospective guidance boundary with isolated planner object graphs."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/champion_athletic_map/shared_guidance_runtime.py"
spec = importlib.util.spec_from_file_location("test_shared_guidance_runtime", SOURCE)
API = importlib.util.module_from_spec(spec)
spec.loader.exec_module(API)
SCHEMA = {"type": "object", "fixture_only": True}


class OriginalRole:
    def __init__(self, root, client, shared, integration):
        self.root, self.client, self.shared, self.integration = root, client, shared, integration
        self.reference_policy = {"policy_version": "fixture-policy", "source_configuration_sha256": "base"}
        self.budget_checks = []

    def _budget_view(self, payload):
        self.budget_checks.append(deepcopy(payload))
        return payload

    def prepare_request(self, *args, **kwargs):
        table = {"columns": ["check_id", "required", "status", "reason"],
            "findings": [["row" + str(i), True, "unknown", "The complete source finding remains unresolved."] for i in range(25)],
            "policy": "fixture_complete_report"}
        self.original_view = {"athlete_input": {"request": "Original public facts"},
            "reference_data": {"qualifications": ["Full reference preserved"]},
            "specialist_notes": [{"role": "training", "statement": "Original contribution"}],
            "candidate": {"complete": ["All original fields", None, 20]},
            "check_results": table, "evaluator_assessment": {"assessment_complete": True, "issues": ["Kept"]}}
        return {"prepared": True}, {"messages": [{"role": "system", "content": "Original instructions"},
            {"role": "user", "content": json.dumps(self.original_view)}]}, {"unchanged": "value"}


class CandidateRole(OriginalRole):
    def prepare_request(self, *args, **kwargs):
        prepared, payload, config = super().prepare_request(*args, **kwargs)
        view = json.loads(payload["messages"][1]["content"])
        view["candidate"] = {"existing_candidate_encoding": True, "all_values": view["candidate"]}
        payload["messages"][1]["content"] = json.dumps(view)
        self.candidate_view = deepcopy(view)
        config["candidate_encoding"] = "already_retained"
        return prepared, payload, config


def graph(root, *, construction_seconds=1):
    policy = {"policy_version": "fixture-policy", "source_configuration_sha256": "base"}
    shared = SimpleNamespace(_decode=lambda value: json.loads(value),
        _sha=lambda data: hashlib.sha256(data).hexdigest())
    clients = [SimpleNamespace(input_schema=deepcopy(SCHEMA),
        encoder=SimpleNamespace(encode=lambda text, parse_special=False: list(text))) for _ in range(4)]
    def node(client, reference=True):
        return SimpleNamespace(instructions="Original common task and schedule coverage.", client=client,
            config={"fixture_only": True, **({"reference_policy": deepcopy(policy)} if reference else {})})
    one, two, three = node(clients[0], False), node(clients[1]), node(clients[2])
    outer, evaluated, drafting = node(clients[3]), node(clients[3]), node(clients[3])
    for value in (three, evaluated, drafting):
        value.roles = CandidateRole(root, value.client, shared, {"unchanged_model_limits": True})
    evaluated.drafting, outer.planner = drafting, evaluated
    evaluated._adapter, evaluated.integration = shared, {"unchanged_model_limits": True}
    evaluated.policy = {"required_unknowns_block": True, "maximum_revisions": 2}
    manifest = {"runtime_version": "fixture-base", "effective_reference_policy": deepcopy(policy),
        "effective_instructions_sha256": API.sha(one.instructions.encode("utf-8")),
        "verified_file_sha256": {}, "construction_seconds": construction_seconds,
        "reference_tools_construction_seconds": construction_seconds / 2,
        "constructor_test_doubles": False, "model_calls_during_construction": 0,
        "query_encoding_during_construction": 0}
    roles = [{"label": label + ".roles", "planner_version": version, "target": value.roles}
        for label, version, value in (("v3", 3, three), ("v4.evaluated", 4, evaluated), ("v4.drafting", 4, drafting))]
    return SimpleNamespace(planners={1: one, 2: two, 3: three, 4: outer}, reference_policy=deepcopy(policy),
        roles=roles, clients=[{"target": c} for c in clients], tools=object(), manifest=manifest)


@pytest.fixture
def project(tmp_path):
    target = tmp_path / "src/champion_athletic_map"
    target.mkdir(parents=True)
    for name in ("continuation_runtime.py", "review_encoding.py"):
        (target / name).write_bytes((ROOT / "src/champion_athletic_map" / name).read_bytes())
    (target / "shared_guidance_runtime.py").write_bytes(SOURCE.read_bytes())
    (target / "pilot_runtime.py").write_text("# The injected software fixture constructs no model runtime.\n")
    prompt = tmp_path / API.GUIDANCE_PATH
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Follow the requested session count and answer any supplied food question.\n")
    return tmp_path


def nodes(runtime):
    p = runtime.planners
    return [p[1], p[2], p[3], p[4], p[4].planner, p[4].planner.drafting]


def test_shared_guidance_reaches_all_six_nodes_without_reference_access_for_v1(project):
    base = graph(project)
    original_files = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    old_base_manifest = deepcopy(base.manifest)
    old_v1 = deepcopy(base.planners[1].config)
    old_clients = [n.client for n in nodes(base)]
    result = API.build_runtime(project, {"case_review": "unchanged"}, SCHEMA, runtime_builder=lambda *args: base)
    instructions = [n.instructions for n in nodes(result)]
    assert len(set(instructions)) == 1
    assert instructions[0].endswith((project / API.GUIDANCE_PATH).read_text())
    assert result.planners[1].config == old_v1
    assert "reference_policy" not in result.planners[1].config
    assert [n.client for n in nodes(result)] == old_clients
    assert result.manifest["base_runtime_manifest"] == old_base_manifest
    assert result.manifest["constructor_test_doubles"] is True
    assert result.manifest["legacy_files_modified"] is False
    assert result.manifest["acceptance_policy_changed"] is False
    assert result.manifest["output_and_context_limits_changed"] is False
    assert {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()} == original_files


def test_reference_policy_is_rebound_everywhere_and_budget_guard_remains(project):
    base = graph(project)
    acceptance = deepcopy(base.planners[4].planner.policy)
    result = API.build_runtime(project, {}, SCHEMA, runtime_builder=lambda *args: base)
    policy = result.reference_policy
    assert policy["source_configuration_sha256"] != "base"
    assert policy["source_configuration_sha256"] == result.manifest["shared_guidance_configuration_sha256"]
    for value in nodes(result):
        if "reference_policy" in value.config:
            assert value.config["reference_policy"] == policy
        if hasattr(value, "roles"):
            assert value.roles.reference_policy == policy
    assert result.planners[4].planner.policy == acceptance
    assert result.manifest["model_calls_during_construction"] == 0
    assert result.manifest["query_encoding_during_construction"] == 0
    assert result.manifest["effective_instructions_sha256"] == API.sha(result.planners[1].instructions.encode())


def test_v4_replacement_retains_candidate_encoding_and_complete_check_rows(project):
    base = graph(project)
    old = base.planners[4].planner.roles
    result = API.build_runtime(project, {}, SCHEMA, runtime_builder=lambda *args: base)
    current = result.planners[4].planner.roles
    assert current is not old and isinstance(current, CandidateRole)
    assert result.roles[1]["target"] is current
    assert all(row["target"] is not old for row in result.roles)
    prepared, payload, config = current.prepare_request()
    codec = API.load(project, "src/champion_athletic_map/review_encoding.py")
    view = json.loads(payload["messages"][1]["content"])
    assert prepared == {"prepared": True}
    assert config["candidate_encoding"] == "already_retained"
    assert config["lossless_review_roundtrip_verified"] is True
    assert codec.decode_view(view) == current.candidate_view
    assert view["candidate"]["existing_candidate_encoding"] is True
    assert current.budget_checks == [payload]
    assert result.manifest["candidate_encoding_retained"] is True
    for relative in ("src/champion_athletic_map/continuation_runtime.py", "src/champion_athletic_map/review_encoding.py"):
        assert result.manifest["verified_file_sha256"][relative] == API.sha((project / relative).read_bytes())


def test_configuration_identity_excludes_measured_construction_time(project):
    first = API.build_runtime(project, {}, SCHEMA, runtime_builder=lambda *args: graph(project, construction_seconds=1))
    second = API.build_runtime(project, {}, SCHEMA, runtime_builder=lambda *args: graph(project, construction_seconds=9))
    assert first.reference_policy == second.reference_policy
    assert first.manifest["shared_guidance_configuration_sha256"] == second.manifest["shared_guidance_configuration_sha256"]
    prompt = project / API.GUIDANCE_PATH
    prompt.write_text(prompt.read_text() + "Keep uncertainty explicit.\n")
    changed = API.build_runtime(project, {}, SCHEMA, runtime_builder=lambda *args: graph(project))
    assert changed.reference_policy != first.reference_policy


def test_default_constructor_path_is_not_labelled_as_test_double(project, monkeypatch):
    real_load = API.load
    monkeypatch.setattr(API, "load", lambda root, relative:
        SimpleNamespace(build_runtime=lambda *args: graph(project)) if relative.endswith("/pilot_runtime.py")
        else real_load(root, relative))
    result = API.build_runtime(project, {}, SCHEMA)
    assert result.manifest["constructor_test_doubles"] is False
    assert result.manifest["shared_guidance_configuration"]["injected_runtime_builder"] is False


@pytest.mark.parametrize("fault", ["instructions", "role_policy", "public_schema", "inventory", "base_manifest"])
def test_changed_shared_graph_blocks_the_prospective_runtime(project, fault):
    base = graph(project)
    if fault == "instructions":
        base.planners[4].planner.drafting.instructions += "Private alteration"
    elif fault == "role_policy":
        base.planners[3].roles.reference_policy = {"wrong": True}
    elif fault == "public_schema":
        base.planners[1].client.input_schema = {"changed": True}
    elif fault == "inventory":
        base.roles = base.roles[:2]
    else:
        base.manifest["effective_instructions_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        API.build_runtime(project, {}, SCHEMA, runtime_builder=lambda *args: base)


def test_empty_guidance_blocks_before_runtime_construction(project):
    (project / API.GUIDANCE_PATH).write_text(" \n")
    def forbidden(*args):
        raise AssertionError("The base runtime must not be constructed.")
    with pytest.raises(ValueError, match="empty"):
        API.build_runtime(project, {}, SCHEMA, runtime_builder=forbidden)


pytestmark = pytest.mark.requirement("31:shared-guidance-runtime")
