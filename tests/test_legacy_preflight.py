import pytest

from canvas_calendar_sync import sync
from canvas_calendar_sync.google_calendar import CalendarError


@pytest.mark.parametrize("status", [404, 410])
def test_removed_legacy_event_does_not_block_later_sync(monkeypatch, status):
    def missing(*args):
        raise CalendarError("calendar_api_error", "Event absent.", status)
    monkeypatch.setattr(sync, "get_event", missing)
    assert sync.preflight_legacy(object(), {"canvas:1:assignment:2": {"eventId": "old"}}, {}) == {}


def test_cancelled_legacy_event_does_not_require_marker(monkeypatch):
    monkeypatch.setattr(sync, "get_event", lambda *args: {"status": "cancelled"})
    assert sync.preflight_legacy(object(), {"canvas:1:assignment:2": {"eventId": "old"}}, {}) == {}


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_legacy_access_failure_still_aborts(monkeypatch, status):
    def unavailable(*args):
        raise CalendarError("calendar_api_error", "Read failed.", status)
    monkeypatch.setattr(sync, "get_event", unavailable)
    with pytest.raises(CalendarError):
        sync.preflight_legacy(object(), {"canvas:1:assignment:2": {"eventId": "old"}}, {})
