# Our controlled examples

Fixture version: `step30-authored-fixtures-1`.

We use small fictional profiles, hand-written calendars and scripted replies.
The test files contain the complete inputs and expected outcomes beside each
case. No fixture is selected from a final profile or final retrieval question.

The independent examples include:

- A 60-minute practice with included components and a separate 30-minute
  session contributes 90 minutes, without counting the components again.
- A completed November 16 session stays completed when November 18 is edited.
  Changing November 16 itself resets that occurrence to pending.
- Four feasible outcomes, including two verified successes, one timeout and
  one required unknown, produce two successes out of four.
- A complete request with 2,048 output tokens and the recorded reserves can
  contain 5,886 rendered-body tokens. One more token exceeds that ceiling.
- Two distinct sessions using the same drill remain two events.
- A food amount recorded for 100 g is scaled once; a valid zero is different
  from a missing nutrient value.

Numerical guidance cases use the adopted rule records. An unresolved coverage
or applicability result stays unknown. Passing these tests does not establish
that every rule is executable or that a generated plan is correct.

The source hash of each test and helper is recorded in the suite manifest.
The requirement map lists every collected test and its actual execution result.
