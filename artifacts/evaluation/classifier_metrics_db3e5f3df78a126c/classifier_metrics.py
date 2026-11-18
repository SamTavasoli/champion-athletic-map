"""Pure classification summaries using an explicitly supplied frozen class order."""

from collections.abc import Mapping, Set

from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

VERSION = "classifier-metrics-1"


def summarize_classifier_predictions(y_true, y_pred, split_group_ids, class_order):
    """Summarize supplied predictions without fitting, predicting, or reading files.

    Confusion-matrix rows are actual classes and columns are predicted classes.
    Undefined per-class ratios use sklearn's zero-division convention and carry
    separate definition flags. An empty evaluation reports unavailable metrics.
    """

    def string_vector(values):
        if (isinstance(values, (str, bytes, bytearray, Mapping, Set))
                or getattr(values, "ndim", 1) != 1):
            raise ValueError("Expected a one-dimensional string sequence.")
        try:
            result = list(values)
        except TypeError:
            raise ValueError("Expected a one-dimensional string sequence.") from None
        if any(not isinstance(value, str) or not value.strip() for value in result):
            raise ValueError("Expected nonblank string values without nested entries.")
        return result

    order = string_vector(class_order)
    if not order or len(set(order)) != len(order):
        raise ValueError("Class order must be nonempty and contain unique labels.")
    actual = string_vector(y_true)
    predicted = string_vector(y_pred)
    groups = string_vector(split_group_ids)
    if not len(actual) == len(predicted) == len(groups):
        raise ValueError("Evaluation sequences must have identical lengths.")
    allowed = set(order)
    if any(value not in allowed for value in actual + predicted):
        raise ValueError("Evaluation labels must belong to the supplied class order.")

    count = len(actual)
    class_count = len(order)
    if count:
        precision, recall, f1, support = precision_recall_fscore_support(
            actual, predicted, labels=order, average=None, zero_division=0
        )
        confusion = confusion_matrix(actual, predicted, labels=order).tolist()
        accuracy = float(accuracy_score(actual, predicted))
        macro_f1 = float(f1_score(
            actual, predicted, labels=order, average="macro", zero_division=0
        ))
    else:
        precision = recall = f1 = [None] * class_count
        support = [0] * class_count
        confusion = [[0] * class_count for _ in order]
        accuracy = macro_f1 = None

    per_class, proportions = [], []
    for index, label in enumerate(order):
        actual_count = int(support[index])
        predicted_count = sum(row[index] for row in confusion)
        class_groups = {group for target, group in zip(actual, groups) if target == label}
        per_class.append({
            "class_index": index,
            "label": label,
            "precision": float(precision[index]) if count else None,
            "recall": float(recall[index]) if count else None,
            "f1": float(f1[index]) if count else None,
            "support_records": actual_count,
            "support_groups": len(class_groups),
            "predicted_records": predicted_count,
            "precision_defined": predicted_count > 0,
            "recall_defined": actual_count > 0,
            "f1_defined": actual_count + predicted_count > 0,
        })
        proportions.append(
            [value / actual_count for value in confusion[index]]
            if actual_count else [None] * class_count
        )
    return {
        "version": VERSION,
        "status": "available" if count else "unavailable_no_evaluated_records",
        "class_order": order,
        "n_records": count,
        "n_groups": len(set(groups)),
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "per_class": per_class,
        "confusion_axes": {"rows": "actual", "columns": "predicted"},
        "confusion_counts": confusion,
        "confusion_row_proportions": proportions,
    }
