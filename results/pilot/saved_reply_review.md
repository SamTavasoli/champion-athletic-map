# Step 31-12 — Review of the saved pilot replies

We reviewed all eighty saved outcomes against their original athlete inputs and
matching reference packets. We checked the source files against the pilot
summary before reviewing them. We made no new model calls and kept the
original replies, assessments and comparison results unchanged.

The main finding is an integration gap: we had approved basketball drills
available, but this pilot did not retrieve them. None of the sixty packets
delivered to Planners 2–4 contained a drill record, and no drill lookup was
recorded. The lookup path depended on drill IDs linked from the retrieved
general references. Those references did not provide the IDs. The planners
therefore received general guidance, selected rules and optional food facts,
without source-backed drill instructions. The records were not looked up and
then removed to fit the budget.

## Recorded development performance

| Planner | Contract valid | Response completed | Model requests | Median job time |
|---|---:|---:|---:|---:|
| 1 | 10/20 | 20/20 | 20 | 8.5 s |
| 2 | 11/20 | 20/20 | 20 | 15.6 s |
| 3 | 13/20 | 20/20 | 66 | 22.6 s |
| 4 | 13/20 | 15/20 | 141 | 41.3 s |

Contract checks include activity identifiers, relationships and calendar dates;
they are more demanding than checking JSON syntax alone. Timings are from this
machine and this recorded run, include fresh reference preparation where used,
and exclude runtime setup and independent assessment. All twenty jobs per
planner, including failures, remain in the timing totals. This is a development
comparison, not a final quality score or controlled speed benchmark.

## What the replies show

- **Food:** none of the twenty-four food responses gives the requested number.
  Twenty-one repeat the question; three baseline replies honestly say
  "Unknown" without reference access. All six requested numerical facts were
  present in the packets supplied to Planners 2–4. There are no hidden correct
  food answers behind the numerical checker's unknown statuses.
- **Scheduling:** the replies include omitted or moved commitments, changed
  durations, incorrect session counts, and times inconsistent with durations.
  Some replies omit structured timing; that remains an evidence gap. Case 19,
  Planner 1 also repeats calendar dates. These are separate from resource and
  food findings.
- **Activity detail:** all fifty-five plan-type replies use generic session or
  skill titles without a complete source-backed action, setup and participant
  roles. No additional full resource proof can be justified from these replies.
  Case 18, Planners 3 and 4 explicitly require an agility ladder that the
  athlete does not have.
- **Contract and execution errors:** twenty-eight completed replies have real
  identifier, relationship or calendar-date errors. Planner 4 additionally has
  five unfinished workflows: three revision requests exceed the input budget
  and two role replies reach their output limits. Earlier drafts were not used
  as replacements for those failed final outcomes.
- **Scope:** the four replies to the rehabilitation case do not consistently
  enforce the prototype's scope. Some non-plan explanations also claim
  conflicts that the stated facts do not establish. A suitable response type
  alone does not prove that the explanation is correct.

## Where our checks need correction

The exact-question food audit misses ten question-only replies because they
change quotation marks. Three conflict explanations receive supported labels
through broad keyword matching despite weak or inaccurate reasoning. Another
reply correctly names a rest-day conflict, but the matcher leaves it unknown.
Some time-limit findings inherit an activity-link error even when the literal
session totals do not exceed a numerical limit. Resource flags on badly linked
existing games or soccer commitments also need qualification before being
described as shortages for new training. Some space descriptions fall outside
the checker's narrow wording patterns.

We retained these as separate assistant review notes. We did not overwrite the
original checks, convert unresolved findings to passes, or label the notes as
human ratings. Zero fully verified plans remains the original result; it does
not establish that every suggested activity is physically unsuitable.

## Next work

We need to connect approved drill selection to the reference workflow, ensure
that food facts are actually answered, preserve existing commitments, and
correct the identified checking limitations. We should verify the revised
workflow on a small balanced development check before a larger evaluation.
Any future configuration should be recorded separately from this pilot.

This review does not modify the planners or enable live app generation.
Human ratings, accepted final study cases and final scoring remain pending.
The accompanying JSON records findings for each of the eighty outcomes.
