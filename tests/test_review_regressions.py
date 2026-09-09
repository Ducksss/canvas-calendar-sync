"""Offline regressions for the pre-merge safety review."""
import datetime as dt
import urllib.request

import pytest

from canvas_calendar_sync import canvas, config, sync


NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


@pytest.mark.parametrize("courses,assignments", [
    ([{"name": "missing identity"}], []),
    ([{"id": 1}], [{"id": 2, "due_at": "not-a-date"}]),
    ([{"id": 1}], [{"id": 2}]),
    ([{"id": 1}], [{"id": None, "due_at": "2090-01-01T00:00:00Z"}]),
])
def test_malformed_discovery_stops_before_calendar(monkeypatch, courses, assignments):
    class FakeCanvas:
        def get_all(self, path, params=()):
            if path == "/api/v1/courses": return courses
            if path.endswith("/assignments"): return assignments
            return []

    class UntouchedCalendar:
        def events(self):
            pytest.fail("Incomplete discovery reached Calendar")

    monkeypatch.setattr(sync, "CanvasClient", lambda _token: FakeCanvas())
    monkeypatch.setattr(sync, "keychain_token", lambda: "fixture")
    with pytest.raises(canvas.CanvasError) as caught:
        sync.run_sync(UntouchedCalendar(), None)
    assert caught.value.code == "malformed_response"


def test_explicit_null_deadline_is_legitimate():
    assert canvas.normalize_assignment({"id": 2, "due_at": None}, {"id": 1}, NOW) is None


@pytest.mark.parametrize("link", ['broken; rel="next"', '<>; rel="next"'])
def test_malformed_next_link_is_not_end_of_pagination(link):
    with pytest.raises(canvas.CanvasError):
        canvas.parse_next_link(link)


def test_redirect_checks_origin_before_forwarding_authorization():
    origin = getattr(canvas, "BASE_URL", None) or config.settings.canvas_url
    request = urllib.request.Request(origin + "api/v1/courses", headers={"Authorization": "Bearer fixture"})
    with pytest.raises(canvas.CanvasError):
        canvas.SameOriginRedirect().redirect_request(request, None, 302, "Found", {}, "https://other.example/login")
    redirected = canvas.SameOriginRedirect().redirect_request(request, None, 302, "Found", {}, origin + "api/v1/courses?page=2")
    assert redirected.get_header("Authorization") == "Bearer fixture"


@pytest.mark.parametrize("kind", ["peer_review_sub_assignment", "sub_assignment", "assessment_request"])
def test_independent_planner_deadline_survives_parent_assignment_dedup(kind):
    item = {"course_id": 1, "plannable_type": kind, "plannable_id": 9,
            "plannable": {"id": 9, "assignment_id": 2, "due_at": "2026-01-03T00:00:00Z"}}
    result = canvas.normalize_planner(item, {"1": {"id": 1}}, {("1", "2")}, NOW)
    assert result is not None
    assert result["itemType"] == kind
    assert result["dueAt"] == "2026-01-03T00:00:00Z"
