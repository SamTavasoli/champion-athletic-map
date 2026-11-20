# Step 28 saved-findings review and future workflow correction

We reviewed remaining_findings.json without making model requests. The original
outcomes remain unchanged: five valid returned responses, zero internal passes
and one execution failure during the second revision. These are development
findings, not independent plan-quality scores.

Real planner errors remain. Example 1 schedules three sessions when two were
requested. Examples 2 and 3 omit supplied school travel; Example 2 also omits
activity timing. Example 4 returns a conflict instead of asking for the missing
participant count and introduces unsupported injury uncertainty. Example 5
places 45 minutes inside a 20-minute window and omits the existing practice and
game. Examples 1–3 do not answer the supplied food questions.

The evaluator also makes mistakes. It rejects the ordinary basketball goals in
Examples 1–3 without a project requirement for narrower goals. Example 6 correctly
refuses diagnosis/rehabilitation, but the evaluator treats the excluded request
itself as a defect in that correct refusal. Example 5 also confuses grade-based
source applicability and missing schedule coverage. We clarify candidate-focused
evaluation; we do not discard old evaluator findings or change old acceptance.

Some blockers are evidence gaps: the public schema does not attest complete
classified sports coverage, and free-form activity requirements are not verified
catalog records. A model cannot establish those facts by rewriting its answer.
Required unknowns remain blockers under the adopted policy. This update does
not weaken that policy or imply that every existing plan should pass.

The failed second revision used 6013 input tokens against a 5888-token allowance,
125 too many. The future workflow uses a lossless representation of the candidate
calendar with shared column names and exact repeated rest text stored once.
All original candidate values can be reconstructed. Original public facts,
reference packet, specialist notes, coded findings and source qualifications
are retained. Actual complete backend-rendered budgets remain enforced; arbitrary
future requests may still overflow. No context size or output limit is changed.

CandidateFocusedEvaluatedPlanner is a separate future workflow candidate. Fresh
jobs perform their own original specialist drafting, corrected evaluations and
up to two revisions. The old sources, prompts, configs, accepted-resource release,
datasets, saved results and active development pointer are preserved. Installation
makes no model calls and does not replay the six cases or alter their results.
The new candidate is saved for a documented pilot before final protocol freezing.
Independent scoring, accepted final study profiles and operational readiness
remain pending.
