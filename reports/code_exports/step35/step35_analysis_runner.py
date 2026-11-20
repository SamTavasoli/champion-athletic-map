"""Saved-evidence analysis. No fitting, model inference, retrieval or revisions."""
from __future__ import annotations
import csv
import hashlib
import html
import io
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile
import numpy as np
from step35_statistics_core import (CONTRASTS, CLASSIFIER_CONTRASTS, paired_binary_counts, bootstrap_planner, analyze_classifier_records)
from step35_classifier_inputs import load_classifier, MissingClassifierInput
from step35_retrieval_analysis import analyze_retrieval
from step35_native_runtime_analysis import analyze_runtime_details

DIMENSIONS = ('response_suitability', 'profile_fit', 'practicality_completeness', 'evidence_accuracy', 'clarity')
EXPECTED_CATEGORIES = {'feasible': 150, 'missing_information': 20, 'conflicting_constraints': 15, 'outside_scope': 15}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def packed(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def rows_from_bytes(data):
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def safe_path(root, relative):
    require(isinstance(relative, str) and '\\' not in relative and ':' not in relative, 'Invalid saved evidence path.')
    candidate = (root / relative).resolve()
    require(candidate.is_relative_to(root), 'Saved evidence path leaves the project.')
    return candidate


def csv_content(rows):
    fields = list(dict.fromkeys(key for row in rows for key in row)) if rows else ['status']
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (list, dict, tuple)) else value
                         for key, value in row.items()})
    return stream.getvalue().encode('utf-8-sig')


def read_planners(root, expected_members):
    archive = root / 'results/step33_saved_results_review.zip'
    with ZipFile(archive) as source:
        members = {name: source.read(name) for name in expected_members}
    require(all(sha(members[name]) == expected for name, expected in expected_members.items()), 'The saved Step 33 comparison export changed.')
    rows = rows_from_bytes(members['saved_outcomes.jsonl']); ledger = rows_from_bytes(members['saved_ledger.jsonl'])
    protocol = json.loads(members['frozen_comparison_protocol.json']); summary = json.loads(members['comparison_summary.json'])
    source_hashes = json.loads(members['source_file_sha256.json'])
    by_job = {row['job_id']: row for row in rows}; entries = {row['job_id']: row for row in ledger}
    require(len(rows) == len(by_job) == len(ledger) == len(entries) == 800 and set(by_job) == set(entries), 'The comparison needs all 800 unique designated outcomes and assessments.')
    for row in rows:
        item = entries[row['job_id']]
        require(item['execution_state'] == 'terminal' and item['assessment_execution'] == 'completed' and item['metric_state'] == 'assessed', 'An unstarted, unresolved or unassessed planner job remains incomplete.')
        for field in ('profile_id', 'family_id', 'planner_version', 'case_category', 'public_record_sha256', 'designated_outcome_sha256', 'assessment_sha256'):
            require(row[field] == item[field], 'A saved planner identity or canonical assessment hash differs: ' + field)
        require(all(item.get(key) == value for key, value in row['final_metrics'].items() if key != 'applicable_category'), 'Ledger and saved metric flags disagree.')
        require(all(type(row['final_metrics'][key]) is bool for key in ('strict_format_valid', 'designated_workflow_completed', 'automated_declared_checks_pass', 'complete_request_fulfillment_verified', 'category_response_success')), 'A missing saved metric cannot be substituted with a failure.')
        primary = row['final_metrics']['automated_feasible_plan_success']
        require((type(primary) is bool) if row['case_category'] == 'feasible' else primary is None, 'The primary metric must remain applicable only to feasible requests.')
        require(row['raw_text_sha256'] == (None if row['raw_text'] is None else sha(row['raw_text'].encode('utf-8'))), 'A saved raw reply differs from its original text hash.')
        require(row['assessment_path'] in source_hashes and source_hashes.get(row['transport_record_path']) == row['transport_record_sha256'], 'The saved assessment/transport source bindings are incomplete.')
    matched = {(row['profile_id'], row['planner_version']): row for row in rows}
    profiles = sorted({row['profile_id'] for row in rows})
    require(len(matched) == 800 and len(profiles) == 200 and all((profile, version) in matched for profile in profiles for version in range(1, 5)), 'The four-planner comparison roster is incomplete.')
    bases = [matched[profile, 1] for profile in profiles]
    require(Counter(row['case_category'] for row in bases) == EXPECTED_CATEGORIES, 'The frozen final scenario denominators differ.')
    for profile in profiles:
        for key in ('family_id', 'case_category', 'public_record_sha256'):
            require(len({matched[profile, version][key] for version in range(1, 5)}) == 1, 'Matched profile metadata differs across planners.')
    require(protocol['metric_definitions']['paired']['contrasts'] == ['V2-V1', 'V3-V2', 'V4-V3', 'V4-V1'], 'The frozen comparison directions differ.')
    candidate_path = safe_path(root, protocol['original_settings_protocol_path'])
    candidate_status = 'bound_in_export_not_reopened'
    input_hashes = {'results/step33_saved_results_review.zip': sha(archive.read_bytes())}
    if candidate_path.is_file():
        raw = candidate_path.read_bytes()
        require(sha(raw) == protocol['original_settings_protocol_sha256'], 'The original planner protocol candidate hash differs.')
        original = json.loads(raw)
        require(original['metric_definitions_candidate'] == protocol['metric_definitions'] and original['order_policy'] == protocol['order_policy'], 'The final protocol differs from its original settings snapshot.')
        input_hashes[protocol['original_settings_protocol_path']] = sha(raw);candidate_status = 'reopened_and_verified'
    return {'rows': rows, 'ledger': ledger, 'matched': matched, 'profiles': profiles, 'bases': bases, 'protocol': protocol,
        'summary': summary, 'source_hashes': source_hashes, 'member_hashes': expected_members, 'input_hashes': input_hashes, 'original_protocol_check': candidate_status}


def read_review(root, planner, expected_review_id):
    pointer = root / 'results/step34_team_review_summary.json'
    summary = json.loads(pointer.read_bytes())
    require(summary['review_id'] == expected_review_id, 'The Step 34 review version differs from this analysis.')
    folder = safe_path(root, summary['review_folder'])
    manifest = json.loads((folder / 'review_manifest.json').read_bytes())
    inputs = {pointer.relative_to(root).as_posix(): sha(pointer.read_bytes())}
    for name, expected in manifest['files'].items():
        path = safe_path(root, (folder / name).relative_to(root).as_posix());raw = path.read_bytes()
        require(sha(raw) == expected, 'A locked team review artifact has changed: ' + name)
        inputs[path.relative_to(root).as_posix()] = expected
    require(all(planner['member_hashes'].get(name) == value for name, value in manifest['source_member_sha256'].items()), 'The review refers to another saved comparison.')
    locked = json.loads((folder / 'rating_lock.json').read_bytes());raw = (folder / 'ratings.jsonl').read_bytes()
    require(locked['ratings_sha256'] == sha(raw), 'The completed review does not match its lock.')
    reviews = rows_from_bytes(raw);bindings = json.loads((folder / 'private_response_binding.json').read_bytes())
    ratings = {review['response_id']: review for review in reviews};key = {row['response_id']: row for row in bindings}
    require(len(reviews) == len(ratings) == len(bindings) == len(key) == 160 and set(ratings) == set(key), 'The selected review needs all 160 unchanged replies.')
    original_key = rows_from_bytes(ZipFile(root / 'results/step33_saved_results_review.zip').read('private_review_binding/private_bound_response_key.jsonl'))
    require(key == {row['response_id']: row for row in original_key}, 'The reviewed sample differs from the pre-output selection.')
    matched_ratings = {}
    for response_id, review in ratings.items():
        binding = key[response_id];outcome = planner['matched'][binding['profile_id'], binding['planner_version']]
        require(binding['response_text_sha256'] == outcome['raw_text_sha256'] and binding['designated_outcome_sha256'] == outcome['designated_outcome_sha256'], 'A review is not bound to its designated reply.')
        require(set(review['ratings']) == set(DIMENSIONS), 'A review dimension is missing.')
        for dimension, rating in review['ratings'].items():
            require((rating['status'] == 'rated' and type(rating['score']) is int and rating['score'] in (0, 1, 2))
                    or (dimension == 'evidence_accuracy' and rating['status'] == 'not_applicable' and rating['score'] is None and bool(rating['rationale'])), 'An unfinished or invalid review entry cannot be imputed.')
            matched_ratings[binding['profile_id'], binding['planner_version'], dimension] = rating
    profiles = sorted({row['profile_id'] for row in bindings})
    require(len(profiles) == 40 and len(matched_ratings) == 800, 'The complete supplementary review needs 40 profiles and 800 dimension entries.')
    require(summary['independent_teammate_ratings_collected'] == 0 and summary['reviewer_agreement']['computed'] is False, 'The review method must remain the executed single assisted review.')
    return {'summary': summary, 'reviews': reviews, 'matched': matched_ratings, 'profiles': profiles, 'input_hashes': inputs}


def metric(row, name):
    if name == 'completed_valid_plan':
        return row['completion_valid'] and row['format_valid'] and row['response_type'] == 'plan'
    if name == 'declared_response_type_match':
        return row['response_type'] == {'missing_information': 'clarification', 'conflicting_constraints': 'constraint_conflict', 'outside_scope': 'outside_scope'}[row['case_category']]
    return row['final_metrics'][name]


def paired_tables(planner):
    rows, population_rows, headline = [], [], []
    metrics = [('all_planner', planner['profiles'], 'strict_format_valid'), ('all_planner', planner['profiles'], 'designated_workflow_completed')]
    for category in EXPECTED_CATEGORIES:
        selected = [row['profile_id'] for row in planner['bases'] if row['case_category'] == category]
        names = ('automated_feasible_plan_success', 'automated_declared_checks_pass', 'complete_request_fulfillment_verified', 'completed_valid_plan') if category == 'feasible' else ('category_response_success', 'declared_response_type_match')
        metrics.extend((category, selected, name) for name in names)
    for population, selected, name in metrics:
        for version in range(1, 5):
            numerator = sum(metric(planner['matched'][profile, version], name) for profile in selected)
            headline.append({'population': population, 'metric': name, 'planner': version, 'numerator': numerator, 'denominator': len(selected), 'percent': 100 * numerator / len(selected),
                'families': len({planner['matched'][profile, version]['family_id'] for profile in selected})})
        for later, earlier in CONTRASTS:
            counts = paired_binary_counts([metric(planner['matched'][profile, later], name) for profile in selected], [metric(planner['matched'][profile, earlier], name) for profile in selected])
            rows.append({'population': population, 'metric': name, 'contrast': f'V{later}-V{earlier}', **counts,
                'later_numerator': sum(metric(planner['matched'][profile, later], name) for profile in selected),
                'earlier_numerator': sum(metric(planner['matched'][profile, earlier], name) for profile in selected),
                'families': len({planner['matched'][profile, 1]['family_id'] for profile in selected})})
    for base in planner['bases']:
        for population in ('all_planner', base['case_category']):
            population_rows.append({'population': population, 'record_id': base['profile_id'], 'group_id': base['family_id'], 'age': base['public_input']['age'], 'case_category': base['case_category']})
    return rows, headline, population_rows


def review_tables(review, planner):
    distributions, paired = [], []
    for version in range(1, 5):
        for dimension in DIMENSIONS:
            ratings = [review['matched'][profile, version, dimension] for profile in review['profiles']]
            counts = Counter(rating['score'] for rating in ratings if rating['status'] == 'rated')
            distributions.append({'review_stream': 'single_assisted_team_review', 'planner': version, 'dimension': dimension,
                'score_0': counts[0], 'score_1': counts[1], 'score_2': counts[2], 'numeric': sum(counts.values()),
                'not_applicable': sum(rating['status'] == 'not_applicable' for rating in ratings), 'missing': 0, 'responses': 40, 'families': 40})
    for later, earlier in CONTRASTS:
        for dimension in DIMENSIONS:
            counts = Counter()
            for profile in review['profiles']:
                a, b = review['matched'][profile, later, dimension], review['matched'][profile, earlier, dimension]
                if a['status'] == b['status'] == 'rated':
                    counts['higher' if a['score'] > b['score'] else 'lower' if a['score'] < b['score'] else 'equal'] += 1
                elif a['status'] == b['status'] == 'not_applicable':
                    counts['both_not_applicable'] += 1
                else:
                    counts['one_not_applicable'] += 1
            paired.append({'review_stream': 'single_assisted_team_review', 'contrast': f'V{later}-V{earlier}', 'dimension': dimension,
                'jointly_numeric_pairs': counts['higher'] + counts['equal'] + counts['lower'], 'higher': counts['higher'], 'equal': counts['equal'], 'lower': counts['lower'],
                'both_not_applicable': counts['both_not_applicable'], 'one_not_applicable': counts['one_not_applicable'], 'missing_pairs': 0, 'profiles': 40,
                'agreement_statistic': None, 'interpretation': 'Descriptive ordinal comparison from one assisted review; not two-rater agreement or a combined quality score.'})
    return distributions, paired


def describe_times(rows):
    values = [float(row['elapsed_seconds']) for row in rows if isinstance(row.get('elapsed_seconds'), (int, float)) and math.isfinite(row['elapsed_seconds']) and row['elapsed_seconds'] >= 0]
    return {'outcomes': len(rows), 'measured': len(values), 'missing': len(rows)-len(values), 'mean_seconds': float(np.mean(values)) if values else None,
        'median_seconds': float(np.median(values)) if values else None, 'p95_seconds': float(np.percentile(values, 95, method='linear')) if values else None,
        'p95_method': 'linear percentile', 'minimum_seconds': min(values) if values else None, 'maximum_seconds': max(values) if values else None}


def runtime_tables(planner):
    times, matched, usage = [], [], []
    for version in range(1, 5):
        group = [row for row in planner['rows'] if row['planner_version'] == version]
        for population, included in (('all_terminal', group), ('workflow_completed', [r for r in group if r['completion_valid']]),
                ('workflow_not_completed', [r for r in group if not r['completion_valid']]), ('strict_format_valid', [r for r in group if r['format_valid']]),
                ('automatic_primary_success', [r for r in group if r['final_metrics']['automated_feasible_plan_success']])):
            times.append({'planner': version, 'population': population, **describe_times(included), 'scope': 'Measured saved end-to-end request time; external scoring excluded.'})
        objects = [row['usage'] for row in group if isinstance(row.get('usage'), dict)]
        for field in ('prompt_eval_count', 'eval_count', 'prompt_eval_cached_count'):
            values = [obj[field] for obj in objects if type(obj.get(field)) is int]
            usage.append({'planner': version, 'measure': field, 'observed_objects': len(values), 'expected_outcomes': 200, 'missing': 200-len(values),
                'value_sum': sum(values) if values else None, 'scope': 'Designated terminal-role usage only; excludes earlier specialist/evaluator/revision calls.', 'unit': 'tokens'})
    for later, earlier in CONTRASTS:
        for population in ('all_terminal', 'both_workflows_completed'):
            differences = []
            for profile in planner['profiles']:
                a, b = planner['matched'][profile, later], planner['matched'][profile, earlier]
                if population == 'both_workflows_completed' and not (a['completion_valid'] and b['completion_valid']):continue
                if all(isinstance(row.get('elapsed_seconds'), (int, float)) and math.isfinite(row['elapsed_seconds']) and row['elapsed_seconds'] >= 0 for row in (a, b)):
                    differences.append(a['elapsed_seconds'] - b['elapsed_seconds'])
            matched.append({'contrast': f'V{later}-V{earlier}', 'population': population, 'matched_profiles': len(differences), 'excluded_profiles': 200-len(differences),
                'mean_paired_difference_seconds': float(np.mean(differences)) if differences else None, 'median_paired_difference_seconds': float(np.median(differences)) if differences else None,
                'uncertainty_interval': None, 'interpretation': 'Observed paired timing difference; no new timing hypothesis test or post-hoc bootstrap introduced.'})
    return times, matched, usage


def diagnostic_tables(planner):
    failure_rows, parent_counts, subgroup_rows = [], defaultdict(Counter), []
    for row in planner['rows']:
        missing = row['raw_text'] is None or not row['raw_text'].strip()
        issue_codes = sorted({issue['code'] for check in (row.get('checks') or []) if isinstance(check, dict) and check.get('check_id') == 'output_structure'
            for issue in (check.get('observed') if isinstance(check.get('observed'), list) else []) if isinstance(issue, dict) and issue.get('code')})
        parents = row['parent_checks']; require(len({p['check_id'] for p in parents}) == len(parents), 'A conceptual parent check is duplicated.')
        violations = [p['check_id'] for p in parents if p['required'] and p['status'] == 'violated']
        unknowns = [p['check_id'] for p in parents if p['required'] and p['status'] == 'unknown']
        for parent in parents:
            require(parent['status'] in ('met', 'violated', 'unknown', 'not_applicable'), 'An assessment status is invalid.')
            for population in ('all_planner', row['case_category']):
                parent_counts[row['planner_version'], population, parent['check_id'], parent['required']][parent['status']] += 1
        failure_rows.append({'job_id': row['job_id'], 'profile_id': row['profile_id'], 'family_id': row['family_id'], 'planner': row['planner_version'], 'case_category': row['case_category'],
            'workflow_completed': row['completion_valid'], 'strict_format_valid': row['format_valid'], 'response_type': row['response_type'], 'missing_reply_text': missing,
            'required_violated': violations, 'required_unknown': unknowns, 'recorded_issue_codes': issue_codes,
            'workflow_error': row.get('workflow_error'), 'failed_stage': row.get('failed_stage'), 'terminal_state': row.get('terminal_state'),
            'internal_review': row.get('internal_review'), 'assessment_path': row['assessment_path'], 'assessment_canonical_sha256': row['assessment_sha256'],
            'designated_outcome_sha256': row['designated_outcome_sha256'], 'note': 'Diagnostic categories overlap. Unknown is not proved unsafe; source byte hashes and canonical assessment hashes use different hash domains.'})
    parent_rows = []
    for (version, population, check_id, required), counts in sorted(parent_counts.items()):
        denominator = 200 if population == 'all_planner' else EXPECTED_CATEGORIES[population]
        applicable = counts['met'] + counts['violated'] + counts['unknown']
        parent_rows.append({'planner': version, 'population': population, 'check_id': check_id, 'required': required, 'case_denominator': denominator,
            'cases_with_parent': sum(counts.values()), 'met': counts['met'], 'violated': counts['violated'], 'unknown': counts['unknown'], 'not_applicable': counts['not_applicable'],
            'coverage': (counts['met'] + counts['violated']) / applicable if applicable else None,
            'coverage_definition': '(met + violated)/(met + violated + unknown); coverage is not a pass rate'})
    for kind, values in (('age', range(13, 18)), ('scenario', EXPECTED_CATEGORIES)):
        for value in values:
            bases = [row for row in planner['bases'] if (row['public_input']['age'] if kind == 'age' else row['case_category']) == value]
            for version in range(1, 5):
                chosen = [planner['matched'][row['profile_id'], version] for row in bases]
                feasible = [row for row in chosen if row['case_category'] == 'feasible']
                subgroup_rows.append({'grouping': kind, 'value': value, 'planner': version, 'profiles': len(chosen), 'families': len({row['family_id'] for row in chosen}),
                    'format_valid': sum(row['format_valid'] for row in chosen), 'workflow_completed': sum(row['completion_valid'] for row in chosen),
                    'feasible_profiles': len(feasible), 'primary_success': sum(row['final_metrics']['automated_feasible_plan_success'] for row in feasible),
                    'interpretation': 'Prespecified age/scenario descriptive summary; not independent-athlete sampling or a new passing threshold.'})
    return failure_rows, parent_rows, subgroup_rows


def build_figures(planner, classifier):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 11, 'svg.hashsalt': 'step35-saved-analysis', 'axes.spines.top': False, 'axes.spines.right': False})
    outputs = {}
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    labels = ['Planner 1', 'Planner 2', 'Planner 3', 'Planner 4'];colors = ['#326d9c', '#427c84', '#6d6b99', '#a36a45']
    for ax, key, title in ((axes[0], 'strict_format_valid', 'Response format'), (axes[1], 'designated_workflow_completed', 'Workflow completion')):
        counts = [sum(row['final_metrics'][key] for row in planner['rows'] if row['planner_version'] == v) for v in range(1, 5)]
        ax.bar(labels, counts, color=colors);ax.set_ylim(0, 215);ax.set_ylabel('Outcomes out of 200');ax.set_title(title)
        for x, value in enumerate(counts):ax.text(x, value+3, str(value), ha='center')
        ax.tick_params(axis='x', rotation=20)
    fig.suptitle('Saved comparison: 200 matched profiles, four planners');fig.tight_layout()
    stream=io.BytesIO();fig.savefig(stream,format='svg',metadata={'Date':None});plt.close(fig);outputs['figures/planner_execution.svg']=stream.getvalue()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    medians=[]
    for version in range(1, 5):
        values=[row['elapsed_seconds'] for row in planner['rows'] if row['planner_version']==version and isinstance(row.get('elapsed_seconds'),(int,float)) and math.isfinite(row['elapsed_seconds'])]
        medians.append(float(np.median(values)))
    ax.bar(labels,medians,color=colors);ax.set_ylabel('Median end-to-end time (seconds)');ax.set_title('All terminal workflows, including failures (200 per planner)')
    for x,value in enumerate(medians):ax.text(x,value+0.8,f'{value:.2f} s',ha='center')
    ax.set_ylim(0,max(medians)*1.2);fig.tight_layout();stream=io.BytesIO();fig.savefig(stream,format='svg',metadata={'Date':None});plt.close(fig);outputs['figures/planner_runtime.svg']=stream.getvalue()
    if classifier is not None:
        fig,ax=plt.subplots(figsize=(8,4.5)); selected=[row for row in classifier['intervals'] if row['metric']=='macro_f1' and '_minus_' in row['model_or_contrast']]
        names={'logistic_regression_minus_majority':'Logistic − majority','neural_minus_majority':'Neural − majority','neural_minus_logistic_regression':'Neural − logistic'}
        for position,row in enumerate(selected):
            ax.plot([row['lower_95'],row['upper_95']],[position,position],color='#326d9c');ax.plot(row['estimate'],position,'o',color='#326d9c')
        ax.axvline(0,color='#6c737b',linewidth=1);ax.set_yticks(range(len(selected)),[names[row['model_or_contrast']] for row in selected]);ax.set_xlabel('Macro-F1 difference (0–1 scale)');ax.set_title('Paired exercise-group bootstrap: individual 95% intervals');fig.tight_layout()
        stream=io.BytesIO();fig.savefig(stream,format='svg',metadata={'Date':None});plt.close(fig);outputs['figures/classifier_macro_f1_differences.svg']=stream.getvalue()
    return outputs


def findings_text(planner, headline, paired, times, review_paired, classifier, classifier_status, retrieval, native_runtime, method_note):
    lookup = {(row['population'], row['metric'], row['planner']): row for row in headline}
    lines = ['# Step 35 — Results analysis and comparison', '',
        'We analyzed the saved results without retraining models, searching the reference index again, revising replies or changing the original scores. The planner study contains 200 fictional profiles and 800 designated outcomes. All four planners use the same local language model; the comparison concerns the complete workflows.', '',
        '## Planner results', '',
        '| Planner | Valid format | Workflow completed | Valid completed plans | Coded checks passed | Full verification | Median time |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for version in range(1,5):
        h=lambda population,metric: lookup[population,metric,version]
        runtime=next(row for row in times if row['planner']==version and row['population']=='all_terminal')
        lines.append(f"| {version} | {h('all_planner','strict_format_valid')['numerator']}/200 | {h('all_planner','designated_workflow_completed')['numerator']}/200 | {h('feasible','completed_valid_plan')['numerator']}/150 | {h('feasible','automated_declared_checks_pass')['numerator']}/150 | {h('feasible','automated_feasible_plan_success')['numerator']}/150 | {runtime['median_seconds']:.2f} s |")
    lines += ['', 'The baseline has the largest number of valid formats across all 200 profiles and the lowest observed time. Planner 4 has the largest number of completed, valid plan responses among the 150 feasible requests (47), compared with 45, 40 and 39. A valid format is not evidence that a plan meets every request.', '',
        'The primary full-verification result is 0/150 for every planner. The automatic goal check was not implemented, and resource checks cover only a limited set of activity descriptions. These gaps prevented full verification. Saved assessments also contain genuine schedule, session-count and existing-commitment violations. We retain both facts: unknown checks are not passes, and lack of verification is not proof that every plan is unsafe or useless.', '',
        '## Matched comparisons and uncertainty', '',
        'We compare Version 2 minus 1, Version 3 minus 2, Version 4 minus 3, and Version 4 minus 1 on the same profiles. Each binary comparison retains both-success, later-only, earlier-only and neither-success counts. Differences in rates use percentage points.', '',
        'The format-rate differences are −6.5, +2.5, +1.0 and −3.0 percentage points in that order. These are descriptive differences in response format, not proof of better overall planning. Challenge cases remain separate: missing-information handling is 0/20 and conflict handling 0/15 for every planner; outside-scope handling is 3, 5, 8 and 3 out of 15. Planner 4 loses five of Planner 3’s outside-scope successes and adds none.', '',
        'The primary intervals use 2,000 paired family-group resamples, seed 42, with individual 95% percentile endpoints. Every eligible member contributes whenever its group is drawn, including repeated draws. All 150 feasible profiles have different adopted family IDs, so the saved family structure is singleton. We also retain the prespecified wording-pattern sensitivity: the 14-pattern mapping across all 200 profiles has three groups in the feasible subset, containing 52, 50 and 48 profiles. We resample only those eligible groups.', '',
        'All primary success flags are zero, so their saved-output bootstrap intervals and rate differences are [0, 0]. This is a constant distribution produced by these fixed flags and verification limits. It does not establish equivalence, zero real-world uncertainty or an absence of useful differences. No significance test, combined quality score, new pass threshold or winning planner is introduced.', '',
        'The planner protocol specified family pairing, 2,000 resamples, seed 42 and percentile intervals. It did not fix the random-generator family, lexical group order or interpolation convention. We explicitly record PCG64, sorted exact IDs and linear percentiles as a numerical implementation clarification made at analysis time. These choices were already frozen for the classifier. Draws and estimates are saved so the calculations can be reproduced.', '',
        '## Exercise classifier', '']
    if classifier is not None:
        labels={'majority':'Majority baseline','logistic_regression':'L5 logistic regression','neural':'N3 neural classifier'}
        lines += ['The classifier comparison uses the saved predictions for 438 test records in 385 exercise groups and all 16 frozen classes. Macro-F1 remains primary; accuracy, class-level metrics and confusion counts provide context.', '', '| Classifier | Macro-F1 | Accuracy |', '|---|---:|---:|']
        for model,values in classifier['observed'].items():lines.append(f"| {labels[model]} | {values['macro_f1']:.4f} | {100*values['accuracy']:.2f}% |")
        lines += ['', 'We compute all three fixed classifier contrasts using the same 2,000 exercise-group draws. Every resample retains the full class list with zero-division scores of zero, including absent classes in a resample. This measures sensitivity to the existing test groups, not retraining or seed variability. The validation-selected L5 application model remains unchanged.', '', '| Macro-F1 contrast | Observed difference | Individual 95% interval |', '|---|---:|---|']
        for row in classifier['intervals']:
            if row['metric']=='macro_f1' and '_minus_' in row['model_or_contrast']:
                lines.append(f"| {row['model_or_contrast'].replace('_',' ')} | {row['estimate']:+.4f} | [{row['lower_95']:+.4f}, {row['upper_95']:+.4f}] |")
    else:
        lines += ['Classifier uncertainty is unavailable in this execution because the original saved test inputs or predictions could not be read. No development predictions, synthetic scores or new inference are substituted. Reason: ' + classifier_status['reason']]
    lines += ['', '## Retrieval', '']
    if retrieval.get('status','').startswith('verified'):
        r=retrieval['summary'];lines += [f"We retain the original {r['heldout_questions']}-question, {r['question_families']}-family held-out retrieval results. The source labels are 20 supported, two partially supported and eight unsupported. The original ranking denominator is 24 nonempty relevance sets; six empty relevance sets do not receive invented recall. Supported-only ranking uses 20 questions. The broader unsupported-service category contains the two partially supported and eight unsupported questions.", '',
            'The early Step 35 text described a planned 20-answerable/10-unsupported split. We preserve the saved source populations rather than change their labels or denominators. Ranked evidence-set coverage, verified retrieval companion text and actual generation-prompt delivery remain different quantities. Companion preservation does not prove that every required fact reached the planner. No new retrieval intervals or held-out searches are introduced.']
        recorded=r['reported_route_metrics'][0]
        lines += ['', '| Saved retrieval measure | Value | Scored questions |', '|---|---:|---:|',
            f"| Mean Recall@5 | {recorded['mean_recall_at_5']:.4f} | {recorded['ranking_scored_denominator']} |",
            f"| MRR@5 | {recorded['mrr_at_5']:.4f} | {recorded['ranking_scored_denominator']} |",
            f"| Ranked complete-evidence-set coverage@5 | {recorded['complete_evidence_set_coverage_rate_at_5']:.4f} | {recorded['complete_evidence_scored_denominator']} |", '',
            'All 30 saved queries returned candidates, including the ten questions in the broader unsupported-service category. The saved no-match and error counts are zero. Returned references and high ranking scores do not establish that a question is answerable or that abstention works.']
    else:lines += ['Retrieval inputs are unavailable in this execution; no development results replace them. ' + '; '.join(retrieval.get('limitations',[]))]
    lines += ['', '## Supplementary team review', '',
        'The Step 34 review contains 160 replies from 40 selected profiles, with 800 separate dimension entries. It is one ChatGPT-assisted review under Sam’s direction, not two independent teammate rating sets. We retain 799 numeric entries and one justified evidence N/A; agreement and weighted kappa remain unavailable. The assisted findings are descriptive supplementary evidence, not a replacement for the original independent-review design.', '',
        'For each dimension, matched version comparisons report higher, equal and lower ratings. No scores are averaged across dimensions or reviewers. Most paired judgments are ties. For clarity, Planner 4 versus Planner 1 has two higher, 15 equal and 23 lower ratings among 40 profiles. The review sample contains 25 feasible and 15 challenge profiles, overrepresenting challenge cases compared with the full benchmark. Its pooled scores do not estimate all 800 replies.', '',
        '## Runtime, failed work and resource limits', '',
        'All-terminal timing includes failed attempts. Completed-workflow, valid-format and unsuccessful-work timings are also saved separately; paired time differences identify which profiles were included. The observed all-terminal means are approximately 10.44, 18.90, 26.61 and 66.22 seconds. Longer workflows did not deliver a verified primary success in this benchmark. That observation does not establish an isolated causal effect of references, specialist roles or checks.', '',
        f"The frozen comparison summary records {planner['summary']['cumulative_model_submissions']} local model submissions across the full run. This is the cumulative total, not the 67 submissions shown for the final five-case batch. Planner 4’s saved terminal states are 198 revision-limit outcomes and two execution errors; none was internally accepted. Independent scoring remains separate from those internal decisions.", '']
    if native_runtime['status']=='complete':
        lines += ['The original hash-bound runtime journals were also read. We report generation submissions, metadata/render attempts, distinct logical calls, cached role reads and available stage usage separately. Token usage is charged once per saved call ID; repeated reads do not multiply tokens. Missing hardware measurements or dollar-cost calculations remain unavailable.']
    else:
        lines += ['Full native runtime journals are unavailable or incomplete in this execution. Their missing measurements are not treated as zero. The export contains 797 designated-role usage objects; those token counts omit earlier specialist/evaluator/revision work and are not labeled full-workflow costs.']
    lines += ['', '## Interpretation and next step', '',
        'We can compare recorded reliability, format, timing, class predictions and review patterns, but cannot declare a fully verified planner or a general winner. Failures and unknown coverage remain visible, with case identifiers and source hashes. The results concern a constructed benchmark and fixed saved outputs; they do not establish improved athletic performance, clinical suitability or results on real athletes. Future changes based on these findings belong to a new experiment version.', '',
        'Step 36 will check reproduction of the saved analysis and its documented starting route. The original two-independent-teammate review component remains unperformed. All versioned tables, uncertainty draws, figures and limitations are retained with the analysis inputs.', '']
    return '\n'.join(lines)


def simple_report_html(text, files):
    escaped=html.escape(text)
    # We keep the report self-contained except for the generated local figures.
    parts=[]
    for block in escaped.split('\n\n'):
        if block.startswith('# '):parts.append('<h1>'+block[2:]+'</h1>')
        elif block.startswith('## '):parts.append('<h2>'+block[3:]+'</h2>')
        elif block.startswith('|'):
            lines=block.splitlines();cells=[line.strip('|').split('|') for line in lines]
            header='<tr>'+''.join('<th>'+cell.strip()+'</th>' for cell in cells[0])+'</tr>'
            body=''.join('<tr>'+''.join('<td>'+cell.strip()+'</td>' for cell in row)+'</tr>' for row in cells[2:])
            parts.append('<table>'+header+body+'</table>')
        else:parts.append('<p>'+block.replace('\n',' ')+'</p>')
    plots=''.join('<figure><img src="'+name+'" alt="'+html.escape(name)+'"></figure>' for name in files if name.endswith('.svg'))
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Step 35 — Results analysis</title><style>body{font:16px/1.6 system-ui,sans-serif;max-width:1100px;margin:35px auto;padding:0 25px;color:#182837}h1,h2{color:#174569}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:8px;border-bottom:1px solid #cad4df}figure{margin:30px 0}img{max-width:100%;height:auto}p{max-width:1000px}</style>'+''.join(parts)+plots+'</html>').encode('utf-8')


def analyze(root, package):
    root=Path(root).resolve();planner=read_planners(root,package['source_member_sha256'])
    review=read_review(root,planner,package['review_id'])
    comparisons,headline,population_rows=paired_tables(planner)
    review_distributions,review_comparisons=review_tables(review,planner)
    time_rows,paired_time_rows,usage_rows=runtime_tables(planner)
    failures,parents,subgroups=diagnostic_tables(planner)
    patterns=package['wording_pattern_groups'];mapping={profile:group['design_tag'] for group in patterns for profile in group['profile_ids']}
    require(len(mapping)==200 and set(mapping)==set(planner['profiles']), 'The original wording-pattern mapping does not cover the frozen roster.')
    proposed=package['original_family_by_profile'];require(all(planner['matched'][profile,1]['family_id']==family for profile,family in proposed.items()), 'Saved pattern/family evidence differs from adopted families.')
    feasible=[row['profile_id'] for row in planner['bases'] if row['case_category']=='feasible']
    values=[[metric(planner['matched'][profile,version],'automated_feasible_plan_success') for version in range(1,5)] for profile in feasible]
    primary=bootstrap_planner(values,[planner['matched'][profile,1]['family_id'] for profile in feasible],'feasible_adopted_families')
    sensitivity=bootstrap_planner(values,[mapping[profile] for profile in feasible],'feasible_original_wording_patterns_sensitivity')
    input_hashes={**planner['input_hashes'],**review['input_hashes']}
    pattern_path=safe_path(root,package['pattern_source_path'])
    pattern_source_status='exact_historical_mapping_embedded_with_source_hash'
    if pattern_path.is_file():
        raw=pattern_path.read_bytes();require(sha(raw)==package['pattern_source_sha256'],'The original wording-pattern evidence differs.')
        source=json.loads(raw);require(source['shared_design_pattern_groups']==patterns,'The embedded historical pattern mapping differs from its original file.')
        input_hashes[package['pattern_source_path']]=sha(raw);pattern_source_status='native_source_reopened_and_verified'
    classifier=None;classifier_input=None
    try:
        classifier_input=load_classifier(root)
        configuration=classifier_input['analysis_config']
        require(configuration['uncertainty']['resamples']==2000 and configuration['uncertainty']['seed']==42,'The frozen classifier resampling settings differ.')
        require(configuration['contrasts']==['logistic_regression_minus_majority','neural_minus_majority','neural_minus_logistic_regression'],'The frozen classifier contrasts differ.')
        classifier=analyze_classifier_records(classifier_input)
        for model,computed in classifier['observed'].items():
            for name,value in computed.items():require(math.isclose(value,classifier_input['summary']['models'][model][name],rel_tol=0,abs_tol=1e-12),'Recomputed saved classifier metric differs: '+model+'/'+name)
        classifier_status={'status':'complete','records':len(classifier_input['records']),'groups':len(classifier['groups']),'class_count':len(classifier_input['class_order']),'observed':classifier['observed'],'reason':None}
        input_hashes.update(classifier_input['input_sha256'])
        population_rows.extend({'population':'classifier_test','record_id':row['record_id'],'group_id':row['group_id'],'target_label':row['target_label']} for row in classifier_input['records'])
    except MissingClassifierInput as exc:
        classifier_status={'status':'unavailable_saved_inputs','records':None,'groups':None,'reason':str(exc),'new_inference_performed':False}
    retrieval=analyze_retrieval(root);input_hashes.update(retrieval.get('input_sha256',{}))
    native_runtime=analyze_runtime_details(root,planner['rows'],planner['source_hashes'],expected_generation_submissions=planner['summary']['cumulative_model_submissions'])
    require(not native_runtime.get('errors'),'Native runtime evidence failed validation: '+'; '.join(native_runtime.get('errors',[])[:3]))
    input_hashes.update(native_runtime.get('input_sha256',{}))
    method_note={**package['method_note'],'planner_original_protocol_check':planner['original_protocol_check'],'pattern_source_check':pattern_source_status,
        'original_two_independent_reviewer_component_completed':False,'retrieval_population_discrepancy_preserved':retrieval.get('summary',{}).get('protocol_population_discrepancy')}
    intervals=primary['intervals']+sensitivity['intervals']+(classifier['intervals'] if classifier is not None else [])
    estimates=primary['estimates']+sensitivity['estimates']+(classifier['estimates'] if classifier is not None else [])
    population_rows.extend({'population':'supplementary_review','record_id':profile,'group_id':planner['matched'][profile,1]['family_id'],
        'age':planner['matched'][profile,1]['public_input']['age'],'case_category':planner['matched'][profile,1]['case_category']} for profile in review['profiles'])
    population_rows.extend({'population':'wording_pattern_sensitivity','record_id':profile,'group_id':mapping[profile],'case_category':'feasible'} for profile in feasible)
    if retrieval.get('question_rows'):
        population_rows.extend({'population':'retrieval_heldout','record_id':row['query_id'],'group_id':row['question_family_id'],'support_status':row['support_status'],'ranking_eligible':bool(row['relevant_unit_count'])} for row in retrieval['question_rows'])
    settings={'resamples':2000,'seed':42,'generator':'numpy.random.Generator(numpy.random.PCG64(42))','group_order':'sorted exact string IDs',
        'draw_method':'Generator.integers(0, number_of_groups, size=(2000, number_of_groups), dtype=int64)','percentile_endpoints':[2.5,97.5],'percentile_method':'linear',
        'resampled_member_policy':'Every eligible record contributes once per draw of its group; actual resampled record denominator; common draws for matched models.',
        'intervals':'individual 95% intervals; no multiplicity-adjusted simultaneous inference','groups':{'feasible_adopted_families':primary['groups'],'feasible_original_wording_patterns_sensitivity':sensitivity['groups']},
        'numerical_convention_timing':method_note['planner_numerical_clarification'], 'numpy_version':np.__version__}
    if classifier is not None:settings['groups']['classifier_test']=classifier['groups']
    identity={'source_member_sha256':package['source_member_sha256'],'input_sha256':input_hashes,'review_id':package['review_id'],'software_sha256':package['software_sha256'],
        'bootstrap_settings':settings,'method_note':method_note,'classifier_status':classifier_status,'retrieval_status':retrieval['status'],'native_runtime_status':native_runtime['status']}
    analysis_id=sha(packed(identity));relative_folder='results/statistical_analysis/analysis_'+analysis_id[:20];folder=root/relative_folder
    checks=[{'check':'all_designated_planner_jobs_assessed','status':'passed','observed':800,'expected':800},
        {'check':'four_version_pairing','status':'passed','observed':200,'expected':200},
        {'check':'supplementary_review_entries','status':'passed','observed':800,'expected':800},
        {'check':'classifier_saved_input_analysis','status':classifier_status['status'],'observed':classifier_status.get('records'),'expected':438},
        {'check':'retrieval_saved_evidence','status':retrieval['status'],'observed':retrieval.get('summary',{}).get('heldout_questions'),'expected':30},
        {'check':'native_runtime_details','status':native_runtime['status'],'observed':native_runtime.get('observed_jobs'),'expected':800},
        {'check':'primary_bootstrap_draws','status':'passed','observed':len(primary['draws']),'expected':2000},
        {'check':'independent_reviewer_agreement','status':'unavailable_not_collected','observed':0,'expected':2}]
    summary={'schema_version':'step35-statistical-analysis-1','analysis_id':analysis_id,
        'status':'saved_evidence_analysis_complete_with_recorded_limits' if classifier is not None and retrieval['status'].startswith('verified') else 'available_components_analyzed_missing_saved_inputs',
        'planner_profiles':200,'planner_outcomes':800,'feasible_profiles_per_planner':150,'adopted_feasible_families':len(primary['groups']),
        'wording_patterns_full_population':len(patterns),'wording_patterns_in_feasible_subset':len(sensitivity['groups']),
        'review_profiles':40,'review_responses':160,'review_dimension_entries':800,'review_method':'single_assisted_supplementary_review',
        'independent_reviewer_agreement':{'computed':False,'reason':'No two actual independent teammate rating sets were collected.'},
        'paired_planner_contrasts':['V%d-V%d'%pair for pair in CONTRASTS],'resamples':2000,'bootstrap_seed':42,'bootstrap_intervals':len(intervals),
        'classifier':classifier_status,'retrieval':retrieval.get('summary',{'status':retrieval['status']}),'native_runtime_status':native_runtime['status'],
        'cumulative_planner_model_submissions':planner['summary']['cumulative_model_submissions'],'new_model_calls':0,'new_predictions':0,'new_reference_queries':0,
        'original_outcomes_changed':False,'automatic_scores_changed':False,'best_planner_selected':False,'formal_significance_claimed':False,
        'analysis_folder':relative_folder,'report_path':relative_folder+'/analysis_report.html','findings_path':relative_folder+'/statistical_analysis_findings.md',
        'primary_metric_limitation':'Goal check unimplemented; resource coverage limited. Constant zero verification intervals do not prove no useful plans or equal true quality.',
        'pending_original_design_components':['two_independent_teammate_ratings_and_agreement'],
        'headline_planner_rows':headline,'timing_all_terminal':[row for row in time_rows if row['population']=='all_terminal'],
        'input_manifest_sha256':sha(packed(identity))}
    review_subgroups=[]
    for kind,values in (('age',range(13,18)),('scenario',EXPECTED_CATEGORIES)):
        for value in values:
            subset=[profile for profile in review['profiles'] if (planner['matched'][profile,1]['public_input']['age'] if kind=='age' else planner['matched'][profile,1]['case_category'])==value]
            for version in range(1,5):
                for dimension in DIMENSIONS:
                    items=[review['matched'][profile,version,dimension] for profile in subset]
                    counts=Counter(item['score'] for item in items if item['status']=='rated')
                    review_subgroups.append({'grouping':kind,'value':value,'planner':version,'dimension':dimension,'profiles':len(subset),'families':len({planner['matched'][profile,1]['family_id'] for profile in subset}),
                        'score_0':counts[0],'score_1':counts[1],'score_2':counts[2],'not_applicable':sum(item['status']=='not_applicable' for item in items),'missing':0,'review_stream':'single_assisted_supplementary_review'})
    files={'analysis_input_manifest.json':packed(identity),'analysis_method_note.json':packed(method_note),'analysis_populations.csv':csv_content(population_rows),
        'analysis_checks.csv':csv_content(checks),'planner_summary.csv':csv_content(headline),'paired_comparisons.csv':csv_content(comparisons),
        'bootstrap_settings.json':packed(settings),'bootstrap_estimates.csv':csv_content(estimates),'bootstrap_intervals.csv':csv_content(intervals),
        'retrieval_summary.csv':csv_content(retrieval.get('summary_rows',[])),'retrieval_question_analysis.csv':csv_content(retrieval.get('question_rows',[])),
        'retrieval_analysis_status.json':packed({key:value for key,value in retrieval.items() if key not in ('question_rows','summary_rows')}),
        'team_rating_distributions.csv':csv_content(review_distributions),'team_rating_comparisons.csv':csv_content(review_comparisons),
        'subgroup_summary.csv':csv_content(subgroups),'team_review_subgroups.csv':csv_content(review_subgroups),'runtime_resource_summary.csv':csv_content(time_rows),'matched_runtime_comparisons.csv':csv_content(paired_time_rows),
        'designated_role_usage.csv':csv_content(usage_rows),'native_runtime_summary.json':packed(native_runtime),
        'native_runtime_by_planner.csv':csv_content(native_runtime.get('per_planner_rows',[])), 'native_runtime_by_stage.csv':csv_content(native_runtime.get('stage_rows',[])),
        'failure_analysis.csv':csv_content(failures),'parent_check_summary.csv':csv_content(parents),'classifier_analysis_status.json':packed(classifier_status),
        'analysis_summary.json':packed(summary)}
    arrays={'feasible_family_draws':primary['draws'],'feasible_family_denominators':primary['denominators'],
        'wording_pattern_draws':sensitivity['draws'],'wording_pattern_denominators':sensitivity['denominators']}
    if classifier is not None:
        arrays.update(classifier_group_draws=classifier['draws'],classifier_resampled_record_counts=classifier['denominators'])
        files['classifier_per_class_metrics.csv']=csv_content(classifier['class_rows']);files['classifier_confusion_matrices.csv']=csv_content(classifier['confusion_rows'])
        files['classifier_summary.json']=packed(classifier['observed'])
        files['classifier_prediction_analysis.csv']=csv_content([{'record_id':row['record_id'],'group_id':row['group_id'],'model':name,'target_label':row['target_label'],'predicted_label':predicted,'correct':row['target_label']==predicted} for row in classifier_input['records'] for name,predicted in row['predictions'].items()])
    stream=io.BytesIO();np.savez_compressed(stream,**arrays);files['bootstrap_draws.npz']=stream.getvalue()
    files.update(build_figures(planner,classifier))
    text=findings_text(planner,headline,comparisons,time_rows,review_comparisons,classifier,classifier_status,retrieval,native_runtime,method_note)
    files['statistical_analysis_findings.md']=text.encode('utf-8');files['analysis_report.html']=simple_report_html(text,files)
    files['output_manifest.json']=packed({'schema_version':'step35-analysis-output-manifest-1','analysis_id':analysis_id,'files':{name:sha(raw) for name,raw in sorted(files.items())}})
    for name,raw in files.items():
        target=folder/name
        require(not target.exists() or target.read_bytes()==raw,'A previous analysis artifact differs and was preserved: '+name)
    pointer=root/'results/step35_statistical_analysis_summary.json'
    doc=root/'docs/statistical_analysis_findings.md'
    if pointer.exists():
        old=json.loads(pointer.read_bytes());require(old.get('schema_version')==summary['schema_version'],'An unrelated Step 35 summary exists and was preserved.')
        old_folder=safe_path(root,old['analysis_folder'])
        require((old_folder/'analysis_summary.json').read_bytes()==pointer.read_bytes(),'An edited Step 35 index was preserved.')
        if doc.exists():
            require(doc.read_bytes() in ((old_folder/'statistical_analysis_findings.md').read_bytes(),text.encode('utf-8')),'Edited analysis documentation was preserved.')
    if doc.exists() and not pointer.exists():require(doc.read_bytes()==text.encode('utf-8'),'Existing analysis documentation was preserved.')
    # We recheck the evidence bytes before saving derived results.
    for name,expected in input_hashes.items():require(sha(safe_path(root,name).read_bytes())==expected,'An analysis input changed while calculations were running: '+name)
    for name,raw in files.items():
        target=folder/name;target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            with target.open('xb') as handle:handle.write(raw)
    pointer.parent.mkdir(parents=True,exist_ok=True);doc.parent.mkdir(parents=True,exist_ok=True)
    pointer.write_bytes(packed(summary));doc.write_bytes(text.encode('utf-8'))
    return summary
