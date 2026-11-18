"""Clarify evaluator completion and resume from verified, unchanged draft receipts."""

import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from threading import Lock


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class _SavedDraft:
    def __init__(self, original, public_record, packet, draft, call_id):
        self.original = original
        self.public_record, self.packet = copy.deepcopy(public_record), copy.deepcopy(packet)
        self.saved, self.call_id = copy.deepcopy(draft), call_id
        self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}

    def __getattr__(self, name):
        return getattr(self.original, name)

    def draft(self, public_record, reference_packet, call_id, *, planner_version=4):
        if (planner_version != 4 or call_id != self.call_id + "_draft"
                or _canonical(public_record) != _canonical(self.public_record)
                or _canonical(reference_packet) != _canonical(self.packet)):
            raise ValueError("The saved draft belongs to different public inputs or a different job.")
        draft = copy.deepcopy(self.saved)
        count = 0
        for stage in draft["stages"]:
            if stage.get("execution") == "recorded":
                stage["result"]["cached"] = True
                stage["result"]["transport_attempts"] = dict(self.last_transport_attempts)
                stage["elapsed_seconds_this_execution"] = 0
                count += 1
        draft.update(cached=True, transport_attempts=dict(self.last_transport_attempts),
                     saved_stage_responses_reused=count, elapsed_seconds=0,
                     source_draft_reused=True)
        return draft


class CorrectedEvaluatedPlanner:
    """Run new Version 4 jobs with a clearer evaluator prompt and the same checks."""

    def __init__(self, root, source_config, resume_config):
        self.root = Path(root).resolve()
        self.source_config, self.resume_config = copy.deepcopy(source_config), copy.deepcopy(resume_config)
        self._lock = Lock()
        self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}
        raw = self._read("artifacts/planners/version4_config.json", resume_config["source_config_sha256"])
        if json.loads(raw) != source_config:
            raise ValueError("The original Version 4 configuration differs from the correction's source.")
        source = "src/champion_athletic_map/planners/evaluated_specialists.py"
        code = self._read(source, source_config["module_sha256"][source])
        spec = importlib.util.spec_from_file_location("champion_original_v4_for_evaluator_fix", self.root / source)
        self.workflow = importlib.util.module_from_spec(spec)
        exec(compile(code, str(self.root / source), "exec"), self.workflow.__dict__)
        self.planner = self.workflow.EvaluatedSpecialistPlanner(self.root)
        prompt = resume_config["evaluator_prompt"]
        self.corrected_prompt = self._read(prompt["path"], prompt["sha256"]).decode("utf-8")
        if not self.corrected_prompt.strip():
            raise ValueError("The clarified evaluator prompt is empty.")
        self.original_evaluator_prompt = self.planner.prompts["evaluator"]
        self.planner.prompts["evaluator"] = self.corrected_prompt
        self.client, self.integration = self.planner.client, self.planner.integration
        self.instructions, self.policy = self.planner.instructions, self.planner.policy

    def _read(self, relative, expected=None):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("A saved correction dependency leaves our project.")
        data = path.read_bytes()
        if expected is not None and _sha(data) != expected:
            raise ValueError("A saved evaluator-correction dependency changed: " + path.name)
        return data

    def generate(self, public_record, packet, call_id):
        """Use fresh drafting for future jobs; this entry point never replays a parent draft."""
        with self._lock:
            self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}
            try:
                result = self.planner.generate(public_record, packet, call_id)
            finally:
                self.last_transport_attempts = dict(self.planner.last_transport_attempts)
            return {**result, "evaluator_prompt_correction": {
                "mode": "fresh_workflow", "source_config_sha256": self.resume_config["source_config_sha256"],
                "evaluator_prompt_sha256": self.resume_config["evaluator_prompt"]["sha256"]}}


class ResumedEvaluatedPlanner(CorrectedEvaluatedPlanner):
    """Re-evaluate a saved initial draft after the evaluator-prompt correction."""

    def _verify_receipt(self, role, public_record, packet, instructions, logged, *, schema,
                        tokens, notes, adapter, bindings):
        shared = self.planner._adapter
        call_id = logged.get("call_id")
        if type(call_id) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", call_id) is None:
            raise ValueError("A source role lacks a stable saved call ID.")
        folder = "results/integration/model_calls/" + call_id
        loaded = {}
        for name in ("request.json", "result.json", "backend_response.json", "rendered_prompt.txt"):
            relative = folder + "/" + name
            raw = self._read(relative)
            bindings[relative] = _sha(raw)
            loaded[name] = raw if name.endswith(".txt") else shared._decode(raw)
        saved, receipt, answer = (loaded[name] for name in ("result.json", "request.json", "backend_response.json"))
        prepared, expected, configuration = adapter.prepare_request(public_record, packet, instructions,
            stage=role, output_schema=schema, output_tokens=tokens, specialist_notes=notes, planner_version=4)
        request_sha = shared._sha(shared._wire_bytes(expected))
        if (saved.get("request_sha256") != request_sha or receipt.get("input_audit") != prepared["audit"]
                or shared._sha(shared._wire_bytes(receipt.get("request"))) != request_sha
                or saved.get("input_configuration") != configuration
                or receipt.get("input_configuration") != configuration
                or saved.get("model_digest") != shared.DIGEST or saved.get("completion_valid") is not True):
            raise ValueError("A saved source role no longer matches its exact original request.")
        ignored = {"cached", "transport_attempts"}
        if ({key: value for key, value in logged.items() if key not in ignored}
                != {key: value for key, value in saved.items() if key not in ignored}):
            raise ValueError("A logged source contribution differs from its saved role receipt.")
        message = answer.get("message", {})
        complete = (answer.get("done") is True and answer.get("model") == shared.MODEL
            and answer.get("done_reason") == "stop" and not answer.get("error")
            and not answer.get("remote_host") and not answer.get("remote_model")
            and type(message) is dict and message.get("role") == "assistant"
            and type(message.get("content")) is str and message.get("thinking") in (None, "")
            and message.get("tool_calls") in (None, []) and message.get("images") in (None, [])
            and answer.get("_debug_info") is None)
        if not complete:
            raise ValueError("A source contribution was not a completed local response.")
        parsed = self.client.response.parse_response_text(message["content"], self.client.response_schema if schema is None else schema)
        preserved = self.client.public.preserve_response_record(prepared, parsed)
        if (saved.get("response") != preserved or saved.get("format_valid") is not parsed["parse_valid"]
                or role != "coordinator" and parsed["parse_valid"] is not True):
            raise ValueError("A source role's raw wording or parsed contribution changed.")
        budget = self.client.preflight.assess_rendered_prompt(adapter._budget_view(expected),
            loaded["rendered_prompt.txt"].decode("utf-8"), self.client.encoder, self.client.controls)
        budget.update(request_sha256=request_sha, output_format="native_json_schema")
        count, output = answer.get("prompt_eval_count"), answer.get("eval_count")
        if (budget != saved.get("context") or budget["status"] != "within_local_budget"
                or type(count) is not int or not 0 < count <= budget["input_ceiling_after_output_and_margin"]
                or type(output) is not int or not 0 < output <= tokens):
            raise ValueError("A source role's saved completion budget cannot be verified.")
        return saved, parsed

    def _verify_source(self, public_record, packet, source_outcome):
        """Verify original role receipts without submitting or repairing a request."""
        if (source_outcome.get("run_id") != self.source_config["run_id"]
                or source_outcome.get("profile_id") != public_record["profile_id"]
                or source_outcome.get("reference_packet_id") != packet["packet_id"]):
            raise ValueError("The parent development outcome belongs to another source case.")
        outcome = source_outcome["result"]
        if (outcome.get("failed_stage") != "evaluator" or outcome.get("revisions_used") != 0
                or outcome.get("internally_accepted") is not False):
            raise ValueError("Only the saved incomplete-evaluator outcome is eligible for this correction.")
        draft = outcome.get("draft_result")
        if not isinstance(draft, dict) or draft.get("completion_valid") is not True:
            raise ValueError("The source job has no completed initial draft to reuse.")
        drafting = self.planner.drafting
        question = public_record["input"].get("food_question")
        expected_roles = ["training", "recovery"] + (["food"] if isinstance(question, str) and question.strip() else []) + ["coordinator"]
        recorded = [stage for stage in draft.get("stages", []) if stage.get("execution") == "recorded"]
        if [stage.get("stage") for stage in recorded] != expected_roles:
            raise ValueError("The source initial draft did not complete every required role in order.")
        roles = outcome.get("roles", [])
        if [role.get("stage") for role in roles] != expected_roles + ["evaluator"]:
            raise ValueError("The source job contains an unexpected role sequence.")
        source_job = outcome.get("job_call_id")
        bindings, notes, saved_stages = {}, [], []
        for stage, logged_role in zip(recorded, roles):
            role, logged = stage["stage"], stage["result"]
            if logged_role.get("result") != logged or logged.get("call_id") != source_job + "_draft_" + role:
                raise ValueError("The source role lineage differs from the parent initial draft.")
            schema = None if role == "coordinator" else drafting.note_schema
            saved, parsed = self._verify_receipt(role, public_record, packet,
                drafting.instructions + "\n\n" + drafting.prompts[role], logged, schema=schema,
                tokens=drafting.config["role_output_tokens"][role], notes=notes if role == "coordinator" else None,
                adapter=drafting.roles, bindings=bindings)
            saved_stages.append(saved)
            if role != "coordinator":
                notes.append({"role": role, "contribution": parsed["parsed_object"]})
        if draft.get("specialist_notes") != notes:
            raise ValueError("The source draft notes differ from the verified specialist wording.")
        coordinator = saved_stages[-1]
        for key in ("response", "format_valid", "completion_valid", "response_type", "request_sha256", "input_configuration", "call_id", "model_digest", "status"):
            if draft.get(key) != coordinator.get(key):
                raise ValueError("The reused initial candidate differs from its original coordinator receipt.")
        history = outcome.get("history", [])
        if len(history) != 1 or history[0].get("candidate_id") != "candidate_0":
            raise ValueError("The parent outcome contains an unexpected assessed candidate history.")
        report = self.planner.checker.check(public_record, draft, packet, candidate_id="candidate_0")
        if report != history[0].get("check_report") or not self.workflow._coverage(report, self.planner.policy):
            raise ValueError("The original candidate's complete coded findings no longer match.")
        evaluator = roles[-1]["result"]
        if evaluator.get("call_id") != source_job + "_evaluator0" or history[0].get("evaluator_result") != evaluator:
            raise ValueError("The original evaluator does not match its assessed candidate.")
        envelope = {"notes": notes, "candidate": self.workflow.candidate_view(draft, "candidate_0"),
                    "check_results": self.workflow.model_check_view(report)}
        saved_evaluator, parsed = self._verify_receipt("evaluator", public_record, packet,
            self.planner.instructions + "\n\n" + self.original_evaluator_prompt, evaluator,
            schema=self.planner.evaluator_schema, tokens=768, notes=envelope,
            adapter=self.planner.roles, bindings=bindings)
        if (parsed["parse_valid"] is not True or not isinstance(parsed["parsed_object"], dict)
                or parsed["parsed_object"].get("assessment_complete") is not False):
            raise ValueError("The parent evaluator was not the diagnosed incomplete-review response.")
        prior_calls = sum(saved.get("transport_attempts", {}).get("generation", 0) for saved in saved_stages + [saved_evaluator])
        return copy.deepcopy(draft), {"source_job_call_id": source_job,
            "source_run_id": self.source_config["run_id"], "source_profile_id": public_record["profile_id"],
            "source_reference_packet_id": packet["packet_id"], "source_receipt_sha256": bindings,
            "source_model_calls": prior_calls, "reused_initial_role_count": len(expected_roles)}

    def generate(self, public_record, packet, call_id, source_outcome):
        with self._lock:
            self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}
            saved, lineage = self._verify_source(public_record, packet, source_outcome)
            original = self.planner.drafting
            self.planner.drafting = _SavedDraft(original, public_record, packet, saved, call_id)
            try:
                result = self.planner.generate(public_record, packet, call_id)
            finally:
                self.last_transport_attempts = dict(self.planner.last_transport_attempts)
                self.planner.drafting = original
            saved_new_calls, seen = 0, set()
            for role in result.get("roles", []):
                if role.get("stage") not in ("evaluator", "revision"):
                    continue
                receipt = role["result"]
                role_id = receipt.get("call_id")
                if not role_id or role_id in seen:
                    continue
                seen.add(role_id)
                saved_path = self.root / "results/integration/model_calls" / role_id / "result.json"
                if saved_path.is_file():
                    receipt = self.planner._adapter._decode(saved_path.read_bytes())
                saved_new_calls += receipt.get("transport_attempts", {}).get("generation", 0)
            return {**result, "evaluator_prompt_correction": {
                "mode": "resume_verified_initial_draft", **lineage,
                "source_config_sha256": self.resume_config["source_config_sha256"],
                "evaluator_prompt_sha256": self.resume_config["evaluator_prompt"]["sha256"],
                "incremental_model_calls": result["transport_attempts"]["generation"],
                "saved_correction_model_calls": saved_new_calls,
                "cumulative_model_calls_for_profile": lineage["source_model_calls"] + saved_new_calls}}
