"""Our small fictional application fixtures; no research examples or model calls."""

from copy import deepcopy
from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]


def load(relative, name):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location("step30_app_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


state = load("src/champion_athletic_map/application_state.py", "state")
exports = load("src/champion_athletic_map/plan_exports.py", "exports")
runtime = load("src/champion_athletic_map/runtime_controller.py", "runtime")
integration = json.loads((ROOT / "artifacts/language_model/integration_config.json").read_bytes())
response = load(integration["contracts_directory"] + "/response_contract.py", "response")
PROFILE_SCHEMA = json.loads((ROOT / "artifacts/application/interactive_profile_schema.json").read_bytes())
VERSIONS = {"catalog": "authored-catalog-1", "rules": "authored-rules-1", "checker": "authored-checker-1"}


def public_profile(identifier="athlete:software-fixture"):
    return {"profile_id": identifier, "schema_version": "interactive-profile-input-1", "input": {
        "age": 16, "school_grade": 10,
        "athlete_request": "Plan three short basketball sessions using my available times.",
        "planning_window": {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"},
        "basketball_background": {"experience_level": "beginner"}, "goals": ["Improve passing"],
        "availability": [{"date": day, "start_time": "17:30", "end_time": "18:00"}
            for day in ("2026-11-16", "2026-11-18", "2026-11-21")],
        "existing_commitments": [], "equipment": [{"name": "Basketball", "quantity": 1}],
        "participants_available": 2,
        "space": {"court_access": "half_court", "hoop_access": True,
            "usable_area_description": "Half basketball court", "restrictions": []},
        "reported_limitations": [],
        "time_limits": {"max_additional_sessions_per_week": 3,
            "max_additional_minutes_per_week": 60, "max_session_minutes": 20}}}


def activity(identifier, *, parent=None, refs=None, description="Basketball passing session"):
    return {"activity_id": identifier, "description": description, "duration_minutes": 20,
        "timing": {"start_time": "17:30", "end_time": "17:50"},
        "existing_commitment_refs": refs or [],
        "resources": {"equipment": [{"name": "Basketball", "quantity": 1}],
            "space": "half_court", "participants": 2},
        "relationship": {"kind": "part_of_activity" if parent else "separate_session",
            "parent_activity_id": parent}}


def plan_response():
    days = [{"date": (date(2026, 11, 16) + timedelta(days=i)).isoformat(),
        "activities": [], "rest_arrangements": "No added training."} for i in range(7)]
    for offset, identifier in ((0, "monday"), (2, "wednesday"), (5, "saturday")):
        days[offset]["activities"].append(activity(identifier))
    return {"response_type": "plan", "explanation": "An authored software fixture.",
        "planning_window": deepcopy(public_profile()["input"]["planning_window"]), "weekly_schedule": days}


def validate_profile(value):
    Draft202012Validator(PROFILE_SCHEMA, format_checker=FormatChecker()).validate(value)
    return {"public_input": deepcopy(value["input"])}


def validate_response(value):
    parsed = response.parse_response_text(json.dumps(value), response.build_response_schema())
    if not parsed["parse_valid"]:
        raise ValueError(parsed["issues"])
    return parsed


def coded_check(public, candidate, packet):
    validate_profile(public)
    validate_response(candidate)
    return {"execution_status": "completed", "checks": [{"check_id": "authored-interface-check",
        "status": "unknown", "required": True, "reason": "Software fixture; plan quality is not assessed."}]}


def resolve_catalog(identifier):
    if identifier != "catalog:approved-fixture":
        raise ValueError("This activity is unavailable or unapproved.")
    return {"catalog_id": identifier, "description": "Authoritative passing activity instructions.",
        "resources": {"equipment": [{"name": "Basketball", "quantity": 1}],
            "space": "half_court", "participants": 2},
        "evidence_refs": [identifier, "https://example.org/authored-passing-source"],
        "source_fields": {"instructions": "Authoritative passing activity instructions."}}


def outcome(candidate=None):
    return {"status": "returned", "terminal_state": "revision_limit_reached",
        "completion_valid": True, "format_valid": True, "internally_accepted": False,
        "response": {"model_output": {"parsed_object": deepcopy(candidate or plan_response())}}}


def saved_state(*, historical=False, candidate=None, public=None, session="fixture-session"):
    workspace = state.new_state(session)
    state.save_profile(workspace, public or public_profile(), validate_profile)
    state.begin_job(workspace, "authored-generation")
    attached = state.attach_outcome(workspace, "authored-generation", outcome(candidate),
        source_versions=VERSIONS, check_report=None, historical=historical)
    assert attached["attached"]
    return workspace


def set_completed(workspace, identifier="monday"):
    item = next(x for x in state.trackable_sessions(workspace) if x["activity_id"] == identifier)
    state.update_progress(workspace, item["occurrence_id"], "completed")


def change_duration(workspace, identifier="wednesday"):
    return state.save_plan_changes(workspace,
        [{"activity_id": identifier, "duration_minutes": 15, "end_time": "17:45"}],
        resolve_catalog, coded_check, VERSIONS)


def restore(data, **overrides):
    options = {"session_id": "restored-fixture-session", "validate_profile": validate_profile,
        "validate_response": validate_response, "resolve_catalog": resolve_catalog,
        "check_plan": coded_check, "source_versions": VERSIONS}
    options.update(overrides)
    return exports.restore_snapshot(data, **options)


class FakePrototypeService:
    instances = []

    def __init__(self, root):
        self.calls = {"generation": 0, "review": 0, "checks": 0}
        self.instances.append(self)

    def readiness(self):
        return {"generation_ready": False, "review_ready": False,
            "message": "Pilot testing is pending. Saved examples remain available."}

    def source_versions(self):
        return deepcopy(VERSIONS)

    def development_examples(self):
        return [{"public_record": public_profile(), "outcome": outcome(), "reference_packet": None}
            for _ in range(6)]

    validate_profile = staticmethod(validate_profile)
    validate_response = staticmethod(validate_response)
    resolve_catalog = staticmethod(resolve_catalog)

    def catalog_options(self):
        return [{"catalog_id": "catalog:approved-fixture", "name": "Authored approved passing activity"}]

    def check_plan(self, *args):
        self.calls["checks"] += 1
        return coded_check(*args)

    def generate(self, *args, **kwargs):
        self.calls["generation"] += 1
        raise AssertionError("A pending-pilot interface started generation.")

    def review_saved(self, *args, **kwargs):
        self.calls["review"] += 1
        raise AssertionError("A pending-pilot interface started model review.")
