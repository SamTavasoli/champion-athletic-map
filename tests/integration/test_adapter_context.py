"""Exercise saved chat attempts, complete-request budgets, and lossless quoting."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import MethodType

import pytest


ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "artifacts/language_model/shared_contracts/contracts_3293242853ce2cf7"
PREFLIGHT = ROOT / "artifacts/language_model/prompt_preflight/preflight_eb1720a4533bf163/prompt_preflight.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load("step30_saved_adapter", ROOT / "src/champion_athletic_map/llm.py")
preflight = load("step30_complete_budget", PREFLIGHT)
public_input = load("step30_adapter_public_input", CONTRACTS / "public_input.py")
response_contract = load("step30_adapter_response", CONTRACTS / "response_contract.py")
encoding = load("step30_candidate_encoding", ROOT / "src/champion_athletic_map/context_encoding.py")
CONTROLS = ("<|begin_of_text|>", "<|start_header_id|>", "<|end_header_id|>", "<|eot_id|>")


class FixedCountEncoder:
    """An authored count exercises arithmetic; it is not a tokenizer measurement."""

    def __init__(self, count=30):
        self.count = count
        self.calls = []

    def encode(self, text, **options):
        self.calls.append((text, options))
        return list(range(self.count))


def render(request, *, system_prefix="", system_suffix="", user=None):
    system, supplied = [message["content"] for message in request["messages"]]
    return ("<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n"
            + system_prefix + system + system_suffix + "<|eot_id|>"
            + "<|start_header_id|>user<|end_header_id|>\n\n"
            + (supplied if user is None else user) + "<|eot_id|>"
            + "<|start_header_id|>assistant<|end_header_id|>\n\n")


def request_fixture():
    return {"model": adapter.MODEL, "stream": False, "format": "json", "truncate": False, "shift": False,
            "messages": [{"role": "system", "content": "Use the supplied facts. Café Ω 中文 🏀"},
                         {"role": "user", "content": '{"athlete_request":"Ask for missing availability.\\nKeep uncertainty."}'}],
            "options": {"temperature": 0, "seed": 42, "num_ctx": 8192, "num_predict": 2048}}


VALID_TEXT = json.dumps({"response_type": "clarification", "explanation": "Availability is needed.",
                        "questions": ["Which days and times are available?"]})


def client_fixture(root, *, content=VALID_TEXT, done=True, finish="stop", generation_error=None, body_tokens=30):
    """Use actual generate/parsers/preflight while replacing only identity and I/O."""
    client = adapter.OllamaClient.__new__(adapter.OllamaClient)
    client.root = root
    client.public = public_input
    client.response = response_contract
    client.response_schema = response_contract.build_response_schema()
    client.output_schema = adapter._schema_order(adapter._generation_schema(client.response_schema))
    client.preflight = preflight
    client.encoder = FixedCountEncoder(body_tokens)
    client.controls = CONTROLS
    client.http_calls = []

    def prepare(self, record, instructions, **kwargs):
        facts = deepcopy(record)
        text = public_input.canonical_json(facts)
        prepared = {"schema_version": "step24-prepared-public-input-1",
                    "audit": {"profile_id": "authored-adapter-case", "profile_schema_version": "athlete-profile-input-1",
                              "public_input_sha256": hashlib.sha256(text.encode()).hexdigest()},
                    "public_input": facts, "model_visible_json": text}
        payload = request_fixture()
        payload["messages"] = [{"role": "system", "content": instructions}, {"role": "user", "content": text}]
        payload["format"] = self.output_schema
        return prepared, payload, {"planner_version": None, "reference_packet_id": None, "fixture": "authored-I/O-only"}

    def http(self, endpoint, payload=None, timeout=8, raw_path=None):
        self.http_calls.append((endpoint, deepcopy(payload)))
        if endpoint == "/api/ps":
            answer = {"models": [{"digest": adapter.DIGEST, "context_length": 8192}]}
        elif endpoint == "/api/chat" and payload.get("_debug_render_only") is True:
            answer = {"_debug_info": {"rendered_template": render(payload)}}
        elif endpoint == "/api/chat":
            if generation_error is not None:
                raise generation_error
            answer = {"model": adapter.MODEL, "done": done, "done_reason": finish,
                      "message": {"role": "assistant", "content": content},
                      "prompt_eval_count": body_tokens + 1, "eval_count": 18,
                      "total_duration": 123, "load_duration": 4}
        else:
            raise AssertionError("Unexpected scripted endpoint: " + endpoint)
        if raw_path is not None:
            adapter._save(raw_path, adapter._wire_bytes(answer))
        return answer

    client.prepare_request = MethodType(prepare, client)
    client._identity = lambda: {"version": "scripted-identity", "fixture_only": True}
    client._http = MethodType(http, client)
    return client


def generation_calls(client):
    return [payload for endpoint, payload in client.http_calls
            if endpoint == "/api/chat" and payload.get("_debug_render_only") is not True]


@pytest.mark.requirement("30.8.saved_response_no_resubmission")
def test_valid_saved_result_is_reused_without_another_backend_attempt(tmp_path):
    client = client_fixture(tmp_path)
    record = {"athlete_request": "Ask for the missing availability.", "availability": None}
    first = client.generate(record, "Preserve unknown facts.", "authored_valid")
    assert first["status"] == "returned" and first["completion_valid"] and first["format_valid"]
    folder = tmp_path / "results/integration/model_calls/authored_valid"
    assert json.loads((folder / "backend_response.json").read_bytes())["message"]["content"] == VALID_TEXT
    assert first["response"]["authoritative_public_input"] == record
    assert first["response"]["semantic_correctness_verified"] is False
    assert not (folder.parent / "active_call").exists()
    calls = deepcopy(client.http_calls)
    second = client.generate(record, "Preserve unknown facts.", "authored_valid")
    assert second["cached"] is True and second["request_sha256"] == first["request_sha256"]
    assert client.http_calls == calls and len(generation_calls(client)) == 1


@pytest.mark.requirement("30.8.saved_request_identity")
def test_a_completed_call_id_cannot_be_reused_for_changed_input(tmp_path):
    client = client_fixture(tmp_path)
    client.generate({"athlete_request": "First request."}, "Preserve supplied facts.", "authored_identity")
    calls = deepcopy(client.http_calls)
    with pytest.raises(ValueError, match="different request"):
        client.generate({"athlete_request": "Changed request."}, "Preserve supplied facts.", "authored_identity")
    assert client.http_calls == calls


@pytest.mark.parametrize("content,finish", [("{not-json", "stop"), ('{"response_type":"plan"', "length")])
@pytest.mark.requirement("30.8.completed_content_no_retry")
def test_malformed_or_truncated_completed_content_is_retained_without_retry(tmp_path, content, finish):
    client = client_fixture(tmp_path, content=content, finish=finish)
    result = client.generate({"athlete_request": "Ask for missing information."}, "Keep unknown values.", "authored_bad_reply")
    assert result["status"] == "failed" and result["format_valid"] is False
    assert result["response"]["model_output"]["raw_text"] == content
    assert len(generation_calls(client)) == 1
    if finish == "length":
        assert result["completion_valid"] is False and "reply limit" in result["error"]
    calls = deepcopy(client.http_calls)
    saved = client.generate({"athlete_request": "Ask for missing information."}, "Keep unknown values.", "authored_bad_reply")
    assert saved["cached"] is True and saved["status"] == "failed"
    assert client.http_calls == calls


@pytest.mark.requirement("30.8.uncertain_completion_lock")
def test_generation_timeout_keeps_the_attempt_unresolved_and_blocks_new_submission(tmp_path):
    client = client_fixture(tmp_path, generation_error=TimeoutError("Authored post-submission timeout"))
    facts = {"athlete_request": "Ask for missing information."}
    result = client.generate(facts, "Keep unknown values.", "authored_timeout")
    assert result["status"] == "unresolved" and "TimeoutError" in result["error"]
    folder = tmp_path / "results/integration/model_calls/authored_timeout"
    assert (folder / "generation_pending.json").is_file()
    assert (folder.parent / "active_call/owner.json").is_file()
    assert not (folder / "backend_response.json").exists()
    replay = client.generate(facts, "Keep unknown values.", "authored_timeout")
    assert replay["cached"] is True and replay["status"] == "unresolved"
    with pytest.raises(FileExistsError):
        client.generate(facts, "Keep unknown values.", "authored_new_job")
    assert len(generation_calls(client)) == 1


@pytest.mark.requirement("30.8.context_overflow_before_generation")
def test_over_budget_complete_prompt_stops_before_generation(tmp_path):
    client = client_fixture(tmp_path, body_tokens=5887)
    result = client.generate({"athlete_request": "Ask for missing information."}, "Keep unknown values.", "authored_overflow")
    assert result["status"] == "failed" and result["context"]["status"] == "context_overflow"
    assert result["context"]["local_input_tokens_with_boundary_reserve"] == 5889
    assert result["context"]["input_ceiling_after_output_and_margin"] == 5888
    assert generation_calls(client) == []
    folder = tmp_path / "results/integration/model_calls/authored_overflow"
    assert (folder / "rendered_prompt.txt").is_file()
    assert not (folder / "generation_pending.json").exists()
    assert not (folder.parent / "active_call").exists()


@pytest.mark.parametrize("data", [b'{"count":1,"count":2}', b'{"count":NaN}', b'{"count":Infinity}', b'[]', b'\xff'])
@pytest.mark.requirement("30.4.strict_backend_json")
def test_backend_decoder_rejects_duplicate_nonfinite_nonobject_and_invalid_utf8(data):
    with pytest.raises((ValueError, UnicodeError)):
        adapter._decode(data)


@pytest.mark.parametrize("body,status,remaining", [(5885, "within_local_budget", 1),
                                                  (5886, "within_local_budget", 0),
                                                  (5887, "context_overflow", -1)])
@pytest.mark.requirement("30.8.complete_request_budget_boundary")
def test_complete_request_budget_below_equal_and_above_the_hand_worked_ceiling(body, status, remaining):
    result = preflight.budget_from_count(body, 2048)
    assert result["status"] == status
    assert result["input_ceiling_after_output_and_margin"] == 5888
    assert result["remaining_tokens_after_all_reserves"] == remaining
    assert result["token_count_is_provisional"] is True
    assert result["backend_token_count_agreement_verified"] is False
    assert result["effective_backend_context_verified"] is False
    assert result["operational_generation_ready"] is False


@pytest.mark.parametrize("bad_count", [-1, True, 1.5, float("nan")])
@pytest.mark.requirement("30.4.invalid_budget_values")
def test_token_budget_rejects_invalid_counts(bad_count):
    with pytest.raises(ValueError):
        preflight.budget_from_count(bad_count, 2048)


@pytest.mark.requirement("30.8.rendered_role_content")
def test_complete_render_preserves_both_roles_and_counts_backend_added_system_text():
    request = request_fixture()
    prompt = render(request, system_prefix="Backend notice.\n", system_suffix="\nEnd notice.")
    encoder = FixedCountEncoder(77)
    result = preflight.assess_rendered_prompt(request, prompt, encoder, CONTROLS)
    assert result["exact_submitted_content_preserved"] is True
    assert result["backend_added_system_prefix"] == "Backend notice.\n"
    assert result["backend_added_system_suffix"] == "\nEnd notice."
    assert result["rendered_body_tokens"] == 77 and result["token_count_is_provisional"] is True
    assert encoder.calls == [(prompt, {"parse_special": True, "add_bos": False, "add_eos": False})]


@pytest.mark.parametrize("damage", ["changed_user", "missing_user_header", "missing_system_content", "extra_assistant_content"])
@pytest.mark.requirement("30.8.rendered_role_content")
def test_unrecognized_or_changed_complete_render_is_rejected_before_counting(damage):
    request = request_fixture()
    prompt = render(request)
    if damage == "changed_user":
        prompt = render(request, user="Another athlete's request.")
    elif damage == "missing_user_header":
        prompt = prompt.replace("<|start_header_id|>user<|end_header_id|>", "")
    elif damage == "missing_system_content":
        prompt = prompt.replace(request["messages"][0]["content"], "Omitted instructions.")
    else:
        prompt += "Unexpected answer text."
    encoder = FixedCountEncoder()
    with pytest.raises(ValueError):
        preflight.assess_rendered_prompt(request, prompt, encoder, CONTROLS)
    assert encoder.calls == []


@pytest.mark.requirement("30.8.render_only_not_generation")
def test_render_only_response_cannot_disguise_generated_content():
    response = {"_debug_info": {"rendered_template": "a complete quoted prompt"}, "eval_count": 1}
    with pytest.raises(ValueError, match="Unexpected evaluation"):
        preflight.extract_rendered_prompt(response)


def candidate_fixture(kind):
    shared = {"equipment": None, "space": "Café Ω 中文 🏀\nHalf court", "participants": 2}
    first = {"activity_id": "first", "description": "Basketball\nPassing 🏀", "duration_minutes": 15,
             "resources": shared, "relationship": {"kind": "separate_session", "parent_activity_id": None},
             "timing": {"start_time": "17:30", "end_time": "17:45"}}
    second = deepcopy(first)
    second["activity_id"] = "second"
    if kind == "heterogeneous":
        first.pop("timing")
        second["timing"] = None
        second["evidence_refs"] = []
    days = [{"date": "2026-11-16", "activities": [first], "rest_arrangements": None},
            {"date": "2026-11-17", "activities": [second], "rest_arrangements": "Café\nRecovery 🏀"},
            {"date": "2026-11-18", "activities": [], "rest_arrangements": False},
            {"date": "2026-11-19", "activities": [], "rest_arrangements": 0}]
    if kind == "empty":
        for day in days:
            day["activities"] = []
    return {"candidate_id": "authored-candidate", "format_valid": kind != "heterogeneous",
            "parsed_object": {"response_type": "plan", "explanation": "Literal values remain unchanged.",
                              "questions": [], "weekly_schedule": days, "food_facts": None}}


@pytest.mark.parametrize("kind", ["uniform", "heterogeneous", "empty"])
@pytest.mark.requirement("30.8.lossless_candidate_context")
def test_calendar_table_round_trip_preserves_unicode_null_absence_and_value_types(kind):
    original = candidate_fixture(kind)
    before = json.dumps(original, ensure_ascii=False, sort_keys=True)
    quoted = encoding.encode_candidate_view(original)
    restored = encoding.decode_candidate_view(quoted)
    assert "calendar_table" in quoted
    assert json.dumps(restored, ensure_ascii=False, sort_keys=True) == before
    assert json.dumps(original, ensure_ascii=False, sort_keys=True) == before
    if kind == "heterogeneous":
        rows = restored["parsed_object"]["weekly_schedule"]
        assert "timing" not in rows[0]["activities"][0]
        assert rows[1]["activities"][0]["timing"] is None
    rests = restored["parsed_object"]["weekly_schedule"]
    assert rests[2]["rest_arrangements"] is False
    assert type(rests[3]["rest_arrangements"]) is int


@pytest.mark.requirement("30.8.lossless_candidate_context")
def test_unrecognized_candidate_shape_is_copied_without_encoding_or_field_loss():
    view = {**candidate_fixture("uniform"), "extra_field": "Keep the original shape."}
    quoted = encoding.encode_candidate_view(view)
    assert quoted == view and "calendar_table" not in quoted and quoted is not view
    quoted["parsed_object"]["explanation"] = "Changed copy."
    assert view["parsed_object"]["explanation"] == "Literal values remain unchanged."
