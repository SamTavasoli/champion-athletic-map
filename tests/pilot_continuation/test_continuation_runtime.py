"""Check that the amendment changes only reversible review representation."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load(name):
    path = ROOT / "src/champion_athletic_map" / (name + ".py")
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location("runtime_test_" + name, path))
    module.__spec__.loader.exec_module(module)
    return module


RUNTIME = load("continuation_runtime")
CODEC = load("review_encoding")


class OriginalRole:
    def __init__(self, root=None, client=None, shared=None, integration=None):
        self.shared = shared or SimpleNamespace(_decode=lambda data: json.loads(data), _sha=RUNTIME.sha)
        self.client = client or SimpleNamespace(encoder=SimpleNamespace(encode=lambda text, parse_special=False: list(range(len(text) // 4))))
        self.calls = []

    def _budget_view(self, payload):
        self.budget_payload = deepcopy(payload)

    def prepare_request(self, record, packet, instructions, call_id=None, **kwargs):
        self.calls.append((deepcopy(record), deepcopy(packet), instructions, call_id, deepcopy(kwargs)))
        view = {"athlete_input": deepcopy(record["input"]), "reference_data": deepcopy(packet),
            "candidate": {"raw_text": "exact original candidate 🏀"}, "specialist_notes": [{"text": "exact note"}],
            "evaluator_assessment": {"assessment_complete": True, "issues": []}, "check_results": deepcopy(kwargs["checks"])}
        payload = {"model": "saved-test-model", "messages": [{"role": "system", "content": instructions},
            {"role": "user", "content": RUNTIME.canonical(view)}], "options": {"num_ctx": 8192, "num_predict": 2048},
            "format": {"type": "object"}, "truncate": False, "shift": False, "stream": False}
        return {"public": record["input"]}, payload, {"stage": kwargs["stage"], "output_limit": 2048}


def sample_checks():
    return {"execution_status": "completed", "columns": ["check_ids", "status", "reason", "observed"],
        "findings": [[["check_" + str(i)], "unknown", "The entire repeated explanation remains present.",
            {"known_active_days": i, "policy": "shared-policy", "complete": True,
             "upper_bound_basis": "all returned roots count as relevant training", "sport_days": ["2026-11-16", "2026-11-18"]}]
            for i in range(8)]}


def test_request_encoding_preserves_every_original_field_limits_and_arguments():
    role = RUNTIME.encoded_role_type(OriginalRole, CODEC)()
    original = OriginalRole()
    public = {"profile_id": "test:continuation", "input": {"athlete_request": "Keep exact newlines\nand 🏀", "participants_available": None}}
    packet = {"references": [{"complete_text": "Full, unchanged reference."}]}
    kwargs = {"stage": "revision", "checks": sample_checks()}
    before, old_payload, old_config = original.prepare_request(public, packet, "Original instructions", "id", **kwargs)
    prepared, payload, config = role.prepare_request(public, packet, "Original instructions", "id", **kwargs)
    view = json.loads(payload["messages"][1]["content"])
    view["check_results"] = CODEC.decode_checks(view["check_results"])
    assert RUNTIME.canonical(view) == RUNTIME.canonical(json.loads(old_payload["messages"][1]["content"]))
    assert prepared == before and role.calls == original.calls
    assert {key: value for key, value in payload.items() if key != "messages"} == {key: value for key, value in old_payload.items() if key != "messages"}
    assert payload["messages"][0]["content"] == "Original instructions\n\n" + CODEC.ENCODING_NOTICE
    assert config["lossless_review_roundtrip_verified"] is True
    assert config["stage"] == old_config["stage"] and config["output_limit"] == 2048
    assert role.budget_payload == payload
    assert config["message_sha256"] == [RUNTIME.sha(row["content"].encode()) for row in payload["messages"]]


def test_corrupted_decoder_blocks_preparation_before_any_transport():
    bad = SimpleNamespace(encode_checks=CODEC.encode_checks, decode_checks=lambda encoded: {},
        ENCODING_VERSION="corrupted-test-only", ENCODING_NOTICE="test")
    role = RUNTIME.encoded_role_type(OriginalRole, bad)()
    with pytest.raises(ValueError, match="restore every original check"):
        role.prepare_request({"input": {}}, {}, "Original", stage="revision", checks=sample_checks())
    assert not hasattr(role, "budget_payload")


pytestmark = pytest.mark.requirement("31:continuation-runtime-encoding")
