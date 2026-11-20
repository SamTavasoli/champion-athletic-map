"""Retire only a verified zero-call continuation preflight, preserving its evidence."""

import hashlib
import json
import os
from pathlib import Path
import re


VERSION = "continuation-zero-call-preflight-recovery-1"
POINTER = "results/pilot/continuations/blocked_revision2_amendment.json"
ARCHIVES = "results/pilot/continuation_preflight_recoveries"
_MARKERS = ("results/app/active_model_job", "results/integration/active_runtime",
    "results/integration/model_calls/active_call", "results/integration/chat_compatibility/active_step24_5_run")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _read(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("A recovery record contains duplicate JSON keys.")
            value[key] = item
        return value
    return json.loads(path.read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("A recovery value is nonfinite.")))


def _path(root, relative):
    if type(relative) is not str or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("Recovery paths must be project-relative.")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("A recovery path leaves the project.")
    return path


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Existing recovery evidence differs and was preserved.")
        return
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _maps(root, old, replacement):
    if type(old) is not dict or not old or type(replacement) is not dict or set(old) != set(replacement):
        raise ValueError("Both complete component maps must name the same sources.")
    for mapping in (old, replacement):
        for relative, digest in mapping.items():
            _path(root, relative)
            if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("A recovery component digest is invalid.")


def _manifest(root, pointer):
    if type(pointer) is not dict or set(pointer) != {"manifest_id", "manifest_path"}:
        raise ValueError("The continuation pointer has an unexpected shape.")
    path = _path(root, pointer["manifest_path"])
    value = _read(path)
    identity = {key: item for key, item in value.items() if key not in {"manifest_id", "amendment_id", "call_prefix"}}
    digest = sha(canonical(identity))
    if (value.get("manifest_id") != digest or pointer["manifest_id"] != digest
            or value.get("amendment_id") != "continuation_" + digest[:20]
            or value.get("call_prefix") != "p31c_" + digest[:16]
            or path != _path(root, "artifacts/pilot/continuations/" + value["amendment_id"] + "/manifest.json")
            or type(value.get("maximum_new_generation_submissions")) is not int
            or value.get("maximum_new_generation_submissions") != 2
            or type(value.get("maximum_total_original_and_amended_submissions")) is not int
            or value.get("maximum_total_original_and_amended_submissions") != 15):
        raise ValueError("The saved continuation identity or two-call scope differs.")
    return value, path


def _zero_state(root, manifest):
    problems = [relative for relative in _MARKERS if _path(root, relative).exists()]
    native = _path(root, "results/integration/model_calls")
    if native.exists():
        problems.extend(str(path.relative_to(root)) for path in native.iterdir()
            if path.name.startswith(manifest["call_prefix"]))
    folder = _path(root, "results/pilot/continuations/" + manifest["amendment_id"])
    allowed = {"trace_identity.json", "stage_events.jsonl", "http_events.jsonl"}
    if folder.exists():
        for path in folder.iterdir():
            if not path.is_file() or path.name not in allowed:
                problems.append(str(path.relative_to(root)))
            elif path.name.endswith("events.jsonl") and path.read_bytes().strip():
                problems.append(str(path.relative_to(root)))
        trace_path = folder / "trace_identity.json"
        if trace_path.exists():
            trace = _read(trace_path)
            if trace.get("manifest_id") != manifest["manifest_id"] or trace.get("maximum_generation_submissions") != 2:
                problems.append(str(trace_path.relative_to(root)))
    if problems:
        raise ValueError("This amendment is not a zero-call preflight; existing state was preserved: " + ", ".join(problems))
    return {str(path.relative_to(root)): sha(path.read_bytes()) for path in folder.iterdir()} if folder.exists() else {}


def _prior(root, old, replacement):
    matches = []
    folder = _path(root, ARCHIVES)
    for path in sorted(folder.glob("*/recovery.json")) if folder.exists() else []:
        record = _read(path)
        if record.get("old_component_sha256") != old or record.get("replacement_component_sha256") != replacement:
            continue
        body = {key: item for key, item in record.items() if key != "record_sha256"}
        if record.get("record_sha256") != sha(canonical(body)):
            raise ValueError("The saved recovery decision changed.")
        for relative, expected in record["archive_file_sha256"].items():
            artifact = _path(root, relative)
            if not artifact.is_file() or sha(artifact.read_bytes()) != expected:
                raise ValueError("A recovery archive changed.")
        old_pointer = _read(_path(root, record["archived_pointer_path"]))
        manifest, _ = _manifest(root, old_pointer)
        if _zero_state(root, manifest) != record["old_trace_file_sha256"]:
            raise ValueError("The original zero-call trace changed after recovery.")
        for relative in old:
            if sha(_path(root, relative).read_bytes()) not in {old[relative], replacement[relative]}:
                raise ValueError("A recovered component differs from both declared versions.")
        matches.append(record)
    if len(matches) > 1:
        raise ValueError("More than one recovery matches these components; no pointer was removed.")
    return matches[0] if matches else None


def recover_preflight(root, *, old_component_sha256, replacement_component_sha256):
    """Archive one known failed comparison; never clear a submitted or new amendment."""
    root = Path(root).resolve()
    old, replacement = dict(old_component_sha256), dict(replacement_component_sha256)
    _maps(root, old, replacement)
    active = [relative for relative in _MARKERS if _path(root, relative).exists()]
    if active:
        raise ValueError("An active or unresolved runtime marker was preserved: " + ", ".join(active))
    pointer_path = _path(root, POINTER)
    if not pointer_path.exists():
        previous = _prior(root, old, replacement)
        return {**previous, "status": "already_recovered"} if previous else {"status": "not_needed_no_pointer"}
    pointer_bytes = pointer_path.read_bytes()
    manifest, manifest_path = _manifest(root, _read(pointer_path))
    if manifest.get("amendment_component_sha256") == replacement:
        return {"status": "not_needed_replacement_amendment", "manifest_id": manifest["manifest_id"],
            "pointer_preserved": True}
    if manifest.get("amendment_component_sha256") != old:
        raise ValueError("The pointer is not the known superseded preflight or its declared replacement.")
    state = _zero_state(root, manifest)
    for relative, expected in old.items():
        if sha(_path(root, relative).read_bytes()) != expected:
            raise ValueError("A superseded component differs from the allowed old source: " + relative)
    identity = {"old_manifest_id": manifest["manifest_id"], "old_component_sha256": old,
        "replacement_component_sha256": replacement}
    archive = _path(root, ARCHIVES + "/recovery_" + sha(canonical(identity))[:20])
    archived = {archive / "pointer.json": pointer_bytes, archive / "manifest.json": manifest_path.read_bytes()}
    for relative in old:
        archived[archive / "sources" / relative] = _path(root, relative).read_bytes()
    for path, data in archived.items():
        _save(path, data)
    record = {"schema_version": VERSION, **identity,
        "reason": "Correct the ordered-table comparison, prove complete row equivalence, and reuse the exact saved check table.",
        "decision": "Archive the superseded zero-call preflight pointer before the declared source upgrade.",
        "old_manifest_path": manifest_path.relative_to(root).as_posix(),
        "archived_pointer_path": (archive / "pointer.json").relative_to(root).as_posix(),
        "archive_file_sha256": {path.relative_to(root).as_posix(): sha(data) for path, data in archived.items()},
        "old_trace_file_sha256": state, "old_model_submissions": 0,
        "replacement_maximum_new_generation_submissions": 2,
        "replacement_scope": "The same ungenerated revision2 and evaluator2; no earlier model outcome is retried.",
        "original_manifest_and_trace_preserved": True}
    record["record_sha256"] = sha(canonical(record))
    _save(archive / "recovery.json", canonical(record) + b"\n")
    # Recheck immediately before the only removal. Source upgrades happen later.
    if pointer_path.read_bytes() != pointer_bytes or _zero_state(root, manifest) != state:
        raise ValueError("The preflight state changed during recovery; the pointer was preserved.")
    pointer_path.unlink()
    return {**record, "status": "recovered"}
