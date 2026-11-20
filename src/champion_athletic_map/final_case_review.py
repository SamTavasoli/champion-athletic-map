"""Prepare a private, readable review package without running the final planners."""

from collections import Counter
from copy import deepcopy
import csv
import hashlib
import html
import io
import json
import math
from pathlib import Path, PurePosixPath

VERSION = "final-case-review-preparation-1"
PROTOCOL = "020a5ce67c9ecc046548479c8bd17ee1fa51cfd3912457340924bef11a9fb49f"
PROTECTED = "results/profile_preparation/protected_test_drafts_6f292bd047b72685"
WORKSPACE = "results/profile_preparation/review_workspace_95c5163bfa1213fc"
CONTRACT = "artifacts/evaluation/profile_contract_d3addc8aa60b70ab"
RETRIEVAL = "artifacts/retrieval/evaluation/evaluation_62d4b123570c2ca8"
CATEGORIES = {"feasible": 150, "missing_information": 20, "conflicting_constraints": 15, "outside_scope": 15}
FAMILIES = ("majority", "logistic_regression", "neural")
PREPARATION_SUMMARY_HASHES = {
    PROTECTED + "/step16_protected_test_drafts_summary.json": "767bd7cce148528b60cea1c82cc96b26a18072c5563927289d4d0f0053bccd5b",
    WORKSPACE + "/step16_review_workspace_summary.json": "034fca60a232c95688171c6c66794a9d6b493d10f9581d58b2bc7664d408fe33",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def jsonl_bytes(values):
    return b''.join(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                               allow_nan=False).encode("utf-8") + b"\n" for value in values)


def checked(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative, "Invalid review source path.")
    value = PurePosixPath(relative)
    require(not value.is_absolute() and value.as_posix() == relative and not set(value.parts) & {".", ".."}, "Invalid review source path.")
    path = root / relative
    require(path.resolve() == path and path.is_file(), "Missing or linked review source: " + relative)
    return path


def read_json(data):
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "A review source has duplicate JSON keys.")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("Nonfinite review source value.")))


def save_once(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == data, "An immutable case-review file changed: " + str(path))
    else:
        with path.open("xb") as handle:
            handle.write(data)


def csv_records(data):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    require(reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)), "Invalid case-review CSV header.")
    rows = list(reader)
    require(all(None not in row and all(value is not None for value in row.values()) for row in rows), "Malformed case-review CSV row.")
    return rows


def csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def verify_step32(root):
    """Read completion metadata; prediction payloads are hashed only as opaque bytes."""
    name = "results/step32_classifier_test_summary.json"
    data = checked(root, name).read_bytes()
    result = read_json(data)
    require(result.get("schema_version") == "heldout-classifier-evaluation-1" and result.get("status") == "complete"
            and result.get("all_models_complete") is True and result.get("injected_test_dependencies") is False
            and result.get("protocol_id") == PROTOCOL and result.get("records") == 438
            and result.get("groups") == 385 and result.get("class_count") == 16
            and result.get("model_training_calls") == 0 and result.get("application_selection_changed") is False
            and result.get("planner_inputs_changed") is False, "The successful native Step 32 completion record is required.")
    require(set(result.get("models", {})) == set(FAMILIES)
            and all(result["models"][family].get("records") == 438 for family in FAMILIES), "The Step 32 comparison is incomplete.")
    relative = result.get("summary_path")
    require(isinstance(relative, str) and relative.startswith("results/classifier_test/heldout_")
            and relative.endswith("/summary.json"), "The Step 32 summary is not a native held-out evaluation.")
    require(checked(root, relative).read_bytes() == data, "The Step 32 public summary differs from its saved evaluation.")
    receipt_path = str(PurePosixPath(relative).parent / "completed.json")
    receipt_data = checked(root, receipt_path).read_bytes()
    receipt = read_json(receipt_data)
    require(receipt.get("evaluation_id") == result.get("evaluation_id")
            and receipt.get("files", {}).get(name) == sha(data)
            and receipt["files"].get(relative) == sha(data), "The Step 32 terminal receipt does not bind its summary.")
    for filename, expected in receipt["files"].items():
        require(sha(checked(root, filename).read_bytes()) == expected, "A completed classifier evaluation file changed: " + filename)
    return {"path": name, "sha256": sha(data), "terminal_receipt_path": receipt_path,
            "terminal_receipt_sha256": sha(receipt_data), "records": 438, "groups": 385, "classes": 16,
            "classification_scores_used_for_planner_preparation": False, "predictions_parsed": False}


def load_sources(root):
    """Verify the preparation lineage before decoding any candidate case records."""
    bindings, content = {}, {}
    def bind(name, expected=None):
        data = checked(root, name).read_bytes()
        require(expected is None or sha(data) == expected, "A saved preparation source changed: " + name)
        bindings[name], content[name] = sha(data), data
        return data
    def config(name, expected=None):
        return read_json(bind(name, expected))
    protected_name = PROTECTED + "/step16_protected_test_drafts_summary.json"
    workspace_name = WORKSPACE + "/step16_review_workspace_summary.json"
    protected = config(protected_name, PREPARATION_SUMMARY_HASHES[protected_name])
    workspace = config(workspace_name, PREPARATION_SUMMARY_HASHES[workspace_name])
    require(protected.get("accepted_final_profiles") == 0 and protected.get("final_profiles_frozen") is False
            and workspace.get("accepted_profiles") == 0 and workspace.get("human_review_decisions_recorded") == 0,
            "The saved sources no longer describe the unaccepted candidate review stage.")
    for folder, producer in ((PROTECTED, protected), (WORKSPACE, workspace)):
        for filename, expected in producer["artifacts"].items():
            bind(folder + "/" + filename, expected)
    schema_path = CONTRACT + "/profile_input_schema.json"
    config(schema_path, protected["input_hashes"][schema_path])
    config(CONTRACT + "/profile_dataset_config.json", protected["input_hashes"][CONTRACT + "/profile_dataset_config.json"])
    provisional = read_json(content[WORKSPACE + "/step16_provisional_checkpoint.json"])
    require(provisional["protected_draft_digest"] == protected["draft_digest"] == workspace["parent_protected_digest"]
            and provisional["accepted_final_profiles"] == 0, "The protected source lineage differs.")
    checkpoint = config("results/step31_protocol_checkpoint_summary.json")
    require(checkpoint.get("classifier_protocol_id") == PROTOCOL and checkpoint.get("injected_test_dependencies") is False,
            "The production Step 31-18 checkpoint is required.")
    require(checkpoint["source_file_sha256"][WORKSPACE + "/step16_provisional_checkpoint.json"]
            == bindings[WORKSPACE + "/step16_provisional_checkpoint.json"], "The reviewed profile preparation checkpoint changed.")
    protocol = config(checkpoint["classifier_protocol_path"])
    identity = {key: value for key, value in protocol.items() if key != "protocol_id"}
    digest = sha(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    require(protocol.get("protocol_id") == digest == PROTOCOL, "The source-separation protocol changed.")
    for filename, expected in protocol["planner_source_snapshot_before_classifier_test"].items():
        bind(filename, expected)
    pointer = config("artifacts/language_model/active_resource_release.json")
    resource_folder = pointer["release_directory"]
    resource = config(resource_folder + "/manifest.json", pointer["manifest_sha256"])
    drills = config(resource_folder + "/adopted_drills.json", resource["file_hashes"]["adopted_drills.json"])
    rules = config(resource_folder + "/adopted_rules.json", resource["file_hashes"]["adopted_rules.json"])
    counts = resource["counts"]
    require(counts["basketball_variants"] == 127 and counts["warmups"] == 9 and counts["approved_rule_definitions"] == 29
            and counts["gym_exercises_approved_for_planning"] == 0
            and len(drills["records"]) == 136 and len(rules["records"]) == 29, "The expected current approved resource release differs.")
    retrieval = config(RETRIEVAL + "/step23_retrieval_evaluation_summary.json")
    manifest = config(RETRIEVAL + "/heldout_manifest.json", retrieval["output_hashes"][RETRIEVAL + "/heldout_manifest.json"])
    for filename in ("retrieval_handoff.json", "frozen_method_evaluation.json"):
        require(filename in manifest["payload_hashes"], "The held-out retrieval manifest omits a required metadata file.")
        bind(RETRIEVAL + "/" + filename, manifest["payload_hashes"][filename])
    handoff = read_json(content[RETRIEVAL + "/retrieval_handoff.json"])
    frozen = read_json(content[RETRIEVAL + "/frozen_method_evaluation.json"])
    require(retrieval.get("step23_complete") is True and retrieval.get("heldout_evaluation_verified") is True
            and retrieval["selected_route"] == handoff["runtime"]["selected_route"] == frozen["selected_route"] == "semantic"
            and retrieval["heldout_evaluation_id"] == handoff["audit_provenance"]["heldout_evaluation_id"] == frozen["heldout_evaluation_id"]
            and retrieval["reference_units"] == 11 and retrieval["heldout_questions"] == 30
            and retrieval["ranking_eligible_questions"] == 24 and retrieval["supported_coverage_denominator"] == 20
            and retrieval["empty_relevant_sets"] == 6 and retrieval["held_out_used_for_method_selection"] is False
            and retrieval["selected_route_unchanged"] is True, "The completed scoped retrieval evidence differs.")
    return {"bindings": bindings, "content": content, "protected": protected, "workspace": workspace,
            "resources": resource, "resource_folder": resource_folder, "drills": drills, "rules": rules,
            "retrieval": retrieval, "retrieval_handoff": handoff}


def build_migration_proposal(record, metadata):
    require(record.get("schema_version") == "athlete-profile-input-1", "Unexpected protected public-input version.")
    public = deepcopy(record)
    public["schema_version"] = "athlete-profile-input-2"
    require("schedule_coverage" not in public["input"], "An existing coverage declaration needs a separate version review.")
    public["input"]["schedule_coverage"] = None
    return {"profile_id": record["profile_id"], "source_record_sha256": metadata["record_sha256"],
            "source_input_sha256": sha(packed(record["input"])), "proposal_status": "not_reviewed_not_model_ready",
            "authorized_for_model_use": False, "human_authored_completeness_decision": None,
            "meaning": "Version-2 migration proposal only. Null coverage preserves uncertainty; no completeness declaration was inferred.",
            "proposed_public_record": public}


def validate_templates(content, records, metadata):
    expected = {record["profile_id"]: record for record in records}
    cases = csv_records(content[WORKSPACE + "/protected_case_review_TEMPLATE.csv"])
    require(len(cases) == 200 and {row["profile_id"] for row in cases} == set(expected), "The case-review template population differs.")
    for row in cases:
        record = expected[row["profile_id"]]
        require(row["record_sha256"] == metadata[row["profile_id"]]["record_sha256"]
                and row["input_sha256"] == sha(packed(record["input"])) and read_json(row["input_json"]) == record["input"],
                "A case-review template no longer matches its candidate input.")
    families = csv_records(content[WORKSPACE + "/protected_family_proposals_TEMPLATE.csv"])
    members = [pid for row in families for pid in read_json(row["member_profile_ids_json"])]
    require(len(members) == 200 and len(set(members)) == 200 and set(members) == set(expected), "Family proposal membership differs from the protected candidates.")
    pairs = csv_records(content[WORKSPACE + "/protected_pair_review_evidence_TEMPLATE.csv"])
    for row in pairs:
        pid = row["candidate_profile_id"]
        require(pid in expected and row["candidate_record_sha256"] == metadata[pid]["record_sha256"]
                and row["candidate_input_sha256"] == sha(packed(expected[pid]["input"])), "An overlap-review candidate join changed.")
    return {"case_rows": len(cases), "family_proposals": len(families), "overlap_rows": len(pairs)}


def make_html(records, metadata, proposals, reference_info):
    cards = []
    for number, (record, proposal) in enumerate(zip(records, proposals), 1):
        row, public = metadata[record["profile_id"]], record["input"]
        e = lambda value: html.escape(str(value), quote=True)
        cards.append('<article id="case-' + str(number) + '"><h2>Case ' + str(number) + ' · age ' + e(public["age"]) + '</h2>'
            + '<p class="status">Unaccepted draft · proposed category: ' + e(row["scenario_intent"]) + '</p>'
            + '<p><b>Profile:</b> ' + e(record["profile_id"]) + '<br><b>Proposed family:</b> ' + e(row["proposed_family_id"]) + '</p>'
            + '<h3>Request</h3><p>' + e(public["athlete_request"]) + '</p>'
            + '<details><summary>Original athlete information</summary><pre>' + e(json.dumps(public, ensure_ascii=False, indent=2)) + '</pre></details>'
            + '<details><summary>Version-2 migration proposal — not approved</summary><pre>' + e(json.dumps(proposal, ensure_ascii=False, indent=2)) + '</pre></details>'
            + '<h3>Review before acceptance</h3><ul><li>Confirm category, expected response and actual family; review every linked overlap flag.</li>'
            + '<li>Record essential constraints and checks. For a feasible case, provide a private witness using approved activities and applicable rules.</li>'
            + '<li>Choose any new fictional schedule-coverage fact explicitly. Null coverage is not complete.</li>'
            + '<li>Have a real preparer and a distinct teammate record their own review decisions.</li></ul>'
            + '<p>Use the matching profile ID in <a href="working/review_decisions.csv">review_decisions.csv</a> and the working annotation and feasibility worksheets.</p></article>')
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Final planner case review</title>'
        '<style>body{font:16px/1.55 system-ui,sans-serif;max-width:1000px;margin:35px auto;padding:0 22px;background:#f5f7fa;color:#18212e}'
        'article{background:white;border:1px solid #d7dee8;padding:24px;margin:20px 0;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}'
        '.status{background:#fff1cf;padding:8px}input{padding:10px;width:95%;font:inherit}a{color:#1456a3}h2{margin-top:0}'
        '@media print{input{display:none}article{break-before:page}body{background:white}}</style>'
        '<h1>Final planner case review</h1><p>200 fictional candidate cases. This is a private preparation package, not an accepted benchmark or a set of planner results.</p>'
        '<p>Approved resources: ' + html.escape(str(reference_info["basketball"])) + ' basketball records, '
        + html.escape(str(reference_info["warmups"])) + ' warm-ups, ' + html.escape(str(reference_info["rules"])) + ' rule definitions.</p>'
        '<p><a href="README.md">Review instructions</a> · <a href="working/review_decisions.csv">Editable case decisions</a> · '
        '<a href="reference_snapshot/adopted_drills.json">Approved activities</a> · <a href="reference_snapshot/adopted_rules.json">Adopted rule definitions</a></p>'
        '<label>Find a case, age, category or request <input id="find" type="search" placeholder="Search these case cards"></label>'
        + ''.join(cards)
        + '<script>document.getElementById("find").addEventListener("input",function(){const q=this.value.toLowerCase();document.querySelectorAll("article").forEach(x=>x.hidden=!x.textContent.toLowerCase().includes(q));});</script></html>').encode("utf-8")


def execute(root, *, emit=print, dependencies=None):
    root = Path(root).resolve()
    require(dependencies is None or set(dependencies) == {"verify_step32"}, "Only the explicit software-fixture Step 32 verifier may be injected.")
    injected = dependencies is not None
    completion = (dependencies["verify_step32"] if injected else verify_step32)(root)
    source = load_sources(root)
    bindings, content = source["bindings"], source["content"]
    ignore = checked(root, ".gitignore").read_text(encoding="utf-8-sig")
    require("/results/final_case_review/" in ignore.splitlines(), "The private final-case review directory needs its explicit ignore rule before writing.")
    records = [read_json(line) for line in content[PROTECTED + "/protected_test_draft_inputs.jsonl"].splitlines() if line.strip()]
    rows = csv_records(content[PROTECTED + "/protected_test_draft_manifest.csv"])
    metadata = {row["profile_id"]: row for row in rows}
    require(len(records) == len(rows) == len(metadata) == 200 and len({r["profile_id"] for r in records}) == 200
            and {r["profile_id"] for r in records} == set(metadata), "The 200 protected candidate IDs do not join exactly.")
    categories, ages = Counter(), Counter()
    for record in records:
        row = metadata[record["profile_id"]]
        require(set(record) == {"profile_id", "schema_version", "input"} and row["partition"] == "test"
                and sha(packed(record)) == row["record_sha256"], "A protected public record or identity changed.")
        require(type(record["input"].get("age")) is int and record["input"]["age"] in range(13, 18)
                and isinstance(record["input"].get("athlete_request"), str) and record["input"]["athlete_request"].strip(), "A candidate has invalid age or request information.")
        categories[row["scenario_intent"]] += 1
        ages[(record["input"]["age"], row["scenario_intent"])] += 1
    require(dict(categories) == CATEGORIES and all(ages[(age, category)] == count // 5 for age in range(13, 18)
            for category, count in CATEGORIES.items()), "The planned age/category coverage differs.")
    template_counts = validate_templates(content, records, metadata)
    worksheets = {}
    for filename in ("profile_annotation_WORKSHEETS.jsonl", "profile_feasibility_WORKSHEETS.jsonl"):
        values = [read_json(line) for line in content[WORKSPACE + "/" + filename].splitlines() if line.strip()]
        selected = [value for value in values if value["partition"] == "test"]
        indexed = {value["profile_id"]: value for value in selected}
        require(len(selected) == len(indexed) == 200 and set(indexed) == set(metadata), "Private draft worksheets do not join the protected population.")
        for record in records:
            value = indexed[record["profile_id"]]
            require(value["approved"] is False and value["annotation_status"] == "not_prepared"
                    and value["record_sha256"] == metadata[record["profile_id"]]["record_sha256"]
                    and value["input_sha256"] == sha(packed(record["input"]))
                    and value["draft_digest"] == source["protected"]["draft_digest"], "A private worksheet has stale inputs or unexpected recorded decisions.")
        worksheets[filename] = jsonl_bytes(selected)
    proposals = [build_migration_proposal(record, metadata[record["profile_id"]]) for record in records]
    info = {"basketball": 127, "warmups": 9, "rules": 29}
    identity = {"schema_version": VERSION, "source_file_sha256": bindings, "classifier_completion": completion,
                "injected_test_dependencies": injected, "category_targets": CATEGORIES,
                "candidate_records": 200, "human_reviews_claimed": 0, "source_records_changed": False,
                "code_sha256": sha(Path(__file__).read_bytes())}
    package_id = sha(packed(identity))
    relative = "results/final_case_review/" + ("software_fixture_" if injected else "") + "review_" + package_id[:20]
    folder = root / relative
    summary_path = "results/step33_fixture_summary.json" if injected else "results/step33_preparation_summary.json"
    immutable = {"source_public_profiles.jsonl": content[PROTECTED + "/protected_test_draft_inputs.jsonl"],
        "source_manifest.csv": content[PROTECTED + "/protected_test_draft_manifest.csv"],
        "source_field_lineage.csv": content[PROTECTED + "/protected_test_field_lineage.csv"],
        "migration_proposals.jsonl": jsonl_bytes(proposals),
        "case_cards.html": make_html(records, metadata, proposals, info),
        "reference_snapshot/adopted_drills.json": content[source["resource_folder"] + "/adopted_drills.json"],
        "reference_snapshot/adopted_rules.json": content[source["resource_folder"] + "/adopted_rules.json"],
        "reference_snapshot/manifest.json": content[source["resource_folder"] + "/manifest.json"],
        "reference_snapshot/retrieval_summary.json": content[RETRIEVAL + "/step23_retrieval_evaluation_summary.json"],
        "reference_snapshot/retrieval_handoff.json": content[RETRIEVAL + "/retrieval_handoff.json"],
        "reference_snapshot/frozen_method_evaluation.json": content[RETRIEVAL + "/frozen_method_evaluation.json"],
        "draft_templates/private_annotation_worksheet_schema.json": content[WORKSPACE + "/private_annotation_worksheet_schema.json"],
        "draft_templates/private_feasibility_worksheet_schema.json": content[WORKSPACE + "/private_feasibility_worksheet_schema.json"],
        "future_acceptance_requirements.json": content[WORKSPACE + "/future_acceptance_requirements.json"]}
    immutable.update({"draft_templates/" + name: data for name, data in worksheets.items()})
    for filename in ("protected_case_review_TEMPLATE.csv", "protected_family_proposals_TEMPLATE.csv", "protected_pair_review_evidence_TEMPLATE.csv"):
        immutable["draft_templates/" + filename] = content[WORKSPACE + "/" + filename]
    decisions = [{"profile_id": record["profile_id"], "record_sha256": metadata[record["profile_id"]]["record_sha256"],
        "input_sha256": sha(packed(record["input"])), "proposed_category": metadata[record["profile_id"]]["scenario_intent"],
        "proposed_family_id": metadata[record["profile_id"]]["proposed_family_id"], "review_status": "not_entered",
        "case_decision": "", "adopted_category": "", "actual_family_id": "", "expected_response_type": "",
        "existing_commitments_complete_decision": "", "prepared_by": "", "prepared_at": "", "reviewed_by": "", "reviewed_at": "",
        "feasibility_record_ref": "", "rationale": ""} for record in records]
    immutable["draft_templates/review_decisions.csv"] = csv_bytes(decisions, list(decisions[0]))
    readme = """# Final planner case review

We have prepared the 200 protected fictional candidates for real case review.
Open `case_cards.html` in a browser. It shows the requests, original public facts,
proposed categories/families and unapproved version-2 migration proposals.

## Where we enter review work

Use **working/review_decisions.csv** as the case checklist. Enter the preparer's
actual name/date and a distinct teammate's actual name/date after each person
has reviewed the case. Leave them blank until that work happens. Complete the
matching annotation and feasibility worksheets, family proposals and pair-review
evidence in **working/**. Every form uses the original profile ID and hashes.
Record category, expected behavior, essential constraints, required/advisory
checks, applicable adopted rule IDs/versions, uncertainty and the evidence basis.
For each feasible case, give a private witness plan using approved activities
and applicable rules. The witness proves that at least one solution exists;
it is not the unique correct generated plan. Review all overlap flags before
adopting real family assignments and excluding development relatives.

Only **working/** is editable. The other files are immutable source snapshots
and blank originals. Rerunning preparation preserves every working-file edit.
The draft worksheet schemas deliberately prohibit approval. Completed working
forms will need a separately implemented acceptance validation and a recorded
final population freeze before final model testing. This cell neither accepts
cases nor creates human ratings or reviews.

## Schedule coverage and the public/private boundary

`migration_proposals.jsonl` proposes the current version-2 record wrapper while
keeping schedule_coverage null. Null means unknown; an empty or nonempty event
list does not establish completeness. Any new true/false declaration must be
an explicit, reviewed fictional authoring decision with original/new hashes.
Do not send migration proposals or original draft wrappers to the final models
until they have been accepted and exported under the public input contract.

Categories, expectations, check masks, families, feasibility witnesses, reviewer
names and these case cards stay private. Models may receive only the eventual
accepted public `input`. Do not add this directory to retrieval or publish it.
The driver protects its parent directory with an explicit ignore rule.

## References and existing retrieval results

The reference snapshots contain 127 approved basketball records, nine warm-ups
and 29 adopted rule definitions. Gym exercises remain unavailable. Resource
approval alone does not establish feasibility, source adaptation approval,
athlete suitability or complete automatic rule checking for any case.

Step 23 already completed its selected semantic-retrieval evaluation: 30 queries
against 11 admitted reference units, 24 ranking-eligible questions, 20 with
accepted complete-evidence bundles and six with empty relevant sets. We reuse
that saved evidence without another search or model call. Its limited corpus
does not establish coverage of all current approved drills or complete planner
quality. Historical pending flags in old checkpoints are not new failures.

We will freeze the final case expectations, source/runtime versions and human
review sampling/assignments before final planner execution. Step 34's quality
ratings remain separate, and no independent human work is invented here.
"""
    immutable["README.md"] = readme.encode("utf-8")
    manifest = {**identity, "package_id": package_id, "package_directory": relative,
                "files": {name: sha(data) for name, data in immutable.items()}, "mutable_directory": "working/",
                "accepted_final_profiles": 0, "final_planner_execution_authorized": False}
    save_once(folder / "manifest.json", packed(manifest))
    for name, data in immutable.items():
        save_once(folder / name, data)
    for name, data in immutable.items():
        if name.startswith("draft_templates/") and not name.endswith("_schema.json"):
            path = folder / "working" / name.removeprefix("draft_templates/")
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                with path.open("xb") as handle:
                    handle.write(data)
    for filename, expected in bindings.items():
        require(sha(checked(root, filename).read_bytes()) == expected, "A source changed during case-review preparation.")
    summary = {"schema_version": VERSION, "status": "review_package_prepared_not_accepted", "package_id": package_id,
        "package_directory": relative, "case_cards_path": relative + "/case_cards.html", "working_directory": relative + "/working",
        "review_cases": 200, "category_targets": CATEGORIES, "accepted_final_profiles": 0, "human_reviews_entered": 0,
        "human_reviews_created_by_this_cell": 0, "working_decisions_imported": False, "template_counts": template_counts,
        "final_planner_execution_authorized": False, "injected_test_dependencies": injected,
        "retrieval_results_reused": True, "retrieval_scope": {"reference_units": 11, "heldout_questions": 30,
            "ranking_eligible": 24, "complete_evidence": 20, "empty_relevant": 6, "selected_route": "semantic"},
        "new_model_calls": 0, "new_query_encodings": 0, "human_ratings_created": 0,
        "original_candidate_inputs_changed": False, "classifier_predictions_parsed": False,
        "manifest_path": relative + "/manifest.json", "manifest_sha256": sha(packed(manifest)), "summary_path": summary_path}
    save_once(root / summary_path, packed(summary))
    return summary
