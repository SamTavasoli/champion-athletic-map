"""Reference-supported planner using the same model and task as our baseline."""

import hashlib
import importlib.util
import json
from pathlib import Path
from threading import Lock


class RAGPlanner:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._lock = Lock()
        self.config = json.loads((self.root / "artifacts/planners/version2_config.json").read_bytes())
        if self.config.get("schema_version") != "planner-v2-config-1" or self.config.get("planner_version") != 2:
            raise ValueError("The Version 2 configuration is not the expected version.")
        baseline_path = self.root / "artifacts/planners/version1_config.json"
        if hashlib.sha256(baseline_path.read_bytes()).hexdigest() != self.config["baseline_config_sha256"]:
            raise ValueError("Our saved baseline configuration changed.")
        source_path = self.root / "src/champion_athletic_map/planners/llm_only.py"
        source = source_path.read_bytes()
        if hashlib.sha256(source).hexdigest() != self.config["baseline_workflow_sha256"]:
            raise ValueError("Our baseline workflow changed.")
        spec = importlib.util.spec_from_file_location("champion_v2_baseline_dependencies", source_path)
        baseline_module = importlib.util.module_from_spec(spec)
        exec(compile(source, str(source_path), "exec"), baseline_module.__dict__)
        baseline = baseline_module.LLMOnlyPlanner(self.root)
        self.client, self.instructions = baseline.client, baseline.instructions
        self.integration, self._adapter = baseline.integration, baseline._adapter
        self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}

    def generate(self, public_record, reference_packet, call_id):
        """Generate once from public facts and the saved matched packet."""
        with self._lock:
            attempts = {"metadata": 0, "render": 0, "generation": 0}
            self.last_transport_attempts = dict(attempts)
            policy = self.config["reference_policy"]
            preparation = reference_packet.get("preparation", {}) if type(reference_packet) is dict else {}
            if (type(preparation) is not dict
                    or preparation.get("builder_policy") != policy["policy_version"]
                    or preparation.get("source_configuration_sha256") != policy["source_configuration_sha256"]):
                raise ValueError("The reference packet does not match our saved reference policy.")
            prepared, _, _ = self.client.prepare_request(public_record, self.instructions,
                planner_version=2, reference_packet=reference_packet)
            expected_user = {"athlete_input": prepared["public_input"], "reference_data": reference_packet["payload"]}
            supplied = {"profile_id": prepared["audit"]["profile_id"],
                        "schema_version": prepared["audit"]["profile_schema_version"], "input": prepared["public_input"]}
            original_http = self.client._http

            def counted_http(endpoint, payload=None, timeout=8, raw_path=None):
                if endpoint == "/api/chat":
                    if type(payload) is not dict:
                        raise ValueError("The planner request must be a JSON object.")
                    render_only = payload.get("_debug_render_only") is True
                    keys = {"model", "stream", "format", "truncate", "shift", "messages", "options"}
                    if render_only:
                        keys.add("_debug_render_only")
                    messages = payload.get("messages")
                    if (set(payload) != keys or type(messages) is not list or len(messages) != 2
                            or [m.get("role") for m in messages if type(m) is dict] != ["system", "user"]
                            or any(set(m) != {"role", "content"} for m in messages)
                            or any(type(m.get("content")) is not str for m in messages)
                            or self._adapter._decode(messages[1]["content"].encode("utf-8")) != expected_user
                            or payload.get("model") != self.integration["model"]
                            or payload.get("options") != self.integration["options"]
                            or self._adapter._wire_bytes(payload.get("format")) != self._adapter._wire_bytes(self.client.output_schema)
                            or payload.get("stream") is not False or payload.get("truncate") is not False
                            or payload.get("shift") is not False):
                        raise ValueError("Version 2 must use the unchanged public facts, matched packet and common settings.")
                    phase = "render" if render_only else "generation"
                    if attempts[phase]:
                        raise RuntimeError("A planner job cannot submit another " + phase + " request.")
                elif endpoint in ("/api/version", "/api/tags", "/api/show", "/api/ps"):
                    phase = "metadata"
                else:
                    raise ValueError("Version 2 cannot call another endpoint during generation.")
                attempts[phase] += 1
                return original_http(endpoint, payload, timeout, raw_path)

            # We keep the existing save, budget, parsing and unfinished-call behavior.
            self.client._http = counted_http
            try:
                result = self.client.generate(supplied, self.instructions, call_id,
                    planner_version=2, reference_packet=reference_packet)
            finally:
                self.client._http = original_http
                self.last_transport_attempts = dict(attempts)
            return {**result, "planner_version": 2, "transport_attempts": dict(attempts),
                    "reference_packet_id": reference_packet["packet_id"]}
