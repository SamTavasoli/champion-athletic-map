# Step 31-11 — Development pilot comparison

Cases: 20. Outcomes: 80. Model submissions during the pilot: 247.
New model calls in this comparison: 0.

| Planner | Format valid | Response completed | Plans fully verified |
|---|---:|---:|---:|
| 1 — Language model alone | 10/20 | 20/20 | 0/16 |
| 2 — With references | 11/20 | 20/20 | 0/16 |
| 3 — With specialist roles | 13/20 | 20/20 | 0/15 |
| 4 — With checks and revisions | 13/20 | 15/20 | 0/8 |

- This is a comparison of provisional development cases, not the final study population.
- Format and completion counts describe response structure and execution; they do not establish plan quality.
- The last table column uses all replies labelled as plans, including those with invalid structure, as its denominator.
- A plan is fully verified here only when none of the required independent checks is violated or unknown. This is not a safety certification.
- Supported clarification, conflict and outside-scope replies are counted separately from training plans.
- Unknown means unverified. Resource checks cover only the separately reviewed activity variants, and invalid activity structure can also prevent verification.
- Food wording that the checker cannot interpret remains unknown. Missing or question-only replies remain violations of answer completeness.
- Some rule checks repeat underlying schedule findings; their counts must not be added as separate errors.
- This cell summarizes the assessments embedded in the Step 31-10 summary. It does not reopen raw model replies or rerun the checks.
- Human review, final scoring and any choice of an overall winner remain pending.

Source summary SHA-256: `498e31c961be00e29b5f1c624a316422f1fa539dc61723c54173c66bfbbc4af8`.

## Selected independent checks

The four status counts sum to 20 for each planner. Applicable excludes only not applicable outcomes; it includes unverified checks.

| Planner | Check | Met | Violated | Unverified | Not applicable | Applicable |
|---|---|---:|---:|---:|---:|---:|
| 1 | Existing commitments | 1 | 5 | 12 | 2 | 18 |
| 1 | Requested session count | 3 | 3 | 7 | 7 | 13 |
| 1 | Availability and overlaps | 4 | 1 | 13 | 2 | 18 |
| 1 | Additional training limits | 4 | 2 | 12 | 2 | 18 |
| 1 | Resource evidence | 0 | 0 | 18 | 2 | 18 |
| 1 | Food answer completeness | 0 | 3 | 3 | 14 | 6 |
| 1 | Food numeric correctness | 0 | 0 | 6 | 14 | 6 |
| 1 | Reason for response type | 7 | 2 | 11 | 0 | 20 |
| 2 | Existing commitments | 1 | 6 | 12 | 1 | 19 |
| 2 | Requested session count | 5 | 2 | 6 | 7 | 13 |
| 2 | Availability and overlaps | 3 | 1 | 15 | 1 | 19 |
| 2 | Additional training limits | 4 | 3 | 12 | 1 | 19 |
| 2 | Resource evidence | 0 | 0 | 19 | 1 | 19 |
| 2 | Food answer completeness | 0 | 4 | 2 | 14 | 6 |
| 2 | Food numeric correctness | 0 | 0 | 6 | 14 | 6 |
| 2 | Reason for response type | 7 | 3 | 10 | 0 | 20 |
| 3 | Existing commitments | 1 | 6 | 9 | 4 | 16 |
| 3 | Requested session count | 5 | 3 | 5 | 7 | 13 |
| 3 | Availability and overlaps | 2 | 0 | 14 | 4 | 16 |
| 3 | Additional training limits | 5 | 3 | 8 | 4 | 16 |
| 3 | Resource evidence | 0 | 0 | 16 | 4 | 16 |
| 3 | Food answer completeness | 0 | 2 | 4 | 14 | 6 |
| 3 | Food numeric correctness | 0 | 0 | 6 | 14 | 6 |
| 3 | Reason for response type | 11 | 2 | 7 | 0 | 20 |
| 4 | Existing commitments | 1 | 4 | 11 | 4 | 16 |
| 4 | Requested session count | 4 | 1 | 7 | 8 | 12 |
| 4 | Availability and overlaps | 2 | 0 | 14 | 4 | 16 |
| 4 | Additional training limits | 5 | 1 | 10 | 4 | 16 |
| 4 | Resource evidence | 0 | 0 | 16 | 4 | 16 |
| 4 | Food answer completeness | 0 | 2 | 4 | 14 | 6 |
| 4 | Food numeric correctness | 0 | 0 | 6 | 14 | 6 |
| 4 | Reason for response type | 9 | 4 | 7 | 0 | 20 |

## Supported responses that were not plans

| Planner | Supported clarification, conflict or outside-scope replies |
|---|---:|
| 1 | 2/20 |
| 2 | 1/20 |
| 3 | 4/20 |
| 4 | 4/20 |

## Remaining review

We still need to review the meaning and usefulness of the saved responses, unresolved resource and food evidence, and failed executions. No human ratings or final scores are created here. The JSON comparison lists the saved findings for each outcome.
