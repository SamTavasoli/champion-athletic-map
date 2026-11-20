"""Freeze validated case versions and pin comparison settings without enabling final runs."""

from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import random

VERSION = "reviewed-final-case-and-settings-snapshot-1"
REVIEW_ID = "ae2274034fa35533515d841e0364e64da3419c5f59117839092aa9bc14997f79"
SUMMARY_SHA256 = "367f71538d27bad74770aa55edf160160c5618c6bb387df3ac86efaf925b77ee"
SOURCE_REVIEW_FOLDER = "results/final_case_review/review_cb1efb8523e7c29384d3"
ORDERS = {"A": (1, 2, 4, 3), "B": (2, 3, 1, 4), "C": (3, 4, 2, 1), "D": (4, 1, 3, 2)}


def require(value, message):
    if not value:
        raise ValueError(message)


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def jsonl(rows):
    return b"".join(compact(row) + b"\n" for row in rows)


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "A settings JSON object repeats a key.")
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("A settings JSON number is not finite.")))


def module(root, filename):
    path = Path(root) / "src/champion_athletic_map" / filename
    spec = importlib.util.spec_from_file_location("final_case_settings_" + path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def save_once(path, data):
    path = Path(path)
    if path.exists():
        require(path.read_bytes() == data, "A saved case-settings file differs and was preserved: " + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)


def make_job_plan(profiles, runtime, contracts, seed=42):
    """Make a new paired 800-job roster; do not reuse development jobs or responses."""
    require(type(seed) is int and seed == 42, "The recorded final order seed is 42.")
    records = {row["profile_id"]: row for row in profiles}
    require(len(records) == len(profiles) == 200, "The final comparison needs the same 200 distinct cases.")
    bindings = {row["profile_id"]: row for row in contracts["case_bindings"]}
    require(bindings.keys() == records.keys(), "The per-case response contracts do not match the case roster.")
    require(all(bindings[pid]["public_record_canonical_sha256"] == sha(compact(record))
        and bindings[pid]["public_input_canonical_sha256"] == sha(compact(record["input"]))
        for pid, record in records.items()), "A response contract is bound to an earlier public case version.")
    ids = sorted(records)
    random.Random(seed).shuffle(ids)
    jobs = []
    labels = list(ORDERS)
    for index, pid in enumerate(ids):
        label = labels[index % 4]
        for position, version in enumerate(ORDERS[label], 1):
            record_hash = sha(packed(records[pid]))
            identity = {"review_id": REVIEW_ID, "runtime_settings_id": runtime["settings_id"],
                "contracts_id": contracts["contracts_id"], "profile_id": pid,
                "public_record_sha256": record_hash, "planner_version": version}
            jobs.append({"job_id": "final-planned-job:" + sha(packed(identity))[:24],
                "profile_id": pid, "public_record_sha256": record_hash,
                "planner_version": version, "case_sequence": index + 1,
                "position_in_case": position, "order_label": label,
                "contract_bundle_id": bindings[pid]["contract_bundle_id"],
                "runtime_settings_id": runtime["settings_id"],
                "reference_equivalence_group": pid if version in (2, 3, 4) else None,
                "designated_final_outcome": None, "execution_state": "not_started",
                "source_development_job_reused": False})
    require(len(jobs) == len({row["job_id"] for row in jobs}) == 800, "Final job identities are not distinct.")
    require(Counter(row["planner_version"] for row in jobs) == {1: 200, 2: 200, 3: 200, 4: 200},
            "A planner is missing from the paired roster.")
    require(Counter((row["planner_version"], row["position_in_case"]) for row in jobs)
            == {(version, position): 50 for version in range(1, 5) for position in range(1, 5)},
            "The planned version positions are not balanced.")
    predecessors = Counter()
    for index in range(0, len(jobs), 4):
        for left, right in zip(jobs[index:index + 3], jobs[index + 1:index + 4]):
            predecessors[(left["planner_version"], right["planner_version"])] += 1
    require(predecessors == {(a, b): 50 for a in range(1, 5) for b in range(1, 5) if a != b},
            "The within-case predecessor orders are not balanced.")
    return {"schema_version": "planned-final-four-workflow-roster-1", "seed": seed,
        "orders": {name: list(order) for name, order in ORDERS.items()},
        "case_order": "Lexically sorted opaque case IDs, shuffled once with Python random.Random(42).",
        "order_assignment": "Cycle the four recorded order patterns across the shuffled 200 cases; each pattern occurs50times.",
        "balanced_planner_positions": True, "balanced_within_case_predecessor_pairs": True,
        "planned_jobs": 800, "jobs": jobs, "executed_jobs": 0, "model_calls": 0,
        "reference_packet_equality_required_across_versions_2_3_4_for_each_case": True,
        "case_category_or_private_evidence_in_job_arguments": False,
        "final_planner_execution_authorized": False}


def make_protocol_candidate(design, cases, runtime, contracts, roster):
    """Prespecify settings and definitions while retaining unfinished scoring gates."""
    return {"schema_version": "final-planner-protocol-candidate-1",
        "status": "case_population_frozen_settings_recorded_full_protocol_pending",
        "case_review_id": REVIEW_ID, "case_count": 200, "planned_jobs": 800,
        "category_counts_per_version": {"feasible": 150, "missing_information": 20,
            "conflicting_constraints": 15, "outside_scope": 15},
        "feasible_conditioning_plan_coverage": False,
        "scope_note": "The feasible set has13basketball-skill goals; two preserved challenge cases still mention conditioning.",
        "case_family_convention": "one separately authored base per family; preserve its versions and paired workflow outcomes",
        "family_count": 200, "case_authoring_accepted": True,
        "case_review_method_changed_by_this_cell": False,
        "runtime_settings_id": runtime["settings_id"], "contracts_id": contracts["contracts_id"],
        "model_and_workflows": {"model": runtime["model"], "runtime_factory": runtime["runtime_factory"],
            "runtime_version": runtime["runtime_version"], "workflows": runtime["workflows"],
            "budgets": runtime["budgets"], "reference_policy": runtime["reference_policy"],
            "request_policy": runtime["request_policy"], "timing_policy": runtime["timing_policy"]},
        "response_contract_policy": {"same_effective_per_case_contract_for_all_versions": True,
            "independent_format_validation_must_use_frozen_effective_local_schema": True,
            "native_ordered_schema_wire_string_must_be_preserved": True,
            "private_food_truth_or_source_choices_used_to_build_contracts": False,
            "full_runtime_and_backend_contract_parity_verified": False},
        "order_policy": {key: value for key, value in roster.items() if key not in {"jobs"}},
        "metric_definitions_candidate": deepcopy(design["metric_definitions"]),
        "team_response_review_preparation": deepcopy(design["team_response_review_unchanged"]),
        "preserved_development_results": True, "development_outcomes_substituted_for_final_jobs": False,
        "required_check_applicability": "Evaluate adopted-rule predicates using the actual reply and authoritative public facts. An expected nonplan label does not exempt an unexpected returned plan from content checks.",
        "private_example_policy": "Existence examples are not the only correct plans. Do not demand hidden witness IDs or catalog membership from generic activities; report unresolved evidence consistently across all versions.",
        "v4_internal_review_is_external_assessment": False,
        "readiness_gaps": deepcopy(design["readiness_gaps"]),
        "source_design_bindings": deepcopy(design["source_bindings"]),
        "common_response_scoring_ready": False, "backend_and_actual_request_preflight_ready": False,
        "final_runner_ready": False, "team_response_review_preparation_complete": False,
        "final_protocol_frozen": False, "final_planner_execution_authorized": False,
        "model_calls": 0, "reference_query_encodings": 0}


def prepare_components(root, *, case_report, runtime, contracts, design, public_bytes,
                       private_food_bytes, software_fixture=False):
    """Write a case-only freeze; fixture results have a separate explicit namespace."""
    root = Path(root).resolve()
    require(case_report["review_id"] == REVIEW_ID, "The case acceptance result belongs to another review.")
    require(case_report["summary"]["case_authoring_accepted"] == 200
        and case_report["summary"]["planning_existence_examples_checked"] == 150
        and case_report["summary"]["food_expectations_checked"] == 20, "The reviewed case checks are incomplete.")
    if not software_fixture:
        require(case_report["summary"]["native_installation_checked"] is True
            and runtime["native_case_configuration_verified"] is True and runtime["inventory_only_host_mode"] is False,
            "The actual installed review and local comparison configuration must be verified.")
    require(sha(public_bytes) == case_report["reviewed_population_sha256"], "The public case file differs from the reviewed population.")
    profiles = case_report["public_case_projection"]
    require(sha(jsonl(profiles)) == sha(public_bytes), "The case projection changed the input records or their order.")
    require(len(case_report["case_annotations"]) == 200 and len(case_report["private_feasibility_evidence"]) == 150,
            "The private case evidence does not match the frozen roster.")
    current = {row["profile_id"]: sha(packed(row)) for row in profiles}
    require(all(row["public_record_sha256"] == current[row["profile_id"]]
        for row in case_report["case_annotations"] + case_report["private_feasibility_evidence"]),
        "Private case evidence refers to an earlier public version.")
    for value, key in ((runtime, "settings_id"), (contracts, "contracts_id")):
        identity = deepcopy(value)
        identifier = identity.pop(key, None)
        require(identifier == sha(packed(identity)), "A settings or response-contract identity changed.")
    roster = make_job_plan(profiles, runtime, contracts)
    protocol = make_protocol_candidate(design, case_report, runtime, contracts, roster)
    native_bindings = case_report.get("native_bindings", {})
    source_hashes = {name: sha((root / "src/champion_athletic_map" / name).read_bytes()) for name in
        ("final_case_settings.py", "case_acceptance.py", "runtime_settings.py")}
    identity = {"schema_version": VERSION, "review_id": REVIEW_ID,
        "case_authoring_population_sha256": sha(public_bytes),
        "case_annotations_sha256": sha(packed(case_report["case_annotations"])),
        "private_feasibility_sha256": sha(packed(case_report["private_feasibility_evidence"])),
        "runtime_settings_id": runtime["settings_id"], "contracts_id": contracts["contracts_id"],
        "protocol_candidate_sha256": sha(packed(protocol)), "planned_roster_sha256": sha(packed(roster)),
        "native_case_source_bindings": native_bindings, "software_source_sha256": source_hashes,
        "software_fixture": software_fixture}
    freeze_id = sha(packed(identity))
    prefix = "software_fixture_case_freeze_" if software_fixture else "case_freeze_"
    relative = SOURCE_REVIEW_FOLDER + "/" + prefix + freeze_id[:20]
    folder = root / relative
    families = [{"profile_id": row["profile_id"], "family_id": row["family_id"],
                 "public_record_sha256": row["public_record_sha256"]} for row in case_report["case_annotations"]]
    files = {"public_case_inputs.jsonl": public_bytes, "private_case_annotations.jsonl": jsonl(case_report["case_annotations"]),
        "private_feasibility_evidence.jsonl": jsonl(case_report["private_feasibility_evidence"]),
        "private_family_assignments.jsonl": jsonl(families), "private_food_expectations.json": private_food_bytes,
        "case_acceptance_report.json": packed({k: v for k, v in case_report.items() if k not in
            {"public_case_projection", "case_annotations", "private_feasibility_evidence"}}),
        "comparison_settings.json": packed(runtime), "case_response_contracts.json": packed(contracts),
        "planned_jobs.jsonl": jsonl(roster["jobs"]),
        "planned_job_schedule.json": packed({k: v for k, v in roster.items() if k != "jobs"}),
        "final_protocol_candidate.json": packed(protocol)}
    files["README.md"] = ("# Step 33-6 — Reviewed cases and comparison settings\n\n"
        "We validated and froze the200 reviewed public case versions and their separate private authoring evidence. "
        "The private evidence includes150 complete source-linked existence examples,50 challenge expectations,20 frozen food facts and200 authored-base family assignments. "
        "The feasible set covers basketball skills, with no feasible conditioning-plan cases; two preserved challenge cases still mention conditioning.\n\n"
        "We recorded the intended corrected runtime, same local model and per-case response contracts, and prepared800 new planned jobs. "
        "The four order patterns occur50times each, so each workflow occurs50times in each within-case position. "
        "These jobs have not started. Saved development outputs do not replace them.\n\n"
        "This is a case-population freeze and comparison-settings snapshot. The global final protocol remains unfinished. "
        "The common checker needs final-case wording and conflict-proof coverage, exact effective response schemas, a common score ledger and explicit resource-evidence limitations. "
        "Final runtime/backend preflight, the final runner and response-review preparation also remain. "
        "No generation or new reference query encoding occurs here. The existing classifier selection/test results and retrieval benchmark remain separate.\n\n"
        "Only public_case_inputs.jsonl public wrappers and their public input projections may enter the future planner calls. "
        "Case categories, expected behaviors, families, feasibility examples and food truth remain private. "
        "Actual-reply applicability must be evaluated independently; expected nonplan labels do not waive content checks on an unexpected plan. "
        "The private source example is not the only correct answer and introduces no hidden catalog-ID requirement for generic activities.\n").encode("utf-8")
    manifest = {**identity, "case_freeze_id": freeze_id, "package_directory": relative,
        "case_population_frozen": True, "comparison_settings_recorded": True,
        "global_final_protocol_frozen": False, "final_planner_execution_authorized": False,
        "files": {name: sha(data) for name, data in files.items()}}
    summary_relative = "results/testing/step33_6_case_settings_fixture_summary.json" if software_fixture else "results/step33_final_case_settings_summary.json"
    summary = {"schema_version": VERSION, "status": "software_fixture_verified" if software_fixture else "reviewed_cases_frozen_comparison_settings_recorded",
        "review_id": REVIEW_ID, "case_freeze_id": freeze_id, "package_directory": relative,
        "public_case_file": relative + "/public_case_inputs.jsonl", "public_case_file_sha256": sha(public_bytes),
        "validated_case_choices": 200, "validated_private_examples": 150, "verified_food_expectations": 20,
        "family_assignments": 200, "planned_final_jobs": 800,
        "case_population_frozen": True, "comparison_settings_recorded": True,
        "runtime_settings_id": runtime["settings_id"], "case_contracts_id": contracts["contracts_id"],
        "effective_case_contracts": len(contracts["case_bindings"]),
        "common_response_scoring_ready": False, "global_final_protocol_frozen": False,
        "final_planner_execution_authorized": False, "model_calls": 0, "reference_query_encodings": 0,
        "software_fixture": software_fixture, "summary_path": summary_relative}
    files["manifest.json"] = packed(manifest)
    files["summary.json"] = packed(summary)
    for name, data in files.items():
        path = folder / name
        require(not path.exists() or path.read_bytes() == data, "A frozen case/settings file differs: " + name)
    destination = root / summary_relative
    require(not destination.exists() or destination.read_bytes() == packed(summary), "An earlier case/settings summary differs and was preserved.")
    for name, expected in {**native_bindings, **runtime["source_file_sha256"], **design["source_bindings"]}.items():
        require(sha((root / name).read_bytes()) == expected, "A bound source changed during case/settings preparation: " + name)
    for name, data in files.items():
        save_once(folder / name, data)
    save_once(destination, packed(summary))
    return summary


def execute(root, *, expected_runtime_bindings, design, emit=print):
    root = Path(root).resolve()
    require("/results/final_case_review/" in (root / ".gitignore").read_text(encoding="utf-8-sig").splitlines(),
            "The private case-review folder exclusion is required.")
    summary_file = root / "results/step33_delegated_team_review_summary.json"
    require(sha(summary_file.read_bytes()) == SUMMARY_SHA256, "The completed Team review differs from the uploaded record.")
    summary = read_json(summary_file)
    emit("Checking the reviewed cases and comparison settings…")
    case_report = module(root, "case_acceptance.py").validate_reviewed_cases(root, summary=summary)
    runtime_helper = module(root, "runtime_settings.py")
    runtime = runtime_helper.collect_runtime_settings(root, expected_bindings=expected_runtime_bindings)
    contracts = runtime_helper.build_case_contracts(root, case_report["public_case_projection"], runtime)
    public_file = root / case_report["reviewed_public_case_file"]
    private_food = root / summary["package_directory"] / "private_food_expectations.json"
    return prepare_components(root, case_report=case_report, runtime=runtime, contracts=contracts,
        design=design, public_bytes=public_file.read_bytes(), private_food_bytes=private_food.read_bytes())
