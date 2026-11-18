"""Our correction checks use artificial cases and make no planner requests."""

from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import os
import sys

import pytest


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def _root():
    configured = os.environ.get("CHAMPION_STEP33_2_ROOT") or os.environ.get("CHAMPION_STEP33_SOURCE_ROOT")
    roots = [Path(configured)] if configured else []
    for base in (Path.cwd(), Path(__file__).resolve().parent):
        roots.extend((base, *base.parents))
    marker = "data/processed/usda_sr_legacy_2018_04/reference_ee67cf780262d24b/usda_food_reference.py"
    found = next((root for root in roots if (root / marker).is_file()), None)
    assert found is not None, "The recorded food arithmetic source is required."
    return found.resolve()


def _candidate(root, environment, filename):
    configured = os.environ.get(environment)
    locations = ([Path(configured)] if configured else []) + [
        root / "src/champion_athletic_map" / filename, Path(__file__).with_name(filename)]
    found = next((path for path in locations if path.is_file()), None)
    assert found is not None, "The correction source is required: " + filename
    return found


@pytest.fixture(scope="session")
def source_root():
    return _root()


@pytest.fixture(scope="session")
def food(source_root):
    path = _candidate(source_root, "CHAMPION_STEP33_2_FOOD_MODULE", "food_expectations.py")
    return _load(path, "step33_artificial_food_expectations")


@pytest.fixture(scope="session")
def food_arithmetic(source_root, food):
    path = source_root / "data/processed/usda_sr_legacy_2018_04/reference_ee67cf780262d24b/usda_food_reference.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == food.EXPECTED["usda_food_reference.py"]
    return _load(path, "step33_recorded_food_arithmetic").food_fact


def _food_profile(identifier="artificial_food_case", name="Artificial exact food", mass="80", measure="grams of protein"):
    return {"profile_id": identifier, "schema_version": "athlete-profile-input-1", "input": {
        "food_question": f'For the recorded food identity "{name}", how many {measure} are listed for {mass} g?'}}


@pytest.fixture
def artificial_food_rows():
    foods = [{"fdc_id": "101", "description": "Artificial exact food", "source_data_type": "sr_legacy_food",
              "catalog_release": "2018-04", "source_record_url": "https://example.invalid/food/101"}]
    nutrients = [{"fdc_id": "101", "nutrient_id": "1003", "nutrient_name": "Protein", "unit_name": "G",
                  "numeric_status": "available", "amount_per_100g_raw": "2.75", "reference_mass_g": "100",
                  "reference_basis": "edible_food", "source_food_nutrient_id": "9001"}]
    return foods, nutrients


def test_food_expectation_uses_exact_record_and_recorded_decimal_arithmetic(food, food_arithmetic, artificial_food_rows):
    foods, nutrients = artificial_food_rows
    original = copy.deepcopy((foods, nutrients))
    result = food.evaluate_food_questions([_food_profile()], foods, nutrients, food_arithmetic,
                                         source_version="explicit-artificial-food-fixture")
    assert result["verified_cases"] == result["requested_cases"] == 1
    assert result["private_expectations_only"] is True
    expected = result["cases"][0]["expected_fact"]
    assert expected["amount"] == "2.2" and expected["grams"] == "80"
    assert expected["fdc_id"] == "101" and expected["nutrient_id"] == "1003" and expected["unit"] == "G"
    assert expected["source_food_nutrient_id"] == "9001"
    assert expected["source_ref"] == foods[0]["source_record_url"]
    assert expected["reference_version"] == "explicit-artificial-food-fixture"
    assert expected["exact_arithmetic_crosscheck"] is True
    assert (foods, nutrients) == original
    assert result["team_approvals_created"] == result["model_calls"] == 0


def test_zero_recorded_food_value_is_available_not_missing(food, food_arithmetic, artificial_food_rows):
    foods, nutrients = artificial_food_rows
    nutrients[0]["amount_per_100g_raw"] = "0"
    result = food.evaluate_food_questions([_food_profile()], foods, nutrients, food_arithmetic)
    assert result["verified_cases"] == 1 and result["cases"][0]["expected_fact"]["amount"] == "0"


@pytest.mark.parametrize("question", [None, "How much protein is in a snack?",
    'For the recorded food identity "Artificial exact food", how many grams of protein are listed for 0 g?',
    'For the recorded food identity "Artificial exact food", how many grams of protein are listed for -2 g?',
    'For the recorded food identity "Artificial exact food", how many grams of protein are listed for NaN g?'])
def test_food_question_parser_does_not_guess_unrecorded_or_invalid_requests(food, question):
    assert food.parse_food_question(question) is None


@pytest.mark.parametrize("defect,status", [("partial_food_name", "not_found"), ("duplicate_food", "ambiguous_food"),
    ("missing_nutrient", "nutrient_not_found"), ("duplicate_nutrient", "ambiguous_nutrient"),
    ("wrong_unit", "nutrient_definition_mismatch"), ("wrong_name", "nutrient_definition_mismatch"),
    ("unavailable_value", "source_value_unavailable"), ("missing_source", "source_attribution_missing")])
def test_food_uncertainty_is_preserved_without_fabricating_answer(food, food_arithmetic, artificial_food_rows, defect, status):
    foods, nutrients = artificial_food_rows
    if defect == "partial_food_name":
        foods[0]["description"] += ", raw"
    elif defect == "duplicate_food":
        foods.append({**foods[0], "fdc_id": "102"})
    elif defect == "missing_nutrient":
        nutrients.clear()
    elif defect == "duplicate_nutrient":
        nutrients.append(copy.deepcopy(nutrients[0]))
    elif defect == "wrong_unit":
        nutrients[0]["unit_name"] = "MG"
    elif defect == "wrong_name":
        nutrients[0]["nutrient_name"] = "Energy"
    elif defect == "unavailable_value":
        nutrients[0]["numeric_status"] = "not_reported"
    else:
        foods[0].pop("source_record_url")
    result = food.evaluate_food_questions([_food_profile()], foods, nutrients, food_arithmetic)
    assert result["verified_cases"] == 0
    assert result["cases"][0]["status"] == status
    assert result["cases"][0]["expected_fact"] is None


def test_food_helper_disagreement_stays_unverified(food, food_arithmetic, artificial_food_rows):
    foods, nutrients = artificial_food_rows
    def disagreement(*args, **kwargs):
        return {**food_arithmetic(*args, **kwargs), "amount": "999"}
    result = food.evaluate_food_questions([_food_profile()], foods, nutrients, disagreement)
    assert result["verified_cases"] == 0
    assert result["cases"][0]["status"] == "invalid_source_value"
    assert result["cases"][0]["expected_fact"] is None


def test_missing_native_food_table_records_unavailable_instead_of_twenty_verified(food, tmp_path):
    records = [_food_profile("artificial_" + str(index)) for index in range(20)]
    result = food.build_food_expectations(tmp_path, records)
    assert result["requested_cases"] == 20 and result["verified_cases"] == 0
    assert result["counts"] == {"reference_unavailable": 20}
    assert result["reference_files_verified"] is False
    assert result["native_food_values_verified"] is False
    assert all(row["expected_fact"] is None for row in result["cases"])


def test_changed_native_food_reference_is_rejected_before_calculation(food, tmp_path):
    file = tmp_path / food.FOOD / next(iter(food.EXPECTED))
    file.parent.mkdir(parents=True)
    file.write_bytes(b"Artificial changed source bytes.\n")
    with pytest.raises(ValueError, match="frozen food-reference file changed"):
        food.build_food_expectations(tmp_path, [_food_profile()])


@pytest.mark.parametrize("mass,measure", [("80", "grams of protein"), ("12.5", "kilocalories of energy")])
def test_food_wording_amendment_preserves_identity_quantity_and_supported_runtime_grammar(food, source_root, mass, measure):
    focus = _load(source_root / "src/champion_athletic_map/food_fact_focus.py", "step33_saved_food_focus_for_test")
    source = _food_profile(mass=mass, measure=measure)["input"]["food_question"]
    proposed = food.canonical_runtime_question(source)
    assert source.startswith("For the recorded food identity")
    assert proposed.startswith("For the food")
    assert focus._QUESTION.fullmatch(proposed) is not None
    assert food.parse_food_question(source) == food.parse_food_question(proposed)
    assert food.canonical_runtime_question(proposed) == proposed


def test_exact_food_value_does_not_clear_an_ambiguous_existing_runtime_lookup(food, food_arithmetic, artificial_food_rows):
    foods, nutrients = artificial_food_rows
    foods.append({**foods[0], "fdc_id": "102", "description": "Artificial exact food, related record"})
    result = food.evaluate_food_questions([_food_profile()], foods, nutrients, food_arithmetic)
    row = result["cases"][0]
    assert row["status"] == "verified" and row["expected_fact"]["fdc_id"] == "101"
    assert row["runtime_description_lookup"]["status"] == "ambiguous_or_nonexact"
    assert result["verified_cases"] == 1 and result["runtime_ready_cases"] == 0
    assert row["question"].startswith("For the recorded food identity")
    assert row["original_question_preserved"] is True


@pytest.fixture(scope="session")
def correction(source_root):
    return _load(_candidate(source_root, "CHAMPION_STEP33_2_MODULE", "case_corrections.py"),
                 "step33_artificial_case_corrections")


@pytest.fixture(scope="session")
def family(source_root):
    return _load(_candidate(source_root, "CHAMPION_STEP33_2_FAMILY_MODULE", "family_reconciliation.py"),
                 "step33_artificial_family_reconciliation")


@pytest.fixture(scope="session")
def original_screen(source_root, family):
    path = source_root / family.PROTECTED / "protected_generator.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == family.GENERATOR_SHA256
    return _load(path, "step33_recorded_relationship_screen")


def _public(identifier="artificial_case", commitments=None):
    return {"profile_id": identifier, "schema_version": "athlete-profile-input-1", "input": {
        "age": 15, "athlete_request": "Arrange 1 additional practice block within the listed limits.",
        "planning_window": {"start_date": "2026-11-16", "end_date": "2026-11-22", "timezone": "America/Los_Angeles"},
        "availability": [{"date": "2026-11-17", "start_time": "17:00", "end_time": "17:20"}],
        "basketball_background": {"experience_level": "beginner"}, "school_grade": 9,
        "goals": ["Improve controlled dribbling"], "equipment": [{"name": "Basketball", "quantity": 1}],
        "space": {"court_access": "none", "hoop_access": False, "restrictions": []},
        "reported_limitations": [], "participants_available": 1,
        "existing_commitments": [] if commitments is None else commitments,
        "time_limits": {"max_additional_sessions_per_week": 1, "max_additional_minutes_per_week": 20, "max_session_minutes": 20}}}


def test_complete_schedule_is_an_explicit_new_fictional_proposal_with_original_hashes(correction):
    source = _public()
    untouched = copy.deepcopy(source)
    result = correction.propose_public_record(source, "feasible")
    proposed = result["proposed_public_record"]
    assert source == untouched and "schedule_coverage" not in source["input"]
    assert proposed["schema_version"] == "athlete-profile-input-2"
    assert proposed["input"]["schedule_coverage"] == {**source["input"]["planning_window"], "existing_commitments_complete": True}
    reverted = copy.deepcopy(proposed)
    reverted["schema_version"] = source["schema_version"]
    reverted["input"].pop("schedule_coverage")
    assert reverted == source
    assert result["source_record_sha256"] == correction.sha(correction.packed(source))
    assert result["proposed_record_sha256"] == correction.sha(correction.packed(proposed))
    assert result["source_record_sha256"] != result["proposed_record_sha256"]
    assert result["schedule_fact_origin"] == "new_fictional_fact_pending_team_review"
    assert result["authoring_decisions"][0]["origin"] == "new_explicit_fictional_authoring_proposal"
    assert result["authoring_decisions"][0]["team_decision"] is None
    assert result["approved"] is result["authorized_for_model_use"] is False
    assert result["prepared_by"] is result["reviewed_by"] is result["team_decision"] is None
    assert result["adopted_category"] is result["adopted_family_id"] is None


@pytest.mark.parametrize("category,expected", [("missing_information", "clarification"),
    ("conflicting_constraints", "constraint_conflict"), ("outside_scope", "outside_scope")])
def test_challenge_facts_stay_unchanged_and_coverage_stays_unknown(correction, category, expected):
    source = _public()
    source["input"]["existing_commitments"] = None
    untouched = copy.deepcopy(source)
    result = correction.propose_public_record(source, category)
    assert result["proposed_expected_response"] == expected
    assert result["proposed_public_record"]["input"]["schedule_coverage"] is None
    assert result["proposed_public_record"]["input"]["existing_commitments"] is None
    assert result["authoring_decisions"] == []
    assert source == untouched
    assert result["approved"] is False and result["adopted_category"] is None


def test_planning_case_with_unknown_existing_events_is_not_silently_completed(correction):
    source = _public()
    source["input"]["existing_commitments"] = None
    with pytest.raises(ValueError, match="unknown commitments"):
        correction.propose_public_record(source, "feasible")
    assert source["input"]["existing_commitments"] is None
    assert "schedule_coverage" not in source["input"]


@pytest.mark.parametrize("defect", ["existing_coverage", "unsupported_schema", "unknown_category"])
def test_existing_or_unrecognized_public_facts_require_separate_amendment(correction, defect):
    source = _public()
    category = "feasible"
    if defect == "existing_coverage":
        source["input"]["schedule_coverage"] = None
    elif defect == "unsupported_schema":
        source["schema_version"] = "artificial-unrecognized-schema"
    else:
        category = "artificial-unrecognized-category"
    before = copy.deepcopy(source)
    with pytest.raises(ValueError):
        correction.propose_public_record(source, category)
    assert source == before


def test_full_artificial_population_has_only_150_new_completeness_proposals(correction):
    categories = ["feasible"] * 150 + ["missing_information"] * 20 + ["conflicting_constraints"] * 15 + ["outside_scope"] * 15
    sources = []
    for index, category in enumerate(categories):
        record = _public("artificial_" + str(index))
        if category == "missing_information" and index < 156:
            record["input"]["existing_commitments"] = None
        sources.append(record)
    before = copy.deepcopy(sources)
    values = [correction.propose_public_record(record, category) for record, category in zip(sources, categories)]
    coverage = [row["proposed_public_record"]["input"]["schedule_coverage"] for row in values]
    assert sum(isinstance(value, dict) and value["existing_commitments_complete"] is True for value in coverage) == 150
    assert sum(value is None for value in coverage) == 50
    assert sum(row["proposed_public_record"]["input"]["existing_commitments"] is None for row in values) == 6
    assert sources == before
    for value in values:
        public = value["proposed_public_record"]
        assert set(public) == {"profile_id", "schema_version", "input"}
        assert not set(public["input"]) & {"expected_response_type", "expected_food_fact", "family_id", "team_decision", "feasibility_witness"}
        assert value["approved"] is False and value["team_decision"] is None


def test_food_wording_is_an_explicit_versioned_public_amendment_without_private_answer(correction, food):
    original = _public()
    original["input"]["food_question"] = _food_profile()["input"]["food_question"]
    before = copy.deepcopy(original)
    wording = food.canonical_runtime_question(original["input"]["food_question"])
    result = correction.propose_public_record(original, "feasible", food_question_amendment=wording)
    proposed = result["proposed_public_record"]
    assert original == before
    assert proposed["input"]["food_question"] == wording
    assert food.parse_food_question(wording) == food.parse_food_question(original["input"]["food_question"])
    decision = next(row for row in result["authoring_decisions"] if row["field"] == "/input/food_question")
    assert decision["source_value"] == original["input"]["food_question"]
    assert decision["proposed_value"] == wording and decision["team_decision"] is None
    assert decision["origin"] == "runtime_compatible_wording_proposal"
    assert not set(proposed["input"]) & {"expected_fact", "amount", "food_id", "source_ref"}


@pytest.mark.parametrize("defect", ["quantity", "identity", "nutrient", "no_source_question"])
def test_food_wording_amendment_cannot_change_the_requested_fact(correction, food, defect):
    original = _public()
    original["input"]["food_question"] = _food_profile()["input"]["food_question"]
    wording = food.canonical_runtime_question(original["input"]["food_question"])
    if defect == "quantity":
        wording = wording.replace("80 g", "81 g")
    elif defect == "identity":
        wording = wording.replace("Artificial exact food", "Different fictional food")
    elif defect == "nutrient":
        wording = wording.replace("grams of protein", "kilocalories of energy")
    else:
        original["input"].pop("food_question")
    before = copy.deepcopy(original)
    with pytest.raises(ValueError):
        correction.propose_public_record(original, "feasible", food_question_amendment=wording)
    assert original == before


def test_saved_correction_files_are_immutable(correction, tmp_path):
    path = tmp_path / "artificial_review.json"
    correction.save_once(path, b'{"fixture":true}\n')
    correction.save_once(path, b'{"fixture":true}\n')
    before = path.read_bytes()
    with pytest.raises(ValueError, match="saved correction file changed"):
        correction.save_once(path, b'{"fixture":false}\n')
    assert path.read_bytes() == before


def test_fresh_relationship_screen_separates_exact_copy_and_similarity(family, original_screen):
    candidate = _public("artificial_candidate")
    exact = copy.deepcopy(candidate)
    exact["profile_id"] = "artificial_development_exact"
    similar = copy.deepcopy(candidate)
    similar["profile_id"] = "artificial_development_similar"
    similar["input"]["athlete_request"] = "Help me arrange a basketball block using my listed resources."
    inputs = copy.deepcopy((candidate, exact, similar))
    result = family.compare_populations([candidate], [{"label": "artificial_development", "profiles": [similar, exact]}], original_screen)
    assert result["summary"]["screened_pairs"] == 2
    assert result["summary"]["exact_full_input_pairs"] == 1
    assert len(result["flagged_pairs"]) == 2
    indexed = {row["development_profile_id"]: row for row in result["flagged_pairs"]}
    assert indexed[exact["profile_id"]]["exact_full_input"] is True
    assert indexed[similar["profile_id"]]["exact_full_input"] is False
    assert indexed[similar["profile_id"]]["original_screen_findings"]["known_fact_similarity"] is True
    assert all(row["adopted_family_id"] is None and row["team_decision"] is None
               and row["exclude_candidate"] is False for row in result["flagged_pairs"])
    assert result["summary"]["families_adopted"] == result["summary"]["cases_excluded"] == 0
    assert result["case_proposals"][0]["independence_established"] is False
    assert (candidate, exact, similar) == inputs


def test_schedule_coverage_alignment_is_diagnostic_not_identical_fact_claim(family, original_screen):
    candidate = _public("artificial_candidate")
    candidate["schema_version"] = "athlete-profile-input-2"
    candidate["input"]["schedule_coverage"] = {**candidate["input"]["planning_window"], "existing_commitments_complete": True}
    different = copy.deepcopy(candidate)
    different["profile_id"] = "artificial_development"
    different["input"]["schedule_coverage"]["existing_commitments_complete"] = False
    result = family.compare_populations([candidate], [{"label": "artificial_development", "profiles": [different]}], original_screen)
    pair = result["flagged_pairs"][0]
    assert pair["exact_full_input"] is False
    assert pair["common_input_equal_without_schedule_coverage"] is True
    assert "does not make different completeness facts identical" in pair["comparison_qualification"]
    assert result["case_proposals"][0]["adopted_family_id"] is None


@pytest.mark.parametrize("defect", ["candidate_ids", "development_ids", "version_labels"])
def test_relationship_population_identity_errors_are_not_silently_deduplicated(family, original_screen, defect):
    candidates = [_public("artificial_candidate")]
    groups = [{"label": "artificial_development", "profiles": [_public("artificial_development")]}]
    if defect == "candidate_ids":
        candidates.append(copy.deepcopy(candidates[0]))
    elif defect == "development_ids":
        groups[0]["profiles"].append(copy.deepcopy(groups[0]["profiles"][0]))
    else:
        groups.append(copy.deepcopy(groups[0]))
    with pytest.raises(ValueError):
        family.compare_populations(candidates, groups, original_screen)


@pytest.fixture
def artificial_correction_package(tmp_path, correction, food, family, food_arithmetic, original_screen,
                                  artificial_food_rows, monkeypatch):
    """A complete artificial 200-case package, isolated from the native benchmark."""
    root = tmp_path / "artificial_project"
    root.mkdir()
    (root / ".gitignore").write_bytes(b"/results/final_case_review/\n")
    package = root / "results/final_case_review/artificial_source_package"
    package.mkdir(parents=True)
    original_working = package / "working/review_decisions.csv"
    original_working.parent.mkdir()
    original_working.write_bytes(b"Original artificial team-file marker.\n")
    categories = ["feasible"] * 150 + ["missing_information"] * 20 + ["conflicting_constraints"] * 15 + ["outside_scope"] * 15
    profiles, metadata = [], {}
    for number, category in enumerate(categories):
        record = _public("artificial_" + str(number))
        if number < 20:
            record["input"]["food_question"] = _food_profile()["input"]["food_question"]
        if 150 <= number < 156:
            record["input"]["existing_commitments"] = None
        profiles.append(record)
        metadata[record["profile_id"]] = {"profile_id": record["profile_id"], "scenario_intent": category,
            "record_sha256": correction.sha(correction.packed(record))}
    base = {"catalog_candidate_id": "artificial_base", "source_prescription": "3 minutes",
            "instructions": "Artificial stationary ball-control base.", "participants": "Individual player"}
    options = {"catalog_candidate_id": base["catalog_candidate_id"], "source_index": 0,
        "source_evidence": {key: {"path": "reference_snapshot/adopted_drills.json#/records/0/" + key, "value": value}
                            for key, value in base.items()},
        "base_case_approval": False, "full_case_feasibility_proved": False, "hard_blockers": [], "unknown_conditions": [],
        "elapsed_prescription": {"kind": "single_explicit_elapsed_dose", "source_text": "3 minutes", "calendar_minutes": 3,
                                  "seconds": 180.0, "minutes": 3.0}}
    activities = []
    for record in profiles[:150]:
        activities.append({"profile_id": record["profile_id"], "source_record_sha256": metadata[record["profile_id"]]["record_sha256"],
            "approved": False, "candidate_options": [copy.deepcopy(options)], "remaining_decisions": ["Team review pending"],
            "selected_example": {"case_approved": False, "invented_rest_or_dose": False,
                "qualification": "Explicit artificial software-check example; not a case approval.",
                "witness_slots": [{"catalog_candidate_id": "artificial_base", "source_prescription": "3 minutes",
                    "date": "2026-11-17", "start_time": "17:00", "end_time": "17:03", "duration_minutes": 3}]}})
    activity = {"source_package_id": "artificial_source_package", "cases": activities,
                "fixture_label": "Artificial activity proposals, not study outputs"}
    artifact_path = "artifacts/evaluation/artificial_activity_proposals.json"
    (root / artifact_path).parent.mkdir(parents=True)
    (root / artifact_path).write_bytes(correction.packed(activity))
    anchor = package / "artificial_source_marker.json"
    anchor.write_bytes(b'{"software_fixture":true}\n')
    source = {"package_root": package, "manifest": {"package_id": "artificial_source_package"},
              "profiles": profiles, "metadata": metadata, "resources": {"records": [base]},
              "bindings": {anchor.relative_to(root).as_posix(): correction.sha(anchor.read_bytes())}}
    for loaded, name in [(correction, "case_corrections.py"), (food, "food_expectations.py"), (family, "family_reconciliation.py")]:
        path = root / "src/champion_athletic_map" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(loaded.__file__).read_bytes())
    foods, nutrients = artificial_food_rows
    calls = {"food": 0, "families": 0}
    def food_runner(project, values):
        calls["food"] += 1
        return food.evaluate_food_questions(values, foods, nutrients, food_arithmetic,
                                             source_version="explicit-artificial-food-fixture")
    def family_runner(project, values, package_root):
        calls["families"] += 1
        dev = copy.deepcopy(values[0])
        dev["profile_id"] = "artificial_development"
        result = family.compare_populations(values, [{"label": "artificial_development", "profiles": [dev]}], original_screen)
        result.update(current_development_rescreen_completed=True, source_file_sha256={}, source_package_id="artificial_source_package",
                      fixture_label="Artificial development population, not native readiness")
        return result
    monkeypatch.setattr(correction, "load_package", lambda _root: source)
    return {"root": root, "source": source, "activity": activity, "artifact_path": artifact_path,
            "dependencies": {"food": food_runner, "families": family_runner}, "calls": calls,
            "original_working": original_working}


def test_full_correction_export_keeps_private_answers_out_of_public_inputs(correction, artificial_correction_package):
    fixture = artificial_correction_package
    source_before = copy.deepcopy(fixture["source"]["profiles"])
    team_before = fixture["original_working"].read_bytes()
    result = correction.execute(fixture["root"], activity_path=fixture["artifact_path"],
                                dependencies=fixture["dependencies"], emit=lambda _message: None)
    assert result["injected_test_dependencies"] is True
    assert result["summary_path"] == "results/step33_2_fixture_summary.json"
    assert "software_fixture_" in result["package_directory"]
    assert not (fixture["root"] / "results/step33_case_corrections_summary.json").exists()
    assert result["cases_prepared"] == 200 and result["challenge_cases_preserved"] == 50
    assert result["new_fictional_schedule_proposals"] == 150 and result["food_question_wording_proposals"] == 20
    assert result["food_expected_values_verified"] == result["food_runtime_ready"] == 20
    assert result["team_approvals_created"] == result["new_model_calls"] == 0
    assert result["final_planner_execution_authorized"] is False
    folder = fixture["root"] / result["package_directory"]
    public = [json.loads(line) for line in (folder / "proposed_public_profiles.jsonl").read_bytes().splitlines()]
    private = [json.loads(line) for line in (folder / "correction_register.jsonl").read_bytes().splitlines()]
    gold = json.loads((folder / "private_food_expectations.json").read_bytes())
    assert len(public) == len(private) == 200 and gold["verified_cases"] == 20
    for record in public:
        assert set(record) == {"profile_id", "schema_version", "input"}
        assert not set(record["input"]) & {"expected_fact", "expected_response_type", "family_id", "source_ref", "amount", "feasibility_witness"}
    assert all(row["approved"] is False and row["team_decision"] is None for row in private)
    assert fixture["source"]["profiles"] == source_before
    assert fixture["original_working"].read_bytes() == team_before


def test_repeat_export_preserves_team_edits_and_original_case_files(correction, artificial_correction_package):
    fixture = artificial_correction_package
    result = correction.execute(fixture["root"], activity_path=fixture["artifact_path"], dependencies=fixture["dependencies"], emit=lambda _message: None)
    folder = fixture["root"] / result["package_directory"]
    working = folder / "working/team_decisions.csv"
    working.write_bytes(working.read_bytes() + b"\n# Artificial saved reviewer note.\n")
    before = working.read_bytes()
    repeated = correction.execute(fixture["root"], activity_path=fixture["artifact_path"], dependencies=fixture["dependencies"], emit=lambda _message: None)
    assert repeated == result and working.read_bytes() == before
    assert fixture["original_working"].read_bytes() == b"Original artificial team-file marker.\n"


def test_stale_family_screen_cannot_substitute_original_v1_hashes_for_corrected_inputs(correction, artificial_correction_package):
    fixture = artificial_correction_package
    original_runner = fixture["dependencies"]["families"]
    original_hash = correction.sha(correction.packed(fixture["source"]["profiles"][0]))
    identifier = fixture["source"]["profiles"][0]["profile_id"]
    def stale_runner(*args, **kwargs):
        result = original_runner(*args, **kwargs)
        row = next(row for row in result["case_proposals"] if row["profile_id"] == identifier)
        assert row["candidate_record_sha256"] != original_hash
        row["candidate_record_sha256"] = original_hash
        return result
    fixture["dependencies"]["families"] = stale_runner
    before = fixture["original_working"].read_bytes()
    with pytest.raises(ValueError):
        correction.execute(fixture["root"], activity_path=fixture["artifact_path"], dependencies=fixture["dependencies"], emit=lambda _message: None)
    assert not (fixture["root"] / "results/step33_2_fixture_summary.json").exists()
    assert fixture["original_working"].read_bytes() == before


@pytest.mark.parametrize("defect", ["missing_case", "duplicate_case", "case_approval", "unknown_base", "wrong_source_value",
    "resource_unknown", "outside_window", "bad_elapsed", "repetition_converted_to_minutes"])
def test_activity_evidence_errors_stop_before_private_food_or_family_work(correction, artificial_correction_package, defect):
    fixture = artificial_correction_package
    activity = fixture["activity"]
    row = activity["cases"][0]
    if defect == "missing_case":
        activity["cases"].pop()
    elif defect == "duplicate_case":
        activity["cases"][1] = copy.deepcopy(row)
    elif defect == "case_approval":
        row["approved"] = True
    elif defect == "unknown_base":
        row["candidate_options"][0]["catalog_candidate_id"] = "not_in_source_snapshot"
    elif defect == "wrong_source_value":
        row["candidate_options"][0]["source_evidence"]["instructions"]["value"] = "Invented source instruction"
    elif defect == "resource_unknown":
        row["candidate_options"][0]["unknown_conditions"] = ["Partner availability not established"]
    elif defect == "outside_window":
        row["selected_example"]["witness_slots"][0].update(start_time="18:00", end_time="18:03")
    elif defect == "bad_elapsed":
        row["selected_example"]["witness_slots"][0]["duration_minutes"] = 2
    else:
        fixture["source"]["resources"]["records"][0]["source_prescription"] = "2 × 10"
        for case in activity["cases"]:
            case["candidate_options"][0]["source_evidence"]["source_prescription"]["value"] = "2 × 10"
            case["candidate_options"][0]["elapsed_prescription"]["source_text"] = "2 × 10"
            case["selected_example"]["witness_slots"][0]["source_prescription"] = "2 × 10"
    (fixture["root"] / fixture["artifact_path"]).write_bytes(correction.packed(activity))
    with pytest.raises(ValueError):
        correction.execute(fixture["root"], activity_path=fixture["artifact_path"], dependencies=fixture["dependencies"], emit=lambda _message: None)
    assert fixture["calls"] == {"food": 0, "families": 0}
    assert not (fixture["root"] / "results/step33_2_fixture_summary.json").exists()
