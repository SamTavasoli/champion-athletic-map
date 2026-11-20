"""Read local model metadata only when this separate check is selected."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

import pytest


pytestmark = [pytest.mark.real_backend, pytest.mark.requirement("30.11:local_identity")]
ROOT = Path(__file__).resolve().parents[2]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def test_recorded_local_runtime_and_model_are_available():
    if os.environ.get("CAM_RUN_REAL_BACKEND") != "1":
        pytest.skip("Select this metadata check explicitly with CAM_RUN_REAL_BACKEND=1.")
    config = json.loads((ROOT / "artifacts/language_model/integration_config.json").read_bytes())
    record = {"checked_at": datetime.now(timezone.utc).isoformat(), "kind": "local_metadata_only",
              "generation_requests": 0, "observations": {}, "status": "started"}
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        for endpoint in ("version", "tags", "ps"):
            request = Request("http://127.0.0.1:11434/api/" + endpoint)
            with opener.open(request, timeout=8) as response:
                payload = response.read(2 * 1024 * 1024 + 1)
            assert len(payload) <= 2 * 1024 * 1024
            record["observations"][endpoint] = json.loads(payload.decode("utf-8"))
        assert record["observations"]["version"]["version"] == config["runtime_version_from_saved_response"]
        models = [m for m in record["observations"]["tags"]["models"]
                  if m.get("name") == config["model"] or m.get("model") == config["model"]]
        assert len(models) == 1
        assert models[0]["digest"] == config["model_digest"]
        assert models[0]["details"]["quantization_level"] == config["quantization"]
        record["status"] = "passed"
    except Exception as error:
        record["status"] = "failed"
        record["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        path = ROOT / "results/testing/real_backend_checks.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
