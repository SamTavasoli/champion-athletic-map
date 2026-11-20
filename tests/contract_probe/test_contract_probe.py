"""Check the contract probe with explicit synthetic records and offline doubles."""

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


SOURCE = ROOT / "src/champion_athletic_map/contract_probe.py"
API = load(SOURCE, "contract_probe_under_test")
DOUBLES = load(ROOT / "tests/pilot_probe/test_pilot_probe.py", "contract_probe_saved_transport_doubles")
ADAPTER = load(ROOT / "src/champion_athletic_map/llm.py", "contract_probe_strict_decoder")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(API.canonical(value) + b"\n")


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts}


@pytest.fixture
def saved(tmp_path, monkeypatch):
    root = tmp_path
    for name in ("pilot_probe", "pilot_trace", "shared_guidance_probe", "independent_plan_assessment"):
        path = root / "src/champion_athletic_map" / (name + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "src/champion_athletic_map" / (name + ".py"), path)
    document = root / API.DOCUMENT
    document.parent.mkdir(parents=True)
    document.write_text("Synthetic contract probe test fixture.\n")
    public = {"profile_id": API.PROFILE_ID, "schema_version": "athlete-profile-input-2",
        "input": {"age": 16, "athlete_request": "Organize two additional basketball practices.",
            "availability": [{"fixture_slot": 1}, {"fixture_slot": 2}],
            "time_limits": {"max_additional_sessions_per_week": 2},
            "food_question": "Blueberry protein in 250 g?"}, "fixture_only": True}
    original = {"profile_id": "synthetic_earlier_case", "input": {"age": 13}, "fixture_only": True}
    profile_path = "artifacts/synthetic_review/public_profiles.jsonl"
    path = root / profile_path
    path.parent.mkdir(parents=True)
    path.write_bytes(API.canonical(original) + b"\n" + API.canonical(public) + b"\n")
    jobs_path = "artifacts/synthetic_review/planned_pilot_jobs.csv"
    order = (4, 3, 1, 2)
    (root / jobs_path).write_text("profile_id,planner_version,position_in_case,job_id\n" + "".join(
        API.PROFILE_ID + "," + str(v) + "," + str(i) + ",synthetic_prepared_v" + str(v) + "\n"
        for i, v in enumerate(order, 1)))
    config_path = "artifacts/synthetic_review/case_review_config.json"
    schema_path = "artifacts/synthetic_review/public_profile_schema.json"
    write(root / config_path, {"parent_preparation_files": {jobs_path: API.sha((root / jobs_path).read_bytes())}, "fixture_only": True})
    write(root / schema_path, {"type": "object", "fixture_only": True})
    review_files = {name: API.sha((root / name).read_bytes()) for name in (profile_path, config_path, schema_path)}
    identity = {"case_review_files": review_files, "public_record": original, "module_and_config_sha256": {},
        "case_review_id": "synthetic_review", "model_configuration": {"model": "offline-test-double", "fixture_only": True},
        "limits": {"maximum_generation_submissions": 15, "maximum_revisions_v4": 2}, "timing_policy": {"fixture_only": True}}
    digest = API.sha(API.canonical(identity))
    source = {**identity, "probe_id": "synthetic_earlier_probe", "manifest_id": digest,
        "case_review_config_path": config_path, "public_schema_path": schema_path, "jobs": []}
    manifest_path = "artifacts/pilot/synthetic_original_manifest.json"
    write(root / manifest_path, source)
    write(root / "results/pilot/probes/first_operational_probe.json", {"manifest_path": manifest_path, "manifest_id": digest})
    for relative in ("results/step31_first_probe_summary.json", "results/step31_shared_guidance_summary.json"):
        write(root / relative, {"old_result": "preserve these bytes", "fixture_only": True})
    evidence_path, contract_path = "results/synthetic_software.json", "artifacts/synthetic_contracts/contracts.json"
    write(root / evidence_path, {"passed": 1, "fixture_only": True})
    native = {"type": "object", "properties": {"response_type": {"const": "plan"},
        "food_facts": {"type": "array", "minItems": 1}}, "required": ["response_type", "food_facts"]}
    bundle = {"native_response_schema": native, "local_response_schema": deepcopy(native),
        "food_note_schema": {"type": "object"}, "policy": {"fixture_only": True}}
    write(root / contract_path, bundle)
    evidence = {"status": "passed", "passed": 1, "files": {evidence_path: API.sha((root / evidence_path).read_bytes())}, "fixture_only": True}
    prior = {"candidate_only": True, "new_runtime_executed": False, "new_model_calls": 0,
        "configuration_id": "synthetic_parent_contract", "input_sha256": {}, "component_sha256": {},
        "contract_files": {contract_path: API.sha((root / contract_path).read_bytes())}, "software_evidence": evidence,
        "fixture_only": True}
    write(root / "results/step31_response_contract_summary.json", prior)
    monkeypatch.setattr(API, "case_contracts", lambda *args: deepcopy(bundle))
    original_module = API.module
    monkeypatch.setattr(API, "module", lambda project, name: ADAPTER if name == "llm" else original_module(project, name))
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", lambda *a, **k: pytest.fail("Offline test attempted network transport"))
    manifest = API.prepare(root, environment_record={"fixture_only": True})
    return SimpleNamespace(root=root, manifest=manifest, software=evidence, public=public, bundle=bundle,
        order=order, contract_path=contract_path, profile_path=profile_path)


@pytest.fixture
def execution(saved):
    state = {"runtime_builds": 0, "http": [], "jobs": [], "references": [], "encoder_processes": 0,
        "public_inputs": [], "packets": [], "assessed": []}
    class Planner(DOUBLES.TestPlanner):
        def generate(self, public, *args):
            result = super().generate(public, *args)
            if self.version == 4 and state.get("fatal_v4"):
                return {**result, "completion_valid": False, "format_valid": False, "response_type": None,
                    "status": "failed", "terminal_state": "execution_error", "response": None,
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
            state["assessed"].append(deepcopy(outcome))
            return {"assessment_execution": "completed", "overall": "requirements_unverified", "fixture_only": True,
                "checks": [{"check_id": name, "status": "unknown", "required": True} for name in
                    ("requested_session_count", "food_answer_completeness", "food_numeric_correctness", "resource_requirements_evidence")]}
    def run(**kwargs):
        return API.execute(saved.root, saved.manifest, software_evidence=saved.software,
            runtime_factory=kwargs.pop("runtime_factory", runtime),
            references_factory=kwargs.pop("references_factory", DOUBLES.SavedReferences),
            trace_module=DOUBLES.tracing, assessor_factory=Assessor, emit=lambda text: None, **kwargs)
    return SimpleNamespace(saved=saved, state=state, runtime=runtime, Assessor=Assessor, run=run)


def test_prepare_preserves_original_inputs_and_fixed_fresh_balanced_case(saved):
    before = files(saved.root)
    value = API.prepare(saved.root, environment_record={"fixture_only": True})
    assert value == saved.manifest and files(saved.root) == before
    assert value["public_record"] == saved.public and value["public_record"]["input"]["age"] == 16
    assert [job["planner_version"] for job in value["jobs"]] == list(saved.order)
    assert value["limits"]["maximum_generation_submissions"] == 15
    assert value["parent_contract_configuration_id"] == "synthetic_parent_contract"
    assert value["output_repairs"] == value["automatic_retries"] == value["accepted_study_profiles"] == 0


def test_real_runner_redirects_old_summaries_and_whole_job_reuse_makes_zero_calls(execution):
    before = files(execution.saved.root)
    first = execution.run()
    state = deepcopy(execution.state)
    def forbidden(*args, **kwargs):
        pytest.fail("Verified whole-job reuse constructed another runtime or reference preparer")
    second = execution.run(runtime_factory=forbidden, references_factory=forbidden)
    assert first["new_model_submissions"] == 4 and second["new_model_submissions"] == 0
    assert second["saved_jobs_reused"] == 4
    assert execution.state["http"] == state["http"] and execution.state["encoder_processes"] == 3
    assert execution.state["jobs"] == list(execution.saved.order)
    assert execution.state["public_inputs"] == [execution.saved.public] * 4
    assert len(execution.state["packets"]) == 3  # Planner 1 receives no reference packet.
    assert all((execution.saved.root / relative).read_bytes() == data for relative, data in before.items())
    assert (execution.saved.root / API.GENERATION_SUMMARY).is_file()
    assert first["final_scores_computed"] is first["protocol_frozen"] is False


def test_designated_fatal_v4_is_assessed_without_earlier_draft_fallback(execution):
    execution.state["fatal_v4"] = True
    result = execution.run()
    outcome = next(value for value in execution.state["assessed"] if value["planner_version"] == 4)
    assert outcome["response"] is None and outcome["draft_result"]["response"] is not None
    assert outcome["terminal_state"] == "execution_error"
    assert all(report["assessment"]["overall"] == "requirements_unverified" for report in result["reports"])
    assert result["request_contract_native_evidence"]["semantic_correctness_established"] is False


@pytest.mark.parametrize("fault", ["public_input", "parent_contract", "software"])
def test_changed_inputs_contracts_and_software_block_before_calls(execution, fault):
    if fault == "public_input":
        execution.saved.manifest["public_record"]["input"]["age"] = 17
    elif fault == "parent_contract":
        path = execution.saved.root / execution.saved.contract_path
        path.write_bytes(path.read_bytes() + b" ")
    else:
        execution.saved.software["passed"] = 0
    with pytest.raises(ValueError):
        execution.run()
    assert execution.state["jobs"] == [] and execution.state["http"] == []


def test_partial_reference_failure_is_not_reported_as_completed(execution):
    execution.state["reference_failure"] = True
    result = execution.run()
    assert result["recorded_jobs"] == 1 and result["new_model_submissions"] == 0
    assert result["reports"] == [] and result["independent_assessment_completed"] is False
    assert result["request_contract_native_evidence"]["status"] == "unverified"


def test_native_observation_requires_preserved_wire_request_and_matching_reply(saved):
    value = {"response_type": "plan", "food_facts": [{"statement": "The requested nutrient value is unverified."}]}
    text = json.dumps(value)
    configuration = {"output_schema_sha256": API.sha(API.wire(saved.bundle["native_response_schema"])), "fixture_only": True}
    submitted = {"model": "offline-test-double", "format": deepcopy(saved.bundle["native_response_schema"]), "messages": []}
    outcome = {"call_id": "synthetic_native_final", "input_configuration": configuration,
        "request_sha256": API.sha(API.wire(submitted)),
        "response": {"model_output": {"raw_text": text}}, "fixture_only": True}
    path = "results/synthetic_designated_outcome.json"
    write(saved.root / path, outcome)
    folder = saved.root / "results/integration/model_calls/synthetic_native_final"
    # Production writes explicit wire bytes, preserving native schema property order.
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "request.json").write_bytes(API.wire({"request": submitted, "input_configuration": configuration}))
    write(folder / "backend_response.json", {"done": True, "done_reason": "stop", "eval_count": 10,
        "message": {"role": "assistant", "content": text}, "fixture_only": True})
    reports = [{"planner_version": 1, "outcome_path": path}]
    result = API.native_evidence(saved.root, reports, saved.bundle)
    assert result["designated_replies_with_candidate_native_evidence"] == 1
    assert result["per_planner"][0]["reply_conforms_to_candidate_native_schema"] is True
    assert result["native_chronology_or_unique_dates_guaranteed"] is False
    write(folder / "request.json", {"request": submitted, "input_configuration": configuration})
    assert API.native_evidence(saved.root, reports, saved.bundle)["designated_replies_with_candidate_native_evidence"] == 0
    configuration["output_schema_sha256"] = "0" * 64
    (folder / "request.json").write_bytes(API.wire({"request": submitted, "input_configuration": configuration}))
    assert API.native_evidence(saved.root, reports, saved.bundle)["designated_replies_with_candidate_native_evidence"] == 0


def test_default_runtime_router_uses_contract_factory_without_caller_injection(execution, monkeypatch):
    real_module = API.module
    received = []
    def modules(project, name):
        if name == "contract_runtime":
            def build(root, review, schema, *, public_record):
                received.append(deepcopy(public_record))
                return execution.runtime(root, review, schema)
            return SimpleNamespace(build_runtime=build)
        value = real_module(project, name)
        if name == "shared_guidance_probe":
            old_module = value.module
            def defaults(root, requested):
                if requested == "independent_plan_assessment":
                    return SimpleNamespace(IndependentAssessor=execution.Assessor)
                loaded = old_module(root, requested)
                if requested == "pilot_probe":
                    old_load = loaded.load_module
                    loaded.load_module = lambda root, requested: SimpleNamespace(FreshReferencePreparer=DOUBLES.SavedReferences) if requested == "pilot_references" else old_load(root, requested)
                return loaded
            value.module = defaults
        return value
    monkeypatch.setattr(API, "module", modules)
    result = API.execute(execution.saved.root, execution.saved.manifest, software_evidence=execution.saved.software, emit=lambda text: None)
    assert received == [execution.saved.public]
    assert result["injected_test_dependencies"] is False  # Caller supplied no production dependency override.
    assert result["new_model_submissions"] == 4


pytestmark = pytest.mark.requirement("31:request-contract-development-probe")
