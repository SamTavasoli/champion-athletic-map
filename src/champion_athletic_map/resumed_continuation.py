"""Restore the verified saved check-table layout before the unchanged continuation."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


VERSION = "verified-saved-case13-handoff-1"
SUMMARY = "results/step31_verified_continuation_summary.json"
POINTERS = {"production": "results/pilot/saved_continuation/verified_case13.json",
            "injected_test": "results/pilot/saved_continuation/verified_injected_case13.json"}
EXPECTED_ERROR = "ValueError: The first prepared revision differs from the saved corrected case-13 request."


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def load(root, name):
    path = root / "src/champion_athletic_map" / (name + ".py")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("verified_handoff_" + name, path))
    result.__spec__.loader.exec_module(result)
    return result


def named_rows(table):
    if not isinstance(table, dict):
        raise ValueError("The original check-table view must remain an object.")
    columns, rows = table.get("columns"), table.get("findings")
    if (not isinstance(columns, list) or not columns or len(set(columns)) != len(columns)
            or any(not isinstance(key, str) for key in columns) or not isinstance(rows, list)
            or not rows or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)):
        raise ValueError("The original complete check-table rows or column layout are invalid.")
    return {"fields": {key: deepcopy(value) for key, value in table.items() if key not in ("columns", "findings")},
            "rows": [dict(zip(columns, deepcopy(row))) for row in rows]}


def verified_initial_table(root, source):
    engine = load(root, "planners/evaluated_specialists")
    review, candidate, food = (load(root, name) for name in
                               ("review_encoding", "context_encoding", "food_reference_encoding"))
    encoded = json.loads(source["initial"]["new_candidate_request"]["messages"][1]["content"])
    decoded = food.decode_view(encoded)
    saved_candidate = candidate.decode_candidate(decoded["candidate"])
    expected_candidate = engine.candidate_view(source["current"]["candidate"], "candidate_0")
    saved_checks = review.decode_checks(decoded["check_results"])
    rebuilt = engine.model_check_view(source["current"]["check_report"])
    if (canonical(saved_candidate) != canonical(expected_candidate)
            or canonical(named_rows(saved_checks)) != canonical(named_rows(rebuilt))
            or canonical(decoded["athlete_input"]) != canonical(source["selected"]["public"])
            or canonical(decoded["reference_data"]) != canonical(source["selected"]["packet"]["payload"])
            or canonical(decoded["evaluator_assessment"]) != canonical(source["assessment"])
            or canonical(source["initial"]["removed_generated_notes"]) != canonical(source["old"]["draft_result"]["specialist_notes"])):
        raise ValueError("The captured handoff differs from its original facts, complete findings, candidate or evaluation.")
    # Candidate encoding is already identical in this captured case; only the check-table layout needs restoration.
    if canonical(candidate.encode_candidate(expected_candidate)) != canonical(encoded["candidate"]):
        raise ValueError("The candidate encoding has an additional unreviewed layout difference.")
    return deepcopy(saved_checks)


def initial_envelope(root, source):
    engine = load(root, "planners/evaluated_specialists")
    return {"notes": deepcopy(source["initial"]["removed_generated_notes"]),
            "candidate": engine.candidate_view(source["current"]["candidate"], "candidate_0"),
            "check_results": verified_initial_table(root, source),
            "evaluator_assessment": deepcopy(source["assessment"])}


def _zero_transport_predecessor(root, mode):
    old = load(root, "saved_continuation")
    pointer_path = old.checked(root, old.POINTERS[mode])
    pointer = old.read(pointer_path)
    manifest_path = old.checked(root, pointer["manifest_path"])
    manifest = old.read(manifest_path)
    old.validate_manifest(root, manifest)
    if manifest.get("execution_mode") != mode:
        raise ValueError("The previous attempt belongs to a different execution mode.")
    folder = root / "results/pilot/saved_continuation" / manifest["continuation_id"]
    receipt_path, outcome_path = folder / "completed.json", folder / "outcome.json"
    if not receipt_path.is_file() or not outcome_path.is_file() or (folder / "stopped.json").exists():
        raise ValueError("The previous attempt must have a conclusive verified zero-transport receipt.")
    receipt, outcome = old.read(receipt_path), old.read(outcome_path)
    if receipt.get("manifest_id") != manifest["manifest_id"]:
        raise ValueError("The previous receipt belongs to another continuation.")
    if (receipt.get("files") or {}).get(outcome_path.relative_to(root).as_posix()) != sha(outcome_path.read_bytes()):
        raise ValueError("The previous receipt does not bind its exact terminal outcome.")
    old.verify(root, receipt["files"])
    old._verified_terminal(outcome, manifest)
    trace = outcome.get("trace") or {}
    if (outcome.get("terminal_state") != "execution_error" or outcome.get("failed_stage") != "runtime_setup"
            or outcome.get("injected_test_dependencies") is not (mode == "injected_test")
            or outcome.get("error") != EXPECTED_ERROR or outcome.get("roles") or outcome.get("history")
            or outcome.get("new_model_submissions") != 0 or outcome.get("amended_model_submissions_total") != 0
            or outcome.get("backend_requests_confirmed") != 0
            or any(trace.get(key) != 0 for key in ("generation_transport_attempts", "render_transport_attempts", "metadata_transport_attempts"))
            or trace.get("http_requests") != 0 or trace.get("role_invocations") != 0
            or trace.get("http_without_terminal_event")):
        raise ValueError("The previous attempt is outside the reviewed zero-request handoff failure.")
    for name in ("http_events.jsonl", "stage_events.jsonl"):
        path = folder / name
        if path.exists() and any(line.strip() for line in path.read_bytes().splitlines()):
            raise ValueError("The previous attempt already recorded transport or role activity.")
    native = root / "results/integration/model_calls"
    if any(native.glob(manifest["call_prefix"] + "*")):
        raise ValueError("A previous native call directory exists; no new four-request budget may be created.")
    bindings = {**receipt["files"], pointer_path.relative_to(root).as_posix(): sha(pointer_path.read_bytes()),
                manifest_path.relative_to(root).as_posix(): sha(manifest_path.read_bytes()),
                receipt_path.relative_to(root).as_posix(): sha(receipt_path.read_bytes())}
    proof = {"previous_continuation_manifest_id": manifest["manifest_id"], "previous_continuation_id": manifest["continuation_id"],
        "failure": EXPECTED_ERROR, "verified_previous_generation_submissions": 0,
        "verified_previous_render_submissions": 0, "verified_previous_metadata_submissions": 0,
        "verified_previous_role_invocations": 0, "original_four_request_allowance_remaining": 4,
        "old_failed_outcome_sha256": sha(outcome_path.read_bytes()), "old_receipt_sha256": sha(receipt_path.read_bytes())}
    proof_path = root / "artifacts/pilot/saved_continuation/verified_handoff" / manifest["manifest_id"] / "zero_transport_proof.json"
    old.save_once(proof_path, proof)
    bindings[proof_path.relative_to(root).as_posix()] = sha(proof_path.read_bytes())
    return proof, bindings


def _api(root, mode):
    base = load(root, "saved_continuation")
    original_source, original_module = base._load_source, base.module
    base.VERSION, base.SUMMARY, base.POINTERS = VERSION, SUMMARY, deepcopy(POINTERS)
    cache = {}
    def source(project):
        value = original_source(project)
        proof, previous = _zero_transport_predecessor(project, mode)
        value["bindings"].update(previous)
        path = project / "src/champion_athletic_map/resumed_continuation.py"
        value["bindings"][path.relative_to(project).as_posix()] = sha(path.read_bytes())
        value["verified_initial_table"] = verified_initial_table(project, value)
        value["previous_zero_transport_proof"] = proof
        cache["source"] = value
        return value
    def modules(project, name):
        value = original_module(project, name)
        if name == "src/champion_athletic_map/planners/evaluated_specialists.py":
            original_view = value.model_check_view
            def check_view(report):
                selected = cache.get("source") or source(project)
                if canonical(report) == canonical(selected["current"]["check_report"]):
                    proposed = original_view(report)
                    restored = selected["verified_initial_table"]
                    if canonical(named_rows(proposed)) != canonical(named_rows(restored)):
                        raise ValueError("The complete initial findings changed before handoff restoration.")
                    return deepcopy(restored)
                return original_view(report)
            return SimpleNamespace(**{**value.__dict__, "model_check_view": check_view})
        return value
    base._load_source, base.module = source, modules
    return base


def prepare(root, *, execution_mode="production"):
    return _api(Path(root).resolve(), execution_mode).prepare(root, execution_mode=execution_mode)


def execute(root, *, software_evidence=None, emit=print, runtime_factory=None,
            confirmation_api=None, trace_module=None, assessor_factory=None):
    root = Path(root).resolve()
    injected = any(v is not None for v in (runtime_factory, confirmation_api, trace_module, assessor_factory))
    base = _api(root, "injected_test" if injected else "production")
    return base.execute(root, software_evidence=software_evidence, emit=emit, runtime_factory=runtime_factory,
        confirmation_api=confirmation_api, trace_module=trace_module, assessor_factory=assessor_factory)
