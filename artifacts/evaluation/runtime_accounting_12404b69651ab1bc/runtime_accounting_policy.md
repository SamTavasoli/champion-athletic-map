# Runtime and resource accounting — prepared component

This component verifies arithmetic and bookkeeping for supplied artificial records. It does not start a planner, measure a model, inspect protected profiles, query hardware or prices, or collect actual usage.

Measure one complete workflow request using a shared timing policy. Include retrieval, structured lookups, orchestration, model attempts, retries, revisions and in-request waiting. Record startup/loading separately; loading performed inside the request remains within the observed request duration. Preserve stage observations without summing them because stages can overlap or nest. Establish runner instrumentation and resumed-run clock policy before final testing.

Report returned, failed and timed-out jobs separately. A returned response is not evidence of planner success. Later, join independent scoring outcomes to report successful-response latency. Pending and unrecorded jobs remain incomplete work. Every mean has measured and missing counts. Observed partial totals/means are descriptive; complete totals/means remain unavailable until the job inventory is terminal and the required measurements are available. Empty latency groups have no latency value.

Retrieval/lookup aggregates describe terminal jobs only. Pending-job observations stay in their original records. Stage/startup observation counts include all recorded jobs. Scope labels identify those populations; no full total is exposed while jobs are pending.

Model usage is accounted for one workflow job at a time. Logical call IDs and transport attempt IDs are distinct. A retry adds an attempt to the same call; a substantive revision uses a new logical call. Record role and phase separately because a coordinator can also act during revision. Do not add overlapping role and phase totals. Distinct model-call revision indices describe model revision rounds; non-model loop activity still needs a stage log.

Tokens are counted once across transport attempts, including failed attempts with known usage. Missing token quantities retain null complete totals and known observed totals with availability counts. A complete empty call inventory can support zero call/token counts. Missing inventory or a declared call without its attempt records cannot establish completed usage.

The cost helper reports model-transport estimates, not billed spend or full-workflow cost. An estimate needs an explicit currency and recorded estimation/pricing basis. Unknown cost is not zero; a recorded zero needs a basis too. Keep observed currency totals separate and leave a single total unavailable for mixed currencies or missing expected estimates. Additional retrieval/lookup/provider charges and local resource costs require their own cost inventory.

Actual resource observations must identify their metric, unit, device, measurement window and method. Keep unavailable GPU, RAM, energy, timing and token telemetry unavailable. Record cache state and common startup policy across versions. Timeout, retry and revision limits remain unset until the Step 31 development pilot.

The pure helpers validate supplied records, not instrumentation truth or cross-ledger consistency. The later runner must bind runtime, model-usage, resource and designated-response logs to the same job/run/version and reconcile them. These artificial checks are not operational telemetry integration or final evaluation.
