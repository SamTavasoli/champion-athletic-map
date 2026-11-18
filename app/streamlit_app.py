"""Our local basketball-planning workspace."""

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4
import json
import math
import os
import re
import sys

import streamlit as st


ROOT = Path(os.environ.get("CHAMPION_PROJECT_ROOT", Path(__file__).resolve().parents[1])).resolve()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
from champion_athletic_map import application_state as state_api
from champion_athletic_map import plan_exports
from champion_athletic_map.interactive_review import PrototypeService


st.set_page_config(page_title="Champions Athletic Map", page_icon="🏀", layout="wide")


@st.cache_resource(show_spinner="Opening project resources…")
def open_service(project_root):
    return PrototypeService(Path(project_root))


def _empty(value):
    return value is None or value == "" or isinstance(value, float) and math.isnan(value)


def _optional(value):
    return None if _empty(value) else value


def _lines(text):
    return [line.strip() for line in str(text).splitlines() if line.strip()]


def _list_text(value):
    return "\n".join(value or [])


def _rows(value):
    result = []
    for item in value:
        row = {key: _optional(value) for key, value in item.items()}
        if any(value is not None for value in row.values()):
            result.append(row)
    return result


def _integer(value):
    value = _optional(value)
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _index(options, value):
    return options.index(value) if value in options else 0


def _message(kind, text):
    st.session_state["champion_notice"] = (kind, text)


def _refresh_intake(record=None):
    st.session_state["champion_intake"] = deepcopy(record)
    st.session_state["champion_form_epoch"] = st.session_state.get("champion_form_epoch", 0) + 1


def _profile_name(profile):
    if profile is None:
        return "No saved profile"
    order = list(workspace["profiles"])
    number = order.index(profile["profile_version"]) + 1 if profile["profile_version"] in order else len(order)
    return "Saved athlete information · version " + str(number)


def _busy():
    return workspace.get("active_job") is not None and workspace["jobs"].get(workspace["active_job"], {}).get("status") in ("active", "unresolved")


def _failed_job_outcome(error):
    # We release only jobs that are confirmed to have stopped before submission.
    return {"status": "blocked" if getattr(error, "request_accepted", None) is False else "unresolved",
            "error": str(error)}


def _load_example(number):
    examples = service.development_examples()
    if not 0 <= number < len(examples):
        raise ValueError("This saved example is unavailable.")
    example = examples[number]
    saved = state_api.save_profile(workspace, example["public_record"], service.validate_profile)
    _refresh_intake(saved["public_record"])
    outcome = example.get("outcome")
    if outcome:
        response = ((outcome.get("response") or {}).get("model_output") or {}).get("parsed_object")
        report = (service.check_plan(saved["public_record"], response, example.get("reference_packet"))
                  if outcome.get("completion_valid") and outcome.get("format_valid") and isinstance(response, dict) else None)
        job_id = "app_demo_" + uuid4().hex
        state_api.begin_job(workspace, job_id, "demonstration")
        attached = state_api.attach_outcome(workspace, job_id, outcome,
            example.get("reference_packet"), service.source_versions(), check_report=report, historical=True)
        if not attached["attached"]:
            _message("info", "The profile is loaded. Its saved workflow did not return a complete plan.")
            return
    _message("success", "Saved example loaded. No model request was made.")


def _submit_generation(record):
    profile = state_api.save_profile(workspace, record, service.validate_profile)
    _refresh_intake(profile["public_record"])
    ready = service.readiness()
    if not ready.get("generation_ready"):
        _message("info", ready.get("message", "Live planning is waiting for pilot testing."))
        return
    job_id = "app_" + uuid4().hex
    started = state_api.begin_job(workspace, job_id, "generation")
    if not started["created"]:
        return
    try:
        with st.spinner("Preparing the plan…"):
            envelope = service.generate(profile, job_id, workspace["session_id"])
        outcome = envelope.get("outcome", envelope)
        attached = state_api.attach_outcome(workspace, job_id, outcome,
            envelope.get("reference_packet"), envelope.get("source_versions", service.source_versions()),
            check_report=envelope.get("check_report"))
        _message("success" if attached["attached"] else "info",
                 "The response is saved." if attached["attached"] else attached["reason"])
    except Exception as error:
        failure = _failed_job_outcome(error)
        state_api.complete_job(workspace, job_id, failure)
        _message("info" if failure["status"] == "blocked" else "error", "Planning could not finish: " + str(error))


def _intake():
    saved = state_api.current_profile(workspace)
    record = st.session_state.get("champion_intake") or (saved or {}).get("public_record")
    record = deepcopy(record) if record else {"profile_id": "athlete:app-" + uuid4().hex,
        "schema_version": "interactive-profile-input-1", "input": {}}
    p = record["input"]
    epoch = st.session_state["champion_form_epoch"]
    key = lambda name: "intake_" + str(epoch) + "_" + name
    st.subheader("Athlete information")
    st.caption("Use a fictional label for this prototype. Changes stay in the form until you save or generate.")
    with st.form(key("form")):
        st.text_input("Athlete label", value=st.session_state.get("champion_label", "Development athlete"), key=key("label"))
        c1, c2, c3 = st.columns(3)
        with c1:
            age_unknown = st.checkbox("Age not provided", value=p.get("age") is None, key=key("age_unknown"))
            age = st.number_input("Age", min_value=13, max_value=17, value=p.get("age") or 16, step=1, key=key("age"))
        with c2:
            grades = ["Not provided"] + list(range(1, 13))
            grade = st.selectbox("School grade", grades, index=_index(grades, p.get("school_grade")), key=key("grade"))
        with c3:
            experience_options = ["Not provided", "beginner", "intermediate", "advanced"]
            experience = st.selectbox("Basketball experience", experience_options,
                index=_index(experience_options, (p.get("basketball_background") or {}).get("experience_level")), key=key("experience"))
        request = st.text_area("What would you like to plan?", value=p.get("athlete_request", ""), height=90, key=key("request"))
        goals_unknown = st.checkbox("Goals not provided", value=p.get("goals") is None, key=key("goals_unknown"))
        goals = st.text_area("Basketball goals — one per line", value=_list_text(p.get("goals")), height=75, key=key("goals"))
        c1, c2 = st.columns(2)
        with c1:
            week = st.date_input("Week starts", value=date.fromisoformat((p.get("planning_window") or {}).get("start_date", "2026-11-16")), key=key("week"))
            position = st.text_input("Position, if relevant", value=(p.get("basketball_background") or {}).get("position") or "", key=key("position"))
        with c2:
            zone = st.text_input("Time zone", value=(p.get("planning_window") or {}).get("timezone", "America/Los_Angeles"), key=key("timezone"))
            skill = st.text_input("Current skill or experience notes", value=(p.get("basketball_background") or {}).get("reported_skill_level") or "", key=key("skill"))
        st.markdown("**Available times**")
        availability_known = st.checkbox("Availability is confirmed", value=p.get("availability") is not None, key=key("availability_known"))
        st.caption("Use dates as YYYY-MM-DD and local times as HH:MM. An empty confirmed list means no available time; an unconfirmed list stays unknown.")
        availability_rows = [{"date": row.get("date"), "start_time": row.get("start_time"), "end_time": row.get("end_time")}
                             for row in p.get("availability") or []]
        availability = st.data_editor(availability_rows or [{"date": None, "start_time": None, "end_time": None}],
            num_rows="dynamic", hide_index=True, width="stretch", key=key("availability"), column_config={
                "date": st.column_config.TextColumn("Date"), "start_time": st.column_config.TextColumn("Start"),
                "end_time": st.column_config.TextColumn("End")})
        st.markdown("**Existing commitments**")
        commitments_known = st.checkbox("Existing commitments are confirmed", value=p.get("existing_commitments") is not None, key=key("commitments_known"))
        st.caption("Include practices, games, other sports and non-training commitments. An empty confirmed list means none were reported for this week.")
        kinds = {"Practice": "practice", "Game": "game", "Training": "training", "Conditioning": "conditioning",
                 "Informal": "informal", "School": "school", "Travel": "travel", "Other": "other"}
        categories = {"Basketball": "organized_basketball", "Other sport": "other_organized_sport",
                      "Conditioning": "general_conditioning", "Informal activity": "informal_activity", "Other commitment": "nontraining"}
        kind_names, category_names = {v: k for k, v in kinds.items()}, {v: k for k, v in categories.items()}
        commitments_rows = [{"date": row.get("date"), "description": row.get("description"),
            "category": category_names.get(row.get("activity_type")), "kind": kind_names.get(row.get("activity_kind")),
            "sport": row.get("sport"), "start_time": row.get("start_time"), "end_time": row.get("end_time")}
            for row in p.get("existing_commitments") or []]
        commitments = st.data_editor(commitments_rows or [{key: None for key in ("date", "description", "category", "kind", "sport", "start_time", "end_time")}],
            num_rows="dynamic", hide_index=True, width="stretch", key=key("commitments"), column_config={
                "date": st.column_config.TextColumn("Date"), "description": st.column_config.TextColumn("Commitment"),
                "category": st.column_config.SelectboxColumn("Category", options=list(categories)),
                "kind": st.column_config.SelectboxColumn("Kind", options=list(kinds)), "sport": st.column_config.TextColumn("Sport"),
                "start_time": st.column_config.TextColumn("Start"), "end_time": st.column_config.TextColumn("End")})
        st.markdown("**Equipment and practice space**")
        equipment_known = st.checkbox("Equipment is confirmed", value=p.get("equipment") is not None, key=key("equipment_known"))
        equipment = st.data_editor([{"name": row.get("name"), "quantity": row.get("quantity")} for row in p.get("equipment") or []]
            or [{"name": None, "quantity": None}], num_rows="dynamic", hide_index=True, width="stretch", key=key("equipment"),
            column_config={"name": st.column_config.TextColumn("Equipment"), "quantity": st.column_config.NumberColumn("Quantity — blank if unknown", min_value=0, step=1)})
        c1, c2 = st.columns(2)
        space = p.get("space") or {}
        with c1:
            courts = {"Not provided": None, "No court": "none", "Full court": "full_court", "Half court": "half_court", "Single hoop area": "single_hoop_area"}
            court = st.selectbox("Court access", list(courts), index=_index(list(courts.values()), space.get("court_access")), key=key("court"))
            area = st.text_area("Usable practice area", value=space.get("usable_area_description") or "", height=75, key=key("area"))
        with c2:
            hoops = {"Not provided": None, "Yes": True, "No": False}
            hoop = st.selectbox("Hoop access", list(hoops), index=_index(list(hoops.values()), space.get("hoop_access")), key=key("hoop"))
            restrictions_unknown = st.checkbox("Space restrictions not provided", value=space.get("restrictions") is None, key=key("restrictions_unknown"))
            restrictions = st.text_area("Practice-space restrictions — one per line", value=_list_text(space.get("restrictions")), height=75, key=key("restrictions"))
        c1, c2 = st.columns(2)
        with c1:
            participants_unknown = st.checkbox("Participant count not provided", value=p.get("participants_available") is None, key=key("participants_unknown"))
            participants = st.number_input("Total participants, including the athlete", min_value=1, value=p.get("participants_available") or 1, step=1, key=key("participants"))
        with c2:
            limitations_unknown = st.checkbox("Limitations not provided", value=p.get("reported_limitations") is None, key=key("limitations_unknown"))
            limitations = st.text_area("Reported limitations — one per line", value=_list_text(p.get("reported_limitations")), height=75, key=key("limitations"))
        st.markdown("**Limits for additional training**")
        limits, entered_limits = p.get("time_limits") or {}, {}
        for column, (field, label, maximum) in zip(st.columns(3), (
                ("max_additional_sessions_per_week", "Extra sessions per week", 99),
                ("max_additional_minutes_per_week", "Extra minutes per week", 10080),
                ("max_session_minutes", "Minutes per session", 1440))):
            with column:
                unknown = st.checkbox("Limit not provided", value=limits.get(field) is None, key=key(field + "_unknown"))
                value = st.number_input(label, min_value=0, value=limits.get(field) or 0, step=1, key=key(field))
                entered_limits[field] = None if unknown else value
        food = st.text_area("Optional food-facts question", value=p.get("food_question") or "", height=75, key=key("food"))
        c1, c2 = st.columns(2)
        save = c1.form_submit_button("Save athlete information", width="stretch")
        generate = c2.form_submit_button("Generate plan", disabled=not readiness.get("generation_ready") or _busy(), width="stretch")
    if save or generate:
        try:
            updated = deepcopy(p)
            background = {"experience_level": None if experience == "Not provided" else experience,
                          "position": _optional(position.strip()), "reported_skill_level": _optional(skill.strip())}
            commit_values = []
            for row in _rows(commitments):
                commit_values.append({"date": row.get("date"), "description": row.get("description"),
                    "activity_type": categories.get(row.get("category")), "activity_kind": kinds.get(row.get("kind")),
                    "sport": row.get("sport"), "start_time": row.get("start_time"), "end_time": row.get("end_time")})
            updated.update(age=None if age_unknown else age, school_grade=None if grade == "Not provided" else grade,
                athlete_request=request.strip(), goals=None if goals_unknown else _lines(goals),
                planning_window={"start_date": week.isoformat(), "end_date": (week + timedelta(days=6)).isoformat(), "timezone": zone.strip()},
                basketball_background=background, availability=_rows(availability) if availability_known else None,
                existing_commitments=commit_values if commitments_known else None,
                equipment=[{"name": row.get("name"), "quantity": _integer(row.get("quantity"))} for row in _rows(equipment)] if equipment_known else None,
                space={"court_access": courts[court], "hoop_access": hoops[hoop], "usable_area_description": _optional(area.strip()),
                       "restrictions": None if restrictions_unknown else _lines(restrictions)},
                participants_available=None if participants_unknown else participants,
                reported_limitations=None if limitations_unknown else _lines(limitations), time_limits=entered_limits,
                food_question=_optional(food.strip()))
            record["input"] = updated
            st.session_state["champion_label"] = st.session_state[key("label")]
            if generate:
                _submit_generation(record)
            else:
                profile = state_api.save_profile(workspace, record, service.validate_profile)
                _refresh_intake(profile["public_record"])
                _message("success", "Athlete information saved. No model request was made.")
            st.rerun()
        except Exception as error:
            st.error("Please check the entered information: " + str(error))


def _findings(plan):
    current = state_api.assessment_current(workspace, service.source_versions())
    assessment = (plan.get("assessment") or {}).get("report") or {}
    history = (plan.get("original_outcome") or {}).get("history") or []
    reports = (plan.get("original_outcome") or {}).get("check_results") or []
    report = (assessment.get("coded_report") if current else None) or plan.get("check_report") or (reports[-1] if reports else {})
    rows = report.get("checks", []) if isinstance(report, dict) else []
    relevant = [row for row in rows if row.get("status") in ("violated", "unknown")]
    if relevant:
        with st.expander("Items that still need attention", expanded=False):
            seen = set()
            for row in relevant:
                text = str(row.get("reason") or "This condition needs more information.")
                if text not in seen:
                    st.write(text)
                    seen.add(text)
    evaluation = assessment.get("evaluator_result") if current else (history[-1].get("evaluator_result") if history else None)
    body = (((evaluation or {}).get("response") or {}).get("model_output") or {}).get("parsed_object")
    issues = body.get("issues") if isinstance(body, dict) else []
    if issues:
        with st.expander("Model review comments" if current else "Historical model review comments"):
            if not current:
                st.caption("These are saved comments, not a current assessment. Model review can also make mistakes.")
            for issue in issues:
                st.write(issue.get("problem", ""))
                if issue.get("correction"):
                    st.caption(issue["correction"])


def _sources(plan):
    assessment = (plan.get("assessment") or {}).get("report") or {}
    current_packet = assessment.get("reference_packet") if state_api.assessment_current(workspace, service.source_versions()) else None
    payload = (current_packet or plan.get("reference_packet") or {}).get("payload") or {}
    refs = payload.get("references") or []
    if refs:
        with st.expander("Sources used in this saved response"):
            for index, source in enumerate(refs, 1):
                text = source.get("complete_required_delivery_text") or ""
                st.markdown("**Reference " + str(index) + "**")
                st.text(text)
                for link in dict.fromkeys(re.findall(r"https?://[^\s<>\"']+", text)):
                    if link.startswith(("https://", "http://")):
                        st.link_button("Open source", link)
    food = payload.get("food_lookup") or []
    if food:
        with st.expander("Recorded food facts"):
            st.caption("These values come from the frozen food reference. The planner's explanation is separate.")
            for item in food:
                data = item.get("data") or {}
                if item.get("status") != "found":
                    st.write("Food lookup:", item.get("status", "unavailable"))
                    for issue in item.get("issues") or []:
                        st.write(issue)
                    continue
                st.write(str(data.get("grams", "")) + " g " + str(data.get("description", "")))
                table = [{"Nutrient": row.get("nutrient_name"), "Amount": row.get("amount") if row.get("status") == "available" else "Not recorded", "Unit": row.get("unit")}
                         for row in data.get("nutrients") or []]
                st.dataframe(table, hide_index=True, width="stretch")
                for link in item.get("source_refs") or []:
                    if isinstance(link, str) and link.startswith(("https://", "http://")):
                        st.link_button("Open food source", link)
    activity_sources = plan.get("activity_sources") or {}
    if activity_sources:
        with st.expander("Approved replacement instructions"):
            for source in activity_sources.values():
                st.write(source.get("name") or "Approved activity")
                st.text(source.get("description") or "")
                details = source.get("source_fields") or {}
                for key, label in (("equipment", "Equipment"), ("participants", "Participants"),
                                   ("space", "Space"), ("source_prescription", "Source prescription"),
                                   ("use_conditions", "Use conditions"), ("publisher_attribution", "Publisher")):
                    if details.get(key) not in (None, "", []):
                        st.write(label + ":", details[key])
                for link in source.get("evidence_refs") or []:
                    if isinstance(link, str) and link.startswith(("https://", "http://")):
                        st.link_button("Open activity source", link)


def _plan_view():
    plan = state_api.current_plan(workspace)
    profile = state_api.current_profile(workspace)
    st.subheader("Saved response")
    if plan is None:
        st.info("Load a saved example or save athlete information to begin.")
        active = workspace.get("active_job")
        if active:
            job = workspace["jobs"].get(active) or {}
            st.warning("A previous job is " + job.get("status", "still recorded") + ". Starting a new workspace does not cancel it.")
        return
    label = state_api.plan_status(workspace, service.source_versions())
    if label == "Plan checked":
        st.success(label)
    elif label in ("More information needed", "Outside the supported scope"):
        st.info(label)
    else:
        st.warning(label)
    st.caption("This response belongs to " + _profile_name(profile).lower() + ".")
    if plan.get("historical"):
        st.caption("Saved demonstration or imported history. A current model review has not been established.")
    response = plan["response"]
    st.write(response.get("explanation", ""))
    for question in response.get("questions") or []:
        st.write("• " + question)
    for issue in response.get("unresolved_issues") or []:
        st.write("• " + issue)
    for day in response.get("weekly_schedule") or []:
        st.markdown("**" + day["date"] + "**")
        for activity in day.get("activities") or []:
            timing = activity.get("timing") or {}
            interval = (str(timing.get("start_time")) + "–" + str(timing.get("end_time"))) if timing.get("start_time") and timing.get("end_time") else "Time not specified"
            duration = str(activity["duration_minutes"]) + " min" if activity.get("duration_minutes") is not None else "Duration not specified"
            existing = bool(activity.get("existing_commitment_refs"))
            st.write(("Existing commitment · " if existing else "Proposed · ") + activity.get("description", "") + " · " + interval + " · " + duration)
            resources = activity.get("resources") or {}
            equipment = ", ".join(str(row.get("quantity")) + " × " + row["name"] if row.get("quantity") is not None else row["name"] for row in resources.get("equipment") or [])
            if equipment or resources.get("space") or resources.get("participants") is not None:
                st.caption("Equipment: " + (equipment or "not specified") + " · Space: " + str(resources.get("space") or "not specified")
                    + " · Participants: " + str(resources.get("participants") if resources.get("participants") is not None else "not specified"))
        if day.get("rest_arrangements"):
            st.caption(day["rest_arrangements"])
    _findings(plan)
    _sources(plan)
    st.caption("Internal review describes the checks that ran. It is not a guarantee about training safety or results.")


def _edit_plan():
    plan = state_api.current_plan(workspace)
    st.subheader("Edit proposed activities")
    if plan is None or plan["response"].get("response_type") != "plan":
        st.info("A saved weekly plan is needed before editing activities.")
        return
    if plan.get("historical_readonly"):
        st.info("This historical view needs compatible source records before it can be edited.")
        return
    candidates = [row for row in state_api.editable_rows(plan) if not row.get("existing_commitment")]
    if not candidates:
        st.info("There are no proposed activities to edit. Change existing commitments through athlete information.")
        return
    ids = [row["activity_id"] for row in candidates]
    by_id = {row["activity_id"]: row for row in candidates}
    selected = st.selectbox("Proposed activity", ids, format_func=lambda value: by_id[value]["date"] + " · " + by_id[value]["description"], key="edit_activity_" + plan["plan_version"])
    row = by_id[selected]
    options = service.catalog_options()
    replacements = {"": "Keep this activity", **{item["catalog_id"]: item["name"] for item in options}}
    key = "edit_" + plan["plan_version"] + "_" + selected
    with st.form(key):
        c1, c2, c3 = st.columns(3)
        with c1:
            day = st.date_input("Activity date", value=date.fromisoformat(row["date"]), key=key + "_date")
            unknown_duration = st.checkbox("Duration not specified", value=row.get("duration_minutes") is None, key=key + "_duration_unknown")
            duration = st.number_input("Allocated minutes", min_value=0, value=row.get("duration_minutes") or 0, step=1, key=key + "_duration")
        with c2:
            start = st.text_input("Start time — HH:MM", value=row.get("start_time") or "", key=key + "_start")
            end = st.text_input("End time — HH:MM", value=row.get("end_time") or "", key=key + "_end")
        with c3:
            replacement = st.selectbox("Replace with an approved activity", list(replacements), format_func=lambda value: replacements[value], key=key + "_replacement")
        st.caption("Edit times and duration together. Saving checks the change and makes the earlier model review outdated.")
        submitted = st.form_submit_button("Save plan changes")
    if submitted:
        try:
            edit = {"activity_id": selected, "date": day.isoformat(), "start_time": _optional(start.strip()),
                    "end_time": _optional(end.strip()), "duration_minutes": None if unknown_duration else duration}
            if replacement:
                edit["replacement_id"] = replacement
            state_api.save_plan_changes(workspace, [edit], service.resolve_catalog, service.check_plan, service.source_versions())
            _message("success", "Changes saved. Schedule checks were updated; model review is needed.")
            st.rerun()
        except Exception as error:
            st.error("The changes were not saved: " + str(error))
    if st.button("Review saved changes", disabled=not readiness.get("review_ready") or _busy(), key="review_" + plan["plan_version"]):
        if not service.readiness().get("review_ready"):
            st.info("Model review is waiting for pilot testing.")
            return
        job_id = "app_" + uuid4().hex
        bindings = state_api.assessment_bindings(workspace, service.source_versions())
        started = state_api.begin_job(workspace, job_id, "review")
        if started["created"]:
            try:
                with st.spinner("Reviewing the saved version…"):
                    envelope = service.review_saved(state_api.current_profile(workspace), state_api.current_plan(workspace), job_id, workspace["session_id"])
                assessment = envelope.get("assessment", envelope)
                state_api.complete_job(workspace, job_id, {"status": envelope.get("status", assessment.get("status", "returned")), "assessment": assessment})
                attached = state_api.record_assessment(workspace, assessment, envelope.get("bindings", assessment.get("bindings", bindings)))
                if attached["attached"]:
                    _message("success" if assessment.get("internally_accepted") else "info",
                             "Review completed." if assessment.get("internally_accepted") else "Review completed. The saved response still needs attention.")
                elif not assessment.get("review_complete") or assessment.get("execution_status") != "completed":
                    _message("info", "The review could not complete. Saved changes still need review.")
                else:
                    _message("info", "Review saved against its original version; the active version changed.")
            except Exception as error:
                failure = _failed_job_outcome(error)
                state_api.complete_job(workspace, job_id, failure)
                _message("info" if failure["status"] == "blocked" else "error", "The review could not finish: " + str(error))
            st.rerun()
    if not readiness.get("review_ready"):
        st.caption("Model review is waiting for pilot testing. Saving changes still runs the available schedule checks.")


def _progress():
    st.subheader("This week's progress")
    sessions = state_api.trackable_sessions(workspace)
    if not sessions:
        st.info("There are no trackable training sessions in the saved response.")
        return
    counts = state_api.progress_summary(workspace)
    for column, label in zip(st.columns(3), ("completed", "pending", "skipped")):
        column.metric(label.title(), counts[label])
    st.caption("Skipped sessions stay in the total. These are self-reported completion records.")
    with st.form("progress_" + str(workspace.get("current_plan"))):
        changes = []
        for session in sessions:
            status = st.selectbox(session["date"] + " · " + session["description"], ["pending", "completed", "skipped"],
                index=["pending", "completed", "skipped"].index(session["status"]),
                format_func=str.title, key="progress_" + session["occurrence_id"] + "_" + session["activity_revision"])
            changes.append((session["occurrence_id"], status))
        save = st.form_submit_button("Update progress")
    if save:
        for occurrence, status in changes:
            state_api.update_progress(workspace, occurrence, status)
        _message("success", "Progress saved. The schedule and its review were not changed.")
        st.rerun()


def _export_restore():
    st.subheader("Download or restore")
    if state_api.current_profile(workspace) is not None:
        c1, c2 = st.columns(2)
        c1.download_button("Download saved snapshot", plan_exports.export_snapshot(workspace, service.source_versions()),
            file_name="champions_saved_snapshot.json", mime="application/json", width="stretch")
        if state_api.current_plan(workspace) is not None:
            c2.download_button("Download schedule CSV", plan_exports.export_schedule_csv(workspace),
                file_name="champions_weekly_schedule.csv", mime="text/csv", width="stretch")
    st.caption("Snapshots are local files you keep. Restored reviews remain historical until explicitly reviewed again.")
    uploaded = st.file_uploader("Choose a saved JSON snapshot", type=["json"], key="restore_upload")
    if _busy():
        st.caption("Restore is paused while a job is active or unresolved.")
    if st.button("Restore snapshot", disabled=uploaded is None or _busy(), key="restore_snapshot"):
        try:
            restored = plan_exports.restore_snapshot(uploaded.getvalue(), session_id=workspace["session_id"],
                validate_profile=service.validate_profile, validate_response=service.validate_response,
                resolve_catalog=service.resolve_catalog, check_plan=service.check_plan, source_versions=service.source_versions())
            st.session_state["champion_workspace"] = restored
            profile = state_api.current_profile(restored)
            _refresh_intake(profile["public_record"] if profile else None)
            _message("success", "Snapshot restored. Imported reviews are historical; no model request was made.")
            st.rerun()
        except Exception as error:
            st.error("The snapshot was not restored: " + str(error))


try:
    service = open_service(str(ROOT))
    readiness = service.readiness()
except Exception as error:
    st.title("Champions Athletic Map")
    st.error("Project setup needs attention: " + str(error))
    st.caption("Run the Step 29 setup cell from the project notebook, then reopen this app.")
    st.stop()

if "champion_workspace" not in st.session_state:
    st.session_state["champion_workspace"] = state_api.new_state()
    st.session_state["champion_form_epoch"] = 0
workspace = st.session_state["champion_workspace"]

st.title("Champions Athletic Map")
st.caption("A weekly basketball planning workspace for athletes, parents and coaches.")
notice = st.session_state.pop("champion_notice", None)
if notice:
    getattr(st, notice[0])(notice[1])
if not readiness.get("generation_ready"):
    st.info(readiness.get("message") or "Live planning is waiting for pilot testing. Saved examples, edits, progress and downloads remain available.")
with st.sidebar:
    st.subheader("Local prototype")
    st.write(_profile_name(state_api.current_profile(workspace)))
    st.caption("Demonstrations use fictional development profiles.")
    selected_example = st.selectbox("Saved example", list(range(1, 7)), format_func=lambda number: "Example " + str(number), key="demo_choice")
    if st.button("Load saved example", width="stretch", key="load_demo", disabled=_busy()):
        try:
            _load_example(selected_example - 1)
            st.rerun()
        except Exception as error:
            st.error("The saved example could not be loaded: " + str(error))
    if st.button("Start a new workspace", width="stretch", key="clear_workspace"):
        state_api.clear_workspace(workspace)
        _refresh_intake()
        _message("info", "The workspace is cleared. Saved jobs and unresolved requests remain recorded.")
        st.rerun()

intake_tab, plan_tab, edit_tab, progress_tab, files_tab = st.tabs(["Athlete information", "Saved response", "Edit & review", "Progress", "Files"])
with intake_tab:
    _intake()
with plan_tab:
    _plan_view()
with edit_tab:
    _edit_plan()
with progress_tab:
    _progress()
with files_tab:
    _export_restore()
st.divider()
st.caption("General basketball planning and recorded food facts. Medical diagnosis, injury rehabilitation and dietary prescriptions are outside this prototype.")
