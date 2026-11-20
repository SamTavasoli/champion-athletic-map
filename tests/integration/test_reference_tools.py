"""Check reference delivery and food arithmetic using small authored records."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.requirement("30.6.reference_tools")
FIXTURE_VERSION = "step30-reference-fixtures-1"


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lookup = load("step30_reference_lookup", "src/champion_athletic_map/reference_tools.py")
context = load("step30_reference_context", "src/champion_athletic_map/reference_context.py")
packets = load("step30_reference_packets", "src/champion_athletic_map/reference_packets.py")
preparation = load("step30_reference_preparation", "src/champion_athletic_map/reference_preparation.py")


@pytest.fixture
def food_math():
    relative = lookup.FOOD + "/usda_food_reference.py"
    path = ROOT / relative
    if not path.is_file():
        pytest.fail("The versioned food arithmetic module is missing: " + relative)
    return load("step30_food_math", relative)


def food(identifier="1", name="Authored red fruit"):
    return {"fdc_id": identifier, "description": name, "source_data_type": "sr_legacy_food",
            "catalog_release": "2018-04", "source_record_url": "https://example.org/food/" + identifier}


def nutrient(identifier="1003", amount="8", unit="G", status="available"):
    return {"fdc_id": "1", "nutrient_id": identifier, "nutrient_name": "Authored nutrient",
            "numeric_status": status, "unit_name": unit, "source_food_nutrient_id": "111",
            "amount_per_100g_raw": amount, "reference_mass_g": "100", "reference_basis": "edible_food"}


def portion():
    # A complete record already describes TWO units weighing 300 g together.
    return {"fdc_id": "1", "portion_id": "11", "amount_raw": "2", "gram_weight_raw": "300",
            "measure_unit_id": "9", "unit_name": "piece", "modifier": "two pieces",
            "footnote": "", "household_numeric_screen_pass": True, "household_eligibility": "available"}


@pytest.fixture
def tools(food_math):
    service = lookup.ReferenceTools.__new__(lookup.ReferenceTools)
    service._food = food_math
    service._food_version = "authored-sr-legacy-2018-04"
    service._foods = {"1": food(), "2": food("2", "Authored green fruit")}
    service._nutrients = [nutrient(), nutrient("1004", "0"), nutrient("1005", "", status="missing")]
    service._portions = {"11": portion()}
    service._drill_ids = {"approved", "held", "alias"}
    service._exercise_ids = {"gym"}
    service._approved_drills = {"approved": {"catalog_candidate_id": "approved", "instructions": "Authored passing drill.",
        "source_url": "https://example.org/drill", "scope": "basketball_drill_candidate"}}
    service._drill_aliases = {"alias": "approved"}
    service._adopted_rules = []
    service._release_context, service._release_version = {}, "authored-release"
    service.bound = {lookup.DRILLS: "authored-drills", lookup.EXERCISES: "authored-exercises", lookup.RULES: "authored-rules"}
    return service


def test_food_gram_scaling_preserves_zero_missing_and_source_identity(tools):
    answer = tools.lookup_food(food_id="1", grams="150")
    assert answer["status"] == "found"
    facts = answer["data"]["nutrients"]
    assert answer["data"]["grams"] == "150"
    assert facts[0]["amount"] == "12"  # 8 g per 100 g, applied to 150 g.
    assert facts[1]["status"] == "available" and facts[1]["amount"] == "0"
    assert facts[2]["status"] == "unavailable" and facts[2]["amount"] is None
    assert answer["source_refs"] == ["https://example.org/food/1"]


def test_portion_record_amount_is_not_multiplied_twice(tools, food_math):
    answer = tools.lookup_food(food_id="1", portion_id="11", multiplier=2)
    assert answer["status"] == "found"
    assert answer["data"]["grams"] == "600"  # Two copies of the 300 g record.
    assert answer["data"]["nutrients"][0]["amount"] == "48"
    assert food_math.household_mass(food(), portion(), quantity=1, mode="same_defined_unit")["grams"] == "150"


@pytest.mark.parametrize("arguments", [
    {"food_id": "1", "grams": 0}, {"food_id": "1", "grams": -1},
    {"food_id": "1", "grams": float("nan")}, {"food_id": "1", "grams": float("inf")},
    {"food_id": True}, {"food_id": "1", "grams": 100, "portion_id": "11", "multiplier": 1},
    {"food_id": "1", "portion_id": "11"}, {"food_id": "1", "multiplier": 1},
    {"food_id": "1", "search_text": "fruit"},
])
def test_food_invalid_arguments_never_produce_facts(tools, arguments):
    answer = tools.lookup_food(**arguments)
    assert answer["status"] == "invalid_arguments" and answer["data"] is None


def test_ambiguous_food_name_does_not_choose_first_match(tools):
    answer = tools.lookup_food(search_text="fruit", grams=100)
    assert answer["status"] == "ambiguous"
    assert {row["food_id"] for row in answer["data"]["candidates"]} == {"1", "2"}
    assert "nutrients" not in answer["data"]
    assert tools.lookup_food(food_id="99")["status"] == "not_found"


@pytest.mark.parametrize("change, expected", [
    ({"unit_name": "MG"}, "unexpected_unit_or_unsupported_nutrient"),
    ({"reference_basis": "unknown"}, "unverified_reference_basis"),
    ({"reference_mass_g": "200"}, "unsupported_reference_mass"),
])
def test_food_unit_and_reference_qualifications_remain_unavailable(food_math, change, expected):
    record = {**nutrient(), **change}
    answer = food_math.food_fact(food(), record, grams=100)
    assert answer["status"] == "unavailable" and answer["reason"] == expected
    assert answer["amount"] is None


def test_household_footnotes_and_wrong_food_prevent_conversion(tools):
    tools._portions["11"]["footnote"] = "Unreviewed qualification"
    assert tools.lookup_food(food_id="1", portion_id="11", multiplier=1)["status"] == "invalid_arguments"
    tools._portions["11"] = {**portion(), "fdc_id": "2"}
    assert tools.lookup_food(food_id="1", portion_id="11", multiplier=1)["status"] == "invalid_arguments"


def test_pending_catalog_records_and_unadopted_rules_stay_unavailable(tools):
    assert tools.get_drill("held")["status"] == "not_eligible"
    assert tools.get_exercise("gym")["status"] == "not_eligible"
    assert tools.get_drill("unknown")["status"] == "not_found"
    assert tools.get_planning_rules(age=15, school_grade=10)["status"] == "unavailable"
    result = tools.get_drill("alias")
    assert result["data"]["canonical_drill_id"] == "approved"
    assert result["data"]["alias_resolved"] is True
    assert tools.catalog_availability()["validator_execution_ready"] is False


def public(food_question=None):
    value = {"age": 15, "school_grade": 10, "athlete_request": "Two passing sessions.", "goals": ["Passing"]}
    if food_question is not None:
        value["food_question"] = food_question
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"schema_version": "step24-prepared-public-input-1", "public_input": value,
            "model_visible_json": text, "audit": {"public_input_sha256": hashlib.sha256(text.encode()).hexdigest()}}


def tool_result(status="found", data=None, request_id="volatile-a"):
    return {"request_id": request_id, "elapsed_seconds": 99, "status": status, "data": data,
            "issues": [], "source_refs": ["authored-source"], "data_version": "authored-source-v1"}


def reference(identifier, text="Complete source, including its qualification.", links=None):
    return {"reference_unit_id": identifier, "passage_id": "passage-" + identifier,
            "complete_required_delivery_text": text, "linked_drill_ids": links or []}


class PacketTools:
    def __init__(self, request_id="volatile-a"):
        self.request_id, self.food_calls, self.catalog_calls = request_id, [], []

    def get_planning_rules(self, *args):
        return tool_result("unavailable", None, self.request_id)

    def complete_reference(self, row):
        return deepcopy(row)

    def lookup_food(self, **arguments):
        self.food_calls.append(arguments)
        return tool_result("found", {"food_id": "1", "grams": "100", "recorded": "authored"}, self.request_id)

    def get_drill(self, identifier):
        self.catalog_calls.append(identifier)
        canonical = "canonical-alias" if identifier.startswith("alias") else identifier
        return tool_result("found", {"canonical_drill_id": canonical, "instructions": "Complete authored instructions."}, self.request_id)

    get_exercise = get_drill


POLICY = {"policy_version": "authored-reference-policy-1", "source_configuration_sha256": "a" * 64,
          "max_packet_tokens": 100000, "max_rule_bundles": 2}


def test_two_rankings_merge_round_robin_with_stable_deduplication():
    left = [reference("a"), reference("b"), reference("c")]
    right = [reference("c"), reference("a"), reference("d")]
    assert [row["reference_unit_id"] for row in context.merge_results([left, right])] == ["a", "c", "b", "d"]


def test_whole_references_share_one_budget_and_omissions_are_recorded():
    rows = [[reference("small"), reference("large", "Qualification. " * 1000)], []]
    packet, trace = context.build_packet(public(), PacketTools(), rows, len, {**POLICY, "max_packet_tokens": 1000})
    assert packet["preparation"]["selected_reference_ids"] == ["small"]
    assert packet["payload"]["references"][0]["complete_required_delivery_text"] == rows[0][0]["complete_required_delivery_text"]
    assert packet["preparation"]["packet_text_tokens"] <= 1000
    assert {row["id"] for row in trace["omissions"] if row["kind"] == "reference"} == {"large"}


def test_matched_versions_share_reference_content_and_baseline_has_none():
    prepared = public()
    packet, _ = context.build_packet(prepared, PacketTools(), [[reference("a")], []], len, POLICY)
    views = [packets.model_input_for_version(prepared, version, packet) for version in (2, 3, 4)]
    assert views[0] == views[1] == views[2]
    assert packets.model_input_for_version(prepared, 1) == {"athlete_input": prepared["public_input"]}
    with pytest.raises(ValueError, match="cannot receive"):
        packets.model_input_for_version(prepared, 1, packet)
    changed = deepcopy(packet)
    changed["payload"]["references"][0]["complete_required_delivery_text"] = "Changed source"
    with pytest.raises(ValueError, match="changed"):
        packets.model_input_for_version(prepared, 2, changed)


def test_packet_hash_excludes_volatile_tool_metadata():
    prepared = public('{"food_id":"1","grams":100}')
    first, _ = context.build_packet(prepared, PacketTools("request-a"), [[reference("a")], []], len, POLICY)
    second, _ = context.build_packet(prepared, PacketTools("request-b"), [[reference("a")], []], len, POLICY)
    assert first["packet_id"] == second["packet_id"]
    assert "request_id" not in json.dumps(first)


def test_food_and_catalog_limits_keep_complete_records_and_explicit_omissions():
    question = json.dumps([{"food_id": str(i), "grams": 100} for i in (1, 2, 3)])
    service = PacketTools()
    packet, trace = context.build_packet(public(question), service,
        [[reference("a", links=["d" + str(i) for i in range(12)])], []], len, POLICY)
    assert len(service.food_calls) == 2
    assert len(service.catalog_calls) == 10
    assert len(packet["payload"]["food_lookup"]) == 2
    assert any(row["kind"] == "food" and row["position"] == 2 for row in trace["omissions"])
    assert sum(row.get("reason") == "ten_lookup_limit" for row in trace["omissions"]) == 2


def test_catalog_aliases_share_one_canonical_record_but_calls_are_counted():
    service = PacketTools()
    packet, trace = context.build_packet(public(), service, [[reference("a", links=["alias-a", "alias-b"])], []], len, POLICY)
    assert len(packet["payload"]["catalog_records"]) == 1
    assert trace["tool_calls"]["catalog"] == 2


def test_reference_execution_error_is_distinct_from_missing_evidence():
    with pytest.raises(RuntimeError, match="preparation failed"):
        context._tool(tool_result("execution_error", None))
    assert context._tool(tool_result("not_found", None))["status"] == "not_found"


def test_oversized_required_food_context_is_not_silently_removed():
    with pytest.raises(ValueError, match="food context exceeds"):
        context.build_packet(public('{"food_id":"1"}'), PacketTools(), [[], []], len,
                             {**POLICY, "max_packet_tokens": 10})
