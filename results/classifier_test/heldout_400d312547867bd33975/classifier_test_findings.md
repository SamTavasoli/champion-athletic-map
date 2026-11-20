# Final exercise classifier findings

We evaluated the three preselected classifiers on 438 records in 385 exercise groups, using all 16 frozen labels.

| Model | Macro-F1 | Accuracy | Errors |
|---|---:|---:|---:|
| Majority baseline | 0.0234 | 0.2306 | 337 |
| L5 logistic regression | 0.6143 | 0.7329 | 117 |
| N3 neural classifier (seed 42) | 0.5288 | 0.6781 | 141 |

Macro-F1 gives every frozen label equal weight, with zero_division=0. Accuracy is the proportion of records classified correctly. CSV and JSON scores retain full precision; this table rounds for display.

## Input and error review

The test includes 236 name-only inputs. Inputs containing unfamiliar words and zero TF-IDF feature rows remain included. The input diagnostics table records the saved neural token, unknown-word and truncation counts alongside each model's correctness.

The models disagree on 363 records. The error review contains up to 20 mistakes per model, ordered by SHA256(protocol ID, model family and catalog ID). These are examples for analysis; no human error ratings have been entered and no benchmark labels were changed.

- Majority baseline — most frequent actual → predicted errors: quadriceps → abdominals: 97; chest → abdominals: 43; shoulders → abdominals: 43; biceps → abdominals: 28; triceps → abdominals: 28
- L5 logistic regression — most frequent actual → predicted errors: quadriceps → abdominals: 10; abdominals → quadriceps: 9; abdominals → lats: 4; quadriceps → abductors: 4; shoulders → abdominals: 4
- N3 neural classifier (seed 42) — most frequent actual → predicted errors: quadriceps → abdominals: 14; abdominals → lats: 8; quadriceps → glutes: 6; abdominals → quadriceps: 5; quadriceps → lower back: 5

## Interpretation and limits

These scores measure agreement with this constructed exercise-label benchmark. They do not establish basketball-plan quality, athlete suitability or real-world safety. Related records were kept within their frozen groups, but full-source preparation and exploratory analysis took place before the benchmark freeze. Source labels may still contain errors or broad categories.

The confusion matrices use actual labels on rows and predicted labels on columns. Row proportions divide by actual-label support. An undefined row remains blank in the CSV and grey in the figure.

The error patterns are exploratory. We did not refit a model, select another seed, remove difficult examples or change targets after testing. The application keeps its validation-selected L5 model, and these test predictions are not added to the planner inputs. Human review and the planner experiment remain separate.

Confidence intervals and paired group-bootstrap comparisons are reserved for Step 35. The aligned prediction table retains catalog IDs, group IDs and the original targets for that analysis.
