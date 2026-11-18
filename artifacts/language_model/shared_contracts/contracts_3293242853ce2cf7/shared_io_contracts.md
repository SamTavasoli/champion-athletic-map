# Shared input and response contract candidates

We preserve the saved public profile schema without widening its study week or age range. Only the `input` object enters a planner's athlete-data content. The wrapper ID and schema version remain in application audit metadata. We reject unknown fields instead of attempting to scrub a private case record.

We retain missing fields, explicit nulls, empty arrays, zeros, false values, conflicting commitments, and exact supplied text. Preparing an input does not accept a study case or establish feasibility. Allowed free text still needs author review for private material.

Our candidate response schema distinguishes a plan, clarification, constraint conflict, and outside-scope response. A plan contains seven dated day records. A non-plan response does not need a weekly schedule. Missing source identifiers remain optional or null, including for the reference-free planner.

Activities carry resources, nullable durations, relationships and optional commitment pointers. Structural validation does not establish meaningful durations, sufficient activity detail, factual accuracy, request fulfillment, source eligibility, or rule compliance. An artificial all-rest week is only a structure check. Existing commitment pointers have a documented shape; resolving them against the public input and assessing coverage remain separate integration work.

We preserve raw response text and parsed values even when validation fails. The application stores its authoritative input beside model output. It never fixes generated text or merges generated profile facts into supplied facts. The saved emoji substitution from Step 24-5 remains a failed exact-echo check.

These candidates have offline software checks. Model execution with this schema, complete prompt budgeting, reference-tool integration, actual case acceptance and operational adoption remain pending. Software fixtures, private annotations and audit bindings are excluded from planner context. The response schema has no source-rule thresholds or private scoring expectations.
