"""Prepare and reuse the same reference packets for our reference-supported planners."""

import hashlib
import importlib.util
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _write_once(path, value):
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("An existing reference preparation differs and was preserved.")
    else:
        with path.open("xb") as handle:
            handle.write(data)


def validate_packet(packet, prepared, policy, count_tokens):
    """Check the saved content without regenerating or trimming it."""
    body = {key: value for key, value in packet.items() if key != "packet_id"}
    preparation = packet.get("preparation", {})
    if (packet.get("schema_version") != "shared-reference-packet-1"
            or packet.get("public_input_sha256") != prepared["audit"]["public_input_sha256"]
            or packet.get("packet_id") != "reference-packet:" + _hash(body)
            or preparation.get("builder_policy") != policy["policy_version"]
            or preparation.get("source_configuration_sha256") != policy["source_configuration_sha256"]
            or count_tokens(_json(packet["payload"])) > policy["max_packet_tokens"]):
        raise ValueError("The matched reference packet changed or exceeds its budget.")
    return True


def prepare_reference_packets(root, prepared_profiles, tools, count_tokens, policy):
    """Batch only missing public queries; reuse complete saved packets unchanged."""
    root = Path(root).resolve()
    source = root / "src/champion_athletic_map/reference_context.py"
    spec = importlib.util.spec_from_file_location("champion_shared_reference_context", source)
    builder = importlib.util.module_from_spec(spec)
    exec(compile(source.read_bytes(), str(source), "exec"), builder.__dict__)
    folder = root / "artifacts/planners/reference_packets" / policy["source_configuration_sha256"][:16]
    results, missing = [None] * len(prepared_profiles), []
    counts = {"query_rows_encoded": 0, "query_encoder_processes": 0, "ranking_calls": 0,
              "rule_lookups": 0, "catalog_lookups": 0, "food_lookups": 0, "cached_packets": 0}
    started = perf_counter()
    for index, prepared in enumerate(prepared_profiles):
        key = prepared["audit"]["public_input_sha256"]
        packet_path, trace_path = folder / (key + ".json"), folder / (key + ".preparation.json")
        if packet_path.exists():
            if not trace_path.is_file():
                raise ValueError("A saved packet is missing its preparation record.")
            packet, trace = json.loads(packet_path.read_bytes()), json.loads(trace_path.read_bytes())
            validate_packet(packet, prepared, policy, count_tokens)
            trace_body = {key: value for key, value in trace.items() if key != "preparation_record_sha256"}
            if (trace.get("packet_id") != packet["packet_id"]
                    or trace.get("preparation_record_sha256") != _hash(trace_body)):
                raise ValueError("The saved preparation record belongs to a different packet.")
            results[index] = {"packet": packet, "trace": trace, "cache_reused": True,
                              "packet_path": packet_path.relative_to(root).as_posix()}
            counts["cached_packets"] += 1
        else:
            if trace_path.exists():
                raise ValueError("A prior reference preparation is incomplete; its record was preserved.")
            missing.append((index, prepared, packet_path, trace_path, builder.make_queries(prepared)))

    if missing:
        runtime = tools.load_query_runtime()
        api = tools.core._query_api
        # We load the pinned query encoder once for up to thirty profiles per batch.
        for offset in range(0, len(missing), 30):
            group = missing[offset:offset + 30]
            texts = [query for _, _, _, _, queries in group for query in queries]
            records = api.make_query_records(texts)
            work = root / "results/planner_v2/query_batches" / uuid4().hex[:12]
            work.mkdir(parents=True)
            encoded = api.encode_queries(runtime, records, work.resolve())
            ranked = api.rank_queries(runtime, records, encoded["vectors"], routes=("semantic",))
            if (len(ranked) != len(records)
                    or any(row["query_id"] != query["query_id"] or row["route"] != "semantic"
                           for row, query in zip(ranked, records))):
                raise ValueError("The query rankings do not match our public query batch.")
            counts["query_rows_encoded"] += len(records)
            counts["query_encoder_processes"] += 1
            counts["ranking_calls"] += len(ranked)
            for ordinal, (index, prepared, packet_path, trace_path, queries) in enumerate(group):
                pair = ranked[2 * ordinal:2 * ordinal + 2]
                if any(row.get("result", {}).get("status") in ("execution_error", "technical_error", "error", "failed")
                       or not isinstance(row.get("result", {}).get("results"), list)
                       or not row["result"]["results"] for row in pair):
                    raise RuntimeError("A required reference search did not return its ranked source units.")
                lists = [item["result"]["results"] for item in pair]
                packet, trace = builder.build_packet(prepared, tools, lists, count_tokens, policy)
                validate_packet(packet, prepared, policy, count_tokens)
                trace.update(packet_id=packet["packet_id"], queries=queries, ranked_results=pair,
                             query_batch_directory=work.relative_to(root).as_posix())
                trace["preparation_record_sha256"] = _hash(trace)
                tool_counts = trace.get("tool_calls", {})
                counts["rule_lookups"] += tool_counts.get("rules", 1)
                counts["catalog_lookups"] += tool_counts.get("catalog", 0)
                counts["food_lookups"] += tool_counts.get("food", 0)
                _write_once(trace_path, trace)
                _write_once(packet_path, packet)
                results[index] = {"packet": packet, "trace": trace, "cache_reused": False,
                                  "packet_path": packet_path.relative_to(root).as_posix()}
    return results, {**counts, "preparation_seconds": perf_counter() - started}
