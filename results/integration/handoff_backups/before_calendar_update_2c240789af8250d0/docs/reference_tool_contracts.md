# Read-only reference tools

ReferenceTools(root, contracts_directory) reads the frozen resources through validated Python methods.
Native model tool calling is not enabled. No lookup refreshes publisher pages or approves source records.

| Method | Arguments | Behavior |
|---|---|---|
| search_references | query, filters=None | Nonblank query; no nonempty filters. Frozen semantic search returns up to five complete reference units with required companions. Ranking alone does not establish answerability. |
| get_drill | drill_id | Known pending record returns not_eligible; unknown ID returns not_found. |
| get_exercise | catalog_id | Same eligibility boundary for the selected development exercise export; no new classification or label approval. |
| get_planning_rules | age=None, school_grade=None | Age 13–17 and grade 1–12 when supplied. The current unadopted register returns unavailable. |
| lookup_food | food_id=None, search_text=None, grams=None, portion_id=None, multiplier=None | Choose ID or description search. Ambiguity requires an exact food selection. Use positive finite grams or a recorded food-specific portion with an explicit multiplier; default is 100 g. |

Results contain request_id, status, data, issues, source_refs and data_version.
Food facts preserve source nutrient IDs, missing values, and recorded zeros; calculations do not prescribe dietary intake.
Whole reference units may be omitted for packet size, with omissions recorded; their required context is not sliced.
Version 1 cannot receive lookup results. Versions 2–4 share the same packet for each matched case.
The saved lookup example and Step 14 calculation evidence remain distinct from future planner evaluations.
