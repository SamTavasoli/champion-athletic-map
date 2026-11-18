"""Fixed exercise-text rules; learned representations are prepared separately."""

import re
import unicodedata

TEXT_RULES_VERSION = "exercise-text-rules-0.1.0"
TOKEN_PATTERN = r"(?u)\b\w+(?:[.'’/-]\w+)*\b"
_TOKENS = re.compile(TOKEN_PATTERN)


def _string(value):
    if not isinstance(value, str):
        raise TypeError("Text preparation requires a string without coercion.")
    return value


def normalize_model_text(canonical_text):
    """Apply NFKC, compact whitespace, strip, then casefold, in that order.

    This generic operation permits empty strings. Validate canonical exercise
    input through prepare_canonical_text before using it as a model example.
    Apply this function once to canonical text, never again to saved model_text.
    """
    normalized = unicodedata.normalize("NFKC", _string(canonical_text))
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def tokenize_model_text(model_text):
    """Tokenize already prepared text; do not normalize again or insert UNK."""
    return _TOKENS.findall(_string(model_text))


def prepare_canonical_text(canonical_text):
    """Validate a nonblank canonical input and prepare both shared representations."""
    text = _string(canonical_text)
    if not text.strip():
        raise ValueError("Canonical exercise text must not be empty or whitespace-only.")
    model_text = normalize_model_text(text)
    if not model_text:
        raise ValueError("Canonical exercise text became empty after fixed normalization.")
    return {"model_text": model_text, "tokens": tokenize_model_text(model_text)}


def tokenize_canonical_text(canonical_text):
    """Sklearn tokenizer for canonical input: normalize once, then tokenize.

    Keep the vectorizer's word analyzer, disable extra lowercasing and use no
    additional preprocessor. Pass classifier_text, not saved model_text.
    """
    return prepare_canonical_text(canonical_text)["tokens"]

"""Deterministic neural representation helpers; split isolation is the caller's job."""

from collections import Counter as _NeuralCounter
from fractions import Fraction as _NeuralFraction
import math as _neural_math

NEURAL_PAD_TOKEN = "<PAD>"
NEURAL_UNK_TOKEN = "<UNK>"
NEURAL_VOCABULARY_SCHEMA_VERSION = "neural-vocabulary-1"
NEURAL_SEQUENCE_SCHEMA_VERSION = "neural-sequence-limit-1"


def _neural_positive_integer(value):
    if type(value) is not int or value < 1:
        raise ValueError("Expected a positive integer without Boolean coercion.")
    return value


def _neural_raw_tokens(tokens):
    if not isinstance(tokens, list):
        raise ValueError("Expected a raw-token list.")
    for token in tokens:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("Raw tokens must be nonblank strings.")
        if token in (NEURAL_PAD_TOKEN, NEURAL_UNK_TOKEN):
            raise ValueError("Reserved neural symbols cannot occur as ordinary raw tokens.")
    return list(tokens)


def _neural_training_sequences(token_sequences):
    if not isinstance(token_sequences, list) or not token_sequences:
        raise ValueError("Expected a nonempty training list of raw-token lists.")
    return [_neural_raw_tokens(tokens) for tokens in token_sequences]


def fit_training_vocabulary(token_sequences, min_frequency=2, max_ordinary_tokens=10000):
    """Fit occurrence counts on full, untruncated TRAIN token sequences only.

    The caller must supply training rows and enforce their provenance. This
    function does not infer split membership, normalize tokens or truncate text.
    Empty token rows remain empty during frequency fitting and add no UNK count.
    """
    minimum = _neural_positive_integer(min_frequency)
    capacity = _neural_positive_integer(max_ordinary_tokens)
    sequences = _neural_training_sequences(token_sequences)
    counts = _NeuralCounter()
    for tokens in sequences:
        counts.update(tokens)
    candidates = sorted(counts, key=lambda token: (-counts[token], token))
    eligible = [token for token in candidates if counts[token] >= minimum]
    retained = eligible[:capacity]
    id_to_token = [NEURAL_PAD_TOKEN, NEURAL_UNK_TOKEN, *retained]
    token_to_id = {token: index for index, token in enumerate(id_to_token)}
    occurrences = sum(counts.values())
    retained_occurrences = sum(counts[token] for token in retained)
    return {
        "schema_version": NEURAL_VOCABULARY_SCHEMA_VERSION,
        "token_to_id": token_to_id,
        "id_to_token": id_to_token,
        "retained_frequencies": {token: counts[token] for token in retained},
        "vocabulary_size": len(id_to_token),
        "n_training_sequences": len(sequences),
        "n_empty_token_sequences": sum(not tokens for tokens in sequences),
        "candidate_ordinary_tokens": len(candidates),
        "frequency_eligible_ordinary_tokens": len(eligible),
        "retained_ordinary_tokens": len(retained),
        "excluded_below_frequency": len(candidates) - len(eligible),
        "excluded_by_capacity": len(eligible) - len(retained),
        "raw_token_occurrences": occurrences,
        "retained_token_occurrences": retained_occurrences,
        "excluded_token_occurrences": occurrences - retained_occurrences,
        "fit_policy": {
            "fit_split": "train",
            "split_verification": "caller_responsibility",
            "frequency_basis": "total occurrences in full untruncated raw training token sequences",
            "min_frequency": minimum,
            "max_ordinary_tokens": capacity,
            "ordering": ["descending training frequency", "lexical token order for ties"],
            "reserved_ids": {NEURAL_PAD_TOKEN: 0, NEURAL_UNK_TOKEN: 1},
            "ordinary_ids_start": 2,
            "truncation_before_fit": False,
            "validation_or_test_expansion": False,
            "empty_rows_add_frequency_counts": False,
        },
    }


def choose_training_sequence_limit(token_sequences, percentile=0.95, minimum=16, maximum=256):
    """Choose a clamped nearest-rank limit from full effective TRAIN lengths.

    A raw empty row has effective length one for the later UNK fallback. No
    fallback token is inserted into the supplied raw sequences or vocabulary.
    """
    lower = _neural_positive_integer(minimum)
    upper = _neural_positive_integer(maximum)
    if lower > upper:
        raise ValueError("The sequence minimum must not exceed its maximum.")
    if (type(percentile) not in (int, float) or not 0 < percentile <= 1
            or not _neural_math.isfinite(percentile)):
        raise ValueError("Expected a finite percentile greater than zero and at most one.")
    sequences = _neural_training_sequences(token_sequences)
    lengths = sorted(max(1, len(tokens)) for tokens in sequences)
    fraction = _NeuralFraction(str(percentile))
    rank = (len(lengths) * fraction.numerator + fraction.denominator - 1) // fraction.denominator
    selected = lengths[rank - 1]
    return {
        "schema_version": NEURAL_SEQUENCE_SCHEMA_VERSION,
        "fit_split": "train",
        "split_verification": "caller_responsibility",
        "percentile": float(percentile),
        "method": "nearest_rank",
        "percentile_rank": rank,
        "nearest_rank_length": selected,
        "max_sequence_length": min(upper, max(lower, selected)),
        "n_sequences": len(lengths),
        "minimum": lower,
        "maximum": upper,
        "minimum_effective_length": lengths[0],
        "maximum_effective_length": lengths[-1],
        "n_empty_token_sequences": sum(not tokens for tokens in sequences),
        "length_basis": "max(1, full raw-token length), before truncation",
    }


def validate_neural_vocabulary(vocabulary):
    """Validate actual mapping/list consistency and contiguous reserved-aware IDs.

    Encoding depends on the supplied token_to_id mapping. Fit metadata may be
    present, but it cannot replace validation of that actual mapping and list.
    """
    if not isinstance(vocabulary, dict):
        raise ValueError("Expected a neural-vocabulary object.")
    token_to_id = vocabulary.get("token_to_id")
    id_to_token = vocabulary.get("id_to_token")
    if not isinstance(token_to_id, dict) or not isinstance(id_to_token, list) or len(id_to_token) < 2:
        raise ValueError("Vocabulary needs a token mapping and an ordered token list.")
    if len(token_to_id) != len(id_to_token):
        raise ValueError("Vocabulary mapping and token-list sizes differ.")
    if id_to_token[:2] != [NEURAL_PAD_TOKEN, NEURAL_UNK_TOKEN]:
        raise ValueError("Vocabulary must reserve PAD at zero and UNK at one.")
    seen = set()
    for index, token in enumerate(id_to_token):
        if not isinstance(token, str) or not token.strip() or token in seen:
            raise ValueError("Vocabulary tokens must be unique nonblank strings.")
        if index >= 2 and token in (NEURAL_PAD_TOKEN, NEURAL_UNK_TOKEN):
            raise ValueError("Reserved symbols cannot occupy ordinary-token positions.")
        seen.add(token)
        actual = token_to_id.get(token)
        if type(actual) is not int or actual != index:
            raise ValueError("Vocabulary IDs must be contiguous and match the ordered tokens.")
    if "schema_version" in vocabulary and vocabulary["schema_version"] != NEURAL_VOCABULARY_SCHEMA_VERSION:
        raise ValueError("Unexpected neural-vocabulary schema version.")
    if "vocabulary_size" in vocabulary and (type(vocabulary["vocabulary_size"]) is not int
            or vocabulary["vocabulary_size"] != len(id_to_token)):
        raise ValueError("Declared vocabulary size differs from the actual mapping.")
    if "retained_frequencies" in vocabulary:
        frequencies = vocabulary["retained_frequencies"]
        if not isinstance(frequencies, dict) or set(frequencies) != set(id_to_token[2:]):
            raise ValueError("Retained frequencies must describe exactly the ordinary vocabulary.")
        for count in frequencies.values():
            _neural_positive_integer(count)
    return True


def encode_neural_tokens(tokens, vocabulary, max_sequence_length):
    """Map full raw tokens, use one UNK for empties, then retain a prefix.

    No PAD positions are emitted. Padding and labels belong to later batching;
    a valid class label zero has no relation to the reserved token PAD ID zero.
    """
    raw = _neural_raw_tokens(tokens)
    limit = _neural_positive_integer(max_sequence_length)
    validate_neural_vocabulary(vocabulary)
    token_to_id = vocabulary["token_to_id"]
    fallback = not raw
    full_ids = [1] if fallback else [token_to_id.get(token, 1) for token in raw]
    token_ids = full_ids[:limit]
    unknown_before = full_ids.count(1)
    unknown_after = token_ids.count(1)
    return {
        "token_ids": token_ids,
        "raw_token_count": len(raw),
        "effective_token_count": len(full_ids),
        "retained_length": len(token_ids),
        "truncated_tokens": len(full_ids) - len(token_ids),
        "unknown_tokens_before_truncation": unknown_before,
        "unknown_tokens_after_truncation": unknown_after,
        "empty_token_fallback": fallback,
        "all_unknown_after_truncation": unknown_after == len(token_ids),
    }

"""Right-pad validated neural examples; tensor conversion belongs to modeling."""

BATCH_SCHEMA_VERSION = "neural-batch-1"


def pad_neural_batch(examples, max_sequence_length, vocabulary_size, num_classes):
    """Preserve row order and repeated IDs; emit PAD zero and Boolean masks.

    Inputs must already be encoded and truncated under the saved text policy.
    This helper performs no truncation, tensor conversion, model math or fitting.
    """
    for value, lower in ((max_sequence_length, 1), (vocabulary_size, 2), (num_classes, 2)):
        if type(value) is not int or value < lower:
            raise ValueError("Invalid batch dimensions; use integers without Boolean coercion.")
    if not isinstance(examples, list) or not examples:
        raise ValueError("Expected a nonempty list of encoded examples.")
    record_ids, sequences, lengths, targets = [], [], [], []
    for example in examples:
        if not isinstance(example, dict) or set(example) != {"record_id", "token_ids", "target"}:
            raise ValueError("Each batch example needs exactly record_id, token_ids and target.")
        record_id = example["record_id"]
        if not isinstance(record_id, str) or not record_id.strip():
            raise ValueError("Record identifiers must be nonblank strings.")
        ids = example["token_ids"]
        if not isinstance(ids, list) or not ids or len(ids) > max_sequence_length:
            raise ValueError("Encoded token lists must be nonempty and within the saved limit.")
        if any(type(token_id) is not int or not 1 <= token_id < vocabulary_size for token_id in ids):
            raise ValueError("Unpadded tokens must be valid positive vocabulary IDs; PAD is not input.")
        target = example["target"]
        if type(target) is not int or not 0 <= target < num_classes:
            raise ValueError("Targets must be valid class indices, including class zero.")
        record_ids.append(record_id)
        sequences.append(list(ids))
        lengths.append(len(ids))
        targets.append(target)
    width = max(lengths)
    token_ids = [ids + [0] * (width - length) for ids, length in zip(sequences, lengths)]
    mask = [[True] * length + [False] * (width - length) for length in lengths]
    return {"record_ids": record_ids, "token_ids": token_ids, "mask": mask,
        "lengths": lengths, "targets": targets}
