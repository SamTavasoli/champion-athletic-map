"""Apply the common saved-response checks to each frozen final case.

Case annotations select reporting strata and verify accepted case versions. The
actual public input and actual response determine content-check applicability.
This assessor neither generates nor edits a model response.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

VERSION = "frozen-case-common-response-checks-1"
STATUSES = {"met", "violated", "unknown", "not_applicable"}
CATEGORIES = {"feasible": "plan", "missing_information": "clarification",
              "conflicting_constraints": "constraint_conflict", "outside_scope": "outside_scope"}
POLICY_ALIASES = {
    "USER_AVAILABLE_TIME": ["availability_and_collisions", "additional_training_limits"],
    "USER_EXISTING_COMMITMENTS": ["existing_commitments"],
    "POLICY_REQUIRED_INFORMATION": ["response_type_basis"],
    "POLICY_TIMING_INTEGRITY": ["timing_durations", "availability_and_collisions"],
    "POLICY_SESSION_ACCOUNTING": ["activity_accounting"],
    "POLICY_CATALOG_ELIGIBILITY": ["reference_identity"],
    "POLICY_SCOPE": ["response_type_basis"],
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def module(root, name):
    path = Path(root).resolve() / "src/champion_athletic_map" / (name + ".py")
    spec = importlib.util.spec_from_file_location("final_response_" + name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def combine(rows):
    states = [row["status"] for row in rows]
    return ("violated" if "violated" in states else "unknown" if "unknown" in states else
            "met" if "met" in states else "not_applicable")


def coverage(rows):
    counts = {state: sum(row["status"] == state for row in rows) for state in sorted(STATUSES)}
    denominator = counts["met"] + counts["violated"] + counts["unknown"]
    return {**counts, "parent_checks": len(rows), "applicable_denominator": denominator,
            "determinate_coverage": (counts["met"] + counts["violated"]) / denominator if denominator else None,
            "coverage_is_not_pass_rate": True}



def duration_check(public, response, requests, roots_function, *, structure_valid, supported_nonplan):
    """An upper time allowance never supplies an exact requested duration."""
    duration = requests.requested_duration(public)
    if supported_nonplan:
        state, reason, observed = "not_applicable", "The checked non-plan response prescribes no new practice duration.", None
    elif duration is None:
        state, reason, observed = "not_applicable", "No exact practice-block duration is supported by the literal public request.", None
    else:
        roots, complete = roots_function(response)
        values = [root.get("duration_minutes") for root in roots]
        observed = {"requested_minutes": duration, "known_root_durations": values, "complete_graph": complete}
        if any(type(value) is int and value != duration for value in values):
            state, reason = "violated", "At least one added practice block changes the explicitly requested duration."
        elif not structure_valid or not complete or not roots or any(type(value) is not int for value in values):
            state, reason = "unknown", "Complete added practice-block durations are unavailable."
        else:
            state, reason = "met", "Every added practice block preserves the explicitly requested duration."
    return {"check_id": "requested_session_duration", "status": state, "reason": reason,
        "observed": observed, "required": True, "assessment_version": VERSION}



def goal_check(public, response, *, supported_nonplan):
    """Keep an unimplemented semantic proof visible instead of passing an echo."""
    goals = public.get("goals")
    explicit = [goal for goal in goals if isinstance(goal, str) and goal.strip()] if isinstance(goals, list) else []
    kind = response.get("response_type") if isinstance(response, dict) else None
    if supported_nonplan:
        state, reason = "not_applicable", "The supported non-plan response proposes no practice plan whose skill-goal fulfillment can be checked."
    elif not explicit:
        state, reason = "not_applicable", "No separate explicit public skill-goal target is declared; the other request-content checks still apply."
    else:
        state, reason = "unknown", "The public skill goal has no implemented independent semantic proof for the actual activities. Repeating a goal or resolving a source ID does not verify fulfillment."
    return {"check_id": "public_goal_fulfillment", "status": state, "reason": reason,
        "observed": {"explicit_public_goal_count": len(explicit), "actual_response_type": kind,
                     "semantic_verification_implemented": False, "word_echo_is_not_proof": True},
        "required": True, "assessment_version": VERSION}


def parent_report(checks, annotation):
    """Keep aliases in evidence, while scoring each parent constraint once."""
    by_id = {row["check_id"]: row for row in checks}
    require(len(by_id) == len(checks), "Common response evidence repeats a check identifier.")
    groups, used, aliases = [], set(), {}
    def add(identifier, members, required, **extra):
        require(bool(members) and all(key in by_id for key in members), "A parent constraint has missing check evidence.")
        rows = [by_id[key] for key in members]
        used.update(members)
        groups.append({"check_id": identifier, "status": combine(rows), "required": required,
            "reason": "; ".join(dict.fromkeys(row["reason"] for row in rows)),
            "source_check_ids": members, **extra})
    applicability = annotation.get("rule_applicability") or {}
    for group in applicability.get("numeric_groups", []):
        members = ["rule:" + ref["rule_id"] for ref in group["rule_refs"]]
        add(group["evaluation_group_id"], members, True, operator=group["operator"],
            threshold=group["threshold"], most_restrictive_applicable_threshold=True)
    advisory = {}
    for row in applicability.get("advisory_rules", []):
        identifier = "rule:" + row["rule_id"]
        if identifier in by_id:
            advisory.setdefault(row["evaluation_group_id"], []).append(identifier)
    for identifier, members in advisory.items():
        add("advisory:" + identifier, members, False)
    for identifier, parents in POLICY_ALIASES.items():
        key = "rule:" + identifier
        if key in by_id:
            used.add(key)
            aliases[key] = parents
    for row in checks:
        if row["check_id"] not in used:
            add(row["check_id"], [row["check_id"]], row["required"])
    require(all(row["status"] in STATUSES and row["reason"] for row in groups), "A parent constraint lacks a four-state result.")
    return {"parent_checks": groups, "retained_policy_aliases": aliases,
        "parent_coverage": {"required": coverage([row for row in groups if row["required"]]),
                            "advisory": coverage([row for row in groups if not row["required"]])}}


class FinalResponseAssessor:
    def __init__(self, root, public_schema, case_contracts):
        self.root = Path(root).resolve()
        self.contracts = deepcopy(case_contracts)
        identity = deepcopy(self.contracts)
        declared = identity.pop("contracts_id", None)
        require(declared == sha(packed(identity)), "The frozen response-contract identity differs.")
        bindings = self.contracts.get("case_bindings")
        require(isinstance(bindings, list) and len(bindings) == 200, "The common checks need the complete 200-case contract roster.")
        self.bindings = {row["profile_id"]: row for row in bindings}
        require(len(self.bindings) == 200, "A frozen case contract is duplicated.")
        self.requests = module(self.root, "final_request_checks")
        self.resource_checks = module(self.root, "final_resource_checks")
        self.assessor = module(self.root, "corrected_runtime").make_assessor(self.root, public_schema)
        self._busy = False
        # We isolate the inherited module before changing its literal parser.
        for cls in type(self.assessor).__mro__:
            method = cls.__dict__.get("assess")
            if callable(method) and "requested_count" in method.__globals__:
                method.__globals__["requested_count"] = self.requests.requested_count
                self.roots_function = method.__globals__["added_roots"]
                break
        else:
            raise ValueError("The saved common assessor has no isolated request-count extension point.")
        core = self.assessor.calendar.check.__func__.__globals__
        original_facts, original_basis = core["_request_facts"], core["_basis"]
        core["_request_facts"] = lambda public: self.requests.request_facts(public, original_facts(public))
        def basis(public, response):
            facts = core["_request_facts"](public)
            kind = response.get("response_type")
            if facts.get("outside_scope"):
                return ("met" if kind == "outside_scope" else "violated", "The public request asks for a service outside the basketball-planning prototype.", kind == "outside_scope", facts)
            proof = self.requests.response_conflict_basis(public, response)
            if proof is not None:
                return proof["status"], proof["reason"], proof["supported_nonplan"], facts
            missing = facts.get("essential_missing") or []
            if missing:
                if kind != "clarification":
                    return "violated", "Essential public information remains missing: " + ", ".join(missing) + ".", False, facts
                questions = " ".join(response.get("questions") or []).casefold()
                terms = {"age": ("age", "old"), "availability": ("availab", "date", "time", "window"),
                    "participants": ("participant", "people", "person", "group", "how many"),
                    "existing_commitments": ("existing", "event", "practice", "game", "commitment", "schedule"),
                    "court_or_hoop": ("court", "hoop", "basket", "space", "area")}
                supported = all(field in terms and any(term in questions for term in terms[field]) for field in missing)
                return ("met" if supported else "unknown", "Clarification addresses the essential missing public facts." if supported else
                    "The questions do not establish all essential missing public facts.", supported, facts)
            return original_basis(public, response)
        core["_basis"] = basis
        original_resources = self.assessor.resources
        adopted = {"records": list(self.assessor.calendar.resources["drills"].values()),
                   "aliases": deepcopy(self.assessor.calendar.resources.get("aliases", {}))}
        self.resource_coverage = self.resource_checks.coverage_spec(self.assessor.resource_contracts, adopted)
        self.assessor.resources = SimpleNamespace(assess_resources=lambda public, activities, contracts:
            self.resource_checks.assess_resources(public, activities, contracts, checker=original_resources, adopted_drills=adopted))

    def _binding(self, record, annotation):
        require(isinstance(record, dict) and set(record) == {"profile_id", "schema_version", "input"}, "Only the frozen public case wrapper may enter common checks.")
        binding = self.bindings.get(record["profile_id"])
        require(binding is not None and binding["public_record_canonical_sha256"] == sha(canonical(record))
            and binding["public_input_canonical_sha256"] == sha(canonical(record["input"])), "The case differs from its frozen response contract.")
        require(annotation.get("profile_id") == record["profile_id"] and annotation.get("public_record_sha256") == sha(packed(record))
            and annotation.get("case_authoring_accepted") is True and annotation.get("case_category") in CATEGORIES,
            "A final response needs the accepted annotation for this exact case version.")
        bundle = self.contracts["contract_bundles"][binding["contract_bundle_id"]]
        require(sha(canonical(bundle)) == binding["contract_bundle_id"]
            and sha(canonical(bundle["local_response_schema"])) == binding["local_response_schema_sha256"],
            "The case's exact local response schema differs from its frozen binding.")
        return binding, bundle

    def validate_case_binding(self, public_record, case_annotation):
        binding, _bundle = self._binding(public_record, case_annotation)
        return {"profile_id": public_record["profile_id"], "public_record_sha256": sha(packed(public_record)),
            "contract_bundle_id": binding["contract_bundle_id"],
            "effective_local_schema_sha256": binding["local_response_schema_sha256"],
            "accepted_case_version_verified": True}

    def assess(self, public_record, outcome, truth_packet, *, assessment_id, case_annotation):
        require(not self._busy, "The common assessor handles one designated outcome at a time.")
        self._busy = True
        try:
            binding, bundle = self._binding(public_record, case_annotation)
            require(isinstance(outcome, dict), "A designated saved workflow outcome is required.")
            # Both inherited parser paths receive the identical effective schema.
            for client in (self.assessor.client, self.assessor.calendar.client):
                client.response_schema = deepcopy(bundle["local_response_schema"])
            original_calendar_check = self.assessor.calendar.check
            def safe_calendar_check(*args, **kwargs):
                result = original_calendar_check(*args, **kwargs)
                if result.get("format_valid") is not True:
                    # Invalid contract shapes are model failures. Semantic checks
                    # receive no usable object; the original raw reply is retained.
                    result = {**result, "parsed_object": None}
                return result
            self.assessor.calendar.check = safe_calendar_check
            try:
                report = self.assessor.assess(public_record, outcome, truth_packet, assessment_id=assessment_id)
            finally:
                self.assessor.calendar.check = original_calendar_check
            if report.get("assessment_execution") != "completed":
                return {**report, "schema_version": VERSION, "final_metrics": None,
                        "external_check_execution_complete": False}
            raw = (((outcome.get("response") or {}).get("model_output") or {}).get("raw_text"))
            parsed = self.assessor.client.response.parse_response_text(raw if isinstance(raw, str) else "", bundle["local_response_schema"])
            parsed_object = parsed.get("parsed_object")
            kind = parsed_object.get("response_type") if isinstance(parsed_object, dict) else None
            by_id = {row["check_id"]: row for row in report["checks"]}
            duration = duration_check(public_record["input"], parsed.get("parsed_object"), self.requests, self.roots_function,
                structure_valid=parsed.get("parse_valid") is True and by_id["activity_accounting"]["status"] == "met",
                supported_nonplan=kind in {"clarification", "constraint_conflict", "outside_scope"} and by_id["response_type_basis"]["status"] == "met")
            goal = goal_check(public_record["input"], parsed.get("parsed_object"),
                supported_nonplan=kind in {"clarification", "constraint_conflict", "outside_scope"} and by_id["response_type_basis"]["status"] == "met")
            for added in (duration, goal):
                report["checks"].append(added)
                report["expected_check_ids"].append(added["check_id"])
                if added["status"] == "violated":
                    report["required_violations"].append(added["check_id"])
                if added["status"] == "unknown":
                    report["required_unknowns"].append(added["check_id"])
            parent = parent_report(report["checks"], case_annotation)
            category = case_annotation["case_category"]
            required = [row for row in parent["parent_checks"] if row["required"]]
            parent_violations = [row["check_id"] for row in required if row["status"] == "violated"]
            parent_unknowns = [row["check_id"] for row in required if row["status"] == "unknown"]
            all_supported = not parent_violations and not parent_unknowns
            declared_checks_supported = all(row["status"] in {"met", "not_applicable"}
                for row in required if row["check_id"] != "public_goal_fulfillment")
            success = bool(all_supported and kind == CATEGORIES[category] and outcome.get("completion_valid") is True)
            return {**report, **parent, "schema_version": VERSION, "accepted_study_case": True,
                "case_category": category,
                "overall": "requirements_violated" if parent_violations else "requirements_unverified" if parent_unknowns else "declared_checks_supported",
                "required_parent_violations": parent_violations, "required_parent_unknowns": parent_unknowns,
                "public_record_sha256": sha(packed(public_record)),
                "designated_outcome_sha256": sha(canonical(outcome)), "contract_bundle_id": binding["contract_bundle_id"],
                "effective_local_schema_sha256": binding["local_response_schema_sha256"],
                "exact_effective_case_schema_used": True, "public_case_frozen_binding_checked": True,
                "schema_invalid_parsed_object_diagnostic": deepcopy(parsed_object) if parsed.get("parse_valid") is not True else None,
                "schema_invalid_object_used_for_semantic_positive_result": False,
                "external_check_execution_complete": True, "source_resolution_is_claim_support": False,
                "resource_coverage": deepcopy(self.resource_coverage),
                "final_metrics": {"automated_feasible_plan_success": success if category == "feasible" else None,
                    "category_response_success": success, "automated_declared_checks_pass": bool(declared_checks_supported),
                    "complete_request_fulfillment_verified": bool(all_supported), "strict_format_valid": parsed.get("parse_valid") is True,
                    "designated_workflow_completed": outcome.get("completion_valid") is True,
                    "applicable_category": category},
                "internal_evaluator_used_for_verdict": False, "private_example_used_as_output_template": False,
                "final_study_score": None, "team_response_ratings_completed": False,
                "goal_semantic_verification_implemented": False,
                "quality_or_safety_certified": False,
                "coverage_limits": [*report.get("coverage_limits", []),
                    "The automated metrics cover the declared checks; goal quality, prose meaning outside their grammars, clinical suitability and team response ratings remain separate."]}
        except Exception as error:
            return {"schema_version": VERSION, "assessment_id": assessment_id, "assessment_execution": "error",
                "error": type(error).__name__ + ": " + str(error), "checks": [], "parent_checks": [],
                "final_metrics": None, "external_check_execution_complete": False,
                "internal_evaluator_used_for_verdict": False, "quality_or_safety_certified": False}
        finally:
            self._busy = False
