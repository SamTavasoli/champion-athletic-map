"""We exercise the actual interface with a scripted service and fictional sessions."""

from copy import deepcopy
import sys
from types import ModuleType

import pytest

from app_fixtures import FakePrototypeService, ROOT, state


pytestmark = pytest.mark.requirement("30.9:streamlit-interactions")


@pytest.fixture
def app_factory(tmp_path, monkeypatch):
    # AppTest runs the real interface. Only the service boundary is scripted.
    pytest.importorskip("streamlit", reason="Streamlit is required for the interface checks.")
    from streamlit.testing.v1 import AppTest
    fake = ModuleType("champion_athletic_map.interactive_review")
    fake.PrototypeService = FakePrototypeService
    monkeypatch.setitem(sys.modules, "champion_athletic_map.interactive_review", fake)
    monkeypatch.syspath_prepend(str(ROOT / "src"))
    monkeypatch.setenv("CHAMPION_PROJECT_ROOT", str(tmp_path))
    FakePrototypeService.instances.clear()
    def create():
        result = AppTest.from_file(str(ROOT / "app/streamlit_app.py"), default_timeout=20).run()
        assert not result.exception, str(result.exception)
        return result
    return create


def labelled(elements, label):
    return next(element for element in elements if element.label == label)


def workspace(app):
    return app.session_state["champion_workspace"]


def load_example(app):
    app.button(key="load_demo").click().run()
    assert not app.exception, str(app.exception)
    return workspace(app)


def assert_no_model_calls():
    assert FakePrototypeService.instances
    assert all(item.calls["generation"] == item.calls["review"] == 0 for item in FakePrototypeService.instances)


def complete_first_session(app):
    row = state.trackable_sessions(workspace(app))[0]
    key = "progress_" + row["occurrence_id"] + "_" + row["activity_revision"]
    app.selectbox(key=key).select("completed")
    labelled(app.button, "Update progress").click().run()
    assert state.progress_summary(workspace(app))["completed"] == 1


def test_form_drafts_and_profile_save_do_not_generate(app_factory):
    app = app_factory()
    assert labelled(app.button, "Generate plan").disabled is True
    load_example(app)
    original = deepcopy(state.current_profile(workspace(app)))
    labelled(app.text_area, "What would you like to plan?").input("An unsaved fictional request.")
    assert state.current_profile(workspace(app)) == original
    labelled(app.button, "Save athlete information").click().run()
    assert not app.exception and not app.error
    assert state.current_profile(workspace(app))["public_record"]["input"]["athlete_request"] == "An unsaved fictional request."
    assert state.current_plan(workspace(app)) is None
    assert_no_model_calls()


def test_pending_edit_keeps_other_completed_session_and_updates_saved_calendar(app_factory):
    app = app_factory()
    load_example(app)
    complete_first_session(app)
    previous = state.current_plan(workspace(app))
    labelled(app.selectbox, "Proposed activity").select("wednesday").run()
    labelled(app.number_input, "Allocated minutes").set_value(15)
    labelled(app.text_input, "End time — HH:MM").input("17:45")
    labelled(app.button, "Save plan changes").click().run()
    assert not app.exception and not app.error
    changed = state.current_plan(workspace(app))
    assert changed["plan_version"] != previous["plan_version"]
    edited = next(row for row in state.editable_rows(changed) if row["activity_id"] == "wednesday")
    assert (edited["duration_minutes"], edited["end_time"]) == (15, "17:45")
    assert state.progress_summary(workspace(app))["completed"] == 1
    assert changed["model_review_stale"] is True
    assert labelled(app.button, "Review saved changes").disabled is True
    assert_no_model_calls()


def test_editing_completed_session_resets_only_that_session(app_factory):
    app = app_factory()
    load_example(app)
    complete_first_session(app)
    labelled(app.selectbox, "Proposed activity").select("monday").run()
    labelled(app.number_input, "Allocated minutes").set_value(15)
    labelled(app.text_input, "End time — HH:MM").input("17:45")
    labelled(app.button, "Save plan changes").click().run()
    assert not app.exception and not app.error
    assert state.progress_summary(workspace(app))["pending"] == 3
    assert state.progress_summary(workspace(app))["completed"] == 0
    assert_no_model_calls()


def test_browser_sessions_keep_independent_profiles_and_progress(app_factory):
    first, second = app_factory(), app_factory()
    load_example(first)
    load_example(second)
    complete_first_session(first)
    assert workspace(first)["session_id"] != workspace(second)["session_id"]
    assert state.progress_summary(workspace(first))["completed"] == 1
    assert state.progress_summary(workspace(second))["completed"] == 0
    assert_no_model_calls()


def test_form_keeps_unknown_commitments_distinct_from_confirmed_empty(app_factory):
    app = app_factory()
    load_example(app)
    labelled(app.checkbox, "Existing commitments are confirmed").uncheck()
    labelled(app.button, "Save athlete information").click().run()
    assert not app.exception and not app.error
    assert state.current_profile(workspace(app))["public_record"]["input"]["existing_commitments"] is None
    labelled(app.checkbox, "Existing commitments are confirmed").check()
    labelled(app.button, "Save athlete information").click().run()
    assert not app.exception and not app.error
    assert state.current_profile(workspace(app))["public_record"]["input"]["existing_commitments"] == []
    assert_no_model_calls()
