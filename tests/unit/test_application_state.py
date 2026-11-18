"""We preserve saved plans, activity identity and completion across supported edits."""

from copy import deepcopy
import csv
import io
import json

import pytest

from app_fixtures import (VERSIONS, activity, change_duration, coded_check, exports,
    outcome, plan_response, public_profile, resolve_catalog, restore, saved_state,
    set_completed, state, validate_profile)


pytestmark = pytest.mark.requirement("30.9:application-state-editing-restoration")


def test_unchanged_session_keeps_completion_and_original_response():
    workspace = saved_state()
    set_completed(workspace)
    original = state.current_plan(workspace)
    changed = change_duration(workspace)
    assert changed["plan_version"] != original["plan_version"]
    assert workspace["plans"][original["plan_version"]]["response"] == original["response"]
    assert state.progress_summary(workspace) == {
        "completed": 1, "pending": 2, "skipped": 0, "total": 3, "completed_percent": 33.3}
    assert changed["check_report"]["execution_status"] == "completed"
    assert changed["model_review_stale"] is True
    assert state.assessment_current(workspace, VERSIONS) is False


def test_editing_completed_session_resets_only_its_own_progress():
    workspace = saved_state()
    set_completed(workspace)
    set_completed(workspace, "saturday")
    change_duration(workspace, "monday")
    statuses = {x["activity_id"]: x["status"] for x in state.trackable_sessions(workspace)}
    assert statuses == {"monday": "pending", "wednesday": "pending", "saturday": "completed"}
    assert any(x["status"] == "completed" for x in workspace["progress_history"])


def test_checklist_update_does_not_change_plan_hash_or_review():
    workspace = saved_state()
    before = deepcopy(state.current_plan(workspace))
    set_completed(workspace)
    item = state.trackable_sessions(workspace)[1]
    state.update_progress(workspace, item["occurrence_id"], "skipped")
    assert state.current_plan(workspace) == before
    assert state.progress_summary(workspace)["total"] == 3
    assert state.progress_summary(workspace)["skipped"] == 1


def test_progress_counts_existing_practice_but_not_travel_or_components():
    public, candidate = public_profile(), plan_response()
    public["input"]["existing_commitments"] = [
        {"date": "2026-11-16", "description": "Existing basketball practice", "activity_type": "organized_basketball",
            "activity_kind": "practice", "start_time": "17:30", "end_time": "17:50"},
        {"date": "2026-11-17", "description": "School travel", "activity_type": "nontraining",
            "activity_kind": "travel", "start_time": "17:30", "end_time": "17:50"}]
    candidate["weekly_schedule"][0]["activities"][0]["existing_commitment_refs"] = ["/existing_commitments/0"]
    candidate["weekly_schedule"][0]["activities"].append(activity("included-drill", parent="monday"))
    candidate["weekly_schedule"][1]["activities"].append(activity("travel", refs=["/existing_commitments/1"], description="School travel"))
    workspace = saved_state(public=public, candidate=candidate)
    assert {x["activity_id"] for x in state.trackable_sessions(workspace)} == {"monday", "wednesday", "saturday"}


def test_empty_week_has_no_completion_percentage():
    candidate = plan_response()
    for day in candidate["weekly_schedule"]:
        day["activities"] = []
    assert state.progress_summary(saved_state(candidate=candidate)) == {
        "completed": 0, "pending": 0, "skipped": 0, "total": 0, "completed_percent": None}


def test_reordered_rows_preserve_progress_without_changing_planning_hash():
    workspace = saved_state()
    set_completed(workspace)
    original = state.current_plan(workspace)
    response = deepcopy(original["response"])
    response["weekly_schedule"].reverse()
    assert state.planning_content_hash(response) == original["content_hash"]
    reordered = state.build_plan_snapshot(state.current_profile(workspace), response, source_versions=VERSIONS)
    state.install_plan(workspace, reordered)
    assert state.progress_summary(workspace)["completed"] == 1


def test_existing_commitments_and_source_fields_cannot_be_edited():
    public, candidate = public_profile(), plan_response()
    public["input"]["existing_commitments"] = [{"date": "2026-11-16", "description": "Practice",
        "activity_type": "organized_basketball", "activity_kind": "practice", "start_time": "17:30", "end_time": "17:50"}]
    candidate["weekly_schedule"][0]["activities"][0]["existing_commitment_refs"] = ["/existing_commitments/0"]
    workspace = saved_state(public=public, candidate=candidate)
    before = deepcopy(workspace)
    with pytest.raises(ValueError, match="Existing commitments"):
        change_duration(workspace, "monday")
    with pytest.raises(ValueError, match="Only activity IDs"):
        state.save_plan_changes(workspace, [{"activity_id": "wednesday", "description": "Unreviewed instructions"}],
            resolve_catalog, coded_check, VERSIONS)
    assert workspace == before


def test_catalog_replacement_gets_new_identity_and_authoritative_sources():
    workspace = saved_state()
    set_completed(workspace, "saturday")
    updated = state.save_plan_changes(workspace,
        [{"activity_id": "saturday", "replacement_id": "catalog:approved-fixture"}],
        resolve_catalog, coded_check, VERSIONS)
    replacement = next(x for x in state.trackable_sessions(workspace) if x["date"] == "2026-11-21")
    assert replacement["activity_id"] != "saturday"
    assert replacement["status"] == "pending"
    assert replacement["activity"]["description"] == "Authoritative passing activity instructions."
    assert replacement["activity"]["evidence_refs"] == ["catalog:approved-fixture", "https://example.org/authored-passing-source"]
    assert updated["edits"][0]["replacement_activity_id"] == replacement["activity_id"]


def test_snapshot_restores_edits_and_progress_but_not_current_assessment():
    workspace = saved_state()
    set_completed(workspace)
    change_duration(workspace)
    checks = []
    def checker(*args):
        checks.append(args)
        return coded_check(*args)
    snapshot = exports.export_snapshot(workspace, VERSIONS)
    restored = restore(snapshot, check_plan=checker)
    assert state.current_plan(restored)["response"] == state.current_plan(workspace)["response"]
    assert state.progress_summary(restored)["completed"] == 1
    assert len(checks) == 1
    assert state.assessment_current(restored, VERSIONS) is False
    assert restored["restore_status"]["coded_checks_recomputed"] is True
    assert all(item["historical"] is True for item in restored["assessments"])
    assert restored["session_id"] != workspace["session_id"]
    assert restored["jobs"] == {}


def test_snapshot_excludes_raw_jobs_and_rejects_tampered_content():
    workspace = saved_state()
    payload = json.loads(exports.export_snapshot(workspace, VERSIONS))
    assert "jobs" not in payload and "original_outcome" not in payload["plan"]
    assert "reference_packet" not in payload["plan"]
    payload["plan"]["response"]["weekly_schedule"][0]["activities"][0]["duration_minutes"] = 999
    with pytest.raises(ValueError, match="not bound"):
        restore(json.dumps(payload))
    for invalid in (b'{"a":1,"a":2}', b'{"a":NaN}', b'\xff'):
        with pytest.raises(ValueError):
            restore(invalid)


def test_changed_source_is_historical_readonly_but_new_checker_only_stales_review():
    workspace = saved_state()
    data = exports.export_snapshot(workspace, VERSIONS)
    readonly = restore(data, source_versions={**VERSIONS, "catalog": "unavailable-catalog-2"})
    assert state.current_plan(readonly)["historical_readonly"] is True
    compatible = restore(data, source_versions={**VERSIONS, "checker": "checker-2"})
    assert state.current_plan(compatible)["historical_readonly"] is False
    assert state.current_plan(compatible)["model_review_stale"] is True


def test_csv_preserves_rows_and_neutralizes_formula_prefixes():
    candidate = plan_response()
    candidate["weekly_schedule"][0]["activities"][0]["description"] = '=HYPERLINK("https://example.org")'
    workspace = saved_state(candidate=candidate)
    csv_data = exports.export_schedule_csv(workspace)
    rows = list(csv.DictReader(io.StringIO(csv_data.decode("utf-8-sig"))))
    assert len(rows) == 7
    first = next(row for row in rows if row.get("date") == "2026-11-16")
    assert any(value.startswith("'=") for value in first.values())


def test_late_result_is_saved_against_original_profile_and_failure_has_no_plan():
    workspace = state.new_state()
    state.save_profile(workspace, public_profile(), validate_profile)
    state.begin_job(workspace, "late-job")
    state.save_profile(workspace, public_profile("athlete:another-fixture"), validate_profile)
    attached = state.attach_outcome(workspace, "late-job", outcome(), source_versions=VERSIONS)
    assert attached["attached"] is False
    assert state.current_plan(workspace) is None
    assert attached["plan"]["profile_version"] != workspace["current_profile"]
    state.begin_job(workspace, "failed-job")
    failed = {**outcome(), "terminal_state": "execution_error", "completion_valid": False,
        "error": "Authored failed workflow"}
    assert state.attach_outcome(workspace, "failed-job", failed)["plan"] is None
    assert state.current_plan(workspace) is None
