"""Compose prospective reviewed inputs and checks without changing saved runs."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import MethodType, SimpleNamespace


RUNTIME_VERSION = "reviewed-development-runtime-1"
COMMON_GUIDANCE = (
    "Keep every supplied commitment's date, time, duration and reference. All activity IDs are unique. "
    "Separate sessions have parent_activity_id null; components name a different, present parent on the same date. "
    "Meet the requested extra-session count within supplied limits. Specify each new drill's action, setup and "
    "participant roles from complete supplied catalog variants; unknown requirements stay unresolved. Use only "
    "supplied source IDs. Broad goals are sufficient; confirmed empty commitments mean none. Ask for essential "
    "missing facts. Rehabilitation and personalized calorie/meal prescriptions are outside_scope. Explain actual "
    "conflicts with supplied facts."
)
FINAL_FOOD_GUIDANCE = (
    "Answer food questions with supported food, mass, nutrient, amount, unit and source_ref in food_facts. "
    "Read requested_food_facts and its source qualifications. A copied question is not an answer. "
    "If unsupported, state exactly what is unknown; never invent a value."
)
FOOD_ROLE_GUIDANCE = (
    "Read requested_food_facts and its source qualifications alongside the complete reference_data. "
    "Put the supported food, mass, nutrient, amount, unit and source attribution in your note recommendations. "
    "If unsupported, state exactly what is unknown. A copied question is not an answer."
)
_SHARED_NOTICE = "docs/prompts/shared_task_addendum_candidate.txt"
_COMPONENTS = tuple("src/champion_athletic_map/" + name + ".py" for name in
    ("reviewed_runtime", "selected_drill_context", "food_fact_focus", "reviewed_planning_checks",
     "operational_runtime", "food_reference_encoding", "pilot_references", "contract_runtime")) + (_SHARED_NOTICE,)
_POINTER = "artifacts/language_model/active_resource_release.json"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def load(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("A reviewed-runtime source leaves the project.")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("reviewed_" + path.stem, path))
    exec(compile(path.read_bytes(), str(path), "exec"), result.__dict__)
    return result


def release_bindings(root):
    pointer_bytes = (root / _POINTER).read_bytes()
    pointer = json.loads(pointer_bytes)
    folder = (root / pointer["release_directory"]).resolve()
    if not folder.is_relative_to(root):
        raise ValueError("The approved-resource release leaves the project.")
    manifest = folder / "manifest.json"
    digest = sha(manifest.read_bytes())
    if digest != pointer["manifest_sha256"]:
        raise ValueError("The approved-resource release manifest changed.")
    return {"resource_release_manifest_sha256": digest,
            "active_resource_pointer_sha256": sha(pointer_bytes)}, {
                _POINTER: sha(pointer_bytes), manifest.relative_to(root).as_posix(): digest}


def _has_question(view):
    public = view.get("athlete_input") if isinstance(view, dict) else None
    question = public.get("food_question") if isinstance(public, dict) else None
    return isinstance(question, str) and bool(question.strip())


def focused_request(prepared, payload, configuration, *, food, codec, strict_decode, budget, stage=None,
                    old_food_notice=None):
    """Enrich only private reference-enabled inputs, retaining the original data."""
    payload, configuration = deepcopy(payload), dict(configuration)
    view = codec.decode_view(strict_decode(payload["messages"][1]["content"].encode("utf-8")))
    if not isinstance(view, dict) or "athlete_input" not in view or "reference_data" not in view or "response_type" in view:
        raise ValueError("The reviewed request needs the complete original public/reference view.")
    focused = food.attach_food_focus(view) if _has_question(view) else deepcopy(view)
    if "requested_food_facts" in view and canonical(view["requested_food_facts"]) != canonical(focused.get("requested_food_facts")):
        raise ValueError("A supplied food-focus view differs from its original source facts.")
    restored = deepcopy(focused)
    restored.pop("requested_food_facts", None)
    original = deepcopy(view)
    original.pop("requested_food_facts", None)
    if canonical(restored) != canonical(original):
        raise ValueError("Food focus changed the original model input.")
    encoded = codec.encode_view(focused)
    if canonical(codec.decode_view(encoded)) != canonical(focused):
        raise ValueError("Food focus did not preserve the lossless reference encoding.")
    payload["messages"][1]["content"] = canonical(encoded).decode("utf-8")
    if stage == "food":
        system = payload["messages"][0]["content"]
        if not isinstance(old_food_notice, str) or system.count(old_food_notice) != 1:
            raise ValueError("The original prospective food-role guidance changed.")
        payload["messages"][0]["content"] = system.replace(old_food_notice, FOOD_ROLE_GUIDANCE, 1)
    configuration.update(reviewed_runtime=RUNTIME_VERSION,
        requested_food_focus_version=food.VERSION,
        requested_food_focus_present="requested_food_facts" in focused,
        requested_food_focus_sha256=sha(canonical(focused["requested_food_facts"])) if "requested_food_facts" in focused else None,
        original_public_and_reference_values_preserved=True,
        food_focus_is_input_only=True,
        message_sha256=[sha(row["content"].encode("utf-8")) for row in payload["messages"]])
    budget(payload)
    return prepared, payload, configuration


def focused_role(previous, food, codec, strict_decode, old_food_notice):
    class ReviewedInputRole(type(previous)):
        def prepare_request(self, *args, **kwargs):
            prepared, payload, configuration = super().prepare_request(*args, **kwargs)
            return focused_request(prepared, payload, configuration, food=food, codec=codec,
                strict_decode=strict_decode, budget=self._budget_view, stage=kwargs.get("stage"),
                old_food_notice=old_food_notice)
    result = ReviewedInputRole.__new__(ReviewedInputRole)
    result.__dict__ = dict(previous.__dict__)
    return result


def concise_instructions(root, previous, contract, *, injected=False):
    """Replace only the two exact prospective addenda; retain original task text."""
    shared_notice = (root / _SHARED_NOTICE).read_text(encoding="utf-8")
    if not shared_notice.strip():
        raise ValueError("The original prospective shared-task notice is empty.")
    text, replacements = previous, []
    for name, notice in (("shared_task_candidate", shared_notice), ("request_contract_candidate", contract.COMMON_NOTICE)):
        count = text.count("\n\n" + notice)
        if count != 1:
            if injected and name == "shared_task_candidate" and count == 0:
                continue
            raise ValueError("An exact prospective instruction stanza changed: " + name)
        text = text.replace("\n\n" + notice, "", 1)
        replacements.append(name)
    return text + "\n\n" + COMMON_GUIDANCE + "\n\n" + FINAL_FOOD_GUIDANCE, replacements


def build_runtime(root, review_config, public_schema, *, public_record, runtime_builder=None):
    """Build candidate objects only; generation and reference preparation stay explicit."""
    root = Path(root).resolve()
    sources = {name: sha((root / name).read_bytes()) for name in _COMPONENTS}
    binding_policy, resource_sources = release_bindings(root)
    sources.update(resource_sources)
    operational = load(root, "src/champion_athletic_map/operational_runtime.py")
    food = load(root, "src/champion_athletic_map/food_fact_focus.py")
    codec = load(root, "src/champion_athletic_map/food_reference_encoding.py")
    checks = load(root, "src/champion_athletic_map/reviewed_planning_checks.py")
    selected = load(root, "src/champion_athletic_map/selected_drill_context.py")
    contract = load(root, "src/champion_athletic_map/contract_runtime.py")
    builder = runtime_builder or operational.build_runtime
    runtime = builder(root, deepcopy(review_config), deepcopy(public_schema), public_record=deepcopy(public_record))
    planners = runtime.planners
    if set(planners) != {1, 2, 3, 4}:
        raise ValueError("The reviewed runtime requires four isolated planners.")
    engine, drafting = planners[4].planner, planners[4].planner.drafting
    nodes = [("v1", planners[1]), ("v2", planners[2]), ("v3", planners[3]),
             ("v4", planners[4]), ("v4.evaluated", engine), ("v4.drafting", drafting)]
    clients = [planners[number].client for number in range(1, 5)]
    base_manifest, base_policy = deepcopy(runtime.manifest), deepcopy(runtime.reference_policy)
    if (base_manifest.get("runtime_version") != operational.RUNTIME_VERSION
            or len({id(client) for client in clients}) != 4
            or engine.client is not clients[3] or drafting.client is not clients[3]
            or any(node.instructions != nodes[0][1].instructions for _, node in nodes)
            or base_manifest.get("effective_reference_policy") != base_policy):
        raise ValueError("The recorded operational planner graph changed.")
    expected_roles = [(label + ".roles", node.roles) for label, node in nodes if hasattr(node, "roles")]
    if (len(expected_roles) != 3 or len(runtime.roles) != 3
            or [(row["label"], id(row["target"])) for row in runtime.roles]
               != [(label, id(role)) for label, role in expected_roles]):
        raise ValueError("The complete role tracing inventory changed.")
    adapters = {id(node.client): node._adapter for node in (planners[2], planners[3], engine)}
    if len({id(value) for value in adapters.values()}) != 3 or planners[1]._adapter in adapters.values():
        raise ValueError("Reference-enabled adapters must remain private and separate from the baseline.")
    for _, node in nodes:
        if ("reference_policy" in node.config and node.config["reference_policy"] != base_policy
                or hasattr(node, "roles") and (node.roles.reference_policy != base_policy
                    or node.roles.shared is not adapters[id(node.client)])):
            raise ValueError("A planner or role differs from the common reference policy.")
    if not hasattr(engine.checker, "resources"):
        raise ValueError("The internal checker resource bindings are unavailable.")
    checker = checks.make_checker(root, engine.client, engine.policy, resources=engine.checker.resources)
    if checker.client is not engine.client:
        raise ValueError("The reviewed internal checker uses another public-input client.")
    validators = []
    for node in (planners[3], drafting):
        if not hasattr(node, "_preparation"):
            raise ValueError("A specialist packet validator is unavailable.")
        validators.append((node, SimpleNamespace(**{**node._preparation.__dict__, "validate_packet": selected.validate_packet})))
    decoders = {key: value._decode for key, value in adapters.items()}
    if any(not callable(value) for value in decoders.values()):
        raise ValueError("A strict private input decoder is unavailable.")
    replacements = {id(role): focused_role(role, food, codec, decoders[id(role.client)], contract.FOOD_NOTICE)
                    for _, role in expected_roles}
    previous_instructions = nodes[0][1].instructions
    instructions, replaced_stanzas = concise_instructions(root, previous_instructions, contract,
        injected=runtime_builder is not None)
    before_tokens = len(clients[0].encoder.encode(previous_instructions, parse_special=False))
    after_tokens = len(clients[0].encoder.encode(instructions, parse_special=False))
    instruction_change = {"replaced_exact_prospective_stanzas": replaced_stanzas,
        "old_bytes": len(previous_instructions.encode("utf-8")), "new_bytes": len(instructions.encode("utf-8")),
        "byte_delta": len(instructions.encode("utf-8")) - len(previous_instructions.encode("utf-8")),
        "old_instruction_tokens": before_tokens, "new_instruction_tokens": after_tokens,
        "instruction_token_delta": after_tokens - before_tokens,
        "token_count_basis": "configured_encoder_instruction_text_only; complete_backend_request_pending"}
    identity = {"runtime_version": RUNTIME_VERSION,
        "base_runtime_identity": operational.identity_view(base_manifest), "component_sha256": sources,
        "effective_instructions_sha256": sha(instructions.encode("utf-8")),
        "common_guidance_sha256": sha(COMMON_GUIDANCE.encode("utf-8")),
        "food_focus_version": food.VERSION, "food_role_guidance_sha256": sha(FOOD_ROLE_GUIDANCE.encode("utf-8")),
        "final_food_guidance_sha256": sha(FINAL_FOOD_GUIDANCE.encode("utf-8")), "instruction_change": instruction_change,
        "approved_resource_bindings": binding_policy,
        "internal_checker_source_sha256": sources["src/champion_athletic_map/reviewed_planning_checks.py"],
        "injected_runtime_builder": runtime_builder is not None}
    identifier = sha(canonical(identity))
    policy = {**base_policy, **binding_policy, "source_configuration_sha256": identifier}
    old_v2_prepare = planners[2].client.prepare_request
    def prepared_v2(self, *args, **kwargs):
        prepared, payload, configuration = old_v2_prepare(*args, **kwargs)
        return focused_request(prepared, payload, configuration, food=food, codec=codec,
            strict_decode=decoders[id(self)], budget=self._budget_view)
    # The frozen RAG guard still checks the exact original public/reference envelope.
    # A supplemental source-derived focus must first validate before it is removed for that comparison.
    original_v2_decode = decoders[id(clients[1])]
    def guarded_v2_decode(data):
        value = original_v2_decode(data)
        if isinstance(value, dict) and "athlete_input" in value and "reference_data" in value and "response_type" not in value:
            if _has_question(value) and "requested_food_facts" not in value:
                raise ValueError("The requested source-derived food focus is missing.")
            if "requested_food_facts" in value:
                expected = food.make_food_focus(value["athlete_input"], value["reference_data"])
                if not _has_question(value) or canonical(value["requested_food_facts"]) != canonical(expected):
                    raise ValueError("The source-derived requested food facts changed.")
                value = deepcopy(value)
                value.pop("requested_food_facts")
        return value
    planners[2].client.prepare_request = MethodType(prepared_v2, planners[2].client)
    adapters[id(clients[1])]._decode = guarded_v2_decode
    for node, preparation in validators:
        node._preparation = preparation
    for _, node in nodes:
        node.instructions = instructions
        node.config = deepcopy(node.config)
        if "reference_policy" in node.config:
            node.config["reference_policy"] = deepcopy(policy)
        if hasattr(node, "roles"):
            node.roles = replacements[id(node.roles)]
            node.roles.reference_policy = deepcopy(policy)
    runtime.roles = [{**row, "target": replacements[id(row["target"])]} for row in runtime.roles]
    engine.checker = runtime.checker = checker
    runtime.reference_policy = deepcopy(policy)
    runtime.reference_preparer_factory = build_reference_preparer
    runtime.assessor_factory = make_assessor
    runtime.manifest = {**base_manifest, "runtime_version": RUNTIME_VERSION, "base_runtime_manifest": base_manifest,
        "reviewed_runtime_configuration": identity, "reviewed_runtime_configuration_sha256": identifier,
        "effective_reference_policy": deepcopy(policy), "effective_instructions_sha256": identity["effective_instructions_sha256"],
        "verified_file_sha256": {**base_manifest.get("verified_file_sha256", {}), **sources},
        "checker_policy": deepcopy(getattr(checker, "pilot_schedule_policy", {})),
        "instruction_change": instruction_change,
        "internal_v4_checker_updated": True, "specialist_packet_validators_updated": True,
        "common_instructions_applied_to_all_six_nodes": True, "three_role_trace_targets_preserved": True,
        "requested_food_focus_applied_to_versions": [2, 3, 4], "baseline_reference_access_changed": False,
        "food_focus_is_input_only": True, "all_reference_values_and_qualifications_preserved": True,
        "candidate_and_check_encoding_retained": True, "legacy_files_modified": False,
        "output_and_context_limits_changed": False, "acceptance_policy_changed": False,
        "constructor_test_doubles": bool(base_manifest.get("constructor_test_doubles")) or runtime_builder is not None,
        "model_calls_during_construction": 0, "query_encoding_during_construction": 0,
        "new_native_backend_contract_verified": False, "operational_generation_ready": False}
    return runtime


def build_reference_preparer(root, tools, client, policy, *, preparer_api=None, builder_module=None):
    """Use the original fresh-job machinery with explicitly reviewed production components."""
    root = Path(root).resolve()
    expected, release_sources = release_bindings(root)
    if any(policy.get(key) != value for key, value in expected.items()):
        raise ValueError("The reference policy belongs to another approved-resource release.")
    api = preparer_api or load(root, "src/champion_athletic_map/pilot_references.py")
    selected = builder_module or load(root, "src/champion_athletic_map/selected_drill_context.py")
    test_injection = preparer_api is not None or builder_module is not None
    # Keep the original exact-source guards even though the public factory supports injection.
    for name in api._MODULES:
        api._module(root, name)
    preparer = api.FreshReferencePreparer(root, tools, client, policy,
        builder=selected, validator=selected.validate_packet)
    preparer.module_bindings = {"src/champion_athletic_map/" + name + ".py": digest for name, digest in api._MODULES.items()}
    components = {name: sha((root / name).read_bytes()) for name in _COMPONENTS}
    preparer.module_bindings.update(components)
    preparer.module_bindings.update(release_sources)
    preparer.setup_record.update(module_bindings=deepcopy(preparer.module_bindings),
        original_constructor_dependency_injection=True,
        dependency_injection_kind="explicit_test_dependencies" if test_injection else "reviewed_production_builder_and_validator",
        injected_test_dependencies=test_injection,
        reviewed_production_component_sha256=components)
    return preparer


def make_assessor(root, public_schema):
    return load(Path(root).resolve(), "src/champion_athletic_map/reviewed_planning_checks.py").make_assessor(root, public_schema)


make_reference_preparer = build_reference_preparer
