"""Literal public-request evidence shared by the final response checks.

These functions inspect public input only. They do not infer a requested dose
from a maximum allowance or read private case categories and example plans.
"""
from copy import deepcopy
from datetime import date
import re

VERSION = "final-public-request-checks-1"
_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
          "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_NUMBER = r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|[0-9]+)"
_UNIT = r"(?:sessions?|practices?(?:\s+blocks?)?|workouts?|blocks?)"
_COUNT = re.compile(r"\b(?P<count>" + _NUMBER + r")\s+"
                    r"(?:(?:extra|additional|uninterrupted)\s+)?"
                    r"(?:[1-9][0-9]*[- ]minute\s+)?(?:basketball\s+)?" + _UNIT + r"\b")
_DISTINCT = re.compile(r"\b(?:on|across|over)\s+(?P<count>" + _NUMBER + r")\s+(?:distinct|different|separate)\s+(?:dates?|days?)\b")
_DURATION = re.compile(r"\b(?P<duration>[1-9][0-9]*)[- ]minute\s+(?:basketball\s+)?" + _UNIT + r"\b")


def _number(text):
    return int(text) if text.isdigit() else _WORDS[text]


def _request(public):
    value = public.get("athlete_request", "")
    return value.casefold() if isinstance(value, str) else ""


def _distinct_targets(text):
    # A count of calendar dates represents session count only when an added
    # practice is explicitly requested on those dates.
    if not re.search(r"\b(?:extra|additional)\b", text) or not re.search(r"\b(?:basketball|practice|training|session|workout|block)\b", text):
        return []
    values = []
    for match in _DISTINCT.finditer(text):
        clause = re.split(r"[.!?;\n]", text[:match.start()])[-1]
        if re.search(r"\b(?:do not|don't|never|avoid)\s+(?:add|plan|schedule|arrange|include|keep|place)\b", clause):
            continue
        values.append(_number(match["count"]))
    return values


def requested_count(public):
    """Return an exact literal count, retaining ambiguity instead of guessing."""
    text = _request(public)
    matches = list(_COUNT.finditer(text))
    # Negative/range/alternative wording cannot authorize an exact dose. A
    # future semantic review can resolve wording outside this literal policy.
    if matches and (re.search(r"\b(?:at least|at most|up to|between|no more than|no fewer than)\s+" + _NUMBER, text)
                    or re.search(r"\b(?:do not|don't|never|avoid|not)\s+(?:(?:add|plan|schedule|arrange|include)\s+)?" + _NUMBER, text)
                    or re.search(_NUMBER + r"\s*(?:[-–]|or|to)\s*" + _NUMBER + r"\s+(?:extra\s+|additional\s+)?" + _UNIT, text)):
        return None, "multiple_or_qualified_count_statements_need_interpretation"
    values = []
    for match in matches:
        segment = match.group(0)
        preceding = text[max(0, match.start() - 35):match.start()]
        if (re.search(r"\b(?:extra|additional|uninterrupted)\b", segment)
                or re.search(r"\b(?:add|plan|schedule|arrange|include|keep)\s*$", preceding)):
            values.append(_number(match["count"]))
    values.extend(_distinct_targets(text))
    zero = re.search(r"\bno\s+(?:extra|additional)\s+(?:basketball\s+)?(?:sessions?|training|practices?(?:\s+blocks?)?|workouts?|blocks?)\b", text)
    if zero:
        values.append(0)
    if len(set(values)) > 1:
        return None, "multiple_count_statements_need_interpretation"
    if values:
        return values[0], "explicit_no_additional_training" if values[0] == 0 else "literal_additional_session_count"
    return None, "no_supported_exact_count_expression"


def requested_duration(public):
    text = _request(public)
    values = set()
    for match in _DURATION.finditer(text):
        clause = re.split(r"[.!?;\n]", text[:match.start()])[-1]
        if re.search(r"\b(?:do not|don't|never|avoid)\s+(?:add|plan|schedule|arrange|include|keep|place)\b", clause):
            return None
        if re.search(r"\b(?:at least|at most|up to|between|no more than|no fewer than)\s*$", text[:match.start()]):
            return None
        values.add(int(match["duration"]))
    return next(iter(values)) if len(values) == 1 else None


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _span(item):
    if not isinstance(item, dict):
        return None
    times = []
    for key in ("start_time", "end_time"):
        value = item.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
            return None
        hour, minute = map(int, value.split(":"))
        times.append(hour * 60 + minute)
    return tuple(times) if times[1] > times[0] else None


def _merge(spans):
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _subtract(spans, blockers):
    result = spans
    for low, high in blockers:
        remaining = []
        for start, end in result:
            if high <= start or low >= end:
                remaining.append((start, end))
            else:
                if start < low:
                    remaining.append((start, low))
                if high < end:
                    remaining.append((high, end))
        result = remaining
    return result


def distinct_date_proof(public):
    """Prove only a public demand greater than its possible available dates.

    Unknown commitments cannot increase availability. Valid known timed
    commitments may safely reduce this upper bound; malformed ones are ignored.
    Malformed availability prevents a proof because it might hide another date.
    """
    text = _request(public)
    targets = set(_distinct_targets(text))
    if len(targets) != 1:
        return None
    required = next(iter(targets))
    count, _ = requested_count(public)
    if count != required or required <= 0:
        return None
    available = public.get("availability")
    if not isinstance(available, list):
        return None
    window = public.get("planning_window") or {}
    first, last = _day(window.get("start_date")), _day(window.get("end_date"))
    if first is None or last is None or last < first:
        return None
    by_date = {}
    for item in available:
        if not isinstance(item, dict):
            return None
        on, span = _day(item.get("date")), _span(item)
        if on is None or span is None:
            return None
        if first <= on <= last:
            by_date.setdefault(item["date"], []).append(span)
    blockers = {}
    for item in public.get("existing_commitments") or []:
        if not isinstance(item, dict):
            continue
        on, span = _day(item.get("date")), _span(item)
        if on is not None and span is not None:
            blockers.setdefault(item["date"], []).append(span)
    duration = requested_duration(public)
    usable = []
    for on, spans in by_date.items():
        # Merging adjacent public windows gives a conservative upper bound.
        # Treating separate windows as continuous cannot create a false conflict.
        free = _subtract(_merge(spans), blockers.get(on, []))
        if any(end - start >= (duration or 1) for start, end in free):
            usable.append(on)
    if required <= len(usable):
        return None
    return {"kind": "distinct_dates", "observed": required, "bound": len(usable),
            "requested_distinct_dates": required, "available_distinct_date_upper_bound": len(usable),
            "available_dates": sorted(usable), "required_duration_minutes": duration,
            "source": "/availability", "public_request_source": "/athlete_request",
            "existing_commitments_source": "/existing_commitments",
            "proof_basis": "literal_distinct_date_demand_exceeds_public_availability_upper_bound",
            "unknown_commitments_cannot_increase_available_dates": True}


def _mentions_number(text, value):
    words = [word for word, number in _WORDS.items() if number == value]
    return re.search(r"\b(?:" + "|".join([str(value), *words]) + r")\b", text) is not None


def response_conflict_basis(public, response):
    """Return a narrow distinct-date basis, or None when this proof is absent."""
    proof = distinct_date_proof(public)
    if proof is None:
        return None
    kind = (response or {}).get("response_type")
    if kind != "constraint_conflict":
        return {"status": "violated", "reason": "The public request needs more distinct dates than its available-date upper bound.",
                "observed": proof, "supported_nonplan": False}
    text = " ".join([str(response.get("explanation", "")), *[str(value) for value in response.get("unresolved_issues") or []]]).casefold()
    for clause in re.split(r"[.!?;\n]", text):
        if re.search(r"\b(?:no|not|does not|doesn't|do not|don't)\s+(?:actual\s+)?(?:conflict|conflicts|exceed|exceeds|incompatible)\b", clause):
            continue
        if (re.search(r"\b(?:dates?|days?)\b", clause)
                and re.search(r"\b(?:available|availability|listed|provided|only)\b", clause)
                and re.search(r"\b(?:cannot|can't|only|insufficient|conflict|conflicts|exceed|exceeds|not enough|incompatible)\b", clause)
                and _mentions_number(clause, proof["observed"])
                and _mentions_number(clause, proof["bound"])):
            return {"status": "met", "reason": "The explanation identifies the demonstrated public distinct-date conflict.",
                    "observed": proof, "supported_nonplan": True}
    return {"status": "unknown", "reason": "The response does not identify the demonstrated requested-date and available-date counts together.",
            "observed": proof, "supported_nonplan": False}


def request_facts(public, original_facts):
    """Add literal request facts while preserving the caller's other evidence."""
    facts = deepcopy(original_facts)
    count, basis = requested_count(public)
    facts["requested_sessions"] = count
    facts["requested_session_count_basis"] = basis
    if basis.startswith("multiple"):
        facts["conflict"] = None
    duration = requested_duration(public)
    facts["requested_duration"] = duration
    text = _request(public)
    if duration is None and _DURATION.search(text):
        # A legacy parser may have retained the first duration in a negated or
        # ambiguous request; it cannot support a conflict under this policy.
        facts["conflict"] = None
    missing = list(facts.get("essential_missing") or [])
    schedule_request = bool(re.search(r"\b(?:basketball|practice|training)\b", text)
        and re.search(r"\b(?:schedule|week|dated|blocks?|sessions?|existing events)\b", text))
    if public.get("existing_commitments") is None and schedule_request:
        missing.append("existing_commitments")
    space = public.get("space") or {}
    if (re.search(r"\b(?:basket[- ]shooting|shooting)\b", text)
            and re.search(r"\b(?:specific|exact)\s+shooting\s+locations?\b", text)
            and (space.get("court_access") is None or space.get("hoop_access") is None)):
        missing.append("court_or_hoop")
    if (public.get("participants_available") is None
            and re.search(r"\b(?:each person|passing group|participants?|everyone)\b", text)
            and re.search(r"\b(?:exact role|turn order|equal turns|roles?)\b", text)):
        missing.append("participants")
    facts["essential_missing"] = list(dict.fromkeys(missing))
    excluded = [
        r"\b(?:create|make|write|give|prepare)\s+(?:me\s+)?(?:a\s+)?study\s+plan\b.*\b(?:history|math|science|exam)\b",
        r"\b(?:choose|recommend|select|prescribe)\b.*\bsupplements?\b.*\b(?:amount|dose|dosing|timing|quantity)\b",
        r"\b(?:set|calculate|give|prescribe)\b.*\b(?:my\s+personal|personalized|individualized)\b.*\bcalorie\b",
        r"\b(?:find|diagnose|identify)\b.*\b(?:medical cause|diagnosis)\b",
        r"\bprescribe\b.*\b(?:rehabilitation|rehab)\b",
    ]
    for clause in re.split(r"[.!?;\n]", text):
        for pattern in excluded:
            match = re.search(pattern, clause)
            if match and not re.search(r"\b(?:do not|don't|never|not)\s*$", clause[:match.start()]):
                facts["outside_scope"] = True
    if re.search(r"\b(?:extra|additional)\s+(?:basketball\s+)?practice\s+blocks?\b", text):
        facts["requires_complete_schedule"] = not facts.get("only_existing", False)
    limits = public.get("time_limits") or {}
    maximum = limits.get("max_additional_sessions_per_week")
    if type(count) is int and type(maximum) is int and count > maximum:
        facts["conflict"] = "The requested number of additional sessions exceeds the supplied weekly extra-session limit."
    weekly = limits.get("max_additional_minutes_per_week")
    if type(count) is int and type(duration) is int and type(weekly) is int and count * duration > weekly:
        facts["conflict"] = "The requested additional duration exceeds the supplied weekly extra-training minute limit."
    per_session = limits.get("max_session_minutes")
    if type(duration) is int and type(per_session) is int and duration > per_session:
        facts["conflict"] = "The requested uninterrupted session duration exceeds the supplied per-session limit."
    if type(duration) is int and isinstance(public.get("availability"), list):
        spans = [_span(item) for item in public["availability"]]
        if all(span is not None for span in spans) and all(end - start < duration for start, end in spans):
            facts["conflict"] = "The requested uninterrupted duration exceeds every supplied availability window."
    proof = distinct_date_proof(public)
    if proof is not None:
        facts["conflict"] = "Requested " + str(proof["observed"]) + " distinct dates; at most " + str(proof["bound"]) + " supplied dates can fit the practice."
        facts["distinct_date_proof"] = proof
    return facts
