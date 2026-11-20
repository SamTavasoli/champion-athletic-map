"""We check construction boundaries with fictional public cases and inert objects."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from champion_athletic_map import final_runtime_setup as final
from champion_athletic_map import final_request_checks as requests


def seal(contracts):
    result = deepcopy(contracts)
    result.pop("contracts_id", None)
    result["contracts_id"] = final.sha(final.packed(result))
    return result


@pytest.fixture
def case_data():
    note = {"type": "object", "properties": {"note": {"type": "string"}}}
    evaluator = {"type": "object", "properties": {"assessment_complete": {"type": "boolean"}}}
    records, bundles, bindings = [], {}, []
    for index in range(200):
        public = {"age": 15, "athlete_request": "Arrange 2 extra practice blocks.",
            "planning_window": {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"},
            "availability": [{"date": "2026-11-16", "start_time": "17:00", "end_time": "17:30"}],
            "existing_commitments": [], "space": {"court_access": "full_court", "hoop_access": True},
            "participants_available": 1, "time_limits": {"max_additional_sessions_per_week": 3}}
        food = index == 0
        if food:
            public["food_question"] = "A fictional food question for software checks."
        record = {"profile_id": "software-runtime-case-" + str(index), "schema_version": "athlete-profile-input-2", "input": public}
        local = {"type": "object", "properties": {"response_type": {"type": "string"}}, "food_present": food}
        native = {"type": "object", "properties": {"response_type": {"type": "string"}, "explanation": {"type": "string"}}, "food_present": food}
        food_note = {**deepcopy(note), "food_present": food}
        text = final.wire(native)
        bundle = {"local_response_schema": local, "native_response_schema": native,
            "native_schema_ordered_wire_json": text, "native_schema_ordered_wire_sha256": final.sha(text.encode()),
            "food_note_schema": food_note, "food_note_native_schema_ordered_wire_json": final.wire(food_note)}
        identifier = final.sha(final.canonical(bundle))
        bundles[identifier] = bundle
        bindings.append({"profile_id": record["profile_id"],
            "public_record_canonical_sha256": final.sha(final.canonical(record)),
            "public_input_canonical_sha256": final.sha(final.canonical(public)),
            "contract_bundle_id": identifier,
            "local_response_schema_sha256": final.sha(final.canonical(local)),
            "native_response_schema_sha256": final.sha(final.canonical(native)),
            "native_schema_ordered_wire_sha256": final.sha(text.encode())})
        records.append(record)
    contracts = seal({"case_bindings": bindings, "contract_bundles": bundles,
        "base_specialist_note_schema": note, "base_specialist_note_native_schema_ordered_wire_json": final.wire(note),
        "evaluator_schema": evaluator, "evaluator_native_schema_ordered_wire_json": final.wire(evaluator)})
    return records, contracts


def checker():
    namespace = {"_request_facts": lambda public: {"essential_missing": [], "conflict": None,
        "outside_scope": False, "only_existing": False},
        "_basis": lambda public, response: ("unknown", "Original literal basis.", False, {})}
    exec("def check(self):\n    return _request_facts, _basis\n", namespace)
    kind = type("SoftwareChecker", (), {"check": namespace["check"]})
    return kind()


def fake_runtime(record, contracts):
    binding = next(row for row in contracts["case_bindings"] if row["profile_id"] == record["profile_id"])
    bundle = contracts["contract_bundles"][binding["contract_bundle_id"]]
    policy = {"source_configuration_sha256": "software-only"}
    class Public:
        def prepare_public_input(self, supplied, _schema):
            if supplied != record:
                raise ValueError("Another fictional case was supplied.")
            return {"public_input": deepcopy(supplied["input"])}
    clients = [SimpleNamespace(public=Public(), input_schema={"type": "object"},
        response_schema=deepcopy(bundle["local_response_schema"]),
        output_schema=deepcopy(bundle["native_response_schema"])) for _ in range(4)]
    shared = SimpleNamespace(_schema_order=lambda value: deepcopy(value), _generation_schema=lambda value: deepcopy(value))
    def role(client):
        return SimpleNamespace(client=client, shared=shared, reference_policy=deepcopy(policy),
            _food_arguments=lambda args, kwargs: (args, {**kwargs, "output_schema": deepcopy(bundle["food_note_schema"])}))
    def node(client, with_role=False):
        value = SimpleNamespace(client=client, instructions="Shared fictional setup instructions.",
            config={"reference_policy": deepcopy(policy)})
        if with_role:
            value.roles = role(client)
        return value
    planners = {1: node(clients[0]), 2: node(clients[1]), 3: node(clients[2], True)}
    planners[3].note_schema = deepcopy(contracts["base_specialist_note_schema"])
    drafting, engine = node(clients[3], True), node(clients[3], True)
    drafting.note_schema = deepcopy(contracts["base_specialist_note_schema"])
    engine.drafting = drafting
    engine.evaluator_schema = deepcopy(contracts["evaluator_schema"])
    engine.checker = checker(); engine.checker.client = clients[3]
    kind = type("CandidateFocusedEvaluatedPlanner", (), {})
    outer = kind(); outer.__dict__.update(node(clients[3]).__dict__); outer.planner = engine
    planners[4] = outer
    roles = [{"label": label, "target": item.roles} for label, item in
        (("v3.roles", planners[3]), ("v4.evaluated.roles", engine), ("v4.drafting.roles", drafting))]
    return SimpleNamespace(planners=planners, clients=[{"target": client} for client in clients],
        roles=roles, checker=engine.checker, reference_policy=policy,
        tools=SimpleNamespace(core=SimpleNamespace(_query_runtime=None)), client=clients[1],
        manifest={"runtime_version": "software-base", "effective_reference_policy": deepcopy(policy),
            "model_calls_during_construction": 0, "query_encoding_during_construction": 0,
            "constructor_test_doubles": False})


def test_all_public_case_bindings_are_checked(case_data):
    records, contracts = case_data
    assert len(final.validate_case_bindings(records, contracts)) == 200


def test_changed_public_case_cannot_reuse_its_contract(case_data):
    records, contracts = case_data
    records[7]["input"]["age"] = 16
    with pytest.raises(ValueError, match="public version"):
        final.validate_case_bindings(records, contracts)


def test_private_annotations_are_not_runtime_arguments(case_data):
    records, contracts = case_data
    records[0]["expected_response_type"] = "plan"
    with pytest.raises(ValueError, match="public case wrappers"):
        final.validate_case_bindings(records, contracts)


def test_changed_local_schema_is_rejected(case_data):
    records, contracts = case_data
    next(iter(contracts["contract_bundles"].values()))["local_response_schema"]["type"] = "array"
    with pytest.raises(ValueError, match="schema differs"):
        final.validate_case_bindings(records, seal(contracts))


def test_schema_wire_text_is_part_of_the_case_binding(case_data):
    records, contracts = case_data
    next(iter(contracts["contract_bundles"].values()))["native_schema_ordered_wire_json"] += " "
    with pytest.raises(ValueError):
        final.validate_case_bindings(records, seal(contracts))


def test_graph_requires_four_distinct_clients_and_all_trace_targets(case_data):
    records, contracts = case_data
    runtime = fake_runtime(records[0], contracts)
    binding = contracts["case_bindings"][0]
    bundle = contracts["contract_bundles"][binding["contract_bundle_id"]]
    assert final.inspect_graph(runtime, records[0], bundle, contracts, {"type": "object"})["distinct_clients_verified"] == 4
    runtime.clients.pop()
    with pytest.raises(ValueError, match="tracing inventory"):
        final.inspect_graph(runtime, records[0], bundle, contracts, {"type": "object"})


def test_graph_rejects_another_v4_class(case_data):
    records, contracts = case_data
    runtime = fake_runtime(records[0], contracts)
    runtime.planners[4] = SimpleNamespace(**runtime.planners[4].__dict__)
    bundle = contracts["contract_bundles"][contracts["case_bindings"][0]["contract_bundle_id"]]
    with pytest.raises(ValueError, match="candidate-focused"):
        final.inspect_graph(runtime, records[0], bundle, contracts, {"type": "object"})


def test_graph_rejects_changed_food_note_binding(case_data):
    records, contracts = case_data
    runtime = fake_runtime(records[0], contracts)
    runtime.planners[3].roles._food_arguments = lambda args, kwargs: (args, {**kwargs, "output_schema": {"type": "array"}})
    bundle = contracts["contract_bundles"][contracts["case_bindings"][0]["contract_bundle_id"]]
    with pytest.raises(ValueError, match="conditional food"):
        final.inspect_graph(runtime, records[0], bundle, contracts, {"type": "object"})


def test_equivalent_schema_order_is_restored_from_frozen_wire(case_data):
    records, contracts = case_data
    runtime = fake_runtime(records[0], contracts)
    for row in runtime.clients:
        row["target"].output_schema = dict(reversed(list(row["target"].output_schema.items())))
    bundle = contracts["contract_bundles"][contracts["case_bindings"][0]["contract_bundle_id"]]
    report = final.inspect_graph(runtime, records[0], bundle, contracts, {"type": "object"})
    assert report["native_schema_order_restored_from_frozen_wire"] is True
    assert all(final.wire(row["target"].output_schema) == bundle["native_schema_ordered_wire_json"] for row in runtime.clients)


def test_reference_query_loading_cannot_be_hidden_by_construction_receipt(case_data):
    records, contracts = case_data
    runtime = fake_runtime(records[0], contracts)
    runtime.tools.core._query_runtime = object()
    bundle = contracts["contract_bundles"][contracts["case_bindings"][0]["contract_bundle_id"]]
    with pytest.raises(ValueError, match="query runtime"):
        final.inspect_graph(runtime, records[0], bundle, contracts, {"type": "object"})


def test_constructor_network_attempt_cannot_be_swallowed():
    import socket
    with pytest.raises(ValueError, match="attempted network"):
        with final.without_network():
            try:
                socket.create_connection(("example.invalid", 443))
            except RuntimeError:
                pass


def test_internal_count_parser_uses_public_blocks_not_private_labels():
    value = checker()
    final.patch_public_checker(value, requests)
    facts, _basis = value.check()
    assert facts({"athlete_request": "Arrange 2 extra practice blocks.", "availability": [], "existing_commitments": []})["requested_sessions"] == 2


def test_internal_distinct_date_conflict_has_exact_public_basis():
    value = checker(); final.patch_public_checker(value, requests)
    _facts, basis = value.check()
    public = {"athlete_request": "Place an additional 20-minute basketball block on 3 distinct dates.",
        "availability": [{"date": "2026-11-16", "start_time": "17:00", "end_time": "17:30"},
                         {"date": "2026-11-18", "start_time": "17:00", "end_time": "17:30"}],
        "existing_commitments": [], "planning_window": {"start_date": "2026-11-16", "end_date": "2026-11-22"}}
    status, _reason, supported, _facts = basis(public, {"response_type": "constraint_conflict",
        "explanation": "You request 3 distinct dates but only 2 dates are available."})
    assert status == "met" and supported is True
    assert basis(public, {"response_type": "constraint_conflict", "explanation": "There is some problem."})[0] == "unknown"


def test_internal_missing_court_requires_relevant_clarification():
    value = checker(); final.patch_public_checker(value, requests)
    _facts, basis = value.check()
    public = {"athlete_request": "Give me specific shooting locations for basketball shooting this week.",
        "availability": [], "existing_commitments": [], "space": {"court_access": None, "hoop_access": None}}
    assert basis(public, {"response_type": "clarification", "questions": ["What court and hoop can you use?"]})[0] == "met"
    assert basis(public, {"response_type": "plan"})[0] == "violated"


def test_final_factory_records_the_public_checker_amendment(case_data):
    records, contracts = case_data
    root = Path(final.__file__).resolve().parents[2]
    runtime = final.build_runtime(root, {}, {"type": "object"}, public_record=records[0], case_contracts=contracts,
        runtime_builder=lambda *args, **kwargs: fake_runtime(kwargs["public_record"], contracts))
    assert runtime.manifest["runtime_version"] == final.VERSION
    assert runtime.manifest["constructor_test_doubles"] is True
    assert runtime.manifest["final_runtime_amendment"]["private_case_annotations_used"] is False
    assert runtime.manifest["final_runtime_amendment"]["output_or_context_limits_changed"] is False
    assert runtime.manifest["final_protocol_frozen"] is False
    assert runtime.checker.final_public_request_policy["version"] == requests.VERSION


def test_constructor_fixtures_cannot_establish_native_readiness(case_data):
    records, contracts = case_data
    root = Path(final.__file__).resolve().parents[2]
    with pytest.raises(ValueError, match="software constructor fixture"):
        final.verify_representative_graphs(root, {}, {"type": "object"}, records, contracts,
            runtime_builder=lambda *args, **kwargs: fake_runtime(kwargs["public_record"], contracts))


def test_representative_receipt_does_not_claim_all_case_budgets(case_data):
    records, contracts = case_data
    root = Path(final.__file__).resolve().parents[2]
    result = final.verify_representative_graphs(root, {}, {"type": "object"}, records, contracts,
        runtime_builder=lambda *args, **kwargs: fake_runtime(kwargs["public_record"], contracts), software_fixture=True)
    report = result["report"]
    assert report["frozen_public_bindings_verified"] == 200
    assert report["representative_runtime_graphs_verified"] == 2
    assert report["all_200_runtime_graphs_constructed"] is False
    assert report["actual_200_case_request_budgets_verified"] is False
    assert report["native_runtime_graphs_verified"] is False
    assert report["model_calls"] == report["reference_query_encodings"] == 0


def test_final_factory_rejects_private_arguments_before_building(case_data):
    records, contracts = case_data
    record = deepcopy(records[0]); record["private_expected_response"] = "plan"
    with pytest.raises(ValueError, match="public input only"):
        final.build_runtime(Path(final.__file__).resolve().parents[2], {}, {}, public_record=record,
            case_contracts=contracts, runtime_builder=lambda *args, **kwargs: pytest.fail("Constructor must not run."))
