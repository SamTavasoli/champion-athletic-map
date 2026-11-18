"""Read unchanged public development profiles from our shared dataset."""

import csv
import hashlib
import importlib.util
import json
from pathlib import Path


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_development_profiles(root, expected, profile_ids):
    """Return selected fictional drafts; no other row payloads are decoded."""
    root = Path(root).resolve()
    folder = (root / expected["relative_directory"]).resolve()
    if not folder.is_relative_to(root):
        raise ValueError("The shared dataset must be inside our project.")
    for name, digest in expected["file_sha256"].items():
        path = folder / name
        if not path.is_file() or file_sha256(path) != digest:
            raise ValueError("Our shared dataset file is missing or changed: " + name)
    spec = importlib.util.spec_from_file_location("champion_shared_dataset_reader", folder / "load_unified_dataset.py")
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    manifest = reader.load_manifest()
    if manifest["dataset_id"] != expected["dataset_id"]:
        raise ValueError("The shared dataset release differs from our configuration.")
    wanted = set(profile_ids)
    if len(wanted) != len(profile_ids) or not wanted:
        raise ValueError("Choose distinct development profile IDs.")
    found = {}
    previous_limit = csv.field_size_limit()
    rows = reader.iter_records(record_type="athlete_profile", record_stage="development_draft")
    try:
        for row in rows:
            if row["source_record_id"] not in wanted:
                continue
            if (row["source_dataset"] != "development_profile_drafts"
                    or row["is_synthetic"] != "true"
                    or row["classifier_use"] != "not_classifier_input"):
                raise ValueError("The selected record is not a fictional development draft.")
            record = json.loads(row["data_json"])["source_record"]
            identifier = record.get("profile_id")
            if (identifier != row["source_record_id"] or identifier in found
                    or set(record) != {"profile_id", "schema_version", "input"}):
                raise ValueError("The selected public profile wrapper is inconsistent.")
            found[identifier] = {"public_record": record, "unified_record_id": row["record_id"],
                                 "source_record_id": row["source_record_id"], "source_sha256": row["source_sha256"],
                                 "record_stage": row["record_stage"], "accepted_study_profile": False}
            if len(found) == len(wanted):
                break
    finally:
        rows.close()
        csv.field_size_limit(previous_limit)
    if set(found) != wanted:
        raise ValueError("Some selected development profiles are absent from our shared dataset.")
    return [found[identifier] for identifier in profile_ids]
