# Read-only reference tools

ReferenceTools(root, contracts_directory) reads the frozen resources through validated Python methods.
Native model tool calling is not enabled. No lookup refreshes publisher pages or approves source records.

| Method | Arguments | Behavior |
|---|---|---|
| search_references | query, filters=None | Nonblank query; no nonempty filters. Frozen semantic search returns up to five complete reference units with required companions. Ranking alone does not establish answerability. |
| get_drill | drill_id | Approved records return found; held records return not_eligible; aliases resolve to their approved record; unknown IDs return not_found. |
| get_exercise | catalog_id | Known development exercise records return not_eligible; unknown IDs return not_found. No new classification or exercise approval is performed. |
| get_planning_rules | age=None, school_grade=None | Age 13–17 and grade 1–12 when supplied. The active release returns adopted definitions and scope information. Definition availability does not establish compliance or execute rule checks. |
| lookup_food | food_id=None, search_text=None, grams=None, portion_id=None, multiplier=None | Choose ID or description search. Ambiguity requires an exact food selection. Use positive finite grams or a recorded food-specific portion with an explicit multiplier; default is 100 g. |

Results contain request_id, status, data, issues, source_refs and data_version.
Food facts preserve source nutrient IDs, missing values, and recorded zeros; calculations do not prescribe dietary intake.
Whole reference units may be omitted for packet size, with omissions recorded; their required context is not sliced.
Version 1 cannot receive lookup results. Versions 2–4 share the same packet for each matched case.
The original lookup example retains its historical pending statuses. The current approved release is recorded separately.
Gym exercise instructions remain unavailable for planning. Approval does not certify individual athlete suitability or a distinct basketball-drill total.
The saved lookup example and Step 14 calculation evidence remain distinct from future planner evaluations.
