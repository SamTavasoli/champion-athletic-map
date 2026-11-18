"""Check our installed pilot prerequisites without running a planning workflow."""

from datetime import datetime, timezone
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import re
import sys
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from urllib.error import HTTPError


MODEL = "llama3.1:8b"
DIGEST = "46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e"
RUNTIME = "0.40.16"
QUANTIZATION = "Q4_K_M"
QUERY = "artifacts/retrieval/query_runtime/query_f6db9aad37d7a9b9"
TOKENIZER = "artifacts/language_model/tokenizers/tokenizer_bdb1409b4c107f2a"
TOKENIZER_MANIFEST_SHA = "b289efbbd60fceb3e6bc38c19fcec0cb4229e5a7445df52fe82d2eb7fd277678"
FOOD = "data/processed/usda_sr_legacy_2018_04/reference_ee67cf780262d24b"


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _decode(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("A JSON field is repeated.")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("A JSON number is not finite.")

    return json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)


def _path(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("A prerequisite path must stay inside its declared folder.")
    result = (root / path).resolve()
    if not result.is_relative_to(root) or result == root:
        raise ValueError("A prerequisite path leaves its declared folder.")
    return result


def _file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _row(identifier, status, reason, evidence="", *, required=True, details=None):
    value = {"check_id": identifier, "status": status, "reason": reason,
             "evidence": evidence, "required": required}
    if details is not None:
        value["details"] = details
    return value


def _hash_group(root, bindings, identifier, evidence):
    if not isinstance(bindings, dict) or not bindings:
        return _row(identifier, "blocked", "The required file bindings are unavailable.", evidence)
    checked, issues = {}, []
    for relative, expected in sorted(bindings.items()):
        try:
            if not isinstance(relative, str) or re.fullmatch(r"[0-9a-f]{64}", str(expected)) is None:
                raise ValueError("Invalid file binding.")
            path = _path(root, relative)
            actual = _file_sha(path)
            if actual != expected:
                raise ValueError("The saved file hash differs.")
            checked[relative] = actual
        except (OSError, ValueError) as error:
            issues.append({"path": relative, "issue": type(error).__name__ + ": " + str(error)})
    return _row(identifier, "blocked" if issues else "passed",
        "Some prerequisite files are missing or changed." if issues else "The declared files match their saved hashes.",
        evidence, details={"verified_files": checked, "issues": issues})


def check_step30(root):
    """Reuse the actual completed routine report only while its bindings match."""
    root = Path(root).resolve()
    relative = "results/step30_testing_summary.json"
    try:
        summary = _decode(_path(root, relative).read_bytes())
        outcomes = summary.get("outcomes") or {}
        total = summary.get("collected_tests")
        valid = (summary.get("schema_version") == "step30-testing-summary-1"
            and summary.get("routine_suite") == "passed" and summary.get("pytest_exit_code") == 0
            and type(total) is int and total >= 248 and summary.get("executed_tests") == total
            and outcomes.get("passed") == total
            and all(outcomes.get(name) == 0 for name in ("failed", "error", "skipped", "expected_failure", "not_executed"))
            and summary.get("collection_errors") == [] and summary.get("source_files_changed") == [])
        rows = [_row("step30_execution", "passed" if valid else "blocked",
            "All recorded routine tests executed and passed." if valid else "The routine test report is incomplete or unsuccessful.",
            relative, details={"collected": total, "executed": summary.get("executed_tests"), "outcomes": outcomes})]
        rows.append(_hash_group(root, summary.get("source_sha256"), "step30_source_bindings", relative))
        rows.append(_hash_group(root, summary.get("test_sha256"), "step30_test_bindings", relative))
        return rows
    except (OSError, ValueError, TypeError, AttributeError) as error:
        return [_row("step30_execution", "blocked", "The completed routine report could not be verified.", relative,
                     details={"error": type(error).__name__ + ": " + str(error)})]


def _environment():
    return {"python_version": platform.python_version(), "python_full_version": sys.version,
            "platform_system": platform.system(), "platform_machine": platform.machine()}


def _query_environment(config, environment):
    expected = config["runtime_environment"]
    actual = _environment() if environment is None else dict(environment)
    supplied_versions = actual.get("versions")
    if supplied_versions is None:
        supplied_versions = {}
        for name in expected["versions"]:
            try:
                supplied_versions[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                supplied_versions[name] = None
    differences = []
    for field in ("python_version", "python_full_version", "platform_system", "platform_machine"):
        if actual.get(field) != expected.get(field):
            differences.append({"field": field, "expected": expected.get(field), "actual": actual.get(field)})
    for name, version in expected["versions"].items():
        if supplied_versions.get(name) != version:
            differences.append({"field": "package:" + name, "expected": version, "actual": supplied_versions.get(name)})
    return _row("query_runtime_environment", "blocked" if differences else "passed",
        "The offline query environment differs from its recorded version." if differences else "The offline query environment matches its recorded version.",
        QUERY + "/query_runtime_config.json", details={"differences": differences})


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _metadata_request(endpoint, payload=None, timeout=8):
    allowed = {"/api/version", "/api/tags", "/api/show", "/api/ps"}
    if endpoint not in allowed or (endpoint == "/api/show") != (payload is not None):
        raise ValueError("Only the declared local metadata requests are available.")
    request = Request("http://127.0.0.1:11434" + endpoint,
        data=None if payload is None else _json_bytes(payload), headers={"Content-Type": "application/json"})
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        data = response.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("The metadata response exceeds its size limit.")
    return data


def check_local_readiness(root, output_dir, *, http_request=None, environment=None, model_cache_root=None):
    """Inspect files and local metadata; never load an index or generate a reply."""
    root = Path(root).resolve()
    output_dir = Path(output_dir)
    output_dir = output_dir.resolve() if output_dir.is_absolute() else (root / output_dir).resolve()
    if not output_dir.is_relative_to(root) or output_dir == root:
        raise ValueError("The readiness evidence folder must be inside the project.")
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise ValueError("Use a fresh evidence folder; earlier readiness results are preserved.")
    rows = check_step30(root)

    def load(relative):
        return _decode(_path(root, relative).read_bytes())

    source_config = None
    try:
        relative = "artifacts/planners/shared_reference_source_config.json"
        source_config = load(relative)
        bindings = {**source_config["source_sha256"], **source_config["builder_sha256"]}
        rows.append(_hash_group(root, bindings, "reference_source_files", relative))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        rows.append(_row("reference_source_files", "blocked", "The shared reference file bindings are unavailable.",
                         details={"error": type(error).__name__ + ": " + str(error)}))

    try:
        relative = FOOD + "/step14_food_reference_summary.json"
        food = load(relative)
        expected_summary = (source_config or {}).get("source_sha256", {}).get(relative)
        if expected_summary is None or _file_sha(_path(root, relative)) != expected_summary:
            raise ValueError("The food snapshot producer is not bound to the selected sources.")
        bindings = {FOOD + "/" + name: data["sha256"] for name, data in food["artifacts"].items()}
        rows.append(_hash_group(root, bindings, "food_snapshot_files", relative))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        rows.append(_row("food_snapshot_files", "blocked", "The frozen food files could not be verified.",
                         details={"error": type(error).__name__ + ": " + str(error)}))

    try:
        relative = QUERY + "/query_runtime_config.json"
        config = load(relative)
        rows.append(_query_environment(config, environment))
        revision = config["model_source_manifest"]["revision"]
        cache = (Path(model_cache_root).resolve() if model_cache_root is not None else
                 (Path.home() / ".cache/champion_athletic_map/retrieval_models" / revision).resolve())
        bindings = {item["relative_path"]: item["sha256"] for item in config["model_source_manifest"]["files"]}
        rows.append(_hash_group(cache, bindings, "query_model_cache", str(cache)))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        rows.append(_row("query_model_cache", "blocked", "The pinned offline query files could not be verified.",
                         details={"error": type(error).__name__ + ": " + str(error)}))

    locks = ["results/integration/model_calls/active_call",
             "results/integration/chat_compatibility/active_step24_5_run",
             "results/app/active_model_job", "results/integration/active_runtime"]
    try:
        active = [name for name in locks if _path(root, name).exists()]
        calls = _path(root, "results/integration/model_calls")
        unfinished, unresolved, unreadable = [], [], []
        if calls.is_dir():
            for folder in calls.iterdir():
                if not folder.is_dir() or folder.name == "active_call":
                    continue
                relative = folder.relative_to(root).as_posix()
                result_path = _path(root, relative + "/result.json")
                if not result_path.is_file():
                    if (folder / "request.json").exists() or (folder / "generation_pending.json").exists():
                        unfinished.append(relative)
                    continue
                try:
                    saved_result = _decode(result_path.read_bytes())
                    if not isinstance(saved_result, dict):
                        raise ValueError("The saved result must be an object.")
                    if saved_result.get("status") == "unresolved":
                        unresolved.append(relative)
                except (OSError, ValueError) as error:
                    unreadable.append({"path": relative, "error": type(error).__name__ + ": " + str(error)})
        needs_resolution = bool(active or unfinished or unresolved or unreadable)
        rows.append(_row("unresolved_request_markers", "blocked" if needs_resolution else "passed",
            "An earlier request needs resolution; its files were preserved." if needs_resolution else "No recorded active or unfinished request marker was found.",
            details={"active_markers": active, "unfinished_generation_folders": unfinished,
                "unresolved_result_folders": unresolved, "unreadable_result_records": unreadable}))
    except (OSError, ValueError) as error:
        rows.append(_row("unresolved_request_markers", "blocked", "The request-marker state could not be inspected safely.",
            details={"error": type(error).__name__ + ": " + str(error)}))

    native = None
    try:
        manifest_path = TOKENIZER + "/tokenizer_manifest.json"
        if _file_sha(_path(root, manifest_path)) != TOKENIZER_MANIFEST_SHA:
            raise ValueError("The tokenizer producer differs from the selected artifact.")
        manifest = load(manifest_path)
        payloads = {TOKENIZER + "/" + name: value for name, value in manifest["payload_hashes"].items()}
        rows.append(_hash_group(root, payloads, "native_tokenizer_files", manifest_path))
        source = manifest["source_native_metadata"]
        if manifest["model_digest"] != DIGEST or _file_sha(_path(root, source["relative_path"])) != source["sha256"]:
            raise ValueError("The saved native model metadata binding differs.")
        native = load(source["relative_path"])
        if not isinstance(native, dict):
            raise ValueError("The recorded native metadata must be an object.")
        rows.append(_row("native_metadata_snapshot", "passed", "The recorded model metadata matches its saved hash.", source["relative_path"]))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        rows.append(_row("native_metadata_snapshot", "blocked", "The recorded native metadata is unavailable.",
                         details={"error": type(error).__name__ + ": " + str(error)}))

    request = http_request or _metadata_request
    observations, requests = {}, []
    for endpoint in ("/api/version", "/api/tags", "/api/show", "/api/ps"):
        event = {"endpoint": endpoint, "method": "POST" if endpoint == "/api/show" else "GET",
                 "evidence_kind": "injected_test_transport" if http_request else "local_http_observation"}
        try:
            data = request(endpoint, {"model": MODEL, "verbose": False} if endpoint == "/api/show" else None, 8)
            if not isinstance(data, bytes):
                raise TypeError("Metadata transport must retain the raw response bytes.")
            name = str(len(requests) + 1).zfill(3) + "_" + endpoint.rsplit("/", 1)[1] + ".bin"
            with (output_dir / name).open("xb") as handle:
                handle.write(data)
            event["raw_response_path"] = (output_dir / name).relative_to(root).as_posix()
            event["raw_response_sha256"] = hashlib.sha256(data).hexdigest()
            value = _decode(data)
            if not isinstance(value, dict):
                raise ValueError("The metadata reply must be an object.")
            observations[endpoint] = value
            event["status"] = "returned"
        except Exception as error:
            event["status"] = "failed"
            event["error"] = type(error).__name__ + ": " + str(error)
            if isinstance(error, HTTPError):
                data = error.read(2 * 1024 * 1024 + 1)
                name = str(len(requests) + 1).zfill(3) + "_" + endpoint.rsplit("/", 1)[1] + "_http_error.bin"
                with (output_dir / name).open("xb") as handle:
                    handle.write(data)
                event.update(http_status=error.code,
                    raw_response_path=(output_dir / name).relative_to(root).as_posix(),
                    raw_response_sha256=hashlib.sha256(data).hexdigest())
        requests.append(event)

    evidence = output_dir.relative_to(root).as_posix() + "/metadata_requests.json"
    version_ok = observations.get("/api/version", {}).get("version") == RUNTIME
    rows.append(_row("local_runtime_version", "passed" if version_ok else "blocked",
        "The local Ollama version matches the recorded runtime." if version_ok else "The recorded local Ollama runtime is unavailable or differs.", evidence))
    tags = observations.get("/api/tags", {}).get("models")
    matches = [m for m in (tags if isinstance(tags, list) else [])
               if isinstance(m, dict) and (m.get("name") == MODEL or m.get("model") == MODEL)]
    details = matches[0].get("details") if len(matches) == 1 else None
    model_ok = (len(matches) == 1 and matches[0].get("digest") == DIGEST
                and isinstance(details, dict) and details.get("quantization_level") == QUANTIZATION)
    rows.append(_row("local_model_artifact", "passed" if model_ok else "blocked",
        "The installed model digest and quantization match." if model_ok else "The installed model artifact is unavailable or differs.", evidence))
    shown = observations.get("/api/show")
    defaults = ("template", "system", "messages", "parameters", "renderer", "parser", "template_source")
    template_ok = (native is not None and isinstance(shown, dict) and bool(native.get("template"))
        and not shown.get("remote_host") and not shown.get("remote_model")
        and all(shown.get(key) == native.get(key) for key in defaults))
    rows.append(_row("local_model_template", "passed" if template_ok else "blocked",
        "The local template and defaults match the recorded metadata." if template_ok else "The local model template or defaults could not be matched.", evidence))
    running = observations.get("/api/ps", {}).get("models")
    runners = [m for m in (running if isinstance(running, list) else [])
               if isinstance(m, dict) and m.get("digest") == DIGEST]
    context_ok = len(runners) == 1 and type(runners[0].get("context_length")) is int and runners[0]["context_length"] >= 8192
    rows.append(_row("resident_context_observation", "passed" if context_ok else "pending",
        "The resident selected runner reports at least 8192 context tokens." if context_ok else "The effective runner context remains for the pilot; no model was loaded by this check.",
        evidence, required=False, details={"selected_runners": runners}))

    reference_ids = {"reference_source_files", "food_snapshot_files", "query_runtime_environment", "query_model_cache"}
    identity_ids = {"native_metadata_snapshot", "native_tokenizer_files", "local_runtime_version", "local_model_artifact", "local_model_template"}
    result = {"schema_version": "step31-local-readiness-1", "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": rows, "metadata_requests": len(requests), "model_generation_calls": 0,
        "query_encoder_processes": 0, "model_or_index_loads": 0,
        "local_model_status": "matched_metadata" if all(r["status"] == "passed" for r in rows if r["check_id"] in identity_ids) else "blocked",
        "reference_files_status": "verified" if all(r["status"] == "passed" for r in rows if r["check_id"] in reference_ids) else "blocked",
        "metadata_evidence_dir": output_dir.relative_to(root).as_posix(),
        "generation_runtime_verified": False, "operational_generation_ready": False,
        "transport_evidence": "injected_test_transport" if http_request else "local_http_observation"}
    for filename, value in (("metadata_requests.json", requests), ("readiness_checks.json", result)):
        with (output_dir / filename).open("xb") as handle:
            handle.write(_json_bytes(value))
    return result
