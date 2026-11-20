"""Compose candidate-focused revisions and explicit food-answer checks privately."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


VERSION = "bounded-revision-food-validation-runtime-1"
LIVE = "src/champion_athletic_map/live_reviewed_runtime.py"
FROZEN = "src/champion_athletic_map/reviewed_runtime.py"
CHECKS = "src/champion_athletic_map/reviewed_planning_checks.py"
SOURCES = tuple("src/champion_athletic_map/" + name + ".py" for name in
                ("corrected_runtime", "bounded_revision", "food_response_validation")) + (LIVE, FROZEN, CHECKS)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def load(root, relative):
    path = (Path(root).resolve() / relative).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("A corrected runtime source leaves the project.")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("corrected_" + path.stem, path))
    result.__spec__.loader.exec_module(result)
    return result


def food_checker_api(root):
    """Change only food interpretation inside an isolated copy of the prior checker."""
    checks = load(root, CHECKS)
    validation = load(root, "src/champion_athletic_map/food_response_validation.py")
    original_module = checks._module
    def modules(project, name):
        value = original_module(project, name)
        if name == "food_fact_focus":
            value = SimpleNamespace(**{**value.__dict__, "assess_food": validation.assess_food})
        return value
    checks._module = modules
    return checks


def revision_role(previous, revision):
    """Keep the existing role and transport code; change the revision input only."""
    class CorrectedRevisionRole(type(previous)):
        def prepare_request(self, *args, **kwargs):
            prepared, payload, configuration = super().prepare_request(*args, **kwargs)
            stage = kwargs.get("stage", configuration.get("stage"))
            if stage != "revision":
                return prepared, payload, configuration
            prepared, payload, configuration = revision.transform_request(
                prepared, payload, configuration, stage=stage)
            # The final request still passes the original byte, control and schema guards.
            self._budget_view(payload)
            return prepared, payload, configuration
    result = CorrectedRevisionRole.__new__(CorrectedRevisionRole)
    result.__dict__ = dict(previous.__dict__)
    return result


def build_runtime(root, review_config, public_schema, *, public_record, runtime_builder=None):
    root = Path(root).resolve()
    sources = {name: sha((root / name).read_bytes()) for name in SOURCES}
    live = load(root, LIVE)
    original_live_load = live.load
    def live_load(project, relative):
        value = original_live_load(project, relative)
        if relative == FROZEN:
            previous_load = value.load
            def reviewed_load(project_root, source):
                return food_checker_api(project_root) if source == CHECKS else previous_load(project_root, source)
            value.load = reviewed_load
        return value
    live.load = live_load
    runtime = live.build_runtime(root, deepcopy(review_config), deepcopy(public_schema),
        public_record=deepcopy(public_record), runtime_builder=runtime_builder)
    revision = load(root, "src/champion_athletic_map/bounded_revision.py")
    previous_manifest, previous_policy = deepcopy(runtime.manifest), deepcopy(runtime.reference_policy)
    engine = runtime.planners[4].planner
    previous_role = engine.roles
    if sum(row["target"] is previous_role for row in runtime.roles) != 1:
        raise ValueError("The revision role is missing or duplicated in the tracing inventory.")
    changed_role = revision_role(previous_role, revision)
    base_api = load(root, "src/champion_athletic_map/operational_runtime.py")
    identity = {"runtime_version": VERSION,
        "base_runtime_identity": base_api.identity_view(previous_manifest), "source_sha256": sources,
        "revision_input_policy": "candidate_facts_sources_complete_checks_evaluator;generated_notes_archived_only",
        "food_validation_policy": "numeric_claims_and_required_field_completeness_assessed_separately",
        "injected_runtime_builder": runtime_builder is not None}
    identifier = sha(canonical(identity))
    policy = {**previous_policy, "source_configuration_sha256": identifier}
    engine.roles = changed_role
    runtime.roles = [{**row, "target": changed_role if row["target"] is previous_role else row["target"]}
                     for row in runtime.roles]
    nodes = [runtime.planners[v] for v in range(1, 5)] + [engine, engine.drafting]
    for node in nodes:
        node.config = deepcopy(node.config)
        if "reference_policy" in node.config:
            node.config["reference_policy"] = deepcopy(policy)
        if hasattr(node, "roles"):
            node.roles.reference_policy = deepcopy(policy)
    runtime.reference_policy = deepcopy(policy)
    runtime.reference_preparer_factory, runtime.assessor_factory = build_reference_preparer, make_assessor
    runtime.manifest = {**previous_manifest, "runtime_version": VERSION,
        "base_runtime_manifest": previous_manifest, "corrected_runtime_configuration": identity,
        "corrected_runtime_configuration_sha256": identifier,
        "effective_reference_policy": deepcopy(policy),
        "verified_file_sha256": {**previous_manifest.get("verified_file_sha256", {}), **sources},
        "revision_input_changed_only_for_v4_revision_stage": True,
        "generated_specialist_notes_retained_in_audit_not_revision_prompt": True,
        "authoritative_facts_reference_data_candidate_and_check_evidence_preserved": True,
        "food_numeric_and_required_field_checks_separate": True,
        "model_output_autofilled_or_repaired": False,
        "baseline_reference_access_changed": False, "budget_guards_changed": False,
        "output_and_context_limits_changed": False, "original_sources_modified": False,
        "model_calls_during_construction": 0, "query_encoding_during_construction": 0,
        "new_backend_count_agreement_verified": False, "operational_generation_ready": False}
    return runtime


def make_assessor(root, public_schema):
    root = Path(root).resolve()
    assessor = food_checker_api(root).make_assessor(root, public_schema)
    active = {name: sha((root / name).read_bytes()) for name in
              ("src/champion_athletic_map/corrected_runtime.py",
               "src/champion_athletic_map/food_response_validation.py")}
    assessor.dependency_sha256.update(active)
    original_assess = assessor.assess
    def assess(*args, **kwargs):
        result = original_assess(*args, **kwargs)
        result["food_validation_correction_version"] = VERSION
        result["food_validation_active_source_sha256"] = deepcopy(active)
        result["original_saved_assessments_changed"] = False
        return result
    assessor.assess = assess
    return assessor


def build_reference_preparer(root, tools, client, policy, **kwargs):
    root = Path(root).resolve()
    preparer = load(root, LIVE).build_reference_preparer(root, tools, client, policy, **kwargs)
    for relative in SOURCES:
        preparer.module_bindings[relative] = sha((root / relative).read_bytes())
    preparer.setup_record["module_bindings"] = deepcopy(preparer.module_bindings)
    preparer.setup_record["corrected_runtime_version"] = VERSION
    return preparer


make_reference_preparer = build_reference_preparer
