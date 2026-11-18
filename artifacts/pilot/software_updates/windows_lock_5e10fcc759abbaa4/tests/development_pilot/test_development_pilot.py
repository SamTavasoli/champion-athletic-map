"""Run the real saved-job orchestration with synthetic, offline pilot cases."""

from copy import deepcopy
import csv
import importlib.util
import io
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


SOURCE = ROOT / "src/champion_athletic_map/development_pilot.py"
API = load(SOURCE, "development_pilot_under_test")
DOUBLES = load(ROOT / "tests/pilot_probe/test_pilot_probe.py", "development_pilot_offline_transport")
ORDERS = ((1, 2, 4, 3), (2, 3, 1, 4), (3, 4, 2, 1), (4, 1, 3, 2))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(API.canonical(value) + b"\n")


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts}


@pytest.fixture
def saved(tmp_path, monkeypatch):
    root = tmp_path
    for name in ("pilot_probe", "pilot_trace", "shared_guidance_probe"):
        path = root / "src/champion_athletic_map" / (name + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "src/champion_athletic_map" / (name + ".py"), path)
    (root / "src/champion_athletic_map/development_pilot.py").write_bytes(SOURCE.read_bytes())
    doc = root / API.DOCUMENT
    doc.parent.mkdir(parents=True)
    doc.write_text("Synthetic twenty-case software fixture; no actual model observation.\n")
    window = {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"}
    originals, publics, jobs = [], [], []
    for n in range(1, 21):
        original = {"profile_id": "software:development:" + str(n).zfill(2), "schema_version": "athlete-profile-input-1",
            "input": {"age": 13 + (n - 1) // 4, "athlete_request": "Plan two additional basketball sessions.",
                "planning_window": deepcopy(window), "existing_commitments": []}}
        if n <= 6:
            original["input"]["food_question"] = "A supplied synthetic food question?"
        original_hash = API.sha(API.canonical(original))
        amended = deepcopy(original)
        amended["schema_version"] = "athlete-profile-input-2"
        amended["input"]["schedule_coverage"] = {**window, "existing_commitments_complete": True}
        originals.append(original); publics.append(amended)
        for position, version in enumerate(ORDERS[(n - 1) % 4], 1):
            jobs.append({"scheduled_index": str(len(jobs) + 1), "pilot_index": str(n), "position_in_case": str(position),
                "planner_version": str(version), "profile_id": original["profile_id"], "public_record_sha256": original_hash,
                "job_id": "synthetic_prepared_case" + str(n) + "_v" + str(version), "order_label": "ABCD"[(n - 1) % 4]})
    legacy_path, public_path = "artifacts/synthetic_preparation/public_profiles.jsonl", "artifacts/synthetic_review/public_profiles.jsonl"
    for relative, rows in ((legacy_path, originals), (public_path, publics)):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"".join(API.canonical(row) + b"\n" for row in rows))
    jobs_path = "artifacts/synthetic_preparation/planned_pilot_jobs.csv"
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=list(jobs[0]), lineterminator="\n")
    writer.writeheader(); writer.writerows(jobs)
    (root / jobs_path).write_text(text.getvalue())
    config_path, schema_path = "artifacts/synthetic_review/case_review_config.json", "artifacts/synthetic_review/public_profile_schema.json"
    write(root / config_path, {"parent_preparation_files": {name: API.sha((root / name).read_bytes()) for name in (legacy_path, jobs_path)}, "fixture_only": True})
    write(root / schema_path, {"type": "object", "required": ["profile_id", "schema_version", "input"], "fixture_only": True})
    review_files = {name: API.sha((root / name).read_bytes()) for name in (public_path, config_path, schema_path)}
    identity = {"case_review_id": "synthetic_twenty_case_review", "case_review_files": review_files,
        "module_and_config_sha256": {}, "public_record": publics[0], "model_configuration": {"fixture_only": True},
        "limits": {"maximum_generation_submissions": 15, "maximum_revisions_v4": 2}, "timing_policy": {"fixture_only": True}}
    digest = API.sha(API.canonical(identity))
    source = {**identity, "manifest_id": digest, "probe_id": "synthetic_original_probe",
        "case_review_config_path": config_path, "public_schema_path": schema_path, "jobs": []}
    source_path = "artifacts/pilot/synthetic_original_manifest.json"
    write(root / source_path, source)
    write(root / "results/pilot/probes/first_operational_probe.json", {"manifest_id": digest, "manifest_path": source_path})
    for relative in ("results/step31_first_probe_summary.json", "results/step31_shared_guidance_summary.json", "results/step31_contract_probe_summary.json"):
        write(root / relative, {"fixture_only": True, "old_results": "preserve"})
    evidence_path, candidate_path = "results/synthetic_software_checks.json", "artifacts/synthetic_operational/configuration.json"
    write(root / evidence_path, {"passed": 1, "fixture_only": True})
    write(root / candidate_path, {"fixture_only": True, "food_field_limits": {"food_id": 64, "source_ref": 512}})
    evidence = {"status": "passed", "passed": 1, "files": {evidence_path: API.sha((root / evidence_path).read_bytes())}, "fixture_only": True}
    write(root / "results/step31_operational_corrections_summary.json", {"candidate_only": True, "new_runtime_executed": False,
        "new_model_calls": 0, "software_evidence": evidence, "input_sha256": {}, "component_sha256": {},
        "candidate_files": {candidate_path: API.sha((root / candidate_path).read_bytes())},
        "configuration_id": "synthetic_operational_candidate", "fixture_only": True})
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", lambda *a, **k: pytest.fail("Offline test attempted network transport"))
    manifest = API.prepare(root, environment_record={"fixture_only": True})
    return SimpleNamespace(root=root, manifest=manifest, software=evidence, publics=publics, prepared_jobs=jobs,
        candidate_path=candidate_path)


@pytest.fixture
def execution(saved):
    state = {"http": [], "jobs": [], "public_inputs": [], "packets": [], "references": [],
        "runtime_builds": 0, "encoder_processes": 0, "assessed": [], "default_publics": [], "audit_factory_calls": 0}
    class Planner(DOUBLES.TestPlanner):
        def generate(self, public, *args):
            result = super().generate(public, *args)
            if self.version == 4 and state.get("fatal_v4"):
                return {**result, "completion_valid": False, "format_valid": False, "status": "failed",
                    "response_type": None, "terminal_state": "execution_error", "response": None,
                    "draft_result": deepcopy(result), "fixture_only": True}
            return result
    def runtime(project, review, schema):
        state["runtime_builds"] += 1
        return SimpleNamespace(planners={v: Planner(project, state, v) for v in range(1, 5)}, tools=SimpleNamespace(state=state),
            reference_policy={"fixture_only": True}, manifest={"fixture_only": True})
    class Assessor:
        def __init__(self, project, schema):
            pass
        def assess(self, public, outcome, truth, *, assessment_id):
            state["assessed"].append(deepcopy(outcome))
            return {"assessment_id": assessment_id, "assessment_execution": "completed",
                "designated_outcome_sha256": API.sha(API.canonical(outcome)), "overall": "requirements_unverified",
                "food_answer_audit_version": "synthetic_audited_assessor", "fixture_only": True,
                "checks": [{"check_id": name, "status": "unknown", "required": True} for name in
                    ("requested_session_count", "food_answer_completeness", "food_numeric_correctness", "resource_requirements_evidence")]}
    def run(**kwargs):
        return API.run_next_batch(saved.root, saved.manifest, software_evidence=saved.software,
            runtime_factory=kwargs.pop("runtime_factory", runtime), references_factory=kwargs.pop("references_factory", DOUBLES.SavedReferences),
            trace_module=DOUBLES.tracing, assessor_factory=Assessor, emit=lambda text: None, **kwargs)
    return SimpleNamespace(saved=saved, state=state, runtime=runtime, Assessor=Assessor, run=run)


def test_prepare_freezes_twenty_amended_profiles_eighty_original_ordered_jobs(saved):
    before = files(saved.root)
    assert API.prepare(saved.root, environment_record={"fixture_only": True}) == saved.manifest
    assert files(saved.root) == before
    assert len(saved.manifest["case_roster"]) == 20 and sum(len(item["prepared_jobs"]) for item in saved.manifest["case_roster"]) == 80
    for n, case in enumerate(saved.manifest["cases"]):
        child = API.child_manifest(saved.root, saved.manifest, case)
        assert child["public_record"] == saved.publics[n]
        assert [job["planner_version"] for job in child["jobs"]] == list(ORDERS[n % 4])
        assert all(len(job["call_id"]) < 50 for job in child["jobs"])
    assert saved.manifest["limits"]["maximum_generation_submissions_total"] == 300
    assert saved.manifest["accepted_study_profiles"] == 0 and saved.manifest["protocol_frozen"] is False


def test_batches_resume_next_case_and_completed_receipt_skips_runtime(execution):
    before = files(execution.saved.root)
    first = execution.run(max_cases=1)
    second = execution.run(max_cases=1)
    assert first["completed_cases"] == 1 and second["completed_cases"] == 2
    assert first["new_model_submissions"] == second["new_model_submissions"] == 4
    assert second["saved_completed_cases_reused"] == 1 and second["recorded_jobs"] == 8
    assert len(second["jobs"]) == 80 and sum(job["state"] == "not_started" for job in second["jobs"]) == 72
    assert execution.state["runtime_builds"] == 2 and execution.state["encoder_processes"] == 6
    assert execution.state["public_inputs"] == [execution.saved.publics[0]] * 4 + [execution.saved.publics[1]] * 4
    assert all((execution.saved.root / relative).read_bytes() == data for relative, data in before.items())
    assert all(check["status"] == "unknown" for case in second["cases"] for report in case["reports"] for check in report["assessment"]["checks"])


def test_four_five_case_batches_record_all_jobs_then_reuse_without_calls(execution):
    for expected in (5, 10, 15, 20):
        result = execution.run()
        assert result["completed_cases"] == expected and result["new_cases_attempted_this_batch"] == 5
    before = deepcopy(execution.state)
    def forbidden(*args, **kwargs):
        pytest.fail("A fully recorded pilot constructed a runtime or encoded references")
    reused = execution.run(runtime_factory=forbidden, references_factory=forbidden)
    assert reused["new_model_submissions"] == 0 and reused["completed_cases"] == 20
    assert reused["recorded_jobs"] == 80 and reused["saved_completed_cases_reused"] == 20
    assert execution.state == before
    assert reused["development_pilot_completed"] is True
    assert reused["final_scores_computed"] is reused["protocol_frozen"] is reused["app_generation_enabled"] is False


def test_fatal_v4_is_terminal_and_assessed_without_draft_fallback(execution):
    execution.state["fatal_v4"] = True
    result = execution.run(max_cases=1)
    assert result["completed_cases"] == 1 and result["recorded_jobs"] == 4
    fatal = next(value for value in execution.state["assessed"] if value["planner_version"] == 4)
    assert fatal["response"] is None and fatal["draft_result"]["response"] is not None
    assert fatal["terminal_state"] == "execution_error"
    assert next(job for job in result["jobs"] if job["planner_version"] == 4)["outcome"]["completion_valid"] is False


def test_reference_failure_stops_batch_and_is_not_automatically_repeated(execution):
    execution.state["reference_failure"] = True
    result = execution.run()
    before = deepcopy(execution.state)
    assert result["stop_reason"] == "reference_preparation_needs_attention"
    assert result["completed_cases"] == 0 and result["recorded_jobs"] == 2
    execution.state["reference_failure"] = False
    repeated = execution.run()
    assert repeated["new_model_submissions"] == 0 and repeated["new_cases_attempted_this_batch"] == 0
    assert execution.state["http"] == before["http"] and execution.state["runtime_builds"] == before["runtime_builds"]


def test_injected_saved_cases_cannot_be_reused_as_production_observations(execution):
    execution.run(max_cases=1)
    before = deepcopy(execution.state)
    with pytest.raises(ValueError, match="injected test dependencies"):
        API.run_next_batch(execution.saved.root, execution.saved.manifest, software_evidence=execution.saved.software,
            max_cases=1, emit=lambda text: None)
    assert execution.state == before


@pytest.mark.parametrize("fault", ["completed_outcome", "child_pointer", "parent_candidate", "software"])
def test_changed_completed_inputs_and_evidence_block_before_new_calls(execution, fault):
    execution.run(max_cases=1)
    root, manifest = execution.saved.root, execution.saved.manifest
    case = manifest["cases"][0]
    if fault == "completed_outcome":
        child = API.child_manifest(root, manifest, case)
        path = root / "results/pilot/probes" / child["probe_id"] / "jobs" / child["jobs"][0]["job_id"] / "outcome.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif fault == "child_pointer":
        write(root / case["pointer"], {"manifest_id": "changed", "manifest_path": case["manifest_path"]})
    elif fault == "parent_candidate":
        path = root / execution.saved.candidate_path
        path.write_bytes(path.read_bytes() + b" ")
    else:
        execution.saved.software["passed"] = 0
    before = deepcopy(execution.state)
    with pytest.raises(ValueError):
        execution.run(max_cases=1)
    assert execution.state == before


def test_default_router_selects_operational_runtime_and_audited_assessor(execution, monkeypatch):
    real_module = API.module
    def modules(root, name):
        if name == "operational_runtime":
            def build(project, review, schema, *, public_record):
                execution.state["default_publics"].append(deepcopy(public_record))
                return execution.runtime(project, review, schema)
            return SimpleNamespace(build_runtime=build)
        if name == "food_answer_audit":
            def audited(project, schema):
                execution.state["audit_factory_calls"] += 1
                return execution.Assessor(project, schema)
            return SimpleNamespace(make_assessor=audited)
        value = real_module(root, name)
        if name == "shared_guidance_probe":
            old_module = value.module
            def defaults(project, requested):
                loaded = old_module(project, requested)
                if requested == "pilot_probe":
                    old_load = loaded.load_module
                    loaded.load_module = lambda project, requested: SimpleNamespace(FreshReferencePreparer=DOUBLES.SavedReferences) if requested == "pilot_references" else old_load(project, requested)
                return loaded
            value.module = defaults
        return value
    monkeypatch.setattr(API, "module", modules)
    result = API.run_next_batch(execution.saved.root, execution.saved.manifest, software_evidence=execution.saved.software,
        max_cases=1, emit=lambda text: None)
    assert result["injected_test_dependencies"] is False
    assert execution.state["default_publics"] == [execution.saved.publics[0]]
    assert execution.state["audit_factory_calls"] == 1
    assert all(report["assessment"]["food_answer_audit_version"] == "synthetic_audited_assessor" for report in result["cases"][0]["reports"])


def test_batch_lock_is_exclusive_and_released_without_deleting_persistent_markers(saved):
    with API.batch_lock(saved.root, saved.manifest):
        with pytest.raises(RuntimeError, match="Another development-pilot batch"):
            with API.batch_lock(saved.root, saved.manifest):
                pytest.fail("Two concurrent batch owners acquired the same lock")
    with API.batch_lock(saved.root, saved.manifest):
        pass
    assert not (saved.root / "results/integration/model_calls/active_call").exists()


pytestmark = pytest.mark.requirement("31:resumable-development-pilot")
