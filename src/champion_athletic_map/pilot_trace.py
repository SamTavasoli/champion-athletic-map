"""Record bounded local pilot work without changing the model adapters."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from time import perf_counter
from uuid import uuid4


TRACE_VERSION = "pilot-operational-trace-1"
_BACKEND_MARKERS = ("results/integration/model_calls/active_call",
    "results/integration/chat_compatibility/active_step24_5_run")
_GATE_MARKERS = ("results/app/active_model_job", "results/integration/active_runtime")
_ENDPOINTS = {"/api/version", "/api/tags", "/api/show", "/api/ps", "/api/chat"}


class ProbeBlocked(RuntimeError):
    """An existing or uncertain attempt was preserved rather than resubmitted."""


class UncertainProbe(ProbeBlocked):
    """Backend completion cannot be established from the saved evidence."""


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _path(root, path):
    path = Path(path)
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Pilot evidence must stay inside the project.")
    return path


def _save_once(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ProbeBlocked("Existing pilot evidence differs and was preserved: " + str(path))
        return
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _read_events(path):
    if not path.exists():
        return []
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        raise ProbeBlocked("The pilot journal has an incomplete final record; it was preserved.")
    try:
        rows = [json.loads(line) for line in data.splitlines()]
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("Journal rows must be objects.")
        return rows
    except (ValueError, UnicodeError) as error:
        raise ProbeBlocked("The pilot journal cannot be read safely: " + str(error)) from None


def _backend_problems(root):
    problems = [relative for relative in _BACKEND_MARKERS if (root / relative).exists()]
    folder = root / "results/integration/model_calls"
    if folder.is_dir():
        for call in sorted(folder.iterdir()):
            if not call.is_dir() or call.name == "active_call":
                continue
            result = call / "result.json"
            if result.is_file():
                try:
                    saved = json.loads(result.read_bytes())
                    if not isinstance(saved, dict) or saved.get("status") == "unresolved":
                        problems.append(str(call.relative_to(root)))
                except (OSError, ValueError, UnicodeError):
                    problems.append(str(call.relative_to(root)))
            elif (call / "request.json").exists() or (call / "generation_pending.json").exists():
                problems.append(str(call.relative_to(root)))
    return problems


class PilotTrace:
    """Instrument private workflow instances and retain every observed attempt."""

    def __init__(self, root, output_dir, *, manifest_id, max_generation_submissions=15, clock=perf_counter):
        self.root = Path(root).resolve()
        self.output_dir = _path(self.root, output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not isinstance(manifest_id, str) or not manifest_id.strip():
            raise ValueError("A pilot trace needs its immutable manifest identity.")
        if type(max_generation_submissions) is not int or not 1 <= max_generation_submissions <= 15:
            raise ValueError("This bounded probe permits between one and fifteen generation submissions.")
        self.max_generation_submissions = max_generation_submissions
        self.manifest_id, self.clock = manifest_id, clock
        self.session_id, self.current, self._instrumenting = uuid4().hex, None, False
        self._uncertain = False
        self.stage_path = self.output_dir / "stage_events.jsonl"
        self.http_path = self.output_dir / "http_events.jsonl"
        _save_once(self.output_dir / "trace_identity.json", _bytes({"schema_version": TRACE_VERSION,
            "manifest_id": manifest_id, "timing": "synchronous_client_wall_clock",
            "maximum_generation_submissions": max_generation_submissions,
            "generation_counts": "actual_leaf_transport_invocations_not_backend_acceptance"}))
        earlier = _read_events(self.stage_path) + _read_events(self.http_path)
        self._uncertain = any(row.get("unresolved") is True for row in earlier)

    def _event(self, path, event, **fields):
        row = {"schema_version": TRACE_VERSION, "manifest_id": self.manifest_id,
            "session_id": self.session_id, "time": datetime.now(timezone.utc).isoformat(),
            "event": event, **fields}
        data = _bytes(row)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            with os.fdopen(descriptor, "ab") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            self._uncertain = True
            raise
        return row

    def assert_safe(self, call_id=None):
        problems = _backend_problems(self.root)
        if self._uncertain or problems:
            raise UncertainProbe("The probe stopped at an uncertain or incomplete request; existing evidence was preserved. " + ", ".join(problems))
        if call_id is not None:
            if not isinstance(call_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", call_id) is None:
                raise ValueError("Use a stable model-call identifier of at most 80 characters.")
            folder = self.root / "results/integration/model_calls" / call_id
            if folder.exists() and not (folder / "result.json").is_file():
                raise UncertainProbe("This role has an incomplete saved folder; it was not resubmitted.")
            starts = [row for row in _read_events(self.stage_path) if row.get("call_id") == call_id]
            if starts and not (folder / "result.json").is_file():
                raise ProbeBlocked("This role already has a recorded invocation without a saved result; it was not resubmitted.")

    raise_if_uncertain = assert_safe

    def is_uncertain(self):
        return self._uncertain or bool(_backend_problems(self.root))

    def _stage(self, original, kind, job_id, planner_version, args, kwargs):
        position = 3 if kind == "role" else 2
        call_id = kwargs.get("call_id", args[position] if len(args) > position else None)
        self.assert_safe(call_id)
        stage = kwargs.get("stage", "final")
        if any(row.get("call_id") == call_id and (row.get("job_id") != job_id
                or row.get("planner_version") != planner_version or row.get("stage") != stage)
                for row in _read_events(self.stage_path)):
            raise ProbeBlocked("This call identifier belongs to another recorded workflow or role.")
        existing = self.root / "results/integration/model_calls" / call_id / "result.json"
        submissions = [row for row in _read_events(self.http_path)
            if row.get("event") == "http_started" and row.get("phase") == "generation"]
        if not existing.is_file() and len(submissions) >= self.max_generation_submissions:
            raise ProbeBlocked("The probe has reached its declared generation limit; no new role was submitted.")
        if self.current is not None:
            raise ProbeBlocked("Pilot role instrumentation cannot nest or run concurrently.")
        invocation_id = uuid4().hex
        current = {"job_id": job_id, "planner_version": planner_version,
            "call_id": call_id, "stage": stage, "invocation_id": invocation_id}
        self.current = current
        started = self.clock()
        self._event(self.stage_path, "stage_started", **current)
        try:
            result = original(*args, **kwargs)
            if not isinstance(result, dict):
                raise TypeError("The model adapter returned no saved role record.")
            if result.get("call_id") not in (None, call_id):
                raise ValueError("The returned role belongs to a different call identifier.")
            snapshot = self.output_dir / "stage_results" / (invocation_id + ".json")
            _save_once(snapshot, _bytes(result))
            saved = self.root / "results/integration/model_calls" / call_id / "result.json"
            uncertain = result.get("status") == "unresolved" or bool(_backend_problems(self.root))
            self._uncertain = self._uncertain or uncertain
            self._event(self.stage_path, "stage_finished", **current,
                elapsed_seconds=self.clock() - started, status=result.get("status"),
                cached=result.get("cached") is True, completion_valid=result.get("completion_valid"),
                format_valid=result.get("format_valid"), request_sha256=result.get("request_sha256"),
                usage=result.get("usage") or {}, error=result.get("error"),
                result_snapshot=str(snapshot.relative_to(self.root)),
                result_snapshot_sha256=_sha(snapshot.read_bytes()),
                saved_result_sha256=_sha(saved.read_bytes()) if saved.is_file() else None,
                unresolved=uncertain)
            return result
        except BaseException as error:
            self._uncertain = self._uncertain or bool(_backend_problems(self.root))
            self._event(self.stage_path, "stage_exception", **current,
                elapsed_seconds=self.clock() - started,
                error=type(error).__name__ + ": " + str(error), unresolved=self._uncertain)
            raise
        finally:
            self.current = None

    def _http(self, original, endpoint, payload=None, timeout=8, raw_path=None):
        if self.current is None or endpoint not in _ENDPOINTS:
            raise ProbeBlocked("A pilot transport needs its recorded role and a declared endpoint.")
        phase = ("render" if isinstance(payload, dict) and payload.get("_debug_render_only") is True
                 else "generation") if endpoint == "/api/chat" else "metadata"
        if endpoint == "/api/chat" and payload is None:
            raise ProbeBlocked("A chat transport requires the unchanged request body.")
        current = dict(self.current)
        if phase in ("render", "generation"):
            if any(row.get("event") == "http_started" and row.get("call_id") == current["call_id"]
                   and row.get("phase") == phase for row in _read_events(self.http_path)):
                raise ProbeBlocked("This role already attempted " + phase + "; automatic resubmission is disabled.")
        if phase == "generation" and sum(row.get("event") == "http_started" and row.get("phase") == "generation"
                for row in _read_events(self.http_path)) >= self.max_generation_submissions:
            raise ProbeBlocked("The probe has reached its declared generation limit; no HTTP request was submitted.")
        http_id = uuid4().hex
        request_data = b"" if payload is None else json.dumps(payload, ensure_ascii=False, sort_keys=False, allow_nan=False).encode("utf-8")
        request_path = self.output_dir / "http_requests" / (http_id + ".json")
        _save_once(request_path, request_data)
        target = _path(self.root, raw_path) if raw_path is not None else self.output_dir / "http_responses" / (http_id + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        started = self.clock()
        common = {**current, "http_id": http_id, "endpoint": endpoint,
            "method": "GET" if payload is None else "POST", "phase": phase, "timeout_seconds": timeout,
            "request_sha256": _sha(request_data), "request_path": str(request_path.relative_to(self.root)),
            "raw_path": str(target.relative_to(self.root))}
        self._event(self.http_path, "http_started", **common)
        try:
            value = original(endpoint, payload, timeout, target)
            self._event(self.http_path, "http_finished", **common,
                elapsed_seconds=self.clock() - started,
                raw_response_sha256=_sha(target.read_bytes()) if target.is_file() else None,
                backend_done=value.get("done") if isinstance(value, dict) else None)
            return value
        except BaseException as error:
            if phase in ("render", "generation"):
                self._uncertain = True
            self._event(self.http_path, "http_exception", **common,
                elapsed_seconds=self.clock() - started,
                raw_response_sha256=_sha(target.read_bytes()) if target.is_file() else None,
                error=type(error).__name__ + ": " + str(error), unresolved=self._uncertain)
            raise

    @contextmanager
    def instrument(self, planner, job_id, planner_version):
        """Wrap actual leaf transports and their generate methods, restoring both."""
        if self._instrumenting:
            raise ProbeBlocked("Only one workflow may use this pilot trace at a time.")
        self.assert_safe()
        visited, transports = set(), []
        def visit(value):
            if id(value) in visited:
                return
            visited.add(id(value))
            if callable(getattr(value, "_http", None)) and callable(getattr(value, "generate", None)):
                transports.append(value)
            for attribute in ("planner", "drafting", "roles", "client"):
                child = getattr(value, attribute, None)
                if child is not None:
                    visit(child)
        visit(planner)
        if not transports:
            raise ValueError("The workflow exposes no supported private model transport.")
        changed = []
        def patch(value, name, replacement):
            changed.append((value, name, name in vars(value), vars(value).get(name)))
            setattr(value, name, replacement)
        self._instrumenting = True
        try:
            for transport in transports:
                role = getattr(transport, "client", None) is not None
                generate = transport.generate
                def wrapped(*args, _original=generate, _kind="role" if role else "client", **kwargs):
                    return self._stage(_original, _kind, job_id, planner_version, args, kwargs)
                patch(transport, "generate", wrapped)
                if not role:
                    original = transport._http
                    def http(endpoint, payload=None, timeout=8, raw_path=None, _original=original):
                        return self._http(_original, endpoint, payload, timeout, raw_path)
                    patch(transport, "_http", http)
            yield self
        finally:
            for value, name, existed, old in reversed(changed):
                if existed:
                    setattr(value, name, old)
                else:
                    delattr(value, name)
            self._instrumenting = False

    def summary(self):
        stages, http = _read_events(self.stage_path), _read_events(self.http_path)
        starts = {row["http_id"]: row for row in http if row.get("event") == "http_started"}
        ends = {row["http_id"]: row for row in http if row.get("event") in ("http_finished", "http_exception")}
        terminal = [row for row in stages if row.get("event") == "stage_finished"]
        unique = {}
        for row in terminal:
            unique.setdefault(row["call_id"], row)
        usage = {call_id: {"usage": row["usage"], "status": row["status"],
            "first_observation_cached": row["cached"], "observed_first_role_wall_seconds": row["elapsed_seconds"],
            "charged_once_by_call_id": True}
            for call_id, row in unique.items()}
        return {"schema_version": TRACE_VERSION, "manifest_id": self.manifest_id,
            "metadata_transport_attempts": sum(row["phase"] == "metadata" for row in starts.values()),
            "render_transport_attempts": sum(row["phase"] == "render" for row in starts.values()),
            "generation_transport_attempts": sum(row["phase"] == "generation" for row in starts.values()),
            "generation_call_ids": sorted({row["call_id"] for row in starts.values() if row["phase"] == "generation"}),
            "http_requests": len(starts), "http_without_terminal_event": sorted(set(starts) - set(ends)),
            "role_invocations": sum(row.get("event") == "stage_started" for row in stages),
            "saved_role_reads": sum(row["cached"] for row in terminal),
            "unique_recorded_roles": len(unique), "role_usage": usage,
            "observed_role_wall_seconds": sum(row.get("elapsed_seconds", 0) for row in terminal),
            "new_role_wall_seconds": sum(row.get("elapsed_seconds", 0) for row in terminal if not row["cached"]),
            "saved_role_read_wall_seconds": sum(row.get("elapsed_seconds", 0) for row in terminal if row["cached"]),
            "backend_acceptance_inferred": False, "uncertain": self.is_uncertain()}


class _ExecutionGate:
    def __init__(self, root, owner_id, manifest_sha256, trace):
        self.root, self.trace = Path(root).resolve(), trace
        self.owner = {"schema_version": TRACE_VERSION, "owner_id": owner_id,
            "manifest_sha256": manifest_sha256, "kind": "bounded_pilot_probe", "token": uuid4().hex}
        self.owned, self.uncertain = [], False

    def mark_uncertain(self, reason):
        self.uncertain = True
        self.owner["uncertainty_reason"] = str(reason)

    def __enter__(self):
        problems = _backend_problems(self.root) + [p for p in _GATE_MARKERS if (self.root / p).exists()]
        if problems:
            kind = UncertainProbe if _backend_problems(self.root) else ProbeBlocked
            raise kind("An existing runtime marker or incomplete request was preserved: " + ", ".join(problems))
        try:
            for relative in _GATE_MARKERS:
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.mkdir(exist_ok=False)
                self.owned.append(path)
                _save_once(path / "owner.json", _bytes(self.owner))
            if _backend_problems(self.root):
                raise ProbeBlocked("A backend request appeared while acquiring the pilot gate.")
            return self
        except BaseException:
            self._release()
            raise

    def _release(self):
        for path in reversed(self.owned):
            owner = path / "owner.json"
            if (owner.is_file() and owner.read_bytes() == _bytes(self.owner)
                    and {item.name for item in path.iterdir()} == {"owner.json"}):
                owner.unlink()
                path.rmdir()
            elif not owner.exists() and path.exists() and not list(path.iterdir()):
                path.rmdir()
        self.owned = []

    def __exit__(self, exc_type, exc, traceback):
        uncertain = self.uncertain or bool(_backend_problems(self.root))
        if self.trace is not None:
            uncertain = uncertain or self.trace.is_uncertain()
        elif exc_type is not None:
            uncertain = True
        if not uncertain:
            self._release()
        return False


def execution_gate(root, owner_id, *, manifest_sha256, trace=None):
    """Hold the existing app marker across all probe roles and release only if safe."""
    if not isinstance(owner_id, str) or not owner_id.strip() or not isinstance(manifest_sha256, str) or not manifest_sha256:
        raise ValueError("The pilot gate needs its owner and immutable configuration hash.")
    return _ExecutionGate(root, owner_id, manifest_sha256, trace)
