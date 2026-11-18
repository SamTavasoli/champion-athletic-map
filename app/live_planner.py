"""Our live basketball planning workspace."""

from datetime import date, datetime, timedelta
from pathlib import Path
import json
import sys

import streamlit as st


APP = Path(__file__).resolve().parent
ROOT = APP.parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
from live_engine import run_generation, validate_profile
from live_resources import candidates, food_facts, food_options, load_resources


st.set_page_config(page_title="Champions Athletic Map", page_icon="🏀", layout="wide")
st.title("Champions Athletic Map")
st.write("Build a weekly basketball draft from an athlete's goals, time and equipment.")
st.caption("Live development workflow · llama3.1:8b · Use fictional athlete information.")


@st.cache_resource(show_spinner="Opening our approved references…")
def open_resources(project_root):
    return load_resources(Path(project_root))


def hhmm(value):
    return value.strftime("%H:%M")


def snapshot_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def table_rows(value):
    records = value.to_dict("records") if hasattr(value, "to_dict") else value
    return [{key: str(item or "").strip() for key, item in row.items()} for row in records
            if any(str(item or "").strip() for item in row.values())]


try:
    resources = open_resources(str(ROOT))
except Exception as error:
    st.error("Our planning references could not be opened: " + str(error))
    st.stop()

goals = {"Ball handling": "dribbling", "Shooting": "shooting", "Passing": "passing",
         "Footwork": "footwork", "Defense": "defense", "Finishing": "finishing"}
courts = {"Full court": "full_court", "Half court": "half_court",
          "Single hoop area": "single_hoop_area", "No court or hoop": "none"}
food_choices = food_options(resources)
food_names = {row["id"]: row["name"] for row in food_choices}

with st.expander("Athlete information", expanded=True):
    with st.form("new_athlete"):
        label = st.text_input("Athlete label", value="Demo athlete", max_chars=60)
        c1, c2, c3 = st.columns(3)
        age = c1.number_input("Age", min_value=13, max_value=17, value=16, step=1)
        experience = c2.selectbox("Basketball experience", ["beginner", "intermediate", "advanced"])
        goal_label = c3.selectbox("Basketball goal", list(goals))
        c1, c2 = st.columns(2)
        today = date.today()
        week = c1.date_input("Week starts", value=today - timedelta(days=today.weekday()))
        zone = c2.text_input("Time zone", value="America/Los_Angeles", max_chars=60)
        dates = [week + timedelta(days=offset) for offset in range(7)]
        days = st.multiselect("Available days", list(range(7)), default=[0, 2, 5],
                              format_func=lambda i: dates[i].strftime("%A, %b %d"))
        st.caption("The available start and end times apply to every selected day.")
        c1, c2 = st.columns(2)
        start = c1.time_input("Available from", value=datetime.strptime("17:30", "%H:%M").time())
        end = c2.time_input("Available until", value=datetime.strptime("18:00", "%H:%M").time())
        st.markdown("**Existing practices, games or other commitments**")
        no_commitments = st.checkbox("No existing commitments this week", value=True)
        commitments = st.data_editor(
            [{"date": "", "start_time": "", "end_time": "", "description": ""}],
            num_rows="dynamic", hide_index=True, width="stretch", key="existing_commitments",
            column_config={"date": st.column_config.TextColumn("Date — YYYY-MM-DD"),
                           "start_time": st.column_config.TextColumn("Start — HH:MM"),
                           "end_time": st.column_config.TextColumn("End — HH:MM"),
                           "description": st.column_config.TextColumn("Commitment")})
        st.caption("Uncheck the box when entering commitments. These are preserved in the calendar.")
        c1, c2, c3 = st.columns(3)
        balls = c1.number_input("Basketballs available", min_value=0, max_value=20, value=1, step=1)
        markers = c1.number_input("Cones or markers available", min_value=0, max_value=20, value=0, step=1)
        hoop = c1.checkbox("Hoop is available", value=True)
        participants = c2.number_input("Total participants", min_value=1, max_value=20, value=1, step=1)
        court_label = c3.selectbox("Practice space", list(courts))
        c1, c2 = st.columns(2)
        sessions = c1.number_input("Additional sessions requested", min_value=1, max_value=3, value=2, step=1)
        minutes = c2.selectbox("Minutes per additional session", [10, 15, 20, 25, 30], index=1)
        limitations = st.text_area("Reported limitations, if any — one per line", max_chars=300)
        st.markdown("**Optional recorded food facts**")
        selected_food = st.selectbox("Food", [None] + list(food_names),
                                    format_func=lambda value: "No food lookup" if value is None else food_names[value])
        grams = st.number_input("Food amount in grams", min_value=1, max_value=2000, value=100, step=1)
        if not food_choices:
            st.caption("The recorded food reference is unavailable. Training can still be tested.")
        submitted = st.form_submit_button("Generate plan", type="primary", width="stretch")

if submitted:
    st.session_state.pop("live_result", None)
    equipment = ["basketball"] * int(balls) + ["marker"] * int(markers) + (["hoop"] if hoop else [])
    practices = table_rows(commitments)
    profile = {"label": label.strip(), "age": int(age), "experience": experience,
               "goal": goals[goal_label], "week_start": week.isoformat(), "timezone": zone.strip(),
               "availability": [{"date": dates[i].isoformat(), "start_time": hhmm(start),
                                  "end_time": hhmm(end)} for i in days],
               "existing_practices": [] if no_commitments else practices,
               "equipment": equipment, "participants": int(participants), "court": courts[court_label],
               "requested_sessions": int(sessions), "session_minutes": int(minutes),
               "reported_limitations": [line.strip() for line in limitations.splitlines() if line.strip()]}
    errors = validate_profile(profile)
    if no_commitments and practices:
        errors.append("Uncheck 'No existing commitments this week' to include the commitments entered below it.")
    if errors:
        for error in errors:
            st.error(error)
    else:
        eligible = candidates(resources, profile["goal"], equipment, int(participants), profile["court"], int(age))
        if not eligible:
            st.info("Our references do not establish a resource match for this goal and setup. "
                    "Try another supported goal or provide the equipment and participants required by a recorded drill.")
        else:
            facts = None
            if selected_food is not None:
                try:
                    facts = food_facts(resources, selected_food, str(grams))
                except Exception as error:
                    st.error("The food lookup could not be completed: " + str(error))
            with st.spinner("Our local model is preparing the weekly draft…"):
                result = run_generation(ROOT, profile, eligible, resources["rules"], resources["source_files"])
            result["recorded_food_facts"] = facts
            st.session_state["live_result"] = result

result = st.session_state.get("live_result")
if result:
    raw_body = result.get("parsed_response")
    body = raw_body if result.get("format_valid") and isinstance(raw_body, dict) else {}
    report = result.get("assessment") or {}
    profile = result.get("profile") or {}
    supplied = result.get("selected_candidates") or []
    by_id = {row["id"]: row for row in supplied}
    status = result.get("status", "unavailable")
    if status == "draft_ready":
        st.success("The model returned a draft. The implemented schedule checks passed.")
    elif status in ("clarification", "constraint_conflict", "outside_scope"):
        st.info("Model response: " + status.replace("_", " "))
    elif body:
        st.warning("The model returned a reply with items that need attention.")
    else:
        st.error("A new plan was not completed.")
    if result.get("error"):
        st.write(result["error"])
    for issue in report.get("issues") or []:
        st.write("• " + str(issue))
    if body:
        st.write(body.get("explanation", ""))
        for question in body.get("questions") or []:
            st.write("• " + question)
    st.caption("This draft is not fully verified. Goal suitability, total training load and source coverage still need checking.")
    if profile:
        st.write("Draft for **" + profile.get("label", "Athlete") + "** · Goal: " + profile.get("goal", "").replace("_", " "))
    training, recovery, food_tab, evidence = st.tabs(["Training", "Recovery", "Food facts", "Generation details"])
    with training:
        if body.get("response_type") == "plan":
            start_date = date.fromisoformat(profile["week_start"])
            for offset in range(7):
                current = (start_date + timedelta(days=offset)).isoformat()
                st.markdown("**" + current + "**")
                existing = [row for row in profile.get("existing_practices", []) if row["date"] == current]
                proposed = [row for row in body.get("sessions", []) if row.get("date") == current]
                for row in existing:
                    st.write("Existing: " + row["description"] + " · " + row["start_time"] + "–" + row["end_time"])
                for row in proposed:
                    drill = by_id.get(row.get("drill_id"), {})
                    name = drill.get("name") or "Unrecognized activity: " + str(row.get("drill_id"))
                    st.write("Proposed: " + name + " · " + str(row.get("start_time")) + " · "
                             + str(row.get("duration_minutes")) + " minutes allocated")
                    st.write(row.get("reason", ""))
                    if drill:
                        with st.expander("Activity instructions — " + name):
                            st.write(drill.get("instructions", ""))
                            if drill.get("source_prescription"):
                                st.write("Recorded prescription: " + str(drill["source_prescription"]))
                            if drill.get("source_url"):
                                st.link_button("Activity source", drill["source_url"])
                if not existing and not proposed:
                    st.write("No training scheduled in this draft.")
        else:
            st.write("No weekly plan was returned.")
    with recovery:
        by_rule = {row["id"]: row for row in resources["rules"]}
        for item in body.get("recovery_guidance") or []:
            st.write(item.get("statement", ""))
            for identifier in item.get("source_rule_ids") or []:
                rule = by_rule.get(identifier, {})
                values = rule.get("source_values") or {}
                if (identifier == "AAP_WEEKLY_SPORT_REST" and values.get("minimum_guidance") == 1
                        and values.get("preferred_range") == [1, 2] and rule.get("source_unit") == "days/week"):
                    st.write("Recorded guidance: at least one day per week away from competition and "
                             "sport-specific training, with one to two days preferred. Other organized sports count; "
                             "free play is outside this guidance.")
                if rule.get("source_url"):
                    st.link_button("Recovery source — " + identifier, rule["source_url"])
        if not body.get("recovery_guidance"):
            st.write("No recovery guidance was returned.")
        st.caption("General rest and participation guidance. This is not injury rehabilitation.")
    with food_tab:
        facts = result.get("recorded_food_facts")
        if facts and facts.get("status") == "available":
            st.write(str(facts.get("grams", "")) + " g · " + str(facts.get("description", "")))
            st.dataframe([{"Nutrient": row.get("name"), "Amount": row.get("amount"),
                           "Unit": row.get("unit"), "Status": row.get("status")}
                          for row in facts.get("nutrients") or []], hide_index=True, width="stretch")
            for link in facts.get("source_refs") or []:
                st.link_button("Food source", link)
        elif facts:
            st.info("Food lookup: " + str(facts.get("reason") or facts.get("status")))
        else:
            st.write("No recorded food lookup was completed for this draft.")
        st.caption("Values come from our food reference and quantity calculation. This is not a personalized meal plan.")
    with evidence:
        st.write("Model: llama3.1:8b")
        st.write("Workflow: live application draft; separate from the four evaluated planner versions.")
        st.write("Saved job: " + str(result.get("job_id", "not submitted")))
        st.json(report.get("checks") or {})
        with st.expander("Parsed model reply"):
            if raw_body is not None:
                st.json(raw_body)
            else:
                st.write("The reply could not be parsed. The original response is retained in the saved job folder.")
        st.caption("A displayed reply is generated only by a model request. No saved example is substituted.")
    st.download_button("Download draft and generation record", snapshot_bytes(result),
                       file_name="champions_weekly_draft.json", mime="application/json")
