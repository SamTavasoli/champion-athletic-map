"""Recheck case relationships with the saved screen and current development inputs."""

from collections import Counter
from copy import deepcopy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath

VERSION = "step33-family-reconciliation-proposals-1"
PROTECTED = "results/profile_preparation/protected_test_drafts_6f292bd047b72685"
DEVELOPMENT = "results/profile_preparation/development_drafts_7b7f2fc781077cdc"
GENERATOR_SHA256 = "b4952fac39cd254a02bda896169bfa656b02888eaca273c59eacb3eadaf6d298"


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _path(root, name):
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name, "Invalid family-review source path.")
    value = PurePosixPath(name)
    require(not value.is_absolute() and value.as_posix() == name and not set(value.parts) & {".", ".."}, "Invalid family-review source path.")
    path = root / name
    require(path.resolve() == path and path.is_file(), "Missing or linked development source: " + name)
    return path


def _json(data):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            require(key not in out, "Duplicate family-review JSON key.")
            out[key] = value
        return out
    return json.loads(data, object_pairs_hook=unique,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("Nonfinite family-review JSON value.")))


def _records(data):
    records = [_json(line) for line in data.splitlines() if line.strip()]
    require(records and len({row.get("profile_id") for row in records}) == len(records), "Development profile IDs must be nonempty and unique within each saved version.")
    require(all(isinstance(row.get("profile_id"), str) and row["profile_id"] and isinstance(row.get("input"), dict) for row in records), "Invalid development public record.")
    return records


def _common_input(record):
    value = deepcopy(record["input"])
    value.pop("schedule_coverage", None)
    return value


def compare_populations(profiles, development_groups, helper):
    """Screen all supplied candidate–development pairs; similarity never adopts a family."""
    require(profiles and len({row["profile_id"] for row in profiles}) == len(profiles), "Candidate IDs must be unique.")
    require(getattr(helper, "SCREEN_VERSION", None) == "protected-overlap-screen-1", "The original overlap-screen version is required.")
    require(len({group["label"] for group in development_groups}) == len(development_groups), "Development version labels must be unique.")
    candidates = sorted(profiles, key=lambda row: row["profile_id"])
    left_views = {row["profile_id"]: helper.comparison_view(row) for row in candidates}
    prepared_groups = []
    for group in development_groups:
        rows = group["profiles"]
        require(len({row["profile_id"] for row in rows}) == len(rows), "Duplicate IDs in a development version.")
        prepared_groups.append((group["label"], sorted(rows, key=lambda row: row["profile_id"]),
                                {row["profile_id"]: helper.comparison_view(row) for row in rows}))
    pairs, by_case = [], {row["profile_id"]: [] for row in candidates}
    comparison_counts = Counter()
    for candidate in candidates:
        for label, rows, right_views in prepared_groups:
            for development in rows:
                comparison_counts[label] += 1
                exact = packed(candidate["input"]) == packed(development["input"])
                common_exact = packed(_common_input(candidate)) == packed(_common_input(development))
                finding = helper.compare_views(left_views[candidate["profile_id"]], right_views[development["profile_id"]],
                    candidate["input"].get("athlete_request", ""), development["input"].get("athlete_request", ""), exact_full_input=exact)
                if finding is None and not common_exact:
                    continue
                finding = deepcopy(finding or {})
                row = {"candidate_profile_id": candidate["profile_id"], "development_profile_id": development["profile_id"],
                    "development_version": label, "candidate_record_sha256": sha(packed(candidate)),
                    "development_record_sha256": sha(packed(development)), "exact_full_input": exact,
                    "common_input_equal_without_schedule_coverage": common_exact,
                    "comparison_qualification": "Removing schedule_coverage is a separate alignment diagnostic; it does not make different completeness facts identical.",
                    "original_screen_findings": finding,
                    "proposed_action": "review_exact_public_fact_relationship" if exact or common_exact else "review_similarity_without_assuming_ancestry",
                    "adopted_family_id": None, "exclude_candidate": False, "team_decision": None}
                row["pair_id"] = "current-development-screen:" + sha(packed({k: row[k] for k in
                    ("candidate_profile_id", "development_profile_id", "development_version", "candidate_record_sha256", "development_record_sha256")}))[:24]
                pairs.append(row)
                by_case[candidate["profile_id"]].append(row)
    proposals = []
    for candidate in candidates:
        linked = by_case[candidate["profile_id"]]
        ids = sorted({row["development_profile_id"] for row in linked})
        exact_ids = sorted({row["development_profile_id"] for row in linked if row["exact_full_input"]})
        common_ids = sorted({row["development_profile_id"] for row in linked if row["common_input_equal_without_schedule_coverage"]})
        proposals.append({"profile_id": candidate["profile_id"], "candidate_record_sha256": sha(packed(candidate)),
            "current_development_link_count": len(linked), "distinct_development_profile_ids": ids,
            "exact_full_input_match_ids": exact_ids, "common_input_match_ids": common_ids,
            "screen_pair_ids": [row["pair_id"] for row in linked],
            "proposal_status": "relationship_review_needed" if linked else "no_flag_in_current_saved_screen_not_independence_clearance",
            "proposed_family_decision": "Keep the original family proposal pending. Resolve actual authoring/source relationships before adopting a family.",
            "adopted_family_id": None, "excluded": False, "team_decision": None,
            "independence_established": False})
    return {"screen_version": helper.SCREEN_VERSION, "comparison_counts": dict(comparison_counts), "flagged_pairs": pairs,
        "case_proposals": proposals, "summary": {"candidate_cases": len(candidates), "development_version_records": sum(len(g[1]) for g in prepared_groups),
            "distinct_development_profile_ids": len({row["profile_id"] for _, rows, _ in prepared_groups for row in rows}),
            "screened_pairs": sum(comparison_counts.values()), "flagged_version_pairs": len(pairs),
            "candidates_with_current_development_flags": sum(bool(by_case[row["profile_id"]]) for row in candidates),
            "exact_full_input_pairs": sum(row["exact_full_input"] for row in pairs),
            "common_input_equal_pairs": sum(row["common_input_equal_without_schedule_coverage"] for row in pairs),
            "families_adopted": 0, "cases_excluded": 0, "team_approvals_created": 0}}


def screen_families(root, profiles, sourcepackage):
    """Read the original 100-draft pool and all 20 versioned pilot public inputs."""
    root, sourcepackage = Path(root).resolve(), Path(sourcepackage).resolve()
    bindings = {}
    def read(name, expected=None):
        data = _path(root, name).read_bytes()
        require(expected is None or sha(data) == expected, "A development rescreen source changed: " + name)
        bindings[name] = sha(data)
        return data
    source_manifest_bytes = (sourcepackage / "manifest.json").read_bytes()
    source_manifest = _json(source_manifest_bytes)
    require(source_manifest.get("injected_test_dependencies") is False and source_manifest.get("candidate_records") == 200,
            "The native 200-case review package is required for the development rescreen.")
    original_data = (sourcepackage / "source_public_profiles.jsonl").read_bytes()
    require(source_manifest["files"]["source_public_profiles.jsonl"] == sha(original_data), "The original candidate input snapshot changed.")
    originals = _records(original_data)
    require(len(profiles) == 200 and {row["profile_id"] for row in profiles} == {row["profile_id"] for row in originals}, "The candidate correction population changed.")
    original_by_id = {row["profile_id"]: row for row in originals}
    old_flags_path = "draft_templates/protected_pair_review_evidence_TEMPLATE.csv"
    old_flags_data = (sourcepackage / old_flags_path).read_bytes()
    require(sha(old_flags_data) == source_manifest["files"][old_flags_path], "The saved prior relationship evidence changed.")
    old_flags = list(csv.DictReader(io.StringIO(old_flags_data.decode("utf-8-sig"), newline="")))
    require(len(old_flags) == 618 and len({row["screen_pair_id"] for row in old_flags}) == 618,
            "The prior relationship evidence is incomplete.")
    prior_incident = {identifier: [] for identifier in original_by_id}
    for row in old_flags:
        candidate = row["candidate_profile_id"]
        require(candidate in original_by_id and row["candidate_record_sha256"] == sha(packed(original_by_id[candidate])),
                "A prior relationship row differs from its original candidate.")
        prior_incident[candidate].append(row["screen_pair_id"])
        if row["comparison_kind"] == "protected_candidate":
            other = row["other_record_id"]
            require(other in original_by_id and row["other_record_sha256"] == sha(packed(original_by_id[other])),
                    "A prior candidate-pair record differs from its original facts.")
            prior_incident[other].append(row["screen_pair_id"])
    protected_name = PROTECTED + "/step16_protected_test_drafts_summary.json"
    protected = _json(read(protected_name, source_manifest["source_file_sha256"][protected_name]))
    helper_path = PROTECTED + "/protected_generator.py"
    helper_bytes = read(helper_path, GENERATOR_SHA256)
    require(protected["artifacts"]["protected_generator.py"] == GENERATOR_SHA256
            and source_manifest["source_file_sha256"].get(helper_path) == GENERATOR_SHA256, "The original overlap-screen source differs.")
    summary_path = DEVELOPMENT + "/step16_development_drafts_summary.json"
    summary = _json(read(summary_path, protected["input_hashes"][summary_path]))
    pool_path = DEVELOPMENT + "/development_draft_inputs.jsonl"
    pool = _records(read(pool_path, summary["artifacts"]["development_draft_inputs.jsonl"]))
    require(len(pool) == summary.get("development_drafts") == 100, "The full development draft population differs.")
    pilot_summary_name = "results/step31_case_review_summary.json"
    pilot = _json(read(pilot_summary_name))
    require(pilot.get("reviewed_cases") == pilot.get("public_profiles_versioned") == 20
            and pilot.get("original_inputs_preserved") is True, "The completed versioned development case record is required.")
    paths = pilot["review_files"]
    def suffix(value):
        selected = [name for name in paths if name.endswith(value)]
        require(len(selected) == 1, "Ambiguous or missing current development artifact: " + value)
        return selected[0]
    pilot_path = suffix("/public_profiles.jsonl")
    amended = _records(read(pilot_path, paths[pilot_path]))
    amendment_path = suffix("/public_amendments.json")
    amendments = _json(read(amendment_path, paths[amendment_path]))
    require(len(amended) == len(amendments) == 20, "The versioned development population is incomplete.")
    pool_by_id = {row["profile_id"]: row for row in pool}
    changes_by_id = {row["profile_id"]: row for row in amendments}
    require(len(changes_by_id) == 20 and set(changes_by_id) == {row["profile_id"] for row in amended}, "Development amendment IDs differ.")
    canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    for record in amended:
        identifier = record["profile_id"]
        require(identifier in pool_by_id and record.get("schema_version") == "athlete-profile-input-2", "A development amendment lost its source record.")
        original, change = pool_by_id[identifier], changes_by_id[identifier]
        require(change["source_public_record_sha256"] == sha(canonical(original))
                and change["amended_public_record_sha256"] == sha(canonical(record)), "A development amendment fingerprint differs.")
        reverted = deepcopy(record)
        reverted["schema_version"] = original["schema_version"]
        coverage = reverted["input"].pop("schedule_coverage", None)
        require(reverted == original and isinstance(coverage, dict) and type(coverage.get("existing_commitments_complete")) is bool
                and coverage["existing_commitments_complete"] == change["existing_commitments_complete"], "The development public amendment contains an unrecorded change.")
    spec = importlib.util.spec_from_file_location("step33_frozen_relationship_screen", _path(root, helper_path))
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    result = compare_populations(profiles, [{"label": "original_development_drafts_v1", "profiles": pool},
        {"label": "versioned_pilot_development_v2", "profiles": amended}], helper)
    corrected_by_id = {row["profile_id"]: row for row in profiles}
    for row in result["case_proposals"]:
        identifier = row["profile_id"]
        row["source_candidate_record_sha256"] = sha(packed(original_by_id[identifier]))
        row["candidate_version_differs_from_source"] = packed(corrected_by_id[identifier]) != packed(original_by_id[identifier])
        row["retained_prior_screen_pair_ids"] = sorted(set(prior_incident[identifier]))
        row["prior_relationship_decisions_cleared"] = False
    result.update(schema_version=VERSION, source_package_id=source_manifest["package_id"], source_manifest_sha256=sha(source_manifest_bytes),
        source_file_sha256=bindings, development_review_summary_path=pilot_summary_name, current_development_rescreen_completed=True,
        candidate_basis="Supplied candidate versions; original source IDs and source snapshots preserved.",
        comparison_scope="100 original development drafts plus the 20 versioned pilot states of selected drafts; not 120 independent development athletes.",
        team_review_status="pending", original_case_values_changed=False, model_calls=0,
        adopted_family_decisions_created=0, interpretation="A fresh use of the unchanged saved screen. Flags are review leads; neither similarity nor a clean screen establishes ancestry or independence.")
    result["retained_prior_screen"] = {"path_within_source_package": old_flags_path, "sha256": sha(old_flags_data),
        "rows": 618, "counts_by_kind": dict(Counter(row["comparison_kind"] for row in old_flags)),
        "pair_ids": [row["screen_pair_id"] for row in old_flags],
        "pending_relationship_decisions": "All previous findings remain available for team review; a new clean screen does not clear them."}
    result["summary"]["candidate_versions_differing_from_source"] = sum(row["candidate_version_differs_from_source"] for row in result["case_proposals"])
    result["summary"]["prior_flag_rows_retained"] = 618
    for name, expected in bindings.items():
        require(sha(_path(root, name).read_bytes()) == expected, "A source changed during the development rescreen.")
    return result
