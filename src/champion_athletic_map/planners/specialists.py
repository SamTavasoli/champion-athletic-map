"""Prepare focused notes, then coordinate one response from the same public facts."""

import hashlib
import importlib.util
import json
from pathlib import Path
from threading import Lock
from time import perf_counter


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class SpecialistPlanner:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._lock = Lock()
        self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}
        self.config = json.loads(self._read("artifacts/planners/version3_config.json"))
        if self.config.get("schema_version") != "planner-v3-config-1" or self.config.get("planner_version") != 3:
            raise ValueError("The Version 3 configuration is not the expected version.")
        baseline_bytes = self._read("artifacts/planners/version2_config.json", self.config["baseline_v2_config_sha256"])
        baseline = json.loads(baseline_bytes)
        if self.config["reference_policy"] != baseline["reference_policy"]:
            raise ValueError("Our specialist workflow must use the same reference policy.")
        for name, digest in self.config["module_sha256"].items():
            self._read(name, digest)
        if set(self.config["prompts"]) != {"training", "recovery", "food", "coordinator"}:
            raise ValueError("Our four role prompts must be present.")
        self.prompts = {role: self._read(item["path"], item["sha256"]).decode("utf-8")
                        for role, item in self.config["prompts"].items()}
        if any(not prompt.strip() for prompt in self.prompts.values()):
            raise ValueError("A specialist role prompt is empty.")
        self.note_schema = json.loads(self._read(self.config["note_schema_path"], self.config["note_schema_sha256"]))
        expected_limits = {"training": 512, "recovery": 512, "food": 512, "coordinator": 2048}
        if self.config["role_output_tokens"] != expected_limits:
            raise ValueError("Our saved role output limits changed.")
        rag_path = "src/champion_athletic_map/planners/rag.py"
        rag = self._module("champion_specialist_shared_foundation", rag_path,
                           baseline["module_sha256"][rag_path])
        foundation = rag.RAGPlanner(self.root)
        self.client, self.instructions = foundation.client, foundation.instructions
        self.integration, self._adapter = foundation.integration, foundation._adapter
        adapter_path = "src/champion_athletic_map/role_adapter.py"
        adapter = self._module("champion_specialist_role_adapter", adapter_path,
                               self.config["module_sha256"][adapter_path])
        self.roles = adapter.RoleAdapter(self.root, self.client, self._adapter, self.integration)
        preparation_path = "src/champion_athletic_map/reference_preparation.py"
        self._preparation = self._module("champion_specialist_packet_validation", preparation_path,
                                        baseline["module_sha256"][preparation_path])

    def _read(self, relative, expected=None):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("A specialist dependency leaves our project.")
        data = path.read_bytes()
        if expected is not None and _sha(data) != expected:
            raise ValueError("A saved specialist dependency changed: " + path.name)
        return data

    def _module(self, name, relative, expected):
        data = self._read(relative, expected)
        result = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, self.root / relative))
        exec(compile(data, str(self.root / relative), "exec"), result.__dict__)
        return result

    def draft(self, public_record, reference_packet, call_id, *, planner_version=3):
        """Use the same drafting sequence for separately recorded Version 3 or 4 jobs."""
        return self.generate(public_record, reference_packet, call_id, planner_version=planner_version)

    def generate(self, public_record, reference_packet, call_id, *, planner_version=3):
        with self._lock:
            if type(planner_version) is not int or planner_version not in (3, 4):
                raise ValueError("Specialist drafting is available only to Versions 3 and 4.")
            started = perf_counter()
            totals = {"metadata": 0, "render": 0, "generation": 0}
            self.last_transport_attempts = dict(totals)
            prepared = self.client.public.prepare_public_input(public_record, self.client.input_schema)
            self._preparation.validate_packet(reference_packet, prepared, self.config["reference_policy"],
                lambda text: len(self.client.encoder.encode(text, parse_special=False)))
            question = prepared["public_input"].get("food_question")
            food_active = isinstance(question, str) and bool(question.strip())
            sequence = ["training", "recovery", "food", "coordinator"]
            required = [role for role in sequence if role != "food" or food_active]
            notes, stages, final, failed_stage = [], [], None, None
            for position, role in enumerate(sequence):
                if role == "food" and not food_active:
                    stages.append({"stage": role, "status": "skipped_public_route", "execution": "skipped_public_route"})
                    continue
                stage_started = perf_counter()
                instructions = self.instructions + "\n\n" + self.prompts[role]
                try:
                    result = self.roles.generate(public_record, reference_packet, instructions,
                        call_id + "_" + role, stage=role,
                        output_schema=None if role == "coordinator" else self.note_schema,
                        output_tokens=self.config["role_output_tokens"][role],
                        specialist_notes=notes if role == "coordinator" else None,
                        planner_version=planner_version)
                except Exception as error:
                    result = {"status": "blocked", "format_valid": False, "completion_valid": False,
                              "cached": False, "response_type": None, "response": None,
                              "error": str(error), "call_id": call_id + "_" + role,
                              "transport_attempts": dict(self.roles.last_transport_attempts)}
                attempts = result.get("transport_attempts", {})
                for key in totals:
                    totals[key] += attempts.get(key, 0)
                self.last_transport_attempts = dict(totals)
                stages.append({"stage": role, "status": result.get("status"), "execution": "recorded", "result": result,
                               "elapsed_seconds_this_execution": perf_counter() - stage_started,
                               "reference_packet_id": reference_packet["packet_id"]})
                if not result.get("completion_valid") or (role != "coordinator" and not result.get("format_valid")):
                    failed_stage = role
                    for remaining in sequence[position + 1:]:
                        state = "skipped_public_route" if remaining == "food" and not food_active else "not_started"
                        stages.append({"stage": remaining, "status": state, "execution": state, "reason": "required_stage_failed"})
                    final = {"status": "unresolved" if result.get("status") == "unresolved" else
                                       "blocked" if result.get("status") == "blocked" else "failed",
                             "format_valid": False, "completion_valid": False, "response_type": None,
                             "response": None, "error": "Required " + role + " contribution did not complete and validate.",
                             "failed_stage_error": result.get("error"), "call_id": call_id}
                    break
                if role == "coordinator":
                    final = result
                else:
                    parsed = result["response"]["model_output"]["parsed_object"]
                    notes.append({"role": role, "contribution": parsed})
            # We retain every stage; limited-information notes can still reach coordination.
            recorded = [stage for stage in stages if stage["execution"] == "recorded"]
            reused = sum(stage["result"].get("cached") is True for stage in recorded)
            return {**final, "planner_version": planner_version, "job_call_id": call_id,
                    "cached": bool(recorded) and reused == len(recorded),
                    "transport_attempts": dict(totals), "stages": stages, "specialist_notes": notes,
                    "food_role_active": food_active, "required_roles": required, "failed_stage": failed_stage,
                    "logical_stage_calls": len(recorded), "saved_stage_responses_reused": reused,
                    "reference_packet_id": reference_packet["packet_id"],
                    "reference_calls_during_roles": 0, "classifier_calls": 0, "evaluator_calls": 0,
                    "elapsed_seconds": perf_counter() - started,
                    "operational_generation_ready": False}
