"""Record the final run setup and the preselected team response-review sample."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

VERSION = "final-run-and-response-review-setup-1"
MODEL = "llama3.1:8b"
DIGEST = "46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def module(root, name):
    path = Path(root) / "src/champion_athletic_map" / (name + ".py")
    spec = importlib.util.spec_from_file_location("final_setup_" + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def save_once(path, data):
    if path.exists():
        require(path.read_bytes() == data, "An earlier final setup record differs and was preserved: " + path.name)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)


def metadata_only_identity(client, folder):
    """Permit the existing three identity lookups, never a chat request."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    original, requests = client._http, []
    allowed = ("/api/version", "/api/tags", "/api/show")
    def restricted(endpoint, payload=None, timeout=8, raw_path=None):
        require(len(requests) < 3 and endpoint == allowed[len(requests)],
                "The setup permits only the three model identity lookups.")
        require(payload == ({"model": MODEL, "verbose": False} if endpoint == "/api/show" else None),
                "A model identity lookup has an unexpected payload.")
        requests.append({"endpoint": endpoint, "payload": payload})
        target = folder / (str(len(requests)) + "_" + endpoint.rsplit("/", 1)[-1] + ".json")
        return original(endpoint, payload, 8, target)
    client._http = restricted
    try:
        identity = client._identity()
        require(len(requests) == 3 and identity.get("version") == "0.40.16"
            and identity.get("model", {}).get("digest") == DIGEST
            and identity.get("model", {}).get("details", {}).get("quantization_level") == "Q4_K_M",
            "The current model identity differs from the recorded comparison settings.")
        return {"status": "matched", "identity": identity, "metadata_requests": 3,
            "generation_requests": 0, "render_only_requests": 0,
            "current_resident_context_verified": False, "all_final_request_budgets_verified": False}
    except Exception as error:
        return {"status": "needs_attention", "error": type(error).__name__ + ": " + str(error),
            "metadata_requests": len(requests), "generation_requests": 0, "render_only_requests": 0,
            "current_resident_context_verified": False, "all_final_request_budgets_verified": False}
    finally:
        client._http = original


def load_common(root, freeze, common, *, software_fixture=False):
    relative = ("results/testing/step33_7_common_checks_fixture_summary.json" if software_fixture
                else "results/step33_common_response_checks_summary.json")
    summary = common.read_json(root / relative)
    require(summary.get("software_fixture") is software_fixture
            and summary.get("case_freeze_id") == freeze["summary"]["case_freeze_id"]
            and summary.get("contracts_bound") == 200 and summary.get("assessed_final_jobs") == 0,
            "The completed common-check setup does not match the frozen cases.")
    directory = common.safe_path(root, summary["package_directory"])
    configuration = common.read_json(directory / "common_checker_configuration.json")
    require(sha(packed(configuration)) == summary["preparation_id"],
            "The common-check configuration differs from its saved identity.")
    for source_path, expected in configuration["source_file_sha256"].items():
        require(sha(common.safe_path(root, source_path).read_bytes()) == expected,
                "A tested common-check source changed: " + source_path)
    ledger = b"".join(common.compact(row) + b"\n" for row in common.pending_ledger(freeze))
    require((directory / "initial_score_ledger.jsonl").read_bytes() == ledger,
            "The initial common results table changed.")
    return {"summary": summary, "configuration": configuration,
            "summary_path": relative, "summary_sha256": sha((root / relative).read_bytes())}


def neutral_references(root, freeze, common):
    pointer = common.read_json(root / "artifacts/language_model/active_resource_release.json")
    folder = pointer["release_directory"]
    manifest_path = common.safe_path(root, folder + "/manifest.json")
    require(sha(manifest_path.read_bytes()) == pointer["manifest_sha256"], "The approved reference release changed.")
    release = common.read_json(manifest_path)
    refs = []
    for name, label in (("adopted_drills.json", "Approved basketball activities and warm-ups"),
                        ("adopted_rules.json", "Adopted youth participation guidance")):
        path = common.safe_path(root, folder + "/" + name)
        digest = sha(path.read_bytes())
        require(digest == release["file_hashes"][name], "An adopted reference source changed.")
        refs.append({"label": label, "path": path.relative_to(root).as_posix(), "sha256": digest,
                     "description": "Complete neutral source records; no private case examples or expected answers."})
    food = common.read_json(root / freeze["summary"]["package_directory"] / "private_food_expectations.json")
    for relative, digest in food["source_bindings"].items():
        if not relative.endswith(("/usda_foods.csv", "/usda_food_nutrients.csv", "/usda_nutrient_definitions.json")):
            continue
        path = common.safe_path(root, relative)
        require(sha(path.read_bytes()) == digest, "A frozen food-reference table changed.")
        refs.append({"label": "Recorded USDA food reference — " + path.name,
            "path": relative, "sha256": digest,
            "description": "Complete frozen source table for fact checking; no per-case answer mapping."})
    require(len(refs) == 5, "The neutral food and activity source access is incomplete.")
    return refs


def make_protocol(freeze, common_record, review_definition, review_bindings, graph_report,
                  metadata, source_sha256, *, software_fixture=False):
    """Declare coverage limits before outputs, retaining the original primary definition."""
    ready = (not software_fixture and graph_report.get("native_runtime_graphs_verified") is True
        and graph_report.get("frozen_public_bindings_verified") == 200
        and graph_report.get("representative_runtime_graphs_verified") == 2
        and metadata.get("status") == "matched"
        and review_definition["summary"].get("sample_chosen_before_final_outputs") is True)
    return {"schema_version": VERSION, "case_freeze_id": freeze["summary"]["case_freeze_id"],
        "runtime_settings_id": freeze["settings"]["settings_id"],
        "case_contracts_id": freeze["contracts"]["contracts_id"],
        "common_checker_preparation_id": common_record["summary"]["preparation_id"],
        "source_sha256": source_sha256, "review_source_sha256": review_bindings,
        "team_review_definition": deepcopy(review_definition),
        "full_verification_metric_definition_changed": False,
        "goal_semantic_verification_implemented": False,
        "primary_measure_interpretation": "The automated full-verification measure is conservative. All 150 feasible cases have explicit goals that the present automatic checker cannot semantically verify, so positive full verification is unavailable by construction. Its zeros describe verification coverage, not proof that all planners produce unusable plans.",
        "separate_coded_measure": "Report automated_declared_checks_pass separately, together with format, completion, individual constraint and food findings, coverage and elapsed time. Do not relabel it as full request fulfillment or switch the primary after observing outputs.",
        "team_response_review_interpretation": "Five separate 0/1/2 rubric dimensions on the preselected 40 profiles and all four replies. Actual independent reviewer assignment, development practice and ratings remain pending before rating; these do not retroactively change the automated primary definition.",
        "request_preflight_policy": "The saved transport must render and check every actual complete request before submitting generation, with output reserved. Representative construction and metadata checks do not establish all future input budgets or reference packets.",
        "reference_policy": "No references for Planner 1; fresh preparation for each new reference-enabled job, with exactly the same complete case packet for Planners 2, 3 and 4. Query-runtime loading and preparation belong to the recorded measured job policy.",
        "failure_policy": "Retain designated terminal failures and required unknowns. Keep unstarted jobs and external-check errors incomplete. Never replace a failed result with an earlier draft or rerun an unresolved generation automatically.",
        "original_case_and_settings_snapshots_preserved": True,
        "public_checker_amendment": "Use the final public-only practice-block, duration and distinct-date interpretation in the isolated V4 checker; no rule thresholds, source records, model or budgets change.",
        "native_representative_graphs_checked": graph_report.get("native_runtime_graphs_verified") is True,
        "current_model_identity_matched": metadata.get("status") == "matched",
        "all_200_runtime_graphs_constructed": False, "all_final_request_budgets_verified": False,
        "complete_final_reference_packets_prepared": False,
        "actual_response_ratings": 0, "final_protocol_frozen": ready,
        "final_execution_started": False, "software_fixture": software_fixture,
        "model_calls": 0, "reference_query_encodings": 0}


def preserve_started_run(root, common):
    existing = root / "results/step33_final_run_setup_summary.json"
    if not existing.exists():
        return
    previous = common.read_json(existing)
    relative = previous.get("run_manifest_path")
    if isinstance(relative, str) and common.safe_path(root, relative).is_file():
        manifest = common.read_json(root / relative)
        folder = common.safe_path(root, manifest["package_directory"])
        require(not any((folder / "cases").glob("case_*/started.json")),
                "The final comparison has already started. Continue its batch cell; the saved run setup was preserved.")


def prepare(root, *, software_evidence, review_source_bindings, emit=print):
    root = Path(root).resolve()
    common = module(root, "common_response_preparation")
    freeze = common.load_freeze(root)
    completed = load_common(root, freeze, common)
    preserve_started_run(root, common)
    require(software_evidence.get("status") == "passed" and software_evidence.get("passed", 0) > 0
            and software_evidence.get("failed") == 0, "The final setup software checks must pass.")
    for relative, digest in software_evidence["files"].items():
        require(sha(common.safe_path(root, relative).read_bytes()) == digest,
                "A tested final setup source changed: " + relative)
    contract = module(root, "final_team_review_preparation").load_review_contract(root, review_source_bindings)
    refs = neutral_references(root, freeze, common)
    review = module(root, "final_team_review_preparation").prepare_components(
        freeze["profiles"], freeze["annotations"], freeze["jobs"], contract["config"],
        case_freeze_id=freeze["summary"]["case_freeze_id"], reference_access=refs)
    native = freeze["settings"]["native_case_configuration"]
    food_questions = [row["input"]["food_question"] for row in freeze["profiles"]
                      if isinstance(row["input"].get("food_question"), str) and row["input"]["food_question"].strip()]
    food_parser = module(root, "food_response_validation")
    require(len(food_questions) == 20 and all(food_parser.QUESTION.fullmatch(value) for value in food_questions),
            "A final food question is outside the common checker's declared question grammar.")
    config_path, schema_path = native["configuration_path"], native["public_schema_path"]
    require(sha(common.safe_path(root, config_path).read_bytes()) == native["configuration_sha256"]
            and sha(common.safe_path(root, schema_path).read_bytes()) == native["public_schema_sha256"],
            "The native common runtime configuration changed.")
    emit("Checking the local planner setup…")
    graph = module(root, "final_runtime_setup").verify_representative_graphs(root,
        common.read_json(root / config_path), common.read_json(root / schema_path),
        freeze["profiles"], freeze["contracts"])
    attempt_dir = (root / freeze["summary"]["package_directory"] / "setup_metadata" / ("check_" + uuid4().hex[:16]))
    metadata = metadata_only_identity(next(iter(graph["runtimes"].values())).client, attempt_dir)
    evidence_identity = {"case_freeze_id": freeze["summary"]["case_freeze_id"],
        "common_checker_preparation_id": completed["summary"]["preparation_id"],
        "source_sha256": software_evidence["files"], "review_definition": review["definition"],
        "review_source_sha256": contract["source_bindings"], "graph_report": graph["report"],
        "model_identity": metadata.get("identity"), "metadata_status": metadata["status"]}
    setup_id = sha(packed(evidence_identity))
    relative = freeze["summary"]["package_directory"] + "/run_setup_" + setup_id[:20]
    folder = root / relative
    for name, data in review["files"].items():
        save_once(folder / "team_response_review" / name, data)
    review_files = {(folder / "team_response_review" / name).relative_to(root).as_posix(): sha(data)
                    for name, data in review["files"].items()}
    protocol = make_protocol(freeze, completed, review["definition"],
        {**contract["source_bindings"], **review_files}, graph["report"], metadata, software_evidence["files"])
    original_protocol_path = freeze["summary"]["package_directory"] + "/final_protocol_candidate.json"
    original_protocol = common.read_json(root / original_protocol_path)
    protocol["original_settings_protocol_path"] = original_protocol_path
    protocol["original_settings_protocol_sha256"] = sha((root / original_protocol_path).read_bytes())
    protocol["metric_definitions"] = deepcopy(original_protocol["metric_definitions_candidate"])
    protocol["order_policy"] = deepcopy(original_protocol["order_policy"])
    protocol["current_runtime_factory"] = "final_runtime_setup.build_runtime"
    protocol["effective_runtime_identity_policy"] = "Bind the final protocol and amendment sources as well as the original planned job ID. Each constructed case runtime records its actual public-input-bound amendment identity. The Step 33-6 runtime settings ID remains the original settings snapshot, not the complete amended runtime identity."
    runner = module(root, "final_comparison_runner")
    run_manifest = runner.prepare_manifest(root, freeze=freeze, common_summary=completed["summary"],
        review_config_path=config_path, public_schema_path=schema_path,
        source_sha256=software_evidence["files"], protocol=protocol, execution_authorized=False)
    files = {"setup_identity.json": packed(evidence_identity), "runtime_graph_checks.json": packed(graph["report"]),
        "metadata_check.json": packed(metadata), "final_comparison_protocol.json": packed(protocol),
        "software_evidence.json": packed(software_evidence)}
    for name, data in files.items():
        save_once(folder / name, data)
    summary = {"schema_version": VERSION, "status": "run_setup_recorded" if protocol["final_protocol_frozen"] else "run_setup_needs_attention",
        "setup_id": setup_id, "package_directory": relative, "case_freeze_id": freeze["summary"]["case_freeze_id"],
        "offline_checks_passed": software_evidence["passed"], "frozen_case_bindings_checked": 200,
        "representative_runtime_graphs_checked": 2, "local_model_metadata": metadata["status"],
        "review_sample_profiles": 40, "masked_response_forms": 160,
        "team_review_package_directory": relative + "/team_response_review",
        "assigned_response_reviewers": 0, "response_ratings": 0,
        "planned_jobs": 800, "recorded_final_jobs": 0,
        "run_manifest_path": run_manifest["manifest_path"],
        "final_protocol_frozen": protocol["final_protocol_frozen"],
        "final_runner_software_prepared": True, "all_final_request_budgets_verified": False,
        "goal_verification": "unavailable automatically; coded-check results remain separate",
        "team_response_ratings": "pending", "final_planner_execution_started": False,
        "model_calls": 0, "metadata_requests": metadata["metadata_requests"],
        "reference_query_encodings": 0, "software_fixture": False,
        "issue": metadata.get("error"), "summary_path": "results/step33_final_run_setup_summary.json"}
    save_once(folder / "summary.json", packed(summary))
    destination = root / summary["summary_path"]
    if destination.exists() and destination.read_bytes() != packed(summary):
        # A later metadata check may resolve an earlier setup issue; retain both packages.
        previous = common.read_json(destination)
        require(previous.get("case_freeze_id") == summary["case_freeze_id"],
                "An existing setup pointer belongs to another case freeze.")
    runner.replace_progress(destination, packed(summary))
    return summary
