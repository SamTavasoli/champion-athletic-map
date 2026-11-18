"""Check source-neutral positive proofs, contradictions and retained unknowns."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / "src/champion_athletic_map/independent_resources.py"
spec = importlib.util.spec_from_file_location("independent_resources_test", SOURCE)
API = importlib.util.module_from_spec(spec)
spec.loader.exec_module(API)
CONTRACT_FILE = PROJECT / "artifacts/evaluation/independent_assessment/reviewed_resource_contracts.json"

STATIONARY = "One player stays in place on a basketball court, dribbles low with one hand while looking up, then changes hands, and repeats at middle height."
SHARING = STATIONARY.rstrip(".") + ". Players take turns sharing one basketball; one player is active at a time and the others wait outside the practice area."
FORM = "Partners take turns shooting and rebounding within a few feet of the hoop. The shooter uses one hand and follows through. One pair is active at a time and shares one basketball."
WINDOWS = "Windows defensive slide drill: Place two cones 6-8 feet apart in clear court space. One defender slides laterally between the markers to stop a ball rolled by a stationary partner. They stop before switching roles; one pair is active at a time and shares one basketball; other players wait outside the practice area."


@pytest.fixture
def bundle(tmp_path):
    raw = json.loads(CONTRACT_FILE.read_bytes())
    for relative in raw["source_file_sha256"]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / relative, path)
    path = tmp_path / "reviewed_contracts.json"
    path.write_bytes(CONTRACT_FILE.read_bytes())
    return API.load_contracts(tmp_path, "reviewed_contracts.json"), tmp_path


def public():
    return {"equipment": [{"name": "Basketball", "quantity": 1}, {"name": "Cones", "quantity": 4}, {"name": "Hoop", "quantity": 1}],
        "participants_available": 4, "space": {"court_access": "full_court", "hoop_access": True,
            "restrictions": [], "usable_area_description": "A clear full basketball court is available."}}


def activity(description=STATIONARY, participants=1, space="full_court", equipment=None):
    return {"activity_id": "a", "description": description, "resources": {"equipment": equipment if equipment is not None else [{"name": "Basketball", "quantity": 1}],
        "participants": participants, "space": space}}


def assess(bundle, item=None, supplied=None):
    return API.assess_resources(supplied if supplied is not None else public(), [item if item is not None else activity()], bundle[0])


def statuses(result):
    return {row["check_id"]: row["status"] for row in result["checks"]}


def test_source_release_and_record_bindings_are_verified(bundle):
    contracts, _ = bundle
    assert contracts["source_bindings_verified"] and len(contracts["contracts"]) == 3
    assert all(row["source_structured_minimum_participants"] is None for row in contracts["contracts"])
    assert all(row["minimum_participants_basis"].startswith("New project interpretation") for row in contracts["contracts"])


@pytest.mark.parametrize("description,people,equipment", [(STATIONARY, 1, [{"name": "ball", "quantity": 1}]),
    (SHARING, 4, [{"name": "ball", "quantity": 1}]), (FORM, 2, [{"name": "ball", "quantity": 1}]),
    (WINDOWS, 4, [{"name": "ball", "quantity": 1}, {"name": "markers", "quantity": 2}])])
def test_concrete_base_actions_can_pass_without_any_catalog_id(bundle, description, people, equipment):
    item = activity(description, people, equipment=equipment)
    assert "evidence_refs" not in item
    result = assess(bundle, item)
    assert statuses(result) == {"declared_resource_consistency": "met", "resource_requirements_evidence": "met"}, result
    assert result["per_activity"][0]["contract_id"]
    assert result["coverage"]["catalog_ids_required"] is False
    assert result["coverage"]["clinical_safety_certified"] is False


def test_literal_quantity_fit_is_distinct_from_vague_requirement_evidence(bundle):
    result = assess(bundle, activity("Basketball session to work on changes of direction", 2,
        equipment=[{"name": "Basketball", "quantity": 1}, {"name": "Cones", "quantity": 4}]))
    assert statuses(result) == {"declared_resource_consistency": "met", "resource_requirements_evidence": "unknown"}


def test_name_and_catalog_id_alone_never_supply_action_role_proof(bundle):
    item = activity("Stationary Dribble Low/Middle")
    item["evidence_refs"] = ["JR-REVIEW-0062"]
    assert statuses(assess(bundle, item))["resource_requirements_evidence"] == "unknown"


@pytest.mark.parametrize("tail", [" Then sprint across the court.", " Do not change hands.", " Then add a weighted vest."])
def test_unreviewed_additions_and_negations_do_not_pass_keyword_matching(bundle, tail):
    assert statuses(assess(bundle, activity(STATIONARY + tail)))["resource_requirements_evidence"] == "unknown"


@pytest.mark.parametrize("change", ["unknown_ball", "no_ball", "unknown_people", "one_for_pair", "unknown_space", "restrictions"])
def test_missing_or_conflicting_material_facts_do_not_pass(bundle, change):
    item, supplied = activity(FORM, 2), public()
    if change == "unknown_ball":
        supplied["equipment"][0]["quantity"] = None
    elif change == "no_ball":
        supplied["equipment"] = []
    elif change == "unknown_people":
        supplied["participants_available"] = None
    elif change == "one_for_pair":
        supplied["participants_available"] = 1
    elif change == "unknown_space":
        supplied["space"]["court_access"] = None
    else:
        supplied["space"]["restrictions"] = ["Only one participant may move at a time."]
    expected = "violated" if change in ("no_ball", "one_for_pair") else "unknown"
    assert statuses(assess(bundle, item, supplied))["resource_requirements_evidence"] == expected


def test_incomplete_declared_equipment_is_not_a_positive_proof(bundle):
    item = activity()
    item["resources"]["equipment"] = None
    result = assess(bundle, item)
    assert statuses(result)["declared_resource_consistency"] == "unknown"
    assert statuses(result)["resource_requirements_evidence"] == "unknown"


def test_understated_required_ball_or_pair_roles_are_caught_independently(bundle):
    item = activity(FORM, 1, equipment=[])
    assert statuses(assess(bundle, item))["resource_requirements_evidence"] == "violated"


def test_turn_taking_does_not_require_a_ball_for_every_available_person(bundle):
    assert statuses(assess(bundle, activity(SHARING, 4)))["resource_requirements_evidence"] == "met"
    assert statuses(assess(bundle, activity(STATIONARY, 4)))["resource_requirements_evidence"] == "unknown"


def test_a_held_catalog_reference_cannot_supply_eligible_resource_proof(bundle):
    item = activity()
    item["evidence_refs"] = [bundle[0]["held_catalog_ids"][0]]
    result = assess(bundle, item)
    assert statuses(result)["resource_requirements_evidence"] == "unknown"
    assert result["per_activity"][0]["eligibility_status"] == "violated"


def test_no_court_adaptation_is_unknown_not_a_false_physical_impossibility(bundle):
    supplied, item = public(), activity(space="clear practice area")
    supplied["space"] = {"court_access": "none", "hoop_access": False, "restrictions": [],
        "usable_area_description": "A clear 6 m by 4 m rectangle is available."}
    assert statuses(assess(bundle, item, supplied))["resource_requirements_evidence"] == "unknown"


def test_shortage_of_markers_and_hoop_unavailability_are_actionable(bundle):
    supplied = public()
    supplied["equipment"][1]["quantity"] = 1
    windows = activity(WINDOWS, 2, equipment=[{"name": "ball", "quantity": 1}, {"name": "cones", "quantity": 2}])
    assert statuses(assess(bundle, windows, supplied))["resource_requirements_evidence"] == "violated"
    supplied = public()
    supplied["space"]["hoop_access"] = False
    assert statuses(assess(bundle, activity(FORM, 2), supplied))["resource_requirements_evidence"] == "violated"


def test_empty_activities_are_resource_inapplicable_not_an_overall_plan_pass(bundle):
    result = API.assess_resources(public(), [], bundle[0])
    assert set(statuses(result).values()) == {"not_applicable"}
    assert result["coverage"]["universal_free_text_resource_verification"] is False
    assert not result["per_activity"]


@pytest.mark.parametrize("change", ["source", "record"])
def test_changed_source_or_contract_record_hash_is_rejected(bundle, change):
    _, root = bundle
    if change == "source":
        path = root / "artifacts/language_model/active_resource_release.json"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        path = root / "reviewed_contracts.json"
        value = json.loads(path.read_bytes())
        value["contracts"][0]["source_record_sha256"] = "0" * 64
        path.write_bytes(API.canonical(value))
    with pytest.raises(ValueError):
        API.load_contracts(root, "reviewed_contracts.json")


def test_resource_assessment_does_not_mutate_inputs_or_contracts(bundle):
    supplied, item, contracts = public(), activity(), bundle[0]
    before = deepcopy((supplied, item, contracts))
    API.assess_resources(supplied, [item], contracts)
    assert (supplied, item, contracts) == before


@pytest.mark.parametrize("field,value", [("equipment", None), ("participants_available", None), ("space", None)])
def test_missing_public_resource_groups_remain_unknown(bundle, field, value):
    supplied = public()
    supplied[field] = value
    assert statuses(assess(bundle, supplied=supplied))["resource_requirements_evidence"] == "unknown"


def test_zero_is_a_known_shortage_while_null_remains_unknown(bundle):
    supplied = public()
    supplied["equipment"][0]["quantity"] = 0
    assert statuses(assess(bundle, supplied=supplied))["resource_requirements_evidence"] == "violated"
    supplied["equipment"][0]["quantity"] = None
    assert statuses(assess(bundle, supplied=supplied))["resource_requirements_evidence"] == "unknown"
    supplied = public()
    supplied["participants_available"] = 0
    assert statuses(assess(bundle, supplied=supplied))["resource_requirements_evidence"] == "violated"


@pytest.mark.parametrize("bad", [None, [], ["not a resource object"]])
def test_malformed_activity_resources_do_not_crash_or_pass(bundle, bad):
    item = activity()
    item["resources"] = bad
    assert statuses(assess(bundle, item))["resource_requirements_evidence"] == "unknown"


pytestmark = pytest.mark.requirement("31:independent-resource-proof")

