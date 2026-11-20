# Step 37 — Results, Limitations, and Future Improvements

We built Champions Athletic Map as a local prototype for weekly teen basketball planning. Our work includes an exercise-text classifier, reference search, recorded food lookups, four planning workflows and an interface for viewing, editing and tracking saved plans. We evaluated these components separately because success in one part does not establish that the complete planner is reliable.

## Main findings

Our exercise classifier completed its evaluation and performed better than its majority baseline. L5 logistic regression had the highest observed Macro-F1 and accuracy among the three tested classifiers. Our four planning workflows produced mixed results: adding references, specialist roles and revisions did not give us a consistent improvement across the recorded measures.

## Exercise classification

We evaluated the saved predictions for 438 test records in 385 exercise groups and 16 categories. Macro-F1 gives each category equal weight, while accuracy measures the proportion of records classified correctly.

| Classifier | Macro-F1 | Accuracy |
|---|---:|---:|
| Majority baseline | 0.0234 | 23.06% |
| L5 logistic regression | 0.6143 | 73.29% |
| N3 neural classifier | 0.5288 | 67.81% |

L5 remains our validation-selected classifier. These results support its use for assigning exercise categories from text. A body-part label alone does not tell us whether an exercise is suitable for a basketball goal, an athlete's limitations or the available equipment. Gym exercises also remain unavailable to the planner under our current resource decisions.

## Four planning workflows

We used the same local llama3.1:8b model across 200 fictional profiles, with 800 saved outcomes. The final comparison used 2,636 cumulative model submissions, including specialist, evaluator and revision work. The comparison concerns the complete workflows rather than different underlying language models.

| Planner | Valid format | Workflow completed | Valid completed plans | Coded checks passed | Full verification | Median time |
|---|---:|---:|---:|---:|---:|---:|
| 1 — Language model alone | 75/200 | 199/200 | 45/150 | 0/150 | 0/150 | 10.57 s |
| 2 — With references | 62/200 | 186/200 | 40/150 | 0/150 | 0/150 | 18.41 s |
| 3 — With specialist roles | 67/200 | 199/200 | 39/150 | 0/150 | 0/150 | 26.98 s |
| 4 — With checks and revisions | 69/200 | 198/200 | 47/150 | 0/150 | 0/150 | 62.10 s |

Format and workflow completion use all 200 profiles per planner. Plan and verification counts use the 150 feasible requests per planner. Timing includes all terminal outcomes, including failures. A valid completed plan means that a completed reply has the required structure and declares a plan; it does not mean the calendar satisfies every requirement.

The baseline returned the most correctly formatted responses overall and had the lowest observed time. Planner 4 returned slightly more valid completed plans for feasible requests, but took much longer. Its internal checks accepted none of the final outcomes. We therefore cannot select a generally superior planner from these results.

No planner achieved full verification. The automatic goal check was not implemented, and resource checking covered only a limited range of activity descriptions. Our saved assessments also found actual errors, including changed or missing existing commitments, incorrect session counts and exceeded extra-training limits. Both the missing checks and the observed output errors matter. An unknown result stays unresolved; it does not establish that the plan is safe, unsafe or useless.

The challenge cases exposed another weakness. None of the workflows successfully handled the 20 missing-information cases or the 15 conflicting-constraint cases under the recorded checks. Outside-scope handling varied across workflows. This shows that asking for clarification and recognizing a request that cannot be fulfilled need more reliable handling.

## Reference search and food facts

The saved reference-search evaluation contained 30 held-out questions in 15 families: 20 supported, two partly supported and eight unsupported. Mean Recall@5 was 1.0000 and MRR@5 was 0.9792 over the 24 questions with nonempty relevant-reference sets. Complete ranked evidence-set coverage was 1.0000 over 20 supported questions.

These scores show that relevant references were often ranked near the top in the saved retrieval task. All 30 questions returned candidates, including unsupported questions. Returning a reference does not prove that the question is answerable, that the system should answer it or that the planner used the correct evidence. The saved ranking task is also distinct from the planner's merged reference packet. Earlier planned answerability counts differed from the final source labels; we kept the original labels and ranking denominators visible.

Our lookup tools could return recorded food values, but reliable lookup and reliable generated answers are separate parts of the workflow. We need to keep verified amounts, units and source identifiers attached to the displayed answer. We do not treat a successful food lookup as proof that every requested food fact appeared correctly in a planner reply.

## Team review and reproducibility

Our supplementary team review covered 160 replies from 40 selected profiles, with 800 entries across five separate dimensions. It used one assisted review rather than two independent teammate rating sets. Reviewer agreement was therefore not estimated. The sample included 25 feasible profiles and 15 challenge profiles, so its pooled ratings should not be treated as scores for the entire benchmark.

Step 36 reproduced the saved analysis in a separate environment and a fresh kernel. All 37 output files passed the declared comparison checks, and the protected originals remained unchanged. This supports reproduction of the saved-results analysis. It does not measure variation from retraining or another round of language-model generation.

## Limitations

- We used constructed fictional profiles. We did not measure training outcomes with real athletes, parents or coaches.
- The final planner comparison used one local language model and one recorded outcome per profile and workflow. It does not compare model families or estimate repeated-generation variability.
- Our evaluation has incomplete goal verification and limited resource coverage. The coded-check and full-verification measures remain separate, and neither produced a passing feasible plan in this run.
- The review was a single assisted assessment. Independent ratings, reviewer agreement and coaching validation remain uncollected.
- Although feasible cases had 150 adopted family IDs, they came from only three original wording patterns. This limits how broadly we can interpret performance on different requests.
- The 2,000 paired group resamples describe the fixed saved outputs. Constant zero-success intervals do not establish equal planner quality or zero uncertainty outside this benchmark.
- Some numerical conventions for planner resampling were clarified during analysis after the outputs were available. We recorded that timing rather than claim those details were frozen earlier.
- Observed runtime describes our local setup. We have not established deployment costs or performance on other hardware.

## Future improvements

| Priority | Improvement | Problem it addresses |
|---|---|---|
| 1 | Build calendars with explicit scheduling logic, preserving existing commitments before adding sessions. | Missing practices, incorrect dates, overlaps and session-count errors. |
| 2 | Select approved drill identifiers and validate their equipment, space and participant requirements. | Activities whose resource requirements cannot be verified. |
| 3 | Display food amounts, units and sources directly from verified lookup results. | Omitted or altered factual answers. |
| 4 | Complete goal and resource checks, keeping unknown results separate from violations. | Incomplete verification and unclear failure reasons. |
| 5 | Simplify prompts and response structures, then compare any model or workflow change in a new experiment. | Format errors, long revision cycles and request-size limits. |
| 6 | Collect separate team ratings and qualified basketball feedback, then test broader cases. | Limited review independence and uncertain practical suitability. |

We would use the language model to describe and explain a schedule while program logic protects dates, commitments and numerical limits. These are proposed changes, not features demonstrated by the present results. Because the final cases have now been examined, improvements based on them should be developed separately and evaluated on fresh cases. Our original final outcomes and scores stay unchanged.

## Project conclusion

We completed an evaluated prototype and a reproducible saved-results analysis. The exercise classifier performed substantially better than its majority baseline, and reference search returned relevant material in its ranking task. The planning comparison showed that more elaborate workflows did not consistently solve the scheduling and response problems. Reliable end-to-end basketball planning remains a development goal; the current results do not establish readiness for independent use with athletes.

## Saved sources

- Step 35 analysis: results/statistical_analysis/analysis_d5e368e9f92725a9d389
- Planner and request results: planner_summary.csv, parent_check_summary.csv and failure_analysis.csv in that analysis folder.
- Classifier, retrieval and timing: classifier_summary.json, retrieval_analysis_status.json and runtime_resource_summary.csv in that analysis folder.
- Review and method: team_rating_distributions.csv, team_rating_comparisons.csv and analysis_method_note.json in that analysis folder.
- Step 36 verification: results/reproducibility/repro_20261117T174153Z_3e7049a7/verification_report.md
