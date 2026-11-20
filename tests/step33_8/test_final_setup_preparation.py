"""We check setup boundaries without submitting a model request."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from champion_athletic_map import final_setup_preparation as setup
from champion_athletic_map import common_response_preparation as common
from champion_athletic_map import llm


def client():
    value = llm.OllamaClient.__new__(llm.OllamaClient)
    value.native = {"template": "Fictional software template."}
    value.calls = []
    def http(endpoint, payload=None, timeout=8, raw_path=None):
        value.calls.append(endpoint)
        response = {"/api/version": {"version": "0.40.16"},
            "/api/tags": {"models": [{"name": setup.MODEL, "digest": setup.DIGEST,
                "details": {"quantization_level": "Q4_K_M"}}]},
            "/api/show": {"template": value.native["template"]}}[endpoint]
        if raw_path is not None:
            raw_path.write_text(json.dumps(response), encoding="utf-8")
        return response
    value._http = http
    return value


def test_existing_model_identity_code_uses_three_metadata_calls_only(tmp_path):
    model = client()
    original = model._http
    report = setup.metadata_only_identity(model, tmp_path / "metadata")
    assert report["status"] == "matched"
    assert model.calls == ["/api/version", "/api/tags", "/api/show"]
    assert report["generation_requests"] == report["render_only_requests"] == 0
    assert report["all_final_request_budgets_verified"] is False
    assert model._http is original


def test_chat_is_rejected_before_any_transport(tmp_path):
    model = client()
    model._identity = lambda: model._http("/api/chat", {"model": setup.MODEL})
    original = model._http
    report = setup.metadata_only_identity(model, tmp_path / "metadata")
    assert report["status"] == "needs_attention"
    assert model.calls == []
    assert model._http is original


def test_unexpected_show_payload_is_rejected(tmp_path):
    model = client()
    def identity():
        model._http("/api/version")
        model._http("/api/tags")
        return model._http("/api/show", {"model": "another-model"})
    model._identity = identity
    assert setup.metadata_only_identity(model, tmp_path / "metadata")["status"] == "needs_attention"
    assert model.calls == ["/api/version", "/api/tags"]


def test_changed_model_is_not_retried_or_accepted(tmp_path):
    model = client()
    original = model._http
    def changed(endpoint, *args):
        value = original(endpoint, *args)
        if endpoint == "/api/tags":
            value["models"][0]["digest"] = "changed-digest"
        return value
    model._http = changed
    report = setup.metadata_only_identity(model, tmp_path / "metadata")
    assert report["status"] == "needs_attention"
    assert model.calls == ["/api/version", "/api/tags"]


def protocol_inputs():
    return ({"summary": {"case_freeze_id": "software-freeze"},
             "settings": {"settings_id": "software-settings"}, "contracts": {"contracts_id": "software-contracts"}},
        {"summary": {"preparation_id": "software-common"}},
        {"summary": {"sample_chosen_before_final_outputs": True}}, {},
        {"native_runtime_graphs_verified": True, "frozen_public_bindings_verified": 200,
         "representative_runtime_graphs_verified": 2}, {"status": "matched"}, {})


def test_software_fixture_never_freezes_native_protocol():
    result = setup.make_protocol(*protocol_inputs(), software_fixture=True)
    assert result["final_protocol_frozen"] is False
    assert result["final_execution_started"] is False


def test_backend_mismatch_keeps_protocol_pending():
    args = list(protocol_inputs())
    args[5] = {"status": "needs_attention"}
    assert setup.make_protocol(*args)["final_protocol_frozen"] is False


def test_unselected_review_sample_keeps_protocol_pending():
    args = list(protocol_inputs())
    args[2] = {"summary": {"sample_chosen_before_final_outputs": False}}
    assert setup.make_protocol(*args)["final_protocol_frozen"] is False


def test_model_metadata_does_not_establish_all_case_budgets_or_goal_quality():
    result = setup.make_protocol(*protocol_inputs())
    assert result["all_final_request_budgets_verified"] is False
    assert result["complete_final_reference_packets_prepared"] is False
    assert result["goal_semantic_verification_implemented"] is False
    assert result["full_verification_metric_definition_changed"] is False
    assert result["actual_response_ratings"] == 0


def test_common_summary_path_remains_the_summary_not_the_last_dependency(tmp_path):
    relative = "results/testing/step33_7_common_checks_fixture_summary.json"
    folder = tmp_path / "results/testing/common"
    folder.mkdir(parents=True)
    dependency = tmp_path / "source.txt"
    dependency.write_bytes(b"source")
    config = {"source_file_sha256": {"source.txt": setup.sha(b"source")}}
    summary = {"software_fixture": True, "case_freeze_id": "software-freeze", "contracts_bound": 200,
        "assessed_final_jobs": 0, "package_directory": "results/testing/common",
        "preparation_id": setup.sha(setup.packed(config))}
    (tmp_path / relative).write_bytes(setup.packed(summary))
    (folder / "common_checker_configuration.json").write_bytes(setup.packed(config))
    (folder / "initial_score_ledger.jsonl").write_bytes(b"")
    api = SimpleNamespace(read_json=common.read_json, safe_path=common.safe_path,
        pending_ledger=lambda _freeze: [], compact=common.compact)
    result = setup.load_common(tmp_path, {"summary": {"case_freeze_id": "software-freeze"}}, api,
                               software_fixture=True)
    assert result["summary_path"] == relative
    assert result["summary_sha256"] == setup.sha((tmp_path / relative).read_bytes())


def test_started_final_run_cannot_be_replaced_by_rerunning_setup(tmp_path):
    root = tmp_path
    summary = root / "results/step33_final_run_setup_summary.json"
    manifest = root / "results/final-run/manifest.json"
    started = manifest.parent / "cases/case_001/started.json"
    started.parent.mkdir(parents=True)
    started.write_text("{}\n")
    manifest.write_bytes(setup.packed({"package_directory": "results/final-run"}))
    summary.write_bytes(setup.packed({"run_manifest_path": "results/final-run/manifest.json"}))
    original = summary.read_bytes()
    with pytest.raises(ValueError, match="already started"):
        setup.preserve_started_run(root, common)
    assert summary.read_bytes() == original


def test_unstarted_setup_can_be_checked_again(tmp_path):
    folder = tmp_path / "results/final-run"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_bytes(setup.packed({"package_directory": "results/final-run"}))
    (tmp_path / "results/step33_final_run_setup_summary.json").write_bytes(
        setup.packed({"run_manifest_path": "results/final-run/manifest.json"}))
    setup.preserve_started_run(tmp_path, common)
