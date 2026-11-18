"""Read the shared dataset with Python's standard library; no installations needed.

Examples:
    from load_unified_dataset import iter_records, load_manifest
    training = list(iter_records(classifier_use='training'))
    references = list(iter_records(retrieval_use='indexed_reference', decode_data=True))
    foods = list(iter_records(food_lookup_use='prepared_selected_reference_activation_unverified', decode_data=True))

For training, use row['text'] as features and row['target_label'] as targets.
The data_json archive contains labels and metadata and is not feature text.
"""
from pathlib import Path
import csv
import json
import hashlib
import argparse

DIRECTORY = Path(__file__).resolve().parent
DATASET = DIRECTORY / 'champions_unified_dataset.csv'
MANIFEST = DIRECTORY / 'dataset_manifest.json'


def load_manifest():
    """Read the field dictionary, source bindings and shared units/policies."""
    with MANIFEST.open(encoding='utf-8') as f:
        return json.load(f)


def iter_records(*, decode_data=False, **filters):
    """Stream rows matching every exact column=value filter.

    Empty source cells remain empty strings. Source JSON values retain their
    recorded types when decode_data=True. This does not normalize, tokenize,
    train, encode, retrieve, or change any approval state.
    """
    csv.field_size_limit(64 * 1024 * 1024)
    with DATASET.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        unknown = set(filters) - set(reader.fieldnames or [])
        if unknown:
            raise ValueError('Unknown dataset columns: ' + ', '.join(sorted(unknown)))
        for row in reader:
            if all(row[key] == str(value) for key, value in filters.items()):
                if decode_data:
                    row['data_json'] = json.loads(row['data_json'])
                yield row


def verify_file():
    expected = load_manifest()
    digest = hashlib.sha256()
    with DATASET.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != expected['csv_sha256']:
        raise ValueError('The CSV does not match this release manifest.')
    return {'dataset_id': expected['dataset_id'], 'rows': expected['row_count'],
            'csv_sha256': actual, 'file_matches_release': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Inspect the shared Champions dataset without changing it.')
    parser.add_argument('--verify', action='store_true', help='Verify the CSV against its release SHA-256.')
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_file(), indent=2))
    else:
        m = load_manifest()
        print(json.dumps({'dataset_id': m['dataset_id'], 'rows': m['row_count'],
                         'record_types': m['counts']['record_type'],
                         'classifier_use': m['counts']['classifier_use']}, indent=2))
