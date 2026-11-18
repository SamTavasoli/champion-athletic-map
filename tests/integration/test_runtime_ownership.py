"""We submit each interactive job once and keep uncertain work owned and locked."""

from copy import deepcopy
import json
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from app_fixtures import (VERSIONS, coded_check, load, resolve_catalog, response,
    runtime, saved_state, state, validate_profile)


pytestmark = pytest.mark.requirement("30.9:runtime-ownership-and-at-most-once")


def request(owner="authored-owner", kind="generation"):
    return {"owner_id": owner, "kind": kind, "profile_version": "profile-fixture",
        "profile_planning_hash": "profile-hash-fixture", "plan_version": None,
        "plan_content_hash": None}


def test_duplicate_completed_job_reuses_record_without_callback(tmp_path):
    controller = runtime.JobController(tmp_path)
    calls = []
    def callback():
        calls.append("generation")
        return {"status": "returned", "transport_attempts": {"metadata": 0, "render": 0, "generation": 1}}
    first = controller.execute("app_same", request(), callback)
    second = controller.execute("app_same", request(), callback)
    assert calls == ["generation"]
    assert first["cached"] is False and second["cached"] is True
    assert second["transport_attempts_this_execution"] == {"metadata": 0, "render": 0, "generation": 0}
    events = [json.loads(line) for line in (tmp_path / "results/app/development_runs.jsonl").read_text().splitlines()]
    assert [row["cached"] for row in events] == [False, True]


@pytest.mark.parametrize("changed", [{"owner_id": "different-owner"}, {"profile_version": "different-profile"}, {"kind": "review"}])
def test_job_identity_cannot_be_reused_for_other_owner_profile_or_action(tmp_path, changed):
    controller = runtime.JobController(tmp_path)
    controller.execute("app_owned", request(), lambda: {"status": "completed"})
    with pytest.raises(runtime.PreflightBlocked, match="belongs to another"):
        controller.execute("app_owned", {**request(), **changed}, lambda: pytest.fail("Replayed an owned job"))


def test_generation_and_review_share_process_wide_gate(tmp_path):
    entered, release = Event(), Event()
    controller = runtime.JobController(tmp_path)
    other_controller = runtime.JobController(tmp_path)
    output = []
    def held_callback():
        entered.set()
        assert release.wait(5), "The authored test did not release the job."
        return {"status": "completed"}
    thread = Thread(target=lambda: output.append(controller.execute("app_running", request(), held_callback)))
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(runtime.PreflightBlocked, match="already running"):
            other_controller.execute("app_review", request(kind="review"), lambda: pytest.fail("Overlapping review ran"))
        assert not (tmp_path / "results/app/jobs/app_review").exists()
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive() and output[0]["status"] == "completed"


def test_uncertain_completion_retains_file_gate_and_is_never_resubmitted(tmp_path):
    controller = runtime.JobController(tmp_path)
    result = controller.execute("app_uncertain", request(), lambda: {"status": "unresolved"})
    assert result["status"] == "unresolved"
    assert (tmp_path / "results/app/active_model_job/owner.json").is_file()
    cached = controller.execute("app_uncertain", request(), lambda: pytest.fail("Uncertain request replayed"))
    assert cached["cached"] is True
    with pytest.raises(runtime.PreflightBlocked, match="active or unresolved"):
        runtime.JobController(tmp_path).execute("app_next", request(), lambda: pytest.fail("New request overlapped"))


def test_unknown_callback_error_is_recorded_as_unresolved(tmp_path):
    controller = runtime.JobController(tmp_path)
    def callback():
        raise RuntimeError("Authored uncertain transport failure")
    result = controller.execute("app_error", request(), callback)
    assert result["status"] == "unresolved"
    assert "Authored uncertain" in result["value"]["error"]
    assert (tmp_path / "results/app/active_model_job").is_dir()


def test_preexisting_backend_request_blocks_before_callback_and_releases_own_gate(tmp_path):
    active = tmp_path / "results/integration/model_calls/active_call"
    active.mkdir(parents=True)
    with pytest.raises(runtime.PreflightBlocked, match="backend request is unresolved"):
        runtime.JobController(tmp_path).execute("app_blocked", request(), lambda: pytest.fail("Blocked callback ran"))
    assert not (tmp_path / "results/app/jobs/app_blocked").exists()
    assert not (tmp_path / "results/app/active_model_job").exists()
    assert active.is_dir()


def test_display_binding_rejects_foreign_session_or_saved_plan(tmp_path):
    result = runtime.JobController(tmp_path).execute("app_binding", request(), lambda: {"status": "completed"})
    assert runtime.JobController.belongs_to(result, "authored-owner", "profile-fixture", "profile-hash-fixture")
    assert not runtime.JobController.belongs_to(result, "other-owner", "profile-fixture", "profile-hash-fixture")
    assert not runtime.JobController.belongs_to(result, "authored-owner", "profile-fixture", "profile-hash-fixture", "plan-other", "hash-other")


@pytest.mark.parametrize("checker_completed,replacement", [(True, False), (False, False), (True, True)])
def test_saved_plan_review_runs_fresh_checks_and_only_one_evaluator(tmp_path, checker_completed, replacement):
    interactive = load("src/champion_athletic_map/interactive_review.py", "interactive-review")
    policy_module = load("src/champion_athletic_map/planners/evaluated_specialists.py", "review-policy")
    codec = load("src/champion_athletic_map/context_encoding.py", "review-codec")
    workspace = saved_state(historical=True)
    if replacement:
        state.save_plan_changes(workspace, [{"activity_id": "wednesday", "replacement_id": "catalog:approved-fixture"}],
            resolve_catalog, coded_check, VERSIONS)
    profile, plan = state.current_profile(workspace), state.current_plan(workspace)
    before = deepcopy(plan)
    calls = []
    source_hash = "authored-review-sources"
    packet = {"schema_version": "shared-reference-packet-1", "packet_id": "authored-packet",
        "public_input_sha256": state.content_hash(profile["public_record"]["input"]),
        "preparation": {"source_configuration_sha256": source_hash, "interactive_catalog_ids": []},
        "payload": {"references": [], "food_lookup": [], "catalog_records": []}}
    plan["reference_packet"] = packet
    before = deepcopy(plan)
    expected_packet = deepcopy(packet)
    if replacement:
        expected_packet["packet_id"] = "authored-replacement-review-packet"
        expected_packet["preparation"]["interactive_catalog_ids"] = ["catalog:approved-fixture"]

    class ScriptedTransport:
        def __init__(self, *args):
            self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}

        def generate(self, public, context, instructions, call_id, **options):
            calls.append(("evaluator", deepcopy(options)))
            assert context == expected_packet
            assert public == profile["public_record"]
            return {"status": "returned", "completion_valid": True, "format_valid": True,
                "response": {"model_output": {"parsed_object": {"assessment_complete": True, "issues": []}}},
                "transport_attempts": {"metadata": 0, "render": 0, "generation": 1}}

    def check(public, candidate, context, **options):
        calls.append(("coded", deepcopy(options)))
        assert candidate == before["response"]
        return {"execution_status": "completed" if checker_completed else "error",
            "checks": [{"check_id": "authored-required", "required": True, "status": "met", "reason": "Authored condition."}]}

    engine = SimpleNamespace(client=object(), _adapter=object(), integration={},
        instructions="Authored review instructions", evaluator_schema={"type": "object"})
    service = object.__new__(interactive.PrototypeService)
    service.root = tmp_path
    service.source_fingerprint = "authored-source-fingerprint"
    service.reference_policy = {"source_configuration_sha256": source_hash, "policy_version": "authored-review"}
    service.policy = {"expected_check_ids": ["authored-required"], "required_check_ids": ["authored-required"],
        "allowed_evaluator_categories": [], "blocking_evaluator_categories": []}
    service.evaluator_prompt = "Review this saved version."
    service.response, service.response_schema = response, response.build_response_schema()
    service.public = SimpleNamespace(preserve_response_record=lambda prepared, parsed: {"model_output": parsed})
    service.readiness = lambda: {"review_ready": True}
    service.source_versions = lambda: deepcopy(VERSIONS)
    def validate(public):
        validate_profile(public)
        return {"audit": {"public_input_sha256": state.content_hash(public["input"])}}
    service.validate_profile = validate
    service._get_planner = lambda: SimpleNamespace(planner=engine)
    service.checker = SimpleNamespace(check=check)
    service.controller = runtime.JobController(tmp_path)
    def module(name, relative):
        if relative.endswith("application_state.py"):
            return state
        if relative.endswith("evaluated_specialists.py"):
            return policy_module
        if relative.endswith("role_adapter.py"):
            return SimpleNamespace(RoleAdapter=ScriptedTransport)
        if relative.endswith("context_encoding.py"):
            return codec
        raise AssertionError("An undeclared saved-review module was requested: " + relative)
    service._module = module
    def prepare_context(public, job_id, catalog_ids):
        assert replacement, "A matching review packet was unexpectedly refreshed."
        assert catalog_ids == ["catalog:approved-fixture"]
        calls.append(("replacement_context", deepcopy(catalog_ids)))
        return deepcopy(expected_packet)
    service._prepare_context = prepare_context
    result = service.review_saved(profile, plan, "app_saved_review", "authored-owner")
    assert plan == before
    assessment = result["assessment"]
    if checker_completed:
        expected_order = ["replacement_context", "coded", "evaluator"] if replacement else ["coded", "evaluator"]
        assert [row[0] for row in calls] == expected_order
        options = calls[-1][1]
        assert options["stage"] == "evaluator" and options["planner_version"] == 4
        assert set(options["specialist_notes"]) == {"candidate", "check_results"}
        assert options["specialist_notes"]["candidate"]["parsed_object"] == before["response"]
        assert assessment["review_complete"] is True
        assert assessment["content_changed"] is False and assessment["coordinator_revisions"] == 0
        assert assessment["reference_packet"] == expected_packet
    else:
        assert [row[0] for row in calls] == ["coded"]
        assert assessment["review_complete"] is False
        assert assessment["internally_accepted"] is False
