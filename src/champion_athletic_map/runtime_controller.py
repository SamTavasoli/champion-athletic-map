"""Keep interactive model jobs separate, owned, and safe to display on reruns."""

import hashlib
import json
import re
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


_REGISTRY_LOCK = Lock()
_PROJECT_GATES = {}


class PreflightBlocked(RuntimeError):
    request_accepted = False


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _save_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (_json(value) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("An existing interactive job differs and was preserved.")
        return
    with path.open("xb") as handle:
        handle.write(data)


class JobController:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.folder = self.root / "results/app/jobs"
        self.active = self.root / "results/app/active_model_job"
        with _REGISTRY_LOCK:
            self.gate = _PROJECT_GATES.setdefault(str(self.root), Lock())

    def _log(self, result):
        path = self.root / "results/app/development_runs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {"schema_version": "interactive-job-event-1", "time": datetime.now(timezone.utc).isoformat(),
            "job_id": result["job_id"], "owner_id": result["owner_id"], "status": result["status"],
            "kind": result["request"]["kind"], "request_sha256": result["request"]["request_sha256"],
            "cached": result["cached"], "transport_attempts_this_execution": result["transport_attempts_this_execution"]}
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(descriptor, (_json(event) + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)

    def execute(self, job_id, request, callback):
        """Submit at most once; an uncertain request remains locked for inspection."""
        if type(job_id) is not str or re.fullmatch(r"app_[A-Za-z0-9_-]{1,55}", job_id) is None:
            raise PreflightBlocked("Use a stable application job ID.")
        if (not isinstance(request, dict) or type(request.get("owner_id")) is not str or not request["owner_id"].strip()
                or request.get("kind") not in ("generation", "review") or {"job_id", "request_sha256"}.intersection(request)):
            raise PreflightBlocked("An interactive job needs its owner and action.")
        record = json.loads(_json(request))
        record["job_id"] = job_id
        record["request_sha256"] = hashlib.sha256(_json(request).encode("utf-8")).hexdigest()
        folder = self.folder / job_id
        if (folder / "result.json").is_file():
            if json.loads((folder / "request.json").read_bytes()) != record:
                raise PreflightBlocked("This job belongs to another profile, plan, owner, or source version.")
            result = json.loads((folder / "result.json").read_bytes())
            cached = {**result, "cached": True, "transport_attempts_this_execution": {"metadata": 0, "render": 0, "generation": 0}}
            self._log(cached)
            return cached
        if folder.exists():
            raise RuntimeError("This application job has an unfinished saved request; it was not resubmitted.")
        if not self.gate.acquire(blocking=False):
            raise PreflightBlocked("Another planning or review action is already running.")
        acquired = False
        try:
            self.active.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.active.mkdir()
                acquired = True
            except FileExistsError:
                raise PreflightBlocked("An earlier interactive request is active or unresolved.") from None
            shared_active = self.root / "results/integration/model_calls/active_call"
            if shared_active.exists():
                raise PreflightBlocked("An earlier backend request is unresolved; no new request was made.")
            _save_once(self.active / "owner.json", record)
            folder.mkdir(parents=True)
            _save_once(folder / "request.json", record)
            try:
                value = callback()
                if not isinstance(value, dict):
                    raise TypeError("The interactive workflow returned no execution record.")
                unresolved = value.get("status") == "unresolved" or shared_active.exists()
                result = {"job_id": job_id, "owner_id": record["owner_id"], "request": record,
                          "status": "unresolved" if unresolved else value.get("status", "completed"),
                          "cached": False, "value": value,
                          "transport_attempts_this_execution": value.get("transport_attempts", {"metadata": 0, "render": 0, "generation": 0})}
            except Exception as error:
                # The controller does not guess whether a failed callback reached the backend.
                result = {"job_id": job_id, "owner_id": record["owner_id"], "request": record,
                          "status": "unresolved", "cached": False, "value": {"status": "unresolved", "error": str(error)},
                          "transport_attempts_this_execution": {"metadata": 0, "render": 0, "generation": 0}}
            _save_once(folder / "result.json", result)
            self._log(result)
            if result["status"] != "unresolved":
                (self.active / "owner.json").unlink()
                self.active.rmdir()
                acquired = False
            return result
        finally:
            if acquired and not (self.active / "owner.json").exists():
                # An earlier readiness check failed before accepting this application job.
                self.active.rmdir()
            self.gate.release()

    @staticmethod
    def belongs_to(result, owner_id, profile_version, profile_hash, plan_version=None, plan_hash=None):
        request = result.get("request") or {}
        return (result.get("owner_id") == owner_id and request.get("profile_version") == profile_version
                and request.get("profile_planning_hash") == profile_hash
                and request.get("plan_version") == plan_version and request.get("plan_content_hash") == plan_hash)
