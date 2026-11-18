# Exercise classifier model card

This release preserves the three comparison artifacts selected in Step 21 for inference and evaluation. It contains their original training-partition fits, the required source package and frozen preprocessing dependencies. It contains no optimizer or exact training-resume state.

Release: `exercise-classifier-4f6b6f435ef52fef8f4cca6d`  
Selection: `classifier-model-selection:f7c959560435263cd7a9f66e2c934f0d93e9d8cd3541183f017ca1c84864b32a`  
Git revision: `d34072a0dffcb44cb28afa3e2fde14911720b91b`

## Intended use

The learned models suggest one supported body-part category from a general exercise name and optional description. Predictions require review and do not establish exercise safety, youth suitability, basketball skill categories, source accuracy or planner eligibility. Unfamiliar inputs can lie outside the learned taxonomy even when a supported label is returned.

The selected tagging artifact is **L5 (logistic_regression)**. It was chosen by the frozen Step 21 rule comparing the actual selected logistic pipeline and neural seed-42 checkpoint.

Supported output labels: `abdominals`, `abductors`, `adductors`, `biceps`, `calves`, `chest`, `forearms`, `glutes`, `hamstrings`, `lats`, `lower back`, `middle back`, `quadriceps`, `shoulders`, `traps`, `triceps`.

## Training and development evidence

The frozen experiment used 1999 training records and 435 validation records, with 384 distinct validation groups and all 16 supported classes retained in macro-F1. Training-derived vocabulary, feature statistics, class weights and the saved neural sequence limit were preserved.

| Artifact | Candidate | Validation accuracy | Validation macro-F1 |
|---|---|---:|---:|
| logistic_regression | L5 | 0.724138 | 0.598009 |
| majority | training majority | 0.190805 | 0.020029 |
| neural | N3 | 0.682759 | 0.571145 |

The selected neural configuration's complete three-seed mean macro-F1 was 0.562456 with sample standard deviation 0.008760 (ddof=1). Its primary artifact remains seed 42, best epoch 19. The mean selects the configuration; the actual seed-42 artifact score is used for tagging comparison.

Validation was reused for checkpointing and tuning, so these scores are development evidence. The three-seed standard deviation is descriptive and is not a confidence interval. Probabilities are uncalibrated model outputs. TF-IDF uses full prepared text; neural inference retains the fixed 81-token limit. Weighted and unweighted training losses describe different objectives.

## Loading and prediction

Use the recorded Python and package versions in `environment.json` and `requirements.txt`. Add this release's `src` directory to Python's import path in a fresh process. Paths in the manifest are relative to the release folder, so the bundle can be moved. Start Python with `-B` to leave the release's source tree unchanged.

```python
from champion_athletic_map.classifier_inference import load_classifier, predict_exercise

handle = load_classifier(release_directory, family="tagging", device="cpu")
result = predict_exercise(handle, "Authored example exercise", input_scope="synthetic")
```

The synthetic scope above is for authored interface demonstrations. The catalog workflow may supply `development_train` or `development_validation` only after verifying actual frozen population membership. A scope string itself does not prove membership or complete review. The default `new_record` scope is deferred before text preparation or model loading. Protected, review-only and unproven records remain deferred; basketball drill types are unsupported by this body-part interface.

Input construction follows Step 10's field whitespace/null handling and uses a name-first canonical string with two newline characters before a present description. Each learned route applies its saved Unicode/text preparation once. Predictions carry the release/model identity, canonical input hash, handling flags and frozen score class order. A missing description is allowed; invalid names return an input error. Loading, integrity or inference failure never selects an undocumented substitute model.

Neural loading uses an explicit device, `weights_only=True`, strict state matching, evaluation mode and gradients disabled. The three models and preprocessing state are checked for changes during inference. These files support inference and evaluation, rather than exact resumption of training.

## Bundle verification

The staged release was imported and loaded in a fresh Python process using its bundled source modules. The completed publication is also replayed at its final location before the external producer record is committed. All 435 validation records per checked model/device must reproduce their recorded labels exactly. Numerical outputs use the fixed tolerances rtol=1e-5 and atol=1e-6.

The reference neural device is `cuda:0`; the portable application device is `cpu`. Device checks are deduplicated when both are the same. Canonical construction and normalized text are checked for all 2434 saved development inputs. Neural API logits and probabilities are compared with an independent batch-32 forward using the same copied weights; objective-specific validation loss is checked against the saved run. The checks are reproducibility evidence, not new independent accuracy experiments.

The saved numerical logit arrays are not an external reference file. Any reported saved-logit digest comparison is an additional check; label agreement, saved-probability agreement and objective-loss agreement remain required at the stated tolerances.

## Catalog and evaluation boundaries

The initial eligible development-preview population contains 2434 records. All 439 catalog rows belonging to the 385 protected test groups remain excluded, including 1 group-related benchmark exclusions. The other 36 excluded records require review and are outside the initial preview population. No catalog suggestions or review decisions are produced by bundle assembly.

Source labels, independent verification status, review decisions and effective catalog labels remain separate. Pending suggestions never become effective labels automatically, and an explicit rejection blocks fallback to the rejected source value. Existing source values and benchmark targets remain unchanged.

New-record intake and complete protected-group screening remain pending. Repeated-relation digests alone cannot clear unfamiliar records, and no new screening index is built from held-out text before Step 32. Final held-out transformations, predictions and scoring remain Step 32. No final test results are included here.

The catalog prediction/review exports and Step 23 handoff follow in later Step 22 substeps. Retrieval and planner eligibility require separate approval conditions. Step 31 freezes experiment versions; any tagging of formerly held-out cases after Step 32 belongs to a separate catalog revision outside the frozen planner comparison.
