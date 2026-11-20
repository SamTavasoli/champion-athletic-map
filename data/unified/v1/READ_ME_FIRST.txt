CHAMPIONS ATHLETIC MAP: ONE SHARED DATASET
Release 1.0.0 | Prepared November 13, 2026

THE FILE EVERYONE USES
champions_unified_dataset.csv

This is the shared master for our team. It combines the original cleaned
master and later source/preparation records in one CSV. Every row has the
same 24 columns. The file has 264,921 mixed records; this is not a count of
training examples, independent athletes, or approved activities.

WHAT IS INCLUDED
- All 256,337 original master records, once. Their nine constituent tables
  enrich those rows; they are not appended as duplicate rows.
- Exercise preparation, original source fields, frozen labels and split
  controls attached to the original 2,909 exercise records.
- 143 current basketball resource identities: 136 prototype-adopted variants
  and seven held records. One historical alias is merged into its target.
  All 23 later drill metadata rows and their 23 matching documents remain
  attached as source history, rather than 46 extra activities.
- 32 older local checklist/topic entries with no confirmed ID link. They
  remain historical candidates, not extra approved or distinct drills.
- 34 rule identities: 29 adopted definitions and five revision/held items.
  Earlier guidance/reference rows are retained within their source history.
- The exact 11 indexed CDC/UGA passage cores, with complete required
  delivery/attribution/context bundles inside data_json.
- 411 earlier Foundation food records and all 7,793 SR Legacy food records.
  The 100 prepared SR Legacy lookup foods carry their selected nutrient and
  portion tables. Full raw food observations remain archival source data;
  their presence does not mean the application used all of them.
- 30 original fictional profiles, 60 later fictional source profiles and
  100 development drafts. These are different stages with overlapping
  lineage, not 190 independent measured athletes.

HOW EACH COMPONENT USES THIS SAME CSV
1. Classifier training: classifier_use = training. This returns 1,999 rows.
2. Classifier validation: classifier_use = validation. This returns 435 rows.
   Features are text ONLY; the target is target_label. The column class_index
   retains the frozen class order, including valid class zero.
3. Existing RAG corpus: retrieval_use = indexed_reference. This returns 11
   rows. The text column is the exact indexed core. Keep its complete
   data_json delivery bundle when presenting reference content.
4. Prepared food lookup:
   food_lookup_use = prepared_selected_reference_activation_unverified.
   This returns the 100 selected SR Legacy foods. Their structured values,
   exact units, per-100-g basis, missing-value statuses and portion records
   are in data_json. Missing nutrient values are not zero.
5. Prototype activity records:
   planner_status = prototype_adopted_activation_pending. This returns 136
   prepared variants. Runtime activation is not confirmed by this export.
6. Adopted rule definitions:
   planner_status = prototype_definition_adopted_validator_not_ready.
   This returns 29 definitions; automatic validator execution is not ready
   according to the supplied release evidence.
7. Development profile drafts: record_stage = development_draft. This
   returns 100 fictional drafts, not accepted final evaluation profiles.

THE COLUMNS TO START WITH
record_type: what kind of information the row represents.
record_stage: source, current prepared record, historical candidate, or draft.
title: the human-readable name or existing ID.
text: the convenience text for that record's stated route.
source_dataset / source_record_id: where the row came from.
classifier_use / retrieval_use / planner_status / food_lookup_use:
  the row's recorded use and readiness.
data_json: the full structured source fields and history.

The complete field dictionary is in dataset_manifest.json. Shared nutrient
definitions, units, quality reports, source hashes and rule interpretation
policies are there too. Keep this small companion with the CSV.

READING IT IN PYTHON
Put all files from this ZIP in the same directory. No extra Python packages
are required for the supplied loader:

from load_unified_dataset import iter_records
training = list(iter_records(classifier_use="training"))
X = [row["text"] for row in training]
y = [row["target_label"] for row in training]

references = list(iter_records(retrieval_use="indexed_reference",
                               decode_data=True))

The loader streams the large CSV and decodes nested JSON only for matching
rows. Run python load_unified_dataset.py for counts, or add --verify to
check this CSV against its release hash.

PRESERVED BOUNDARIES
The original 438 classifier test records remain reserved. Whole-group
protection covers 439 rows because one excluded sibling belongs to a test
group. Protected and other excluded exercise rows have blank top-level
text; original public source fields remain archival inside data_json.
Do not use archived agent_text, target labels, review fields or all of
data_json as classifier features. Only the existing 11 reference cores
are marked indexed; merging creates no new RAG admissions or approvals.

This CSV organizes the existing records. It does not retrain a model,
change a split, execute a rule, refresh a publisher source, or activate
resources. Our existing notebook still reads its original paths until we
connect it to this shared format. Original project files remain unchanged.

FILE SIZE AND EDITING
The CSV is about 525 MB before ZIP compression. It preserves full nested
source information. Nineteen JSON payloads exceed Excel's 32,767-character
cell limit. Use Python for the master; resaving it through Excel can lose
those payloads. Team members can filter the same master for their task.

SOURCE SCOPE
The source package binds the checked GitHub sam-development snapshot,
saved project evidence through Step 23, and the later resource-review
release. Source/adoption history is preserved as recorded; this export
does not establish later Step 24 runtime execution. Private benchmark
questions/gold, protected planner-test profiles, model weights and
standalone classifier prediction exports are not added to this master.

PACKAGE CONTENTS
champions_unified_dataset.csv: the ONE shared data table.
dataset_manifest.json: field dictionary, shared source definitions and hashes.
load_unified_dataset.py: optional standard-library reader.
READ_ME_FIRST.txt: this guide.
