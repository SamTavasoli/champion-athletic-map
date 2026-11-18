"""Validate fresh text-only chat jobs and count their backend-rendered prompts.

This component uses the actual render-only result. It does not assume that
the recorded Go template is the server's active rendering path.
"""

import copy
import hashlib
import json


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def validate_request(request, native_control_tokens):
    required = {"model", "messages", "format", "stream", "options", "truncate", "shift"}
    if type(request) is not dict or set(request) != required:
        raise ValueError("Unexpected request fields; native tools, history, media and overrides are outside this contract")
    if (request["model"] != "llama3.1:8b" or request["format"] != "json"
            or request["stream"] is not False or request["truncate"] is not False or request["shift"] is not False):
        raise ValueError("Request differs from the text-only JSON and no-truncation policy")
    messages = request["messages"]
    if type(messages) is not list or len(messages) != 2:
        raise ValueError("Each job requires one system message and one user message")
    for message, role in zip(messages, ("system", "user")):
        if (type(message) is not dict or set(message) != {"role", "content"}
                or message["role"] != role or type(message["content"]) is not str):
            raise ValueError("Invalid message shape or role order")
        content = message["content"]
        if not content or content != content.strip():
            raise ValueError("Message boundaries must be nonblank and canonical; content is never silently trimmed")
        content.encode("utf-8", errors="strict")
        if any(token in content for token in native_control_tokens):
            raise ValueError("Literal model control tokens are not allowed inside message content")
    options = request["options"]
    if type(options) is not dict or set(options) != {"temperature", "seed", "num_ctx", "num_predict"}:
        raise ValueError("Decoding options are not the explicit development contract")
    if (type(options["temperature"]) not in (int, float) or options["temperature"] != 0
            or type(options["seed"]) is not int or options["seed"] != 42
            or type(options["num_ctx"]) is not int or options["num_ctx"] != 8192
            or type(options["num_predict"]) is not int or not 1 <= options["num_predict"] <= 2048):
        raise ValueError("Invalid context, output, seed or temperature settings")
    if len(canonical_bytes(request)) > 256 * 1024:
        raise ValueError("Request exceeds the technical byte limit; nothing was truncated")
    return True


def render_only_request(request, native_control_tokens):
    validate_request(request, native_control_tokens)
    result = copy.deepcopy(request)
    result["_debug_render_only"] = True
    return result


def extract_rendered_prompt(response):
    if type(response) is not dict or response.get("error"):
        raise ValueError("Invalid render-only backend response")
    debug = response.get("_debug_info")
    if type(debug) is not dict or type(debug.get("rendered_template")) is not str or not debug["rendered_template"]:
        raise ValueError("No confirmed render-only result; no replacement request is allowed")
    if (response.get("eval_count") not in (None, 0) or response.get("prompt_eval_count") not in (None, 0)
            or response.get("done") not in (None, False) or debug.get("image_count") not in (None, 0)):
        raise ValueError("Unexpected evaluation, completion or media in a render-only response")
    message = response.get("message")
    if message is not None:
        if (type(message) is not dict or message.get("content") not in (None, "")
                or message.get("thinking") not in (None, "") or message.get("tool_calls") not in (None, [])):
            raise ValueError("Unexpected generated content in a render-only response")
    return debug["rendered_template"]


def budget_from_count(body_tokens, output_reserve, *, context_tokens=8192, margin_tokens=256, boundary_reserve=2):
    values = (body_tokens, output_reserve, context_tokens, margin_tokens, boundary_reserve)
    if any(type(value) is not int for value in values) or body_tokens < 0 or output_reserve < 1:
        raise ValueError("Token budget values must be finite nonnegative integers with positive output capacity")
    if context_tokens != 8192 or margin_tokens != 256 or boundary_reserve != 2:
        raise ValueError("Budget policy differs from the versioned development candidate")
    ceiling = context_tokens - output_reserve - margin_tokens
    upper = body_tokens + boundary_reserve
    return {"status": "within_local_budget" if upper <= ceiling else "context_overflow",
            "rendered_body_tokens": body_tokens, "unverified_boundary_reserve": boundary_reserve,
            "local_input_tokens_with_boundary_reserve": upper, "output_reserve": output_reserve,
            "safety_margin": margin_tokens, "configured_context_tokens": context_tokens,
            "input_ceiling_after_output_and_margin": ceiling,
            "remaining_tokens_after_all_reserves": ceiling - upper,
            "backend_token_count_agreement_verified": False, "effective_backend_context_verified": False,
            "token_count_is_provisional": True, "operational_generation_ready": False}


def assess_rendered_prompt(request, rendered_prompt, encoder, native_control_tokens):
    validate_request(request, native_control_tokens)
    if type(rendered_prompt) is not str or not rendered_prompt:
        raise ValueError("A complete backend-rendered prompt is required")
    # We verify each role separately and count any backend-added system text.
    system, user = (message["content"] for message in request["messages"])
    remainder = rendered_prompt.removeprefix("<|begin_of_text|>")
    bodies = {}
    for role in ("system", "user"):
        header = "<|start_header_id|>" + role + "<|end_header_id|>"
        if not remainder.startswith(header):
            raise ValueError("Unrecognized role order in the returned prompt")
        body, boundary, remainder = remainder[len(header):].partition("<|eot_id|>")
        if not boundary or not body.startswith("\n\n") or any(token in body for token in native_control_tokens):
            raise ValueError("Unrecognized message boundary in the returned prompt")
        bodies[role] = body[2:]
    assistant_header = "<|start_header_id|>assistant<|end_header_id|>"
    if not remainder.startswith(assistant_header) or remainder[len(assistant_header):] not in ("", "\n", "\n\n"):
        raise ValueError("Unexpected assistant prefix in the returned prompt")
    if bodies["user"] != user or system not in bodies["system"]:
        raise ValueError("Submitted content was changed or omitted inside its own role section")
    system_at = bodies["system"].find(system)
    ids = encoder.encode(rendered_prompt, parse_special=True, add_bos=False, add_eos=False)
    result = budget_from_count(len(ids), request["options"]["num_predict"])
    result.update(request_sha256=hashlib.sha256(canonical_bytes(request)).hexdigest(),
                  rendered_prompt_sha256=hashlib.sha256(rendered_prompt.encode("utf-8")).hexdigest(),
                  exact_submitted_content_preserved=True,
                  rendered_bos_present=rendered_prompt.startswith("<|begin_of_text|>"),
                  backend_added_system_prefix=bodies["system"][:system_at],
                  backend_added_system_suffix=bodies["system"][system_at + len(system):],
                  counting_basis="native_encoder_over_complete_actual_backend_render_only_prompt")
    return result
