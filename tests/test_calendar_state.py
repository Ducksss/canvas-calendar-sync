import datetime as dt
from pathlib import Path

import pytest

from canvas_calendar_sync.google_calendar import CalendarError, confirms_deleted, desired_event, index_owned, verify_event
from canvas_calendar_sync.state import State
from canvas_calendar_sync.sync import scheduled_due


def item():
    return {"sourceKey": "canvas:1:assignment:2", "fingerprint": "abc", "calendarTitle": "[Canvas] ABC — Work due", "calendarDescription": "Course: ABC\nCanvas: https://canvas.nus.edu.sg/x\nSynced automatically from NUS Canvas.", "dueAt": "2026-09-01T01:00:00Z", "eventEndAt": "2026-09-01T01:15:00Z"}


def test_event_contract():
    event = desired_event(item())
    assert event["visibility"] == "private" and event["transparency"] == "transparent"
    assert event["attendees"] == [] and "conferenceData" not in event
    assert event["extendedProperties"]["private"]["canvasSyncOwner"] == "canvas-calendar-sync-v1"
    assert {x["minutes"] for x in event["reminders"]["overrides"]} == {60, 1440}


def test_readback_accepts_equivalent_calendar_timezone_representation():
    event = desired_event(item())
    event["start"]["dateTime"] = "2026-09-01T09:00:00+08:00"
    event["end"]["dateTime"] = "2026-09-01T09:15:00+08:00"
    verify_event(event, item())


def test_readback_rejects_a_different_instant():
    event = desired_event(item())
    event["start"]["dateTime"] = "2026-09-01T09:01:00+08:00"
    with pytest.raises(CalendarError) as caught:
        verify_event(event, item())
    assert caught.value.code == "calendar_readback_mismatch"


def test_delete_readback_accepts_only_cancelled_events():
    assert confirms_deleted({"status": "cancelled"})
    assert not confirms_deleted({"status": "confirmed"})
    assert not confirms_deleted({})


def test_duplicate_owned_event_fails():
    events = [{"extendedProperties": {"private": {"canvasSourceKey": "same"}}}, {"extendedProperties": {"private": {"canvasSourceKey": "same"}}}]
    with pytest.raises(CalendarError) as caught: index_owned(events)
    assert caught.value.code == "duplicate_owned_event"


def test_sqlite_permissions_and_scheduled_guard(tmp_path: Path):
    state = State(tmp_path / "state.sqlite3")
    try:
        assert scheduled_due(state, dt.datetime(2026, 8, 22, 2, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))) == (False, "before_daily_window")
        assert scheduled_due(state, dt.datetime(2026, 8, 22, 3, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))) == (True, "2026-08-22")
        state.set_meta("last_successful_singapore_date", "2026-08-22")
        assert scheduled_due(state, dt.datetime(2026, 8, 22, 4, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))) == (False, "already_succeeded_today")
    finally: state.close()
    assert (tmp_path / "state.sqlite3").stat().st_mode & 0o777 == 0o600
