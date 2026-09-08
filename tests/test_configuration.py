import datetime as dt
import json
import plistlib
from dataclasses import replace
from pathlib import Path
from urllib.request import Request

import pytest

from canvas_calendar_sync import config
from canvas_calendar_sync.canvas import CanvasError, SameOriginRedirect, normalize_assignment
from canvas_calendar_sync.cli import main
from canvas_calendar_sync.google_calendar import CalendarError, index_owned, list_owned
from canvas_calendar_sync.scheduler import build_agent
from canvas_calendar_sync.state import State
from canvas_calendar_sync.sync import scheduled_due


@pytest.mark.parametrize("data", [
    {"canvas_url": "http://canvas.example.edu"},
    {"canvas_url": "https://user:password@canvas.example.edu"},
    {"canvas_url": "https://canvas.example.edu/?token=bad"},
    {"canvas_url": "https://canvas.example.edu/api"},
    {"canvas_url": "https://canvas.example.edu:444"},
    {"canvas_url": "https://canvas.example.edu", "timezone": "Not/AZone"},
    {"canvas_url": "https://canvas.example.edu", "daily_hour": 24},
    {"canvas_url": "https://canvas.example.edu", "daily_minute": -1},
    {"canvas_url": "https://canvas.example.edu", "token": "must-not-be-stored"},
])
def test_invalid_or_secret_configuration_is_rejected(data):
    with pytest.raises(config.ConfigError):
        config.validate(data)


def test_init_round_trip_and_no_overwrite(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config, "APP_DIR", tmp_path / "new-profile")
    assert main(["init", "--canvas-url", "https://SCHOOL.example:443", "--timezone", "America/New_York", "--calendar-id", "coursework", "--daily-hour", "7", "--daily-minute", "30"]) == 0
    saved = config.load()
    assert saved.canvas_url == "https://school.example/"
    assert saved.timezone == "America/New_York"
    assert saved.calendar_id == "coursework"
    path = config.APP_DIR / "config.json"
    assert path.stat().st_mode & 0o777 == 0o600
    before = path.read_bytes()
    assert main(["init", "--canvas-url", "https://different.example", "--timezone", "UTC"]) == 2
    assert path.read_bytes() == before


def test_origin_and_calendar_have_separate_ownership():
    original = config.settings
    assert original.owner != replace(original, canvas_url="https://another.example/").owner
    assert original.owner != replace(original, calendar_id="other").owner
    assert original.owner == replace(original, timezone="Europe/London").owner


def test_state_refuses_changed_identity(monkeypatch, tmp_path):
    state = State(tmp_path / "state.sqlite3")
    try:
        state.bind_identity()
        monkeypatch.setattr(config, "settings", replace(config.settings, canvas_url="https://another.example/"))
        with pytest.raises(config.ConfigError):
            state.bind_identity()
    finally:
        state.close()


def test_cross_origin_redirect_rejected_before_forwarding_token():
    request = Request("https://canvas.example.edu/api/v1/courses", headers={"Authorization": "Bearer fixture"})
    with pytest.raises(CanvasError):
        SameOriginRedirect().redirect_request(request, None, 302, "Found", {}, "https://other.example/login")


def test_normalization_uses_configured_site(monkeypatch):
    monkeypatch.setattr(config, "settings", replace(config.settings, canvas_url="https://school.example/"))
    found = normalize_assignment({"id": 2, "due_at": "2030-01-02T00:00:00Z", "html_url": "/courses/1/assignments/2"}, {"id": 1}, dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc))
    assert found["htmlUrl"] == "https://school.example/courses/1/assignments/2"
    assert "Synced automatically from Canvas." in found["calendarDescription"]


@pytest.mark.parametrize("zone,before,after", [
    ("America/New_York", "2026-03-08T06:59:00+00:00", "2026-03-08T07:00:00+00:00"),
    ("Asia/Kathmandu", "2026-01-01T21:14:00+00:00", "2026-01-01T21:15:00+00:00"),
])
def test_schedule_uses_configured_zone_including_dst_and_fractional_offsets(monkeypatch, tmp_path, zone, before, after):
    monkeypatch.setattr(config, "settings", replace(config.settings, timezone=zone))
    state = State(tmp_path / "state.sqlite3")
    try:
        assert not scheduled_due(state, dt.datetime.fromisoformat(before))[0]
        assert scheduled_due(state, dt.datetime.fromisoformat(after))[0]
        state.set_meta("last_successful_local_date", scheduled_due(state, dt.datetime.fromisoformat(after))[1])
        assert scheduled_due(state, dt.datetime.fromisoformat(after)) == (False, "already_succeeded_today")
    finally:
        state.close()


def test_failed_scheduled_run_waits_an_hour(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "settings", replace(config.settings, timezone="UTC"))
    state = State(tmp_path / "state.sqlite3")
    try:
        state.set_meta("last_scheduled_attempt", "2026-01-01T03:00:00+00:00")
        assert scheduled_due(state, dt.datetime(2026, 1, 1, 3, 59, tzinfo=dt.timezone.utc)) == (False, "retry_cooldown")
        assert scheduled_due(state, dt.datetime(2026, 1, 1, 4, tzinfo=dt.timezone.utc))[0]
    finally:
        state.close()


def test_scheduler_generates_profile_specific_paths(tmp_path):
    executable = tmp_path / "some folder" / "python"
    agent = plistlib.loads(plistlib.dumps(build_agent(executable)))
    assert agent["ProgramArguments"][0] == str(executable)
    assert agent["EnvironmentVariables"]["CANVAS_CALENDAR_SYNC_HOME"] == str(config.APP_DIR)
    assert agent["StartInterval"] == 60
    assert agent["RunAtLoad"] is True
    assert "StartCalendarInterval" not in agent


def test_calendar_pagination_uses_target_and_is_bounded(monkeypatch):
    monkeypatch.setattr(config, "settings", replace(config.settings, calendar_id="owned-calendar"))
    calls = []

    class API:
        def events(self): return self
        def list(self, **kwargs):
            calls.append(kwargs)
            return self
        def execute(self, **kwargs):
            return {"items": [], "nextPageToken": "repeated"}

    with pytest.raises(CalendarError, match="repeated"):
        list_owned(API())
    assert len(calls) == 2
    assert all(call["calendarId"] == "owned-calendar" for call in calls)


def test_foreign_ownership_cannot_enter_reconciliation():
    with pytest.raises(CalendarError) as caught:
        index_owned([{"extendedProperties": {"private": {"canvasSourceKey": "same", "canvasSyncOwner": "foreign"}}}])
    assert caught.value.code == "foreign_event"
