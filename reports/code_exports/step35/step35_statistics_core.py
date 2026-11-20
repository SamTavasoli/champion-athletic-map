"""Paired group resampling for the saved benchmark outputs."""
from __future__ import annotations
import numpy as np

CONTRASTS = ((2, 1), (3, 2), (4, 3), (4, 1))
CLASSIFIER_CONTRASTS = (('logistic_regression', 'majority'), ('neural', 'majority'), ('neural', 'logistic_regression'))


def prepare_group_draws(group_ids, resamples=2000, seed=42):
    groups = sorted(set(group_ids))
    if not groups or any(not isinstance(group, str) or not group for group in groups):
        raise ValueError('Resampling requires nonempty exact string group IDs.')
    index = {group: number for number, group in enumerate(groups)}
    member_groups = np.asarray([index[group] for group in group_ids], dtype=np.int64)
    generator = np.random.Generator(np.random.PCG64(seed))
    draws = generator.integers(0, len(groups), size=(resamples, len(groups)), dtype=np.int64)
    return groups, member_groups, draws


def group_member_weights(member_groups, drawn_groups, group_count):
    return np.bincount(drawn_groups, minlength=group_count)[member_groups]


def percentile_interval(estimates):
    values = np.asarray(estimates, dtype=float)
    if values.ndim != 1 or not len(values) or not np.all(np.isfinite(values)):
        raise ValueError('Bootstrap estimates must all be finite; no discarded resamples.')
    low, high = np.percentile(values, [2.5, 97.5], method='linear')
    return float(low), float(high)


def paired_binary_counts(later, earlier):
    a, b = np.asarray(later), np.asarray(earlier)
    if a.shape != b.shape or a.ndim != 1 or not len(a):
        raise ValueError('Matched binary outcomes must have the same nonempty roster.')
    if any(type(value) not in (bool, np.bool_) for value in list(a) + list(b)):
        raise ValueError('Binary outcomes must be observed booleans, not missing work.')
    return {'both_succeed': int(np.sum(a & b)), 'later_only': int(np.sum(a & ~b)),
            'earlier_only': int(np.sum(~a & b)), 'neither_succeeds': int(np.sum(~a & ~b)),
            'profiles': len(a), 'difference_percentage_points': float(100 * (np.sum(a) - np.sum(b)) / len(a))}


def bootstrap_planner(values, group_ids, population):
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2 or matrix.shape != (len(group_ids), 4) or not np.all(np.isin(matrix, [0, 1])):
        raise ValueError('Planner bootstrap requires four complete binary outcomes per profile.')
    groups, member_groups, draws = prepare_group_draws(group_ids)
    estimates = np.zeros((len(draws), 8), dtype=float)
    denominators = np.zeros(len(draws), dtype=np.int64)
    for replicate, drawn_groups in enumerate(draws):
        weights = group_member_weights(member_groups, drawn_groups, len(groups))
        denominators[replicate] = int(np.sum(weights))
        if denominators[replicate] <= 0:
            raise ValueError('An empty planner resample cannot be silently omitted.')
        estimates[replicate, :4] = 100 * (weights @ matrix) / denominators[replicate]
        for column, (later, earlier) in enumerate(CONTRASTS, start=4):
            estimates[replicate, column] = estimates[replicate, later - 1] - estimates[replicate, earlier - 1]
    observed = np.concatenate((100 * np.mean(matrix, axis=0),
        np.asarray([100 * np.mean(matrix[:, a-1] - matrix[:, b-1]) for a, b in CONTRASTS])))
    names = ['V' + str(version) for version in range(1, 5)] + ['V%d-V%d' % pair for pair in CONTRASTS]
    interval_rows, estimate_rows = [], []
    for column, name in enumerate(names):
        low, high = percentile_interval(estimates[:, column])
        constant = bool(np.all(estimates[:, column] == estimates[0, column]))
        unit = 'percent' if column < 4 else 'percentage_points'
        interval_rows.append({'population': population, 'metric': 'automated_feasible_plan_success',
            'model_or_contrast': name, 'estimate': float(observed[column]), 'lower_95': low, 'upper_95': high,
            'unit': unit, 'profiles': len(matrix), 'groups': len(groups), 'resamples': len(draws),
            'status': 'constant_on_saved_outputs' if constant else 'computed',
            'interpretation': ('Benchmark resampling only. All saved success flags are zero; this does not establish equivalence or zero real-world uncertainty.' if constant and np.all(matrix == 0) else 'Benchmark resampling of fixed saved outcomes only; a constant distribution does not establish zero real-world uncertainty.')})
        estimate_rows.extend({'population': population, 'metric': 'automated_feasible_plan_success', 'model_or_contrast': name,
            'replicate': i + 1, 'estimate': float(value), 'unit': unit, 'resampled_records': int(denominators[i])}
            for i, value in enumerate(estimates[:, column]))
    return {'groups': groups, 'member_groups': member_groups, 'draws': draws, 'denominators': denominators,
            'estimates': estimate_rows, 'intervals': interval_rows}


def classifier_measures(actual, predicted, class_count, weights=None):
    y, p = np.asarray(actual, dtype=np.int64), np.asarray(predicted, dtype=np.int64)
    if y.shape != p.shape or y.ndim != 1 or not len(y):
        raise ValueError('Classifier targets and saved predictions must align exactly.')
    if np.any(y < 0) or np.any(y >= class_count) or np.any(p < 0) or np.any(p >= class_count):
        raise ValueError('A saved class index is outside the frozen class list.')
    w = np.ones(len(y), dtype=float) if weights is None else np.asarray(weights, dtype=float)
    if w.shape != y.shape or np.any(w < 0) or not np.all(np.isfinite(w)) or np.sum(w) <= 0:
        raise ValueError('Classifier resampling weights must have a positive finite denominator.')
    confusion = np.bincount(y * class_count + p, weights=w, minlength=class_count * class_count).reshape(class_count, class_count)
    tp = np.diag(confusion); support = confusion.sum(axis=1); called = confusion.sum(axis=0)
    precision = np.divide(tp, called, out=np.zeros_like(tp), where=called != 0)
    recall = np.divide(tp, support, out=np.zeros_like(tp), where=support != 0)
    f1 = np.divide(2 * tp, support + called, out=np.zeros_like(tp), where=(support + called) != 0)
    return {'macro_f1': float(np.mean(f1)), 'accuracy': float(np.sum(tp) / np.sum(w)),
            'confusion': confusion, 'precision': precision, 'recall': recall, 'f1': f1, 'support': support}


def analyze_classifier_records(data):
    records, labels = data['records'], data['class_order']
    positions = {label: index for index, label in enumerate(labels)}
    actual = np.asarray([positions[row['target_label']] for row in records], dtype=np.int64)
    if set(actual) != set(range(len(labels))):
        raise ValueError('An original test class is unexpectedly absent.')
    predictions = {model: np.asarray([positions[row['predictions'][model]] for row in records], dtype=np.int64)
                   for model in ('majority', 'logistic_regression', 'neural')}
    groups, member_groups, draws = prepare_group_draws([row['group_id'] for row in records])
    observed = {model: classifier_measures(actual, prediction, len(labels)) for model, prediction in predictions.items()}
    columns = [(model, metric) for model in predictions for metric in ('macro_f1', 'accuracy')]
    columns += [(later + '_minus_' + earlier, metric) for later, earlier in CLASSIFIER_CONTRASTS for metric in ('macro_f1', 'accuracy')]
    estimates = np.zeros((len(draws), len(columns)))
    denominators = np.zeros(len(draws), dtype=np.int64)
    for replicate, drawn_groups in enumerate(draws):
        weights = group_member_weights(member_groups, drawn_groups, len(groups))
        denominators[replicate] = int(np.sum(weights))
        computed = {model: classifier_measures(actual, prediction, len(labels), weights) for model, prediction in predictions.items()}
        for column, (name, metric) in enumerate(columns):
            if '_minus_' in name:
                later, earlier = name.split('_minus_', 1)
                value = computed[later][metric] - computed[earlier][metric]
            else:
                value = computed[name][metric]
            estimates[replicate, column] = value
    intervals, estimate_rows, class_rows, confusion_rows = [], [], [], []
    for column, (name, metric) in enumerate(columns):
        if '_minus_' in name:
            later, earlier = name.split('_minus_', 1); point = observed[later][metric] - observed[earlier][metric]
        else:
            point = observed[name][metric]
        low, high = percentile_interval(estimates[:, column])
        intervals.append({'population': 'classifier_test', 'metric': metric, 'model_or_contrast': name,
            'estimate': float(point), 'lower_95': low, 'upper_95': high, 'unit': 'raw_0_to_1_score_difference' if '_minus_' in name else 'proportion',
            'profiles': len(records), 'groups': len(groups), 'resamples': len(draws), 'status': 'computed',
            'interpretation': 'Saved test-record sensitivity with exercise-group resampling; does not measure retraining or seed variability.'})
        estimate_rows.extend({'population': 'classifier_test', 'metric': metric, 'model_or_contrast': name, 'replicate': i + 1,
            'estimate': float(value), 'unit': 'raw_0_to_1_score_difference' if '_minus_' in name else 'proportion', 'resampled_records': int(denominators[i])}
            for i, value in enumerate(estimates[:, column]))
    for model, metrics in observed.items():
        for class_index, label in enumerate(labels):
            class_rows.append({'model': model, 'class_label': label, 'precision': float(metrics['precision'][class_index]),
                'recall': float(metrics['recall'][class_index]), 'f1': float(metrics['f1'][class_index]), 'record_support': int(metrics['support'][class_index]),
                'distinct_group_support': len({records[i]['group_id'] for i in np.flatnonzero(actual == class_index)})})
            for predicted_index, predicted_label in enumerate(labels):
                confusion_rows.append({'model': model, 'actual_class': label, 'predicted_class': predicted_label,
                    'records': int(metrics['confusion'][class_index, predicted_index]),
                    'row_normalized': float(metrics['confusion'][class_index, predicted_index] / metrics['support'][class_index])})
    return {'observed': {name: {'macro_f1': value['macro_f1'], 'accuracy': value['accuracy']} for name, value in observed.items()},
            'intervals': intervals, 'estimates': estimate_rows, 'groups': groups, 'member_groups': member_groups,
            'draws': draws, 'denominators': denominators, 'class_rows': class_rows, 'confusion_rows': confusion_rows}
