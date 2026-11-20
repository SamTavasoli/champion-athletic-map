"""Run the orchestration with saved transport doubles and the actual trace."""

from copy import deepcopy
import csv
import importlib.util
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


def module(name):
    path = ROOT / "src/champion_athletic_map" / (name + ".py")
    spec = importlib.util.spec_from_file_location("probe_test_" + name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


probe, tracing = module("pilot_probe"), module("pilot_trace")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(probe.canonical(value) + b"\n")


def make_manifest(root, order=(3, 4, 2, 1)):
    """A small declared test configuration, not fabricated runtime evidence."""
    config_path, schema_path = "artifacts/test-review/config.json", "artifacts/test-review/schema.json"
    write(root / config_path, {"fixture_only": True})
    write(root / schema_path, {"type": "object", "fixture_only": True})
    public = {"profile_id": "fictional-probe-profile", "schema_version": "athlete-profile-input-2",
        "input": {"age": 13, "athlete_request": "Plan basketball sessions.", "food_question": "A recorded food fact?"}}
    return {"probe_id": "test_operational_probe", "manifest_id": "b" * 64,
        "public_record": public, "public_record_sha256": probe.sha(probe.canonical(public)),
        "module_and_config_sha256": {},
        "case_review_files": {path: probe.sha((root / path).read_bytes()) for path in (config_path, schema_path)},
        "case_review_config_path": config_path, "public_schema_path": schema_path,
        "jobs": [{"job_id": "probe_test_v" + str(version), "call_id": "probe_test_v" + str(version),
            "planner_version": version, "position_in_case": number}
            for number, version in enumerate(order, 1)]}


class SavedLeafClient:
    """Persist the same request/result/active marker shape as a native adapter."""
    def __init__(self, root, state, version):
        self.root, self.state, self.version = root, state, version

    def _http(self, endpoint, payload=None, timeout=8, raw_path=None):
        self.state["http"].append({"version": self.version, "endpoint": endpoint, "payload": deepcopy(payload)})
        if (self.state.get("timeout_version") == self.version and endpoint == "/api/chat"
                and payload.get("_debug_render_only") is not True):
            raise TimeoutError("The test generation outcome is uncertain.")
        response = {"done": True, "done_reason": "stop", "model": "offline-test-double",
            "message": {"role": "assistant", "content": "{}"}, "eval_count": 20, "prompt_eval_count": 100}
        if raw_path is not None:
            write(Path(raw_path), response)
        return response

    def generate(self, public, instructions, call_id):
        folder = self.root / "results/integration/model_calls" / call_id
        request = {"model": "offline-test-double", "messages": [public, instructions], "stream": False}
        request_sha = probe.sha(probe.canonical(request))
        if (folder / "result.json").is_file():
            previous = json.loads((folder / "result.json").read_bytes())
            if previous["request_sha256"] != request_sha:
                raise ValueError("This call ID belongs to a different request.")
            return {**previous, "cached": True}
        folder.mkdir(parents=True, exist_ok=False)
        write(folder / "request.json", {"request": request, "input_audit": {"fixture_only": True}})
        active = folder.parent / "active_call"
        active.mkdir()
        write(active / "owner.json", {"call_id": call_id, "request_sha256": request_sha})
        try:
            self._http("/api/version")
            self._http("/api/show", {"model": "offline-test-double"})
            self._http("/api/chat", {**request, "_debug_render_only": True}, 60, folder / "render_response.json")
            write(folder / "generation_pending.json", {"call_id": call_id})
            self._http("/api/chat", request, 120, folder / "backend_response.json")
            weak = self.state.get("weak_version") == self.version
            result = {"status": "failed" if weak else "returned", "call_id": call_id,
                "request_sha256": request_sha, "cached": False, "completion_valid": True,
                "format_valid": not weak, "response_type": "plan",
                "response": {"model_output": {"parsed_object": {"response_type": "plan", "explanation": "Saved test output."}}},
                "usage": {"prompt_eval_count": 100, "eval_count": 20}, "saved_path": str(folder)}
        except TimeoutError as error:
            result = {"status": "unresolved", "call_id": call_id, "request_sha256": request_sha,
                "cached": False, "completion_valid": False, "format_valid": False, "usage": {}, "error": str(error)}
        write(folder / "result.json", result)
        if result["status"] != "unresolved":
            (active / "owner.json").unlink()
            active.rmdir()
        return result


class TestPlanner:
    __test__ = False

    def __init__(self, root, state, version):
        self.state, self.version = state, version
        self.client = SavedLeafClient(root, state, version)

    def generate(self, public, *args):
        call_id = args[-1]
        self.state["jobs"].append(self.version)
        self.state["public_inputs"].append(deepcopy(public))
        if self.version != 1:
            self.state["packets"].append(deepcopy(args[0]))
        return {**self.client.generate(public, "Our test task", call_id), "planner_version": self.version,
            "terminal_state": "revision_limit_reached" if self.version == 4 else "completed", "revisions_used": 0}


class SavedReferences:
    def __init__(self, root, tools, client, policy):
        self.root, self.state = root, tools.state
        self.setup_record = {"fixture_only": True, "query_encoder_processes": 0}

    def prepare(self, public, work, *, job_id, configuration_id, expected_packet_id=None):
        minimal = {"manifest_id": configuration_id, "public_record": public}
        if work.exists():
            return probe.saved_references(self.root, work, minimal)
        self.state["references"].append(job_id)
        work.mkdir(parents=True)
        request = {"public_record": deepcopy(public), "configuration_id": configuration_id, "job_id": job_id,
            "fixture_only": True}
        write(work / "request.json", request)
        if self.state.get("reference_failure"):
            write(work / "failure.json", {"failed_stage": "test_reference_preparation", "encoder_api_invoked": False})
            raise RuntimeError("The declared test reference preparation failed.")
        self.state["encoder_processes"] += 1
        packet = {"packet_id": "same-canonical-test-packet", "payload": {
            "references": [{"reference_unit_id": "test-reference", "complete_required_delivery_text": "Complete test reference."}],
            "food_lookup": []}}
        if expected_packet_id is not None:
            assert packet["packet_id"] == expected_packet_id
        reference_trace = {"job_id": job_id, "packet_id": packet["packet_id"], "fixture_only": True}
        write(work / "packet.json", packet)
        write(work / "trace.json", reference_trace)
        counts = {"query_encoder_processes": 1, "query_rows_encoded": 2, "ranking_calls": 2}
        completion = {"configuration_id": configuration_id, "job_id": job_id,
            "request_sha256": probe.sha(probe.canonical(request)), "packet_id": packet["packet_id"],
            "preparation_seconds": 0.125, "counts": counts,
            "artifact_sha256": {name: probe.sha((work / name).read_bytes()) for name in
                ("request.json", "packet.json", "trace.json")}}
        completion["completion_record_sha256"] = probe.sha(probe.canonical(completion))
        write(work / "completed.json", completion)
        value = probe.saved_references(self.root, work, minimal)
        return {**value, "cache_reused": False, "new_counts": counts}


@pytest.fixture
def execution(tmp_path):
    state = {"runtime_builds": 0, "http": [], "jobs": [], "references": [],
        "encoder_processes": 0, "public_inputs": [], "packets": []}
    manifest = make_manifest(tmp_path)
    def runtime_factory(root, config, schema):
        state["runtime_builds"] += 1
        return SimpleNamespace(planners={version: TestPlanner(root, state, version) for version in range(1, 5)},
            tools=SimpleNamespace(state=state), reference_policy={"fixture_only": True}, manifest={"fixture_only": True})
    def execute(**kwargs):
        return probe.execute_probe(tmp_path, manifest, runtime_factory=runtime_factory,
            references_factory=SavedReferences, trace_module=tracing, emit=lambda line: None, **kwargs)
    return SimpleNamespace(root=tmp_path, manifest=manifest, state=state, execute=execute)


def fail_if_runtime_needed(*args, **kwargs):
    raise AssertionError("Verified whole-job reuse must not load runtime or encode references.")


def reuse_only(execution):
    return probe.execute_probe(execution.root, execution.manifest, runtime_factory=fail_if_runtime_needed,
        references_factory=fail_if_runtime_needed, trace_module=tracing, emit=lambda line: None)


def job_folder(execution, version):
    return execution.root / "results/pilot/probes" / execution.manifest["probe_id"] / "jobs" / ("probe_test_v" + str(version))


def test_four_matched_jobs_keep_prepared_order_and_pay_for_three_fresh_packets(execution):
    result = execution.execute()
    assert execution.state["jobs"] == [3, 4, 2, 1]
    assert [row["planner_version"] for row in result["jobs"]] == [3, 4, 2, 1]
    assert execution.state["public_inputs"] == [execution.manifest["public_record"]] * 4
    assert len(execution.state["references"]) == execution.state["encoder_processes"] == 3
    assert len(execution.state["packets"]) == 3 and all(packet == execution.state["packets"][0] for packet in execution.state["packets"])
    assert result["new_reference_encoder_processes"] == 3
    assert result["new_generation_transport_attempts"] == result["new_render_transport_attempts"] == 4
    assert result["new_metadata_transport_attempts"] == 8
    assert result["cumulative_trace"]["unique_recorded_roles"] == 4
    assert result["independent_quality_assessment"] == "pending" and not result["protocol_frozen"]
    assert not result["representative_pilot_completed"] and not result["operational_generation_ready"]
    assert result["accepted_study_profiles"] == 0
    assert all(not (execution.root / name).exists() for name in tracing._GATE_MARKERS)


def test_whole_job_rerun_loads_no_runtime_and_makes_no_transport_or_encoder_work(execution):
    first = execution.execute()
    before = deepcopy(execution.state)
    second = reuse_only(execution)
    assert execution.state == before
    assert second["whole_jobs_reused_this_execution"] == 4
    assert second["new_generation_transport_attempts"] == second["new_render_transport_attempts"] == 0
    assert second["new_metadata_transport_attempts"] == second["new_reference_encoder_processes"] == 0
    assert second["setup_this_execution"]["status"] == "not_needed_for_whole_job_reuse"
    assert second["cumulative_trace"] == first["cumulative_trace"]


@pytest.mark.parametrize("changed", ["outcome", "reference", "record"])
def test_changed_completed_evidence_is_preserved_and_blocks_reuse(execution, changed):
    execution.execute()
    folder = job_folder(execution, 3)
    path = (folder / "outcome.json" if changed == "outcome" else folder / "job_record.json" if changed == "record"
        else folder.parents[1] / "references/probe_test_v3/packet.json")
    value = json.loads(path.read_bytes())
    value["unexpected_change"] = True
    write(path, value)
    changed_bytes, before = path.read_bytes(), deepcopy(execution.state)
    with pytest.raises(ValueError, match="changed|differs"):
        reuse_only(execution)
    assert path.read_bytes() == changed_bytes and execution.state == before


def test_terminal_outcome_recovers_missing_job_record_without_loading_runtime(execution):
    execution.execute()
    folder = job_folder(execution, 3)
    outcome = (folder / "outcome.json").read_bytes()
    (folder / "job_record.json").unlink()
    before = deepcopy(execution.state)
    result = reuse_only(execution)
    recovered = result["jobs"][0]
    assert recovered["recovered_from_saved_outcome"] and recovered["prior_attempt_interrupted"]
    assert recovered["elapsed_seconds"] is None
    assert result["whole_jobs_reused_this_execution"] == 4 and result["new_generation_transport_attempts"] == 0
    assert result["new_reference_encoder_processes"] == 0
    assert (folder / "outcome.json").read_bytes() == outcome and execution.state == before


def test_uncertain_generation_stops_probe_and_retains_owned_markers(execution):
    execution.state["timeout_version"] = 3
    result = execution.execute()
    assert result["stop_reason"] == "unresolved_backend_outcome" and result["recorded_probe_jobs"] == 1
    assert execution.state["jobs"] == [3] and len(execution.state["references"]) == 1
    assert result["new_generation_transport_attempts"] == 1
    for relative in tracing._GATE_MARKERS + tracing._BACKEND_MARKERS[:1]:
        assert (execution.root / relative).is_dir()
    before = deepcopy(execution.state)
    with pytest.raises(tracing.UncertainProbe):
        reuse_only(execution)
    assert execution.state == before


def test_completed_weak_response_is_retained_while_other_versions_run(execution):
    execution.state["weak_version"] = 3
    result = execution.execute()
    assert result["recorded_probe_jobs"] == 4 and not result["stop_reason"]
    assert result["responses_with_valid_format"] == 3 and result["jobs"][0]["outcome"]["status"] == "failed"
    outcome = (job_folder(execution, 3) / "outcome.json").read_bytes()
    repeated = reuse_only(execution)
    assert repeated["new_generation_transport_attempts"] == 0
    assert repeated["jobs"][0]["outcome"]["status"] == "failed"
    assert (job_folder(execution, 3) / "outcome.json").read_bytes() == outcome


def test_reference_failure_stops_before_generation_and_is_not_reencoded(execution):
    execution.state["reference_failure"] = True
    result = execution.execute()
    assert result["stop_reason"] == "reference_preparation_needs_attention"
    assert result["recorded_probe_jobs"] == 1 and result["new_generation_transport_attempts"] == 0
    assert not execution.state["jobs"] and len(execution.state["references"]) == 1
    assert execution.state["encoder_processes"] == 0
    before = deepcopy(execution.state)
    repeated = reuse_only(execution)
    assert repeated["whole_jobs_reused_this_execution"] == 1 and execution.state == before
    assert repeated["stop_reason"] == "reference_preparation_needs_attention"


@pytest.fixture
def reviewed(tmp_path):
    old_path = ROOT / "tests/pilot_case_review/test_pilot_case_review.py"
    spec = importlib.util.spec_from_file_location("probe_previous_case_review_fixtures", old_path)
    previous_tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous_tests)
    root, selected, _ = previous_tests.prepared.__wrapped__(tmp_path)
    # All observations here are explicitly synthetic test evidence.
    report = root / "results/test-only-software-evidence.json"
    write(report, {"fixture_only": True, "not_a_runtime_or_human_review": True})
    evidence = {"status": "passed", "passed": 1, "fixture_only": True,
        "files": {report.relative_to(root).as_posix(): probe.sha(report.read_bytes())}}
    previous_tests.review.prepare(root, software_evidence=evidence)
    for name in ("pilot_probe", "pilot_trace", "pilot_runtime", "pilot_references"):
        source = ROOT / "src/champion_athletic_map" / (name + ".py")
        if not source.is_file():
            source = Path(__file__).with_name(name + ".py")
        shutil.copyfile(source, root / "src/champion_athletic_map" / source.name)
    for name in ("version1_config", "version2_config", "version3_config", "version4_config",
            "version4_candidate_focused_config", "shared_reference_source_config"):
        write(root / "artifacts/planners" / (name + ".json"), {"fixture_only": True, "name": name})
    write(root / "artifacts/language_model/integration_config.json", {"fixture_only": True,
        "model": "offline-test-double", "timeouts_seconds": {"metadata": 8, "render": 60, "generation": 120}})
    return root, selected


def test_preparation_keeps_one_public_case_original_order_and_stable_identity(reviewed):
    root, _ = reviewed
    env = {"fixture_only": True, "python": "recorded-test-environment"}
    manifest = probe.prepare_probe(root, environment_record=env)
    assert probe.prepare_probe(root, environment_record=env) == manifest
    public = manifest["public_record"]
    assert set(public) == {"profile_id", "schema_version", "input"}
    assert public["schema_version"] == "athlete-profile-input-2" and public["input"]["age"] == 13
    assert public["input"]["food_question"] and public["input"]["space"]["court_access"] == "full_court"
    forbidden = {"scenario_intent", "expected_behavior", "witness", "family_id", "review_disposition"}
    assert not (set(public) | set(public["input"])) & forbidden
    config = json.loads((root / manifest["case_review_config_path"]).read_bytes())
    original_path = next(name for name in config["parent_preparation_files"] if name.endswith("/planned_pilot_jobs.csv"))
    original = [row for row in csv.DictReader(io.StringIO((root / original_path).read_text(encoding="utf-8")))
        if row["profile_id"] == public["profile_id"]]
    original.sort(key=lambda row: int(row["position_in_case"]))
    assert [row["planner_version"] for row in manifest["jobs"]] == [int(row["planner_version"]) for row in original]
    assert len(manifest["jobs"]) == 4 and manifest["limits"]["maximum_generation_submissions"] == 15
    assert manifest["accepted_study_profiles"] == 0 and not manifest["protocol_frozen"]


def test_changed_probe_configuration_requires_explicit_amendment(reviewed):
    root, _ = reviewed
    env = {"fixture_only": True}
    first = probe.prepare_probe(root, environment_record=env)
    pointer = root / "results/pilot/probes/first_operational_probe.json"
    before = pointer.read_bytes()
    integration = root / "artifacts/language_model/integration_config.json"
    changed = json.loads(integration.read_bytes())
    changed["model"] = "different-test-configuration"
    write(integration, changed)
    with pytest.raises(ValueError, match="explicit amendment"):
        probe.prepare_probe(root, environment_record=env)
    assert pointer.read_bytes() == before
    original_manifest = root / json.loads(before)["manifest_path"]
    assert json.loads(original_manifest.read_bytes()) == first


pytestmark = pytest.mark.requirement("31:bounded-probe-orchestration")

pytestmark = pytest.mark.requirement("31:bounded-operational-probe")
