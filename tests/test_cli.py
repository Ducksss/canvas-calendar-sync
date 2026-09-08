import contextlib
import json
import subprocess

import canvas_calendar_sync.cli as cli
from canvas_calendar_sync.canvas import CanvasError
from canvas_calendar_sync.cli import notify_failure, safe_failure
from canvas_calendar_sync.google_calendar import CalendarError


def test_failure_notification_is_generic(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr(subprocess, "run", fake_run)
    notify_failure()

    assert captured["args"] == [
        "/usr/bin/osascript",
        "-e",
        'display notification "Canvas calendar sync failed. Run status for details." with title "Canvas Calendar Sync"',
    ]
    assert captured["kwargs"]["check"] is False
    assert captured["kwargs"]["stdout"] is subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] is subprocess.DEVNULL


def test_unexpected_failure_diagnostic_excludes_exception_message():
    failure = safe_failure(ValueError("secret-bearing diagnostic"), "canvas_discovery")
    assert failure == {
        "code": "unexpected_error",
        "message": "Unexpected ValueError during canvas_discovery.",
        "exceptionType": "ValueError",
        "stage": "canvas_discovery",
    }
    assert "secret-bearing" not in str(failure)


def test_wrapped_failure_uses_safe_underlying_type():
    error = CanvasError("transport_error", "Canvas HTTPS transport retries were exhausted.", cause_type="TimeoutError")
    failure = safe_failure(error, "canvas_discovery")
    assert failure["exceptionType"] == "TimeoutError"
    assert failure["code"] == "transport_error"


def test_scheduled_failure_records_stage_and_safe_exception_type(monkeypatch, capsys):
    records, log_lines, notifications = [], [], []

    class FakeState:
        def bind_identity(self):
            pass

        def set_meta(self, *_args):
            pass

        def begin_run(self, mode):
            assert mode == "scheduled"
            return 42

        def finish_run(self, run_id, status, counts=None, code=None, message=None):
            records.append({"run_id": run_id, "status": status, "code": code, "message": message})

        def close(self):
            pass

    class FakeLogger:
        def error(self, value):
            log_lines.append(json.loads(value))

    monkeypatch.setattr(cli, "process_lock", contextlib.nullcontext)
    monkeypatch.setattr(cli, "State", FakeState)
    monkeypatch.setattr(cli, "scheduled_due", lambda _state: (True, "today"))
    monkeypatch.setattr(cli, "service", lambda: (_ for _ in ()).throw(CalendarError("google_auth_failed", "safe message", cause_type="TimeoutError")))
    monkeypatch.setattr(cli, "logger", lambda: FakeLogger())
    monkeypatch.setattr(cli, "notify_failure", lambda: notifications.append(True))

    assert cli.main(["sync", "--scheduled", "--json"]) == 2
    assert records == [{"run_id": 42, "status": "failed", "code": "google_auth_failed", "message": "safe message"}]
    assert log_lines[0]["stage"] == "google_authentication"
    assert log_lines[0]["exceptionType"] == "TimeoutError"
    assert log_lines[0]["message"] == "safe message"
    assert notifications == [True]
    assert json.loads(capsys.readouterr().out)["code"] == "google_auth_failed"


def test_unexpected_runtime_error_does_not_leak_to_stdout(monkeypatch, capsys):
    def fail():
        error = RuntimeError("secret-bearing diagnostic")
        error.code = "secret-bearing-code"
        raise error

    monkeypatch.setattr(cli, "process_lock", fail)
    assert cli.main(["probe"]) == 2
    output = capsys.readouterr().out
    assert "secret-bearing" not in output
    assert json.loads(output)["code"] == "unexpected_error"


def test_unexpected_error_code_is_not_trusted():
    error = RuntimeError("secret-bearing diagnostic")
    error.code = "secret-bearing-code"
    assert "secret-bearing" not in str(safe_failure(error, "google_authentication"))
