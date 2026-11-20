# Planner Version 1

We use LLMOnlyPlanner(root).generate(public_record, call_id) from
src/champion_athletic_map/planners/llm_only.py. Each job delegates once to the
shared Step 24 adapter with planner_version=1. The shared instructions live in
docs/prompts/shared_planner_task_v1.md and are intended for reuse by the other
final-response planners. Model settings, native output shape, token counting,
strict parsing and unresolved-call handling come from the shared integration.

We read six unchanged fictional development drafts from the team's unified CSV
in data/unified/v1. Only the validated public input object enters the user
message. Profile IDs, source metadata and coverage labels stay in local records.
Only matching development-profile payloads are decoded. Exercise text, labels,
protected rows and final planner cases are not used by this workflow.

There are no generation-time reference packets, lookups, classifier predictions,
specialists or evaluator calls. Each response starts with fresh messages. No
automatic retries, continuation or repair generations are allowed. A matching
call ID reuses its saved response. An uncertain outcome stops the batch.

The shared adapter preserves requests and raw replies under results/integration/
model_calls. The development log records every invocation, including cached
reuse and transport counts. Failed responses remain outcomes; the runner does
not select a replacement. The displayed calendar is a returned example, not an
independently approved training recommendation.

Response-format checks are separate from plan quality. Independent scores remain
unavailable until the scorer is implemented and verified. The six examples are
development drafts, not accepted final study cases. Accepted study profiles and
operational generation readiness remain unestablished. Frozen classifier models,
splits, source files, retrieval benchmarks and the unified CSV remain unchanged.

Version 2 will use the same public profiles and shared final-task brief while
adding the matched reference packet. Final model/protocol limits remain Step 31;
the final planner comparison remains Step 33.
