"""Measure prospective revision inputs and food checks without making model calls."""

from copy import deepcopy
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from uuid import uuid4


VERSION = "saved-reviewed-probe-offline-corrections-1"
SOURCE_SUMMARY = "results/step31_reviewed_probe_summary.json"
SUMMARY = "results/step31_offline_corrections_summary.json"
NEW_COMPONENTS = ("offline_corrections", "bounded_revision", "food_response_validation", "corrected_runtime")
OLD_COMPONENTS = ("reviewed_preparation", "operational_preparation", "pilot_probe", "review_encoding",
                  "context_encoding", "food_reference_encoding", "food_fact_focus", "independent_food",
                  "reviewed_planning_checks", "live_reviewed_runtime", "reviewed_runtime")


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
                raise ValueError("A saved correction input has duplicate JSON keys.")
            result[key] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("A correction input is nonfinite.")))


def checked(root, relative):
    text = str(relative).replace("\\", "/")
    path = (root / text).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("A saved correction source is unavailable: " + text)
    return path


def verify(root, bindings):
    for relative, expected in bindings.items():
        if sha(checked(root, relative).read_bytes()) != expected:
            raise ValueError("A saved correction source changed: " + relative)


def module(root, name):
    path = checked(root, "src/champion_athletic_map/" + name + ".py")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("offline_corrections_" + name, path))
    result.__spec__.loader.exec_module(result)
    return result


def save_once(path, value):
    data = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("An earlier correction record differs and was preserved: " + path.name)
    else:
        with path.open("xb") as handle:
            handle.write(data)


def _bind(root, path, bindings):
    path = path.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("A correction source leaves the project or is unavailable.")
    bindings[path.relative_to(root).as_posix()] = sha(path.read_bytes())


def load_saved(root):
    """Validate the sixteen designated outcomes and their original packet receipts."""
    summary = read(checked(root, SOURCE_SUMMARY))
    if (summary.get("schema_version") != "reviewed-four-case-live-probe-1"
            or summary.get("reviewed_probe_completed") is not True
            or summary.get("recorded_jobs") != 16 or summary.get("completed_cases") != 4
            or summary.get("injected_test_dependencies") is not False or summary.get("stop_reason") is not None
            or len(summary.get("cases") or []) != 4
            or [c["case_index"] for c in summary["cases"]] != [13, 3, 4, 12]
            or len({c["profile_id"] for c in summary["cases"]}) != 4):
        raise ValueError("The complete production Step 31-14 probe is required for the offline correction.")
    bindings = {SOURCE_SUMMARY: sha((root / SOURCE_SUMMARY).read_bytes())}
    probe = module(root, "pilot_probe")
    rows, seen = [], set()
    for case in summary["cases"]:
        reports = case.get("reports") or []
        if len(reports) != 4 or {r["planner_version"] for r in reports} != {1, 2, 3, 4}:
            raise ValueError("A saved case lacks one designated outcome for each planner.")
        baseline = next(r for r in reports if r["planner_version"] == 1)
        baseline_outcome = read(checked(root, baseline["outcome_path"]))
        response = baseline_outcome.get("response") or {}
        public = response.get("authoritative_public_input")
        audit = response.get("audit") or {}
        if (not isinstance(public, dict) or audit.get("profile_id") != case["profile_id"]
                or sha(canonical(public)) != audit.get("public_input_sha256")
                or not isinstance(audit.get("profile_schema_version"), str)):
            raise ValueError("The saved baseline has no unchanged authoritative athlete input.")
        public_record = {"profile_id": case["profile_id"], "schema_version": audit["profile_schema_version"], "input": public}
        packets, case_rows = [], []
        for report in reports:
            path = checked(root, report["outcome_path"])
            if report["job_id"] in seen:
                raise ValueError("A designated outcome is duplicated.")
            seen.add(report["job_id"])
            outcome = read(path)
            record_path, request_path = path.with_name("job_record.json"), path.with_name("job_request.json")
            record, job_request = read(record_path), read(request_path)
            if (sha(canonical(outcome)) != report["assessment"]["designated_outcome_sha256"]
                    or sha(canonical(public)) != report["assessment"]["public_input_sha256"]
                    or record["outcome"] != report["outcome"]
                    or job_request["job"]["job_id"] != report["job_id"]
                    or record["planner_version"] != report["planner_version"]):
                raise ValueError("A designated saved outcome differs from the supplied probe summary.")
            manifest = {"manifest_id": record["manifest_id"], "public_record": public_record,
                        "public_record_sha256": sha(canonical(public_record))}
            probe.verify_job(root, manifest, job_request["job"], path.parent, record)
            for source in (path, record_path, request_path):
                _bind(root, source, bindings)
            supplied = (outcome.get("response") or {}).get("authoritative_public_input")
            if supplied is not None and canonical(supplied) != canonical(public):
                raise ValueError("A saved reply contains different authoritative athlete facts.")
            folder = path.parent.parents[1]
            if report["planner_version"] != 1:
                reference_folder = folder / "references" / report["job_id"]
                packet = read(reference_folder / "packet.json")
                packets.append(packet)
                for source in reference_folder.rglob("*"):
                    if source.is_file():
                        _bind(root, source, bindings)
            case_rows.append({"case_index": case["case_index"], "profile_id": case["profile_id"],
                "report": report, "outcome": outcome, "outcome_path": report["outcome_path"],
                "probe_folder": folder, "public": public, "public_record": public_record})
        if len(packets) != 3 or any(canonical(p) != canonical(packets[0]) for p in packets[1:]):
            raise ValueError("The three reference-supported outcomes have different saved source packets.")
        for row in case_rows:
            row["packet"] = packets[0]
            rows.append(row)
    if len(seen) != 16:
        raise ValueError("The offline correction requires exactly sixteen unique designated outcomes.")
    return summary, rows, bindings


def _revision_requests(root, rows, counter, bounded, bindings):
    decoder = module(root, "review_encoding")
    candidate_decoder = module(root, "context_encoding")
    measured = []
    for row in rows:
        if row["report"]["planner_version"] != 4:
            continue
        event_path = row["probe_folder"] / "http_events.jsonl"
        events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        _bind(root, event_path, bindings)
        for stage in row["outcome"].get("roles") or []:
            if stage["stage"] != "revision":
                continue
            role = stage["result"]
            context, call_id = role.get("context") or {}, role["call_id"]
            captured = [event for event in events if event.get("call_id") == call_id
                        and event.get("phase") == "render" and event.get("event") == "http_started"]
            if len(captured) != 1:
                raise ValueError("A saved revision lacks its single complete captured render request.")
            path = checked(root, captured[0]["request_path"])
            if sha(path.read_bytes()) != captured[0].get("request_sha256"):
                raise ValueError("A captured revision request differs from its recorded transport hash.")
            request = read(path)
            if request.pop("_debug_render_only", None) is not True:
                raise ValueError("The captured revision must be its original render-only request.")
            _bind(root, path, bindings)
            old_render = bounded.recorded_render(request)
            old_body = counter.count(old_render)
            if (sha(wire(request)) != context.get("request_sha256")
                    or sha(old_render.encode("utf-8")) != context.get("rendered_prompt_sha256")
                    or old_body != context.get("rendered_body_tokens")
                    or context.get("rendered_bos_present") is not False
                    or context.get("backend_added_system_prefix") != "" or context.get("backend_added_system_suffix") != ""
                    or request.get("options", {}).get("num_ctx") != 8192
                    or request.get("options", {}).get("num_predict") != 2048
                    or context.get("configured_context_tokens") != 8192 or context.get("output_reserve") != 2048
                    or context.get("safety_margin") != 256 or context.get("unverified_boundary_reserve") != 2
                    or context.get("input_ceiling_after_output_and_margin") != 5888
                    or context.get("local_input_tokens_with_boundary_reserve") != old_body + 2):
                raise ValueError("The original full revision render, count or unchanged budget cannot be reproduced.")
            original_view = read_json_text(request["messages"][1]["content"])
            if canonical(original_view.get("athlete_input")) != canonical(row["public"]):
                raise ValueError("A captured revision contains a different athlete input.")
            prepared = {"schema_version": "step24-prepared-public-input-1", "public_input": deepcopy(row["public"]),
                "model_visible_json": canonical(row["public"]).decode("utf-8"),
                "audit": {"public_input_sha256": sha(canonical(row["public"]))}}
            original_prepared = canonical(prepared)
            original_non_messages = canonical({k: v for k, v in request.items() if k != "messages"})
            original_system = request["messages"][0]["content"]
            original_wire_sha = sha(wire(request))
            prepared_after, candidate, configuration = bounded.transform_request(prepared, request,
                deepcopy(role["input_configuration"]), stage="revision", counter=None)
            new_view = read_json_text(candidate["messages"][1]["content"])
            retained = {key: value for key, value in original_view.items() if key != "specialist_notes"}
            if (canonical(new_view) != canonical(retained) or canonical(prepared_after) != original_prepared
                    or canonical({k: v for k, v in candidate.items() if k != "messages"}) != original_non_messages):
                raise ValueError("The bounded candidate altered more than its declared generated-note/system contract.")
            new_render = bounded.recorded_render(candidate)
            new_body = counter.count(new_render)
            decoded = decoder.decode_checks(original_view["check_results"])
            selected = candidate_decoder.decode_candidate(original_view["candidate"])
            history = [h for h in row["outcome"].get("history") or [] if h.get("candidate_id") == selected["candidate_id"]]
            if len(history) != 1:
                raise ValueError("The saved revision cannot be matched to its original checked candidate.")
            full_checks = history[0]["check_report"]["checks"]
            model_ids = [identifier for finding in decoded["findings"] for identifier in
                         finding[decoded["columns"].index("check_ids")]]
            if canonical(selected["parsed_object"]) != canonical(history[0]["candidate"]["response"]["model_output"]["parsed_object"]):
                raise ValueError("The original encoded candidate differs from its checked history entry.")
            measured.append({"case_index": row["case_index"], "call_id": call_id,
                "source_outcome_path": row["outcome_path"], "captured_request_path": path.relative_to(root).as_posix(),
                "original_underlying_request_wire_sha256": original_wire_sha,
                "old_render_sha256": sha(old_render.encode("utf-8")), "old_full_render_reproduced": True,
                "old_body_tokens": old_body, "old_input_tokens_including_boundary": old_body + 2,
                "old_was_blocked_by_input_budget": context["status"] == "context_overflow",
                "new_body_tokens": new_body, "new_input_tokens_including_boundary": new_body + 2,
                "new_request_bytes": len(wire(candidate)),
                "input_ceiling": 5888, "new_headroom": 5888 - new_body - 2,
                "new_fits_local_input_budget": new_body + 2 <= 5888,
                "native_schema_and_options_unchanged": True,
                "all_original_non_note_user_fields_preserved": True,
                "original_generated_notes_removed": "specialist_notes" in original_view,
                "removed_generated_notes": deepcopy(original_view.get("specialist_notes")),
                "removed_generated_notes_sha256": sha(canonical(original_view.get("specialist_notes"))),
                "original_system_text": original_system,
                "original_system_text_sha256": sha(original_system.encode("utf-8")),
                "omitting_generated_notes_is_a_declared_workflow_change": True,
                "full_check_report_rows": len(full_checks),
                "full_check_report_required_rows": sum(q.get("required") is True for q in full_checks),
                "check_report_basis": "original_internal_V4_check_report",
                "saved_independent_report_rows": len(row["report"]["assessment"]["checks"]),
                "saved_independent_report_required_rows": sum(q.get("required") is True
                    for q in row["report"]["assessment"]["checks"]),
                "original_model_check_view_rows": len(decoded["findings"]),
                "original_model_check_view_distinct_ids": len(set(model_ids)),
                "full_report_check_ids_represented_in_original_model_view": set(model_ids) == {q["check_id"] for q in full_checks},
                "original_model_check_view_preserved_exactly": new_view["check_results"] == original_view["check_results"],
                "new_candidate_request": candidate, "new_candidate_configuration": configuration,
                "new_backend_render_confirmed": False, "new_request_submitted": False})
    if (len(measured) != 5 or len({r["call_id"] for r in measured}) != 5
            or Counter(r["case_index"] for r in measured) != Counter({13: 1, 3: 1, 4: 1, 12: 2})
            or sum(r["old_was_blocked_by_input_budget"] for r in measured) != 3):
        raise ValueError("The saved probe must retain all five distinct revisions, including its three blocked first revisions.")
    return measured


def read_json_text(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("A captured model view has duplicate fields.")
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("A captured model view is nonfinite.")))


def execute(root, *, software_evidence=None):
    """Create only prospective diagnostics; do not resume or submit failed calls."""
    root = Path(root).resolve()
    evidence = deepcopy(software_evidence)
    if evidence is not None:
        if evidence.get("status") != "passed" or evidence.get("passed", 0) <= 0:
            raise ValueError("The offline correction software checks must pass first.")
        verify(root, evidence.get("files") or {})
    summary, rows, bindings = load_saved(root)
    components = {"src/champion_athletic_map/" + name + ".py":
                  sha(checked(root, "src/champion_athletic_map/" + name + ".py").read_bytes())
                  for name in (*NEW_COMPONENTS, *OLD_COMPONENTS)}
    counter, assets = module(root, "reviewed_preparation").pinned_counter(root)
    bindings.update(assets)
    bounded, food = module(root, "bounded_revision"), module(root, "food_response_validation")
    revisions = _revision_requests(root, rows, counter, bounded, bindings)
    food_results = []
    for row in rows:
        parsed = ((row["outcome"].get("response") or {}).get("model_output") or {}).get("parsed_object")
        diagnostic = food.diagnose_food(row["public"], parsed, row["packet"])
        original_food = [deepcopy(q) for q in row["report"]["assessment"]["checks"] if q["check_id"].startswith("food_")]
        # The new diagnosis concerns answer presence and numbers; source grounding retains its saved verdict.
        checks = food.assess_food(row["public"], parsed, row["packet"],
                                 base_assess_food=lambda *args, prior=original_food, **kwargs: deepcopy(prior))
        old_grounding = next(q for q in original_food if q["check_id"] == "food_source_grounding")
        checks = [deepcopy(old_grounding) if q["check_id"] == "food_source_grounding" else q for q in checks]
        food_results.append({"case_index": row["case_index"], "planner_version": row["report"]["planner_version"],
            "job_id": row["report"]["job_id"], "outcome_path": row["outcome_path"],
            "original_food_findings": original_food,
            "prospective_food_findings": checks, "diagnostic": diagnostic,
            "source_grounding_policy": "original_saved_finding_retained",
            "original_reply_or_assessment_changed": False, "human_rating": None})
    verify(root, {**bindings, **components})
    identity = {"schema_version": VERSION, "source_probe_id": summary["probe_id"],
        "source_summary_sha256": sha((root / SOURCE_SUMMARY).read_bytes()),
        "input_sha256": bindings, "component_sha256": components,
        "budget_policy": {"context": 8192, "output_reserve": 2048, "safety_margin": 256,
                          "boundary_reserve": 2, "input_ceiling": 5888},
        "candidate_only": True, "revision_omission": "repeated_generated_specialist_notes_only",
        "entrypoints": {"runtime": "corrected_runtime.build_runtime", "references": "corrected_runtime.build_reference_preparer",
                        "assessor": "corrected_runtime.make_assessor"}}
    digest = sha(canonical(identity))
    correction_id = "correction_" + digest[:20]
    folder = root / "results/pilot/offline_corrections" / correction_id
    manifest_name = "artifacts/pilot/offline_corrections/" + correction_id + "/manifest.json"
    manifest = {**identity, "manifest_id": digest, "correction_id": correction_id,
        "new_model_calls": 0, "http_requests": 0, "query_encoder_processes": 0, "jobs_started": 0,
        "new_backend_render_confirmed": False, "operational_generation_ready": False, "app_generation_enabled": False,
        "original_results_changed": False, "original_assessments_changed": False,
        "final_scores_created": False, "human_ratings_created": 0}
    save_once(root / manifest_name, manifest)
    requests = []
    for index, record in enumerate(revisions, 1):
        request_path = folder / "requests" / (str(index).zfill(2) + "_candidate.json")
        details_path = request_path.with_name(str(index).zfill(2) + "_measurement.json")
        save_once(request_path, record["new_candidate_request"])
        save_once(details_path, record)
        requests.append({k: deepcopy(v) for k, v in record.items() if k not in
                         {"new_candidate_request", "new_candidate_configuration", "removed_generated_notes", "original_system_text"}})
        requests[-1].update(candidate_request_path=request_path.relative_to(root).as_posix(),
                            measurement_path=details_path.relative_to(root).as_posix())
    food_path = folder / "food_validation.json"
    save_once(food_path, {"outcomes": food_results, "source_summary_sha256": identity["source_summary_sha256"],
        "original_assessments_changed": False, "final_scores_created": False})
    required = [r for r in food_results if r["diagnostic"]["question_present"]]
    result = {"schema_version": VERSION, "correction_id": correction_id, "manifest_id": digest,
        "manifest_path": manifest_name, "status": "offline_candidate_measured" if all(r["new_fits_local_input_budget"] for r in revisions)
                      else "offline_candidate_measured_with_blocks", "candidate_only": True,
        "saved_outcomes_checked": len(rows), "saved_revision_requests_checked": len(revisions),
        "original_revision_requests_over_budget": sum(r["old_was_blocked_by_input_budget"] for r in revisions),
        "candidate_revision_requests_fitting_locally": sum(r["new_fits_local_input_budget"] for r in revisions),
        "all_candidate_revision_requests_fit_locally": all(r["new_fits_local_input_budget"] for r in revisions),
        "revision_measurements": requests, "food_validation_path": food_path.relative_to(root).as_posix(),
        "food_outcomes_checked": len(food_results), "food_requested_outcomes": len(required),
        "food_field_completeness_met": sum(r["diagnostic"]["field_answer_status"] == "met" for r in required),
        "food_numeric_content_met": sum(r["diagnostic"]["numeric_answer_status"] == "met" for r in required),
        "food_correct_fact_elsewhere": sum(r["diagnostic"]["supported_elsewhere"] for r in required),
        "food_no_designated_response": sum(not r["diagnostic"]["designated_reply_present"] for r in required),
        "input_sha256": bindings, "component_sha256": components, "software_evidence": evidence,
        "new_model_calls": 0, "http_requests": 0, "query_encoder_processes": 0, "jobs_started": 0,
        "new_backend_render_confirmed": False, "native_token_count_agreement_verified": False,
        "operational_generation_ready": False, "app_generation_enabled": False,
        "original_results_changed": False, "original_assessments_changed": False,
        "final_scores_created": False, "human_ratings_created": 0}
    save_once(folder / "preparations" / (sha(canonical(result))[:20] + ".json"), result)
    target = root / SUMMARY
    if target.exists():
        prior = read(target)
        prior_id = prior.get("correction_id")
        if not isinstance(prior_id, str) or Path(prior_id).name != prior_id or not prior_id.startswith("correction_"):
            raise ValueError("An existing correction summary has an invalid identity and was preserved.")
        save_once(root / "results/pilot/offline_corrections" / prior_id / "preparations" / (sha(canonical(prior))[:20] + ".json"), prior)
    data = canonical(result) + b"\n"
    if not target.exists() or target.read_bytes() != data:
        temporary = target.with_name(target.name + ".tmp_" + uuid4().hex[:12])
        with temporary.open("xb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, target)
    return result
