"""We exercise the four workflows with authored responses, never a live model."""

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from threading import Lock
from types import MethodType, SimpleNamespace

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


def load(relative):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location("step30_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shared = load("src/champion_athletic_map/llm.py")
baseline = load("src/champion_athletic_map/planners/llm_only.py")
rag = load("src/champion_athletic_map/planners/rag.py")
specialists = load("src/champion_athletic_map/planners/specialists.py")
evaluated = load("src/champion_athletic_map/planners/evaluated_specialists.py")
role_transport = load("src/champion_athletic_map/role_adapter.py")
candidate_preparation = load("src/champion_athletic_map/planners/candidate_focused.py")
public = load("artifacts/language_model/shared_contracts/contracts_3293242853ce2cf7/public_input.py")
packets = load("src/champion_athletic_map/reference_packets.py")


def config(name):
    return json.loads((ROOT / "artifacts/planners" / name).read_bytes())


def profile(food=False):
    record = {"profile_id": "authored-workflow-example", "schema_version": "athlete-profile-input-1", "input": {
        "age": 16, "school_grade": 10,
        "athlete_request": "Organize my existing basketball commitments for this week.",
        "planning_window": {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"},
        "existing_commitments": [], "availability": []}}
    if food:
        record["input"]["food_question"] = "What is the recorded protein in 100 g of a named food?"
    return record


def answer(number=0):
    return {"response_type": "clarification", "explanation": "Authored candidate " + str(number),
            "questions": ["What would you like to practise?"]}


def returned(body=None, *, valid=True, complete=True, raw=None, status="returned"):
    body = answer() if body is None else body
    return {"status": status, "format_valid": valid, "completion_valid": complete,
            "cached": False, "response_type": body.get("response_type") if isinstance(body, dict) else None,
            "response": {"model_output": {"parsed_object": deepcopy(body) if valid else None,
                         "raw_text": raw if raw is not None else json.dumps(body)}},
            "transport_attempts": {"metadata": 0, "render": 1, "generation": 1}}


def note(role, limited=False):
    return {"contribution_status": "limited_information" if limited else "provided",
            "recommendations": ["Authored " + role + " suggestion."] if not limited else [],
            "evidence_refs": [], "qualifications": ["No external evidence is implied by this fixture."],
            "unresolved_issues": [], "questions": [], "rationale": "A controlled contribution."}


def client():
    instance = shared.OllamaClient.__new__(shared.OllamaClient)
    instance.root = ROOT
    instance.public = public
    instance.input_schema = json.loads((ROOT / "artifacts/language_model/shared_contracts/contracts_3293242853ce2cf7/public_profile_record_schema.json").read_bytes())
    instance.response_schema = {"type": "object"}
    instance.output_schema = {"type": "object"}
    instance.controls = {}
    instance.preflight = SimpleNamespace(validate_request=lambda payload, controls: None)
    instance._budget_view = lambda payload: payload
    instance.wire_calls = []

    def http(endpoint, payload=None, timeout=8, raw_path=None):
        instance.wire_calls.append((endpoint, deepcopy(payload)))
        return {"fixture": True}

    instance._http = http
    return instance


def packet(record, instance):
    prepared = public.prepare_public_input(record, instance.input_schema)
    policy = config("version2_config.json")["reference_policy"]
    body = {"schema_version": "shared-reference-packet-1", "public_input_sha256": prepared["audit"]["public_input_sha256"],
        "payload": {"references": [{"reference_unit_id": "authored-ref", "complete_required_delivery_text": "A complete fictional reference unit."}]},
        "preparation": {"builder_policy": policy["policy_version"], "source_configuration_sha256": policy["source_configuration_sha256"]}}
    digest = sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {**body, "packet_id": "reference-packet:" + digest}


def single_planner(version, mutate=None, repeat=False, forbidden_endpoint=False):
    cls = baseline.LLMOnlyPlanner if version == 1 else rag.RAGPlanner
    planner = cls.__new__(cls)
    planner._lock = Lock()
    planner.client = client()
    planner.instructions = "Use the supplied athlete facts."
    planner.integration = {"model": shared.MODEL, "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 2048}}
    planner._adapter = shared
    if version == 2:
        planner.config = config("version2_config.json")

    def generate(instance, record, instructions, call_id, *, planner_version, reference_packet):
        _, payload, _ = instance.prepare_request(record, instructions, planner_version=planner_version, reference_packet=reference_packet)
        if mutate:
            mutate(payload)
        instance._http("/api/chat", dict(payload, _debug_render_only=True))
        if forbidden_endpoint:
            instance._http("/api/embed", {"input": "unexpected search"})
        instance._http("/api/chat", payload)
        if repeat:
            instance._http("/api/chat", payload)
        return returned()

    planner.client.generate = MethodType(generate, planner.client)
    return planner


class ScriptedRoles:
    def __init__(self, actions=None):
        self.actions = {key: list(values) for key, values in (actions or {}).items()}
        self.calls = []
        self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}

    def generate(self, record, reference_packet, instructions, call_id, **kwargs):
        self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}
        self.calls.append({"public_record": deepcopy(record), "packet": deepcopy(reference_packet),
                           "instructions": instructions, "call_id": call_id, **deepcopy(kwargs)})
        stage = kwargs["stage"]
        action = self.actions.get(stage, []).pop(0) if self.actions.get(stage) else None
        if isinstance(action, BaseException):
            raise action
        if action is None:
            action = returned(answer()) if stage == "coordinator" else returned(note(stage))
        self.last_transport_attempts = deepcopy(action.get("transport_attempts", {}))
        return deepcopy(action)


def specialist_planner(actions=None):
    planner = specialists.SpecialistPlanner.__new__(specialists.SpecialistPlanner)
    planner._lock = Lock()
    planner.config = config("version3_config.json")
    planner.instructions = "The original public facts remain authoritative."
    planner.prompts = {role: "Authored role: " + role for role in ("training", "recovery", "food", "coordinator")}
    planner.note_schema = json.loads((ROOT / "artifacts/planners/version3_note_schema.json").read_bytes())
    planner.client = client()
    planner.client.encoder = SimpleNamespace(encode=lambda text, parse_special=False: list(text))
    planner.preparations = []
    planner._preparation = SimpleNamespace(validate_packet=lambda *args: planner.preparations.append(deepcopy(args[:3])))
    planner.roles = ScriptedRoles(actions)
    return planner


def report(policy, *, required_status="met", advisory_status="met", missing=False, candidate_id=None):
    required = set(policy["required_check_ids"])
    rows = [{"check_id": identifier, "required": identifier in required,
             "status": required_status if identifier in required else advisory_status,
             "reason": "Hand-authored check outcome for workflow control."}
            for identifier in policy["expected_check_ids"]]
    if missing:
        rows.pop()
    return {"execution_status": "completed", "candidate_id": candidate_id, "checks": rows}


class ScriptedChecker:
    def __init__(self, policy, outcomes):
        self.policy, self.outcomes, self.calls = policy, list(outcomes), []

    def check(self, record, candidate, reference_packet, *, candidate_id):
        self.calls.append({"candidate_id": candidate_id, "candidate": deepcopy(candidate)})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return report(self.policy, candidate_id=candidate_id, **outcome)


def evaluated_planner(checks, *, assessments=None, revisions=None, draft_actions=None):
    planner = evaluated.EvaluatedSpecialistPlanner.__new__(evaluated.EvaluatedSpecialistPlanner)
    planner._lock = Lock()
    planner.config = {"maximum_revisions": 2}
    planner.policy = config("version4_acceptance_policy.json")
    planner.evaluator_schema = {"type": "object"}
    planner.instructions = "Keep public facts and complete current findings."
    planner.prompts = {"evaluator": "Assess the candidate.", "revision": "Revise the current candidate."}
    planner.drafting = specialist_planner(draft_actions)
    planner.checker = ScriptedChecker(planner.policy, checks)
    evaluations = assessments if assessments is not None else [returned({"assessment_complete": True, "issues": []}) for _ in checks]
    revision_results = revisions if revisions is not None else [returned(answer(i)) for i in (1, 2)]
    planner.roles = ScriptedRoles({"evaluator": evaluations, "revision": revision_results})
    return planner


@pytest.mark.requirement("30.7:single-request-access")
@pytest.mark.parametrize("version", [1, 2])
def test_single_request_uses_actual_public_message_builder_and_restores_transport(version):
    planner = single_planner(version)
    record = profile()
    references = packet(record, planner.client)
    original_http = planner.client._http
    result = planner.generate(record, "authored_v1") if version == 1 else planner.generate(record, references, "authored_v2")
    assert planner.client._http is original_http
    assert result["transport_attempts"] == {"metadata": 0, "render": 1, "generation": 1}
    payload = planner.client.wire_calls[-1][1]
    view = json.loads(payload["messages"][1]["content"])
    assert view["athlete_input"] == record["input"]
    assert "profile_id" not in view and "schema_version" not in view
    assert set(view) == ({"athlete_input"} if version == 1 else {"athlete_input", "reference_data"})
    if version == 2:
        assert view["reference_data"] == references["payload"]
    assert [message["role"] for message in payload["messages"]] == ["system", "user"]
    assert payload["options"] == {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 2048}
    assert payload["truncate"] is False and payload["shift"] is False


@pytest.mark.requirement("30.7:duplicate-generation-denied")
@pytest.mark.parametrize("version", [1, 2])
def test_single_request_planners_reject_an_undeclared_second_generation(version):
    planner = single_planner(version, repeat=True)
    record = profile()
    original_http = planner.client._http
    with pytest.raises(RuntimeError, match="another generation"):
        if version == 1:
            planner.generate(record, "authored_repeat")
        else:
            planner.generate(record, packet(record, planner.client), "authored_repeat")
    assert planner.client._http is original_http
    assert len([p for _, p in planner.client.wire_calls if not p.get("_debug_render_only")]) == 1


@pytest.mark.requirement("30.7:public-input-settings-access")
@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("change", ["reference_injection", "option_change", "endpoint"])
def test_single_request_planners_reject_changed_inputs_settings_or_search_access(version, change):
    def mutate(payload):
        if change == "reference_injection":
            payload["messages"][1]["content"] = json.dumps({"athlete_input": profile()["input"], "leaked_expected_answer": "private sentinel"})
        elif change == "option_change":
            payload["options"]["num_predict"] = 9999
    planner = single_planner(version, mutate=mutate, forbidden_endpoint=change == "endpoint")
    record = profile()
    with pytest.raises(ValueError):
        if version == 1:
            planner.generate(record, "authored_denied")
        else:
            planner.generate(record, packet(record, planner.client), "authored_denied")
    assert not any(endpoint == "/api/embed" for endpoint, _ in planner.client.wire_calls)


@pytest.mark.requirement("30.7:specialist-isolation-and-public-food-route")
@pytest.mark.parametrize("food,roles", [(False, ["training", "recovery", "coordinator"]), (True, ["training", "recovery", "food", "coordinator"])])
def test_specialist_role_order_peer_isolation_and_coordinator_handoff(food, roles):
    planner = specialist_planner()
    record = profile(food)
    references = packet(record, planner.client)
    result = planner.generate(record, references, "authored_specialists")
    calls = planner.roles.calls
    assert [call["stage"] for call in calls] == roles
    assert result["logical_stage_calls"] == len(roles)
    assert result["food_role_active"] is food
    assert len(planner.preparations) == 1
    assert result["reference_calls_during_roles"] == result["evaluator_calls"] == result["classifier_calls"] == 0
    assert all(call["public_record"] == record and call["packet"] == references for call in calls)
    assert all(call["specialist_notes"] is None and call["output_tokens"] == 512 for call in calls[:-1])
    assert calls[-1]["specialist_notes"] == [{"role": role, "contribution": note(role)} for role in roles[:-1]]
    assert calls[-1]["output_tokens"] == 2048


@pytest.mark.requirement("30.8:limited-note-is-not-failure")
def test_valid_limited_information_note_reaches_coordinator():
    planner = specialist_planner({"recovery": [returned(note("recovery", limited=True))]})
    record = profile()
    result = planner.generate(record, packet(record, planner.client), "authored_limited")
    assert result["completion_valid"] is True
    assert result["logical_stage_calls"] == 3
    assert result["specialist_notes"][1]["contribution"]["contribution_status"] == "limited_information"


@pytest.mark.requirement("30.7:call-budgets-and-first-accepted-candidate")
@pytest.mark.parametrize("food", [False, True])
@pytest.mark.parametrize("accepted_after", [0, 1, 2, None])
def test_v4_counts_and_selects_first_accepted_or_last_assessed_candidate(food, accepted_after):
    revisions = 2 if accepted_after is None else accepted_after
    checks = [{"required_status": "violated"}] * revisions
    checks += [{"required_status": "violated" if accepted_after is None else "met"}]
    planner = evaluated_planner(checks)
    record = profile(food)
    references = packet(record, planner.drafting.client)
    result = planner.generate(record, references, "authored_v4")
    expected = 4 + int(food) + 2 * revisions
    assert result["logical_stage_calls"] == expected
    assert result["transport_attempts"]["generation"] == expected
    assert result["selected_candidate_id"] == "candidate_" + str(revisions)
    assert result["revisions_used"] == revisions
    assert result["internally_accepted"] is (accepted_after is not None)
    assert result["terminal_state"] == ("internally_accepted" if accepted_after is not None else "revision_limit_reached")
    assert [row["candidate_id"] for row in planner.checker.calls] == ["candidate_" + str(i) for i in range(revisions + 1)]
    assert [call["stage"] for call in planner.roles.calls] == [stage for i in range(revisions) for stage in ("evaluator", "revision")] + ["evaluator"]
    assert all(call["packet"] == references for call in planner.roles.calls)
    assert result["reference_calls"] == result["classifier_calls"] == 0
    assert result["operational_generation_ready"] is False
    assert all(call["output_tokens"] == (768 if call["stage"] == "evaluator" else 2048) for call in planner.roles.calls)


@pytest.mark.requirement("30.8:required-unknown-and-advisory-unknown")
@pytest.mark.parametrize("required_status,advisory_status,accepted", [("met", "unknown", True), ("unknown", "met", False), ("violated", "met", False)])
def test_required_findings_cannot_be_waived_by_a_positive_evaluator(required_status, advisory_status, accepted):
    policy = config("version4_acceptance_policy.json")
    assessment = {"assessment_complete": True, "issues": []}
    outcome = evaluated.assess_acceptance(report(policy, required_status=required_status, advisory_status=advisory_status), assessment, policy)
    assert outcome["accepted"] is accepted
    assert bool(outcome["blocking_check_ids"]) is (not accepted)
    assert bool(outcome["disagreements"]) is (not accepted)


@pytest.mark.requirement("30.7:specialist-actual-message-boundaries")
def test_actual_role_request_builder_rejects_peer_notes_and_missing_coordinator_contributions():
    instance = role_transport.RoleAdapter.__new__(role_transport.RoleAdapter)
    instance.client, instance.shared, instance.packets = client(), shared, packets
    instance.integration = {"options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 2048}}
    instance.reference_policy = config("version2_config.json")["reference_policy"]
    instance.client.response = SimpleNamespace(Draft202012Validator=Draft202012Validator)
    record = profile()
    references = packet(record, instance.client)
    with pytest.raises(ValueError, match="Specialists"):
        instance.prepare_request(record, references, "Draft the training contribution.", stage="training", output_schema={"type": "object"}, specialist_notes=[{"role": "recovery", "contribution": note("recovery")}])
    with pytest.raises(ValueError, match="every required"):
        instance.prepare_request(record, references, "Coordinate the contributions.", stage="coordinator", output_tokens=2048, specialist_notes=[{"role": "training", "contribution": note("training")}])
    notes = [{"role": r, "contribution": note(r)} for r in ("training", "recovery")]
    _, payload, settings = instance.prepare_request(record, references, "Coordinate the contributions.", stage="coordinator", output_tokens=2048, specialist_notes=notes)
    view = json.loads(payload["messages"][1]["content"])
    assert view == {"athlete_input": record["input"], "reference_data": references["payload"], "specialist_notes": notes}
    assert settings["output_limit"] == 2048


@pytest.mark.requirement("30.8:candidate-pilot-keeps-original-results")
def test_candidate_focused_wrapper_annotates_a_fresh_job_without_regrading():
    wrapper = candidate_preparation.CandidateFocusedEvaluatedPlanner.__new__(candidate_preparation.CandidateFocusedEvaluatedPlanner)
    wrapper._lock = Lock()
    wrapper.config = {"readiness": "awaiting_pilot"}
    wrapper.config_sha256 = "authored-candidate-config"
    original = {"terminal_state": "execution_error", "response": None}
    seen = []
    def generate(record, references, call_id):
        seen.append((deepcopy(record), deepcopy(references), call_id))
        return deepcopy(original)
    wrapper.planner = SimpleNamespace(generate=generate, last_transport_attempts={"metadata": 0, "render": 0, "generation": 4})
    result = wrapper.generate(profile(), {"packet_id": "authored-packet"}, "fresh_pilot_job")
    assert seen[0][2] == "fresh_pilot_job"
    assert result["terminal_state"] == "execution_error" and result["response"] is None
    assert result["candidate_focused_preparation"]["earlier_results_regraded"] is False
    assert result["candidate_focused_preparation"]["operational_generation_ready"] is False
    assert original == {"terminal_state": "execution_error", "response": None}
