"""Exercise real receipt and transport tracing around authored offline fixtures."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
ROOT = next((p for p in HERE.parents if (p / "src/champion_athletic_map/pilot_probe.py").is_file()),
            HERE.parent / "work_step30/project/folder-before-step-30")
SOURCE = ROOT / "src/champion_athletic_map/reviewed_probe.py"
if not SOURCE.is_file():
    SOURCE = HERE / "reviewed_probe.py"


def load(path, name):
    value = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    value.__spec__.loader.exec_module(value)
    return value


API = load(SOURCE, "reviewed_probe_tested")
DOUBLES = load(ROOT / "tests/pilot_probe/test_pilot_probe.py", "reviewed_probe_transport_doubles")
ORDERS = {13: (3, 4, 2, 1), 3: (2, 3, 1, 4), 4: (1, 2, 4, 3), 12: (4, 1, 3, 2)}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(API.canonical(value) + b"\n")


@pytest.fixture
def saved(tmp_path):
    root = tmp_path
    for name in ("pilot_probe", "pilot_trace", "shared_guidance_probe", "development_pilot"):
        path = root / "src/champion_athletic_map" / (name + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "src/champion_athletic_map" / (name + ".py"), path)
    (root / "src/champion_athletic_map/reviewed_probe.py").write_bytes(SOURCE.read_bytes())
    (root / "src/champion_athletic_map/live_reviewed_runtime.py").write_text('"""Synthetic runtime routing marker."""\n')
    schema_name, config_name = "artifacts/fixture_review/public_schema.json", "artifacts/fixture_review/config.json"
    write(root / schema_name, {"type": "object", "fixture_only": True})
    write(root / config_name, {"fixture_only": True})
    review_files = {n: API.sha((root / n).read_bytes()) for n in (schema_name, config_name)}
    window = {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"}
    roster, publics, bindings = [], {}, dict(review_files)
    for index in range(1, 21):
        public = {"schema_version": "athlete-profile-input-2", "profile_id": "software:reviewed:" + str(index),
            "input": {"age": 13, "athlete_request": "Plan two additional basketball sessions.",
                      "planning_window": deepcopy(window), "existing_commitments": []}}
        publics[index] = public
        jobs = [{"job_id": f"old_case{index}_v{v}", "call_id": f"old_case{index}_v{v}",
                 "planner_version": v, "position_in_case": p}
                for p, v in enumerate(ORDERS.get(index, (1, 2, 3, 4)), 1)]
        probe = "original_" + str(index)
        source = {"public_record": public, "public_record_sha256": API.sha(API.canonical(public)),
            "case_review_id": "synthetic-reviewed-cases", "case_review_files": review_files,
            "case_review_config_path": config_name, "public_schema_path": schema_name,
            "prepared_jobs": [{"fixture_only": True}], "jobs": jobs,
            "module_and_config_sha256": {}, "model_configuration": {"fixture_only": True},
            "limits": {"maximum_generation_submissions": 15, "maximum_revisions_v4": 2}, "timing_policy": {"fixture_only": True}}
        name = "artifacts/pilot/shared_guidance/" + probe + "/probe_manifest.json"
        write(root / name, source)
        bindings[name] = API.sha((root / name).read_bytes())
        reports = [{"planner_version": j["planner_version"], "job_id": j["job_id"],
                    "outcome_path": f"results/pilot/probes/{probe}/jobs/{j['job_id']}/outcome.json"} for j in jobs]
        roster.append({"case_index": index, "profile_id": public["profile_id"], "reports": reports})
    write(root / "results/step31_development_pilot_summary.json", {"development_pilot_completed": True,
        "recorded_jobs": 80, "injected_test_dependencies": False, "cases": roster, "fixture_only": True})
    dataset = {}
    for name in ("champions_unified_dataset.csv", "dataset_manifest.json", "load_unified_dataset.py", "READ_ME_FIRST.txt"):
        path = root / "data/unified/v1" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Authored test fixture, no athlete dataset.\n")
        dataset[name] = API.sha(path.read_bytes())
        bindings[path.relative_to(root).as_posix()] = dataset[name]
    write(root / "artifacts/planners/version1_config.json", {"dataset": {
        "relative_directory": "data/unified/v1", "file_sha256": dataset}, "fixture_only": True})
    bindings["artifacts/planners/version1_config.json"] = API.sha((root / "artifacts/planners/version1_config.json").read_bytes())
    evidence_name = "results/fixture_software.json"
    write(root / evidence_name, {"passed": 131, "fixture_only": True})
    evidence = {"status": "passed", "passed": 131, "files": {evidence_name: API.sha((root / evidence_name).read_bytes())}, "fixture_only": True}
    candidate_name = "artifacts/pilot/reviewed_workflow/fixture/manifest.json"
    write(root / candidate_name, {"manifest_id": "fixture-workflow", "workflow_id": "fixture",
        "candidate_only": True, "future_case_indices": list(API.CASE_INDICES), "injected_test_dependencies": False})
    write(root / API.PARENT, {"schema_version": "reviewed-workflow-offline-preparation-1",
        "status": "reviewed_inputs_prepared_offline", "candidate_only": True, "cases_prepared": 20,
        "all_packet_budgets_fit_locally": True, "original_packet_counts_reproduced": 20,
        "new_model_calls": 0, "query_encoder_processes": 0, "injected_test_dependencies": False,
        "software_evidence": evidence, "input_sha256": bindings, "component_sha256": {},
        "manifest_path": candidate_name, "manifest_id": "fixture-workflow", "workflow_id": "fixture"})
    for name in ("results/step31_first_probe_summary.json", "results/step31_shared_guidance_summary.json"):
        write(root / name, {"older_results": "preserve", "fixture_only": True})
    manifest = API.prepare(root, execution_mode="injected_test", environment_record={"fixture_only": True})
    return SimpleNamespace(root=root, evidence=evidence, manifest=manifest, publics=publics)


@pytest.fixture
def execution(saved):
    state = {"http": [], "jobs": [], "public_inputs": [], "packets": [], "references": [],
             "runtime_builds": 0, "encoder_processes": 0, "assessed": []}
    class Planner(DOUBLES.TestPlanner):
        def generate(self, public, *args):
            if state.get("interrupt_after_first") and len(state["jobs"]) == 1 and not state.get("interrupted"):
                state["interrupted"] = True
                raise KeyboardInterrupt("Synthetic interruption before the next model request")
            result = super().generate(public, *args)
            if self.version == 4 and state.get("fatal_v4"):
                return {**result, "status": "failed", "completion_valid": False, "format_valid": False,
                    "response_type": None, "terminal_state": "execution_error", "response": None, "draft_result": deepcopy(result)}
            return result
    def runtime(root, config, schema):
        state["runtime_builds"] += 1
        return SimpleNamespace(planners={v: Planner(root, state, v) for v in range(1, 5)},
            tools=SimpleNamespace(state=state), reference_policy={"fixture_only": True}, manifest={"fixture_only": True})
    class Assessor:
        def __init__(self, root, schema):
            pass
        def assess(self, public, outcome, packet, *, assessment_id):
            state["assessed"].append(deepcopy(outcome))
            return {"assessment_id": assessment_id, "assessment_execution": "completed",
                "designated_outcome_sha256": API.sha(API.canonical(outcome)), "overall": "requirements_unverified",
                "checks": [{"check_id": "unverified-test-check", "status": "unknown", "required": True}], "fixture_only": True}
    def run(**kwargs):
        return API.execute(saved.root, saved.manifest, software_evidence=saved.evidence,
            runtime_factory=runtime, references_factory=DOUBLES.SavedReferences,
            assessor_factory=Assessor, trace_module=DOUBLES.tracing, emit=lambda text: None, **kwargs)
    return SimpleNamespace(saved=saved, state=state, runtime=runtime, Assessor=Assessor, run=run)


def test_freeze_fixed_balanced_roster_and_all_limits(saved):
    second = API.prepare(saved.root, execution_mode="injected_test", environment_record={"fixture_only": True})
    assert second == saved.manifest
    assert [c["case_index"] for c in second["cases"]] == [13, 3, 4, 12]
    for case in second["cases"]:
        child = API.child_manifest(saved.root, second, case)
        assert [j["planner_version"] for j in child["jobs"]] == list(ORDERS[case["case_index"]])
        assert all(j["call_id"].startswith("p31r_") and len(j["call_id"]) < 50 for j in child["jobs"])
    assert second["limits"]["maximum_generation_submissions_total"] == 60
    assert second["offline_candidate_packets_reused_for_generation"] is False


def test_sixteen_original_runner_jobs_then_zero_call_reuse(execution):
    old = {name: (execution.saved.root / name).read_bytes() for name in
           (API.PARENT, "results/step31_first_probe_summary.json", "results/step31_shared_guidance_summary.json")}
    first = execution.run()
    assert first["completed_cases"] == 4 and first["recorded_jobs"] == 16
    assert first["new_model_submissions"] == first["cumulative_model_submissions"] == 16
    assert execution.state["jobs"] == [v for index in API.CASE_INDICES for v in ORDERS[index]]
    assert execution.state["encoder_processes"] == len(execution.state["references"]) == 12
    before = deepcopy(execution.state)
    second = execution.run()
    assert second["new_model_submissions"] == 0 and second["saved_completed_cases_reused"] == 4
    assert execution.state == before and not (execution.saved.root / API.SUMMARY).exists()
    assert all((execution.saved.root / name).read_bytes() == data for name, data in old.items())


def test_partial_continuation_does_not_repeat_saved_job_or_packet(execution):
    execution.state["interrupt_after_first"] = True
    with pytest.raises(KeyboardInterrupt):
        execution.run()
    assert len(execution.state["jobs"]) == 1
    result = execution.run()
    assert result["recorded_jobs"] == 16 and result["new_model_submissions"] == 15
    assert len(execution.state["jobs"]) == 16 and execution.state["encoder_processes"] == 12


@pytest.mark.parametrize("flag", ["timeout_version", "reference_failure"])
def test_uncertain_or_reference_failure_stays_stopped(execution, flag):
    execution.state[flag] = 3 if flag == "timeout_version" else True
    result = execution.run()
    assert result["status"] == "stopped_for_review" and result["recorded_jobs"] == 1
    before = deepcopy(execution.state)
    repeat = execution.run()
    assert repeat["new_model_submissions"] == 0 and repeat["stop_reason"] == result["stop_reason"]
    assert execution.state == before


def test_fatal_v4_remains_failed_final_outcome(execution):
    execution.state["fatal_v4"] = True
    result = execution.run()
    v4 = [r for c in result["cases"] for r in c["reports"] if r["planner_version"] == 4]
    assert len(v4) == 4 and all(r["outcome"]["completion_valid"] is False for r in v4)
    assert all(o["response"] is None for o in execution.state["assessed"] if o.get("terminal_state") == "execution_error")


def test_changed_software_blocks_before_runtime(execution):
    path = execution.saved.root / next(iter(execution.saved.evidence["files"]))
    path.write_bytes(b"changed\n")
    with pytest.raises(ValueError, match="dependency changed"):
        execution.run()
    assert execution.state["runtime_builds"] == 0 and not execution.state["http"]


def test_completed_receipt_change_blocks_reuse(execution):
    result = execution.run(max_cases=1)
    path = execution.saved.root / result["cases"][0]["reports"][0]["outcome_path"]
    path.write_bytes(b"{}\n")
    before = deepcopy(execution.state)
    with pytest.raises(ValueError, match="changed"):
        execution.run()
    assert execution.state == before


def test_injected_mode_cannot_execute_as_production(saved):
    with pytest.raises(ValueError, match="cannot share"):
        API.execute(saved.root, saved.manifest, software_evidence=saved.evidence, emit=lambda text: None)


def test_default_production_routes_new_factories(saved, execution, monkeypatch):
    production = API.prepare(saved.root, execution_mode="production", environment_record={"fixture_only": True})
    calls = {"runtime": 0, "references": 0, "assessor": 0}
    def runtime(root, config, schema, *, public_record):
        calls["runtime"] += 1
        return execution.runtime(root, config, schema)
    def references(root, tools, client, policy):
        calls["references"] += 1
        return DOUBLES.SavedReferences(root, tools, client, policy)
    def assessor(root, schema):
        calls["assessor"] += 1
        return execution.Assessor(root, schema)
    original_module = API.module
    def routed(root, name):
        if name == "live_reviewed_runtime":
            return SimpleNamespace(build_runtime=runtime, build_reference_preparer=references, make_assessor=assessor)
        return original_module(root, name)
    monkeypatch.setattr(API, "module", routed)
    result = API.execute(saved.root, production, software_evidence=saved.evidence, emit=lambda text: None)
    assert result["recorded_jobs"] == 16 and result["injected_test_dependencies"] is False
    assert calls == {"runtime": 4, "references": 4, "assessor": 4}
    assert execution.state["encoder_processes"] == 12
    assert (saved.root / API.SUMMARY).exists()


pytestmark = pytest.mark.requirement("31:reviewed-four-case-live-probe")
