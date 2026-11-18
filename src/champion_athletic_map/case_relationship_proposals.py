"""Prepare concrete relationship proposals from the saved case facts and authoring trace."""
from collections import Counter, defaultdict
from copy import deepcopy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import re
BASE = Path(__file__).resolve().parent
ORIGINAL = BASE.parent / 'work_step33_review/input_package/review_cb1efb8523e7c29384d3'
CURRENT = BASE / 'input/corrections_331ea7ad69567f8f6472'
PROTECTED = 'results/profile_preparation/protected_test_drafts_6f292bd047b72685'
DEVELOPMENT = 'results/profile_preparation/development_drafts_7b7f2fc781077cdc'

def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def sha(data):
    return hashlib.sha256(data).hexdigest()

def csv_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))

def records(data):
    return [json.loads(line) for line in data.splitlines() if line.strip()]

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def facts(left, right):
    shared, different = ([], [])
    for field in sorted(set(left) | set(right)):
        if field in left and field in right and (left[field] == right[field]):
            shared.append({'field': field, 'value': left[field]})
        else:
            different.append({'field': field, 'candidate_present': field in left, 'candidate': left.get(field), 'counterpart_present': field in right, 'counterpart': right.get(field)})
    return {'equal_public_fields': shared, 'different_public_fields': different}

def prepare_relationship_proposals(original_package, correction_package, project_root, output_folder, *, profiles_override=None, compare_populations=None):
    """Read bound private files and prepare suggestions without adopting any decision."""
    ORIGINAL, CURRENT, PROJECT, BASE = (Path(p).resolve() for p in (original_package, correction_package, project_root, output_folder))
    BASE.mkdir(parents=True, exist_ok=True)
    original_manifest = json.loads((ORIGINAL / 'manifest.json').read_bytes())
    current_manifest = json.loads((CURRENT / 'manifest.json').read_bytes())
    for folder, manifest in ((ORIGINAL, original_manifest), (CURRENT, current_manifest)):
        for relative, expected in manifest['files'].items():
            if not sha((folder / relative).read_bytes()) == expected:
                raise ValueError('Family review evidence check failed: ' + str(relative))
    native = json.loads((CURRENT / 'family_rescreen.json').read_bytes())
    originals = {r['profile_id']: r for r in records((ORIGINAL / 'source_public_profiles.jsonl').read_bytes())}
    candidates = {r['profile_id']: r for r in records((CURRENT / 'proposed_public_profiles.jsonl').read_bytes())}
    metadata = {r['profile_id']: r for r in csv_rows(ORIGINAL / 'source_manifest.csv')}
    lineage = csv_rows(ORIGINAL / 'source_field_lineage.csv')
    prior_pairs = csv_rows(ORIGINAL / 'draft_templates/protected_pair_review_evidence_TEMPLATE.csv')
    if not (len(originals) == len(candidates) == 200 and originals.keys() == candidates.keys()):
        raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
    if not (len(prior_pairs) == 618 and len({p['screen_pair_id'] for p in prior_pairs}) == 618):
        raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
    protected_summary = json.loads((PROJECT / PROTECTED / 'step16_protected_test_drafts_summary.json').read_bytes())
    development_summary = json.loads((PROJECT / DEVELOPMENT / 'step16_development_drafts_summary.json').read_bytes())
    bound = {}
    for relative, expected in native['source_file_sha256'].items():
        path = PROJECT / relative
        if path.is_file():
            if not sha(path.read_bytes()) == expected:
                raise ValueError('Family review evidence check failed: ' + str(relative))
            bound[relative] = expected
    for folder, summary, files in ((PROTECTED, protected_summary, ('protected_generator.py', 'protected_authoring_config.json', 'protected_test_authoring_arguments.csv')), (DEVELOPMENT, development_summary, ('development_draft_inputs.jsonl', 'development_draft_field_lineage.csv', 'development_authoring_config.json'))):
        for filename in files:
            path = PROJECT / folder / filename
            expected = summary['artifacts'][filename]
            if not sha(path.read_bytes()) == expected:
                raise ValueError('Family review evidence check failed: ' + str(filename))
            bound[folder + '/' + filename] = expected
    helper = module(PROJECT / PROTECTED / 'protected_generator.py', 'step33_original_generator')
    arguments = {r['profile_id']: r for r in csv_rows(PROJECT / PROTECTED / 'protected_test_authoring_arguments.csv')}
    if not arguments.keys() == originals.keys():
        raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
    authoring_trace = {}
    for pid, row in arguments.items():
        args = json.loads(row['arguments_json'])
        if not sha(packed(args)) == row['arguments_sha256']:
            raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
        replayed = helper.build_protected_candidate(*args)
        if not replayed['record'] == originals[pid]:
            raise ValueError('Family review evidence check failed: ' + str(pid))
        if not (not args[0]['parent_source_record_key'] and args[0]['origin_plan'] == 'new_fictional_base_planned'):
            raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
        authoring_trace[pid] = {'arguments_sha256': row['arguments_sha256'], 'blueprint_slot_id': args[0]['blueprint_slot_id'], 'origin_plan': args[0]['origin_plan'], 'recorded_parent_source_record_key': args[0]['parent_source_record_key'], 'replay_exactly_matches_original': True, 'complete_argument_kinds': ['reserved_test_slot', 'minimal_public_contract', 'reference_dates', 'optional_food_fact_descriptor'], 'development_or_legacy_record_passed_to_generator': False}
    if not not any((row['parent_source_record_key'] for row in lineage)):
        raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
    pool_data = (PROJECT / DEVELOPMENT / 'development_draft_inputs.jsonl').read_bytes()
    pool = {r['profile_id']: r for r in records(pool_data)}
    if not len(pool) == 100:
        raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
    author_source = PROJECT / 'artifacts/pilot/case_review_source_v1.json'
    authoring = json.loads(author_source.read_bytes())
    amended, amendments = ([], [])
    for row in authoring['rows']:
        original = pool[row['profile_id']]
        record = deepcopy(original)
        record['schema_version'] = 'athlete-profile-input-2'
        complete = authoring['public_authoring_decisions'][record['profile_id']]['existing_commitments_complete']
        record['input']['schedule_coverage'] = {**record['input']['planning_window'], 'existing_commitments_complete': complete}
        amended.append(record)
        amendments.append({'profile_id': record['profile_id'], 'source_public_record_sha256': sha(canonical(original)), 'amended_public_record_sha256': sha(canonical(record)), 'change': 'Added explicit fictional weekly schedule coverage; preserved all earlier fields.', 'author_type': 'assistant_under_Sam_delegated_authority', 'existing_commitments_complete': complete, 'basis': 'New synthetic authoring decision, not an inference from an empty or nonempty list.', 'meaning': 'All existing training and sport activity for this window, including informal sessions, is listed.' if complete else 'Existing weekly commitments remain unknown; no completeness attestation is made.'})
    recovery = {}
    recovered_folder = BASE / 'recovered_development'
    recovered_folder.mkdir(exist_ok=True)
    for suffix, data in (('public_profiles.jsonl', b''.join((canonical(r) + b'\n' for r in amended))), ('public_amendments.json', packed(amendments))):
        relative, expected = next(((p, s) for p, s in native['source_file_sha256'].items() if p.endswith('/' + suffix)))
        if not sha(data) == expected:
            raise ValueError('Family review evidence check failed: ' + str('The recovered native development bytes differ: ' + suffix))
        (recovered_folder / suffix).write_bytes(data)
        recovery[suffix] = {'native_path': relative, 'native_sha256': expected, 'recovered_sha256': sha(data), 'exact_bytes_verified': True}
    amended = {r['profile_id']: r for r in amended}
    dev_lineage = csv_rows(PROJECT / DEVELOPMENT / 'development_draft_field_lineage.csv')
    dev_parents = defaultdict(set)
    for row in dev_lineage:
        if row['parent_source_record_key']:
            dev_parents[row['profile_id']].add(row['parent_source_record_key'])

    def pair_proposals(pair_rows, inputs, scope):
        proposals, grouped = ([], defaultdict(list))
        for pair in pair_rows:
            pid, did = (pair['candidate_profile_id'], pair['development_profile_id'])
            left = inputs[pid]
            right = (pool if pair['development_version'] == 'original_development_drafts_v1' else amended)[did]
            if not sha(packed(left)) == pair['candidate_record_sha256']:
                raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
            if not sha(packed(right)) == pair['development_record_sha256']:
                raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
            exact = left['input'] == right['input']
            lc, rc = (deepcopy(left['input']), deepcopy(right['input']))
            lc.pop('schedule_coverage', None)
            rc.pop('schedule_coverage', None)
            common = lc == rc
            if not (exact == pair['exact_full_input'] and common == pair['common_input_equal_without_schedule_coverage']):
                raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
            lv, rv = (helper.comparison_view(left), helper.comparison_view(right))
            finding = helper.compare_views(lv, rv, left['input'].get('athlete_request', ''), right['input'].get('athlete_request', ''), exact_full_input=exact) or {}
            if not finding == pair['original_screen_findings']:
                raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
            matches = json.loads(finding.get('matching_known_fields_json', '[]'))
            differs = json.loads(finding.get('different_known_fields_json', '[]'))
            compared = facts(left['input'], right['input'])
            note = 'Retain as a distinct authored candidate. Shared ' + ', '.join(matches) + ' triggered the coarse screen; the recorded ' + ', '.join(differs) + ' differ. The exact ORIGINAL protected-base replay uses no development record or source parent. ' + 'Record the listed later authoring changes separately. Do not group this candidate with the development profile as a copied athlete on these facts.'
            if exact or common:
                note = 'Hold this relation for an explicit duplicate/derivation decision: complete public facts match ' + ('exactly.' if exact else 'when schedule coverage is removed; the coverage difference remains a real fact difference.')
            result = {'pair_id': pair['pair_id'], 'candidate_profile_id': pid, 'development_profile_id': did, 'comparison_scope': scope, 'development_version': pair['development_version'], 'candidate_record_sha256': pair['candidate_record_sha256'], 'development_record_sha256': pair['development_record_sha256'], 'matching_screen_facts': [{'field': k, 'value': lv[k]} for k in matches], 'different_screen_facts': [{'field': k, 'candidate': lv[k], 'development': rv[k]} for k in differs], **compared, 'original_base_authoring_trace': authoring_trace[pid], 'current_vs_original_public_fields': facts(left['input'], originals[pid]['input'])['different_public_fields'], 'development_recorded_source_parents': sorted(dev_parents[did]), 'exact_full_input_match': exact, 'common_input_match_ignoring_coverage': common, 'proposed_relationship': 'possible_complete_fact_duplicate_requires_explicit_review' if exact or common else 'distinct_authored_case_with_shared_generic_or_design_facts', 'suggested_decision': 'hold_for_duplicate_or_parent_review' if exact or common else 'retain_separate_fictional_base', 'suggested_rationale': note, 'suggested_development_family_merge': False, 'suggested_exclusion_as_duplicate': False, 'family_adoption_or_exclusion_applied': False, 'team_decision': None, 'limitation': 'Reproduction establishes only the recorded ORIGINAL base authoring inputs, not independence from shared benchmark design, wording, subsequent amendments or unrecorded author knowledge.'}
            proposals.append(result)
            grouped[pid].append(result)
        return (proposals, grouped)
    native_proposals, native_by_case = pair_proposals(native['flagged_pairs'], candidates, 'native_step33_2_historical_candidate_versions')
    if not (len(native_proposals) == 59 and len(native_by_case) == 41):
        raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
    baseline_candidates = candidates
    rescreen = None
    if profiles_override is not None:
        supplied = deepcopy(list(profiles_override))
        if not (len(supplied) == 200 and len({r['profile_id'] for r in supplied}) == 200):
            raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
        candidates = {r['profile_id']: r for r in supplied}
        if not candidates.keys() == originals.keys():
            raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
        if not callable(compare_populations):
            raise ValueError('Family review evidence check failed: ' + str('A fresh unchanged-screen compare_populations callback is required for amended candidate versions.'))
        rescreen = compare_populations(supplied, [{'label': 'original_development_drafts_v1', 'profiles': list(pool.values())}, {'label': 'versioned_pilot_development_v2', 'profiles': list(amended.values())}], helper)
        if not sum(rescreen['comparison_counts'].values()) == 24000:
            raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
        current_proposals, by_case = pair_proposals(rescreen['flagged_pairs'], candidates, 'fresh_screen_of_supplied_amended_candidate_versions')
    else:
        current_proposals, by_case = (native_proposals, native_by_case)
    prior_proposals = []
    legacy_by_case = defaultdict(list)
    for row in prior_pairs:
        pid, other_id, kind = (row['candidate_profile_id'], row['other_record_id'], row['comparison_kind'])
        left = originals[pid]
        raw = json.loads(row['other_raw_evidence_json'])
        if not json.loads(row['candidate_input_json']) == left['input']:
            raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
        if not sha(packed(left)) == row['candidate_record_sha256']:
            raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
        if not sha(packed(left['input'])) == row['candidate_input_sha256']:
            raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
        if kind == 'legacy_source':
            if not sha(packed(raw)) == row['other_record_sha256']:
                raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
            right = raw
            lv, rv = (helper.comparison_view(left), helper.comparison_view(right, raw_source=True))
            detail = {'legacy_raw_evidence': raw, 'unavailable_comparable_source_fields': ['dated_availability', 'time_limits', 'detailed_space', 'participants', 'existing_commitments', 'school_grade', 'full_request']}
        else:
            right = {'profile_id': other_id, 'schema_version': 'athlete-profile-input-1', 'input': raw}
            if not sha(packed(right)) == row['other_record_sha256']:
                raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
            if not sha(packed(raw)) == row['other_input_sha256']:
                raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
            if not raw == (originals[other_id] if kind == 'protected_candidate' else pool[other_id])['input']:
                raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
            lv, rv = (helper.comparison_view(left), helper.comparison_view(right))
            detail = facts(left['input'], right['input'])
        matches, differs = (json.loads(row['matching_known_fields_json']), json.loads(row['different_known_fields_json']))
        if not all((lv[k] == rv[k] for k in matches)):
            raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
        if not all((lv[k] != rv[k] for k in differs)):
            raise ValueError('Family review evidence check failed: ' + str('The saved private family-review evidence is inconsistent.'))
        repeated, partial = (row['repeated_request'] == 'True', row['partial_source_projection_match'] == 'True')
        if kind == 'legacy_source':
            relation = 'partial_legacy_attribute_resemblance_without_recorded_source_parent' if partial else 'generic_legacy_attribute_resemblance_without_recorded_source_parent'
            rationale = 'Retain the authored draft separately from ' + other_id + '. The replayed protected authoring call contains no legacy record or source parent. ' + ('All six comparable coarse facts match, but detailed source scheduling and resource facts are unavailable; this is not a verified full duplicate.' if partial else 'The coarse equal fields are ' + ', '.join(matches) + '; ' + ', '.join(differs) + ' differ. These broad attributes do not establish a parent relationship.')
        elif repeated:
            relation = 'shared_request_template_distinct_authored_case_facts'
            rationale = 'Retain both distinct authored bases. The literal request is reused, so record a shared task/wording-pattern tag; their full inputs differ. Both exact authoring replays have separate reserved slots and no source parent. Do not interpret template reuse as separate independent users or merge athlete families by wording alone.'
        else:
            relation = 'distinct_authored_case_with_shared_generic_or_design_facts'
            rationale = 'Retain separate authored bases. The shared ' + ', '.join(matches) + ' are coarse benchmark facts; ' + ', '.join(differs) + ' differ. The protected authoring call uses its own reserved slot and no counterpart record or source parent.'
        proposal = {'screen_pair_id': row['screen_pair_id'], 'candidate_profile_id': pid, 'comparison_kind': kind, 'other_record_id': other_id, 'original_flag_row_sha256': sha(packed(row)), 'original_flags_preserved': {k: row[k] == 'True' for k in ('exact_full_input', 'repeated_request', 'partial_source_projection_match', 'known_fact_similarity', 'cross_goal_context_similarity')}, 'matching_screen_facts': [{'field': k, 'value': lv[k]} for k in matches], 'different_screen_facts': [{'field': k, 'candidate': lv[k], 'counterpart': rv[k]} for k in differs], **detail, 'candidate_authoring_trace': authoring_trace[pid], 'suggested_relationship': relation, 'suggested_decision': 'retain_separate_fictional_base_with_unresolved_source_comparison' if kind == 'legacy_source' else 'retain_separate_fictional_base', 'suggested_rationale': rationale, 'suggested_family_merge': False, 'suggested_exclusion_as_duplicate': False, 'remaining_relationship_unknowns': ['The legacy source lacks complete dated scheduling, resource and request facts; complete source equality cannot be assessed.', 'No direct recorded parent is present, but unrecorded authoring ancestry cannot be ruled out.'] if kind == 'legacy_source' else ['Shared benchmark recipe and wording create design dependence; distinct bases do not imply independent users or statistically independent tasks.'], 'legacy_relationship_cleared': False if kind == 'legacy_source' else None, 'team_decision': None, 'original_flag_row_changed': False}
        prior_proposals.append(proposal)
        if kind == 'legacy_source':
            legacy_by_case[pid].append(proposal)
    case_proposals = []
    for pid, pairs in sorted(by_case.items()):
        fields = Counter((f['field'] for p in pairs for f in p['different_screen_facts']))
        match_hold = any((p['exact_full_input_match'] or p['common_input_match_ignoring_coverage'] for p in pairs))
        case_proposals.append({'profile_id': pid, 'current_candidate_record_sha256': sha(packed(candidates[pid])), 'current_development_pair_ids': [p['pair_id'] for p in pairs], 'distinct_linked_development_profile_ids': sorted({p['development_profile_id'] for p in pairs}), 'version_links': len(pairs), 'recorded_difference_counts_by_screen_field': dict(fields), 'candidate_authoring_trace': authoring_trace[pid], 'proposed_disposition': 'hold_for_duplicate_or_parent_review' if match_hold else 'retain_as_distinct_authored_draft', 'suggested_family_id': None if match_hold else metadata[pid]['proposed_family_id'], 'suggested_family_basis': 'One separately authored fictional base from this reserved test slot; no recorded shared source parent. Shared recipe/template dependence remains a study limitation.', 'development_family_merge_proposed': False, 'duplicate_exclusion_proposed': False, 'legacy_flags_retained': [{'pair_id': p['screen_pair_id'], 'other_record_id': p['other_record_id'], 'partial_source_projection_match': p['original_flags_preserved']['partial_source_projection_match']} for p in legacy_by_case[pid]], 'proposed_rationale': 'The ' + str(len(pairs)) + ' saved development-version links concern ' + str(len({p['development_profile_id'] for p in pairs})) + ' distinct development record(s). ' + ('A full or coverage-aligned fact match now needs an explicit duplicate/parent decision before proceeding.' if match_hold else 'Recorded differences include ' + ', '.join(sorted(fields)) + '; no input is equal even after removing schedule coverage. ' + 'The ORIGINAL protected base replays exactly from its own slot without any development/source record argument. Record the later authoring amendments separately, keep its separate-base proposal, and record shared design patterns.'), 'accepted_for_final_run': False, 'adopted_family_id': None, 'team_decision': None})
    literal_groups, pattern_groups, incident = (defaultdict(list), defaultdict(list), defaultdict(list))
    for pid, record in originals.items():
        text = record['input']['athlete_request']
        literal_groups[text].append(pid)
        for goal in record['input'].get('goals') or []:
            text = text.replace(goal, '<GOAL>')
        text = re.sub('\\d+', '<NUMBER>', text)
        text = re.sub('\\bblocks\\b', 'block', text)
        pattern_groups[text].append(pid)
    for proposal in prior_proposals:
        incident[proposal['candidate_profile_id']].append(proposal)
        if proposal['comparison_kind'] == 'protected_candidate':
            incident[proposal['other_record_id']].append(proposal)
    literal_tags = {pid: 'literal-request-design:' + sha(packed(text))[:20] for text, ids in literal_groups.items() for pid in ids}
    pattern_tags = {pid: 'request-pattern-design:' + sha(packed(text))[:20] for text, ids in pattern_groups.items() for pid in ids}
    all_cases = []
    for pid in sorted(candidates):
        legacy = legacy_by_case[pid]
        rows = incident[pid]
        match_hold = any((p['exact_full_input_match'] or p['common_input_match_ignoring_coverage'] for p in by_case[pid]))
        all_cases.append({'profile_id': pid, 'candidate_record_sha256': sha(packed(candidates[pid])), 'suggested_case_disposition': 'hold_for_duplicate_or_parent_review' if match_hold else 'retain_distinct_authored_draft_with_unresolved_legacy_comparison' if legacy else 'retain_distinct_authored_draft', 'suggested_family_id': None if match_hold else metadata[pid]['proposed_family_id'], 'original_base_family_basis': authoring_trace[pid], 'current_vs_original_public_fields': facts(candidates[pid]['input'], originals[pid]['input'])['different_public_fields'], 'prior_incident_pair_ids': sorted((p['screen_pair_id'] for p in rows)), 'current_development_pair_ids': [p['pair_id'] for p in by_case[pid]], 'literal_request_design_tag': literal_tags[pid], 'request_pattern_design_tag': pattern_tags[pid], 'proposed_rationale': 'Keep this separately authored reserved-slot base; its original record replays exactly without a counterpart record or parent argument. Keep shared request/recipe patterns as design-correlation tags, and do not call this an independent real athlete. ' + ('Retain the listed legacy resemblance flags as unresolved complete-source comparisons; do not clear them merely from replay or uniqueness.' if legacy else 'The attached pair comparisons document concrete shared and different facts; original-base replay does not automatically clear subsequent authoring amendments.') + (' A new full or coverage-aligned match requires an explicit duplicate/parent decision.' if match_hold else ''), 'remaining_legacy_complete_source_comparison_count': len(legacy), 'shared_recipe_dependence_cleared': False, 'independence_established': False, 'adopted_family_id': None, 'accepted_for_final_run': False, 'team_decision': None})
    result = {'schema_version': 'step33-concrete-relationship-proposals-1', 'source_package_id': original_manifest['package_id'], 'source_correction_id': current_manifest.get('correction_id', current_manifest.get('package_id')), 'source_current_family_rescreen_sha256': sha((CURRENT / 'family_rescreen.json').read_bytes()), 'review_status': 'prepared_relationship_proposals_for_team_review', 'decision_policy': ['A duplicate or direct source-family relation requires complete fact equality or recorded derivation/parent evidence, not a shared age, goal, template or opaque identifier.', 'For these synthetic bases, propose one case-family per separately authored reserved slot when faithful authoring replay shows no parent record; treat this as a constructed-case design choice, not evidence of independent people.', 'Keep task/wording patterns as separate design-correlation tags. Never union every similarity edge into athlete ancestry; describe this recipe dependence when reporting uncertainty.', 'No suggestion is an adopted family, final-case acceptance, exclusion or team approval. Record preparer and distinct teammate decisions through the existing review process before freezing.', 'All original flags, including legacy partial matches, remain evidence; proposing no merge does not erase them or claim absence of leakage.'], 'source_verification': {'original_and_current_manifest_file_bindings_verified': True, 'project_bound_sources_verified': bound, 'all_original_200_protected_records_replayed_exactly': True, 'protected_authoring_arguments_containing_parent_or_counterpart_records': 0, 'protected_lineage_rows': len(lineage), 'protected_lineage_rows_with_parent_source': 0, 'native_20_development_recovery': {'method': 'Faithful replay of production public-authoring decisions over the authentic full100 pool; serialized files match uploaded native receipts exactly before use.', 'source_authoring_decisions_path': author_source.relative_to(PROJECT).as_posix(), 'source_authoring_decisions_sha256': sha(author_source.read_bytes()), 'files': recovery, 'record_count': 20, 'changes': 'Declared schedule_coverage and schema version only'}}, 'summary': {'current_flagged_cases_reviewed': len(case_proposals), 'current_development_version_links_reviewed': len(current_proposals), 'current_distinct_candidate_development_links': len({(p['candidate_profile_id'], p['development_profile_id']) for p in current_proposals}), 'current_link_counts_by_version': dict(Counter((p['development_version'] for p in current_proposals))), 'historical_native_development_version_links': len(native_proposals), 'historical_native_flagged_cases': sum((bool(v) for v in native_by_case.values())), 'fresh_amended_candidate_rescreen_completed': rescreen is not None, 'current_exact_or_common_input_matches': sum((p['exact_full_input_match'] or p['common_input_match_ignoring_coverage'] for p in current_proposals)), 'current_proposed_distinct_authored_drafts': sum((p['proposed_disposition'] == 'retain_as_distinct_authored_draft' for p in case_proposals)), 'prior_flag_rows_preserved_and_reviewed': len(prior_proposals), 'prior_flags_by_kind': dict(Counter((p['comparison_kind'] for p in prior_proposals))), 'legacy_partial_matches_retained': sum((p['original_flags_preserved']['partial_source_projection_match'] for p in prior_proposals)), 'prior_repeated_literal_request_links': sum((p['original_flags_preserved']['repeated_request'] for p in prior_proposals)), 'all_case_family_rationales_prepared': len(all_cases), 'unresolved_legacy_complete_source_comparisons': 9, 'literal_request_design_groups': len(literal_groups), 'normalized_request_pattern_design_groups': len(pattern_groups), 'family_adoptions_applied': 0, 'cases_excluded': 0, 'team_approvals_created': 0, 'new_model_calls': 0, 'source_public_values_changed': 0}, 'current_flagged_case_proposals': case_proposals, 'current_development_pair_proposals': current_proposals, 'historical_native_development_pair_proposals': native_proposals, 'fresh_candidate_rescreen': rescreen, 'current_candidate_versions': {'override_supplied': profiles_override is not None, 'records_differing_from_native_step33_2': sum((candidates[pid] != baseline_candidates[pid] for pid in candidates)), 'record_set_sha256': sha(b''.join((canonical(candidates[pid]) + b'\n' for pid in sorted(candidates)))), 'records': [{'profile_id': pid, 'sha256': sha(packed(candidates[pid]))} for pid in sorted(candidates)]}, 'retained_prior_pair_proposals': prior_proposals, 'all_case_family_proposals': all_cases, 'shared_design_pattern_groups': [{'design_tag': pattern_tags[ids[0]], 'pattern': text, 'profile_ids': sorted(ids), 'case_count': len(ids), 'adopted_sampling_family': False} for text, ids in sorted(pattern_groups.items())], 'uncertainty_design_recommendation': 'The proposed singleton case families represent authored bases, not independence. Before final scoring, agree whether uncertainty is conditional on this fixed constructed-case set; if estimating generalization, predeclare a sensitivity analysis grouped by the14 wording-pattern tags or another justified task-design unit. Do not silently call the200 cases independent users or automatically merge them by the similarity graph.', 'limits': ['Direct-argument replay does not recover unrecorded author knowledge or make shared templates statistically independent.', 'Legacy records contain limited source fields; the two SYN044 matches are partial projection matches, not established full duplicates.', 'The 20 amended pilot records are versions of selected original100 development profiles, not20 additional athletes.', 'Family decision proposals are private review evidence and must not be injected into planner retrieval, prompts or final outputs.'], 'source_facts_edited': False, 'model_calls': 0, 'classifier_test_data_used': False}
    target = BASE / 'family_resolution_proposals.json'
    target.write_bytes(packed(result))
    return result

def main():
    project = json.loads((BASE.parent / 'work_step31_18/portable_project.json').read_bytes())['project']
    result = prepare_relationship_proposals(ORIGINAL, CURRENT, project, BASE)
    print(json.dumps(result['summary'], indent=2))
if __name__ == '__main__':
    main()
