import datetime as dt
from pathlib import Path

import pytest

from canvas_calendar_sync import config
from canvas_calendar_sync.google_calendar import CalendarError
from canvas_calendar_sync.state import State
from canvas_calendar_sync.sync import reconcile


class Request:
    def __init__(self, fn): self.fn = fn
    def execute(self, **_): return self.fn()


class Events:
    def __init__(self, stored, fail_insert=False):
        self.stored, self.fail_insert, self.deleted = stored, fail_insert, []
    def list(self, **kwargs): return Request(lambda: {"items": list(self.stored.values())})
    def get(self, eventId, **kwargs):
        return Request(lambda: self.stored.get(eventId, {"status": "cancelled"}))
    def insert(self, body, **kwargs):
        def action():
            if self.fail_insert: raise OSError("offline")
            event = {"id": "new", **body}; self.stored["new"] = event; return event
        return Request(action)
    def update(self, eventId, body, **kwargs):
        def action():
            self.stored[eventId] = {"id": eventId, **body}
            return self.stored[eventId]
        return Request(action)
    def delete(self, eventId, **kwargs):
        def action(): self.deleted.append(eventId); self.stored.pop(eventId, None); return None
        return Request(action)


class API:
    def __init__(self, events): self._events = events
    def events(self): return self._events


def payload():
    return {"courseCount": 1, "itemCount": 1, "items": [{"sourceKey": "canvas:1:assignment:2", "fingerprint": "abc", "calendarTitle": "Title", "calendarDescription": "Description", "dueAt": "2027-01-01T00:00:00Z", "eventEndAt": "2027-01-01T00:15:00Z"}]}


def test_partial_create_failure_never_deletes(monkeypatch, tmp_path: Path):
    stale = {"id": "stale", "start": {"dateTime": "2027-02-01T00:00:00Z"}, "extendedProperties": {"private": {"canvasSyncOwner": config.settings.owner, "canvasSourceKey": "canvas:old", "canvasFingerprint": "old"}}}
    events = Events({"stale": stale}, fail_insert=True)
    state = State(tmp_path / "state.sqlite3")
    try:
        with pytest.raises(CalendarError): reconcile(API(events), state, payload())
    finally: state.close()
    assert events.deleted == [] and "stale" in events.stored


def test_dry_run_has_zero_mutations(monkeypatch, tmp_path: Path):
    events = Events({})
    state = State(tmp_path / "state.sqlite3")
    try: result = reconcile(API(events), state, payload(), dry_run=True)
    finally: state.close()
    assert result["counts"]["create"] == 1 and events.stored == {}


def test_create_unchanged_update_delete_lifecycle(tmp_path):
    events, data = Events({}), payload()
    data["items"][0]["dueAt"] = "2090-01-01T00:00:00Z"
    data["items"][0]["eventEndAt"] = "2090-01-01T00:15:00Z"
    state = State(tmp_path / "state.sqlite3")
    try:
        assert reconcile(API(events), state, data)["counts"]["create"] == 1
        assert reconcile(API(events), state, data)["counts"]["unchanged"] == 1
        data["items"][0].update(calendarTitle="Changed title", fingerprint="changed")
        assert reconcile(API(events), state, data)["counts"]["update"] == 1
        assert list(events.stored) == ["new"]
        assert events.stored["new"]["summary"] == "Changed title"
        assert reconcile(API(events), state, {"courseCount": 1, "itemCount": 0, "items": []})["counts"]["delete"] == 1
        assert events.stored == {}
        assert state.event_count() == 0
    finally:
        state.close()
