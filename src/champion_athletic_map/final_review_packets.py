"""Bind the preselected team-review forms to unchanged designated final replies."""

from collections import Counter
from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re

VERSION = "designated-final-team-review-packets-1"
PREPARED_FILES = ("private_review_sample.jsonl", "private_response_key.jsonl",
    "private_reviewer_assignments.json", "review_forms_pending.jsonl",
    "rating_templates_pending.jsonl", "review_rubric.md", "reference_access.json", "review_preparation.json")
DIMENSIONS = ("response_suitability", "profile_fit", "practicality_completeness", "evidence_accuracy", "clarity")
SLOTS = ("reviewer-slot-A", "reviewer-slot-B")


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def jsonl(rows):
    return b"".join(canonical(row) + b"\n" for row in rows)


def decode(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "A review source repeats a JSON key.")
            value[key] = item
        return value
    return json.loads(data, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("A review source contains a nonfinite number.")))


def path_inside(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative and ":" not in relative,
            "A review dependency must be a project-relative path.")
    value = PurePosixPath(relative)
    require(not value.is_absolute() and value.as_posix() == relative
            and not set(value.parts) & {".", ".."}, "A review dependency leaves the project.")
    result = root / relative
    require(result.resolve() == result, "A review dependency has an unexpected linked location.")
    return result


def citations(raw):
    """Copy explicit citation strings only; no source or claim is validated here."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = decode(raw)
    except (ValueError, UnicodeError, TypeError):
        return None
    result = []
    def add(value):
        if isinstance(value, str) and value not in result:
            result.append(value)
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "source_ref":
                    add(item)
                elif key == "evidence_refs" and isinstance(item, list):
                    for ref in item:
                        add(ref)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(parsed)
    return result


def page(forms, order, slot):
    escape = html.escape
    rows = {row["response_id"]: row for row in forms}
    pieces = ["<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        "<title>Team response review</title><style>body{font:16px/1.5 system-ui,sans-serif;margin:auto;padding:2rem;max-width:1000px;color:#19212d;background:#f6f8fb}h1,h2,h3{line-height:1.2}article{background:white;border:1px solid #d8dfe9;border-radius:10px;padding:1.5rem;margin:1.5rem 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f4f8;padding:1rem;border-radius:6px}a{color:#1558a6}.note{border-left:4px solid #557ca5;padding-left:1rem}nav{columns:3}nav a{display:block}</style>",
        "<h1>Team response review</h1>",
        "<p>Presentation order " + escape(slot.rsplit("-", 1)[-1]) + " · 160 saved replies</p>",
        "<p class=\"note\">We review the athlete information and the reply exactly as returned. Workflow labels and check results are withheld. The same input can occur more than once. This file contains no entered ratings and assigns no reviewer.</p>",
        "<p>Use the <a href=\"review_rubric.md\">five-dimension rubric</a> and the <a href=\"neutral_references/index.html\">neutral source records</a> supplied with this packet. Assign two distinct reviewers and complete development practice before accepting ratings. Keep the first independent ratings separate from any later discussion.</p>",
        "<nav aria-label=\"Saved replies\">"]
    for index, identifier in enumerate(order, 1):
        pieces.append('<a href="#' + escape(identifier, quote=True) + '">' + str(index) + ". " + escape(identifier) + "</a>")
    pieces.append("</nav>")
    for index, identifier in enumerate(order, 1):
        row = rows[identifier]
        pieces += ['<article id="' + escape(identifier, quote=True) + '">',
            "<h2>" + str(index) + ". " + escape(identifier) + "</h2>",
            "<h3>Athlete information</h3><pre>" + escape(packed(row["athlete_input"]).decode("utf-8")) + "</pre>",
            "<h3>Saved reply</h3>"]
        text = row["response_text"]
        if text is None or text == "":
            pieces.append("<p>No reply text was returned.</p>")
        else:
            pieces.append("<pre>" + escape(text) + "</pre>")
        pieces.append("</article>")
    pieces.append("</html>\n")
    return "\n".join(pieces).encode("utf-8")


def prepare_review_packets(root, manifest, setup, rows, *, source_bindings, software_fixture=False):
    """Read the pre-output sample; return public packets and separate private bindings."""
    root = Path(root).resolve()
    require(manifest.get("software_fixture") is software_fixture
            and setup.get("software_fixture") is software_fixture,
            "A review software fixture cannot stand in for the completed comparison.")
    require(setup.get("case_freeze_id") == manifest.get("case_freeze_id"),
            "The team-review setup belongs to another case freeze.")
    folder = setup["team_review_package_directory"]
    frozen = manifest["protocol"]["review_source_sha256"]
    prepared, hashes = {}, {}
    for name in PREPARED_FILES:
        relative = folder + "/" + name
        expected = frozen.get(relative)
        require(isinstance(expected, str) and source_bindings.get(relative) == expected,
                "A preselected review dependency lacks its frozen binding: " + name)
        data = path_inside(root, relative).read_bytes()
        require(sha(data) == expected, "A preselected review file changed: " + name)
        prepared[name] = data
        hashes[relative] = expected
    def lines(name):
        return [decode(line) for line in prepared[name].splitlines()]
    sample = lines("private_review_sample.jsonl")
    keys = lines("private_response_key.jsonl")
    forms = lines("review_forms_pending.jsonl")
    assignments = decode(prepared["private_reviewer_assignments.json"])
    definition = decode(prepared["review_preparation.json"])
    require(definition.get("case_freeze_id") == manifest["case_freeze_id"]
        and definition.get("summary", {}).get("sample_chosen_before_final_outputs") is True,
        "The saved sample was not recorded before final outcomes.")
    require(len(sample) == len({row["profile_id"] for row in sample}) == 40,
            "The preselected team-review sample is not 40 distinct cases.")
    require(len(keys) == len(forms) == 160 and len({row["response_id"] for row in keys}) == 160,
            "The frozen response masks are incomplete or duplicated.")
    by_form = {row["response_id"]: row for row in forms}
    require(len(by_form) == 160 and by_form.keys() == {row["response_id"] for row in keys},
            "The saved pending forms do not match the preselected masks.")
    require(len(rows) == len({row["job_id"] for row in rows}) == 800,
            "The team-review packet needs the complete designated 800-outcome roster.")
    by_job = {row["job_id"]: row for row in rows}
    profiles = {row["profile_id"]: row for row in manifest["profiles"]}
    planned = {row["job_id"]: row for row in manifest["planned_jobs"]}
    require(len(planned) == 800 and by_job.keys() == planned.keys(),
            "The designated replies differ from the frozen job roster.")
    selected = {row["profile_id"]: row for row in sample}
    require(Counter((row["profile_id"], row["planner_version"]) for row in keys)
        == Counter({(pid, version): 1 for pid in selected for version in range(1, 5)}),
        "The frozen review sample does not retain all four outcomes per case.")
    populated, bound = [], []
    for key in keys:
        job, result = planned.get(key["job_id"]), by_job.get(key["job_id"])
        require(job is not None and result is not None
            and job["profile_id"] == result["profile_id"] == key["profile_id"]
            and job["planner_version"] == result["planner_version"] == key["planner_version"],
            "A masked reply belongs to another case or workflow.")
        profile = profiles[key["profile_id"]]
        digest = sha(packed(profile))
        require(digest == key["public_record_sha256"] == selected[key["profile_id"]]["public_record_sha256"]
            == result["public_record_sha256"] == job["public_record_sha256"]
            and canonical(result["public_input"]) == canonical(profile["input"]),
            "A review reply refers to another public case version.")
        original = by_form[key["response_id"]]
        require(original.get("response_state") == "pending_final_outcome"
            and original.get("response_text") is None and original.get("response_citations") is None
            and canonical(original["athlete_input"]) == canonical(profile["input"]),
            "A pending review form was changed or populated before this binding.")
        require(key.get("designated_outcome_sha256") is None and key.get("response_text_sha256") is None,
                "The immutable pre-output mask already contains a response binding.")
        outcome = result.get("outcome_sha256", result.get("designated_outcome_sha256"))
        require(isinstance(outcome, str) and re.fullmatch(r"[0-9a-f]{64}", outcome),
                "A designated reply lacks its exact saved outcome hash.")
        raw = result.get("raw_text")
        require(raw is None or isinstance(raw, str), "A saved reply is neither text nor an absent reply.")
        require(result.get("raw_text_sha256") == (sha(raw.encode("utf-8")) if isinstance(raw, str) else None),
                "A compact review row's exact reply-text hash differs.")
        populated.append({"response_id": key["response_id"], "athlete_input": deepcopy(profile["input"]),
            "response_state": "saved_reply" if raw else "no_reply_text", "response_text": raw,
            "response_citations": citations(raw)})
        bound.append({**deepcopy(key), "designated_outcome_sha256": outcome,
            "response_text_sha256": sha(raw.encode("utf-8")) if isinstance(raw, str) else None})
    require(isinstance(assignments, list) and len(assignments) == 2
        and {row.get("reviewer_slot_id") for row in assignments} == set(SLOTS),
        "The two prepared independent review slots are incomplete.")
    orders = {}
    ids = {row["response_id"] for row in populated}
    for assignment in assignments:
        order = assignment.get("presentation_order")
        require(isinstance(order, list) and len(order) == len(set(order)) == 160 and set(order) == ids,
                "A saved reviewer presentation order is incomplete or changed.")
        require(assignment.get("assigned_reviewer_id") is None and assignment.get("assigned_reviewer_name") is None
            and assignment.get("independent_reviewer_verified") is False
            and assignment.get("calibration_state") == "not_completed",
            "Reviewer assignment or practice was changed inside the immutable preparation.")
        orders[assignment["reviewer_slot_id"]] = order
    templates = lines("rating_templates_pending.jsonl")
    require(len(templates) == 1600 and all(row.get("rating_status") == "missing"
        and row.get("score") is None and row.get("reviewer_id") is None and row.get("template_only") is True
        for row in templates), "The pending template contains entered or imputed ratings.")
    require(Counter((row["reviewer_slot_id"], row["response_id"], row["dimension"]) for row in templates)
        == Counter({(slot, identifier, dimension): 1 for slot in SLOTS for identifier in ids for dimension in DIMENSIONS}),
        "The blank rating template does not cover the recorded slots and dimensions.")
    public = {"review_responses.jsonl": jsonl(populated), "review_rubric.md": prepared["review_rubric.md"],
        "rating_templates_pending.jsonl": prepared["rating_templates_pending.jsonl"]}
    for slot in SLOTS:
        public["review_" + slot.rsplit("-", 1)[-1] + ".html"] = page(populated, orders[slot], slot)
    public["README.md"] = ("# Team response-review packet\n\n"
        "We bound the 160 masked forms to the designated saved replies for the 40 profiles selected before final outputs. "
        "Open review_A.html or review_B.html in the corresponding prepared presentation order. "
        "The exact reply text and explicit citation strings are also retained in review_responses.jsonl. "
        "The packet contains no workflow map, check scores, timings, private categories or expected case answers. "
        "Reply text can itself reveal an approach, so complete blinding is not guaranteed.\n\n"
        "No ratings have been entered. Reviewer slots are placeholders, not people. "
        "Assign two actual teammates and complete development practice before accepting independent ratings; lock initial ratings before discussion. "
        "Use the separate five-dimension rubric and the supplied neutral references. "
        "These response ratings remain separate from the frozen automatic checks and their goal-verification limitation.\n").encode("utf-8")
    summary = {"schema_version": VERSION, "sample_profiles": 40, "masked_designated_replies": 160,
        "presentation_packets": 2, "blank_rating_entries": 1600,
        "exact_raw_text_preserved": True, "existing_pre_output_sample_reused": True,
        "new_sample_selected": False, "private_labels_in_public_packet": False,
        "actual_assigned_reviewers": 0, "actual_response_ratings": 0,
        "development_calibration_completed": False, "team_review_ready_to_rate": False,
        "neutral_reference_files_verified_by_this_module": False,
        "model_calls": 0, "ratings_are_templates_only": True}
    private = {"private_bound_response_key.jsonl": jsonl(bound),
        "private_original_reference_access.json": prepared["reference_access.json"],
        "private_packet_provenance.json": packed({"schema_version": VERSION,
            "case_freeze_id": manifest["case_freeze_id"], "source_preparation_sha256": hashes,
            "source_manifest_id": manifest.get("manifest_id"),
            "public_file_sha256": {name: sha(data) for name, data in public.items()}, "summary": summary})}
    return {"public_files": public, "private_files": private, "summary": summary}
