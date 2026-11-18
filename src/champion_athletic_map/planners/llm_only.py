"""Language-model-only planner using the shared local adapter."""

import hashlib
import importlib.util
import json
from pathlib import Path
from threading import Lock


class LLMOnlyPlanner:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._lock = Lock()
        self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}
        self.config = json.loads(self._read("artifacts/planners/version1_config.json"))
        if (self.config.get("schema_version") != "planner-v1-config-1"
                or type(self.config.get("planner_version")) is not int
                or self.config["planner_version"] != 1):
            raise ValueError("The Version 1 configuration is not the expected version.")

        integration_bytes = self._read("artifacts/language_model/integration_config.json",
                                       self.config["integration_config_sha256"])
        self.integration = json.loads(integration_bytes)
        adapter_path = "src/champion_athletic_map/llm.py"
        adapter_bytes = self._read(adapter_path, self.config["adapter_sha256"])
        self._read("src/champion_athletic_map/reference_packets.py",
                   self.config["reference_packets_sha256"])
        spec = importlib.util.spec_from_file_location("champion_v1_shared_adapter", self.root / adapter_path)
        self._adapter = importlib.util.module_from_spec(spec)
        exec(compile(adapter_bytes, str(self.root / adapter_path), "exec"), self._adapter.__dict__)
        if (self.integration.get("model") != self._adapter.MODEL
                or self.integration.get("model_digest") != self._adapter.DIGEST
                or self.integration.get("prompt_version") != self._adapter.PROMPT_VERSION
                or self.integration.get("automatic_retries") != 0
                or self.integration.get("automatic_repairs") != 0):
            raise ValueError("The shared model settings differ from the saved baseline.")
        summary = json.loads(self._read("results/step24_language_model_integration_summary.json"))
        if (summary.get("calendar_request_status") != "fulfilled"
                or summary.get("current_configuration") != self.integration):
            raise ValueError("Step 24 must contain the current successful calendar check.")

        contracts = self.integration["contracts_directory"]
        self._read(Path(contracts) / "planner_response_schema.json", self.config["response_schema_sha256"])
        self.instructions = self._read(self.config["shared_instructions_path"],
                                       self.config["shared_instructions_sha256"]).decode("utf-8")
        if not self.instructions.strip():
            raise ValueError("The shared planning instructions are empty.")
        self.client = self._adapter.OllamaClient(self.root, contracts)

    def _read(self, relative, expected_sha256=None):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("A planner dependency leaves the project.")
        data = path.read_bytes()
        if expected_sha256 is not None and hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ValueError("A saved planner dependency changed: " + path.name)
        return data

    def generate(self, public_record, call_id):
        """Generate once from validated public facts, without reference access."""
        with self._lock:
            attempts = {"metadata": 0, "render": 0, "generation": 0}
            self.last_transport_attempts = dict(attempts)
            prepared = self.client.public.prepare_public_input(public_record, self.client.input_schema)
            supplied = {"profile_id": prepared["audit"]["profile_id"],
                        "schema_version": prepared["audit"]["profile_schema_version"],
                        "input": prepared["public_input"]}
            original_http = self.client._http

            def counted_http(endpoint, payload=None, timeout=8, raw_path=None):
                if endpoint == "/api/chat":
                    if type(payload) is not dict:
                        raise ValueError("The planner request must be a JSON object.")
                    render_only = payload.get("_debug_render_only") is True
                    expected_keys = {"model", "stream", "format", "truncate", "shift", "messages", "options"}
                    if render_only:
                        expected_keys.add("_debug_render_only")
                    messages = payload.get("messages")
                    if (set(payload) != expected_keys or type(messages) is not list or len(messages) != 2
                            or [message.get("role") for message in messages if type(message) is dict] != ["system", "user"]
                            or any(set(message) != {"role", "content"} for message in messages)
                            or any(type(message.get("content")) is not str for message in messages)
                            or self._adapter._decode(messages[1]["content"].encode("utf-8")) != {"athlete_input": prepared["public_input"]}
                            or payload.get("model") != self.integration["model"]
                            or payload.get("options") != self.integration["options"]
                            or self._adapter._wire_bytes(payload.get("format")) != self._adapter._wire_bytes(self.client.output_schema)
                            or payload.get("stream") is not False
                            or payload.get("truncate") is not False or payload.get("shift") is not False):
                        raise ValueError("Version 1 must use fresh public inputs and the shared model settings.")
                    phase = "render" if render_only else "generation"
                    if attempts[phase]:
                        raise RuntimeError("A planner job cannot submit another " + phase + " request.")
                elif endpoint in ("/api/version", "/api/tags", "/api/show", "/api/ps"):
                    phase = "metadata"
                else:
                    raise ValueError("Version 1 cannot call another endpoint.")
                attempts[phase] += 1
                return original_http(endpoint, payload, timeout, raw_path)

            # We keep the shared save, budget, parsing and unresolved-call behavior.
            self.client._http = counted_http
            try:
                result = self.client.generate(supplied, self.instructions, call_id,
                                              planner_version=1, reference_packet=None)
            finally:
                self.client._http = original_http
                self.last_transport_attempts = dict(attempts)
            return {**result, "planner_version": 1, "transport_attempts": dict(attempts)}
