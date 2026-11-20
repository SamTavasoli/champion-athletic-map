# Using the prototype

Run the Step 29 notebook cell once from the project environment. It writes the
app files and prepares Streamlit 1.67.0, preserving other installed package
versions. It makes no model or query-encoder calls. Existing research sources,
datasets, approval records and results remain unchanged.

From the project terminal with the same environment active, start the app:

    python -m streamlit run app/streamlit_app.py --server.address 127.0.0.1

Open http://localhost:8501. The app is a local development prototype.

1. Choose a saved fictional example explicitly, or enter athlete information.
   Unknown information and confirmed absence are different choices. Form edits
   remain unsaved until Save athlete information or an enabled Generate action.
2. Read the saved response and its status. A saved development example is
   historical and may contain known errors. A failed workflow has no final plan.
3. Edit a proposed session's allocation or choose an eligible catalog replacement.
   Existing commitments are changed through athlete information. Source facts
   and eligibility are controlled by the application, not by editable columns.
4. Save changes to create a new plan version and refresh coded checks. The
   earlier model review becomes outdated. A conflict may remain in the saved
   draft. Moving a session's day also moves its included components to that day.
5. Mark top-level training sessions pending, completed or skipped. This records
   self-reported completion; it does not assess athletic improvement.
6. Download CSV for reading or JSON for restoration. Restore explicitly into a
   validated workspace; imported model assessments remain historical.

Live generation and explicit model review wait for the development pilot.
Installing the interface does not approve the untested corrected workflow.
The app explains the pending condition instead of substituting another planner.
When enabled by a matching pilot record, Generate starts one bounded Version 4
job. Review saved changes checks the exact saved version with one evaluator
call and never rewrites it. Progress, display, downloads and restoration never
start model work. Application jobs remain separate from research results.

Session state can disappear when the browser connection resets. Download JSON
to retain your work. A browser reset does not cancel an uncertain model request;
the execution gate preserves the recorded job until its outcome is resolved.
Do not treat an imported acceptance flag as a current verification.
