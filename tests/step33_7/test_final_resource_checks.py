"""Exercise the common resource boundary with fictional software fixtures."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from champion_athletic_map import final_resource_checks as final
from champion_athletic_map import independent_resources as base


@pytest.fixture
def setup():
    record = {"catalog_candidate_id": "JR-SOFTWARE-0001",
        "approval_decision": "approved_for_prototype", "instructions": "Fictional software example."}
    adopted = {"records": [record], "aliases": {"JR-SOFTWARE-ALIAS": "JR-SOFTWARE-0001"}}
    contracts = {"schema_version": "reviewed-resource-contracts-1", "source_bindings_verified": True,
        "declared_contract_count": 1, "resource_release_id": "software-fixture-only",
        "held_catalog_ids": ["JR-SOFTWARE-HELD"],
        "contracts": [{"contract_id": "software-action-proof", "source_catalog_id": record["catalog_candidate_id"],
            "source_record_sha256": final._digest(record), "description_patterns": [r"one athlete dribbles on a basketball court"],
            "minimum_equipment": {"basketball": 1}, "minimum_participants": 1, "positive_space_context": "court"}]}
    public = {"equipment": [{"name": "basketball", "quantity": 1}], "participants_available": 1,
        "space": {"court_access": "full_court", "hoop_access": True,
            "usable_area_description": "A clear court.", "restrictions": []}}
    activity = {"activity_id": "software-activity", "description": "One athlete dribbles on a basketball court.",
        "resources": {"equipment": [{"name": "basketball", "quantity": 1}], "participants": 1, "space": "court"},
        "evidence_refs": []}
    return public, [activity], contracts, adopted


def assess(setup, checker=base):
    public, activities, contracts, adopted = setup
    return final.assess_resources(public, activities, contracts, checker=checker, adopted_drills=adopted)


def statuses(report):
    return {row["check_id"]: row["status"] for row in report["checks"]}


def test_complete_source_neutral_recipe_needs_no_id(setup):
    report = assess(setup)
    assert set(statuses(report).values()) == {"met"}
    assert report["source_reference_resolution"] == []
    assert report["coverage"]["catalog_id_required"] is False


def test_source_id_alone_never_certifies_generic_action(setup):
    setup[1][0].update(description="Basketball practice", evidence_refs=["JR-SOFTWARE-0001"])
    report = assess(setup)
    assert statuses(report)["resource_requirements_evidence"] == "unknown"
    assert report["source_reference_resolution"][0]["resolution_status"] == "resolved_to_approved_record"
    assert report["source_reference_resolution"][0]["claim_support_assessed"] is False


def test_unrecognized_description_is_unknown_even_without_id(setup):
    setup[1][0]["description"] = "Practice turns and changes of direction."
    assert statuses(assess(setup))["resource_requirements_evidence"] == "unknown"


def test_known_supply_violation_is_not_hidden_by_unrecognized_prose(setup):
    setup[0]["equipment"][0]["quantity"] = 0
    setup[1][0]["description"] = "A different practice activity."
    assert statuses(assess(setup)) == {"declared_resource_consistency": "violated", "resource_requirements_evidence": "unknown"}


def test_narrative_restriction_is_not_silently_approved(setup):
    setup[0]["space"]["restrictions"] = ["One half of the area is occupied."]
    assert set(statuses(assess(setup)).values()) == {"unknown"}


def test_empty_activity_set_has_no_resource_denominator(setup):
    setup[1].clear()
    report = assess(setup)
    assert set(statuses(report).values()) == {"not_applicable"}
    assert report["coverage"]["activity_status_counts"]["requirements_status"]["determinate_coverage"] is None


def test_source_resolution_aliases_are_diagnostic_only(setup):
    setup[1][0].update(description="Unknown practice.", evidence_refs=["JR-SOFTWARE-ALIAS", "JR-NOT-REGISTERED", "https://example.invalid/"])
    report = assess(setup)
    assert [row["resolution_status"] for row in report["source_reference_resolution"]] == [
        "resolved_to_approved_record", "unresolved_catalog_reference", "non_catalog_reference_not_resolved_here"]
    assert statuses(report)["resource_requirements_evidence"] == "unknown"


def test_mutated_approved_record_is_rejected(setup):
    setup[3]["records"][0]["instructions"] = "Changed source."
    with pytest.raises(ValueError, match="differs from its approved source"):
        assess(setup)


def test_unverified_contract_input_is_rejected(setup):
    setup[2]["source_bindings_verified"] = False
    with pytest.raises(ValueError, match="Verified resource contracts"):
        assess(setup)


def test_positive_proof_without_source_binding_is_rejected(setup):
    report = base.assess_resources(setup[0], setup[1], setup[2])
    report["per_activity"][0]["contract_id"] = "unbound-positive-proof"
    fake = SimpleNamespace(assess_resources=lambda *args: deepcopy(report))
    with pytest.raises(ValueError, match="no verified source proof"):
        assess(setup, checker=fake)


def test_coverage_counts_unknowns_without_turning_them_into_passes(setup):
    unknown = deepcopy(setup[1][0]); unknown.update(activity_id="unknown-activity", description="Unrecognized activity.")
    setup[1].append(unknown)
    report = assess(setup)
    counts = report["coverage"]["activity_status_counts"]["requirements_status"]
    assert counts["met"] == counts["unknown"] == 1
    assert counts["determinate_coverage"] == 0.5
    assert counts["assessable_activity_denominator"] == 2
    assert statuses(report)["resource_requirements_evidence"] == "unknown"


def test_checker_missing_activity_coverage_is_execution_error(setup):
    report = base.assess_resources(setup[0], setup[1], setup[2]); report["per_activity"] = []
    fake = SimpleNamespace(assess_resources=lambda *args: deepcopy(report))
    with pytest.raises(ValueError, match="incomplete or duplicate coverage"):
        assess(setup, checker=fake)


def test_reordered_scope_results_rejoin_the_original_activity_instances(setup):
    second = deepcopy(setup[1][0]); second["activity_id"] = "second-activity"
    setup[1].append(second)
    report = base.assess_resources(setup[0], setup[1], setup[2])
    first, second = report["per_activity"]
    first.update(requirements_status="unknown", resource_scope="existing_linked_or_unresolved")
    report["per_activity"] = [second, first]
    for index, row in enumerate(report["per_activity"]):
        row["activity_index"] = index
    fake = SimpleNamespace(assess_resources=lambda *args: deepcopy(report))
    result = assess(setup, checker=fake)
    assert [row["activity_id"] for row in result["per_activity"]] == ["software-activity", "second-activity"]
    assert [row["activity_index"] for row in result["per_activity"]] == [0, 1]
    assert [row["original_checker_activity_index"] for row in result["per_activity"]] == [1, 0]
    assert result["per_activity"][0]["requirements_status"] == "unknown"
    assert result["coverage"]["activity_index_binding"] == "unique_activity_id"


@pytest.mark.parametrize("identifier", [None, "software-activity"])
def test_missing_or_duplicate_ids_never_imply_an_activity_instance_join(setup, identifier):
    second = deepcopy(setup[1][0]); second["activity_id"] = identifier
    setup[1].append(second)
    result = assess(setup)
    assert set(statuses(result).values()) == {"unknown"}
    assert all(row["activity_index"] is None for row in result["per_activity"])
    assert all(row["requirements_status"] == "unknown" for row in result["per_activity"])
    assert result["coverage"]["activity_index_binding"] == "unresolved_missing_or_duplicate_activity_ids"


def test_ambiguous_ids_do_not_erase_a_known_supply_violation(setup):
    second = deepcopy(setup[1][0]); setup[1].append(second)
    setup[0]["equipment"][0]["quantity"] = 0
    result = assess(setup)
    assert set(statuses(result).values()) == {"violated"}
    assert all(row["activity_index"] is None for row in result["per_activity"])
