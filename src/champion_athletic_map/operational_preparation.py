"""Record bounded, reversible operational corrections from saved development work."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import unicodedata


VERSION = "operational-correction-preparation-1"
SUMMARY = "results/step31_operational_corrections_summary.json"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=False, allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def module(root, name):
    path = root / "src/champion_athletic_map" / (name + ".py")
    value = importlib.util.module_from_spec(importlib.util.spec_from_file_location("operational_preparation_" + name, path))
    value.__spec__.loader.exec_module(value)
    return value


def checked_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("A saved operational dependency is unavailable: " + str(relative))
    return path


def verify(root, bindings):
    for relative, expected in bindings.items():
        if sha(checked_path(root, relative).read_bytes()) != expected:
            raise ValueError("A saved operational dependency changed: " + relative)


def save_once(path, value):
    data = canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("An earlier operational candidate differs and was preserved.")
    else:
        with path.open("xb") as handle:
            handle.write(data)


def _leaves(value):
    if isinstance(value, dict):
        if isinstance(value.get("call_id"), str) and isinstance(value.get("request_sha256"), str):
            yield value
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item)


def load_saved(root):
    root = Path(root).resolve()
    summary_path = "results/step31_contract_probe_summary.json"
    summary = read(checked_path(root, summary_path))
    if (summary.get("recorded_jobs") != 4 or summary.get("independent_assessment_completed") is not True
            or summary.get("injected_test_dependencies") is not False or summary.get("protocol_frozen") is not False
            or len(summary.get("reports", [])) != 4
            or {item["planner_version"] for item in summary["reports"]} != {1, 2, 3, 4}):
        raise ValueError("The saved four-planner contract probe is incomplete.")
    probe_id = summary["probe_id"]
    if not isinstance(probe_id, str) or re.fullmatch(r"contract_[0-9a-f]{20}", probe_id) is None:
        raise ValueError("The saved contract probe identity is invalid.")
    manifest_path = "artifacts/pilot/shared_guidance/" + probe_id + "/probe_manifest.json"
    manifest = read(checked_path(root, manifest_path))
    identity = {key: value for key, value in manifest.items() if key not in
        ("probe_id", "manifest_id", "case_review_config_path", "public_schema_path", "jobs")}
    public = manifest["public_record"]
    if (sha(canonical(identity)) != summary["manifest_id"] or manifest["manifest_id"] != summary["manifest_id"]
            or manifest["probe_id"] != probe_id or sha(canonical(public)) != manifest["public_record_sha256"]):
        raise ValueError("The recorded contract probe manifest changed.")
    bindings = {name: sha(checked_path(root, name).read_bytes()) for name in (summary_path, manifest_path)}
    cases, packets, leaves = [], [], {}
    jobs = {item["job_id"]: item for item in manifest["jobs"]}
    for report in summary["reports"]:
        path = checked_path(root, report["outcome_path"])
        if not path.is_relative_to(root / "results/pilot/probes" / probe_id / "jobs"):
            raise ValueError("A designated outcome leaves its recorded probe.")
        outcome = read(path)
        record_path = path.with_name("job_record.json")
        record = read(record_path)
        body = {key: value for key, value in record.items() if key != "job_record_sha256"}
        job = jobs.get(report["job_id"]) or {}
        if (sha(canonical(outcome)) != report["assessment"]["designated_outcome_sha256"]
                or record.get("job_record_sha256") != sha(canonical(body))
                or record.get("outcome_sha256") != sha(path.read_bytes())
                or record.get("manifest_id") != manifest["manifest_id"]
                or record.get("job_id") != report["job_id"] or job.get("planner_version") != report["planner_version"]
                or record.get("planner_version") != report["planner_version"]
                or record.get("public_record_sha256") != manifest["public_record_sha256"]):
            raise ValueError("A designated outcome or its sealed job record changed.")
        supplied = (outcome.get("response") or {}).get("authoritative_public_input")
        if supplied is not None and canonical(supplied) != canonical(public["input"]):
            raise ValueError("A reply used a different athlete input.")
        for file in (path, record_path):
            bindings[file.relative_to(root).as_posix()] = sha(file.read_bytes())
        if report["planner_version"] != 1:
            packet = (record.get("reference_record") or {}).get("packet")
            if not isinstance(packet, dict):
                raise ValueError("A reference-enabled job lacks its complete original packet.")
            packets.append(packet)
        for leaf in _leaves(outcome):
            call_id = leaf["call_id"]
            if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", call_id) is None:
                raise ValueError("A recorded model call identifier is invalid.")
            folder = root / "results/integration/model_calls" / call_id
            if not (folder / "request.json").is_file():
                # A preparation error may occur before a model-call folder exists.
                continue
            saved_request, saved_result = read(folder / "request.json"), read(folder / "result.json")
            if (sha(wire(saved_request.get("request"))) != leaf["request_sha256"]
                    or saved_result.get("request_sha256") != leaf["request_sha256"]
                    or saved_request.get("input_configuration") != leaf.get("input_configuration")
                    or saved_result.get("completion_valid") != leaf.get("completion_valid")
                    or saved_result.get("format_valid") != leaf.get("format_valid")
                    or canonical(saved_result.get("context")) != canonical(leaf.get("context"))
                    or canonical(saved_result.get("usage")) != canonical(leaf.get("usage"))
                    or canonical((saved_result.get("response") or {}).get("model_output"))
                        != canonical((leaf.get("response") or {}).get("model_output"))):
                raise ValueError("A native model-call request or result differs from its saved workflow.")
            if call_id in leaves and leaves[call_id]["request_sha256"] != leaf["request_sha256"]:
                raise ValueError("A model call identifier belongs to multiple requests.")
            leaves[call_id] = saved_result
            for name in ("request.json", "result.json", "backend_response.json", "render_response.json", "rendered_prompt.txt"):
                file = folder / name
                if file.is_file():
                    bindings[file.relative_to(root).as_posix()] = sha(file.read_bytes())
        cases.append({"planner_version": report["planner_version"], "outcome": outcome, "assessment": report["assessment"]})
    if len(packets) != 3 or any(canonical(packet) != canonical(packets[0]) for packet in packets[1:]):
        raise ValueError("The reference-supported jobs did not receive identical complete packets.")
    return {"summary": summary, "manifest": manifest, "public_record": public, "cases": cases,
        "truth_packet": packets[0], "leaves": leaves, "input_sha256": bindings}


class SourceTableCounter:
    """Reference BPE count, calibrated to the exact saved rendered request below."""
    def __init__(self, model, native_info):
        self.vocab = model["vocab"]
        self.ranks = {tuple(pair): index for index, pair in enumerate(model["merges"])}
        visible = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
        values, extra = list(visible), 0
        for value in range(256):
            if value not in visible:
                visible.append(value); values.append(256 + extra); extra += 1
        self.alphabet = dict(zip(visible, map(chr, values)))
        special = [text for text, kind in zip(native_info["tokenizer.ggml.tokens"], native_info["tokenizer.ggml.token_type"]) if kind == 3]
        if not special:
            raise ValueError("The saved native tokenizer lacks its control-token table.")
        self.controls = re.compile("|".join(re.escape(text) for text in sorted(special, key=lambda value: (-len(value), value))))
        self.cache = {}

    def ordinary(self, text):
        letters = "".join(sorted({char for char in text if unicodedata.category(char).startswith("L")}))
        numbers = "".join(sorted({char for char in text if unicodedata.category(char).startswith("N")}))
        letter, number = re.escape(letters) or "\uffff", re.escape(numbers) or "\uffff"
        pattern = (r"(?:'[sS]|'[tT]|'[rR][eE]|'[vV][eE]|'[mM]|'[lL][lL]|'[dD])"
            + rf"|[^\r\n{letter}{number}]?[{letter}]+|[{number}]{{1,3}}"
            + rf"| ?[^\s{letter}{number}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+")
        pieces = re.findall(pattern, text)
        if "".join(pieces) != text:
            raise ValueError("The reference pre-splitter did not preserve the complete prompt.")
        total = 0
        for piece in pieces:
            if piece not in self.cache:
                encoded = "".join(self.alphabet[value] for value in piece.encode("utf-8"))
                if encoded in self.vocab:
                    self.cache[piece] = 1
                else:
                    symbols = list(encoded)
                    while len(symbols) > 1:
                        choices = [(self.ranks[(symbols[i], symbols[i + 1])], i) for i in range(len(symbols) - 1)
                            if (symbols[i], symbols[i + 1]) in self.ranks]
                        if not choices:
                            break
                        _, index = min(choices)
                        symbols[index:index + 2] = [symbols[index] + symbols[index + 1]]
                    if any(value not in self.vocab for value in symbols):
                        raise ValueError("A reference BPE piece is outside the pinned vocabulary.")
                    self.cache[piece] = len(symbols)
            total += self.cache[piece]
        return total

    def count(self, text):
        if not isinstance(text, str) or len(text) > 200_000:
            raise ValueError("The offline counter requires complete bounded text.")
        total, offset = 0, 0
        for match in self.controls.finditer(text):
            total += self.ordinary(text[offset:match.start()]) + 1
            offset = match.end()
        return total + self.ordinary(text[offset:])


def recorded_render(request):
    messages = request.get("messages")
    if (not isinstance(messages, list) or [item.get("role") for item in messages] != ["system", "user"]
            or any(not isinstance(item.get("content"), str) for item in messages)):
        raise ValueError("The offline replay requires its recorded two-message layout.")
    return "".join("<|start_header_id|>" + item["role"] + "<|end_header_id|>\n\n" + item["content"] + "<|eot_id|>"
        for item in messages) + "<|start_header_id|>assistant<|end_header_id|>\n\n"


def measure_blocked_request(root, source):
    blocked = [item for item in source["leaves"].values() if (item.get("context") or {}).get("status") == "context_overflow"
        and item.get("stage") == "revision"]
    if len(blocked) != 1:
        raise ValueError("The saved development probe needs its single blocked revision request.")
    result = blocked[0]
    folder = root / "results/integration/model_calls" / result["call_id"]
    request = read(folder / "request.json")["request"]
    before = recorded_render(request)
    context = result["context"]
    if (request["options"]["num_ctx"] != context["configured_context_tokens"]
            or request["options"]["num_predict"] != context["output_reserve"]
            or context["input_ceiling_after_output_and_margin"] != request["options"]["num_ctx"]
                - request["options"]["num_predict"] - context["safety_margin"]):
        raise ValueError("The saved budget differs from the unchanged submitted settings.")
    if ((folder / "rendered_prompt.txt").read_text(encoding="utf-8") != before
            or sha(before.encode("utf-8")) != context["rendered_prompt_sha256"]):
        raise ValueError("The complete recorded render layout could not be reproduced.")
    adapter = module(root, "llm")
    candidates = [path for path in (root / "artifacts/language_model/tokenizers").glob("*/tokenizer_manifest.json")
        if sha(path.read_bytes()) == adapter.TOKENIZER_SHA]
    if len(candidates) != 1:
        raise ValueError("The pinned native tokenizer manifest is unavailable.")
    manifest_path = candidates[0]
    manifest = read(manifest_path)
    assets = {manifest_path.relative_to(root).as_posix(): sha(manifest_path.read_bytes())}
    for name, digest in manifest["payload_hashes"].items():
        assets[(manifest_path.parent / name).relative_to(root).as_posix()] = digest
    native = manifest["source_native_metadata"]
    assets[native["relative_path"]] = native["sha256"]
    verify(root, assets)
    model = read(manifest_path.parent / "normal_bpe_tokenizer.json")["model"]
    counter = SourceTableCounter(model, read(root / native["relative_path"])["model_info"])
    old_body = counter.count(before)
    if old_body != context["rendered_body_tokens"]:
        raise ValueError("The local source-table count differs from the saved native-encoder count.")
    codec = module(root, "food_reference_encoding")
    view = adapter._decode(request["messages"][1]["content"].encode("utf-8"))
    encoded = codec.encode_view(view)
    if canonical(codec.decode_view(encoded)) != canonical(view) or canonical(encoded) == canonical(view):
        raise ValueError("The nutrient representation did not preserve and encode this complete request.")
    amended = deepcopy(request)
    amended["messages"][0]["content"] += "\n\n" + codec.ENCODING_NOTICE
    amended["messages"][1]["content"] = canonical(encoded).decode("utf-8")
    new_body = counter.count(recorded_render(amended))
    reserve = context["unverified_boundary_reserve"]
    ceiling = context["input_ceiling_after_output_and_margin"]
    return {"method": "pinned_source_table_BPE_reproduced_on_exact_saved_render",
        "call_id": result["call_id"], "old_rendered_body_tokens": old_body,
        "old_input_tokens_including_boundary_reserve": old_body + reserve,
        "new_rendered_body_tokens": new_body, "new_input_tokens_including_boundary_reserve": new_body + reserve,
        "input_ceiling": ceiling, "local_candidate_fits": new_body + reserve <= ceiling,
        "local_headroom": ceiling - new_body - reserve, "all_original_input_values_roundtrip": True,
        "tokenizer_asset_sha256": assets, "unicode_version": unicodedata.unidata_version,
        "original_backend_render_reproduced": True, "new_backend_render_confirmed": False,
        "new_request_generated": False, "output_reserve_changed": False, "context_limit_changed": False}


def prepare(root, *, software_evidence=None):
    root = Path(root).resolve()
    if software_evidence is not None:
        if (software_evidence.get("status") != "passed" or software_evidence.get("passed", 0) <= 0
                or not software_evidence.get("files")):
            raise ValueError("The operational software checks must execute successfully first.")
        verify(root, software_evidence["files"])
    source = load_saved(root)
    original_bindings = source["manifest"]["module_and_config_sha256"]
    dependencies = ["src/champion_athletic_map/" + name + ".py" for name in
        ("operational_preparation", "operational_runtime", "food_reference_encoding", "food_answer_audit")]
    old_dependencies = ["src/champion_athletic_map/" + name + ".py" for name in
        ("contract_probe", "request_contracts", "contract_runtime", "pilot_schedule", "llm", "independent_food")]
    verify(root, {name: original_bindings[name] for name in old_dependencies})
    integration = read(root / "artifacts/language_model/integration_config.json")
    directory = integration["contracts_directory"]
    local_schema_path = directory + "/public_profile_record_schema.json"
    verify(root, {local_schema_path: original_bindings[local_schema_path]})
    schema = module(root, "pilot_schedule").build_input_schema(read(root / local_schema_path))
    original_bundle = module(root, "contract_probe").case_contracts(root, source["public_record"], schema)
    bounded = module(root, "operational_runtime").bounded_contracts(original_bundle)
    measurement = measure_blocked_request(root, source)
    if not measurement["local_candidate_fits"]:
        raise ValueError("The lossless reference representation still exceeds the saved budget.")
    audit = module(root, "food_answer_audit")
    base = module(root, "independent_food")
    food_reviews, diagnostics = [], []
    for case in sorted(source["cases"], key=lambda value: value["planner_version"]):
        outcome = case["outcome"]
        output = ((outcome.get("response") or {}).get("model_output") or {})
        parsed = output.get("parsed_object")
        checks = audit.assess_food(source["public_record"]["input"], parsed or {}, source["truth_packet"], base_assess_food=base.assess_food)
        food_reviews.append({"planner_version": case["planner_version"], "checks": checks,
            "designated_response_modified": False})
        diagnostics.append({"planner_version": case["planner_version"], "execution_error": outcome.get("error"),
            "completion_valid": outcome.get("completion_valid"), "format_valid": outcome.get("format_valid"),
            "original_required_violations": case["assessment"].get("required_violations"),
            "original_required_unknowns": case["assessment"].get("required_unknowns"),
            "existing_commitments": next((item for item in case["assessment"]["checks"] if item["check_id"] == "existing_commitments"), None)})
    dependencies += old_dependencies + [local_schema_path, "docs/operational_corrections.md"]
    identity = {"schema_version": VERSION, "source_probe_id": source["manifest"]["probe_id"],
        "source_manifest_id": source["manifest"]["manifest_id"], "input_sha256": source["input_sha256"],
        "component_sha256": {name: sha(checked_path(root, name).read_bytes()) for name in dependencies},
        "bounds_sha256": sha(canonical(bounded)), "reference_encoding": module(root, "food_reference_encoding").ENCODING_VERSION,
        "food_assessment": getattr(audit, "VERSION", "exact-question-echo-assessment-1"),
        "next_runtime_factory": "src/champion_athletic_map/operational_runtime.py:build_runtime",
        "next_assessment_factory": "src/champion_athletic_map/food_answer_audit.py:make_assessor",
        "candidate_only": True, "model_calls": 0, "earlier_results_changed": False,
        "accepted_study_profiles": 0, "protocol_frozen": False,
        "backend_confirmation": "pending_new_reference_representation_and_bounded_outputs"}
    digest = sha(canonical(identity))
    folder = root / "artifacts/pilot/operational_corrections" / ("corrections_" + digest[:20])
    save_once(folder / "configuration.json", identity)
    save_once(folder / "request_bounds.json", bounded)
    save_once(folder / "diagnosis.json", {"diagnostics": diagnostics, "new_food_assessments": food_reviews,
        "blocked_request_measurement": measurement, "original_designated_outcomes_preserved": True})
    summary = {**identity, "configuration_id": digest, "saved_replies_reviewed": len(source["cases"]),
        "question_echo_only_answers": sum(any(check["check_id"] == "food_answer_completeness"
            and check["status"] == "violated" and (check.get("food_answer_audit") or {}).get("question_echo_count", 0) > 0
            for check in item["checks"]) for item in food_reviews),
        "local_budget_measurement": measurement,
        "candidate_files": {path.relative_to(root).as_posix(): sha(path.read_bytes()) for path in folder.iterdir() if path.is_file()},
        "new_model_calls": 0, "http_requests": 0, "query_encodings": 0,
        "new_runtime_executed": False, "full_pilot_completed": False, "final_scores_computed": False,
        "app_generation_enabled": False,
        "software_evidence": software_evidence or {"status": "not_recorded_by_this_invocation"}}
    (root / SUMMARY).write_bytes(canonical(summary) + b"\n")
    return summary


def print_summary(summary):
    print("Saved replies reviewed:", summary["saved_replies_reviewed"], "| Question-only food replies:", summary["question_echo_only_answers"])
    print("Food identifier and URL lengths: bounded | Reference encoding: lossless")
    print("Saved blocked request: fits offline | New model calls: 0 | Backend confirmation: pending")
    print("Saved: " + SUMMARY)
