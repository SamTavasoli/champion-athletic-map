"""Exercise readiness reporting with authored files and a scripted metadata service."""

from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import pytest
from unittest.mock import patch
from urllib.error import HTTPError


HERE = Path(__file__).resolve().parents[2] / "src/champion_athletic_map"
spec = importlib.util.spec_from_file_location("pilot_readiness_under_test", HERE / "pilot_readiness.py")
readiness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readiness)


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="step31_readiness_fixture_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "results/pilot/preparation_checks/authored"

        def put(relative, value):
            data = value if isinstance(value, bytes) else packed(value)
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return sha(data)

        self.put = put
        self.native = {"template": "Authored local template", "system": "", "messages": [],
            "parameters": "Authored defaults", "renderer": None, "parser": None, "template_source": None}
        native_relative = "results/integration/runtime_candidates/authored/native_model_metadata.json"
        native_sha = put(native_relative, self.native)
        tokenizer_payloads = {"native_tokenizer.py": put(readiness.TOKENIZER + "/native_tokenizer.py", b"# Authored source, never imported.\n"),
            "normal_bpe_tokenizer.json": put(readiness.TOKENIZER + "/normal_bpe_tokenizer.json", {"authored": "hash-only fixture"})}
        manifest_sha = put(readiness.TOKENIZER + "/tokenizer_manifest.json", {
            "model_digest": readiness.DIGEST,
            "payload_hashes": tokenizer_payloads,
            "source_native_metadata": {"relative_path": native_relative, "sha256": native_sha}})
        self.manifest_patch = patch.object(readiness, "TOKENIZER_MANIFEST_SHA", manifest_sha)
        self.manifest_patch.start()
        self.addCleanup(self.manifest_patch.stop)

        food_hashes = {"usda_food_reference.py": {"sha256": put(readiness.FOOD + "/usda_food_reference.py", b"# Authored food helper fixture.\n")},
            "usda_foods.csv": {"sha256": put(readiness.FOOD + "/usda_foods.csv", b"fdc_id,description\n1,Authored food\n")}}
        food_summary = readiness.FOOD + "/step14_food_reference_summary.json"
        food_sha = put(food_summary, {"artifacts": food_hashes})
        self.environment = {"python_version": "3.12.6", "python_full_version": "Authored Python build",
            "platform_system": "Authored OS", "platform_machine": "Authored CPU", "versions": {"authored-package": "1.0"}}
        self.cache = self.root / "authored_model_cache"
        cache_file = self.cache / "model.safetensors"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_bytes(b"Not a model; authored hash-only fixture.")
        query_sha = put(readiness.QUERY + "/query_runtime_config.json", {
            "runtime_environment": self.environment,
            "model_source_manifest": {"revision": "a" * 40,
                "files": [{"relative_path": "model.safetensors", "sha256": sha(cache_file.read_bytes())}]}})
        dataset_relative = "data/unified/v1/champions_unified_dataset.csv"
        dataset_sha = put(dataset_relative, b"record_type,text\nreference,Authored unit\n")
        builder_sha = put("src/champion_athletic_map/reference_context.py", b"# Authored builder fixture.\n")
        put("artifacts/planners/shared_reference_source_config.json", {
            "source_sha256": {food_summary: food_sha, dataset_relative: dataset_sha,
                              readiness.QUERY + "/query_runtime_config.json": query_sha},
            "builder_sha256": {"src/champion_athletic_map/reference_context.py": builder_sha}})
        self.step30 = {"schema_version": "step30-testing-summary-1", "routine_suite": "passed", "pytest_exit_code": 0,
            "collected_tests": 248, "executed_tests": 248, "collection_errors": [], "source_files_changed": [],
            "outcomes": {"passed": 248, "failed": 0, "error": 0, "skipped": 0, "expected_failure": 0, "not_executed": 0},
            "source_sha256": {"src/authored_probe.py": put("src/authored_probe.py", b"# Authored source.\n")},
            "test_sha256": {"tests/authored_probe.py": put("tests/authored_probe.py", b"# Authored test.\n")}}
        put("results/step30_testing_summary.json", self.step30)
        self.calls = []
        self.replies = {"/api/version": {"version": readiness.RUNTIME},
            "/api/tags": {"models": [{"name": readiness.MODEL, "digest": readiness.DIGEST,
                                      "details": {"quantization_level": readiness.QUANTIZATION}}]},
            "/api/show": deepcopy(self.native), "/api/ps": {"models": []}}

    def transport(self, endpoint, payload, timeout):
        self.calls.append((endpoint, payload, timeout))
        value = self.replies[endpoint]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, bytes) else packed(value)

    def check(self):
        return readiness.check_local_readiness(self.root, self.output, http_request=self.transport,
            environment=self.environment, model_cache_root=self.cache)

    @staticmethod
    def rows(result):
        return {row["check_id"]: row for row in result["checks"]}

    def test_matching_files_and_metadata_are_recorded_without_loading_or_generation(self):
        result = self.check()
        rows = self.rows(result)
        self.assertTrue(all(row["status"] == "passed" for key, row in rows.items() if key != "resident_context_observation"))
        self.assertEqual(rows["resident_context_observation"]["status"], "pending")
        self.assertEqual([call[0] for call in self.calls], ["/api/version", "/api/tags", "/api/show", "/api/ps"])
        self.assertEqual(self.calls[2][1], {"model": readiness.MODEL, "verbose": False})
        self.assertEqual(result["metadata_requests"], 4)
        self.assertEqual((result["model_generation_calls"], result["query_encoder_processes"], result["model_or_index_loads"]), (0, 0, 0))
        self.assertEqual(result["local_model_status"], "matched_metadata")
        self.assertEqual(result["reference_files_status"], "verified")
        self.assertFalse(result["generation_runtime_verified"])
        self.assertFalse(result["operational_generation_ready"])
        events = json.loads((self.output / "metadata_requests.json").read_bytes())
        self.assertTrue(all(e["evidence_kind"] == "injected_test_transport" for e in events))
        for event in events:
            data = (self.root / event["raw_response_path"]).read_bytes()
            self.assertEqual(sha(data), event["raw_response_sha256"])
        self.assertEqual(json.loads((self.output / "readiness_checks.json").read_bytes()), result)

    def test_a_resident_matching_context_is_an_observation_not_generation_verification(self):
        self.replies["/api/ps"] = {"models": [{"digest": readiness.DIGEST, "context_length": 8192, "size_vram": 123}]}
        result = self.check()
        self.assertEqual(self.rows(result)["resident_context_observation"]["status"], "passed")
        self.assertFalse(result["generation_runtime_verified"])

    def test_skipped_routine_cases_do_not_establish_completed_integration(self):
        self.step30["outcomes"].update(passed=247, skipped=1)
        self.put("results/step30_testing_summary.json", self.step30)
        rows = readiness.check_step30(self.root)
        self.assertEqual(rows[0]["status"], "blocked")

    def test_step30_source_change_is_reported(self):
        self.put("src/authored_probe.py", b"# Different authored source.\n")
        rows = {r["check_id"]: r for r in readiness.check_step30(self.root)}
        self.assertEqual(rows["step30_source_bindings"]["status"], "blocked")
        self.assertEqual(rows["step30_test_bindings"]["status"], "passed")

    def test_missing_reference_data_does_not_suppress_other_findings(self):
        (self.root / "data/unified/v1/champions_unified_dataset.csv").unlink()
        result = self.check()
        self.assertEqual(self.rows(result)["reference_source_files"]["status"], "blocked")
        self.assertEqual(result["reference_files_status"], "blocked")
        self.assertEqual(result["local_model_status"], "matched_metadata")
        self.assertEqual(result["metadata_requests"], 4)

    def test_missing_native_tokenizer_file_is_detected_without_loading_it(self):
        (self.root / readiness.TOKENIZER / "normal_bpe_tokenizer.json").unlink()
        result = self.check()
        self.assertEqual(self.rows(result)["native_tokenizer_files"]["status"], "blocked")
        self.assertEqual(result["local_model_status"], "blocked")
        self.assertEqual(result["model_or_index_loads"], 0)

    def test_changed_environment_and_missing_cache_remain_blocked(self):
        self.environment = deepcopy(self.environment)
        self.environment["versions"]["authored-package"] = "2.0"
        (self.cache / "model.safetensors").unlink()
        rows = self.rows(self.check())
        self.assertEqual(rows["query_runtime_environment"]["status"], "blocked")
        self.assertEqual(rows["query_model_cache"]["status"], "blocked")

    def test_unavailable_server_reports_all_metadata_attempts_without_crashing(self):
        for endpoint in self.replies:
            self.replies[endpoint] = ConnectionRefusedError("Authored unavailable service")
        result = self.check()
        self.assertEqual(result["metadata_requests"], 4)
        self.assertEqual(result["local_model_status"], "blocked")
        self.assertEqual(self.rows(result)["resident_context_observation"]["status"], "pending")
        self.assertTrue((self.output / "readiness_checks.json").is_file())

    def test_malformed_metadata_collections_do_not_raise(self):
        self.replies["/api/tags"] = {"models": None}
        self.replies["/api/ps"] = {"models": {"unexpected": "mapping"}}
        result = self.check()
        self.assertEqual(result["local_model_status"], "blocked")
        self.assertEqual(result["metadata_requests"], 4)

    def test_wrong_digest_or_remote_template_is_not_accepted(self):
        self.replies["/api/tags"]["models"][0]["digest"] = "0" * 64
        self.replies["/api/show"]["remote_host"] = "https://example.invalid"
        rows = self.rows(self.check())
        self.assertEqual(rows["local_model_artifact"]["status"], "blocked")
        self.assertEqual(rows["local_model_template"]["status"], "blocked")

    def test_ambiguous_installed_models_do_not_match(self):
        self.replies["/api/tags"]["models"] *= 2
        self.assertEqual(self.rows(self.check())["local_model_artifact"]["status"], "blocked")

    def test_existing_request_markers_and_incomplete_calls_are_preserved(self):
        marker = self.root / "results/integration/model_calls/active_call/owner.json"
        marker.parent.mkdir(parents=True)
        marker.write_bytes(b'{"job":"authored"}')
        pending = self.root / "results/integration/model_calls/authored_role/generation_pending.json"
        pending.parent.mkdir(parents=True)
        pending.write_bytes(b'{"call_id":"authored_role"}')
        result = self.check()
        row = self.rows(result)["unresolved_request_markers"]
        self.assertEqual(row["status"], "blocked")
        self.assertEqual(len(row["details"]["active_markers"]), 1)
        self.assertEqual(len(row["details"]["unfinished_generation_folders"]), 1)
        self.assertEqual(marker.read_bytes(), b'{"job":"authored"}')
        self.assertEqual(pending.read_bytes(), b'{"call_id":"authored_role"}')

    def test_a_prior_evidence_folder_is_never_overwritten(self):
        self.check()
        before = {p.name: p.read_bytes() for p in self.output.iterdir()}
        with self.assertRaisesRegex(ValueError, "fresh evidence folder"):
            self.check()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output.iterdir()})

    def test_unresolved_saved_result_blocks_even_without_an_active_marker(self):
        relative = "results/integration/model_calls/authored_uncertain/result.json"
        self.put(relative, {"status": "unresolved", "error": "Authored uncertain completion"})
        result_path = self.root / relative
        before = result_path.read_bytes()
        row = self.rows(self.check())["unresolved_request_markers"]
        self.assertEqual(row["status"], "blocked")
        self.assertEqual(row["details"]["active_markers"], [])
        self.assertEqual(row["details"]["unresolved_result_folders"], ["results/integration/model_calls/authored_uncertain"])
        self.assertEqual(result_path.read_bytes(), before)

    def test_request_only_or_unreadable_saved_result_needs_inspection(self):
        self.put("results/integration/model_calls/authored_unfinished/request.json", {"call_id": "authored_unfinished"})
        self.put("results/integration/model_calls/authored_unreadable/result.json", b"Not a result record")
        row = self.rows(self.check())["unresolved_request_markers"]
        self.assertEqual(row["status"], "blocked")
        self.assertEqual(len(row["details"]["unfinished_generation_folders"]), 1)
        self.assertEqual(len(row["details"]["unreadable_result_records"]), 1)

    def test_http_error_body_is_preserved_as_failure_evidence(self):
        self.replies["/api/show"] = HTTPError("http://127.0.0.1:11434/api/show", 404, "Authored missing model", {}, io.BytesIO(b'{"error":"authored missing model"}'))
        result = self.check()
        events = json.loads((self.output / "metadata_requests.json").read_bytes())
        event = events[2]
        self.assertEqual(event["status"], "failed")
        self.assertEqual(event["http_status"], 404)
        self.assertEqual((self.root / event["raw_response_path"]).read_bytes(), b'{"error":"authored missing model"}')
        self.assertEqual(result["local_model_status"], "blocked")

    def test_metadata_transport_rejects_generation_before_opening_a_connection(self):
        with patch.object(readiness, "build_opener", side_effect=AssertionError("A network connection was attempted")):
            with self.assertRaisesRegex(ValueError, "metadata requests"):
                readiness._metadata_request("/api/chat", {"model": readiness.MODEL})


if __name__ == "__main__":
    unittest.main(verbosity=2)

pytestmark = pytest.mark.requirement('31.6:readiness-metadata')
