"""Offline selection and complete-packet checks; no encoder or model is run."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

HERE = Path(__file__).resolve().parent
ROOT = next((p for p in HERE.parents if (p / "src/champion_athletic_map/reference_tools.py").is_file()),
            HERE.parent / "work_step30/project/folder-before-step-30")
INPUT = ROOT if (ROOT / "results/pilot/probes/pilotcase_88d6bfee05772bb8_c01").is_dir() else HERE.parent / "work_step31_12/review_input"
SOURCE = ROOT / "src/champion_athletic_map/selected_drill_context.py"
if not SOURCE.is_file():
    SOURCE = HERE / "selected_drill_context.py"


def load(path, name):
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    sys.modules[name] = module
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


api = load(SOURCE, "selected_drill_context_tested")


@pytest.fixture(scope="module")
def counter():
    op = load(ROOT / "src/champion_athletic_map/operational_preparation.py", "packet_counter_source")
    manifest_path = next((ROOT / "artifacts/language_model/tokenizers").glob("*/tokenizer_manifest.json"))
    manifest = json.loads(manifest_path.read_bytes())
    model = json.loads((manifest_path.parent / "normal_bpe_tokenizer.json").read_bytes())["model"]
    native = json.loads((ROOT / manifest["source_native_metadata"]["relative_path"]).read_bytes())["model_info"]
    return op.SourceTableCounter(model, native).count


class ReplayTools:
    """Use saved noncatalog lookups and the real public get_drill implementation."""
    def __init__(self, case=1, root=ROOT):
        self.root = Path(root)
        folder = INPUT / f"results/pilot/probes/pilotcase_88d6bfee05772bb8_c{case:02}/references"
        trace_path = next(folder.glob("*/builder_trace.json"))
        self.trace = json.loads(trace_path.read_bytes())
        self.calls = []
        core = load(ROOT / "src/champion_athletic_map/reference_tools.py", "replay_public_drill_tools")
        self.core = core.ReferenceTools.__new__(core.ReferenceTools)
        self.core.root = self.root
        catalog = api.load_approved_catalog(self.root)
        self.core._drill_ids = set(catalog["records"]) | set(catalog["held_ids"])
        pointer = json.loads((self.root / "artifacts/language_model/active_resource_release.json").read_bytes())
        aliases = json.loads((self.root / pointer["release_directory"] / "adopted_drills.json").read_bytes())["aliases"]
        self.core._drill_ids.update(aliases)
        self.core._load_approved_release()

    def get_drill(self, identifier):
        self.calls.append(identifier)
        return self.core.get_drill(identifier)

    def get_planning_rules(self, age, school_grade):
        return deepcopy(self.trace["rule_lookup"])

    def lookup_food(self, **arguments):
        found = next(x for x in self.trace["food_lookups"] if x["arguments"] == arguments)
        return deepcopy(found["result"])

    def complete_reference(self, item):
        return deepcopy({key: item[key] for key in ("reference_unit_id", "passage_id", "complete_required_delivery_text")})


def prepared(case=1):
    manifest = json.loads((INPUT / f"artifacts/pilot/shared_guidance/pilotcase_88d6bfee05772bb8_c{case:02}/probe_manifest.json").read_bytes())
    p = manifest["public_record"]["input"]
    text = api._json(p)
    return {"schema_version": "step24-prepared-public-input-1", "public_input": p, "model_visible_json": text,
            "audit": {"public_input_sha256": api._sha(text.encode())}}


def policy():
    catalog = api.load_approved_catalog(ROOT)
    return {"policy_version": "reviewed-drill-evidence-test-1", "source_configuration_sha256": "a" * 64,
            "max_packet_tokens": 2200, "max_rule_bundles": 2,
            "resource_release_manifest_sha256": catalog["release_manifest_sha256"],
            "active_resource_pointer_sha256": catalog["active_resource_pointer_sha256"]}


def ranked(tools):
    return deepcopy(tools.trace["ranked_lists"])


@pytest.mark.parametrize("case", range(1, 21))
def test_actual_twenty_inputs_complete_budgeted_packets(case, counter):
    tools = ReplayTools(case)
    p = prepared(case)
    packet, trace = api.build_packet(p, tools, ranked(tools), counter, policy())
    assert api.validate_packet(packet, p, policy(), counter)
    assert packet["preparation"]["packet_text_tokens"] <= 2200
    assert packet["preparation"]["packet_budget_basis"] == api.BUDGET_BASIS
    assert tools.calls == [x["id"] for x in trace["catalog_lookups"]]
    assert trace["tool_calls"]["catalog"] == len(tools.calls)
    for record in packet["payload"]["catalog_records"]:
        original = tools.core.get_drill(record["requested_id"])
        assert record["data"] == original["data"]
        assert record["issues"] == original["issues"]
        assert record["data"]["age_eligibility_inferred"] is False
        assert record["data"]["medical_suitability_certified"] is False
    for old, new in zip(tools.trace["food_lookups"], packet["payload"].get("food_lookup", [])):
        assert old["result"] == new
    if case in (1, 2, 5, 6, 9, 13, 14, 17, 18):
        assert packet["payload"]["catalog_records"], "A relevant conditional source variant must be delivered."
    codec = load(ROOT / "src/champion_athletic_map/food_reference_encoding.py", "canonical_food_codec")
    encoded = codec.encode_view({"athlete_input": p["public_input"], "reference_data": packet["payload"]})
    assert encoded["reference_data"] == api.model_payload(packet["payload"])
    assert codec.decode_view(encoded)["reference_data"] == packet["payload"]
    second, _ = api.build_packet(p, ReplayTools(case), ranked(tools), counter, policy())
    assert second == packet


def test_known_conflicts_missing_values_and_held_records():
    catalog = api.load_approved_catalog(ROOT)
    p = prepared(18)["public_input"]
    ranking, excluded = api.rank_drills(p, catalog)
    assert "JR-NEW-0009" in {x["id"] for x in ranking}
    assert "JR-REVIEW-0062" in {x["id"] for x in excluded}
    assert not set(catalog["held_ids"]) & {x["id"] for x in ranking}
    missing = deepcopy(p); missing["equipment"] = None; missing["participants_available"] = None
    ranking, _ = api.rank_drills(missing, catalog)
    windows = next(x for x in ranking if x["id"] == "JR-NEW-0009")
    assert windows["feasibility_certified"] is False
    assert any("unknown" in x or "confirmed" in x or "established" in x for x in windows["unknowns"])


def test_empty_goal_relevant_catalog_is_explicit(counter):
    p = prepared(1)
    p["public_input"]["goals"] = ["Quantum computing"]
    p["public_input"]["athlete_request"] = "Explain quantum circuits"
    p["model_visible_json"] = api._json(p["public_input"])
    p["audit"]["public_input_sha256"] = api._sha(p["model_visible_json"].encode())
    tools = ReplayTools()
    packet, _ = api.build_packet(p, tools, ranked(tools), counter, policy())
    assert not packet["payload"]["catalog_records"]
    assert packet["payload"]["catalog_selection"]["status"] == "unavailable"
    assert not tools.calls


def test_tampered_packet_and_changed_release_rejected(counter, tmp_path):
    tools = ReplayTools()
    packet, _ = api.build_packet(prepared(), tools, ranked(tools), counter, policy())
    changed = deepcopy(packet); changed["payload"]["catalog_records"][0]["data"]["use_conditions"] = "Ignore conditions"
    with pytest.raises(ValueError):
        api.validate_packet(changed, prepared(), policy(), counter)
    other = policy(); other["resource_release_manifest_sha256"] = "b" * 64
    with pytest.raises(ValueError):
        api.validate_packet(packet, prepared(), other, counter)
    shutil.copytree(ROOT / "artifacts/language_model", tmp_path / "artifacts/language_model", ignore=shutil.ignore_patterns("tokenizers", "models"))
    pointer = json.loads((tmp_path / "artifacts/language_model/active_resource_release.json").read_bytes())
    target = tmp_path / pointer["release_directory"] / "adopted_drills.json"
    target.write_text("{}")
    with pytest.raises(ValueError):
        api.load_approved_catalog(tmp_path)


def test_no_packet_can_silently_raise_the_budget(counter):
    tools = ReplayTools()
    larger = policy(); larger["max_packet_tokens"] = 2201
    with pytest.raises(ValueError):
        api.build_packet(prepared(), tools, ranked(tools), counter, larger)


@pytest.mark.parametrize("question", ['{"grams":100,"grams":200}', '{"grams":NaN}', '{"grams":Infinity}'])
def test_invalid_json_food_arguments_are_not_interpreted(question):
    requests, mode = api._food_requests(question)
    assert mode == "description_only_no_quantity_inference"
    assert requests == [{"search_text": question}]


def test_explicit_prescription_does_not_trigger_drill_selection(counter):
    p = prepared(8)
    p["public_input"]["athlete_request"] = "Give me an exact daily calorie target and exact meal portions."
    p["model_visible_json"] = api._json(p["public_input"])
    p["audit"]["public_input_sha256"] = api._sha(p["model_visible_json"].encode())
    tools = ReplayTools(8)
    packet, _ = api.build_packet(p, tools, ranked(tools), counter, policy())
    assert packet["payload"]["catalog_selection"]["status"] == "not_requested"
    assert not tools.calls


def test_one_person_cannot_be_matched_to_five_player_drill():
    row = api.load_approved_catalog(ROOT)["records"]["JR-NEW-0013"]
    constraints = api._conditions(prepared(11)["public_input"], row)
    assert any("roles" in x for x in constraints["known_conflicts"])


def test_public_drill_lookup_may_not_drop_qualification(counter):
    tools = ReplayTools()
    original = tools.get_drill
    def altered(identifier):
        result = original(identifier)
        del result["data"]["use_conditions"]
        return result
    tools.get_drill = altered
    with pytest.raises(ValueError, match="complete approved variant"):
        api.build_packet(prepared(), tools, ranked(tools), counter, policy())


pytestmark = pytest.mark.requirement("31:reviewed-drill-context")
