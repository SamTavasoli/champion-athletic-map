# Prototype design

We separate the interface, session state, interactive execution and snapshot
validation. Mutable profiles and plans live in each Streamlit session; only
stateless services and verified read-only resources may be cached globally.
The process/file execution gate protects complete model workflows across
sessions. A job records its owner, profile version, content and execution state
before invocation. Reruns and late results do not create or relabel jobs.

Profile snapshots, original responses and saved plan revisions are immutable.
Edits use stable activity IDs and a backend field allowlist. Catalog substitution
resolves canonical instructions, requirements and citations afresh; imported
approval flags cannot activate resources. Planning edits run coded checks and
invalidate model-review freshness. Assessment bindings include profile, plan,
reference, source, checker, evaluator and policy versions. Updating progress
does not enter planning hashes or invalidate a valid assessment.

Progress tracks separate top-level training occurrences, including supplied
practices and games. Rest, nontraining commitments and included components do
not add items. Date/time/duration/definition changes reset only changed activity
versions; unchanged occurrences in the same week can retain reported progress.
Skipped items remain in the denominator and empty checklists have no percentage.

Exports contain the selected minimal profile/plan, activity identities, relevant
edits, historical assessments, source IDs and progress. They exclude raw internal
job traces, credentials, private benchmark expectations, model weights and whole
reference collections. Strict JSON validation and backend canonical source
resolution apply on restore. Source incompatibility yields a historical read-only
view. Fresh coded checks do not convert imported model reviews into current ones.

The frozen research profile contract fixes the study week. The prototype uses
a separate interactive schema for arbitrary seven-day windows and valid IANA
time zones; research files remain byte-for-byte unchanged. A fresh interactive
planner instance uses that schema and an application reference policy in memory.
Interactive contexts use their own namespace and fixed source versions; they
never modify frozen research packets, indexes, splits or evaluation cases.

Version 4's candidate-focused evaluator and reversible calendar representation
remain awaiting a pilot. Generation and evaluator review are therefore disabled
until an explicit local-development pilot record matches the configured sources.
This is a runtime verification gate, not approval of plan quality or medical
safety. Historical saved responses remain available for interface development.
Independent plan-quality scoring and operational readiness remain pending.

Software verification uses authored fixtures, scripted backends, snapshot tests
and Streamlit AppTest. These checks establish interface/state behavior, not
real-model planning quality. Manual browser and real-backend testing continue in
Steps 30 and 31. Original failed development responses remain recorded.

Implementation references:
- https://docs.streamlit.io/1.67.0/develop/concepts/architecture/forms
- https://docs.streamlit.io/1.67.0/develop/api-reference/data/st.data_editor
- https://docs.streamlit.io/1.67.0/develop/api-reference/caching-and-state/st.session_state
- https://docs.streamlit.io/1.67.0/develop/api-reference/app-testing/st.testing.v1.apptest
