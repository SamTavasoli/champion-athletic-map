"""Pure accounting for supplied workflow timing and model-transport usage records."""

import math

VERSION = "runtime-accounting-1"
JOB_STATES = ("not_started", "running", "returned", "failed", "timeout")
TERMINAL_STATES = ("returned", "failed", "timeout")
ROLES = ("generator", "coordinator", "specialist", "evaluator")


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonblank text.")
    return value


def _quantity(value, count=False):
    if value is not None and (type(value) not in ((int,) if count else (int, float))
            or value < 0 or (not count and not math.isfinite(value))):
        raise ValueError("Expected a finite nonnegative measurement or null.")
    return value


def _roster(values):
    if not isinstance(values, list):
        raise ValueError("Expected an identifier list.")
    for value in values:
        _text(value)
    if len(set(values)) != len(values):
        raise ValueError("Expected unique identifiers.")
    return list(values)


def _measure(values, complete, empty_is_zero=False):
    available = [value for value in values if value is not None]
    total = sum(available) if available or (not values and empty_is_zero and complete) else None
    fully_measured = complete and len(available) == len(values)
    return {"expected_measurements": len(values), "available_measurements": len(available),
        "missing_measurements": len(values) - len(available), "observed_total": total,
        "observed_mean": total / len(available) if available else None,
        "complete_total": total if fully_measured else None,
        "complete_mean": total / len(available) if fully_measured and available else None,
        "measure_complete": fully_measured,
        "unavailable_reason": None if fully_measured and total is not None else
            ("inventory_or_execution_incomplete" if not complete else "missing_measurements" if len(available) < len(values) else "empty_group")}


def summarize_workflow_runtime(job_ids, records, inventory_complete):
    """Keep terminal and pending jobs separate; never sum stage durations into wall time."""
    roster = _roster(job_ids)
    if type(inventory_complete) is not bool or not isinstance(records, list):
        raise ValueError("Declare inventory completeness and supply workflow records.")
    fields = {"job_id", "job_status", "workflow_elapsed_seconds", "startup_elapsed_seconds",
        "stages", "cache_state", "retrieval_calls", "lookup_calls"}
    rows = {}
    stage_observations = stage_missing = startup_available = 0
    for row in records:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("Invalid workflow-record fields.")
        key = _text(row["job_id"])
        if key not in roster or key in rows:
            raise ValueError("Unexpected or duplicate job identifier.")
        state = row["job_status"]
        if not isinstance(state, str) or state not in JOB_STATES:
            raise ValueError("Invalid workflow status.")
        elapsed = _quantity(row["workflow_elapsed_seconds"])
        startup = _quantity(row["startup_elapsed_seconds"])
        retrieval = _quantity(row["retrieval_calls"], count=True)
        lookup = _quantity(row["lookup_calls"], count=True)
        if state not in TERMINAL_STATES and elapsed is not None:
            raise ValueError("Unfinished jobs cannot carry a completed workflow duration.")
        if not isinstance(row["cache_state"], str) or row["cache_state"] not in ("unknown", "warm", "cold", "disabled"):
            raise ValueError("Invalid declared cache state.")
        if not isinstance(row["stages"], list):
            raise ValueError("Expected stage observations.")
        stages = set()
        for stage in row["stages"]:
            if not isinstance(stage, dict) or set(stage) != {"stage_id", "elapsed_seconds"}:
                raise ValueError("Invalid stage-observation fields.")
            stage_id = _text(stage["stage_id"])
            duration = _quantity(stage["elapsed_seconds"])
            if stage_id in stages or (elapsed is not None and duration is not None and duration > elapsed):
                raise ValueError("Stage identity or duration differs from its whole-workflow boundary.")
            stages.add(stage_id)
            stage_observations += 1
            stage_missing += int(duration is None)
        if state == "not_started" and (startup is not None or row["stages"] or retrieval not in (None, 0) or lookup not in (None, 0)):
            raise ValueError("Unstarted jobs cannot carry observed runtime activity.")
        startup_available += int(startup is not None)
        rows[key] = row
    states = dict.fromkeys((*JOB_STATES, "not_recorded"), 0)
    for key in roster:
        states[rows[key]["job_status"] if key in rows else "not_recorded"] += 1
    terminal = [row for row in rows.values() if row["job_status"] in TERMINAL_STATES]
    complete = inventory_complete and len(terminal) == len(roster)
    groups = {}
    for state in (*TERMINAL_STATES, "all_terminal"):
        selected = terminal if state == "all_terminal" else [row for row in terminal if row["job_status"] == state]
        groups[state] = {"jobs": len(selected), **_measure([row["workflow_elapsed_seconds"] for row in selected], complete)}
    return {"version": VERSION, "expected_jobs": len(roster), "inventory_complete": inventory_complete,
        "execution_complete": complete, "status_counts": states, "workflow_seconds": groups,
        "lookup_retrieval_summary_scope": "terminal_jobs_only",
        "stage_startup_summary_scope": "all_recorded_jobs",
        "retrieval_calls": _measure([row["retrieval_calls"] for row in terminal], complete, empty_is_zero=True),
        "lookup_calls": _measure([row["lookup_calls"] for row in terminal], complete, empty_is_zero=True),
        "stage_observations": stage_observations, "stage_measurements_missing": stage_missing,
        "stage_durations_summed": False, "startup_measurements_available": startup_available,
        "startup_included_in_request_time": False, "returned_does_not_establish_planner_success": True}


def summarize_model_transport(calls, attempts, inventory_complete):
    """One workflow job; charge tokens and estimates only at the transport-attempt level."""
    if type(inventory_complete) is not bool or not isinstance(calls, list) or not isinstance(attempts, list):
        raise ValueError("Declare inventory completeness and supply call/attempt lists.")
    indexed = {}
    for row in calls:
        if not isinstance(row, dict) or set(row) != {"call_id", "role", "phase", "revision_index"}:
            raise ValueError("Invalid logical-call fields.")
        key = _text(row["call_id"])
        if key in indexed or not isinstance(row["role"], str) or row["role"] not in ROLES:
            raise ValueError("Invalid logical-call identity or role.")
        revision = _quantity(row["revision_index"], count=True)
        if revision is None or row["phase"] not in ("initial", "revision") or (row["phase"] == "initial") != (revision == 0):
            raise ValueError("Initial calls use index zero; revision calls use a positive revision index.")
        indexed[key] = row
    identifiers = set()
    by_call = dict.fromkeys(indexed, 0)
    states = dict.fromkeys(("returned", "failed", "timeout", "running"), 0)
    for row in attempts:
        if not isinstance(row, dict) or set(row) != {"attempt_id", "call_id", "attempt_status", "input_tokens", "output_tokens", "cost_estimate"}:
            raise ValueError("Invalid transport-attempt fields.")
        key = _text(row["attempt_id"])
        parent = _text(row["call_id"])
        if key in identifiers or parent not in indexed:
            raise ValueError("Duplicate attempt or missing logical-call parent.")
        identifiers.add(key)
        by_call[parent] += 1
        state = row["attempt_status"]
        if not isinstance(state, str) or state not in states:
            raise ValueError("Invalid transport-attempt status.")
        states[state] += 1
        _quantity(row["input_tokens"], count=True)
        _quantity(row["output_tokens"], count=True)
        cost = row["cost_estimate"]
        if cost is not None:
            if not isinstance(cost, dict) or set(cost) != {"amount", "currency", "basis_ref"}:
                raise ValueError("Invalid model-transport cost estimate.")
            if _quantity(cost["amount"]) is None:
                raise ValueError("An estimate needs an observed amount and recorded basis.")
            currency = _text(cost["currency"])
            if len(currency) != 3 or not currency.isascii() or not currency.isalpha() or not currency.isupper():
                raise ValueError("Expected an explicit three-letter currency code.")
            _text(cost["basis_ref"])
    absent = sum(count == 0 for count in by_call.values())
    complete = inventory_complete and states["running"] == 0 and absent == 0
    role_counts = {role: sum(row["role"] == role for row in calls) for role in ROLES}
    phase_counts = {phase: sum(row["phase"] == phase for row in calls) for phase in ("initial", "revision")}
    retry_count = sum(max(count - 1, 0) for count in by_call.values())
    revisions = len({row["revision_index"] for row in calls if row["phase"] == "revision"})
    costs = [row["cost_estimate"] for row in attempts if row["cost_estimate"] is not None]
    currencies = sorted({row["currency"] for row in costs})
    cost_ready = complete and bool(attempts) and len(costs) == len(attempts) and len(currencies) == 1
    return {"version": VERSION, "inventory_complete": inventory_complete, "usage_complete": complete,
        "logical_calls_observed": len(calls), "transport_attempts_observed": len(attempts),
        "retry_attempts_observed": retry_count, "revision_calls_observed": phase_counts["revision"], "revision_rounds_observed": revisions,
        "logical_calls_total": len(calls) if complete else None,
        "transport_attempts_total": len(attempts) if complete else None,
        "retry_attempts_total": retry_count if complete else None,
        "revision_rounds_total": revisions if complete else None,
        "calls_without_attempts": absent, "attempt_status_counts": states,
        "logical_call_roles_observed": role_counts, "logical_call_phases_observed": phase_counts,
        "role_and_phase_breakdowns_overlap": True,
        "input_tokens": _measure([row["input_tokens"] for row in attempts], complete, empty_is_zero=True),
        "output_tokens": _measure([row["output_tokens"] for row in attempts], complete, empty_is_zero=True),
        "model_transport_cost_estimate": {"scope": "model_transport_only", "expected_estimates": len(attempts),
            "available_estimates": len(costs), "missing_estimates": len(attempts) - len(costs),
            "observed_totals_by_currency": {currency: sum(row["amount"] for row in costs if row["currency"] == currency) for currency in currencies},
            "estimate_total": sum(row["amount"] for row in costs) if cost_ready else None,
            "currency": currencies[0] if cost_ready else None,
            "basis_refs": sorted({row["basis_ref"] for row in costs}),
            "measure_complete": cost_ready, "unavailable_reason": None if cost_ready else
                ("inventory_or_execution_incomplete" if not complete else "empty_group" if not attempts else "missing_estimates" if len(costs) < len(attempts) else "mixed_currencies")}}
