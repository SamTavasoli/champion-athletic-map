"""Exclude exact question echoes from food-claim assessment without editing replies."""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unicodedata


VERSION = "exact-question-echo-assessment-1"
_IDENTIFIERS = {"food_id", "source_ref", "evidence_refs", "activity_id", "parent_activity_id",
    "existing_commitment_refs", "response_type", "date", "start_date", "end_date", "timezone",
    "start_time", "end_time", "relationship"}


def normalize(text):
    """Match exact wording after NFC, case and whitespace normalization only."""
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _pointer(path, key):
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _assessment_copy(response, question):
    copied, echoes = deepcopy(response), []
    def visit(value, path=""):
        if isinstance(value, dict):
            return {key: deepcopy(item) if key in _IDENTIFIERS else visit(item, _pointer(path, key))
                for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item, _pointer(path, index)) for index, item in enumerate(value)]
        if isinstance(value, str) and normalize(value) == question:
            echoes.append(path)
            return ""
        return value
    return visit(copied), echoes


def assess_food(public, response, packet, *, base_assess_food):
    """Assess original claims while treating an exact copied question as a nonclaim.

    Only a private food-assessment copy is changed. It is never used as a model
    output, schema-validation result or planning input. Other unsupported wording
    and honest uncertainty retain the frozen assessor's original treatment.
    """
    if not isinstance(public, dict) or not callable(base_assess_food):
        raise ValueError("The food audit needs public input and the frozen food assessor.")
    question = public.get("food_question")
    normalized = normalize(question) if isinstance(question, str) and question.strip() else None
    copy, echoes = _assessment_copy(response, normalized) if normalized else (deepcopy(response), [])
    checks = deepcopy(base_assess_food(public, copy, packet))
    if not isinstance(checks, list) or any(not isinstance(item, dict) for item in checks):
        raise ValueError("The frozen food assessor returned no complete finding list.")
    metadata = {"version": VERSION, "question_echo_paths": echoes, "question_echo_count": len(echoes),
        "question_normalized_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None,
        "normalization": "NFC_casefold_whitespace_only", "assessment_copy_only": True,
        "saved_reply_changed": False, "food_answer_or_value_inserted": False,
        "other_unsupported_prose_reclassified": False}
    for item in checks:
        item["food_answer_audit"] = deepcopy(metadata)
        if echoes and item.get("check_id") == "food_answer_completeness" and item.get("status") == "violated":
            item["reason"] = ("The reply repeats the supplied food question without a recognized answer. "
                "The exact question echo is not an asserted numeric food claim.")
    return checks


def _module(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("An audited assessment dependency leaves the project.")
    result = importlib.util.module_from_spec(importlib.util.spec_from_file_location("food_echo_" + path.stem, path))
    result.__spec__.loader.exec_module(result)
    return result


def make_assessor(root, public_schema):
    """Wrap only food interpretation in the unchanged common independent assessor."""
    root = Path(root).resolve()
    original = _module(root, "src/champion_athletic_map/independent_plan_assessment.py")
    source_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    class AuditedIndependentAssessor(original.IndependentAssessor):
        def __init__(self):
            super().__init__(root, public_schema)
            frozen_food = self.food
            self.food = SimpleNamespace(assess_food=lambda public, response, packet:
                assess_food(public, response, packet, base_assess_food=frozen_food.assess_food))
            self.dependency_sha256["src/champion_athletic_map/food_answer_audit.py"] = source_sha256

        def assess(self, *args, **kwargs):
            result = super().assess(*args, **kwargs)
            result["food_answer_audit_version"] = VERSION
            result["food_answer_audit_source_sha256"] = source_sha256
            result["saved_raw_reply_changed"] = False
            return result
    return AuditedIndependentAssessor()
