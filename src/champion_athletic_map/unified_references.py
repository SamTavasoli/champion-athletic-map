"""Use our unchanged unified records with the frozen reference tools."""

import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class UnifiedReferenceTools:
    def __init__(self, root, v1_config, integration):
        self.root = Path(root).resolve()
        self.source_bindings = {}
        expected = v1_config["dataset"]
        folder = self._path(expected["relative_directory"])
        names = {"champions_unified_dataset.csv", "dataset_manifest.json",
                 "load_unified_dataset.py", "READ_ME_FIRST.txt"}
        if set(expected["file_sha256"]) != names:
            raise ValueError("Our dataset configuration must bind all four release files.")
        for name, digest in expected["file_sha256"].items():
            path = folder / name
            if not path.resolve().is_relative_to(self.root) or file_sha256(path) != digest:
                raise ValueError("Our shared dataset file changed: " + name)
            self.source_bindings[path.relative_to(self.root).as_posix()] = digest
        self.manifest = json.loads((folder / "dataset_manifest.json").read_bytes())
        if (self.manifest["dataset_id"] != expected["dataset_id"]
                or self.manifest["csv_sha256"] != expected["file_sha256"]["champions_unified_dataset.csv"]):
            raise ValueError("Our dataset release differs from the baseline.")

        handoff = self._json("results/step24_language_model_integration_summary.json")
        relative = "src/champion_athletic_map/reference_tools.py"
        source = self._verified(relative, handoff["evidence_sha256"][relative])
        name = "champion_unified_reference_core_" + hashlib.sha256(source).hexdigest()[:16]
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader=None))
        sys.modules[name] = module
        exec(compile(source, str(self.root / relative), "exec"), module.__dict__)
        self._api = module
        core = self.core = module.ReferenceTools.__new__(module.ReferenceTools)
        core.root = self.root
        contracts = integration["contracts_directory"]
        summary = self._json(contracts + "/step24_7_shared_contract_summary.json")
        relative = contracts + "/verified_inputs.json"
        core.bound = json.loads(self._verified(relative, summary["output_hashes"][relative]))["project_file_sha256"]
        core._query_runtime = None

        pointer = self._json("artifacts/language_model/active_resource_release.json")
        if type(pointer) is not dict or set(pointer) != {"release_directory", "manifest_sha256"}:
            raise ValueError("Our active resource pointer is invalid.")
        release = pointer["release_directory"]
        manifest = json.loads(self._verified(release + "/manifest.json", pointer["manifest_sha256"]))
        required = {"adopted_drills.json", "adopted_rules.json", "decisions.json"}
        if not required.issubset(manifest["file_hashes"]):
            raise ValueError("Our approved resource release is incomplete.")
        payloads = {name: json.loads(self._verified(release + "/" + name, manifest["file_hashes"][name]))
                    for name in sorted(required)}
        drills, rules, decisions = (payloads[name] for name in
                                   ("adopted_drills.json", "adopted_rules.json", "decisions.json"))
        approved = {row["catalog_candidate_id"]: row for row in drills["records"]}
        adopted = {row["candidate_rule_id"]: row for row in rules["records"]}
        if len(approved) != 136 or len(adopted) != 29 or len(drills["records"]) != 136 or len(rules["records"]) != 29:
            raise ValueError("Our active resource counts differ from the reviewed release.")

        self.references, selected_drills, selected_rules = {}, {}, {}
        core._foods, core._nutrients, core._portions = {}, [], {}
        previous_limit = csv.field_size_limit()
        try:
            csv.field_size_limit(max(previous_limit, 64 * 1024 * 1024))
            with (folder / "champions_unified_dataset.csv").open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    kind, identifier = row["record_type"], row["source_record_id"]
                    reference = kind == "reference_passage" and row["retrieval_use"] == "indexed_reference"
                    drill = kind == "basketball_resource" and row["record_stage"] == "current_resource_record" and identifier in approved
                    rule = kind == "planning_rule" and row["record_stage"] == "current_rule_record" and identifier in adopted
                    food = kind == "food" and row["food_lookup_use"] == "prepared_selected_reference_activation_unverified"
                    if not (reference or drill or rule or food):
                        continue
                    if row["dataset_version"] != expected["dataset_id"] or row["classifier_use"] != "not_classifier_input":
                        raise ValueError("A selected record has unexpected dataset routing.")
                    data = json.loads(row["data_json"])
                    if reference:
                        record, metadata = data["core_record"], data["metadata_record"]
                        if (identifier in self.references or record["passage_id"] != identifier
                                or metadata["passage_id"] != identifier or row["text"] != record["text"]
                                or hashlib.sha256(row["text"].encode()).hexdigest() != data["embedded_core_text_sha256"]
                                or any(record[key] != metadata[key] for key in
                                       ("reference_unit_id", "required_delivery_record", "required_delivery_text"))):
                            raise ValueError("A unified reference differs from its recorded delivery.")
                        self.references[identifier] = data
                    elif drill:
                        if identifier in selected_drills or data["adopted_record"] != approved[identifier]:
                            raise ValueError("A unified drill differs from our active approval.")
                        selected_drills[identifier] = data["adopted_record"]
                    elif rule:
                        if identifier in selected_rules or data["current_record"] != adopted[identifier]:
                            raise ValueError("A unified rule differs from our active approval.")
                        selected_rules[identifier] = data["current_record"]
                    else:
                        foods = data["prepared_lookup_food"]
                        if len(foods) != 1 or foods[0]["fdc_id"] != identifier or identifier in core._foods:
                            raise ValueError("A prepared food has inconsistent identifiers.")
                        core._foods[identifier] = foods[0]
                        core._nutrients.extend(data["prepared_lookup_nutrients"])
                        for portion in data["prepared_lookup_portions"]:
                            if portion["portion_id"] in core._portions:
                                raise ValueError("A prepared food portion is duplicated.")
                            core._portions[portion["portion_id"]] = portion
        finally:
            csv.field_size_limit(previous_limit)
        if (len(self.references), len(selected_drills), len(selected_rules), len(core._foods)) != (11, 136, 29, 100):
            raise ValueError("Our selected unified reference records are incomplete.")

        # We use the current approvals and leave gym exercises unavailable.
        core._approved_drills, core._drill_aliases = selected_drills, drills["aliases"]
        core._drill_ids = set(approved) | set(decisions["held_drill_ids"]) | set(drills["aliases"])
        if any(alias in approved or target not in approved for alias, target in drills["aliases"].items()):
            raise ValueError("An approved drill alias has no canonical target.")
        core._adopted_rules = [selected_rules[row["candidate_rule_id"]] for row in rules["records"]]
        core._release_context = {key: rules[key] for key in
            ("project_overlap_policy", "shared_result_semantics", "current_public_input_gaps") if key in rules}
        core._release_version, core._exercise_ids = manifest["release_id"], set()
        relative = module.FOOD + "/step14_food_reference_summary.json"
        producer = json.loads(core._read(relative))
        self.source_bindings[relative] = core.bound[relative]
        core._food_version = "sr-legacy-2018-04:" + core.bound[relative][:16]
        relative = module.FOOD + "/usda_food_reference.py"
        digest = producer["artifacts"]["usda_food_reference.py"]["sha256"]
        if relative in core.bound and core.bound[relative] != digest:
            raise ValueError("Our food calculation helper binding differs.")
        core.bound[relative] = digest
        core._food = core._module(relative)
        self.source_bindings[relative] = digest

    def _path(self, relative):
        if type(relative) is not str or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("Reference paths must stay inside our project.")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError("A reference path leaves our project.")
        return path

    def _verified(self, relative, expected):
        data = self._path(relative).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("A saved reference binding changed: " + relative)
        self.source_bindings[relative] = expected
        return data

    def _json(self, relative):
        data = self._path(relative).read_bytes()
        self.source_bindings[relative] = hashlib.sha256(data).hexdigest()
        return json.loads(data)

    def load_query_runtime(self):
        core, query = self.core, self._api.QUERY
        if core._query_runtime is None:
            core._query_api = core._module(query + "/query_runtime.py")
            relative = query + "/query_runtime_manifest.json"
            runtime = core._query_api.load_query_runtime(self.root, self.root / relative, core.bound[relative])
            metadata = runtime["index"]["metadata"]
            if (len(metadata) != 11 or {row["passage_id"]: row for row in metadata}
                    != {key: row["metadata_record"] for key, row in self.references.items()}):
                raise ValueError("Our frozen index differs from the unified references.")
            core._query_runtime = runtime
            self.source_bindings[relative] = core.bound[relative]
        return core._query_runtime

    def complete_reference(self, item):
        record = self.references[item["passage_id"]]["metadata_record"]
        delivery = record["required_delivery_record"]
        key = "display_text" if "display_text" in delivery else "complete_display_text"
        text = record["required_delivery_text"]
        if (item["reference_unit_id"] != record["reference_unit_id"]
                or item["required_delivery_record"] != delivery or item["complete_required_delivery_text"] != text
                or item.get("required_delivery_must_be_attached") is not True
                or item.get("standalone_core_delivery_allowed") is not False
                or text != delivery[key] or hashlib.sha256(text.encode()).hexdigest() != delivery[key + "_sha256"]):
            raise ValueError("A retrieved reference lost its complete source context.")
        return {"reference_unit_id": record["reference_unit_id"], "passage_id": item["passage_id"],
                "complete_required_delivery_text": text}

    def get_drill(self, drill_id):
        return self.core.get_drill(drill_id)

    def get_planning_rules(self, age=None, school_grade=None):
        return self.core.get_planning_rules(age=age, school_grade=school_grade)

    def lookup_food(self, **arguments):
        return self.core.lookup_food(**arguments)

    def get_exercise(self, catalog_id):
        if type(catalog_id) is not str or not catalog_id or catalog_id != catalog_id.strip():
            return self.core._result("invalid_arguments", issue="Supply a nonblank record ID.")
        return self.core._result("not_eligible", issue="Gym exercises remain unavailable for planning.")
