"""Prepare a fresh canonical reference packet for each pilot workflow job."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
from time import perf_counter


REFERENCE_VERSION = "pilot-fresh-references-1"
_MODULES = {
    "reference_context": "e9e7ee5bdd1f2ef28aa3edb03713a1439bc18614a92b88d85c2035552432542c",
    "reference_preparation": "50e27d8d5cd84313b1935ae3d6212e90bcb2a83177eab5b4cd1b4e8db788392c",
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate key in a reference preparation record.")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite reference record.")))


def _write_once(path, value):
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("An earlier reference preparation differs and was preserved.")
        return
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _module(root, name):
    path = root / "src/champion_athletic_map" / (name + ".py")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != _MODULES[name]:
        raise ValueError("The recorded reference component changed: " + name)
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location("pilot_fresh_" + name, path))
    exec(compile(data, str(path), "exec"), module.__dict__)
    return module


class _RecordedLookups:
    def __init__(self, tools, work, counts):
        self.tools, self.work, self.counts, self.ordinal = tools, work, counts, 0

    def __getattr__(self, name):
        categories = {"get_planning_rules": "rule_lookups", "get_drill": "catalog_lookups",
            "get_exercise": "catalog_lookups", "lookup_food": "food_lookups",
            "complete_reference": "reference_units_resolved"}
        original = getattr(self.tools, name)
        if name not in categories:
            return original

        def recorded(*args, **kwargs):
            folder = self.work / "lookups"
            folder.mkdir(exist_ok=True)
            self.ordinal += 1
            prefix = folder / (str(self.ordinal).zfill(3) + "_" + name)
            _write_once(prefix.with_suffix(".request.json"), {"method": name, "args": list(args), "kwargs": kwargs})
            self.counts[categories[name]] += 1
            result = original(*args, **kwargs)
            _write_once(prefix.with_suffix(".result.json"), result)
            return result
        return recorded


class FreshReferencePreparer:
    """Load the readonly query index once; encode two fresh queries per new job."""

    def __init__(self, root, tools, client, reference_policy, *, builder=None, validator=None, clock=perf_counter):
        self.root, self.tools, self.client = Path(root).resolve(), tools, client
        self.policy, self.clock = deepcopy(reference_policy), clock
        self.policy_sha256 = fingerprint(self.policy)
        self.schema_sha256 = fingerprint(client.input_schema)
        started = clock()
        self.builder = builder or _module(self.root, "reference_context")
        self.validator = validator or _module(self.root, "reference_preparation").validate_packet
        self.module_bindings = {} if builder is not None or validator is not None else {
            "src/champion_athletic_map/" + name + ".py": digest for name, digest in _MODULES.items()}
        self.query_runtime = tools.load_query_runtime()
        self.api = tools.core._query_api
        self.source_bindings = deepcopy(tools.source_bindings)
        self.runtime_configuration_sha256 = fingerprint(self.query_runtime.get("config", {}))
        elapsed = clock() - started
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("The reference setup timer is invalid.")
        self.setup_record = {"schema_version": REFERENCE_VERSION, "query_runtime_setup_seconds": elapsed,
            "source_bindings": self.source_bindings, "module_bindings": self.module_bindings,
            "query_runtime_configuration_sha256": self.runtime_configuration_sha256,
            "query_manifest_sha256": self.query_runtime.get("query_manifest_sha256"),
            "query_encoder_processes": 0, "query_rows_encoded": 0,
            "timing_scope": "query index/runtime loading; tools construction is recorded separately",
            "injected_test_dependencies": builder is not None or validator is not None}

    def count_tokens(self, text):
        value = len(self.client.encoder.encode(text, parse_special=False))
        if type(value) is not int or value < 0:
            raise ValueError("A reference token count is invalid.")
        return value

    def _guard(self):
        if (fingerprint(self.policy) != self.policy_sha256
                or fingerprint(self.client.input_schema) != self.schema_sha256
                or self.tools.source_bindings != self.source_bindings
                or fingerprint(self.query_runtime.get("config", {})) != self.runtime_configuration_sha256):
            raise ValueError("The live reference configuration changed.")
        for relative, expected in self.module_bindings.items():
            if file_hash(self.root / relative) != expected:
                raise ValueError("A recorded reference source changed.")
        self.query_runtime["guard"]()

    def _work(self, directory):
        path = Path(directory)
        path = (path if path.is_absolute() else self.root / path).resolve()
        boundary = (self.root / "results/pilot").resolve()
        if not boundary.is_relative_to(self.root) or not path.is_relative_to(boundary) or path == boundary:
            raise ValueError("Pilot reference work must stay in a separate results/pilot directory.")
        return path

    def _resume(self, work, request, expected_packet_id):
        if not (work / "completed.json").is_file():
            raise RuntimeError("A prior reference preparation is incomplete; its files were preserved and no encoder was rerun.")
        if _read(work / "request.json") != request:
            raise ValueError("The saved reference request does not match this job and configuration.")
        result = _read(work / "completed.json")
        body = {key: value for key, value in result.items() if key != "completion_record_sha256"}
        if result.get("completion_record_sha256") != fingerprint(body) or result.get("request_sha256") != fingerprint(request):
            raise ValueError("The saved reference completion binding changed.")
        for relative, expected in result["artifact_sha256"].items():
            path = (work / relative).resolve()
            if not path.is_relative_to(work) or not path.is_file() or file_hash(path) != expected:
                raise ValueError("A saved reference preparation artifact changed.")
        packet, trace = _read(work / "packet.json"), _read(work / "trace.json")
        prepared = self.client.public.prepare_public_input(request["public_record"], self.client.input_schema)
        self.validator(packet, prepared, self.policy, self.count_tokens)
        if result["packet_id"] != packet["packet_id"] or (expected_packet_id and packet["packet_id"] != expected_packet_id):
            raise ValueError("Reference-enabled versions did not receive the same canonical packet.")
        return self._returned(work, result, packet, trace, reused=True)

    def _returned(self, work, result, packet, trace, *, reused):
        return {"packet": packet, "trace": trace, "cache_reused": reused,
            "packet_path": (work / "packet.json").relative_to(self.root).as_posix(),
            "reference_record_path": (work / "completed.json").relative_to(self.root).as_posix(),
            "preparation_seconds": result["preparation_seconds"], "counts": deepcopy(result["counts"]),
            "new_counts": {key: 0 if reused else value for key, value in result["counts"].items()},
            "request_sha256": result["request_sha256"], "configuration_id": result["configuration_id"]}

    def prepare(self, public_record, work_directory, *, job_id, configuration_id, expected_packet_id=None):
        """Complete each new job once; resume only its verified completed preparation."""
        started = self.clock()
        self._guard()
        if (not isinstance(job_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", job_id) is None
                or not isinstance(configuration_id, str) or not configuration_id.strip()):
            raise ValueError("A stable job and configuration identity is required.")
        prepared = self.client.public.prepare_public_input(public_record, self.client.input_schema)
        work = self._work(work_directory)
        request = {"schema_version": REFERENCE_VERSION, "job_id": job_id, "configuration_id": configuration_id,
            "public_record": deepcopy(public_record), "public_input_sha256": prepared["audit"]["public_input_sha256"],
            "schema_sha256": self.schema_sha256, "policy_sha256": self.policy_sha256,
            "source_bindings": self.source_bindings, "module_bindings": self.module_bindings,
            "query_runtime_configuration_sha256": self.runtime_configuration_sha256,
            "cache_policy": "fresh_per_job; verified continuation reuses its original work"}
        if work.exists():
            return self._resume(work, request, expected_packet_id)
        work.mkdir(parents=True, exist_ok=False)
        _write_once(work / "request.json", request)
        counts = {"query_encoder_processes": 0, "query_rows_encoded": 0, "ranking_calls": 0,
            "rule_lookups": 0, "catalog_lookups": 0, "food_lookups": 0, "reference_units_resolved": 0}
        stage, encoder_invoked, ranking_invoked = "public_queries", False, False
        try:
            queries = self.builder.make_queries(prepared)
            if not isinstance(queries, list) or len(queries) != 2:
                raise ValueError("Exactly two public reference queries are required.")
            records = self.api.make_query_records(queries)
            if len(records) != 2:
                raise ValueError("The query record count changed.")
            _write_once(work / "queries.json", {"queries": queries, "query_records": records})
            stage, encoder_invoked = "query_encoding", True
            _write_once(work / "encoder_started.json", {"request_sha256": fingerprint(request),
                "recorded_at": datetime.now(timezone.utc).isoformat(), "query_rows": 2})
            encoded = self.api.encode_queries(self.query_runtime, records, work.resolve())
            counts.update(query_encoder_processes=1, query_rows_encoded=2)
            _write_once(work / "encoder_report.json", encoded["report"])
            stage, ranking_invoked = "semantic_ranking", True
            ranked = self.api.rank_queries(self.query_runtime, records, encoded["vectors"], routes=("semantic",))
            _write_once(work / "rankings.json", ranked)
            counts["ranking_calls"] = len(ranked) if isinstance(ranked, list) else 0
            if (len(ranked) != 2 or any(row.get("query_id") != query["query_id"] or row.get("route") != "semantic"
                    or row.get("result", {}).get("status") in ("execution_error", "technical_error", "error", "failed")
                    or not isinstance(row.get("result", {}).get("results"), list) or not row["result"]["results"]
                    for row, query in zip(ranked, records))):
                raise RuntimeError("The two required semantic reference searches did not complete.")
            stage = "packet_building"
            packet, trace = self.builder.build_packet(prepared, _RecordedLookups(self.tools, work, counts),
                [row["result"]["results"] for row in ranked], self.count_tokens, self.policy)
            _write_once(work / "packet.json", packet)
            _write_once(work / "builder_trace.json", trace)
            stage = "packet_validation"
            self.validator(packet, prepared, self.policy, self.count_tokens)
            if expected_packet_id and packet["packet_id"] != expected_packet_id:
                raise ValueError("Reference-enabled versions did not receive the same canonical packet.")
            tool_counts = trace.get("tool_calls", {})
            if any(counts[key] != tool_counts.get(label, 0) for key, label in
                    (("rule_lookups", "rules"), ("catalog_lookups", "catalog"), ("food_lookups", "food"))):
                raise ValueError("The packet trace differs from the observed local lookup calls.")
            trace = {"builder_trace": trace, "queries": queries, "ranked_results": ranked,
                "packet_id": packet["packet_id"], "request_sha256": fingerprint(request)}
            _write_once(work / "trace.json", trace)
            self._guard()
            elapsed = self.clock() - started
            if not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError("The reference preparation timer is invalid.")
            artifacts = {p.relative_to(work).as_posix(): file_hash(p) for p in sorted(work.rglob("*")) if p.is_file()}
            result = {"schema_version": REFERENCE_VERSION, "job_id": job_id, "configuration_id": configuration_id,
                "request_sha256": fingerprint(request), "packet_id": packet["packet_id"], "counts": counts,
                "preparation_seconds": elapsed, "timing_scope": "public preparation through persisted packet/trace; completion-record write excluded",
                "artifact_sha256": artifacts, "state": "completed"}
            result["completion_record_sha256"] = fingerprint(result)
            _write_once(work / "completed.json", result)
            return self._returned(work, result, packet, trace, reused=False)
        except BaseException as error:
            # A failed stage is retained; its folder is never treated as a new job.
            artifacts = {p.relative_to(work).as_posix(): file_hash(p) for p in sorted(work.rglob("*")) if p.is_file()}
            _write_once(work / "failure.json", {"schema_version": REFERENCE_VERSION, "job_id": job_id,
                "configuration_id": configuration_id, "request_sha256": fingerprint(request), "failed_stage": stage,
                "error": type(error).__name__ + ": " + str(error), "counts_confirmed": counts,
                "encoder_api_invoked": encoder_invoked,
                "encoder_process_start_count_unverified": encoder_invoked and counts["query_encoder_processes"] == 0,
                "ranking_api_invoked": ranking_invoked,
                "ranking_call_count_unverified": ranking_invoked and counts["ranking_calls"] == 0,
                "artifact_sha256": artifacts, "model_generation_calls": 0})
            raise
