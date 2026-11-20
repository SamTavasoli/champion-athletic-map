"""We check archive and reference boundaries with fictional source records."""

from io import BytesIO
import json
from pathlib import Path
import shutil
import socket
import zipfile

import pytest

from champion_athletic_map import final_saved_export as export
from champion_athletic_map import final_saved_results as reader


def test_archives_are_repeatable_and_preserve_exact_bytes():
    files = {"reply.txt": "Café Ω 🏀\nExact reply.".encode("utf-8"), "sub/reference.json": b"{}\n"}
    first = export.zip_bytes(files)
    assert first == export.zip_bytes(dict(reversed(list(files.items()))))
    with zipfile.ZipFile(BytesIO(first)) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == files


@pytest.mark.parametrize("name", ["../private.json", "/absolute.json", "C:/drive.json", "sub\\file.json"])
def test_archive_names_cannot_escape_the_export_folder(name):
    with pytest.raises(ValueError, match="archive name"):
        export.zip_bytes({name: b"x"})


def test_network_attempts_are_blocked_during_saved_export():
    with export.offline_only(), socket.socket() as connection:
        with pytest.raises(RuntimeError, match="does not make network requests"):
            connection.connect(("127.0.0.1", 9))


def test_source_case_mappings_are_not_allowed_in_neutral_records():
    with pytest.raises(ValueError, match="case or workflow mapping"):
        export.source_keys_are_neutral({"data": {"planner_version": 4}})
    export.source_keys_are_neutral({"source_version": "recorded-source-1", "amount": "1.250"})


def test_complete_neutral_source_records_keep_values_and_qualifiers(tmp_path):
    package = tmp_path / "src/champion_athletic_map"
    package.mkdir(parents=True)
    shutil.copyfile(Path(reader.__file__), package / "final_saved_results.py")
    relative = "artifacts/language_model/approved_resources/software-only"
    folder = tmp_path / relative
    folder.mkdir(parents=True)
    records = {"adopted_drills.json": b'{"records":[{"catalog_candidate_id":"SOFTWARE-1"}]}\n',
        "adopted_rules.json": b'{"records":[{"candidate_rule_id":"SOFTWARE-RULE"}]}\n'}
    for name, data in records.items():
        (folder / name).write_bytes(data)
    manifest = {"file_hashes": {name: export.sha(data) for name, data in records.items()}}
    (folder / "manifest.json").write_bytes(export.packed(manifest))
    pointer = {"release_directory": relative, "manifest_sha256": export.sha(export.packed(manifest))}
    (tmp_path / "artifacts/language_model/active_resource_release.json").write_bytes(export.packed(pointer))
    lookup = {"status": "found", "source_refs": ["https://example.invalid/source"],
        "data": {"description": "Fictional food", "food_id": "software-food", "grams": "100",
            "nutrients": [{"amount": "1.250", "source_footnote": "Retained source qualification."}]},
        "trace": {"profile_id": "private-software-case"}}
    packet = {"packet_id": "private-packet", "payload": {"references": [{"reference_unit_id": "software-unit",
        "passage_id": "software-passage", "complete_required_delivery_text": "Complete fictional source text."}],
        "food_lookup": [lookup]}}
    result = export.prepare_neutral_sources(tmp_path, {"reference_packets": [packet, packet]})
    assert result["counts"] == {"provided_reference_units": 1, "provided_food_lookups": 1}
    foods = json.loads(result["files"]["neutral_references/provided_food_records.json"])
    assert foods[0]["data"] == lookup["data"] and "trace" not in foods[0]
    assert result["files"]["neutral_references/approved_activities.json"] == records["adopted_drills.json"]
    assert b"private-software-case" not in b"\n".join(result["files"].values())


def test_software_export_cannot_use_native_result_paths(tmp_path):
    with pytest.raises(ValueError, match="testing namespace"):
        export.export(tmp_path, software_evidence={}, expected_manifest_id="software-only", software_fixture=True)
