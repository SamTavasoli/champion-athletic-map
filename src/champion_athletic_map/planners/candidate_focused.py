"""Prepare a candidate-focused evaluator for a future, separately recorded pilot."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from threading import Lock


POLICY_VERSION = "candidate-focused-review-1"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _role_type(original_type, codec):
    """Keep the original transport and replace only the candidate representation."""
    class CandidateFocusedRoleAdapter(original_type):
        def prepare_request(self, *args, **kwargs):
            prepared, payload, configuration = super().prepare_request(*args, **kwargs)
            view = self.shared._decode(payload["messages"][1]["content"].encode("utf-8"))
            original = copy.deepcopy(view["candidate"])
            encoded = codec.encode_candidate(original)
            if _json(codec.decode_candidate(encoded)) != _json(original):
                raise ValueError("The compact candidate does not reproduce its complete original content.")
            if _json(encoded) != _json(original):
                view["candidate"] = encoded
                original_notice = "Coded findings with columns are complete rows in that column order."
                system = payload["messages"][0]["content"]
                payload["messages"][0]["content"] = (system.replace(original_notice, codec.ENCODING_NOTICE, 1)
                    if original_notice in system else system + "\n\n" + codec.ENCODING_NOTICE)
                payload["messages"][1]["content"] = _json(view)
            configuration.update(role_policy=POLICY_VERSION,
                input_format="candidate-focused-public-reference-input-1",
                candidate_encoding=getattr(codec, "ENCODING_VERSION", "lossless-calendar-1") if encoded != original else "unchanged",
                message_sha256=[self.shared._sha(message["content"].encode("utf-8")) for message in payload["messages"]])
            self._budget_view(payload)
            return prepared, payload, configuration
    return CandidateFocusedRoleAdapter


class CandidateFocusedEvaluatedPlanner:
    """Run fresh drafting and review jobs; installing this class starts no model call."""

    def __init__(self, root, source_config=None, candidate_config=None):
        self.root = Path(root).resolve()
        self._lock = Lock()
        self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}
        config_path = "artifacts/planners/version4_candidate_focused_config.json"
        raw = self._read(config_path)
        candidate = json.loads(raw)
        if candidate_config is not None and candidate != candidate_config:
            raise ValueError("The candidate-focused configuration differs from its saved file.")
        self.config, self.config_sha256 = candidate, _sha(raw)
        source_path = candidate.get("source_config_path", "artifacts/planners/version4_config.json")
        source = json.loads(self._read(source_path, candidate["source_config_sha256"]))
        if source_config is not None and source != source_config:
            raise ValueError("The original planner configuration changed.")
        self.source_config = source
        for path, digest in candidate["module_sha256"].items():
            self._read(path, digest)
        original_path = "src/champion_athletic_map/planners/evaluated_specialists.py"
        original = self._module("champion_original_v4_candidate_pilot", original_path,
                                source["module_sha256"][original_path])
        self.planner = original.EvaluatedSpecialistPlanner(self.root)
        prompt = candidate["evaluator_prompt"]
        evaluator_prompt = self._read(prompt["path"], prompt["sha256"]).decode("utf-8")
        if not evaluator_prompt.strip():
            raise ValueError("The candidate-focused evaluator prompt is empty.")
        self.planner.prompts["evaluator"] = evaluator_prompt
        codec_path = "src/champion_athletic_map/context_encoding.py"
        codec = self._module("champion_lossless_calendar_encoding", codec_path,
                             candidate["module_sha256"][codec_path])
        roles_path = "src/champion_athletic_map/evaluated_role_adapter.py"
        roles = self._module("champion_original_v4_transport_for_pilot", roles_path,
                             source["module_sha256"][roles_path])
        self.planner.roles = _role_type(roles.EvaluatedRoleAdapter, codec)(
            self.root, self.planner.client, self.planner._adapter, self.planner.integration)
        self.client, self.integration = self.planner.client, self.planner.integration
        self.instructions, self.policy = self.planner.instructions, self.planner.policy

    def _read(self, relative, expected=None):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("A candidate-focused planner dependency leaves our project.")
        data = path.read_bytes()
        if expected is not None and _sha(data) != expected:
            raise ValueError("A candidate-focused planner dependency changed: " + path.name)
        return data

    def _module(self, name, relative, expected):
        source = self._read(relative, expected)
        module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, self.root / relative))
        exec(compile(source, str(self.root / relative), "exec"), module.__dict__)
        return module

    def generate(self, public_record, reference_packet, call_id):
        """Record this job's own complete drafting, checks, evaluation and revisions."""
        with self._lock:
            self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}
            try:
                result = self.planner.generate(public_record, reference_packet, call_id)
            finally:
                self.last_transport_attempts = dict(self.planner.last_transport_attempts)
            return {**result, "candidate_focused_preparation": {
                "policy_version": POLICY_VERSION, "configuration_sha256": self.config_sha256,
                "mode": "fresh_workflow", "readiness": self.config.get("readiness", "awaiting_pilot"),
                "earlier_results_regraded": False, "operational_generation_ready": False}}
