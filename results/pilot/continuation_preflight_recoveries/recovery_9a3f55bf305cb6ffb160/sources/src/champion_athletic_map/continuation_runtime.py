"""Compose the saved V4 workflow for a declared final-stage continuation."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


POLICY_VERSION = "lossless-review-continuation-1"


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def module(root, relative, expected=None):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("A continuation dependency leaves the project.")
    source = path.read_bytes()
    if expected is not None and sha(source) != expected:
        raise ValueError("A continuation dependency differs from its binding: " + relative)
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("continuation_" + path.stem, path))
    exec(compile(source, str(path), "exec"), result.__dict__)
    return result


def source_runtime_manifest(root):
    summary = json.loads((root / "results/step31_first_probe_summary.json").read_bytes())
    setup = summary.get("setup_this_execution") or {}
    if isinstance(setup.get("runtime_manifest"), dict):
        return setup["runtime_manifest"]
    candidates = []
    for path in sorted((root / "results/pilot/probes" / summary["probe_id"] / "setup").glob("*.json")):
        value = json.loads(path.read_bytes()).get("runtime_manifest")
        if isinstance(value, dict):
            candidates.append(value)
    if not candidates:
        raise ValueError("The original setup policy could not be verified.")
    fields = ("effective_reference_policy", "effective_instructions_sha256", "public_schema_sha256", "checker_policy")
    if any(any(row.get(key) != candidates[0].get(key) for key in fields) for row in candidates):
        raise ValueError("The original setup records disagree on their effective configuration.")
    return candidates[0]


def encoded_role_type(base, codec):
    class ReviewEncodedRole(base):
        def prepare_request(self, *args, **kwargs):
            prepared, payload, config = super().prepare_request(*args, **kwargs)
            view = self.shared._decode(payload["messages"][1]["content"].encode("utf-8"))
            before = deepcopy(view)
            count_tokens = lambda text: len(self.client.encoder.encode(text, parse_special=False))
            encoded = codec.encode_checks(view["check_results"], count_tokens=count_tokens)
            if canonical(codec.decode_checks(encoded)) != canonical(view["check_results"]):
                raise ValueError("The encoded review does not restore every original check field.")
            if canonical(encoded) != canonical(view["check_results"]):
                view["check_results"] = encoded
                restored = deepcopy(view)
                restored["check_results"] = codec.decode_checks(restored["check_results"])
                if canonical(restored) != canonical(before):
                    raise ValueError("The review encoding changed the complete model input.")
                payload["messages"][0]["content"] += "\n\n" + codec.ENCODING_NOTICE
                payload["messages"][1]["content"] = canonical(view)
            config.update(role_policy=POLICY_VERSION, review_encoding=codec.ENCODING_VERSION,
                review_encoding_cost_basis="pinned_native_token_count",
                lossless_review_roundtrip_verified=True,
                message_sha256=[self.shared._sha(row["content"].encode("utf-8")) for row in payload["messages"]])
            self._budget_view(payload)
            return prepared, payload, config
    return ReviewEncodedRole


def build_runtime(root, review_config, public_schema, *, codec_module=None, engine_factory=None, source_setup=None):
    root = Path(root).resolve()
    if review_config["public_schema_sha256"] != sha(packed(public_schema)):
        raise ValueError("The continuation public schema differs from its reviewed version.")
    for relative, expected in review_config["component_sha256"].items():
        if sha((root / relative).read_bytes()) != expected:
            raise ValueError("A reviewed continuation component changed: " + relative)
    schedule = module(root, "src/champion_athletic_map/pilot_schedule.py",
        review_config["component_sha256"]["src/champion_athletic_map/pilot_schedule.py"])
    if review_config["common_task_addendum"] != schedule.COMMON_TASK_ADDENDUM:
        raise ValueError("The common planning instructions changed.")
    source = source_setup or source_runtime_manifest(root)
    candidate = json.loads((root / "artifacts/planners/version4_candidate_focused_config.json").read_bytes())
    relative = "src/champion_athletic_map/planners/candidate_focused.py"
    constructor = engine_factory or module(root, relative, candidate["module_sha256"][relative]).CandidateFocusedEvaluatedPlanner
    outer = constructor(root)
    engine = outer.planner
    instructions = engine.instructions + "\n\n" + schedule.COMMON_TASK_ADDENDUM
    if (sha(instructions.encode("utf-8")) != source["effective_instructions_sha256"]
            or sha(packed(public_schema)) != source["public_schema_sha256"]):
        raise ValueError("The continuation does not reproduce the original effective public task.")
    policy = deepcopy(source["effective_reference_policy"])
    for node in (outer, engine, engine.drafting):
        node.instructions = instructions
        node.client.input_schema = deepcopy(public_schema)
        node.config = deepcopy(node.config)
        if "reference_policy" in node.config:
            node.config["reference_policy"] = deepcopy(policy)
        if hasattr(node, "roles"):
            node.roles.reference_policy = deepcopy(policy)
    checker = schedule.make_checker(root, engine.client, engine.policy, resources=engine.checker.resources)
    checker.client = engine.client
    if checker.pilot_schedule_policy != source["checker_policy"]:
        raise ValueError("The continuation checker differs from the original policy.")
    engine.checker = checker
    codec = codec_module or module(root, "src/champion_athletic_map/review_encoding.py")
    role = encoded_role_type(type(engine.roles), codec)(root, engine.client, engine._adapter, engine.integration)
    role.reference_policy = deepcopy(policy)
    engine.roles = role
    return SimpleNamespace(engine=engine, roles=role, checker=checker, client=engine.client,
        manifest={"policy_version": POLICY_VERSION, "review_encoding": codec.ENCODING_VERSION,
            "review_encoding_cost_basis": "pinned_native_token_count",
            "effective_instructions_sha256": sha(instructions.encode("utf-8")),
            "public_schema_sha256": sha(packed(public_schema)), "reference_policy": policy,
            "source_checker_policy": source["checker_policy"], "reference_tools_loaded": False,
            "query_runtime_loaded": False, "generation_calls_during_setup": 0,
            "input_facts_changed": False, "acceptance_policy_changed": False,
            "output_and_context_limits_changed": False})
