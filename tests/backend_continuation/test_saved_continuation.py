"""Continue only the saved revision with explicit software dependencies.

The temporary source keeps the actual sixteen saved outcomes and reference
receipts. Its historical review configuration is an explicit software fixture;
no production configuration or model readiness is inferred from these tests.
"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest


HERE = Path(__file__).resolve().parent
ROOT = next((p for p in HERE.parents if (p / "src/champion_athletic_map/offline_corrections.py").is_file()),
            HERE.parent / "work_step30/project/folder-before-step-30")


def load(path, name):
    value = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    value.__spec__.loader.exec_module(value)
    return value


SOURCE = HERE / "saved_continuation.py"
if not SOURCE.is_file():
    SOURCE = ROOT / "src/champion_athletic_map/saved_continuation.py"
API = load(SOURCE, "saved_continuation_under_test")


def source_file(name):
    local = HERE / (name + ".py")
    return local if local.is_file() else ROOT / "src/champion_athletic_map" / (name + ".py")


@pytest.fixture
def project(tmp_path):
    parent = json.loads((ROOT / API.PARENT).read_bytes())
    names = set(parent["input_sha256"]) | set(parent["component_sha256"]) | {API.PARENT, parent["manifest_path"]}
    for row in parent["revision_measurements"]:
        names.update((row["candidate_request_path"], row["measurement_path"]))
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    shutil.copytree(ROOT / "src", tmp_path / "src", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("saved_continuation", "backend_confirmation"):
        (tmp_path / "src/champion_athletic_map" / (name + ".py")).write_bytes(source_file(name).read_bytes())

    original = json.loads((tmp_path / "results/step31_reviewed_probe_summary.json").read_bytes())
    case = next(c for c in original["cases"] if c["case_index"] == 13)
    report = next(r for r in case["reports"] if r["planner_version"] == 4)
    setup_directory = Path(report["outcome_path"]).parents[2] / "setup"
    shutil.copytree(ROOT / setup_directory, tmp_path / setup_directory, dirs_exist_ok=True)
    baseline = next(r for r in case["reports"] if r["planner_version"] == 1)
    response = json.loads((tmp_path / baseline["outcome_path"]).read_bytes())["response"]
    audit = response["audit"]
    public_record = {"profile_id": case["profile_id"], "schema_version": audit["profile_schema_version"],
                     "input": response["authoritative_public_input"]}
    paths = {"case_review_config_path": "artifacts/pilot/continuation_software_fixture/review_config.json",
             "public_schema_path": "artifacts/pilot/continuation_software_fixture/public_schema.json"}
    values = [{"explicit_software_fixture": True}, {"type": "object", "explicit_software_fixture": True}]
    packed = lambda value: (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    for name, value in zip(paths.values(), values):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(packed(value))
    for path in (tmp_path / setup_directory).glob("*.json"):
        value = API.read(path)
        value["runtime_manifest"]["review_config_sha256"] = API.sha(packed(values[0]))
        value["runtime_manifest"]["public_schema_sha256"] = API.sha(packed(values[1]))
        path.write_bytes(API.canonical(value) + b"\n")
    source_manifest = tmp_path / "artifacts/pilot/shared_guidance/continuation_software_fixture/probe_manifest.json"
    source_manifest.parent.mkdir(parents=True, exist_ok=True)
    source_manifest.write_bytes(API.canonical({"public_record": public_record, **paths}) + b"\n")
    return tmp_path


def evidence(root):
    path = root / "tests/continuation_software_fixture.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"explicit_test_dependencies":true}\n')
    return {"status": "passed", "passed": 1, "failed": 0, "not_completed": 0,
            "files": {path.relative_to(root).as_posix(): API.sha(path.read_bytes())}}


def test_source_handoff_and_frozen_manifest_retain_original_facts_and_all_five_requests(project):
    source = API._load_source(project)
    before = {name: (project / name).read_bytes() for name in source["bindings"]}
    manifest = API.prepare(project, execution_mode="injected_test")
    assert manifest["execution_mode"] == "injected_test"
    assert manifest["maximum_generation_submissions"] == 4
    assert manifest["maximum_revision_ordinal"] == 2
    assert manifest["output_tokens"] == {"revision": 2048, "evaluator": 768}
    assert manifest["public_record"] == source["selected"]["public_record"]
    assert manifest["reference_packet"] == source["selected"]["packet"]
    assert manifest["historical_reference_policy"] == source["historical_reference_policy"]
    assert len(manifest["backend_confirmation_requests"]) == 5
    assert manifest["first_revision_payload_canonical_sha256"] == API.sha(API.canonical(source["initial"]["new_candidate_request"]))
    assert manifest["original_outcomes_replaced"] is False
    assert API.prepare(project, execution_mode="injected_test") == manifest
    assert all((project / name).read_bytes() == value for name, value in before.items())


def test_changed_parent_observation_does_not_create_a_new_intent(project):
    manifest = API.prepare(project, execution_mode="injected_test")
    pointer = (project / API.POINTERS["injected_test"]).read_bytes()
    parent = API.read(project / API.PARENT)
    parent["software_evidence"]["passed"] += 1
    (project / API.PARENT).write_bytes(API.canonical(parent) + b"\n")
    with pytest.raises(ValueError, match="observation changed"):
        API.prepare(project, execution_mode="injected_test")
    assert (project / API.POINTERS["injected_test"]).read_bytes() == pointer
    assert (project / API.manifest_path(manifest)).is_file()


def test_changed_bound_original_is_rejected_before_backend_work(project):
    manifest = API.prepare(project, execution_mode="injected_test")
    source = API._load_source(project)
    path = project / source["selected"]["outcome_path"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="source changed"):
        API.validate_manifest(project, manifest)


def test_production_and_injected_preparations_have_distinct_frozen_identities(project):
    injected = API.prepare(project, execution_mode="injected_test")
    production = API.prepare(project, execution_mode="production")
    assert injected["manifest_id"] != production["manifest_id"]
    assert injected["call_prefix"] != production["call_prefix"]
    assert API.read(project / API.POINTERS["injected_test"])["manifest_id"] == injected["manifest_id"]
    assert API.read(project / API.POINTERS["production"])["manifest_id"] == production["manifest_id"]
    assert injected["reference_packet"] == production["reference_packet"]


class SoftwareServices:
    """Deliberate dependency doubles; the original PilotTrace records each call."""
    def __init__(self, root, *, accept=False, fault=None):
        self.root, self.accept, self.fault = root, accept, fault
        self.events, self.http_calls, self.interrupted = [], [], False
        self.confirmed = False
        self.source = API._load_source(root)
        self.payload = deepcopy(self.source["initial"]["new_candidate_request"])
        self.revision_reply = deepcopy(self.source["current"]["candidate"]["response"]["model_output"]["parsed_object"])

    def confirmation(self, root, manifest, requests, **kwargs):
        assert len(requests) == 5
        if not self.confirmed:
            assert not self.http_calls
            self.events.append("confirm_five")
            self.confirmed = True
        return {"all_five_confirmed": True, "confirmed_requests": 5,
                "generation_requests": 0, "new_render_requests": 0,
                "saved_confirmation_reused": bool(self.http_calls),
                "injected_test_dependencies": True}

    def assessor(self, root, schema):
        return SimpleNamespace(assess=lambda *args, **kwargs: {
            "assessment_execution": "completed", "overall": "requirements_violated",
            "checks": [{"check_id": "food_answer_completeness", "status": "violated"}],
            "explicit_software_fixture": True})

    def runtime(self, root, config, schema, *, public_record):
        owner = self
        class Client:
            input_schema = {"explicit_software_fixture": True}
            def generate(self, *args, **kwargs):
                raise AssertionError("Only the saved revision/evaluation roles may run")
            def _http(self, endpoint, payload=None, timeout=8, raw_path=None):
                assert endpoint == "/api/chat" and "_debug_render_only" not in payload
                owner.http_calls.append(deepcopy(payload))
                if owner.fault == "uncertain":
                    raise TimeoutError("Explicit test transport timeout")
                value = {"done": True, "model": "llama3.1:8b", "done_reason": "stop"}
                if raw_path is not None:
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_path.write_bytes(API.canonical(value))
                return value
        client = Client()
        class Roles:
            def __init__(self):
                self.client, self.reference_policy = client, {}
            def _http(self, *args, **kwargs):
                return self.client._http(*args, **kwargs)
            def prepare_request(self, *args, **kwargs):
                payload = deepcopy(owner.payload)
                stage = kwargs["stage"]
                if stage != "revision":
                    payload["messages"][0]["content"] = "Explicit software evaluator request"
                    payload["format"] = deepcopy(kwargs["output_schema"])
                    payload["options"]["num_predict"] = kwargs["output_tokens"]
                if owner.fault == "first_payload":
                    payload["messages"][0]["content"] += " changed"
                return {"public_input": deepcopy(public_record["input"]), "audit": {}}, payload, {"stage": stage}
            def generate(self, record, packet, instructions, call_id, **kwargs):
                _, payload, configuration = self.prepare_request(record, packet, instructions, **kwargs)
                folder = root / "results/integration/model_calls" / call_id
                previous = folder / "result.json"
                if previous.is_file():
                    saved_request = API.read(folder / "request.json")
                    assert saved_request == payload
                    return {**API.read(previous), "cached": True}
                folder.mkdir(parents=True)
                (folder / "request.json").write_bytes(API.canonical(payload))
                owner.events.append(kwargs["stage"])
                try:
                    client._http("/api/chat", payload, 120, folder / "backend_response.json")
                    status, complete = "returned", True
                except TimeoutError:
                    status, complete = "unresolved", False
                parsed = ({"assessment_complete": True, "issues": []} if kwargs["stage"] == "evaluator"
                          else deepcopy(owner.revision_reply))
                result = {"status": status, "completion_valid": complete, "format_valid": complete,
                    "response_type": parsed.get("response_type"), "call_id": call_id,
                    "request_sha256": API.sha(API.canonical(payload)), "input_configuration": configuration,
                    "saved_path": str(folder), "cached": False,
                    "response": {"authoritative_public_input": deepcopy(public_record["input"]),
                        "model_output": {"raw_text": API.canonical(parsed).decode("utf-8"),
                            "parsed_object": parsed, "parse_valid": True}}, "usage": {"eval_count": 1}}
                previous.write_bytes(API.canonical(result))
                if owner.fault == "interrupt_after_evaluator1" and call_id.endswith("_evaluator1") and not owner.interrupted:
                    owner.interrupted = True
                    raise KeyboardInterrupt("Explicit interruption after a conclusively saved role")
                return result
        roles = Roles()
        class Checker:
            def check(self, *args, **kwargs):
                report = deepcopy(owner.source["current"]["check_report"])
                for row in report["checks"]:
                    row["status"] = "met"
                if not owner.accept:
                    next(row for row in report["checks"] if row["check_id"] == "food_facts_numeric")["status"] = "violated"
                return report
        checks = self.source["current"]["check_report"]["checks"]
        policy = {"expected_check_ids": [r["check_id"] for r in checks],
                  "required_check_ids": [r["check_id"] for r in checks if r["required"]],
                  "allowed_evaluator_categories": ["software_fixture"],
                  "blocking_evaluator_categories": ["software_fixture"]}
        node = lambda: SimpleNamespace(client=client, config={"reference_policy": {}}, roles=roles)
        drafting = node()
        drafting.draft = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("No old drafting roles"))
        engine = SimpleNamespace(client=client, roles=roles, checker=Checker(), drafting=drafting,
            instructions="Explicit software fixture", prompts={"revision": "revise", "evaluator": "evaluate"},
            evaluator_schema={"type": "object"}, policy=policy, config={"maximum_revisions": 2})
        planners = {number: node() for number in range(1, 5)}
        planners[4].planner = engine
        self.engine = engine
        self.constructed_runtime = SimpleNamespace(planners=planners, reference_policy={},
            manifest={"explicit_software_fixture": True, "new_runtime_identity": "different_from_historical_policy"})
        return self.constructed_runtime

    def run(self):
        return API.execute(self.root, software_evidence=evidence(self.root), emit=lambda value: None,
            runtime_factory=self.runtime,
            confirmation_api=SimpleNamespace(confirm_requests=self.confirmation),
            assessor_factory=self.assessor)


def test_real_trace_runs_only_two_bounded_revisions_and_keeps_food_field_unfilled(project):
    services = SoftwareServices(project)
    source = services.source
    before = {name: (project / name).read_bytes() for name in source["bindings"]}
    result = services.run()
    assert services.events == ["confirm_five", "revision", "evaluator", "revision", "evaluator"]
    assert result["new_model_submissions"] == result["amended_model_submissions_total"] == 4
    assert result["original_plus_amended_model_submissions"] <= 15
    trace_identity = API.read(project / "results/pilot/saved_continuation" / result["continuation_id"] / "trace_identity.json")
    assert trace_identity["maximum_generation_submissions"] == 4
    assert result["terminal_state"] == "revision_limit_reached"
    assert result["internal_review"] == "needs review" and result["injected_test_dependencies"] is True
    assert result["result"]["response"]["model_output"]["parsed_object"]["food_facts"] == services.revision_reply["food_facts"]
    assert result["quality"]["food_complete"] == "violated"
    assert result["old_draft_roles_submitted"] == result["new_reference_encodings"] == 0
    assert result["original_results_changed"] is False and result["earlier_drafts_returned_as_fallback"] is False
    assert result["operational_generation_ready"] is False
    assert API.canonical(services.http_calls[0]) == API.canonical(source["initial"]["new_candidate_request"])
    assert services.engine.roles.reference_policy == source["historical_reference_policy"]
    assert services.constructed_runtime.manifest["historical_reference_hash_relabelled_as_new_runtime"] is False
    assert all((project / name).read_bytes() == value for name, value in before.items())
    assert not (project / API.POINTERS["production"]).exists()
    assert not (project / API.SUMMARY).exists()
    calls = len(services.http_calls)
    reused = services.run()
    assert reused["saved_execution_reused"] is True and reused["new_model_submissions"] == 0
    assert len(services.http_calls) == calls


def test_accepted_revision_stops_after_one_revision_and_one_evaluation(project):
    services = SoftwareServices(project, accept=True)
    result = services.run()
    assert result["terminal_state"] == "internally_accepted"
    assert result["new_model_submissions"] == 2
    assert services.events == ["confirm_five", "revision", "evaluator"]
    assert result["injected_test_dependencies"] is True
    assert result["quality"]["food_complete"] == "violated"
    assert result["operational_generation_ready"] is False


def test_first_payload_mismatch_prevents_confirmation_and_generation(project):
    services = SoftwareServices(project, fault="first_payload")
    result = services.run()
    assert result["terminal_state"] == "execution_error"
    assert result["backend_requests_confirmed"] == result["new_model_submissions"] == 0
    assert "first prepared revision differs" in result["error"]
    assert services.events == services.http_calls == []
    assert result["result"]["response"] is None


def test_ambiguous_generation_is_saved_and_never_automatically_repeated(project):
    services = SoftwareServices(project, fault="uncertain")
    result = services.run()
    assert result["new_model_submissions"] == 1
    assert result["result"]["status"] == "unresolved" and result["result"]["response"] is None
    assert result["earlier_drafts_returned_as_fallback"] is False
    assert (project / "results/integration/active_runtime/owner.json").is_file()
    reused = services.run()
    assert reused["saved_execution_reused"] is True and reused["new_model_submissions"] == 0
    assert len(services.http_calls) == 1


def test_completed_leaf_roles_resume_without_resubmission_after_interruption(project):
    services = SoftwareServices(project, fault="interrupt_after_evaluator1")
    with pytest.raises(KeyboardInterrupt):
        services.run()
    assert len(services.http_calls) == 2
    services.fault = None
    result = services.run()
    assert result["new_model_submissions"] == 2 and result["amended_model_submissions_total"] == 4
    assert result["saved_roles_reused"] == 2 and len(services.http_calls) == 4


def test_completed_receipt_rejects_a_changed_terminal_result(project):
    services = SoftwareServices(project)
    result = services.run()
    path = project / "results/pilot/saved_continuation" / result["continuation_id"] / "outcome.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="source changed"):
        services.run()


pytestmark = pytest.mark.requirement("31:bounded-saved-continuation")
