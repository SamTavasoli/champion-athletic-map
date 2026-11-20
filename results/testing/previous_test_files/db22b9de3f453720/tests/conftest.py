"""Keep routine checks offline and record what pytest actually executes."""

from pathlib import Path
import json
import os
import socket
import subprocess
import sys
import urllib.request

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
_collected = []
_reports = []
_collection_errors = []
_deselected = []


def pytest_configure(config):
    config.addinivalue_line("markers", "real_backend: explicitly selected local Ollama checks")
    config.addinivalue_line("markers", "requirement(identifier): reviewed Step 30 requirement")


def _requirement(item):
    mark = item.get_closest_marker("requirement")
    if mark and mark.args:
        return str(mark.args[0])
    name = item.nodeid.lower()
    groups = (("contract", "30.4"), ("rule_check", "30.5"),
              ("reference", "30.6"), ("classifier", "30.6"),
              ("result_account", "30.10"), ("planner_workflow", "30.7-30.8"),
              ("execution_failure", "30.8"), ("adapter_context", "30.8"),
              ("application", "30.9"), ("runtime_ownership", "30.9"))
    return next((value for key, value in groups if key in name), "30.3")


def pytest_collection_modifyitems(config, items):
    for item in items:
        requirement = _requirement(item)
        item.user_properties.append(("requirement", requirement))
        _collected.append({"test_id": item.nodeid, "requirement": requirement,
            "fixture_version": getattr(item.module, "FIXTURE_VERSION", "step30-authored-fixtures-1"),
            "expected_outcome_source": str(Path(item.path).relative_to(ROOT)).replace("\\", "/") + ":" + str(item.location[1] + 1),
            "description": (getattr(item.obj, "__doc__", None) or item.name).strip().splitlines()[0]})


def pytest_collectreport(report):
    if report.failed:
        _collection_errors.append({"test_id": report.nodeid, "detail": str(report.longrepr)[:12000]})


def pytest_deselected(items):
    _deselected.extend(item.nodeid for item in items)


@pytest.fixture(autouse=True)
def routine_checks_stay_offline(request, monkeypatch):
    if request.node.get_closest_marker("real_backend"):
        return

    def blocked(*args, **kwargs):
        raise AssertionError("Routine tests cannot contact services or start external workers.")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)
    monkeypatch.setattr(subprocess, "run", blocked)


def pytest_runtest_logreport(report):
    _reports.append({"test_id": report.nodeid, "phase": report.when,
        "outcome": report.outcome, "duration_seconds": report.duration,
        "expected_failure": bool(getattr(report, "wasxfail", False)),
        "detail": str(report.longrepr)[:12000] if report.failed or report.skipped else None})


def pytest_sessionfinish(session, exitstatus):
    destination = Path(os.environ.get("CAM_TEST_REPORT_DIR", ROOT / "results/testing"))
    destination.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": "step30-pytest-execution-1", "pytest_exit_code": int(exitstatus),
        "collected": _collected, "phases": _reports,
        "collection_errors": _collection_errors, "deselected": _deselected,
        "new_model_calls": 0, "query_encoder_processes": 0,
        "network_policy": "blocked_in_routine_tests", "fixtures": "authored_public_examples"}
    (destination / "execution_details.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
