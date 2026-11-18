"""Read-only access to frozen references and food facts, with approval limits."""

import csv
import hashlib
import importlib.util
import io
import json
import sys
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path


QUERY = "artifacts/retrieval/query_runtime/query_f6db9aad37d7a9b9"
FOOD = "data/processed/usda_sr_legacy_2018_04/reference_ee67cf780262d24b"
DRILLS = "results/basketball_catalog_review/source_linked_schema_f42c98af0179a37d/basketball_candidate_schema_REVIEW_ONLY.csv"
EXERCISES = "data/processed/exercise_catalog_tagged.csv"
RULES = "results/planning_rule_review/decision_tests_cd2f27a8c1f8876c/planning_rule_decisions_PENDING.csv"


class ReferenceTools:
    def __init__(self, root, contracts_dir):
        self.root = Path(root).resolve()
        folder = self.root / contracts_dir
        summary = json.loads((folder / "step24_7_shared_contract_summary.json").read_text(encoding="utf-8"))
        index = (folder / "verified_inputs.json").read_bytes()
        relative = (folder / "verified_inputs.json").relative_to(self.root).as_posix()
        if hashlib.sha256(index).hexdigest() != summary["output_hashes"][relative]:
            raise ValueError("Saved resource bindings changed")
        self.bound = json.loads(index)["project_file_sha256"]
        self._query_runtime = None
        drills, exercises, rules = self._rows(DRILLS), self._rows(EXERCISES), self._rows(RULES)
        if (any(row["planner_eligible"].lower() not in ("no", "false", "0", "") for row in drills)
                or any(row["planner_eligibility_granted"].lower() not in ("no", "false", "0", "") for row in exercises)
                or any(row["enabled_for_planner"].lower() not in ("no", "false", "0", "") for row in rules)):
            raise ValueError("Approval states changed; the lookup configuration needs review")
        # We retain only IDs; prediction scores and review-only content stay out.
        self._drill_ids = {row["catalog_candidate_id"] for row in drills}
        self._exercise_ids = {row["catalog_id"] for row in exercises}
        producer = json.loads(self._read(FOOD + "/step14_food_reference_summary.json"))
        self._food_version = "sr-legacy-2018-04:" + self.bound[FOOD + "/step14_food_reference_summary.json"][:16]
        names = ("usda_food_reference.py", "usda_foods.csv", "usda_food_nutrients.csv", "usda_food_portions.csv", "usda_nutrient_definitions.json")
        for name in names:
            expected = producer["artifacts"][name]["sha256"]
            relative = FOOD + "/" + name
            if relative in self.bound and self.bound[relative] != expected:
                raise ValueError("Food reference binding differs")
            self.bound[relative] = expected
            self._read(relative)
        self._food = self._module(FOOD + "/usda_food_reference.py")
        self._foods = {row["fdc_id"]: row for row in self._rows(FOOD + "/usda_foods.csv")}
        self._nutrients = self._rows(FOOD + "/usda_food_nutrients.csv")
        self._portions = {row["portion_id"]: row for row in self._rows(FOOD + "/usda_food_portions.csv")}

    def _read(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Resource path leaves the project")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != self.bound.get(relative):
            raise ValueError("Saved reference changed: " + path.name)
        return data

    def _rows(self, relative):
        return list(csv.DictReader(io.StringIO(self._read(relative).decode("utf-8-sig"))))

    def _module(self, relative):
        source = self._read(relative)
        name = "champion_reference_" + hashlib.sha256(source).hexdigest()[:16]
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader=None))
        sys.modules[name] = module
        exec(compile(source, str(self.root / relative), "exec"), module.__dict__)
        return module

    def _result(self, status, data=None, issue=None, source_refs=None, version="selected-local-snapshot"):
        return {"request_id": uuid.uuid4().hex, "status": status, "data": data,
                "issues": [issue] if issue else [], "source_refs": source_refs or [], "data_version": version}

    def search_references(self, query, filters=None):
        """Search the frozen semantic index and preserve complete source companions."""
        if type(query) is not str or not query.strip() or filters not in (None, {}):
            return self._result("invalid_arguments", issue="Supply a nonblank query; this pilot has no supported filters.")
        try:
            if self._query_runtime is None:
                self._query_api = self._module(QUERY + "/query_runtime.py")
                self._query_runtime = self._query_api.load_query_runtime(self.root, self.root / QUERY / "query_runtime_manifest.json",
                                                             self.bound[QUERY + "/query_runtime_manifest.json"])
            api = self._query_api
            work = self.root / "results/integration/reference_queries" / uuid.uuid4().hex[:12]
            work.mkdir(parents=True)
            rows = api.make_query_records([query])
            encoded = api.encode_queries(self._query_runtime, rows, work.resolve())
            result = api.rank_queries(self._query_runtime, rows, encoded["vectors"], routes=("semantic",))[0]["result"]
            items = result["results"]
            return self._result("found" if items else "not_found", data={"references": items},
                                issue="Ranking does not establish answerability; complete source context must remain attached.",
                                source_refs=[row["reference_unit_id"] for row in items],
                                version=self._query_runtime["config"]["expanded_retrieval_id"])
        except Exception as error:
            return self._result("execution_error", issue=str(error))

    def _pending_record(self, identifier, known, label, version):
        if type(identifier) is not str or not identifier or identifier != identifier.strip():
            return self._result("invalid_arguments", issue="Supply a nonblank record ID.", version=version)
        if identifier in known:
            return self._result("not_eligible", issue="This " + label + " record has not been approved for planning.", version=version)
        return self._result("not_found", issue="ID not found in the selected " + label + " lookup.", version=version)

    def get_drill(self, drill_id):
        return self._pending_record(drill_id, self._drill_ids, "drill", self.bound[DRILLS])

    def get_exercise(self, catalog_id):
        return self._pending_record(catalog_id, self._exercise_ids, "development exercise", self.bound[EXERCISES])

    def get_planning_rules(self, age=None, school_grade=None):
        if (age is not None and (type(age) is not int or not 13 <= age <= 17)
                or school_grade is not None and (type(school_grade) is not int or not 1 <= school_grade <= 12)):
            return self._result("invalid_arguments", issue="Age and grade must match the study input contract, or be unknown.")
        return self._result("unavailable", issue="No planning rules in the selected register are adopted and enabled.", version=self.bound[RULES])

    @staticmethod
    def _positive(value):
        if type(value) not in (str, int, float) or len(str(value)) > 128:
            raise ValueError("Quantity must be a positive finite number.")
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise ValueError("Quantity must be a positive finite number.")
        return value

    def lookup_food(self, food_id=None, search_text=None, grams=None, portion_id=None, multiplier=None):
        """Return food facts using exact grams or a food-specific recorded portion."""
        try:
            if (food_id is None) == (search_text is None):
                raise ValueError("Supply either a food ID or search text.")
            if (grams is not None and portion_id is not None) or (portion_id is None) != (multiplier is None):
                raise ValueError("Use grams, or a recorded portion ID with an explicit multiplier.")
            if grams is not None:
                self._positive(grams)
            if multiplier is not None:
                self._positive(multiplier)
            if portion_id is not None:
                if type(portion_id) not in (str, int) or not str(portion_id).isdigit() or int(portion_id) <= 0:
                    raise ValueError("Portion ID must be a positive integer identifier.")
                portion_id = str(int(portion_id))
            if food_id is not None:
                if type(food_id) not in (str, int) or not str(food_id).isdigit() or int(food_id) <= 0:
                    raise ValueError("Food ID must be a positive integer identifier.")
                candidates = [self._foods[str(int(food_id))]] if str(int(food_id)) in self._foods else []
            else:
                if type(search_text) is not str or not search_text.strip():
                    raise ValueError("Food search text must be nonblank.")
                candidates = [row for row in self._foods.values() if search_text.casefold().strip() in row["description"].casefold()]
            if not candidates:
                return self._result("not_found", issue="No matching food in the frozen snapshot.", version=self._food_version)
            if len(candidates) > 1:
                return self._result("ambiguous", data={"candidates": [{"food_id": row["fdc_id"], "description": row["description"]} for row in candidates]},
                                    issue="Select an exact food ID before calculating quantities.", version=self._food_version)
            food, portion = candidates[0], None
            mass = "100" if grams is None else grams
            if portion_id is not None:
                portion = self._portions.get(str(portion_id))
                if portion is None:
                    return self._result("not_found", issue="Recorded portion ID not found.", version=self._food_version)
                portion = self._food.household_mass(food, portion, quantity=multiplier, mode="complete_record")
                mass = portion["grams"]
            facts = [self._food.food_fact(food, row, grams=mass) for row in self._nutrients if row["fdc_id"] == food["fdc_id"]]
            return self._result("found", data={"food_id": food["fdc_id"], "description": food["description"],
                                                "grams": facts[0]["grams"], "portion": portion, "nutrients": facts},
                                source_refs=[food["source_record_url"]], version=self._food_version)
        except (ValueError, TypeError, InvalidOperation) as error:
            return self._result("invalid_arguments", issue=str(error), version=self._food_version)
