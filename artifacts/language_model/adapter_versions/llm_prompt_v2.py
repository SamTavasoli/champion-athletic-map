"""Shared local chat adapter: fresh inputs, complete budgets, saved responses."""

import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


PROMPT_VERSION = "shared-json-instructions-2"
RESPONSE_FORMAT = 'Answer the athlete_request in the supplied profile. Return one JSON answer object, never a JSON schema. Keep supplied facts unchanged and ask about essential unknowns.\nUse response_type: plan, clarification, constraint_conflict, or outside_scope. Always include a short explanation.\nFor clarification, include a nonempty questions array covering the requested missing details. For constraint_conflict, include nonempty unresolved_issues. Omit weekly_schedule for non-plan replies.\nPlans need planning_window {start_date,end_date,timezone} and seven weekly_schedule entries. Each day needs date, activities, rest_arrangements. Each activity needs activity_id, description, duration_minutes, resources {equipment:[{name,quantity}],space,participants}, and relationship {kind,parent_activity_id}. Use separate_session with null parent, or part_of_activity referencing another activity. Unknown durations and resource values may be null. Source IDs are optional.\nExample of a clarification answer:\n{"response_type":"clarification","explanation":"I need a few details before planning.","questions":["Which days and times are available?"]}\nWrite the answer for the actual athlete request; the example illustrates the format only.'

MODEL = "llama3.1:8b"
DIGEST = "46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e"
TOKENIZER_SHA = "b289efbbd60fceb3e6bc38c19fcec0cb4229e5a7445df52fe82d2eb7fd277678"


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _save(path, value):
    data = value if type(value) is bytes else _bytes(value)
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _decode(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key in backend response")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("Nonfinite JSON number")
    value = json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject)
    if type(value) is not dict:
        raise ValueError("Backend response must be a JSON object")
    _bytes(value)
    return value


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class OllamaClient:
    def __init__(self, root, contracts_dir):
        self.root = Path(root).resolve()
        folder = Path(contracts_dir)
        folder = folder if folder.is_absolute() else self.root / folder
        self.contracts = folder.resolve()
        if not self.contracts.is_relative_to(self.root):
            raise ValueError("Contract directory must be inside the project")
        summary = _decode((self.contracts / "step24_7_shared_contract_summary.json").read_bytes())
        if summary.get("status") != "shared_io_contract_candidates_software_checked":
            raise ValueError("Expected the checked Step 24-7 contracts")
        if importlib.metadata.version("jsonschema") != summary["jsonschema_version"]:
            raise ValueError("JSON Schema package version changed")
        self.bound = summary["output_hashes"]
        self.public = self._module(self.contracts / "public_input.py")
        self.response = self._module(self.contracts / "response_contract.py")
        self.input_schema = _decode(self._read(self.contracts / "public_profile_record_schema.json"))
        self.response_schema = _decode(self._read(self.contracts / "planner_response_schema.json"))
        self.bound.update(_decode(self._read(self.contracts / "verified_inputs.json"))["project_file_sha256"])
        manifests = [name for name, digest in self.bound.items() if name.endswith("/tokenizer_manifest.json") and digest == TOKENIZER_SHA]
        if len(manifests) != 1:
            raise ValueError("Pinned native tokenizer manifest is unavailable")
        tokenizer_path = self.root / manifests[0]
        manifest = _decode(self._read(tokenizer_path))
        for name, digest in manifest["payload_hashes"].items():
            self.bound[(tokenizer_path.parent / name).relative_to(self.root).as_posix()] = digest
        source = manifest["source_native_metadata"]
        if self.bound.get(source["relative_path"]) != source["sha256"]:
            raise ValueError("Native model metadata binding differs")
        self.native = _decode(self._read(self.root / source["relative_path"]))
        contract = _decode(self._read(tokenizer_path.parent / "tokenizer_contract.json"))
        for name, version in contract["package_versions"].items():
            if importlib.metadata.version(name) != version:
                raise ValueError("Tokenizer package version changed: " + name)
        tokenizer = self._module(tokenizer_path.parent / "native_tokenizer.py")
        self.encoder = tokenizer.NativeTokenizerCandidate(self.native["model_info"], self._read(tokenizer_path.parent / "normal_bpe_tokenizer.json").decode("utf-8"))
        self.controls = tuple(tokenizer.inspect_native_tables(self.native["model_info"])["special"])
        self.preflight = self._module(self.root / "artifacts/language_model/prompt_preflight/preflight_eb1720a4533bf163/prompt_preflight.py")
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _read(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Dependency path leaves the project")
        data = path.read_bytes()
        if _sha(data) != self.bound.get(path.relative_to(self.root).as_posix()):
            raise ValueError("Saved dependency changed: " + path.name)
        return data

    def _module(self, path):
        data = self._read(path)
        spec = importlib.util.spec_from_loader("champion_" + _sha(data)[:16], loader=None)
        module = importlib.util.module_from_spec(spec)
        exec(compile(data, str(path), "exec"), module.__dict__)
        return module

    def _http(self, endpoint, payload=None, timeout=8, raw_path=None):
        request = Request("http://127.0.0.1:11434" + endpoint, data=None if payload is None else _bytes(payload),
                          headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                data = response.read(2 * 1024 * 1024 + 1)
        except HTTPError as error:
            if raw_path is not None:
                _save(raw_path, error.read(2 * 1024 * 1024 + 1))
            raise RuntimeError("Ollama HTTP error " + str(error.code)) from None
        if raw_path is not None:
            _save(raw_path, data)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError("Backend response exceeded the size limit")
        return _decode(data)

    def _identity(self):
        version = self._http("/api/version").get("version")
        rows = [row for row in self._http("/api/tags").get("models", []) if row.get("name") == MODEL or row.get("model") == MODEL]
        if version != "0.40.16" or len(rows) != 1 or rows[0].get("digest") != DIGEST or rows[0].get("details", {}).get("quantization_level") != "Q4_K_M":
            raise ValueError("Recorded Ollama runtime or model identity changed")
        shown = self._http("/api/show", {"model": MODEL, "verbose": False})
        if shown.get("template") != self.native.get("template") or shown.get("remote_host") or shown.get("remote_model"):
            raise ValueError("Model template or local execution route changed")
        for key in ("system", "messages", "parameters", "renderer", "parser", "template_source"):
            if shown.get(key) != self.native.get(key):
                raise ValueError("Model defaults changed: " + key)
        return {"version": version, "model": rows[0]}

    def generate(self, public_record, instructions, call_id):
        if type(call_id) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,80}", call_id) is None:
            raise ValueError("Use a simple stable call identifier")
        prepared = self.public.prepare_public_input(public_record, self.input_schema)
        payload = {"model": MODEL, "stream": False, "format": "json", "truncate": False, "shift": False,
                   "messages": [{"role": "system", "content": instructions + "\n\n" + RESPONSE_FORMAT},
                                {"role": "user", "content": prepared["model_visible_json"]}],
                   "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 2048}}
        self.preflight.validate_request(payload, self.controls)
        request_sha = _sha(_bytes(payload))
        folder = self.root / "results/integration/model_calls" / call_id
        if (folder / "result.json").is_file():
            previous = _decode((folder / "result.json").read_bytes())
            saved_request = _decode((folder / "request.json").read_bytes())
            if (previous.get("request_sha256") != request_sha or saved_request.get("input_audit") != prepared["audit"]
                    or previous.get("model_digest") != DIGEST):
                raise ValueError("Call ID already belongs to a different request")
            return {**previous, "cached": True}
        if folder.exists():
            raise RuntimeError("This call has an incomplete saved attempt; automatic resubmission is disabled")
        if (self.root / "results/integration/chat_compatibility/active_step24_5_run").exists():
            raise RuntimeError("An earlier chat check has an unresolved request")
        folder.parent.mkdir(parents=True, exist_ok=True)
        active = folder.parent / "active_call"
        active.mkdir(exist_ok=False)
        folder.mkdir()
        _save(active / "owner.json", {"call_id": call_id, "request_sha256": request_sha})
        _save(folder / "request.json", {"request": payload, "input_audit": prepared["audit"], "prompt_version": PROMPT_VERSION})
        phase, completed = "metadata", False
        result = {"status": "failed", "response_type": None, "format_valid": False, "completion_valid": False,
                  "response": None, "usage": {}, "context": {}, "runtime": {}, "request_sha256": request_sha,
                  "call_id": call_id, "model_digest": DIGEST, "prompt_version": PROMPT_VERSION,
                  "cached": False, "saved_path": str(folder), "operational_generation_ready": False}
        try:
            result["runtime"] = self._identity()
            phase = "rendering"
            render_response = self._http("/api/chat", self.preflight.render_only_request(payload, self.controls), 60, folder / "render_response.json")
            rendered = self.preflight.extract_rendered_prompt(render_response)
            phase = "rendered"
            _save(folder / "rendered_prompt.txt", rendered.encode("utf-8"))
            budget = self.preflight.assess_rendered_prompt(payload, rendered, self.encoder, self.controls)
            result["context"] = budget
            if budget["status"] != "within_local_budget":
                raise ValueError("Complete request exceeds the reserved context budget")
            runners = [row for row in self._http("/api/ps").get("models", []) if row.get("digest") == DIGEST]
            if len(runners) != 1 or type(runners[0].get("context_length")) is not int or runners[0]["context_length"] < 8192:
                raise ValueError("Requested model context is unavailable")
            result["runtime"]["runner"] = runners[0]
            result["runtime"]["before_generation"] = self._identity()
            self.public.verify_prepared_input(prepared)
            _save(folder / "generation_pending.json", {"call_id": call_id, "request_sha256": request_sha})
            phase = "generation"
            answer = self._http("/api/chat", payload, 120, folder / "backend_response.json")
            completed = answer.get("done") is True
            message = answer.get("message", {})
            valid = (completed and answer.get("model") == MODEL and answer.get("done_reason") == "stop"
                     and not answer.get("error") and not answer.get("remote_host") and not answer.get("remote_model")
                     and type(message) is dict and message.get("role") == "assistant" and type(message.get("content")) is str
                     and message.get("thinking") in (None, "") and message.get("tool_calls") in (None, [])
                     and message.get("images") in (None, []) and answer.get("_debug_info") is None)
            result["completion_valid"] = bool(valid)
            if type(message) is dict and type(message.get("content")) is str:
                parsed = self.response.parse_response_text(message["content"], self.response_schema)
                result["response"] = self.public.preserve_response_record(prepared, parsed)
                result["format_valid"] = parsed["parse_valid"]
                result["response_type"] = parsed["parsed_object"].get("response_type") if type(parsed["parsed_object"]) is dict else None
            result["usage"] = {key: answer.get(key) for key in ("prompt_eval_count", "prompt_eval_cached_count", "eval_count", "total_duration", "load_duration")}
            count = answer.get("prompt_eval_count")
            result["usage"]["observed_input_offset"] = count - budget["rendered_body_tokens"] if type(count) is int else None
            result["usage"]["matches_prior_offset"] = result["usage"]["observed_input_offset"] == 1
            cached, output = answer.get("prompt_eval_cached_count"), answer.get("eval_count")
            usage_valid = (type(count) is int and 0 < count <= budget["input_ceiling_after_output_and_margin"]
                           and type(output) is int and 0 < output <= 2048
                           and (cached is None or type(cached) is int and 0 <= cached <= count))
            result["usage"]["within_configured_limits"] = usage_valid
            valid = valid and usage_valid
            result["completion_valid"] = bool(valid)
            result["status"] = "returned" if valid and result["format_valid"] else "failed" if completed else "unresolved"
            if completed and not valid:
                result["error"] = "Reply completion or token usage needs review; the saved response was retained."
        except BaseException as error:
            result["status"] = "unresolved" if phase in ("rendering", "generation") and not completed else "failed"
            result["error"] = type(error).__name__ + ": " + str(error)
        _save(folder / "result.json", result)
        if result["status"] != "unresolved":
            (active / "owner.json").unlink()
            active.rmdir()
        return result
