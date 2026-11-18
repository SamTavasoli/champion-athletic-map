# Technical guide

This guide describes our project through Step 37. Earlier model cards, integration notes and planner documents retain the development-stage observations from when they were written. The final result summaries and current reproduction record take precedence for the completed evaluation.

## Components and data flow

| Stage | Main implementation | Responsibility |
|---|---|---|
| Unified inputs | `src/champion_athletic_map/unified_data.py`, `unified_references.py` | Load the recorded input package and maintain source identities. |
| Exercise classification | `classifier_inference.py`, `text_preprocessing.py`, `neural_classifier.py` | Apply the selected fitted classifier and its frozen preprocessing. |
| References | `reference_tools.py`, `reference_packets.py`, `reference_context.py` | Retrieve and package source-linked material. |
| Shared model client | `llm.py` | Validate input, prepare complete requests, record raw replies and apply the response contract. |
| Planning workflows | `planners/` | Implement the four study versions and their role sequence. |
| Coded checks | `planning_checks.py`, `rule_checks.py` and later versioned checking modules | Check supported constraints and retain met, violated, unknown and not-applicable states. |
| Application | `app/streamlit_app.py`, `application_state.py`, `plan_exports.py`, `runtime_controller.py` | Manage the interface, plan versions, progress, snapshots and bounded execution. |
| Results analysis | Step 35 saved analysis helpers | Analyze the original outcomes, predictions, retrieval evidence and review ratings. |
| Reproduction | Step 36 versioned verification folder | Replay a dedicated saved-results notebook in an independently installed environment. |

Module names in the table after the first row are relative to `src/champion_athletic_map/` unless another location is shown. The exact final software versions are recorded in the experiment and reproduction manifests.

## Data and resource versions

The four-file unified package belongs in `data/unified/v1/`. Its manifest and loader belong to the same dataset version. The source register and component manifests provide the broader input inventory.

The exercise taxonomy has 16 body-part classes. L5 logistic regression was selected using validation evidence and kept for the final test. Its classifier release preserves the fitted comparison artifacts and preprocessing; it is an inference/evaluation release, not an exact training-resume checkpoint. See [the classifier model card](classifier_model_card.md) and the final Step 32 results.

Approved basketball records and warm-ups are separate from general gym exercises. A classifier prediction never activates an exercise for planning. Adopted rule definitions are also separate from implemented checking coverage. We retain source facts, review decisions and generated descriptions as different fields.

## Shared requests and the four workflows

The planner comparison used the same local `llama3.1:8b` model across all four versions. The supplied public athlete input was authoritative. Private review expectations and benchmark annotations stayed outside the model messages.

Planner 1 did not receive reference packets. Planners 2–4 received the same packet for a matched case. The reference methods were called by Python rather than native model tool calling. Specialist roles used separate calls to the same model. Planner 4 added coded checks, evaluation and a bounded revision loop.

The shared client saved the original request and raw reply before validation. Native JSON-schema generation and local validation remained separate checks. Request budgeting covered the complete rendered role request with output space reserved; packet size alone was not treated as the complete context cost. Development failures and later amendments remain recorded instead of replacing the original experiment outcomes.

The final comparison was a study of complete workflows. It does not isolate a causal effect of retrieval, specialist reasoning or an evaluator while holding every other execution detail constant.

## Response checks

The response contract supports plans, clarification requests, constraint conflicts and outside-scope replies. A correctly formatted object does not establish that its content meets the athlete's request.

| Status | Meaning |
|---|---|
| Met | The implemented check found the required supporting evidence. |
| Violated | The implemented check found a contradiction or unmet requirement. |
| Unknown | Available information or checking coverage was insufficient. |
| Not applicable | The check does not apply to this case under its recorded policy. |

The automatic goal check was not implemented, and activity-resource recognition covered a limited set of descriptions. These limits prevented complete verification. Actual schedule, commitment, session-count and training-limit errors were also observed. The coded-check measure and full-verification measure remain separate.

## Application state and snapshots

The interface uses fictional development examples. Its saved-example functions are available even when live generation is gated. The application has a separate readiness record; research runs do not automatically change that record.

Saving an edit creates a new plan version and refreshes coded checks. It makes any earlier model review historical. Source requirements and eligibility are resolved by the backend rather than editable table fields. Changing an activity definition can reset that activity's progress, while unchanged compatible activities can retain their reported status.

Progress records top-level session completion. Skipped sessions remain in the total. CSV is a readable export; JSON supports explicit snapshot restoration. Restored assessments retain their historical status, and importing an acceptance flag does not make it a current verification.

The user-facing route is documented in [the prototype guide](prototype_user_guide.md). Application design details are in [the prototype design](prototype_design.md).

## Final evidence and where to find it

| Summary file | Scope |
|---|---|
| `results/step32_classifier_test_summary.json` | Held-out predictions and metrics for the three classifiers. |
| `results/step33_saved_results_comparison_summary.json` | Final 800-outcome planner comparison and exported review evidence. |
| `results/step34_team_review_summary.json` | Supplementary review of 160 replies and its recorded method. |
| `results/step35_statistical_analysis_summary.json` | Matched comparisons, saved analysis tables and source bindings. |
| `results/step36_reproducibility_summary.json` | Separate-environment analysis reproduction and protected-input checks. |
| `results/step37_discussion_summary.json` | Results discussion and improvement priorities. |

These JSON indices identify the corresponding versioned result folders. Preserve the index and its referenced files together. The current Step 35 analysis folder is `results/statistical_analysis/analysis_d5e368e9f92725a9d389/`. The successful Step 36 run is `results/reproducibility/repro_20261117T174153Z_3e7049a7/`. Step 37 saved its report under `results/discussion/discussion_a91e18b52d0a352408d0/`.

Our supplementary review used one assisted review stream. The original two-independent-teammate component was not completed, so agreement was not estimated. Five rating dimensions remain separate; no combined score was introduced.

## Reproduction and further execution

Use [the reproduction guide](reproducibility.md) for the tested entry point. It creates a new environment and fresh kernel, reads copied saved inputs and compares the results under recorded exact and numerical-tolerance rules. Original inputs are hashed before and after.

The successful check covers analysis of saved evidence. It does not claim a full rerun of source preparation, training and live generation. Repeated model generations and deployment performance remain separate experiments.

The Step 30 runner is source-bound to its recorded suite. Later workflow amendments can require their own checks; a changed hash should be investigated rather than removed simply to make the runner continue. The historical 248-pass result is retained in its original scope.

## Related documentation

- [Current results discussion](results_limitations_and_future_improvements.md)
- [Statistical findings](statistical_analysis_findings.md)
- [Figures and code exports](report_figures_and_code_exports.md)
- [Classifier model card](classifier_model_card.md)
- [Reference method contracts](reference_tool_contracts.md)
- [Model integration notes](model_integration.md)

Source-specific data and model terms remain in force. Keep required attribution and usage notices with any redistributed source-derived material.
