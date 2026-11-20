"""Run our controlled suite and save its results separately from pilot evidence."""

from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import importlib.metadata as metadata
import io
import json
import os
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "results/testing"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(relative, value):
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".step30-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_csv(relative, rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    save(relative, stream.getvalue())


def archive_failed_run():
    summary = ROOT / "results/step30_testing_summary.json"
    if not summary.is_file():
        return None
    previous = json.loads(summary.read_bytes())
    if previous.get("routine_suite") == "passed" and previous.get("pytest_exit_code") == 0:
        return None
    folder = REPORTS / "previous_runs" / sha(summary)[:16]
    paths = [summary] + [p for p in REPORTS.iterdir() if p.is_file()]
    for source in paths:
        destination = folder / source.relative_to(ROOT)
        data = source.read_bytes()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != data:
                raise RuntimeError("A saved failure archive differs and was preserved.")
        else:
            with destination.open("xb") as handle:
                handle.write(data)
    return folder.relative_to(ROOT).as_posix()


def main():
    manifest = json.loads((ROOT / "tests/fixtures/suite_manifest.json").read_bytes())
    for relative, expected in manifest["source_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or sha(path) != expected:
            raise RuntimeError("The test suite needs the recorded project version: " + relative)
    for relative, expected in manifest["test_sha256"].items():
        if sha(ROOT / relative) != expected:
            raise RuntimeError("A prepared test file changed: " + relative)
    before = {relative: sha(ROOT / relative) for relative in manifest["source_sha256"]}
    environment = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        CAM_TEST_REPORT_DIR=str(REPORTS), PYTHONDONTWRITEBYTECODE="1",
        STREAMLIT_BROWSER_GATHER_USAGE_STATS="false")
    command = [sys.executable, "-m", "pytest", "tests/unit", "tests/integration", "tests/app",
        "-m", "not real_backend", "-q", "-o", "addopts=", "-o",
        "cache_dir=results/testing/.pytest_cache", "--junitxml=results/testing/test_report.xml"]
    REPORTS.mkdir(parents=True, exist_ok=True)
    previous_failure = archive_failed_run()
    details_path = REPORTS / "execution_details.json"
    if details_path.exists():
        details_path.unlink()
    completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=300)
    save("results/testing/pytest_output.log", completed.stdout + completed.stderr)
    changed = [name for name, expected in before.items() if sha(ROOT / name) != expected]
    if not details_path.is_file():
        raise RuntimeError("The test runner did not produce an execution record. See results/testing/pytest_output.log")
    detail = json.loads(details_path.read_bytes())
    if detail["pytest_exit_code"] != completed.returncode:
        raise RuntimeError("The test process and execution record disagree.")
    by_test = {row["test_id"]: [] for row in detail["collected"]}
    for phase in detail["phases"]:
        by_test.setdefault(phase["test_id"], []).append(phase)
    statuses = {}
    for identifier, phases in by_test.items():
        if any(p["outcome"] == "failed" and p["phase"] != "call" for p in phases):
            result = "error"
        elif any(p["outcome"] == "failed" for p in phases):
            result = "failed"
        elif any(p.get("expected_failure") for p in phases):
            result = "expected_failure"
        elif any(p["outcome"] == "skipped" for p in phases):
            result = "skipped"
        elif any(p["phase"] == "call" and p["outcome"] == "passed" for p in phases):
            result = "passed"
        else:
            result = "not_executed"
        statuses[identifier] = result
    counts = {status: sum(value == status for value in statuses.values()) for status in
        ("passed", "failed", "error", "skipped", "expected_failure", "not_executed")}
    status = "passed" if (completed.returncode == 0 and counts["passed"] > 0
        and all(value == 0 for name, value in counts.items() if name != "passed") and not changed) else "needs_review"
    rows = [{**row, "result": statuses[row["test_id"]],
        "evidence": "results/testing/execution_details.json#" + row["test_id"]} for row in detail["collected"]]
    save_csv("results/testing/requirement_test_map.csv", rows,
        ["requirement", "test_id", "fixture_version", "expected_outcome_source", "description", "result", "evidence"])
    save_csv("results/testing/manual_checks.csv", manifest["manual_checks"],
        ["check", "result", "evidence_type", "evidence", "notes"])
    findings = [{"check": p["test_id"], "kind": p["phase"], "status": "open",
        "finding": p["detail"], "evidence": "results/testing/pytest_output.log"}
        for p in detail["phases"] if p["outcome"] == "failed"]
    findings.extend({"check": p["test_id"], "kind": "collection", "status": "open",
        "finding": p["detail"], "evidence": "results/testing/pytest_output.log"}
        for p in detail.get("collection_errors", []))
    save_csv("results/testing/defect_log.csv", findings,
        ["check", "kind", "status", "finding", "evidence"])
    readiness = [{"area": "routine_suite", "status": status,
        "reason": "Executed controlled cases; model quality and live execution are separate."},
        *manifest["readiness_checks"]]
    save_csv("results/testing/readiness_checks.csv", readiness,
        ["area", "status", "reason"])
    pointer = json.loads((ROOT / "artifacts/language_model/active_resource_release.json").read_bytes())
    release = json.loads((ROOT / pointer["release_directory"] / "adopted_rules.json").read_bytes())
    summary = {"schema_version": "step30-testing-summary-1", "status": "controlled_tests_" + status,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "routine_suite": status,
        "collected_tests": len(detail["collected"]), "outcomes": counts,
        "executed_tests": len({p["test_id"] for p in detail["phases"] if p["phase"] == "call"}),
        "collection_errors": detail.get("collection_errors", []),
        "deselected_tests": len(detail.get("deselected", [])),
        "pytest_exit_code": completed.returncode, "new_model_calls": 0, "query_encoder_processes": 0,
        "previous_failure_archive": previous_failure,
        "source_files_changed": changed, "source_sha256": manifest["source_sha256"],
        "test_sha256": manifest["test_sha256"], "fixture_version": manifest["fixture_version"],
        "command": command[1:], "manual_evidence": "user_reports_from_step29",
        "manual_pending": [r["check"] for r in manifest["manual_checks"] if r["result"] != "passed"],
        "fresh_real_backend_checks": "not_run", "full_numerical_rule_coverage": "pending",
        "representative_pilot": "pending_step31", "independent_scoring_ready": False,
        "operational_generation_ready": False, "protocol_frozen": False,
        "source_adoption": {"release_directory": pointer["release_directory"],
            "rule_definitions": len(release["records"]),
            "all_rules_adopted": all(r.get("adoption_status") == "adopted_by_team_delegation" for r in release["records"])},
        "readiness_checks": readiness,
        "producer": {"runner_sha256": sha(Path(__file__)),
            "suite_manifest_sha256": sha(ROOT / "tests/fixtures/suite_manifest.json")},
        "package_versions": {name: metadata.version(name) for name in
            ("pytest", "streamlit", "jsonschema", "numpy", "pandas", "scikit-learn")},
        "reports": ["results/testing/test_report.xml", "results/testing/execution_details.json",
            "results/testing/requirement_test_map.csv", "results/testing/manual_checks.csv",
            "results/testing/defect_log.csv", "results/testing/readiness_checks.csv"]}
    save("results/step30_testing_summary.json", summary)
    print("Tests:", counts["passed"], "passed |", counts["failed"] + counts["error"],
          "failed |", counts["skipped"] + counts["expected_failure"] + counts["not_executed"], "not completed")
    print("Live model and complete rule checks: pending")
    print("Saved: results/step30_testing_summary.json")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
