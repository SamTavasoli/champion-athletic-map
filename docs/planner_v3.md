# Planner Version 3

We use SpecialistPlanner(root).generate(public_record, reference_packet, call_id).
The reusable draft method also supports separately recorded Version 4 jobs with
the same initial drafting procedure. Earlier Version 3 outputs are not reused
as Version 4 drafting work.

Training and participation/recovery specialists run sequentially. An explicit
nonblank public food_question adds a required food-facts specialist even when
the lookup is ambiguous or unavailable. Each specialist receives fresh messages
containing the same original public input and complete saved reference packet,
the unchanged shared task brief, its role instructions and the note schema.
Specialists receive no other specialist notes. The coordinator receives those
original inputs plus all required valid contributions, with no reviewer verdict.

All roles use the same frozen Llama 3.1:8b model via the existing client. Only
specialist output limits change to 512 tokens and the note schema; coordinator
settings and final schema remain shared, with 2048 output tokens. Temperature,
seed, context, model digest, native tokenizer, source and packet bindings remain
fixed. Complete actual backend-rendered prompts are counted with each stage's
output reserved and the existing margin. No substantive context is shortened.

Notes contain contribution_status, recommendations, evidence_refs,
qualifications, unresolved_issues, questions and rationale. Limited information
or outside-scope contributions are structurally usable; they are not verified
truth. Raw note text is retained. Application metadata identifies the role,
public-input hash, packet ID, schema version, request hash and stage status.
The model does not manufacture application identifiers. Source facts and model
suggestions remain distinct.

The intended workflow uses three logical calls without food, four with food.
These six matched examples activate food for the first three, so the maximum
is 21 new generations. A failed mandatory contribution stops that profile and
later stages are not started. A valid limited contribution proceeds. Failed
coordinator parsing remains a recorded final output. An unresolved transport
outcome stops the batch. There are no retries, repairs, fallback planners,
post-generation checks, evaluator calls or coordinator revisions in Version 3.
Stable call IDs reuse saved replies, including failures, on reruns.

We verify and reuse the exact six Step 26 packets and their saved preparation
records. No query encoding, reference search, lookup or classifier prediction
runs in Step 27. Current source/configuration hashes are checked. Baseline
outputs, source modules and reference packets remain unchanged. Only selected
public development profiles are decoded from the unified dataset; private
evaluation fields and protected exercise payloads are never passed to roles.

Requests, raw backend replies, exact prompts, budgets, note parsing, role order,
not-started stages, transport attempts, timing and final outcomes are preserved.
The summary distinguishes role success from final-response completion and format.
Format counts are not plan-quality scores. Independent quality scoring, accepted
final study profiles and operational readiness remain pending. Version 3 adds
both specialist organization and computation; later comparisons must consider
the extra calls and elapsed time, not attribute any change solely to roles.
