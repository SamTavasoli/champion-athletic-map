# Evaluation protocol — preparation checkpoint

Status: protocol preparation complete; final scoring blocked. This document consolidates saved definitions and artificial component checks. Required approvals, operational integration, the development pilot and final protocol freeze remain open. No study scores or human ratings have been produced.

## 17.1 Purpose

We evaluate two tasks: predicting the exercise dataset's body-part labels, and comparing four basketball-planning workflows. Classifier agreement does not establish anatomical correctness or athlete suitability. Automated planner compliance and human judgments provide different evidence; neither establishes training effectiveness.

## 17.2 Inputs and boundaries

The frozen exercise benchmark is `exercise-benchmark:fb56823695069d9dd15a5280812e8b8faff81550732489cd3b1cc075b532b7df`. Its 2,872 eligible records, groups, labels and partitions come from Step 15. Profile inputs/expectations, adopted rules, approved basketball content, frozen food references and shared response/parsing contracts provide the planner inputs.

The selected preparation checkpoint contains 100 development drafts and 200 protected test candidates, with 0 accepted final profiles. Drafts and provisional categories are not an accepted evaluation population. Recheck intended reference/runtime versions before acceptance.

Private expectations, feasibility examples and scoring masks stay outside planner prompts, retrieval documents and Version 4's internal evaluator. The machine-readable configuration records the exact public component manifests and file hashes; these links identify their definitions:

| Component | Definition | Component digest prefix |
|---|---|---|
| Classifier | [Saved definition](../artifacts/evaluation/classifier_metrics_db3e5f3df78a126c/classifier_metric_config.json) | `db3e5f3df78a126c` |
| Planner | [Saved definition](../artifacts/evaluation/planner_assessment_9bc2c716c90475ff/planner_assessment_config.json) | `9bc2c716c90475ff` |
| Human | [Saved definition](../artifacts/evaluation/human_review_9e637c0f3932c371/human_review_rubric.md) | `9e637c0f3932c371` |
| Evidence | [Saved definition](../artifacts/evaluation/evidence_accounting_c546a28e0ec3a34b/evidence_accounting_policy.md) | `c546a28e0ec3a34b` |
| Runtime | [Saved definition](../artifacts/evaluation/runtime_accounting_12404b69651ab1bc/runtime_accounting_policy.md) | `12404b69651ab1bc` |
| Paired | [Saved definition](../artifacts/evaluation/paired_comparison_acf00a1a848823fb/paired_comparison_policy.md) | `acf00a1a848823fb` |

## 17.3 Classifier metrics

Macro-F1 is primary, using all frozen classes in saved order and `zero_division=0`. Report accuracy, per-class precision/recall/F1, record and distinct-group support, and confusion counts with actual rows and predicted columns. Accompany absent-class zeros with support/definition flags; an empty evaluation is unavailable.

The fixed class order is: abdominals, abductors, adductors, biceps, calves, chest, forearms, glutes, hamstrings, lats, lower back, middle back, quadriceps, shoulders, traps, triceps. All three models—training-majority baseline, TF-IDF logistic regression and neural classifier—use the same benchmark. Fit the baseline and learned transformations on training data. Select configurations by validation macro-F1; final test scoring waits for selected checkpoints and Step 32. The complete manifest/prediction join must not silently drop records.

## 17.4 Primary planner measure

Automated feasible-plan success is successful cases divided by all 150 accepted feasible final profiles per version. These are planned counts. Success requires the designated returned response, shared parsing, the required plan/activity content, request completeness and every required applicable check met. Valid activities in an incomplete plan do not suffice.

Terminal execution failure, missing/malformed output, inappropriate refusal and required semantic unknowns prevent success. Unstarted jobs and failed/unrun external assessments remain incomplete work. Keep the fixed denominator and resolve incompleteness before describing a completed comparison.

## 17.5 Check results and coverage

Preserve rule/checker versions, applicability, required/advisory status, observed values/units, evidence and errors. Results are met, violated, unknown or justified not applicable. Missing information cannot become non-applicability. Required unknowns prevent success; advisory findings are reported separately according to accepted essentiality.

Preserve activity instances and aggregate at the parent rule: an established violation dominates; otherwise necessary unknowns prevent met. Checker errors or missing expected assessments keep evaluation incomplete. Conclusive coverage is `(met + violated) / (met + violated + unknown)` over expected applicable parent checks. Separate required/advisory coverage and justified non-applicability. Empty denominators stay unavailable; coverage is not a pass rate.

## 17.6 Other outcomes and denominators

Per version, the planned population is 150 feasible, 20 missing-information, 15 conflicting-constraint and 15 outside-scope cases: 200 cases, or 800 jobs across four versions. Each age 13–17 contributes 30 feasible and 4/3/3 challenge cases. Show actual age/scenario denominators. Do not combine categories into a headline score that rewards refusing feasible requests.

| Measure | Population and reporting |
|---|---|
| Plan completion | Complete plans among all 150 feasible cases per version |
| Constraint outcomes | Met, violated, unknown and not applicable by rule and scenario; retain counts |
| Check coverage | Conclusive outcomes among expected applicable parent checks |
| Response-type match | Declared response type versus expected category, with the assessed case count |
| Missing-information handling | All 20 missing-information cases per version |
| Conflict handling | All 15 conflict cases per version |
| Scope handling | All 15 outside-scope cases per version |
| Execution and parsing reliability | All 200 scheduled cases per version |
| Evidence findings | Source validity, claim support and attribution; identify assessed sample and denominator |
| Runtime and resource use | Complete workflow observations, including failed attempts; identify measured/missing counts |

A matching response-type label is structural evidence; it does not establish that a clarification or conflict explanation addresses the essential issue.

## 17.7 Evidence and retrieval

Keep ID resolution, claim support and attribution separate: resolvable distinct IDs/supplied distinct IDs; supported cited claims/cited claims assessed; and source-dependent claims with usable attribution/source-dependent claims reviewed. Identify inventories, assessment scope and denominators. Empty or unfinished measures stay unavailable. A valid ID can fail to support its claim; an uncited fact can still be checked for accuracy.

Review relevant ages, units, quantities, conditions and qualifications. Distinguish contradiction, insufficient support, missing qualifications, semantic unknowns and checker failures. Inventory claims actually present; omitted requested answers are completeness issues. Authored scheduling choices are not source prescriptions.

Step 23 separately evaluates Hit@k and Recall@k at 1, 3 and 5, MRR@5, and accepted complete evidence bundles. Select using development Recall@5, then MRR@5, then the simpler lexical method. Report unsupported questions and evidence-adequacy failures separately. Retrieval scores do not substitute for planner or claim assessment.

## 17.8 Human rubric

Rate response suitability, profile fit, practicality/completeness, evidence accuracy and clarity separately from 0 to 2 using the saved anchors. Judge completeness relative to the request: a useful clarification need not invent a plan. Explain important problems and cite supporting evidence when disputing factual claims. Do not create a combined quality score or a new passing threshold after seeing results.

## 17.9 Failed outputs and rating states

Each entry is rated (0/1/2), justified not applicable (no score), or missing (unfinished). Only evidence accuracy permits N/A when no substantive claims exist, with a reason. An omitted requested food fact remains a completeness problem.

For executed jobs returning no assessable response, the four non-evidence dimensions receive zero under the rubric. Review malformed but readable text as received. A clearly written inappropriate refusal can retain a good clarity rating while failing suitability. Unstarted jobs and missing reviewer work stay pending; do not impute scores or copy another reviewer's opinion.

## 17.10 Human sample and procedure

Before viewing outputs, select 40 accepted profiles: 25 feasible and five in each challenge category. Each age contributes five feasible and one per challenge category. Use stable ordering and recorded seed 42 within strata; retain family information. Include all four outcomes for 160 responses, each independently rated by two teammates across five dimensions. No IDs or assignments are selected here.

Randomize presentation reproducibly. Packets contain public profiles/requests, unchanged returned text/citations, rubric and neutral adopted references. Hide version labels, traces, internal findings, automated scores, timing, private category labels and feasibility examples. Practice on development examples; lock independent initial ratings before discussion. This is team review, not external clinical validation. Blinding is incomplete, and the challenge-enriched sample is not representative of all 800 jobs.

## 17.11 Agreement and paired comparisons

Per dimension, report jointly numeric pairs, exact agreement and linearly weighted Cohen's kappa with fixed order 0/1/2. Keep N/A outside the ordinal scale. Report N/A/missing counts, their overlap and each reviewer's distribution. Undefined kappa stays unavailable with its reason; preserve original ratings and later consensus separately.

Compare V2−V1, V3−V2, V4−V3 and V4−V1 on matched profiles. Count improved, worsened and unchanged pairs; report success differences in percentage points. Pending partners remain in the declared roster. Point estimates weight profiles equally; family IDs support later resampling.

Step 31 will finalize 2,000 paired group-bootstrap resamples, seed 42, with individual 95% percentile intervals. Resample profile families for planners and exercise groups for classifiers, preserving matched outcomes and record/profile estimands. This is planned, not executed. Intervals describe constructed-benchmark sensitivity, not athlete outcomes or training-seed variability.

## 17.12 Independent final scoring

Use common public inputs, base model and generation settings while documenting intended workflow differences. Independently score each frozen workflow's designated saved response before user edits. Version 4's internal acceptance flag does not set its research result. If its frozen cap policy returns the last checked candidate, assess that designated candidate under the same rules. Fatal errors remain failures; diagnostic drafts do not silently replace the response.

Optional source IDs remain optional formatting; assess attribution separately. Preserve failures, avoid undeclared best-of selection and document result-driven changes as a new experiment.

## 17.13 Runtime and resources

Record complete workflow time, including retrieval/lookups, orchestration, failed attempts, retries and revisions. Keep startup/loading observations separate and do not sum overlapping stages. Distinguish logical calls, transport attempts, roles and revision phases. Count tokens once at attempt level. Preserve unavailable measurements and report measured/missing counts. Returned responses are not automatically successful plans.

Record device, cache and measurement basis. Model-transport cost estimates need currency and a recorded basis; they are not billed spend or full-workflow costs. Keep currencies separate. Operational telemetry and timeout/retry/revision limits remain pending the development pilot.

## 17.14 Validation, saved status and remaining gates

The six components contain 679 passed checks across 228 component scenarios. They test artificial arithmetic, supplied states and input rejection. They do not establish accepted-case readiness, source-dependent validator correctness or end-to-end runtime integration. Tests below, equal to and above an adopted threshold remain pending until adopted rules and validators exist.

Sample and rating templates remain empty. Consolidated configuration has no accepted rule/profile/expectation/parser version, no assigned reviewers and no frozen operational limits. Final planner and classifier readiness remain false. Complete the following work before its stated use; this register records pending work rather than granting approval.

| Dependency | Status | Needed before |
|---|---|---|
| Adopted planning rules and exact rule versions | Pending | Reference-dependent case acceptance, operational checks and final planner scoring |
| Approved basketball activities and source support | Pending | Feasibility approval, reference-dependent checks and final planner scoring |
| Food lookup routing, source versions, units and factual checks | Pending | Food-case expectations and final factual assessment |
| Accepted profiles, scenario categories and adopted families | Pending | Final population freeze, human sample selection and planner comparisons |
| Adopted private expectations, check masks and feasibility evidence | Pending | Final case-level automated scoring |
| Shared output contract and verified parser version | Pending | Operational response interpretation and final planner scoring |
| Source-dependent validators and adopted-threshold boundary fixtures | Pending | Below/equal/above adopted-threshold tests and operational scoring readiness |
| Human calibration, sampling, anonymized packets and review assignments | Pending | Independent human rating and agreement reporting |
| Workflow timing, call/attempt logging and available resource telemetry | Pending | Actual runtime/resource reporting |
| Independent score ledger, workflow aliases and designated-response hashes | Pending | Research scoring and matched planner comparisons |
| Development integration fixtures and end-to-end scorer validation | Pending | Operational evaluation harness readiness |
| Step 31 pilot, bootstrap procedure and final protocol/settings freeze | Pending | Held-out planner execution, uncertainty intervals and final evaluation |
| Selected classifier models and complete held-out predictions | Pending | Step 32 final classifier scoring |

Step 31's development pilot finalizes operational settings and the exact protocol version before held-out planner evaluation. Add actual scores, ratings, agreement, intervals and runtime findings only after their experiments and reviews have run.
