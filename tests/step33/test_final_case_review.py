"""Case-review checks use isolated software fixtures and never run a planner."""

from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sys

import pytest


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def _source_root():
    configured = os.environ.get("CHAMPION_STEP33_SOURCE_ROOT")
    roots = ([Path(configured)] if configured else [])
    for base in (Path.cwd(), Path(__file__).resolve().parent):
        roots.extend((base, *base.parents))
    for root in roots:
        if (root / "results/profile_preparation/review_workspace_95c5163bfa1213fc/step16_provisional_checkpoint.json").is_file():
            return root.resolve()
    raise AssertionError("The saved profile-preparation sources are required.")


@pytest.fixture(scope="session")
def source_root():
    return _source_root()


@pytest.fixture(scope="session")
def review(source_root):
    configured = os.environ.get("CHAMPION_STEP33_MODULE")
    paths = ([Path(configured)] if configured else []) + [
        source_root / "src/champion_athletic_map/final_case_review.py",
        Path(__file__).with_name("final_case_review.py")]
    path = next((path for path in paths if path.is_file()), None)
    assert path is not None, "The case-review implementation is required."
    return _module(path, "step33_review_candidate")


def _artificial_step32_summary():
    return {"fixture_label": "Artificial metadata for software checks only",
        "schema_version": "heldout-classifier-evaluation-1", "status": "complete", "all_models_complete": True,
        "injected_test_dependencies": False,
        "protocol_id": "020a5ce67c9ecc046548479c8bd17ee1fa51cfd3912457340924bef11a9fb49f",
        "records": 438, "groups": 385, "class_count": 16,
        "evaluation_id": "artificial_completion_fixture", "summary_path": "results/classifier_test/heldout_artificial/summary.json",
        "model_training_calls": 0, "application_selection_changed": False, "planner_inputs_changed": False,
        "models": {family: {"records": 438, "macro_f1": 0.0, "accuracy": 0.0}
                   for family in ("majority", "logistic_regression", "neural")}}


def _put_summary(root, value):
    path = root / "results/step32_classifier_test_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    saved = root / value["summary_path"]
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_bytes(path.read_bytes())
    opaque = saved.parent / "artificial_prediction_payload.jsonl"
    opaque.write_bytes(b"Artificial opaque prediction bytes; do not parse as a classifier result.\n")
    receipt = {"evaluation_id": value["evaluation_id"], "files": {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in (path, saved, opaque)}}
    (saved.parent / "completed.json").write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("key,value", [("status", "incomplete"), ("all_models_complete", False),
    ("injected_test_dependencies", True), ("protocol_id", "artificial_unapproved_protocol"),
    ("records", 437), ("groups", 384), ("class_count", 15), ("schema_version", "unrecognized")])
def test_incomplete_or_unapproved_step32_stops_before_profile_inputs(review, tmp_path, monkeypatch, key, value):
    summary = _artificial_step32_summary()
    summary[key] = value
    _put_summary(tmp_path, summary)
    def protected_inputs(*_args, **_kwargs):
        raise AssertionError("The case inputs were read before the Step32 preflight passed.")
    monkeypatch.setattr(review, "load_sources", protected_inputs)
    with pytest.raises(ValueError):
        review.execute(tmp_path, emit=lambda _message: None)
    assert not (tmp_path / "results/step33_preparation_summary.json").exists()


@pytest.mark.parametrize("defect", ["missing_family", "extra_family", "partial_family"])
def test_step32_requires_the_same_complete_three_model_population(review, tmp_path, defect):
    summary = _artificial_step32_summary()
    if defect == "missing_family":
        summary["models"].pop("neural")
    elif defect == "extra_family":
        summary["models"]["unselected_model"] = {"records": 438}
    else:
        summary["models"]["neural"]["records"] = 437
    _put_summary(tmp_path, summary)
    with pytest.raises(ValueError):
        review.verify_step32(tmp_path)


def test_missing_step32_summary_prevents_case_access(review, tmp_path, monkeypatch):
    def protected_inputs(*_args, **_kwargs):
        raise AssertionError("The case inputs were read without the Step32 result.")
    monkeypatch.setattr(review, "load_sources", protected_inputs)
    with pytest.raises((ValueError, FileNotFoundError)):
        review.execute(tmp_path, emit=lambda _message: None)
    assert not (tmp_path / "results/step33_preparation_summary.json").exists()


def test_step32_preflight_keeps_classifier_prediction_payloads_opaque(review, tmp_path, monkeypatch):
    summary_path = _put_summary(tmp_path, _artificial_step32_summary())
    original = Path.read_bytes
    touched = []
    def recorded(path):
        touched.append(path.resolve())
        return original(path)
    original_json = review.read_json
    def guarded_json(data):
        if b"Artificial opaque prediction bytes" in data:
            raise AssertionError("Classifier predictions were parsed during case preparation.")
        return original_json(data)
    monkeypatch.setattr(Path, "read_bytes", recorded)
    monkeypatch.setattr(review, "read_json", guarded_json)
    result = review.verify_step32(tmp_path)
    assert summary_path.resolve() in touched
    assert any(path.name == "artificial_prediction_payload.jsonl" for path in touched)
    assert result["predictions_parsed"] is False
    assert result["classification_scores_used_for_planner_preparation"] is False


def _jsonl(rows):
    return b"".join((json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode() for row in rows)


@pytest.fixture
def artificial_cases(review, tmp_path, monkeypatch):
    """All 200 records and every reference here are invented software inputs."""
    root = tmp_path.resolve()
    (root / ".gitignore").write_text("/results/final_case_review/\n", encoding="utf-8")
    records, rows = [], []
    for age in range(13, 18):
        for category, count in review.CATEGORIES.items():
            for index in range(count // 5):
                identifier = f"artificial-{age}-{category}-{index}"
                record = {"profile_id": identifier, "schema_version": "athlete-profile-input-1", "input": {
                    "age": age, "athlete_request": "Artificial request for " + identifier,
                    "planning_window": {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"},
                    "existing_commitments": [], "availability": None}}
                if not records:
                    record["input"]["athlete_request"] = "Artificial <script>alert('test')</script> request"
                records.append(record)
                rows.append({"profile_id": identifier, "partition": "test", "record_sha256": review.sha(review.packed(record)),
                    "scenario_intent": category, "proposed_family_id": "artificial-family-" + str(len(rows) // 2)})
    digest = "artificial-draft-digest-no-study-data"
    content = {review.PROTECTED + "/protected_test_draft_inputs.jsonl": _jsonl(records),
        review.PROTECTED + "/protected_test_draft_manifest.csv": review.csv_bytes(rows, list(rows[0])),
        review.PROTECTED + "/protected_test_field_lineage.csv": b"profile_id,field\nartificial,artificial_field\n"}
    for name in ("profile_annotation_WORKSHEETS.jsonl", "profile_feasibility_WORKSHEETS.jsonl"):
        values = [{"profile_id": record["profile_id"], "partition": "test", "approved": False,
            "annotation_status": "not_prepared", "record_sha256": row["record_sha256"],
            "input_sha256": review.sha(review.packed(record["input"])), "draft_digest": digest,
            "private_marker": "Private artificial expectations stay outside public inputs."}
            for record, row in zip(records, rows)]
        content[review.WORKSPACE + "/" + name] = _jsonl(values)
    for name in ("private_annotation_worksheet_schema.json", "private_feasibility_worksheet_schema.json", "future_acceptance_requirements.json"):
        content[review.WORKSPACE + "/" + name] = review.packed({"fixture": "artificial", "accepted": False})
    case_template = [{"profile_id": record["profile_id"], "record_sha256": row["record_sha256"],
        "input_sha256": review.sha(review.packed(record["input"])), "input_json": json.dumps(record["input"], sort_keys=True)}
        for record, row in zip(records, rows)]
    content[review.WORKSPACE + "/protected_case_review_TEMPLATE.csv"] = review.csv_bytes(case_template, list(case_template[0]))
    family_ids = sorted({row["proposed_family_id"] for row in rows})
    family_template = [{"proposed_family_id": family, "member_profile_ids_json": json.dumps([
        row["profile_id"] for row in rows if row["proposed_family_id"] == family])} for family in family_ids]
    content[review.WORKSPACE + "/protected_family_proposals_TEMPLATE.csv"] = review.csv_bytes(family_template, list(family_template[0]))
    pair_template = [{"candidate_profile_id": record["profile_id"], "candidate_record_sha256": row["record_sha256"],
        "candidate_input_sha256": review.sha(review.packed(record["input"]))} for record, row in zip(records, rows)]
    content[review.WORKSPACE + "/protected_pair_review_evidence_TEMPLATE.csv"] = review.csv_bytes(pair_template, list(pair_template[0]))
    resource_folder = "artifacts/artificial_resources"
    for name in ("adopted_drills.json", "adopted_rules.json", "manifest.json"):
        content[resource_folder + "/" + name] = review.packed({"fixture": "artificial", "records": []})
    retrieval = {"fixture": "Artificial retrieval metadata; not study results", "selected_route": "semantic", "reference_units": 11,
        "heldout_questions": 30, "ranking_eligible_questions": 24, "empty_relevant_sets": 6,
        "route_metrics": [{"mean_recall_at_5": 1.0, "mrr_at_5": 0.9791666666666666}]}
    for name, value in (("step23_retrieval_evaluation_summary.json", retrieval),
                        ("retrieval_handoff.json", {"fixture": "artificial", "scope": "eleven_reference_scoped_pilot_and_benchmark"}),
                        ("frozen_method_evaluation.json", {"fixture": "artificial", "selected_route": "semantic"})):
        content[review.RETRIEVAL + "/" + name] = review.packed(value)
    for name, data in content.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    source = {"bindings": {name: review.sha(data) for name, data in content.items()}, "content": content,
        "protected": {"draft_digest": digest}, "workspace": {}, "resources": {}, "resource_folder": resource_folder,
        "drills": {}, "rules": {}, "retrieval": retrieval, "retrieval_handoff": {"fixture": "artificial"}}
    monkeypatch.setattr(review, "load_sources", lambda _root: copy.deepcopy(source))
    deps = {"verify_step32": lambda _root: {"fixture": "artificial-completion-metadata", "predictions_parsed": False}}
    return {"root": root, "source": source, "records": records, "rows": rows, "dependencies": deps}


def test_two_hundred_case_package_keeps_exact_public_copies_and_private_boundary(review, artificial_cases):
    fixture = artificial_cases
    summary = review.execute(fixture["root"], dependencies=fixture["dependencies"], emit=lambda _message: None)
    folder = fixture["root"] / summary["package_directory"]
    assert summary["review_cases"] == 200
    assert summary["injected_test_dependencies"] is True
    assert "software_fixture_" in summary["package_directory"]
    assert summary["summary_path"] == "results/step33_fixture_summary.json"
    assert not (fixture["root"] / "results/step33_preparation_summary.json").exists()
    assert (folder / "source_public_profiles.jsonl").read_bytes() == fixture["source"]["content"][review.PROTECTED + "/protected_test_draft_inputs.jsonl"]
    original_public = [json.loads(line) for line in (folder / "source_public_profiles.jsonl").read_bytes().splitlines()]
    assert original_public == fixture["records"]
    assert all(set(row) == {"profile_id", "schema_version", "input"} for row in original_public)
    assert b"private_marker" not in (folder / "source_public_profiles.jsonl").read_bytes()
    for name in ("profile_annotation_WORKSHEETS.jsonl", "profile_feasibility_WORKSHEETS.jsonl"):
        private = [json.loads(line) for line in (folder / "draft_templates" / name).read_bytes().splitlines()]
        assert len(private) == 200 and {row["profile_id"] for row in private} == {row["profile_id"] for row in original_public}
        assert all(row["approved"] is False and row["annotation_status"] == "not_prepared" for row in private)
        assert all("private_marker" in row for row in private)
    proposals = [json.loads(line) for line in (folder / "migration_proposals.jsonl").read_bytes().splitlines()]
    assert len(proposals) == 200
    for proposal, original in zip(proposals, fixture["records"]):
        assert proposal["authorized_for_model_use"] is False
        assert proposal["human_authored_completeness_decision"] is None
        migrated = proposal["proposed_public_record"]
        assert migrated["schema_version"] == "athlete-profile-input-2"
        assert migrated["input"]["schedule_coverage"] is None
        assert {key: value for key, value in migrated["input"].items() if key != "schedule_coverage"} == original["input"]
    for name in ("source_manifest.csv", "source_field_lineage.csv"):
        source_name = "/protected_test_draft_manifest.csv" if name == "source_manifest.csv" else "/protected_test_field_lineage.csv"
        assert (folder / name).read_bytes() == fixture["source"]["content"][review.PROTECTED + source_name]
    html = (folder / "case_cards.html").read_text(encoding="utf-8")
    assert html.count('<article id="case-') == 200
    assert "<script>alert" not in html and "&lt;script&gt;alert" in html
    assert "Unaccepted draft" in html and "not approved" in html


def test_package_has_no_invented_review_approval_predictions_or_generation(review, artificial_cases):
    fixture = artificial_cases
    summary = review.execute(fixture["root"], dependencies=fixture["dependencies"], emit=lambda _message: None)
    assert summary["accepted_final_profiles"] == summary["human_reviews_entered"] == summary["human_ratings_created"] == 0
    assert summary["final_planner_execution_authorized"] is False
    assert summary["new_model_calls"] == summary["new_query_encodings"] == 0
    assert summary["original_candidate_inputs_changed"] is False and summary["classifier_predictions_parsed"] is False
    folder = fixture["root"] / summary["package_directory"]
    import csv
    with (folder / "working/review_decisions.csv").open(newline="", encoding="utf-8") as handle:
        decisions = list(csv.DictReader(handle))
    assert len(decisions) == 200
    for row in decisions:
        assert row["review_status"] == "not_entered"
        assert all(row[key] == "" for key in ("case_decision", "adopted_category", "actual_family_id", "expected_response_type",
            "existing_commitments_complete_decision", "prepared_by", "prepared_at", "reviewed_by", "reviewed_at", "feasibility_record_ref"))


def test_rerun_preserves_mutable_review_work_and_all_source_snapshots(review, artificial_cases):
    fixture = artificial_cases
    summary = review.execute(fixture["root"], dependencies=fixture["dependencies"], emit=lambda _message: None)
    folder = fixture["root"] / summary["package_directory"]
    working = folder / "working/review_decisions.csv"
    updated = working.read_bytes() + b"\n# Artificial reviewer note retained by rerun.\n"
    working.write_bytes(updated)
    before = {path.relative_to(folder): path.read_bytes() for path in folder.rglob("*") if path.is_file()}
    repeated = review.execute(fixture["root"], dependencies=fixture["dependencies"], emit=lambda _message: None)
    assert repeated == summary
    assert all((folder / name).read_bytes() == data for name, data in before.items())
    assert working.read_bytes() == updated
    assert all((fixture["root"] / name).read_bytes() == data for name, data in fixture["source"]["content"].items())


def test_changed_immutable_review_snapshot_is_rejected_without_overwrite(review, artificial_cases):
    fixture = artificial_cases
    summary = review.execute(fixture["root"], dependencies=fixture["dependencies"], emit=lambda _message: None)
    folder = fixture["root"] / summary["package_directory"]
    path = folder / "source_public_profiles.jsonl"
    changed = path.read_bytes() + b"\nChanged immutable source fixture.\n"
    path.write_bytes(changed)
    with pytest.raises(ValueError, match="immutable"):
        review.execute(fixture["root"], dependencies=fixture["dependencies"], emit=lambda _message: None)
    assert path.read_bytes() == changed


def test_saved_retrieval_evidence_is_reused_with_its_scoped_denominators(review, artificial_cases):
    fixture = artificial_cases
    summary = review.execute(fixture["root"], dependencies=fixture["dependencies"], emit=lambda _message: None)
    assert summary["retrieval_results_reused"] is True
    assert summary["retrieval_scope"] == {"reference_units": 11, "heldout_questions": 30,
        "ranking_eligible": 24, "complete_evidence": 20, "empty_relevant": 6, "selected_route": "semantic"}
    folder = fixture["root"] / summary["package_directory"]
    assert (folder / "reference_snapshot/retrieval_summary.json").read_bytes() == fixture["source"]["content"][review.RETRIEVAL + "/step23_retrieval_evaluation_summary.json"]
    assert (folder / "reference_snapshot/retrieval_handoff.json").read_bytes() == fixture["source"]["content"][review.RETRIEVAL + "/retrieval_handoff.json"]
    note = (folder / "README.md").read_text(encoding="utf-8")
    assert "already completed" in note and "11 admitted reference units" in note
    assert "does not establish coverage" in note


def test_corrupt_preparation_hash_stops_before_candidate_decoding(review, tmp_path, monkeypatch):
    root = tmp_path.resolve()
    original = b'{"private_candidate_fixture":"must not decode"}\n'
    changed = original + b"corrupted"
    name = "protected_test_draft_inputs.jsonl"
    protected = {"accepted_final_profiles": 0, "final_profiles_frozen": False,
        "artifacts": {name: review.sha(original)}}
    workspace = {"accepted_profiles": 0, "human_review_decisions_recorded": 0, "artifacts": {}}
    for relative, data in ((review.PROTECTED + "/step16_protected_test_drafts_summary.json", review.packed(protected)),
        (review.WORKSPACE + "/step16_review_workspace_summary.json", review.packed(workspace)), (review.PROTECTED + "/" + name, changed)):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    parse = review.read_json
    def guarded(data):
        if b"private_candidate_fixture" in data:
            raise AssertionError("Candidate records were decoded before verifying their saved hash.")
        return parse(data)
    monkeypatch.setattr(review, "read_json", guarded)
    with pytest.raises(ValueError, match="source changed"):
        review.execute(root, dependencies={"verify_step32": lambda _root: {"fixture": True}}, emit=lambda _message: None)
    assert not (root / "results/final_case_review").exists()


@pytest.mark.parametrize("defect", ["missing_record", "duplicate_id", "record_hash", "wrong_age", "private_approval"])
def test_invalid_candidate_or_private_join_is_rejected_before_output(review, artificial_cases, defect):
    fixture = artificial_cases
    source, records, rows = fixture["source"], copy.deepcopy(fixture["records"]), copy.deepcopy(fixture["rows"])
    name = review.PROTECTED + "/protected_test_draft_inputs.jsonl"
    if defect == "missing_record":
        records.pop()
    elif defect == "duplicate_id":
        records[-1]["profile_id"] = records[0]["profile_id"]
    elif defect == "wrong_age":
        records[-1]["input"]["age"] = 18
    elif defect == "record_hash":
        rows[-1]["record_sha256"] = "0" * 64
        name = review.PROTECTED + "/protected_test_draft_manifest.csv"
    else:
        name = review.WORKSPACE + "/profile_annotation_WORKSHEETS.jsonl"
        private = [json.loads(line) for line in source["content"][name].splitlines()]
        private[-1]["approved"] = True
    data = (review.csv_bytes(rows, list(rows[0])) if defect == "record_hash"
            else _jsonl(private) if defect == "private_approval" else _jsonl(records))
    source["content"][name] = data
    source["bindings"][name] = review.sha(data)
    (fixture["root"] / name).write_bytes(data)
    with pytest.raises(ValueError):
        review.execute(fixture["root"], dependencies=fixture["dependencies"], emit=lambda _message: None)
    assert not (fixture["root"] / "results/final_case_review").exists()
