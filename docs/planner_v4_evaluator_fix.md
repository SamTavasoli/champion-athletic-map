# Step 28 evaluator prompt correction

The original six evaluator replies completed normally and met their schema but
all reported assessment_complete=false. The prompt did not clearly distinguish
completing a review from approving the candidate. We clarify that a completed
review may report missing information, contradictions and unresolved findings.
The boolean remains a model output; false is still a failed required assessment.
We do not coerce the flag, weaken acceptance or change schemas/model settings.

This targeted development continuation verifies and reuses the six completed
original Step 28 specialist drafts. It does not rerun the 21 drafting calls or
reuse Step 27 outputs. Original prompts, configurations, requests, raw replies,
failed outcomes and summary remain unchanged. The clarified prompt, continuation
configuration, source bindings, incremental model costs and new results are
saved separately. New stable job IDs distinguish corrected evaluations and
bounded revisions from the six failed evaluations. Reruns reuse their saved
outputs, including failures; there is no hidden retry or fallback.

The original acceptance policy, all 41 coded checks, evaluator schema, complete
source packets, specialist notes, output limits, context checks and two-revision
limit remain unchanged. New executions can still fail or remain unaccepted.
Incomplete source bindings or saved draft disagreement block the continuation
before generation. Every reused role request/result/raw reply is checked.

CorrectedEvaluatedPlanner provides the same corrected prompt for future fresh
jobs, with their own complete drafting calls and costs. ResumedEvaluatedPlanner
is reserved for this explicitly linked continuation. The active development
pointer identifies the correction configuration and result summary. This is
development evidence, not an independent final benchmark run or proof of safety.
Independent plan-quality scores, accepted final study profiles and operational
readiness remain pending.
