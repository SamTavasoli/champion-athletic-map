# Our integration test strategy

We run small, controlled examples through the current production functions and
workflow loops. Scripted role and HTTP responses replace actual model requests.
Expected results are written beside the fixtures; they are not obtained by
asking the tested function to supply its own answer.

Run the notebook setup cell once. It writes the tests, records their source
bindings and runs the routine suite. If pytest is missing, it adds pytest 8.4.2
while constraining packages already installed in the project environment.
Streamlit 1.67.0 comes from Step 29. Existing project modules and research results
are preserved. A changed prepared file stops setup rather than overwriting it.

The normal test command is:

    python -m pytest tests/unit tests/integration tests/app -m "not real_backend" --junitxml=results/testing/test_report.xml

The notebook runner captures full output in results/testing/pytest_output.log.
It disables unrelated pytest plugin autoloading, blocks network and external
workers in routine cases, checks source hashes before and after testing, and
records every collected case and execution phase. Zero collected tests,
collection errors, skipped requirements and expected failures cannot establish
a complete passing routine suite. Parameterized boundary cases count as
separate executed tests, not separate reviewed rule definitions.

Coverage includes public/private input separation, strict JSON, uncertainty,
adopted numerical boundaries, timing and session accounting, reference access
and budgets, food arithmetic, classifier boundaries using synthetic text,
planner roles and call limits, revision termination, saved-response reuse,
uncertain completion, application state, protected edits, progress and snapshots.
The requirement map links each test to the location of its expected assertions.
The fixtures README describes the independent examples and their limitations.

The food arithmetic tests load the existing source helper under data/processed;
they supply tiny authored food records. No raw food table, exercise test text,
protected athlete profile or final retrieval question is opened or scored.
Classifier checks do not load model weights or make final predictions.

The browser observations confirmed in our Step 29 discussion are recorded as
user-reported manual evidence. They are not added to pytest's passed count.
CSV content inspection, browser reset recovery and separate real browser
sessions remain pending. AppTest session simulations have their own evidence.

Source approval and software execution are different conditions. The active
release contains 127 basketball records, nine warm-ups and 29 adopted rules.
The checker can identify several violations, but complete classified-schedule
coverage and some free-form resource evidence remain unresolved. Tests preserve
those unknown results. We do not waive them or claim that all rules can now
produce a conclusive pass. Independent semantic scoring and the accepted final
case population still need their own completed bindings.

Live checks are kept in tests/real_backend and are excluded from the routine
command. The supplied optional check reads local model metadata only. It does
not generate a plan, download a model or establish runtime readiness.
To select it in a separate PowerShell session:

    $env:CAM_RUN_REAL_BACKEND = "1"
    python -m pytest tests/real_backend -m real_backend
    Remove-Item Env:CAM_RUN_REAL_BACKEND

Actual metadata requests append their own records to
results/testing/real_backend_checks.jsonl. The file is not fabricated by the
routine suite. Native generation, evaluator behavior, full token agreement,
capacity, operating limits and the representative pilot remain Step 31 work.

The summary keeps the routine result, manual evidence, live backend status,
source adoption, incomplete checking, independent scoring and protocol freeze
separate. Passing fixtures is not a measurement of generated plan quality.
Known gaps are listed in readiness_checks.csv. Newly observed assertion or
execution failures appear in defect_log.csv; an empty defect log does not
remove the recorded readiness gaps.

References:
- https://docs.pytest.org/en/stable/how-to/fixtures.html
- https://docs.pytest.org/en/stable/how-to/parametrize.html
- https://docs.pytest.org/en/stable/how-to/usage.html
- https://docs.pytest.org/en/stable/how-to/output.html
- https://docs.streamlit.io/develop/api-reference/app-testing/st.testing.v1.apptest
