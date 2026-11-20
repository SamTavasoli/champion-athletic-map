### Step 31-16 — Backend confirmation and one saved Planner 4 continuation

Our offline corrections passed their software checks, and all five saved
revision requests now fit the local input allowance. We also found one correct
food value in a reply's explanation, while its required food-facts field was
still incomplete. These results give us a reason to test the corrections with
our local model, but they do not establish that a revised plan will be correct.

We will first send the five corrected requests to Ollama in render-only mode.
This prepares each complete prompt without generating a reply. We will compare
the returned prompt and its locally counted size with our saved measurements,
using the same model, context limit, output allowance and reserves. All five
checks must pass before we continue to generation. The counts still use our
local tokenizer; this check does not measure a generated response's backend
input-token count.

We will then continue only the saved Planner 4 example for Case 13, where the
first revision was stopped because its request was too large. We will reuse
its athlete information, complete reference packet, initial draft, findings
and evaluator feedback. The continuation can use the two revisions already
allowed by our workflow, with one evaluation after each revision: at most four
new model submissions. It will not generate another initial draft or rerun the
other planners and cases. Every new request will still pass the normal
complete-prompt budget check before generation.

We will save this amended outcome separately and run our independent checks on
it. A valid format, successful completion or smaller request will not count as
a correct plan by itself. The calendar, requested number of sessions,
equipment, drill evidence and complete food answer must still be checked.
The original pilot replies and comparison results will remain available as
recorded. Human ratings, final study scores and live-interface activation are
outside this step.

The cell can reuse a fully saved, verified result without another model
submission. If a request's outcome is uncertain, it will stop for review
instead of sending the request again automatically.
