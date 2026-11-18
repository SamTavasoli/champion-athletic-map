"""We keep failures visible instead of returning an earlier draft as a success."""

from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


_path = Path(__file__).with_name("test_planner_workflows.py")
_spec = importlib.util.spec_from_file_location("step30_workflow_fixtures", _path)
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)


def run(planner, food=False):
    record = harness.profile(food)
    references = harness.packet(record, planner.drafting.client)
    return planner.generate(record, references, "authored_failure")


@pytest.mark.requirement("30.8:malformed-coordinator-enters-declared-revision")
def test_malformed_completed_coordinator_gets_a_fresh_assessment_and_revision():
    raw = '{"response_type":"plan",unfinished'
    planner = harness.evaluated_planner(
        [{"required_status": "violated"}, {"required_status": "met"}],
        draft_actions={"coordinator": [harness.returned(valid=False, raw=raw)]})
    result = run(planner)
    assert result["terminal_state"] == "internally_accepted"
    assert result["selected_candidate_id"] == "candidate_1"
    first = planner.roles.calls[0]["specialist_notes"]["candidate"]
    assert first == {"candidate_id": "candidate_0", "raw_text": raw, "format_valid": False}
    assert result["draft_result"]["response"]["model_output"]["raw_text"] == raw
    assert [item["candidate_id"] for item in planner.checker.calls] == ["candidate_0", "candidate_1"]
    assert result["logical_stage_calls"] == 6


@pytest.mark.requirement("30.8:failed-mandatory-contribution-stops")
@pytest.mark.parametrize("failed_role,count", [("training", 1), ("recovery", 2), ("food", 3)])
def test_invalid_mandatory_note_prevents_coordination_and_evaluation(failed_role, count):
    broken = harness.returned(valid=False, raw="not a JSON contribution")
    planner = harness.evaluated_planner([], draft_actions={failed_role: [broken]})
    result = run(planner, food=True)
    assert result["terminal_state"] == "execution_error"
    assert result["failed_stage"] == failed_role
    assert result["response"] is None
    assert result["selected_candidate_id"] is None
    assert result["logical_stage_calls"] == count
    assert planner.roles.calls == [] and planner.checker.calls == []
    assert all(call["stage"] != "coordinator" for call in planner.drafting.roles.calls)


@pytest.mark.requirement("30.8:incomplete-evaluation-stops")
@pytest.mark.parametrize("assessment", [
    harness.returned({"assessment_complete": False, "issues": []}),
    harness.returned({"assessment_complete": True, "issues": []}, valid=False, raw="{}"),
    harness.returned({"assessment_complete": True, "issues": []}, complete=False),
    harness.returned({"assessment_complete": True, "issues": [{"category": "undeclared_category"}]}),
])
def test_invalid_or_incomplete_evaluator_does_not_trigger_an_undeclared_retry(assessment):
    planner = harness.evaluated_planner([{}], assessments=[assessment])
    result = run(planner)
    assert result["failed_stage"] == "evaluator"
    assert result["terminal_state"] == "execution_error"
    assert result["response"] is None and result["selected_candidate_id"] is None
    assert result["revisions_used"] == 0
    assert [call["stage"] for call in planner.roles.calls] == ["evaluator"]
    assert result["logical_stage_calls"] == 4


@pytest.mark.requirement("30.8:checker-coverage-is-mandatory")
@pytest.mark.parametrize("failure", ["exception", "missing_row", "empty_rows", "wrong_required_flag"])
def test_checker_failure_or_incomplete_coverage_stops_before_evaluation(failure):
    planner = harness.evaluated_planner([{}])
    if failure == "exception":
        planner.checker = harness.ScriptedChecker(planner.policy, [RuntimeError("Authored checker failure")])
    elif failure == "missing_row":
        planner.checker = harness.ScriptedChecker(planner.policy, [{"missing": True}])
    else:
        result = harness.report(planner.policy)
        if failure == "empty_rows":
            result["checks"] = []
        else:
            result["checks"][0]["required"] = not result["checks"][0]["required"]
        planner.checker = SimpleNamespace(check=lambda *args, **kwargs: deepcopy(result))
    result = run(planner)
    assert result["terminal_state"] == "execution_error" and result["failed_stage"] == "checker"
    assert result["response"] is None and result["internally_accepted"] is False
    assert planner.roles.calls == []
    assert result["logical_stage_calls"] == 3


@pytest.mark.requirement("30.8:revision-receives-new-findings")
def test_revision_that_introduces_a_new_error_is_not_accepted_on_the_old_assessment():
    revisions = [harness.returned(valid=False, raw="broken revision"), harness.returned(harness.answer(2))]
    planner = harness.evaluated_planner(
        [{"required_status": "violated"}, {"required_status": "violated"}, {"required_status": "unknown"}],
        revisions=revisions)
    result = run(planner)
    assert result["terminal_state"] == "revision_limit_reached"
    assert result["selected_candidate_id"] == "candidate_2"
    assert result["internally_accepted"] is False
    assert result["response"]["model_output"]["parsed_object"]["explanation"] == "Authored candidate 2"
    assert [item["candidate_id"] for item in planner.checker.calls] == ["candidate_0", "candidate_1", "candidate_2"]
    evaluated_candidates = [call["specialist_notes"]["candidate"] for call in planner.roles.calls if call["stage"] == "evaluator"]
    assert evaluated_candidates[1] == {"candidate_id": "candidate_1", "format_valid": False, "raw_text": "broken revision"}
    assert len(evaluated_candidates) == 3 and result["revisions_used"] == 2


@pytest.mark.requirement("30.8:context-overflow-does-not-return-old-draft")
@pytest.mark.parametrize("stage,expected_logical,expected_transport", [("evaluator", 4, 3), ("revision", 5, 4)])
def test_context_failure_preserves_diagnostics_without_returning_the_old_candidate(stage, expected_logical, expected_transport):
    error = ValueError("The complete role request exceeds its reserved context budget.")
    kwargs = {"assessments": [error]} if stage == "evaluator" else {"revisions": [error]}
    planner = harness.evaluated_planner([{"required_status": "violated"}], **kwargs)
    result = run(planner)
    assert result["terminal_state"] == "execution_error" and result["status"] == "blocked"
    assert result["failed_stage"] == stage and "reserved context budget" in result["error"]
    assert result["response"] is None and result["selected_candidate_id"] is None
    assert result["draft_result"]["completion_valid"] is True
    assert result["logical_stage_calls"] == expected_logical
    assert result["transport_attempts"]["generation"] == expected_transport


@pytest.mark.requirement("30.8:uncertain-completion-is-not-resubmitted")
@pytest.mark.parametrize("stage", ["evaluator", "revision"])
def test_uncertain_stage_completion_remains_unresolved_without_replay(stage):
    uncertain = harness.returned(complete=False, status="unresolved")
    kwargs = {"assessments": [uncertain]} if stage == "evaluator" else {"revisions": [uncertain]}
    planner = harness.evaluated_planner([{"required_status": "violated"}], **kwargs)
    result = run(planner)
    assert result["status"] == "unresolved" and result["terminal_state"] == "execution_error"
    assert result["failed_stage"] == stage
    assert result["response"] is None and result["selected_candidate_id"] is None
    assert [c["stage"] for c in planner.roles.calls].count(stage) == 1
    assert result["revisions_used"] <= 1


@pytest.mark.requirement("30.8:real-role-transport-request-guard")
@pytest.mark.parametrize("case", ["mutated_payload", "second_generation", "second_render", "undeclared_endpoint"])
def test_role_transport_rejects_mutation_duplicate_requests_and_other_endpoints(case):
    instance = harness.role_transport.RoleAdapter.__new__(harness.role_transport.RoleAdapter)
    instance.shared = harness.shared
    instance._active_payload = {"model": harness.shared.MODEL, "messages": [{"role": "user", "content": "Authored facts"}]}
    instance.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}
    transmitted = []
    instance.client = SimpleNamespace(_http=lambda *args: transmitted.append(deepcopy(args)))
    if case == "mutated_payload":
        with pytest.raises(ValueError, match="changed"):
            instance._http("/api/chat", {**instance._active_payload, "model": "another-model"})
        assert not transmitted
    elif case == "undeclared_endpoint":
        with pytest.raises(ValueError, match="another backend endpoint"):
            instance._http("/api/embed", {"input": "unexpected reference request"})
        assert not transmitted
    else:
        payload = deepcopy(instance._active_payload)
        if case == "second_render":
            payload["_debug_render_only"] = True
        instance._http("/api/chat", payload)
        with pytest.raises(RuntimeError, match="second"):
            instance._http("/api/chat", payload)
        assert len(transmitted) == 1


@pytest.mark.requirement("30.8:no-empty-or-unadopted-policy-pass")
@pytest.mark.parametrize("policy_change", ["empty_expected", "empty_required", "missing_row", "not_applicable_without_reason"])
def test_acceptance_requires_the_declared_check_register_and_explained_applicability(policy_change):
    policy = harness.config("version4_acceptance_policy.json")
    report = harness.report(policy)
    if policy_change == "empty_expected":
        policy["expected_check_ids"] = []
    elif policy_change == "empty_required":
        # No required rows must be represented as a different policy; old flags cannot pass it.
        policy["required_check_ids"] = []
    elif policy_change == "missing_row":
        report["checks"].pop()
    else:
        report["checks"][0].update(status="not_applicable", reason="")
    assessment = {"assessment_complete": True, "issues": []}
    outcome = harness.evaluated.assess_acceptance(report, assessment, policy)
    assert outcome["accepted"] is False
    assert outcome["coverage_valid"] is False
