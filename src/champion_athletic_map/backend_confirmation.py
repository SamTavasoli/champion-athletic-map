"""Confirm five frozen corrected requests through render-only backend calls."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from uuid import uuid4


VERSION = "five-request-backend-render-confirmation-1"
_NATIVE_OPTIONS = {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 2048}
_METADATA = {"/api/version", "/api/tags", "/api/show", "/api/ps"}


class ConfirmationBlocked(RuntimeError):
    """Saved incomplete or incompatible confirmation evidence was preserved."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=False, allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate key in backend confirmation evidence.")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite confirmation evidence.")))


def save_once(path, value):
    data = value if isinstance(value, bytes) else canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ConfirmationBlocked("Existing backend confirmation evidence differs and was preserved.")
        return
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def checked(root, relative):
    text = str(relative).replace("\\", "/")
    if Path(text).is_absolute() or ".." in Path(text).parts:
        raise ValueError("A confirmation source must be project-relative.")
    path = (root / text).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("A confirmation source is missing or outside the project.")
    return path


def request_descriptors(requests):
    """Bind semantic candidate identity separately from actual wire ordering."""
    if not isinstance(requests, list) or len(requests) != 5:
        raise ValueError("Exactly five corrected revision requests must be confirmed together.")
    result = []
    for entry in requests:
        identifier = entry.get("request_id", entry.get("call_id"))
        payload = entry.get("payload")
        predicted_input = entry.get("predicted_input_tokens")
        predicted_body = entry.get("predicted_body_tokens", predicted_input - 2 if type(predicted_input) is int else None)
        if (not isinstance(identifier, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", identifier) is None
                or not isinstance(payload, dict) or type(predicted_body) is not int or predicted_body < 0
                or type(predicted_input) is not int or predicted_input != predicted_body + 2 or predicted_input > 5888
                or entry.get("output_reserve", 2048) != 2048
                or not isinstance(entry.get("source_path"), str)
                or re.fullmatch(r"[0-9a-f]{64}", entry.get("source_sha256", "")) is None
                or re.fullmatch(r"[0-9a-f]{64}", entry.get("predicted_render_sha256", "")) is None):
            raise ValueError("A corrected render request lacks its frozen payload, source or complete budget prediction.")
        digest = sha(canonical(payload))
        if entry.get("payload_canonical_sha256", digest) != digest:
            raise ValueError("A corrected request differs from its canonical payload binding.")
        row = {"request_id": identifier, "payload_canonical_sha256": digest,
            "source_path": entry["source_path"].replace("\\", "/"), "source_sha256": entry["source_sha256"],
            "predicted_body_tokens": predicted_body, "predicted_input_tokens": predicted_input,
            "predicted_render_sha256": entry["predicted_render_sha256"], "output_reserve": 2048}
        if "case_index" in entry:
            row["case_index"] = entry["case_index"]
        result.append(row)
    if len({row["request_id"] for row in result}) != 5:
        raise ValueError("The five confirmation request IDs must be distinct.")
    return result


def _verify_inputs(root, manifest, requests):
    descriptors = request_descriptors(requests)
    roster_hash = sha(canonical(descriptors))
    if (manifest.get("backend_confirmation_request_roster_sha256") != roster_hash
            and canonical(manifest.get("backend_confirmation_requests")) != canonical(descriptors)):
        raise ValueError("The five backend requests do not match the frozen continuation roster.")
    for entry, descriptor in zip(requests, descriptors):
        source = checked(root, descriptor["source_path"])
        if sha(source.read_bytes()) != descriptor["source_sha256"] or canonical(read(source)) != canonical(entry["payload"]):
            raise ValueError("A saved corrected candidate changed after its source was bound.")
        payload = entry["payload"]
        if (set(payload) != {"model", "stream", "truncate", "shift", "format", "messages", "options"}
                or payload.get("model") != "llama3.1:8b" or payload.get("stream") is not False
                or payload.get("truncate") is not False or payload.get("shift") is not False
                or type(payload.get("format")) is not dict or payload.get("options") != _NATIVE_OPTIONS):
            raise ValueError("A corrected request changed the native schema or shared model settings.")
        messages = payload.get("messages")
        if (not isinstance(messages, list) or len(messages) != 2
                or any(not isinstance(row, dict) or set(row) != {"role", "content"} for row in messages)
                or [row["role"] for row in messages] != ["system", "user"]
                or any(not isinstance(row["content"], str) or not row["content"] or row["content"] != row["content"].strip() for row in messages)):
            raise ValueError("A corrected request changed its complete message boundaries.")
        prepared = entry.get("prepared")
        if prepared is not None:
            view = json.loads(messages[1]["content"])
            if canonical(prepared.get("public_input")) != canonical(view.get("athlete_input")):
                raise ValueError("A confirmation payload differs from its prepared athlete facts.")
    return descriptors, roster_hash


def _folder(root, manifest, trace, output_dir):
    target = Path(output_dir) if output_dir is not None else (
        Path(trace.output_dir) / "backend_confirmation" if trace is not None else
        root / "results/pilot/saved_continuation" / manifest["continuation_id"] / "backend_confirmation")
    target = (target if target.is_absolute() else root / target).resolve()
    boundary = root / "results/pilot"
    if target == boundary or not target.is_relative_to(boundary):
        raise ValueError("Backend confirmation evidence must stay in its separate results/pilot folder.")
    return target


def _load_completed(folder, manifest_id, roster_hash, descriptors):
    path = folder / "completed.json"
    if not path.is_file():
        return None
    saved = read(path)
    body = {key: value for key, value in saved.items() if key != "completion_record_sha256"}
    if (saved.get("completion_record_sha256") != sha(canonical(body)) or saved.get("manifest_id") != manifest_id
            or saved.get("request_roster_sha256") != roster_hash or saved.get("requests") != descriptors
            or saved.get("status") != "backend_renders_confirmed" or saved.get("confirmed_requests") != 5):
        raise ConfirmationBlocked("Saved completed render confirmation does not match this request roster.")
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file() and p != folder / "completed.json"}
    if actual != set(saved["artifact_sha256"]):
        raise ConfirmationBlocked("Completed render confirmation has missing or unexpected artifacts.")
    for relative, expected in saved["artifact_sha256"].items():
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or sha(path.read_bytes()) != expected:
            raise ConfirmationBlocked("Saved render confirmation evidence changed.")
    return {**saved, "saved_confirmation_reused": True, "new_render_requests": 0,
            "new_metadata_requests": 0, "new_http_requests": 0}


def _require_gate(root, manifest_id, trace):
    if trace is None or trace.manifest_id != manifest_id or trace.current is not None or trace._instrumenting:
        raise ConfirmationBlocked("Confirmation requires an idle trace under the continuation execution gate.")
    for relative in ("results/app/active_model_job", "results/integration/active_runtime"):
        owner = root / relative / "owner.json"
        if not owner.is_file() or read(owner).get("manifest_sha256") != manifest_id:
            raise ConfirmationBlocked("The continuation execution gate is not owned by this manifest.")
    trace.assert_safe()
    if trace.summary()["generation_transport_attempts"]:
        raise ConfirmationBlocked("All five backend confirmations must precede any continuation generation.")


@contextmanager
def _current(trace, manifest_id, suffix):
    if trace.current is not None:
        raise ConfirmationBlocked("A backend confirmation cannot overlap another role.")
    context = {"job_id": "backend_confirmation_" + manifest_id[:16], "planner_version": 4,
        "call_id": "confirm_" + manifest_id[:16] + "_" + suffix,
        "stage": "backend_render_confirmation", "invocation_id": uuid4().hex}
    trace.current = context
    try:
        yield
    finally:
        trace.current = None


def confirm_requests(root, manifest, requests, *, role=None, trace=None, output_dir=None, emit=None):
    """Confirm the whole frozen set; submit no generation request and never retry.

    The caller holds pilot_trace.execution_gate for the complete continuation.
    This function owns temporary trace instrumentation during confirmation only.
    A verified completed receipt can be reused without constructing a runtime.
    """
    root = Path(root).resolve()
    manifest_id = manifest.get("manifest_id")
    if not isinstance(manifest_id, str) or re.fullmatch(r"[0-9a-f]{64}", manifest_id) is None:
        raise ValueError("A frozen continuation manifest identity is required.")
    descriptors, roster_hash = _verify_inputs(root, manifest, requests)
    folder = _folder(root, manifest, trace, output_dir)
    completed = _load_completed(folder, manifest_id, roster_hash, descriptors)
    if completed is not None:
        return completed
    if folder.exists() and any(folder.iterdir()):
        raise ConfirmationBlocked("An earlier confirmation is incomplete; it was preserved without resubmission.")
    if role is None or not callable(getattr(role, "_budget_view", None)):
        raise ValueError("New render confirmations require the actual corrected role and shared client.")
    _require_gate(root, manifest_id, trace)
    client = role.client
    views = []
    for entry in requests:
        client.response.Draft202012Validator.check_schema(entry["payload"]["format"])
        views.append(role._budget_view(entry["payload"]))
    save_once(folder / "attempt_started.json", {"schema_version": VERSION, "manifest_id": manifest_id,
        "request_roster_sha256": roster_hash, "requests": descriptors, "maximum_render_requests": 5,
        "maximum_metadata_requests": 8, "maximum_generation_requests": 0})
    before = trace.summary()
    observed = {"metadata": 0, "render": 0}
    expected_render = {"payload": None}
    try:
        with trace.instrument(SimpleNamespace(client=client), "backend_confirmation_" + manifest_id[:16], 4):
            traced_http = client._http
            def guarded_http(endpoint, payload=None, timeout=8, raw_path=None):
                if endpoint == "/api/chat":
                    expected = expected_render["payload"]
                    if (expected is None or not isinstance(payload, dict) or payload.get("_debug_render_only") is not True
                            or wire(payload) != wire(expected) or observed["render"] >= 5):
                        raise ConfirmationBlocked("The render gate forbids generation, payload rewrites or a sixth render request.")
                    observed["render"] += 1
                elif endpoint in _METADATA:
                    if observed["metadata"] >= 8:
                        raise ConfirmationBlocked("The backend confirmation reached its metadata limit.")
                    observed["metadata"] += 1
                else:
                    raise ConfirmationBlocked("The render gate forbids other endpoints.")
                return traced_http(endpoint, payload, timeout, raw_path)
            client._http = guarded_http
            try:
                def identity(label):
                    with _current(trace, manifest_id, "identity_" + label):
                        value = client._identity()
                        runners = client._http("/api/ps")
                    digest = value["model"]["digest"]
                    matching = [row for row in runners.get("models", []) if row.get("digest") == digest]
                    cold_start = label == "before" and not matching
                    if not cold_start and (len(matching) != 1 or type(matching[0].get("context_length")) is not int
                            or matching[0]["context_length"] < 8192):
                        raise ConfirmationBlocked("The exact shared model runner is absent or its context is below8192.")
                    save_once(folder / ("identity_" + label + ".json"), {"identity": value,
                        "runner": matching[0] if matching else None, "cold_before_render": cold_start})
                    return value
                identity_before = identity("before")
                for index, (entry, descriptor, view) in enumerate(zip(requests, descriptors, views), 1):
                    work = folder / (str(index).zfill(2) + "_" + descriptor["request_id"])
                    save_once(work / "request.json", wire(entry["payload"]))
                    save_once(work / "descriptor.json", descriptor)
                    render_payload = {**deepcopy(entry["payload"]), "_debug_render_only": True}
                    expected_render["payload"] = render_payload
                    try:
                        with _current(trace, manifest_id, "render_" + str(index)):
                            response = client._http("/api/chat", render_payload, 60, work / "render_response.json")
                        rendered = client.preflight.extract_rendered_prompt(response)
                        save_once(work / "rendered_prompt.txt", rendered.encode("utf-8"))
                        if sha(rendered.encode()) != descriptor["predicted_render_sha256"]:
                            raise ConfirmationBlocked("The actual backend render differs from the frozen complete candidate rendering.")
                        budget = client.preflight.assess_rendered_prompt(view, rendered, client.encoder, client.controls)
                        if (budget.get("status") != "within_local_budget"
                                or budget.get("rendered_body_tokens") != descriptor["predicted_body_tokens"]
                                or budget.get("local_input_tokens_with_boundary_reserve") != descriptor["predicted_input_tokens"]
                                or budget.get("input_ceiling_after_output_and_margin") != 5888
                                or budget.get("configured_context_tokens") != 8192 or budget.get("output_reserve") != 2048
                                or budget.get("safety_margin") != 256 or budget.get("unverified_boundary_reserve") != 2
                                or budget.get("backend_added_system_prefix") != "" or budget.get("backend_added_system_suffix") != ""):
                            raise ConfirmationBlocked("The backend-rendered complete request or tokenizer budget disagrees with its frozen prediction.")
                        save_once(work / "budget.json", budget)
                    finally:
                        expected_render["payload"] = None
                    save_once(work / "confirmed.json", {"request_id": descriptor["request_id"],
                        "payload_canonical_sha256": descriptor["payload_canonical_sha256"],
                        "actual_submitted_wire_sha256": sha(wire(render_payload)), "rendered_prompt_sha256": sha(rendered.encode()),
                        "local_input_tokens_with_boundary_reserve": budget["local_input_tokens_with_boundary_reserve"],
                        "new_backend_render_confirmed": True, "backend_token_count_agreement_verified": False,
                        "generation_requests_submitted": 0})
                    if emit is not None:
                        emit("Backend render confirmed: " + str(index) + "/5")
                identity_after = identity("after")
                if canonical(identity_before) != canonical(identity_after):
                    raise ConfirmationBlocked("The shared backend model identity changed during render confirmation.")
            finally:
                client._http = traced_http
        after = trace.summary()
        if (observed != {"metadata": 8, "render": 5}
                or after["generation_transport_attempts"] != before["generation_transport_attempts"]
                or after["render_transport_attempts"] - before["render_transport_attempts"] != 5
                or after["metadata_transport_attempts"] - before["metadata_transport_attempts"] != 8
                or after["http_without_terminal_event"]):
            raise ConfirmationBlocked("The confirmation trace does not establish exactly five completed render-only requests.")
        artifacts = {p.relative_to(folder).as_posix(): sha(p.read_bytes()) for p in sorted(folder.rglob('*')) if p.is_file()}
        result = {"schema_version": VERSION, "manifest_id": manifest_id, "request_roster_sha256": roster_hash,
            "status": "backend_renders_confirmed", "requests": descriptors, "confirmed_requests": 5,
            "all_five_confirmed": True, "new_backend_render_confirmed": True,
            "backend_token_count_agreement_verified": False, "operational_generation_ready": False,
            "saved_confirmation_reused": False, "new_render_requests": 5, "new_metadata_requests": 8,
            "new_http_requests": 13, "generation_requests_submitted": 0,
            "injected_test_dependencies": manifest.get("injected_test_dependencies") is True,
            "artifact_sha256": artifacts, "confirmation_record_path": (folder / "completed.json").relative_to(root).as_posix()}
        result["completion_record_sha256"] = sha(canonical(result))
        save_once(folder / "completed.json", result)
        return result
    except BaseException as error:
        save_once(folder / "failure.json", {"schema_version": VERSION, "manifest_id": manifest_id,
            "request_roster_sha256": roster_hash, "error": type(error).__name__ + ": " + str(error),
            "observed_requests": observed, "generation_requests_submitted": 0,
            "render_outcome_uncertain": trace.is_uncertain(), "automatic_retry_permitted": False})
        raise
