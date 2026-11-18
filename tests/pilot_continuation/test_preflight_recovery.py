"""Exercise the one zero-call recovery and refuse any submitted/unknown state."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


PATH = Path(__file__).resolve().parents[2] / "src/champion_athletic_map/preflight_recovery.py"
spec = importlib.util.spec_from_file_location("preflight_recovery_tests", PATH)
API = importlib.util.module_from_spec(spec)
spec.loader.exec_module(API)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(API.canonical(value) + b"\n")


def manifest(root, components, *, extra=None):
    identity = {"schema_version": "saved-continuation-software-fixture", "amendment_component_sha256": components,
        "maximum_new_generation_submissions": 2, "maximum_total_original_and_amended_submissions": 15,
        "scope": "Only blocked revision2 and evaluator2", **(extra or {})}
    digest = API.sha(API.canonical(identity))
    value = {**identity, "manifest_id": digest, "amendment_id": "continuation_" + digest[:20],
        "call_prefix": "p31c_" + digest[:16]}
    relative = "artifacts/pilot/continuations/" + value["amendment_id"] + "/manifest.json"
    write(root / relative, value)
    write(root / API.POINTER, {"manifest_id": digest, "manifest_path": relative})
    return value


@pytest.fixture
def fixture(tmp_path):
    old, replacement = {}, {}
    for name in ("review_encoding", "continuation_runtime", "pilot_continuation"):
        relative = "src/champion_athletic_map/" + name + ".py"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("# saved old " + name + "\n").encode())
        old[relative] = API.sha(path.read_bytes())
        replacement[relative] = API.sha(("# declared replacement " + name + "\n").encode())
    value = manifest(tmp_path, old)
    folder = tmp_path / "results/pilot/continuations" / value["amendment_id"]
    write(folder / "trace_identity.json", {"manifest_id": value["manifest_id"], "maximum_generation_submissions": 2})
    (folder / "http_events.jsonl").write_bytes(b"")
    (folder / "stage_events.jsonl").write_bytes(b"")
    def run():
        return API.recover_preflight(tmp_path, old_component_sha256=old, replacement_component_sha256=replacement)
    return SimpleNamespace(root=tmp_path, old=old, replacement=replacement, manifest=value, folder=folder, run=run)


def all_bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_archive_preserves_exact_pointer_manifest_sources_and_trace(fixture):
    item = fixture
    before = all_bytes(item.root)
    result = item.run()
    assert result["status"] == "recovered" and result["old_model_submissions"] == 0
    assert not (item.root / API.POINTER).exists()
    archived_pointer = item.root / result["archived_pointer_path"]
    assert archived_pointer.read_bytes() == before[API.POINTER]
    for relative, data in before.items():
        if relative != API.POINTER:
            assert (item.root / relative).read_bytes() == data
    assert result["replacement_maximum_new_generation_submissions"] == 2
    assert result["original_manifest_and_trace_preserved"] is True


def test_recovery_is_idempotent_before_and_after_declared_source_upgrade(fixture):
    first = fixture.run()
    after = all_bytes(fixture.root)
    assert fixture.run()["status"] == "already_recovered"
    assert all_bytes(fixture.root) == after
    for relative in fixture.replacement:
        name = Path(relative).stem
        (fixture.root / relative).write_bytes(("# declared replacement " + name + "\n").encode())
    upgraded = all_bytes(fixture.root)
    assert fixture.run()["status"] == "already_recovered"
    assert all_bytes(fixture.root) == upgraded


def test_replacement_pointer_and_its_completed_or_pending_work_are_never_cleared(fixture):
    fixture.run()
    new = manifest(fixture.root, fixture.replacement)
    work = fixture.root / "results/pilot/continuations" / new["amendment_id"]
    write(work / "attempt_started.json", {"manifest_id": new["manifest_id"]})
    write(work / "completed.json", {"preserve": True})
    native = fixture.root / "results/integration/model_calls" / (new["call_prefix"] + "_revision2")
    write(native / "request.json", {"new": True})
    before = all_bytes(fixture.root)
    result = fixture.run()
    assert result["status"] == "not_needed_replacement_amendment" and result["pointer_preserved"]
    assert all_bytes(fixture.root) == before


@pytest.mark.parametrize("name", ["attempt_started.json", "outcome.json", "completed.json", "runtime_manifest.json", "unknown.json"])
def test_any_old_execution_or_unknown_artifact_blocks(fixture, name):
    write(fixture.folder / name, {"existing": True})
    before = all_bytes(fixture.root)
    with pytest.raises(ValueError, match="not a zero-call"):
        fixture.run()
    assert all_bytes(fixture.root) == before


@pytest.mark.parametrize("name", ["http_events.jsonl", "stage_events.jsonl"])
def test_any_old_http_or_stage_event_blocks(fixture, name):
    (fixture.folder / name).write_bytes(b'{"event":"started"}\n')
    before = all_bytes(fixture.root)
    with pytest.raises(ValueError, match="not a zero-call"):
        fixture.run()
    assert all_bytes(fixture.root) == before


def test_even_an_empty_old_request_directory_blocks(fixture):
    (fixture.folder / "http_requests").mkdir()
    with pytest.raises(ValueError, match="not a zero-call"):
        fixture.run()
    assert (fixture.root / API.POINTER).is_file()


def test_any_native_call_prefix_folder_blocks(fixture):
    native = fixture.root / "results/integration/model_calls" / (fixture.manifest["call_prefix"] + "_revision2")
    native.mkdir(parents=True)
    with pytest.raises(ValueError, match="not a zero-call"):
        fixture.run()
    assert native.is_dir() and (fixture.root / API.POINTER).is_file()


@pytest.mark.parametrize("relative", API._MARKERS)
def test_active_global_or_app_markers_block(fixture, relative):
    (fixture.root / relative).mkdir(parents=True)
    before = all_bytes(fixture.root)
    with pytest.raises(ValueError, match="runtime marker"):
        fixture.run()
    assert all_bytes(fixture.root) == before
    assert (fixture.root / relative).is_dir()


@pytest.mark.parametrize("change", ["old_source", "manifest_digest", "pointer_identity", "other_components", "trace_identity", "scope"])
def test_unknown_sources_identities_or_scope_block(fixture, change):
    item = fixture
    pointer = item.root / API.POINTER
    if change == "old_source":
        (item.root / next(iter(item.old))).write_bytes(b"# unexpected source\n")
    elif change == "manifest_digest":
        value = json.loads(pointer.read_bytes())
        path = item.root / value["manifest_path"]
        data = json.loads(path.read_bytes())
        data["scope"] = "changed"
        write(path, data)
    elif change == "pointer_identity":
        value = json.loads(pointer.read_bytes())
        value["manifest_id"] = "f"*64
        write(pointer, value)
    elif change == "other_components":
        manifest(item.root, {**item.old, next(iter(item.old)): "f"*64})
    elif change == "trace_identity":
        write(item.folder / "trace_identity.json", {"manifest_id": "other", "maximum_generation_submissions": 2})
    else:
        manifest(item.root, item.old, extra={"maximum_new_generation_submissions": 3})
    before = all_bytes(item.root)
    with pytest.raises(ValueError):
        item.run()
    assert all_bytes(item.root) == before


def test_changed_archive_or_preserved_old_trace_blocks_idempotent_recovery(fixture):
    result = fixture.run()
    archived = fixture.root / result["archived_pointer_path"]
    archived.write_bytes(archived.read_bytes() + b" ")
    with pytest.raises(ValueError, match="archive changed"):
        fixture.run()


def test_no_pointer_and_no_matching_recovery_needs_no_change(fixture):
    (fixture.root / API.POINTER).unlink()
    before = all_bytes(fixture.root)
    assert fixture.run() == {"status": "not_needed_no_pointer"}
    assert all_bytes(fixture.root) == before

pytestmark = pytest.mark.requirement("31:zero-call-preflight-recovery")
