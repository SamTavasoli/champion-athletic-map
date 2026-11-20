# Planner Version 2

We use RAGPlanner(root).generate(public_record, reference_packet, call_id).
The model, shared task brief, final response schema, generation settings and six
public fictional development drafts are unchanged from Version 1. The only
additional model input is the matched reference packet. No specialist, reviewer,
classifier prediction, model query rewrite, repair or continuation is used.

We read the four unchanged release files in data/unified/v1. Current verified
resource approvals govern eligibility; historical export labels do not undo
those approvals. Only the permitted public profiles, eleven indexed reference
records, approved drill/rule records and prepared food rows are decoded.
Protected exercise payloads and final study cases are not decoded or scored.

We prepare two short public queries per profile and batch their offline MiniLM
encoding in one worker for these six profiles. The existing frozen semantic
index returns at most five units per query. We merge the two lists in fixed
round-robin order by reference-unit ID, without comparing cross-query scores.
The corpus and embeddings are unchanged. Full source companions stay attached.

Each profile gets one age/grade rule lookup. We select at most two complete
external-guidance bundles, preserving population qualifications. Project/user
constraint templates, evaluation procedures and reviewer information are not
model evidence. We reserve a whole retrieved source unit before filling the
rule allowance, then add other whole units in merged order. This is bounded
reference coverage, not execution of all 29 adopted rule definitions.

We use at most two explicit food requests. Supported literal quoted-food/gram
questions and public JSON arguments retain their supplied quantities; ambiguous
or unsupported wording is not guessed. Food outputs are recorded facts only.
Catalog lookups use IDs explicitly linked from delivered results, at most ten
combined. The current eleven indexed units contain no drill/exercise ID links,
so this run can make zero catalog lookups. The 136 available approved resource
variants are not newly indexed or automatically supplied to the model. Gym
exercise planning remains unavailable.

The exact canonical payload has a 2200-token allowance (or the shared configured
allowance) measured with the native model tokenizer. Whole omissions and full
tool/ranking records are saved separately. Required food context or an entire
retrieval context that cannot fit blocks preparation. The shared adapter still
counts the complete actual backend-rendered prompt with the response reserved;
packet fit alone does not establish complete-request fit. No text is truncated.

We save packets by public-input and source-configuration hashes for unchanged
reuse in Versions 2–4. Operational IDs, times, rankings and cache events stay
outside the packet content hash. Saved traces also carry a content hash. A
rerun validates sources and reuses complete saved packets and responses.
Technical preparation failures stop before generation; uncertain generation
outcomes stop the batch. Completed malformed replies remain recorded outcomes.
There is one logical generation per profile and no automatic retries.

Version 1 source/configuration/results stay unchanged. We save Version 2
configuration, packet preparation details, requests, raw replies, format checks,
transport/query/lookup counts and development records separately. The displayed
format counts and calendar are not quality scores or approved recommendations.
Independent scoring, final workflow capacity and operational readiness remain
pending; these six development drafts are not accepted final study profiles.
