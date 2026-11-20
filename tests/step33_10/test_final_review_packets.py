"""Check masked packets with fictional saved replies and no model transport."""

from copy import deepcopy
import json

import pytest

from champion_athletic_map import final_review_packets as packets
from champion_athletic_map import final_team_review_preparation as preparation


def config():
    return {"planned_review_sample": {"profiles": 40, "profiles_per_age": 8,
        "ages": list(range(13, 18)), "per_age_categories": {"feasible": 5, "missing_information": 1,
            "conflicting_constraints": 1, "outside_scope": 1},
        "independent_reviewers_per_response": 2, "planner_versions": 4, "initial_sampling_seed": 42},
        "dimensions": [{"id": key, "name": key, "anchors": ["Low", "Partial", "Complete"]}
            for key in packets.DIMENSIONS], "score_values": [0, 1, 2],
        "combined_quality_score": None, "new_passing_threshold": None}


@pytest.fixture
def saved(tmp_path):
    profiles, annotations, jobs, rows = [], [], [], []
    for age in range(13, 18):
        for category, count in (("feasible", 30), ("missing_information", 4),
                                ("conflicting_constraints", 3), ("outside_scope", 3)):
            for index in range(count):
                pid = "software-case-" + str(len(profiles))
                record = {"profile_id": pid, "schema_version": "software-only",
                    "input": {"age": age, "athlete_request": '<img src=x onerror="bad()"> Fictional request.'}}
                digest = packets.sha(packets.packed(record))
                profiles.append(record)
                annotations.append({"profile_id": pid, "case_authoring_accepted": True,
                    "public_record_sha256": digest, "case_category": category, "family_id": "family-" + pid})
                for version in range(1, 5):
                    jid = "software-job-" + str(len(jobs))
                    jobs.append({"job_id": jid, "profile_id": pid, "planner_version": version,
                        "public_record_sha256": digest, "execution_state": "not_started", "designated_final_outcome": None})
                    raw = '{"explanation":"Fictional saved reply.","evidence_refs":["https://source.example/"]}'
                    rows.append({"job_id": jid, "profile_id": pid, "planner_version": version,
                        "public_record_sha256": digest, "public_input": deepcopy(record["input"]),
                        "outcome_sha256": packets.sha(packets.canonical({"raw_text": raw})),
                        "raw_text": raw, "raw_text_sha256": packets.sha(raw.encode("utf-8")),
                        "case_category": category, "internal_review": "Private synthetic review field."})
    output = preparation.prepare_components(profiles, annotations, jobs, config(),
        case_freeze_id="software-freeze", reference_access=[])
    relative = "results/testing/software-review"
    folder = tmp_path / relative
    folder.mkdir(parents=True)
    bindings = {}
    for name, data in output["files"].items():
        (folder / name).write_bytes(data)
        bindings[relative + "/" + name] = packets.sha(data)
    manifest = {"manifest_id": "software-manifest", "case_freeze_id": "software-freeze",
        "software_fixture": True, "profiles": profiles, "planned_jobs": jobs,
        "protocol": {"review_source_sha256": deepcopy(bindings)}}
    setup = {"software_fixture": True, "case_freeze_id": "software-freeze",
        "team_review_package_directory": relative}
    return {"root": tmp_path, "manifest": manifest, "setup": setup, "rows": rows,
            "bindings": bindings, "folder": folder, "prepared": output}


def make(saved, **changes):
    args = {"source_bindings": saved["bindings"], "software_fixture": True, **changes}
    return packets.prepare_review_packets(saved["root"], saved["manifest"], saved["setup"], saved["rows"], **args)


def selected_result(saved):
    key = json.loads(saved["prepared"]["files"]["private_response_key.jsonl"].splitlines()[0])
    return next(row for row in saved["rows"] if row["job_id"] == key["job_id"])


def replace_prepared(saved, name, data):
    (saved["folder"] / name).write_bytes(data)
    relative = saved["setup"]["team_review_package_directory"] + "/" + name
    digest = packets.sha(data)
    saved["bindings"][relative] = digest
    saved["manifest"]["protocol"]["review_source_sha256"][relative] = digest


def test_existing_sample_populated_without_workflow_metadata(saved):
    result = make(saved)
    forms = [json.loads(row) for row in result["public_files"]["review_responses.jsonl"].splitlines()]
    assert len(forms) == 160
    assert all(set(row) == {"response_id", "athlete_input", "response_state", "response_text", "response_citations"} for row in forms)
    combined = b"\n".join(result["public_files"].values()).decode("utf-8")
    assert not any(row["profile_id"] in combined for row in saved["manifest"]["profiles"])
    assert "Private synthetic review field." not in combined
    assert result["summary"]["actual_response_ratings"] == result["summary"]["actual_assigned_reviewers"] == 0
    assert result["summary"]["existing_pre_output_sample_reused"] is True
    assert result["summary"]["new_sample_selected"] is False


def test_exact_reply_text_and_citations_preserved_and_html_escaped(saved):
    row = selected_result(saved)
    raw = '{"explanation":"<script>bad()</script> Café Ω 🏀",\n"evidence_refs":["https://source.example/"],"food_facts":[{"source_ref":"record:one"}]}'
    row.update(raw_text=raw, raw_text_sha256=packets.sha(raw.encode("utf-8")))
    result = make(saved)
    forms = [json.loads(row) for row in result["public_files"]["review_responses.jsonl"].splitlines()]
    form = next(item for item in forms if item["response_text"] == raw)
    assert form["response_citations"] == ["https://source.example/", "record:one"]
    for name in ("review_A.html", "review_B.html"):
        page = result["public_files"][name].decode("utf-8")
        assert "<script>bad()" not in page and "&lt;script&gt;bad()" in page
        assert "<img src=x" not in page and "&lt;img src=x" in page
    bound = [json.loads(value) for value in result["private_files"]["private_bound_response_key.jsonl"].splitlines()]
    assert next(item for item in bound if item["response_id"] == form["response_id"])["response_text_sha256"] == packets.sha(raw.encode("utf-8"))


def test_wrong_workflow_join_is_rejected(saved):
    row = selected_result(saved)
    row["planner_version"] = 5
    with pytest.raises(ValueError, match="another case or workflow"):
        make(saved)


def test_stale_public_input_is_rejected(saved):
    selected_result(saved)["public_input"]["age"] = 17
    with pytest.raises(ValueError, match="another public case version"):
        make(saved)


def test_changed_reply_text_hash_is_rejected(saved):
    selected_result(saved)["raw_text"] = "Changed after reading."
    with pytest.raises(ValueError, match="reply-text hash"):
        make(saved)


def test_changed_pre_output_preparation_is_rejected(saved):
    path = saved["folder"] / "private_response_key.jsonl"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="preselected review file changed"):
        make(saved)


def test_duplicate_mask_is_rejected(saved):
    keys = [json.loads(row) for row in saved["prepared"]["files"]["private_response_key.jsonl"].splitlines()]
    keys[1]["response_id"] = keys[0]["response_id"]
    replace_prepared(saved, "private_response_key.jsonl", packets.jsonl(keys))
    with pytest.raises(ValueError, match="masks are incomplete or duplicated"):
        make(saved)


def test_presentation_orders_are_the_prepared_orders(saved):
    result = make(saved)
    assignments = json.loads(saved["prepared"]["files"]["private_reviewer_assignments.json"])
    for item in assignments:
        name = "review_" + item["reviewer_slot_id"].rsplit("-", 1)[-1] + ".html"
        page = result["public_files"][name].decode("utf-8")
        positions = [page.index('<article id="' + identifier + '">') for identifier in item["presentation_order"]]
        assert positions == sorted(positions)


def test_blank_rating_templates_cannot_be_promoted_to_scores(saved):
    values = [json.loads(row) for row in saved["prepared"]["files"]["rating_templates_pending.jsonl"].splitlines()]
    values[0].update(rating_status="rated", score=0)
    replace_prepared(saved, "rating_templates_pending.jsonl", packets.jsonl(values))
    with pytest.raises(ValueError, match="entered or imputed ratings"):
        make(saved)


def test_no_reply_is_not_filled_or_scored(saved):
    selected_result(saved).update(raw_text=None, raw_text_sha256=None)
    result = make(saved)
    forms = [json.loads(row) for row in result["public_files"]["review_responses.jsonl"].splitlines()]
    missing = [row for row in forms if row["response_state"] == "no_reply_text"]
    assert len(missing) == 1 and missing[0]["response_text"] is None
    assert "No reply text was returned." in result["public_files"]["review_A.html"].decode("utf-8")
    assert result["summary"]["actual_response_ratings"] == 0


def test_fixture_cannot_stand_in_for_production_review(saved):
    with pytest.raises(ValueError, match="software fixture"):
        make(saved, software_fixture=False)


def test_citation_extraction_does_not_silently_accept_duplicate_json_keys():
    assert packets.citations('{"source_ref":"a","source_ref":"b"}') is None


def test_repeat_preparation_is_identical(saved):
    assert make(saved) == make(saved)
