"""Exercise the prospective runner with synthetic records and offline transports."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import urllib.request

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


source = ROOT / "src/champion_athletic_map/shared_guidance_probe.py"
API = load(source, "prospective_probe_under_test")
DOUBLES = load(ROOT / "tests/pilot_probe/test_pilot_probe.py", "prospective_saved_transport_doubles")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(API.canonical(value) + b"\n")


def file_map(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts}


@pytest.fixture
def saved(tmp_path, monkeypatch):
    # These authored fixtures are software tests, never recorded model observations.
    root = tmp_path
    for name in ("pilot_probe", "pilot_trace", "independent_plan_assessment"):
        target = root / "src/champion_athletic_map" / (name + ".py")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "src/champion_athletic_map" / (name + ".py"), target)
    for relative in ("docs/prompts/shared_task_addendum_candidate.txt", "docs/shared_guidance_development_probe.md"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Synthetic common guidance fixture.\n", encoding="utf-8")
    old = {"profile_id": "synthetic-original-case", "input": {"age": 13}, "fixture_only": True}
    public = {"profile_id": API.PROFILE_ID, "schema_version": "athlete-profile-input-2",
        "input": {"age": 15, "athlete_request": "Organize two additional basketball practices.",
            "availability": [{"fixture_slot": n} for n in range(3)],
            "time_limits": {"max_additional_sessions_per_week": 3},
            "food_question": "For Dates, medjool, protein in 150 g?"}, "fixture_only": True}
    profile_path = "artifacts/synthetic_review/public_profiles.jsonl"
    path = root / profile_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(API.canonical(old) + b"\n" + API.canonical(public) + b"\n")
    jobs_path = "artifacts/synthetic_review/planned_pilot_jobs.csv"
    order = (2, 1, 4, 3)
    (root / jobs_path).write_text("profile_id,planner_version,position_in_case,job_id\n" + "".join(
        API.PROFILE_ID + "," + str(v) + "," + str(i) + ",synthetic_parent_v" + str(v) + "\n"
        for i, v in enumerate(order, 1)), encoding="utf-8")
    config_path = "artifacts/synthetic_review/case_review_config.json"
    schema_path = "artifacts/synthetic_review/public_profile_schema.json"
    write(root / config_path, {"parent_preparation_files": {jobs_path: API.sha((root / jobs_path).read_bytes())},
        "fixture_only": True})
    write(root / schema_path, {"type": "object", "fixture_only": True})
    review_files = {name: API.sha((root / name).read_bytes()) for name in (profile_path, config_path, schema_path)}
    source_manifest = {"case_review_files": review_files, "case_review_config_path": config_path,
        "public_schema_path": schema_path, "public_record": old, "module_and_config_sha256": {},
        "probe_id": "synthetic_original", "case_review_id": "synthetic_review",
        "model_configuration": {"fixture_only": True}, "limits": {"maximum_generation_submissions": 15},
        "timing_policy": {"fixture_only": True}}
    source_path = "artifacts/pilot/synthetic_original_manifest.json"
    write(root / source_path, source_manifest)
    write(root / "results/pilot/probes/first_operational_probe.json", {"manifest_path": source_path})
    assessment_path = "results/synthetic_prior_assessments.json"
    write(root / assessment_path, {"fixture_only": True})
    evidence_path = "results/synthetic_software_report.json"
    write(root / evidence_path, {"fixture_only": True, "passed": 1})
    evidence = {"status": "passed", "passed": 1,
        "files": {evidence_path: API.sha((root / evidence_path).read_bytes())}, "fixture_only": True}
    prior = {"original_outcomes_assessed": 4, "amended_outcomes_assessed": 1,
        "assessment_execution_errors": 0, "injected_test_dependencies": False,
        "software_evidence": evidence, "input_sha256": {}, "component_sha256": {},
        "assessment_file": assessment_path, "assessment_file_sha256": API.sha((root / assessment_path).read_bytes()),
        "assessment_id": "synthetic_prior_assessment", "fixture_only": True}
    write(root / "results/step31_independent_checks_summary.json", prior)
    write(root / "results/step31_first_probe_summary.json", {"old_result": "must remain unchanged", "fixture_only": True})
    calls = []
    real_module = API.module
    def modules(project, name):
        if name == "independent_assessment_run":
            return SimpleNamespace(load_saved_cases=lambda project: calls.append("verified_prior_loader"))
        return real_module(project, name)
    monkeypatch.setattr(API, "module", modules)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", lambda *a, **k: pytest.fail("Offline test attempted network transport"))
    manifest = API.prepare(root, environment_record={"fixture_only": True})
    return SimpleNamespace(root=root, manifest=manifest, public=public, original=source_manifest,
        software=evidence, order=order, profile_path=profile_path, loader_calls=calls)


@pytest.fixture
def execution(saved):
    state = {"runtime_builds": 0, "http": [], "jobs": [], "references": [],
        "encoder_processes": 0, "public_inputs": [], "packets": [], "assessments": [], "arguments": {}}
    class Planner(DOUBLES.TestPlanner):
        def generate(self, public, *args):
            state["arguments"][self.version] = deepcopy(args)
            result = super().generate(public, *args)
            if self.version == 4 and state.get("fatal_v4"):
                return {**result, "status": "failed", "completion_valid": False, "format_valid": False,
                    "response_type": None, "terminal_state": "execution_error", "response": None,
                    "draft_result": deepcopy(result), "fixture_only": True}
            return result
    def runtime(project, config, schema):
        state["runtime_builds"] += 1
        return SimpleNamespace(planners={v: Planner(project, state, v) for v in range(1, 5)},
            tools=SimpleNamespace(state=state), reference_policy={"fixture_only": True}, manifest={"fixture_only": True})
    class Assessor:
        def __init__(self, project, schema):
            pass
        def assess(self, public, outcome, truth, *, assessment_id):
            assert len(state["jobs"]) == 4, "Truth must only reach independent assessment after generation."
            state["assessments"].append({"public": deepcopy(public), "outcome": deepcopy(outcome), "truth": deepcopy(truth)})
            return {"assessment_id": assessment_id, "assessment_execution": "completed",
                "overall": "requirements_unverified", "fixture_only": True,
                "checks": [{"check_id": name, "status": "unknown", "required": True,
                    "reason": "Synthetic unresolved evidence."} for name in
                    ("requested_session_count", "food_answer_completeness", "resource_requirements_evidence")]}
    def run(**kwargs):
        return API.execute(saved.root, saved.manifest, software_evidence=saved.software,
            runtime_factory=kwargs.pop("runtime_factory", runtime),
            references_factory=kwargs.pop("references_factory", DOUBLES.SavedReferences),
            trace_module=DOUBLES.tracing, assessor_factory=Assessor, emit=lambda text: None, **kwargs)
    return SimpleNamespace(saved=saved, state=state, run=run)


def test_prepare_uses_fresh_fixed_case_preserves_balanced_order_and_originals(saved):
    value = saved.manifest
    assert value["public_record"] == saved.public
    assert value["public_record"]["profile_id"] != saved.original["public_record"]["profile_id"]
    assert [job["planner_version"] for job in value["jobs"]] == list(saved.order)
    assert len({job["job_id"] for job in value["jobs"]}) == 4
    assert value["active_guidance_scope"] == "this_new_development_probe_only_all_four_workflows"
    assert value["output_repairs"] == value["automatic_retries"] == value["accepted_study_profiles"] == 0
    before = file_map(saved.root)
    assert API.prepare(saved.root, environment_record={"fixture_only": True}) == value
    assert file_map(saved.root) == before


def test_execute_redirects_old_summary_and_reuses_whole_jobs_without_transport(execution):
    project = execution.saved.root
    original = (project / "results/step31_first_probe_summary.json").read_bytes()
    first = execution.run()
    state = deepcopy(execution.state)
    def forbidden(*args, **kwargs):
        pytest.fail("Verified whole-job reuse constructed a runtime or reference preparer")
    second = execution.run(runtime_factory=forbidden, references_factory=forbidden)
    assert first["new_model_submissions"] == 4 and first["recorded_jobs"] == 4
    assert second["new_model_submissions"] == 0 and second["saved_jobs_reused"] == 4
    assert execution.state["http"] == state["http"] and execution.state["encoder_processes"] == 3
    assert (project / "results/step31_first_probe_summary.json").read_bytes() == original
    assert (project / API.GENERATION_SUMMARY).is_file()
    assert execution.state["jobs"] == list(execution.saved.order)


def test_truth_is_post_generation_only_and_required_unknowns_remain_unknown(execution):
    result = execution.run()
    assert execution.state["public_inputs"] == [execution.saved.public] * 4
    assert len(execution.state["arguments"][1]) == 1  # Only call ID; no reference packet.
    assert len(execution.state["packets"]) == 3
    assert len(execution.state["assessments"]) == 4
    assert all(item["truth"] == execution.state["packets"][0] for item in execution.state["assessments"])
    assert result["independent_assessment_completed"] is True
    assert all(item["assessment"]["overall"] == "requirements_unverified" for item in result["reports"])
    assert all(check["status"] == "unknown" and check["required"] for item in result["reports"]
        for check in item["assessment"]["checks"])
    assert result["final_scores_computed"] is result["protocol_frozen"] is result["app_generation_enabled"] is False


def test_fatal_v4_designated_outcome_does_not_fall_back_to_saved_draft(execution):
    execution.state["fatal_v4"] = True
    result = execution.run()
    assessed = next(item["outcome"] for item in execution.state["assessments"]
        if item["outcome"]["planner_version"] == 4)
    assert assessed["terminal_state"] == "execution_error" and assessed["response"] is None
    assert assessed["draft_result"]["response"] is not None
    row = next(item for item in result["reports"] if item["planner_version"] == 4)
    assert row["outcome"]["completion_valid"] is row["outcome"]["format_valid"] is False


def test_reference_failure_stops_probe_and_cannot_be_scored_as_completed(execution):
    execution.state["reference_failure"] = True
    result = execution.run()
    assert result["stop_reason"] == "reference_preparation_needs_attention"
    assert result["recorded_jobs"] == 1 and result["new_model_submissions"] == 0
    assert result["independent_assessment_completed"] is False and result["reports"] == []
    assert execution.state["assessments"] == [] and execution.state["jobs"] == []


def test_bound_case_mutation_rejected_before_generation(execution):
    path = execution.saved.root / execution.saved.profile_path
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="dependency changed"):
        execution.run()
    assert execution.state["jobs"] == [] and execution.state["http"] == []


def test_in_memory_public_input_mutation_rejected_before_generation(execution):
    execution.saved.manifest["public_record"]["input"]["age"] = 17
    with pytest.raises(ValueError):
        execution.run()
    assert execution.state["jobs"] == [] and execution.state["http"] == []


@pytest.mark.parametrize("changed", ["unexecuted", "changed_report"])
def test_unexecuted_or_corrupt_software_evidence_stops_before_calls(execution, changed):
    if changed == "unexecuted":
        execution.saved.software["passed"] = 0
    else:
        report = next(iter(execution.saved.software["files"]))
        (execution.saved.root / report).write_bytes(b"changed synthetic report")
    with pytest.raises(ValueError):
        execution.run()
    assert execution.state["jobs"] == [] and execution.state["http"] == []


pytestmark = pytest.mark.requirement("31:prospective-shared-guidance-probe")
