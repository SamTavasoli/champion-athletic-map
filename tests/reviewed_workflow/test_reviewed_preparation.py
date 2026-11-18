"""Keep offline preparation distinct from live runtime and preserve saved sources."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


HERE = Path(__file__).resolve().parent
ROOT = next((p for p in HERE.parents if (p / "src/champion_athletic_map/reference_tools.py").is_file()),
            HERE.parent / "work_step30/project/folder-before-step-30")
SOURCE = ROOT / "src/champion_athletic_map/reviewed_preparation.py"
if not SOURCE.is_file():
    SOURCE = HERE / "reviewed_preparation.py"


def load(path, name):
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    exec(compile(path.read_bytes(), str(path), "exec"), result.__dict__)
    return result


API = load(SOURCE, "reviewed_preparation_tested")


def copy_file(root, relative, source=ROOT):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / relative, path)


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("reviewed_preparation")
    review = API.read(ROOT / "results/step31_saved_reply_review_summary.json")
    pilot = API.read(ROOT / "results/step31_development_pilot_summary.json")
    files = set(review["source_sha256"]) | {"results/step31_saved_reply_review_summary.json",
        "artifacts/planners/version1_config.json", "artifacts/language_model/integration_config.json"}
    for case in pilot["cases"]:
        probe = Path(case["reports"][0]["outcome_path"]).parts[3]
        manifest = API.read(ROOT / ("artifacts/pilot/shared_guidance/" + probe + "/probe_manifest.json"))
        files.update(manifest["module_and_config_sha256"])
        files.add(manifest["public_schema_path"])
    pointer_name = "artifacts/language_model/active_resource_release.json"
    pointer = API.read(ROOT / pointer_name)
    files.add(pointer_name)
    files.add(pointer["release_directory"] + "/manifest.json")
    release = API.read(ROOT / pointer["release_directory"] / "manifest.json")
    files.update(pointer["release_directory"] + "/" + name for name in release["file_hashes"])
    integration = API.read(ROOT / "artifacts/language_model/integration_config.json")
    files.update(integration["contracts_directory"] + "/" + name for name in
                 ("public_input.py", "step24_7_shared_contract_summary.json"))
    files.update("src/champion_athletic_map/" + name + ".py" for name in API._OLD)
    for relative in files:
        copy_file(root, relative)
    for name in API._NEW:
        relative = "src/champion_athletic_map/" + name + ".py"
        origin = HERE / (name + ".py")
        if not origin.is_file():
            origin = ROOT / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, destination)
    return root


@pytest.fixture(scope="module")
def offline_counter():
    counter, _ = API.pinned_counter(ROOT)
    return counter


class ReplayTools:
    """Use public lookup implementations and already captured food facts only."""
    def __init__(self, root, config, integration):
        self.root, self.source_bindings = root, {}
        selected = API.module(root, "selected_drill_context")
        catalog = selected.load_approved_catalog(root)
        public = API.module(root, "reference_tools")
        self.core = public.ReferenceTools.__new__(public.ReferenceTools)
        self.core.root = root
        self.core._drill_ids = set(catalog["records"]) | set(catalog["held_ids"])
        pointer = API.read(root / "artifacts/language_model/active_resource_release.json")
        release = API.read(root / pointer["release_directory"] / "adopted_drills.json")
        self.core._drill_ids.update(release["aliases"])
        self.core._load_approved_release()
        self.food = {}
        for trace_path in (root / "results/pilot/probes").glob("pilotcase_*/references/*/builder_trace.json"):
            for lookup in API.read(trace_path)["food_lookups"]:
                self.food[API.canonical(lookup["arguments"])] = lookup["result"]

    def get_drill(self, identifier):
        return self.core.get_drill(identifier)

    def get_planning_rules(self, age, school_grade):
        return self.core.get_planning_rules(age, school_grade)

    def lookup_food(self, **arguments):
        return deepcopy(self.food[API.canonical(arguments)])

    def complete_reference(self, item):
        return deepcopy({key: item[key] for key in
                         ("reference_unit_id", "passage_id", "complete_required_delivery_text")})


def test_twenty_offline_cases_keep_injected_evidence_and_repeat_safely(project, offline_counter):
    before = API.read(project / "results/step31_saved_reply_review_summary.json")["source_sha256"]
    kwargs = {"tools_factory": ReplayTools, "counter_factory": lambda root: (offline_counter, {})}
    result = API.execute(project, **kwargs)
    assert result["cases_prepared"] == 20
    assert result["food_focus_cases_available"] == 6
    assert result["all_packet_budgets_fit_locally"] is True
    assert result["original_packet_counts_reproduced"] == 20
    assert result["injected_test_dependencies"] is True
    assert result["new_model_calls"] == result["http_requests"] == result["query_encoder_processes"] == 0
    assert result["operational_generation_ready"] is False
    manifest = API.read(project / result["manifest_path"])
    assert manifest["prepared_packets_are_offline_diagnostics_only"] is True
    second = API.execute(project, **kwargs)
    assert second == result
    evidence = {"status": "passed", "passed": 1, "files": {}, "elapsed": 0.1}
    third = API.execute(project, software_evidence=evidence, **kwargs)
    evidence["elapsed"] = 0.2
    fourth = API.execute(project, software_evidence=evidence, **kwargs)
    assert third["manifest_id"] == fourth["manifest_id"] == result["manifest_id"]
    assert third["software_evidence"] != fourth["software_evidence"]
    archives = list((project / "results/pilot/reviewed_workflow" / result["workflow_id"] / "preparations").glob("*.json"))
    assert len(archives) == 3
    API.verify(project, before)


def test_changed_original_source_is_rejected_before_tools(project):
    source = project / "results/step31_development_pilot_summary.json"
    original = source.read_bytes()
    value = json.loads(original)
    value["recorded_jobs"] = 79
    try:
        source.write_bytes(API.canonical(value))
        with pytest.raises(ValueError, match="completed pilot"):
            API.execute(project, tools_factory=lambda *args: pytest.fail("Tools must not construct"))
    finally:
        source.write_bytes(original)


def test_missing_software_pass_is_not_accepted(project):
    with pytest.raises(ValueError, match="software checks"):
        API.execute(project, software_evidence={"status": "failed", "passed": 0})


def test_default_tool_route_requires_the_actual_unified_release(project, offline_counter):
    before = (project / API.SUMMARY).read_bytes()
    with pytest.raises((FileNotFoundError, ValueError), match="unified|dataset"):
        API.execute(project, counter_factory=lambda root: (offline_counter, {}))
    assert (project / API.SUMMARY).read_bytes() == before


def test_save_once_preserves_conflicting_record(tmp_path):
    path = tmp_path / "record.json"
    API.save_once(path, {"value": 1})
    with pytest.raises(ValueError, match="preserved"):
        API.save_once(path, {"value": 2})
    assert API.read(path) == {"value": 1}


pytestmark = pytest.mark.requirement("31:reviewed-workflow-preparation")
