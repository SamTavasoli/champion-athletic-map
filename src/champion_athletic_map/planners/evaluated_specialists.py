"""Check a specialist draft and allow two fully assessed coordinator revisions."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from threading import Lock
from time import perf_counter


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _coverage(report, policy):
    if not isinstance(report, dict):
        return False
    expected, required = policy.get("expected_check_ids"), policy.get("required_check_ids")
    rows = report.get("checks") if isinstance(report, dict) else None
    if (report.get("execution_status") != "completed" or type(expected) is not list or not expected
            or len(set(expected)) != len(expected) or type(required) is not list
            or len(set(required)) != len(required) or not set(required) <= set(expected)
            or type(rows) is not list or not rows):
        return False
    if (any(type(row) is not dict for row in rows)
            or len(rows) != len(expected) or {row.get("check_id") for row in rows} != set(expected)):
        return False
    return all(type(row.get("required")) is bool and row["required"] == (row["check_id"] in required)
               and row.get("status") in ("met", "violated", "unknown", "not_applicable")
               and (row["status"] != "not_applicable" or isinstance(row.get("reason"), str) and row["reason"].strip())
               for row in rows)


def assess_acceptance(check_report, evaluator_parsed, policy):
    """Apply our fixed policy; model opinions never replace required coded results."""
    coverage = _coverage(check_report, policy)
    rows = check_report.get("checks", []) if isinstance(check_report, dict) else []
    required = set(policy.get("required_check_ids", []))
    blocking = [row["check_id"] for row in rows if isinstance(row, dict) and row.get("check_id") in required
                and row.get("status") not in ("met", "not_applicable")]
    issues = evaluator_parsed.get("issues") if isinstance(evaluator_parsed, dict) else None
    allowed = policy.get("allowed_evaluator_categories", policy.get("blocking_evaluator_categories", []))
    evaluator_valid = (isinstance(evaluator_parsed, dict) and evaluator_parsed.get("assessment_complete") is True
                       and isinstance(issues, list) and all(isinstance(issue, dict) and issue.get("category") in allowed for issue in issues))
    categories = sorted({issue["category"] for issue in issues or []
                         if isinstance(issue, dict) and issue.get("category") in policy.get("blocking_evaluator_categories", [])})
    disagreements = []
    if blocking and evaluator_valid and not categories:
        disagreements.append({"check_ids": list(blocking), "reason": "Required coded findings remain unresolved although the evaluator reported no blocking issue."})
    return {"accepted": bool(coverage and evaluator_valid and not blocking and not categories),
            "coverage_valid": coverage, "evaluator_valid": bool(evaluator_valid),
            "blocking_check_ids": blocking, "blocking_evaluator_categories": categories,
            "disagreements": disagreements}


def model_check_view(report):
    """Group only identical findings while retaining all substantive check information."""
    omit = {"check_id", "candidate_id", "rule_ids", "data_versions", "data_version", "rule_version", "policy_version"}
    groups, by_content = [], {}
    for row in report["checks"]:
        content = {key: copy.deepcopy(value) for key, value in row.items() if key not in omit}
        key = _json(content)
        if key not in by_content:
            by_content[key] = len(groups)
            groups.append({"check_ids": [], **content})
        groups[by_content[key]]["check_ids"].append(row["check_id"])
    if groups and all(set(group) == set(groups[0]) for group in groups):
        columns = list(groups[0])
        return {"execution_status": report["execution_status"], "columns": columns,
                "findings": [[group[key] for key in columns] for group in groups]}
    return {"execution_status": report["execution_status"], "findings": groups}


def candidate_view(result, candidate_id):
    parsed = (result.get("response") or {}).get("model_output") or {}
    raw = parsed.get("raw_text")
    if type(raw) is not str:
        raise ValueError("A completed candidate must retain its exact raw response.")
    content = ({"parsed_object": copy.deepcopy(parsed["parsed_object"])} if parsed.get("parsed_object") is not None
               else {"raw_text": raw})
    return {"candidate_id": candidate_id, **content, "format_valid": bool(result.get("format_valid"))}


class EvaluatedSpecialistPlanner:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._lock = Lock()
        self.last_transport_attempts = {"metadata": 0, "render": 0, "generation": 0}
        self.config = json.loads(self._read("artifacts/planners/version4_config.json"))
        if self.config.get("schema_version") != "planner-v4-config-1" or self.config.get("planner_version") != 4:
            raise ValueError("The evaluated planner needs its saved Version 4 configuration.")
        if self.config.get("maximum_revisions") != 2 or self.config.get("evaluator_output_tokens") != 768:
            raise ValueError("Our evaluated workflow allows two revisions and 768 evaluator output tokens.")
        v3 = json.loads(self._read("artifacts/planners/version3_config.json", self.config["baseline_v3_config_sha256"]))
        for name, digest in self.config["module_sha256"].items():
            self._read(name, digest)
        self.policy = json.loads(self._read(self.config["acceptance_policy_path"], self.config["acceptance_policy_sha256"]))
        if (not self.policy.get("expected_check_ids") or not self.policy.get("required_check_ids")
                or not self.policy.get("blocking_evaluator_categories")):
            raise ValueError("The evaluated planner needs complete check coverage and fixed acceptance rules.")
        self.evaluator_schema = json.loads(self._read(self.config["evaluator_schema_path"], self.config["evaluator_schema_sha256"]))
        self.prompts = {role: self._read(item["path"], item["sha256"]).decode("utf-8")
                        for role, item in self.config["prompts"].items()}
        if set(self.prompts) != {"evaluator", "revision"} or any(not value.strip() for value in self.prompts.values()):
            raise ValueError("Our evaluator and revision prompts must be present.")
        original = "src/champion_athletic_map/planners/specialists.py"
        drafting = self._module("champion_v4_original_drafting", original, v3["module_sha256"][original])
        self.drafting = drafting.SpecialistPlanner(self.root)
        self.client, self.instructions = self.drafting.client, self.drafting.instructions
        self.integration, self._adapter = self.drafting.integration, self.drafting._adapter
        self.client.response.Draft202012Validator.check_schema(self.evaluator_schema)
        checks = "src/champion_athletic_map/planning_checks.py"
        checking = self._module("champion_v4_planning_checks", checks, self.config["module_sha256"][checks])
        self.checker = checking.PlanningChecker(self.root, self.client, self.policy)
        transport = "src/champion_athletic_map/evaluated_role_adapter.py"
        roles = self._module("champion_v4_evaluated_role_transport", transport, self.config["module_sha256"][transport])
        self.roles = roles.EvaluatedRoleAdapter(self.root, self.client, self._adapter, self.integration)

    def _read(self, relative, expected=None):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("An evaluated-planner dependency leaves our project.")
        data = path.read_bytes()
        if expected is not None and _sha(data) != expected:
            raise ValueError("A saved evaluated-planner dependency changed: " + path.name)
        return data

    def _module(self, name, relative, expected):
        source = self._read(relative, expected)
        module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, self.root / relative))
        exec(compile(source, str(self.root / relative), "exec"), module.__dict__)
        return module

    def generate(self, public_record, reference_packet, call_id):
        with self._lock:
            started = perf_counter()
            totals = {"metadata": 0, "render": 0, "generation": 0}
            self.last_transport_attempts = dict(totals)
            history, check_results, recorded_roles = [], [], []
            draft, final, terminal, selected, failed_stage, error = None, None, "execution_error", None, None, None
            revisions_used = 0

            def add_role(stage, result, candidate_id=None):
                recorded_roles.append({"stage": stage, "candidate_id": candidate_id, "result": result})
                for key in totals:
                    totals[key] += result.get("transport_attempts", {}).get(key, 0)
                self.last_transport_attempts = dict(totals)

            def call_role(stage, envelope, candidate_id, ordinal):
                try:
                    result = self.roles.generate(public_record, reference_packet,
                        self.instructions + "\n\n" + self.prompts[stage], call_id + "_" + stage + str(ordinal),
                        stage=stage, output_schema=self.evaluator_schema if stage == "evaluator" else None,
                        output_tokens=768 if stage == "evaluator" else 2048,
                        specialist_notes=envelope, planner_version=4)
                except Exception as failure:
                    result = {"status": "blocked", "format_valid": False, "completion_valid": False,
                              "response": None, "cached": False, "error": str(failure),
                              "transport_attempts": dict(self.roles.last_transport_attempts)}
                add_role(stage, result, candidate_id)
                return result

            try:
                draft = self.drafting.draft(public_record, reference_packet, call_id + "_draft", planner_version=4)
                for stage in draft.get("stages", []):
                    if stage.get("execution") == "recorded":
                        add_role(stage["stage"], stage["result"], "candidate_0" if stage["stage"] == "coordinator" else None)
                if not draft.get("completion_valid"):
                    failed_stage = draft.get("failed_stage") or "initial_draft"
                    error = draft.get("failed_stage_error") or draft.get("error") or "The required drafting procedure did not complete."
                else:
                    notes = copy.deepcopy(draft["specialist_notes"])
                    current = draft
                    for ordinal in range(self.config["maximum_revisions"] + 1):
                        candidate_id = "candidate_" + str(ordinal)
                        view = candidate_view(current, candidate_id)
                        try:
                            report = self.checker.check(public_record, current, reference_packet, candidate_id=candidate_id)
                        except Exception as failure:
                            report = {"execution_status": "error", "candidate_id": candidate_id,
                                      "checks": [], "error": type(failure).__name__ + ": " + str(failure)}
                        check_results.append(report)
                        entry = {"candidate_id": candidate_id, "parent_candidate_id": None if ordinal == 0 else "candidate_" + str(ordinal - 1),
                                 "candidate": current, "check_report": report, "evaluator_result": None, "acceptance": None}
                        history.append(entry)
                        if not _coverage(report, self.policy):
                            failed_stage, error = "checker", report.get("error") or "The coded checks did not complete with the required coverage and policy flags."
                            break
                        envelope = {"notes": notes, "candidate": view, "check_results": model_check_view(report)}
                        evaluator = call_role("evaluator", envelope, candidate_id, ordinal)
                        entry["evaluator_result"] = evaluator
                        if not evaluator.get("completion_valid") or not evaluator.get("format_valid"):
                            failed_stage, error = "evaluator", evaluator.get("error") or "The required evaluator assessment did not complete and validate."
                            break
                        assessment = evaluator["response"]["model_output"]["parsed_object"]
                        acceptance = assess_acceptance(report, assessment, self.policy)
                        entry["acceptance"] = acceptance
                        if not acceptance["evaluator_valid"]:
                            failed_stage, error = "evaluator", "The evaluator did not provide a complete assessment under the saved policy."
                            break
                        if acceptance["accepted"]:
                            final, terminal, selected = current, "internally_accepted", candidate_id
                            break
                        if ordinal == self.config["maximum_revisions"]:
                            final, terminal, selected = current, "revision_limit_reached", candidate_id
                            break
                        revision = call_role("revision", {**envelope, "evaluator_assessment": assessment}, candidate_id, ordinal + 1)
                        revisions_used += 1
                        if not revision.get("completion_valid"):
                            failed_stage, error = "revision", revision.get("error") or "The required coordinator revision did not complete."
                            break
                        current = revision
            except Exception as failure:
                failed_stage, error = failed_stage or "workflow", type(failure).__name__ + ": " + str(failure)
                for key in totals:
                    totals[key] = max(totals[key], getattr(self.drafting, "last_transport_attempts", {}).get(key, 0))
                self.last_transport_attempts = dict(totals)

            reused = sum(role["result"].get("cached") is True for role in recorded_roles)
            if final is None:
                unresolved = any(role["result"].get("status") == "unresolved" for role in recorded_roles)
                blocked = any(role["result"].get("status") == "blocked" for role in recorded_roles)
                final = {"status": "unresolved" if unresolved else "blocked" if blocked else "failed", "format_valid": False,
                         "completion_valid": False, "response_type": None, "response": None, "error": error,
                         "failed_stage": failed_stage}
            return {**final, "planner_version": 4, "job_call_id": call_id, "terminal_state": terminal,
                    "internally_accepted": terminal == "internally_accepted", "selected_candidate_id": selected,
                    "revisions_used": revisions_used, "draft_result": draft, "history": history, "check_results": check_results,
                    "roles": recorded_roles, "stages": recorded_roles, "failed_stage": failed_stage,
                    "cached": bool(recorded_roles) and reused == len(recorded_roles),
                    "saved_stage_responses_reused": reused, "logical_stage_calls": len(recorded_roles),
                    "transport_attempts": dict(totals), "reference_packet_id": reference_packet["packet_id"],
                    "reference_calls": 0, "classifier_calls": 0, "evaluator_calls": sum(role["stage"] == "evaluator" for role in recorded_roles),
                    "elapsed_seconds": perf_counter() - started, "operational_generation_ready": False}
