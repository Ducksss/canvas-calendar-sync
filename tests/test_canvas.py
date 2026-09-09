import datetime as dt
import io
import json
import subprocess
import urllib.error
from types import SimpleNamespace

import pytest

from canvas_calendar_sync.canvas import CanvasClient, CanvasError, discover, keychain_token, normalize_assignment, parse_next_link


class Response:
    def __init__(self, payload, link=None):
        self.payload = payload; self.headers = {"Link": link} if link else {}
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self): return json.dumps(self.payload).encode()


def test_opaque_pagination_is_followed():
    pages = [Response([{"id": 1}], '<https://canvas.nus.edu.sg/api/v1/courses?page=opaque>; rel="next"'), Response([{"id": 2}])]
    client = CanvasClient("secret", opener=lambda *_a, **_k: pages.pop(0))
    assert [x["id"] for x in client.get_all("/api/v1/courses")] == [1, 2]


def test_cross_origin_pagination_fails():
    client = CanvasClient("secret", opener=lambda *_a, **_k: Response([], '<https://evil.example/page>; rel="next"'))
    with pytest.raises(CanvasError, match="outside"):
        client.get_all("/api/v1/courses")


def test_throttle_exhaustion_fails():
    error = urllib.error.HTTPError("https://canvas.nus.edu.sg/api/v1/courses", 429, "", {}, io.BytesIO())
    client = CanvasClient("secret", opener=lambda *_a, **_k: (_ for _ in ()).throw(error), sleeper=lambda _: None)
    with pytest.raises(CanvasError) as caught: client.get_all("/api/v1/courses")
    assert caught.value.code == "throttled"


def test_transient_server_error_retries_then_succeeds():
    calls, delays = [], []

    def opener(*_args, **_kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.HTTPError("https://canvas.nus.edu.sg/api/v1/courses", 503, "", {}, io.BytesIO())
        return Response([])

    client = CanvasClient("secret", opener=opener, sleeper=delays.append)
    assert client.request_page("https://canvas.nus.edu.sg/api/v1/courses").items == []
    assert len(calls) == 3
    assert delays == [1.0, 2.0]


def test_transport_retries_then_succeeds():
    calls, delays = [], []

    def opener(*_args, **_kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.URLError("temporary failure")
        return Response([{"id": 1}])

    client = CanvasClient("secret", opener=opener, sleeper=delays.append)
    assert client.request_page("https://canvas.nus.edu.sg/api/v1/courses").items == [{"id": 1}]
    assert len(calls) == 3
    assert delays == [1.0, 2.0]


def test_transport_retry_exhaustion_preserves_safe_type():
    calls, delays = [], []

    def opener(*_args, **_kwargs):
        calls.append(1)
        raise TimeoutError("message must not be logged")

    client = CanvasClient("secret", opener=opener, sleeper=delays.append)
    with pytest.raises(CanvasError) as caught:
        client.request_page("https://canvas.nus.edu.sg/api/v1/courses")
    assert len(calls) == 4
    assert delays == [1.0, 2.0, 4.0]
    assert caught.value.code == "transport_error"
    assert caught.value.cause_type == "TimeoutError"
    assert "message must not be logged" not in str(caught.value)


def test_canvas_keychain_retries_transient_command_failures():
    results = [
        SimpleNamespace(returncode=1, stdout=""),
        SimpleNamespace(returncode=1, stdout=""),
        SimpleNamespace(returncode=0, stdout="replacement-token\n"),
    ]
    calls, delays = [], []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        return results.pop(0)

    assert keychain_token(runner=runner, sleeper=delays.append) == "replacement-token"
    assert len(calls) == 3
    assert delays == [1.0, 2.0]
    assert calls[0][1]["timeout"] == 10


def test_canvas_keychain_retry_exhaustion_is_bounded():
    calls, delays = [], []

    def runner(*_args, **_kwargs):
        calls.append(1)
        raise subprocess.TimeoutExpired("security", 10)

    with pytest.raises(CanvasError) as caught:
        keychain_token(runner=runner, sleeper=delays.append)
    assert len(calls) == 4
    assert delays == [1.0, 2.0, 4.0]
    assert caught.value.cause_type == "TimeoutExpired"


def test_user_due_date_and_submission_retained():
    now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    item = normalize_assignment({"id": 7, "name": "Work", "due_at": "2026-01-02T00:00:00Z", "published": True, "submission": {"workflow_state": "submitted"}, "html_url": "/courses/1/assignments/7"}, {"id": 1, "name": "Course", "course_code": "ABC"}, now)
    assert item and item["submitted"] is True and item["dueAt"] == "2026-01-02T00:00:00Z"
    assert "CSYNC:" not in item["calendarDescription"]


def test_planner_assignment_is_deduplicated():
    class Fake:
        def get_all(self, path, params=()):
            if path == "/api/v1/courses": return [{"id": 1, "name": "Course"}]
            if path.endswith("/assignments"): return [{"id": 2, "name": "A", "due_at": "2026-01-03T00:00:00Z", "published": True}]
            return [{"course_id": 1, "plannable_type": "quiz", "plannable_id": 9, "plannable": {"id": 9, "assignment_id": 2, "due_at": "2026-01-03T00:00:00Z"}}]
    result = discover(Fake(), dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
    assert result["itemCount"] == 1


def test_future_only():
    now = dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)
    assert normalize_assignment({"id": 1, "due_at": "2026-01-01T00:00:00Z"}, {"id": 1}, now) is None
