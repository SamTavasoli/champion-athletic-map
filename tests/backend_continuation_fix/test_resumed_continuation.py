"""Keep the verified handoff repair inside the original unspent request budget."""

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = next((p for p in HERE.parents if (p / "src/champion_athletic_map/offline_corrections.py").is_file()),
            HERE.parent / "work_step30/project/folder-before-step-30")


def load(path, name):
    value = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    value.__spec__.loader.exec_module(value)
    return value


SOURCE = HERE / "resumed_continuation.py"
if not SOURCE.is_file():
    SOURCE = ROOT / "src/champion_athletic_map/resumed_continuation.py"
API = load(SOURCE, "verified_resumed_continuation_tested")
legacy_tests = ROOT / "tests/backend_continuation/test_saved_continuation.py"
if not legacy_tests.is_file():
    legacy_tests = HERE.parent / "work_step31_16/test_saved_continuation.py"
OLD = load(legacy_tests, "frozen_saved_continuation_fixture")


@pytest.fixture
def failed_attempt(tmp_path):
    root = OLD.project.__wrapped__(tmp_path)
    target = root / "src/champion_athletic_map/resumed_continuation.py"
    target.write_bytes(SOURCE.read_bytes())
    service = OLD.SoftwareServices(root, fault="first_payload")
    result = service.run()
    assert result["error"] == API.EXPECTED_ERROR
    assert result["new_model_submissions"] == 0 and not service.http_calls
    old_manifest = OLD.API.read(root / OLD.API.POINTERS["injected_test"])
    old_manifest = OLD.API.read(root / old_manifest["manifest_path"])
    folder = root / "results/pilot/saved_continuation" / old_manifest["continuation_id"]
    return root, old_manifest, folder


def test_new_handoff_preserves_verified_layout_and_does_not_change_failed_attempt(failed_attempt):
    root, old_manifest, old_folder = failed_attempt
    prior = {name: (old_folder / name).read_bytes() for name in ("outcome.json", "completed.json")}
    manifest = API.prepare(root, execution_mode="injected_test")
    source = OLD.API._load_source(root)
    table = API.verified_initial_table(root, source)
    assert table["columns"] == ["check_ids", "status", "required", "applicability", "reason", "observed"]
    assert len(table["findings"]) == 16
    assert manifest["manifest_id"] != old_manifest["manifest_id"]
    assert manifest["first_revision_payload_canonical_sha256"] == old_manifest["first_revision_payload_canonical_sha256"]
    assert any(path.endswith("zero_transport_proof.json") for path in manifest["source_bindings"])
    assert "src/champion_athletic_map/resumed_continuation.py" in manifest["source_bindings"]
    assert all((old_folder / name).read_bytes() == data for name, data in prior.items())


def test_repaired_lifecycle_spends_only_four_calls_and_verified_reuse_spends_none(failed_attempt):
    root, old_manifest, old_folder = failed_attempt
    old_outcome = (old_folder / "outcome.json").read_bytes()
    services = OLD.SoftwareServices(root)
    kwargs = {"software_evidence": OLD.evidence(root), "emit": lambda value: None,
        "runtime_factory": services.runtime,
        "confirmation_api": type("Confirmation", (), {"confirm_requests": staticmethod(services.confirmation)})(),
        "assessor_factory": services.assessor}
    result = API.execute(root, **kwargs)
    assert result["backend_requests_confirmed"] == 5
    assert result["new_model_submissions"] == 4 and result["original_plus_amended_model_submissions"] == 15
    assert services.events == ["confirm_five", "revision", "evaluator", "revision", "evaluator"]
    count = len(services.http_calls)
    repeated = API.execute(root, **kwargs)
    assert repeated["saved_execution_reused"] is True and repeated["new_model_submissions"] == 0
    assert len(services.http_calls) == count
    assert (old_folder / "outcome.json").read_bytes() == old_outcome


def test_complete_named_findings_cannot_change_during_layout_restoration(failed_attempt):
    root, _, _ = failed_attempt
    source = OLD.API._load_source(root)
    source["current"]["check_report"]["checks"][0]["reason"] += " Changed finding."
    with pytest.raises(ValueError, match="captured handoff differs"):
        API.verified_initial_table(root, source)


def test_sealed_attempt_with_nonzero_transport_cannot_receive_a_new_allowance(failed_attempt):
    root, _, folder = failed_attempt
    outcome_path, receipt_path = folder / "outcome.json", folder / "completed.json"
    outcome, receipt = OLD.API.read(outcome_path), OLD.API.read(receipt_path)
    outcome["trace"]["http_requests"] = 1
    outcome_path.write_bytes(OLD.API.canonical(outcome) + b"\n")
    receipt["files"][outcome_path.relative_to(root).as_posix()] = API.sha(outcome_path.read_bytes())
    receipt_path.write_bytes(OLD.API.canonical(receipt) + b"\n")
    with pytest.raises(ValueError, match="zero-request handoff failure"):
        API.prepare(root, execution_mode="injected_test")
    assert not (root / API.POINTERS["injected_test"]).exists()


def test_previous_native_call_directory_blocks_handoff_retry(failed_attempt):
    root, manifest, _ = failed_attempt
    (root / "results/integration/model_calls" / (manifest["call_prefix"] + "_revision1")).mkdir(parents=True)
    with pytest.raises(ValueError, match="native call directory"):
        API.prepare(root, execution_mode="injected_test")
    assert not (root / API.POINTERS["injected_test"]).exists()


def test_missing_previous_receipt_blocks_handoff_retry(failed_attempt):
    root, _, folder = failed_attempt
    (folder / "completed.json").unlink()
    with pytest.raises(ValueError, match="zero-transport receipt"):
        API.prepare(root, execution_mode="injected_test")


def test_receipt_must_bind_its_exact_terminal_outcome(failed_attempt):
    root, _, folder = failed_attempt
    path = folder / "completed.json"
    receipt = OLD.API.read(path)
    receipt["files"].pop((folder / "outcome.json").relative_to(root).as_posix())
    path.write_bytes(OLD.API.canonical(receipt) + b"\n")
    with pytest.raises(ValueError, match="does not bind its exact terminal outcome"):
        API.prepare(root, execution_mode="injected_test")


pytestmark = pytest.mark.requirement("31:verified-saved-handoff-continuation")
