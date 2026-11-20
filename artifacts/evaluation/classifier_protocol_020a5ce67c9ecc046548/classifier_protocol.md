# Classifier evaluation protocol — scoped freeze

We freeze Step 32's classifier benchmark settings separately from the unfinished
planner experiment. This explicitly amends the earlier single global readiness
gate and preserves its original document. The sequence of evaluation steps stays
32, 33, 34, 35. The protected classifier test is not executed by this checkpoint.

We retain the training-only majority baseline, logistic L5, and neural N3 seed42
best-validation checkpoint. Macro-F1 uses every frozen class with zero_division=0.
All three models must cover the same complete eligible test population; an
incomplete comparison stays incomplete. Step 35 will use the recorded paired
exercise-group bootstrap recipe. A low result will not justify retraining,
changing labels, replacing difficult examples, or selecting another seed.

Step 32 needs a dedicated protected-benchmark evaluator and environment checks.
The application's protected-record guard remains intact. Classifier findings
must not alter the selected application model, planner inputs, reference corpus,
catalog tags or workflow settings in the recorded experiment.

The JSON manifest records exact model, source, configuration and data-file hashes.
Data files are checked as opaque bytes; protected exercise text and profile rows
are not parsed. Models are not deserialized. Source-label and earlier EDA limits
remain part of interpretation. No prediction, bootstrap interval, human rating
or final score is created here.

The whole planner experiment is NOT frozen. Its final case acceptance, families,
feasibility records, retrieval assessment and human preparation remain pending.
The metadata observations refer to their saved preparation checkpoints; this
cell does not make new case approvals or claim later work has been verified.
The planner must receive its own complete protocol freeze before Step 33.
