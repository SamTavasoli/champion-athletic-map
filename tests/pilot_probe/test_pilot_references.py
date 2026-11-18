"""Verify fresh reference work, continuation and strict failure preservation."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest


PROJECT = Path(__file__).resolve().parents[2]
HERE = PROJECT / "src/champion_athletic_map"


def load(path, name):
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
    module.__spec__.loader.exec_module(module)
    return module


REF = load(HERE / "pilot_references.py", "fresh_references_test")
contracts = PROJECT / "artifacts/language_model/shared_contracts/contracts_3293242853ce2cf7"
PUBLIC = load(contracts / "public_input.py", "fresh_reference_public_test")
BASE_SCHEMA = json.loads((contracts / "public_profile_record_schema.json").read_bytes())
SCHEDULE = load(PROJECT / "src/champion_athletic_map/pilot_schedule.py", "fresh_reference_schema_test")


class FakeEncoder:
    def encode(self, text, *, parse_special):
        assert parse_special is False
        return list(range(len(text) // 8))


class FakeAPI:
    def __init__(self):
        self.encodes, self.ranks, self.failure = 0, 0, None

    def make_query_records(self, queries):
        return [{"query_id": "test-query:" + str(i), "text": text} for i, text in enumerate(queries)]

    def encode_queries(self, runtime, records, work):
        self.encodes += 1
        (work / "test_worker_started.json").write_text('{"fixture":true}')
        if self.failure == "encode":
            raise RuntimeError("Synthetic encoder failure after a retained worker artifact.")
        vectors = [[1, 0], [0, 1]]
        report = {"fixture": True, "mode": "synthetic_test_encoder", "rows": len(records)}
        (work / "test_vectors.json").write_text(json.dumps(vectors))
        return {"report": report, "vectors": vectors}

    def rank_queries(self, runtime, records, vectors, *, routes):
        assert routes == ("semantic",)
        self.ranks += 1
        return [{"query_id": row["query_id"] if self.failure != "identity" else "wrong",
            "route": "semantic", "result": {"status": "found", "results": [{
                "reference_unit_id": "ref:one", "passage_id": "passage:one",
                "complete_required_delivery_text": "Short synthetic reference for this software test."}]}}
            for row in records]


class FakeTools:
    def __init__(self):
        self.core = SimpleNamespace(_query_api=FakeAPI())
        self.source_bindings = {"fixture_source": "a" * 64}
        self.loads, self.rule_calls, self.food_calls = 0, 0, 0
        self.food_failure = False
        self.runtime = {"config": {"fixture": True}, "guard": lambda: True}

    def load_query_runtime(self):
        self.loads += 1
        return self.runtime

    def get_planning_rules(self, age, grade):
        self.rule_calls += 1
        return {"status": "found", "data": {"rules": []}, "issues": [], "source_refs": [], "data_version": "fixture"}

    def lookup_food(self, **kwargs):
        self.food_calls += 1
        if self.food_failure:
            raise RuntimeError("Synthetic food failure.")
        return {"status": "found", "data": {"food_id": "food:fixture", "amount": 3},
            "issues": [], "source_refs": ["fixture:food"], "data_version": "fixture"}

    def complete_reference(self, item):
        return deepcopy(item)


@pytest.fixture
def context(tmp_path):
    for name in ("reference_context", "reference_preparation"):
        target = tmp_path / "src/champion_athletic_map" / (name + ".py")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT / "src/champion_athletic_map" / (name + ".py"), target)
    schema = SCHEDULE.build_input_schema(BASE_SCHEMA)
    client = SimpleNamespace(public=PUBLIC, input_schema=schema, encoder=FakeEncoder())
    tools = FakeTools()
    policy = {"policy_version": "test-policy", "source_configuration_sha256": "a" * 64,
        "max_packet_tokens": 2200, "max_rule_bundles": 2}
    record = {"profile_id": "fixture:public", "schema_version": "athlete-profile-input-2", "input": {
        "planning_window": {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"},
        "athlete_request": "Plan two additional basketball sessions.", "age": 13,
        "schedule_coverage": {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles", "existing_commitments_complete": True},
        "existing_commitments": [], "equipment": [{"name": "Basketball", "quantity": 1}]}}
    preparer = REF.FreshReferencePreparer(tmp_path, tools, client, policy)
    return tmp_path, tools, client, policy, record, preparer


def prepare(context, version=2, **kwargs):
    root, _, _, _, record, preparer = context
    return preparer.prepare(record, root / "results/pilot/probe/references" / ("v" + str(version)),
        job_id="fixture_v" + str(version), configuration_id="fixture-probe-configuration", **kwargs)


def test_each_version_pays_for_fresh_encoding_and_receives_identical_packet(context):
    _, tools, _, _, _, preparer = context
    assert tools.loads == 1 and tools.core._query_api.encodes == 0
    assert preparer.setup_record["query_encoder_processes"] == 0
    first = prepare(context, 2)
    second = prepare(context, 3, expected_packet_id=first["packet"]["packet_id"])
    third = prepare(context, 4, expected_packet_id=first["packet"]["packet_id"])
    assert first["packet"] == second["packet"] == third["packet"]
    assert tools.core._query_api.encodes == tools.core._query_api.ranks == 3
    assert tools.rule_calls == 3
    assert all(not row["cache_reused"] and row["counts"]["query_encoder_processes"] == 1
        and row["counts"]["query_rows_encoded"] == 2 and row["counts"]["ranking_calls"] == 2
        and row["counts"]["rule_lookups"] == 1 for row in (first, second, third))
    assert len({row["reference_record_path"] for row in (first, second, third)}) == 3


def test_verified_continuation_reuses_original_work_and_elapsed_time(context):
    _, tools, _, _, _, _ = context
    first = prepare(context)
    second = prepare(context)
    assert second["cache_reused"] is True
    assert second["packet"] == first["packet"] and second["counts"] == first["counts"]
    assert second["preparation_seconds"] == first["preparation_seconds"]
    assert all(value == 0 for value in second["new_counts"].values())
    assert tools.core._query_api.encodes == 1


@pytest.mark.parametrize("artifact", ["packet.json", "trace.json", "test_vectors.json", "completed.json"])
def test_changed_saved_preparation_never_reencodes(context, artifact):
    root, tools, *_ = context
    first = prepare(context)
    path = root / first["reference_record_path"]
    path = path.parent / artifact
    path.write_bytes(path.read_bytes() + b" ")
    if artifact == "completed.json":
        # A whitespace-only edit is not semantic corruption; alter its binding instead.
        value = json.loads(path.read_bytes())
        value["request_sha256"] = "0" * 64
        path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        prepare(context)
    assert tools.core._query_api.encodes == 1


def test_changed_job_configuration_or_public_input_cannot_reuse_saved_packet(context):
    root, tools, _, _, record, preparer = context
    prepare(context)
    changed = deepcopy(record)
    changed["input"]["athlete_request"] = "A changed basketball request."
    work = root / "results/pilot/probe/references/v2"
    for supplied, config in ((changed, "fixture-probe-configuration"), (record, "different-configuration")):
        with pytest.raises(ValueError, match="does not match"):
            preparer.prepare(supplied, work, job_id="fixture_v2", configuration_id=config)
    assert tools.core._query_api.encodes == 1


@pytest.mark.parametrize("failure", ["encode", "identity"])
def test_failed_query_stage_keeps_artifacts_and_is_not_silently_rerun(context, failure):
    root, tools, *_ = context
    tools.core._query_api.failure = failure
    with pytest.raises(RuntimeError):
        prepare(context)
    work = root / "results/pilot/probe/references/v2"
    result = json.loads((work / "failure.json").read_bytes())
    assert (work / "request.json").is_file() and (work / "test_worker_started.json").is_file()
    assert result["model_generation_calls"] == 0 and result["encoder_api_invoked"] is True
    assert result["encoder_process_start_count_unverified"] == (failure == "encode")
    if failure == "identity":
        assert (work / "rankings.json").is_file()
        assert result["counts_confirmed"]["ranking_calls"] == 2
    with pytest.raises(RuntimeError, match="incomplete"):
        prepare(context)
    assert tools.core._query_api.encodes == 1


def test_partial_lookup_failure_retains_actual_invocation_counts_and_raw_results(context):
    root, tools, _, _, record, _ = context
    record["input"]["food_question"] = 'For the food "Strawberries, raw", how many grams of protein are recorded for 100 g?'
    tools.food_failure = True
    with pytest.raises(RuntimeError, match="food failure"):
        prepare(context)
    work = root / "results/pilot/probe/references/v2"
    failed = json.loads((work / "failure.json").read_bytes())
    assert failed["counts_confirmed"]["rule_lookups"] == 1
    assert failed["counts_confirmed"]["food_lookups"] == 1
    assert (work / "lookups/001_get_planning_rules.result.json").is_file()
    assert (work / "lookups/002_lookup_food.request.json").is_file()
    assert not (work / "lookups/002_lookup_food.result.json").exists()


def test_packet_mismatch_is_saved_before_any_generation_and_never_retried(context):
    root, tools, *_ = context
    with pytest.raises(ValueError, match="same canonical packet"):
        prepare(context, expected_packet_id="reference-packet:unexpected")
    assert (root / "results/pilot/probe/references/v2/failure.json").is_file()
    assert (root / "results/pilot/probe/references/v2/packet.json").is_file()
    assert (root / "results/pilot/probe/references/v2/builder_trace.json").is_file()
    assert tools.core._query_api.encodes == 1
    with pytest.raises(RuntimeError, match="incomplete"):
        prepare(context)


def test_private_or_outside_result_paths_are_rejected_before_any_encoding(context):
    root, tools, _, _, record, preparer = context
    for directory in (root / "artifacts/immutable", root.parent / "outside", root / "results/pilot"):
        with pytest.raises(ValueError, match="separate results/pilot"):
            preparer.prepare(record, directory, job_id="fixture_v2", configuration_id="fixture")
    private = deepcopy(record)
    private["input"]["expected_behavior"] = "plan"
    with pytest.raises(ValueError, match="schema rejected"):
        preparer.prepare(private, root / "results/pilot/private", job_id="fixture_v2", configuration_id="fixture")
    assert tools.core._query_api.encodes == 0


def test_changed_runtime_or_schema_is_rejected_before_fresh_work(context):
    _, tools, client, *_ = context
    tools.runtime["config"]["changed"] = True
    with pytest.raises(ValueError, match="configuration changed"):
        prepare(context)
    tools.runtime["config"].pop("changed")
    client.input_schema["title"] = "Changed after setup"
    with pytest.raises(ValueError, match="configuration changed"):
        prepare(context)
    assert tools.core._query_api.encodes == 0


pytestmark = pytest.mark.requirement("31:fresh-per-job-references")

pytestmark = pytest.mark.requirement("31:bounded-operational-probe")
