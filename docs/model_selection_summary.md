# Step 21 — Model selection summary

The fixed-holdout search retained the frozen training and validation partitions, target mapping and preprocessing rules. The search scheduled six logistic regression configurations and eight neural configuration/seed combinations, including verified reused references. Training-derived features, vocabulary, sequence limits and class weights were preserved.

| Selected comparison artifact | Accuracy | Validation macro-F1 |
|---|---:|---:|
| Majority-class baseline | 0.190805 | 0.020029 |
| Logistic L5: C=10.0, class weight=balanced | 0.724138 | 0.598009 |
| Neural N3, primary seed 42, epoch 19 | 0.682759 | 0.571145 |

The neural configuration was selected by its complete three-seed mean macro-F1 of 0.562456, with sample standard deviation 0.008760 (ddof=1). The primary neural artifact remains its best seed-42 checkpoint; the mean is configuration evidence rather than the score of a separately fitted model. No highest-scoring seed or unplanned ensemble was selected.

The selected neural configuration uses learning rate 0.001, dropout 0.2 and class weighting `training_frequency`. Each run's objective-specific learning loss and selected epoch are retained. Weighted and unweighted cross-entropy describe different objectives and were not used to rank configurations.

The selected tagging family is `logistic_regression`, with artifact validation macro-F1 0.598009, exceeding the majority baseline's 0.020029. Cross-family tagging selection compares the two actual selected artifact scores. An exact tie favors logistic regression; a learned artifact must strictly improve on the majority baseline. A small validation-score difference does not establish a statistically reliable advantage.

All selected artifacts were scored on the same 435 validation records and 384 distinct groups, with all 16 frozen classes retained in macro-F1. Class support ranges from 3 to 119 records, so accuracy alone does not describe performance across the less frequent classes. The class reports preserve undefined-precision flags rather than treating an unpredicted class as having measured precision.

Confusion counts, row proportions and group supports are saved for all three artifacts. Empty diagnostic subsets retain unavailable scores. Name-only, truncation and low-coverage subsets are descriptive: their compositions differ, and these comparisons do not isolate causal effects or replace the full-population selection measure.

The logistic pipeline uses full prepared text. The neural model applies the saved training-derived sequence limit of 81 tokens. Frozen L2 zero-vector flags are reused for the selected logistic model only after its TF-IDF vocabulary, IDF values and feature configuration match the original representation; no new feature transformation is performed by these diagnostics.

Repeated use of validation for checkpointing and tuning makes these results development evidence. The three-seed standard deviation describes variation on this split; it is not a confidence interval or uncertainty across independent athlete populations. Held-out transformations, predictions and final scoring remain reserved for Step 32.

The fitted comparison artifacts retain their original training-partition fits. No combined training/validation refit or new model training occurred during final selection. Step 22 will package the explicitly identified artifacts for tagging suggestions under review. Predictions do not approve an exercise or make a basketball drill eligible for planning; existing source labels and review status remain unchanged, and human source-label review remains pending. Planner acceptance and operational evaluation readiness remain independent open work.

A later classifier revision requires a separately documented development cycle. Step 32 outcomes will not silently switch the classifier supplied to planning workflows.
