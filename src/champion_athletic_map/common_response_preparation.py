"""Prepare the common final assessor without running any final planner jobs."""

from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath

VERSION = "final-common-response-preparation-1"
CATEGORIES = {"feasible": 150, "missing_information": 20,
              "conflicting_constraints": 15, "outside_scope": 15}


def require(value, message):
    if not value:
        raise ValueError(message)


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "A common-check input repeats a JSON key.")
            value[key] = item
        return value
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("A JSON number is not finite.")))


def safe_path(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative,
            "A common-check path must be relative to the project.")
    value = PurePosixPath(relative)
    require(not value.is_absolute() and not set(value.parts) & {".", ".."}
            and value.as_posix() == relative, "A common-check path leaves the project.")
    path = root / relative
    require(path.resolve() == path, "A common-check file is linked outside its declared location.")
    return path


def load_module(root, name):
    path = safe_path(root, "src/champion_athletic_map/" + name + ".py")
    spec = importlib.util.spec_from_file_location("common_preparation_" + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def load_freeze(root, *, software_fixture=False):
    """Read the frozen roster, not any saved development or test predictions."""
    root = Path(root).resolve()
    relative = ("results/testing/step33_6_case_settings_fixture_summary.json" if software_fixture
                else "results/step33_final_case_settings_summary.json")
    summary = read_json(root / relative)
    require(summary.get("software_fixture") is software_fixture,
            "A software fixture cannot stand in for the installed case freeze.")
    require(summary.get("case_population_frozen") is True
            and summary.get("validated_case_choices") == 200
            and summary.get("planned_final_jobs") == 800,
            "The completed Step 33-6 case and settings snapshot is required.")
    folder = safe_path(root, summary["package_directory"])
    manifest = read_json(folder / "manifest.json")
    require(manifest.get("case_freeze_id") == summary.get("case_freeze_id")
            and manifest.get("software_fixture") is software_fixture
            and manifest.get("package_directory") == summary.get("package_directory"),
            "The case freeze does not match its summary.")
    for name, digest in manifest["files"].items():
        path = safe_path(root, summary["package_directory"] + "/" + name)
        require(sha(path.read_bytes()) == digest, "A frozen common-check input changed: " + name)
    def jsonl(name):
        return [json.loads(line) for line in (folder / name).read_bytes().splitlines()]
    profiles = jsonl("public_case_inputs.jsonl")
    annotations = jsonl("private_case_annotations.jsonl")
    jobs = jsonl("planned_jobs.jsonl")
    contracts = read_json(folder / "case_response_contracts.json")
    settings = read_json(folder / "comparison_settings.json")
    for value, key in ((contracts, "contracts_id"), (settings, "settings_id")):
        identity = deepcopy(value)
        digest = identity.pop(key)
        require(digest == sha(packed(identity)), "A frozen settings identity differs.")
    require(contracts["contracts_id"] == summary["case_contracts_id"]
            and settings["settings_id"] == summary["runtime_settings_id"],
            "The response contracts or runtime settings do not match the freeze.")
    bound_sources = {**settings["source_file_sha256"], **{
        "src/champion_athletic_map/" + name: digest
        for name, digest in manifest["software_source_sha256"].items()}}
    for path, digest in bound_sources.items():
        require(sha(safe_path(root, path).read_bytes()) == digest,
                "A previously recorded source changed: " + path)
    require(sha((folder / "public_case_inputs.jsonl").read_bytes()) == summary["public_case_file_sha256"],
            "The frozen public case file does not match its summary.")
    require(len(profiles) == len(annotations) == 200 and len(jobs) == 800,
            "The common-check case or job roster is incomplete.")
    records = {row["profile_id"]: row for row in profiles}
    notes = {row["profile_id"]: row for row in annotations}
    require(len(records) == len(notes) == 200 and records.keys() == notes.keys(),
            "The public and private case rosters differ.")
    require(Counter(row["case_category"] for row in annotations) == CATEGORIES,
            "The fixed category denominators have changed.")
    for pid, record in records.items():
        require(notes[pid]["public_record_sha256"] == sha(packed(record)),
                "A private annotation refers to an earlier public version.")
    require(len({row["job_id"] for row in jobs}) == 800
            and Counter((row["profile_id"], row["planner_version"]) for row in jobs)
                == Counter({(pid, version): 1 for pid in records for version in range(1, 5)}),
            "The paired four-planner job roster differs.")
    require(all(row["execution_state"] == "not_started" and row["designated_final_outcome"] is None
                for row in jobs), "The planned roster must preserve its original unstarted state.")
    return {"summary": summary, "summary_sha256": sha((root / relative).read_bytes()),
            "manifest_sha256": sha((folder / "manifest.json").read_bytes()),
            "profiles": profiles, "annotations": annotations, "jobs": jobs,
            "contracts": contracts, "settings": settings}


def pending_ledger(freeze):
    """Keep the entire paired roster; no missing result counts as a success or failure."""
    notes = {row["profile_id"]: row for row in freeze["annotations"]}
    return [{"job_id": job["job_id"], "profile_id": job["profile_id"],
        "planner_version": job["planner_version"], "case_category": notes[job["profile_id"]]["case_category"],
        "family_id": notes[job["profile_id"]]["family_id"],
        "public_record_sha256": job["public_record_sha256"],
        "execution_state": "not_started", "designated_outcome_sha256": None,
        "assessment_execution": "not_run", "assessment_sha256": None,
        "metric_state": "incomplete", "automated_feasible_plan_success": None,
        "automated_declared_checks_pass": None, "complete_request_fulfillment_verified": None,
        "team_response_ratings": None} for job in freeze["jobs"]]


def record_assessment(ledger_row, outcome, assessment):
    """Join one designated terminal outcome without falling back to an earlier draft."""
    require(isinstance(outcome, dict) and isinstance(assessment, dict),
            "A ledger update needs the saved outcome and its external assessment.")
    outcome_sha = sha(compact(outcome))
    assessment_sha = sha(compact(assessment))
    history = deepcopy(ledger_row.get("assessment_history", []))
    if ledger_row.get("execution_state") != "not_started":
        require(ledger_row.get("designated_outcome_sha256") == outcome_sha,
                "A designated ledger outcome already exists and was preserved.")
        if ledger_row.get("assessment_sha256") == assessment_sha:
            return deepcopy(ledger_row)
        require(ledger_row.get("assessment_execution") == "error",
                "An assessed ledger result already exists and was preserved.")
        history.append({"assessment_sha256": ledger_row.get("assessment_sha256"),
            "assessment_execution": "error", "error": ledger_row.get("assessment_error")})
    require(assessment.get("designated_outcome_sha256") in (None, outcome_sha),
            "The assessment belongs to a different saved outcome.")
    require(assessment.get("assessment_execution") in ("completed", "error"),
            "The external assessment has no terminal status.")
    row = deepcopy(ledger_row)
    row.update(execution_state="terminal", designated_outcome_sha256=outcome_sha,
               assessment_execution=assessment["assessment_execution"], assessment_sha256=assessment_sha,
               assessment_history=history)
    if assessment["assessment_execution"] == "error":
        row.update(metric_state="incomplete", assessment_error=assessment.get("error"))
        return row
    require(assessment.get("designated_outcome_sha256") == outcome_sha,
            "A completed assessment must identify its exact designated outcome.")
    metrics = assessment.get("final_metrics")
    require(isinstance(metrics, dict) and metrics.get("applicable_category") == row["case_category"]
            and type(metrics.get("category_response_success")) is bool,
            "The common final metrics are missing or refer to a different case category.")
    require(assessment.get("public_record_sha256") == row["public_record_sha256"],
            "The assessment belongs to a different public case version.")
    primary = metrics.get("automated_feasible_plan_success")
    require(type(primary) is bool if row["case_category"] == "feasible" else primary is None,
            "The feasible-plan measure uses only the fixed feasible-case roster.")
    row.update(metric_state="assessed", automated_feasible_plan_success=primary,
        automated_declared_checks_pass=metrics.get("automated_declared_checks_pass"),
        complete_request_fulfillment_verified=metrics.get("complete_request_fulfillment_verified"),
        category_response_success=metrics["category_response_success"],
        strict_format_valid=metrics["strict_format_valid"],
        designated_workflow_completed=metrics["designated_workflow_completed"])
    row.pop("assessment_error", None)
    return row


def ledger_counts(rows):
    """Report fixed denominators and incomplete jobs without success-only subsets."""
    require(len(rows) == len({row["job_id"] for row in rows}) == 800,
            "A complete paired ledger contains 800 distinct planned jobs.")
    result = {}
    for version in range(1, 5):
        selected = [row for row in rows if row["planner_version"] == version]
        require(Counter(row["case_category"] for row in selected) == CATEGORIES,
                "The fixed per-planner case denominators have changed.")
        feasible = [row for row in selected if row["case_category"] == "feasible"]
        result[str(version)] = {"all_cases_denominator": 200, "feasible_plan_denominator": 150,
            "feasible_successes": sum(row["automated_feasible_plan_success"] is True for row in feasible),
            "feasible_failures": sum(row["automated_feasible_plan_success"] is False for row in feasible),
            "feasible_incomplete": sum(row["automated_feasible_plan_success"] is None for row in feasible),
            "feasible_declared_checks_passed": sum(row.get("automated_declared_checks_pass") is True for row in feasible),
            "feasible_declared_checks_assessed": sum(type(row.get("automated_declared_checks_pass")) is bool for row in feasible),
            "all_jobs_incomplete": sum(row["metric_state"] == "incomplete" for row in selected)}
    return result


def save_once(path, data):
    if path.exists():
        require(path.read_bytes() == data, "An earlier common-check record differs and was preserved: " + path.name)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)


def prepare(root, *, software_evidence, software_fixture=False):
    root = Path(root).resolve()
    freeze = load_freeze(root, software_fixture=software_fixture)
    require(software_evidence.get("status") == "passed" and software_evidence.get("failed") == 0
            and software_evidence.get("passed", 0) > 0,
            "The common-check software checks must pass before preparation.")
    for path, digest in software_evidence["files"].items():
        require(sha(safe_path(root, path).read_bytes()) == digest,
                "A tested common-check source changed: " + path)
    schema_path = "artifacts/pilot/case_review_794f10d9d10a5fde/public_profile_schema.json"
    assessor_module = load_module(root, "final_response_checks")
    assessor = assessor_module.FinalResponseAssessor(root, read_json(root / schema_path), freeze["contracts"])
    request = load_module(root, "final_request_checks")
    by_id = {row["profile_id"]: row for row in freeze["annotations"]}
    requests_checked, conflicts = 0, 0
    for record in freeze["profiles"]:
        # We bind the format checker to the same public case and local schema used for generation.
        assessor.validate_case_binding(record, by_id[record["profile_id"]])
        note = by_id[record["profile_id"]]
        if note["case_category"] == "feasible":
            count, _basis = request.requested_count(record["input"])
            require(count == note["private_expected_behavior"]["requested_additional_sessions"],
                    "A public practice-block request is not recognized by the common checker.")
            requests_checked += 1
        if request.distinct_date_proof(record["input"]):
            conflicts += 1
    require(requests_checked == 150, "Not all final planning requests were checked.")
    ledger = pending_ledger(freeze)
    configuration = {"schema_version": VERSION, "case_freeze_id": freeze["summary"]["case_freeze_id"],
        "case_freeze_summary_sha256": freeze["summary_sha256"], "case_freeze_manifest_sha256": freeze["manifest_sha256"],
        "case_contracts_id": freeze["contracts"]["contracts_id"],
        "assessor_factory": "champion_athletic_map.final_response_checks.FinalResponseAssessor",
        "effective_per_case_local_schema_required": True,
        "source_file_sha256": software_evidence["files"], "software_evidence": software_evidence,
        "case_categories_in_planner_inputs": False, "private_examples_are_mandatory_answers": False,
        "resource_semantics": "Only separately reviewed concrete descriptions have positive source-backed resource proofs. Generic unverified activity requirements remain unknown; optional source IDs are not mandatory.",
        "goal_semantics": "Passing the coded schedule checks does not establish full goal fulfillment. Explicit goals without semantic verification remain unknown in the primary measure; report coded-check results separately.",
        "v4_internal_acceptance_is_external_verdict": False,
        "fixed_denominators_per_planner": deepcopy(CATEGORIES),
        "missing_jobs_and_checker_errors": "incomplete; retain in the fixed roster",
        "terminal_model_failures": "retain as failed outcomes after external assessment",
        "semantic_unknowns": "not fully verified; do not replace with met",
        "team_response_ratings_completed": False, "final_protocol_frozen": False,
        "final_planner_execution_authorized": False, "backend_preflight_completed": False,
        "software_fixture": software_fixture, "model_calls": 0, "reference_query_encodings": 0}
    preparation_id = sha(packed(configuration))
    prefix = "software_fixture_common_checks_" if software_fixture else "common_checks_"
    relative = freeze["summary"]["package_directory"] + "/" + prefix + preparation_id[:20]
    summary_path = ("results/testing/step33_7_common_checks_fixture_summary.json" if software_fixture
                    else "results/step33_common_response_checks_summary.json")
    summary = {"schema_version": VERSION, "status": "common_response_checker_prepared",
        "preparation_id": preparation_id, "package_directory": relative,
        "case_freeze_id": freeze["summary"]["case_freeze_id"], "contracts_bound": 200,
        "planning_requests_recognized": requests_checked, "distinct_date_conflicts_proved": conflicts,
        "paired_jobs_in_ledger": len(ledger), "assessed_final_jobs": 0,
        "offline_checks_passed": software_evidence["passed"], "common_checker_software_ready": True,
        "resource_semantic_coverage": "limited; unresolved activity requirements remain unknown",
        "goal_semantic_verification": "pending; a coded-check pass is not full goal fulfillment",
        "final_runner_and_backend_readiness": "pending", "team_response_review_preparation": "pending",
        "global_final_protocol_frozen": False, "final_planner_execution_authorized": False,
        "software_fixture": software_fixture, "model_calls": 0, "reference_query_encodings": 0,
        "summary_path": summary_path}
    files = {"common_checker_configuration.json": packed(configuration),
        "initial_score_ledger.jsonl": b"".join(compact(row) + b"\n" for row in ledger),
        "initial_ledger_counts.json": packed(ledger_counts(ledger)),
        "summary.json": packed(summary)}
    for name, data in files.items():
        save_once(root / relative / name, data)
    save_once(root / summary_path, packed(summary))
    return summary
