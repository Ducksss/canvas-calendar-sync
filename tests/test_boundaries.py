import pytest
import json
from types import SimpleNamespace
from google.auth.exceptions import RefreshError, TransportError
from keyring.errors import KeyringError

from canvas_calendar_sync.google_calendar import CalendarError, get_secret, refresh_credentials, store_secret
from canvas_calendar_sync import config, google_calendar


def test_google_onboarding_imports_credentials_without_live_oauth(monkeypatch, tmp_path):
    client = {"installed": {"client_id": "fixture-client", "client_secret": "fixture-secret"}}
    path = tmp_path / "desktop-client.json"
    path.write_text(json.dumps(client))
    stored, calls = {}, []

    def factory(client_config, scopes):
        calls.append((client_config, scopes))
        return SimpleNamespace(run_local_server=lambda **kwargs: SimpleNamespace(refresh_token="fixture-refresh"))

    monkeypatch.setattr(google_calendar.InstalledAppFlow, "from_client_config", factory)
    monkeypatch.setattr(google_calendar, "store_secret", lambda account, value: stored.__setitem__(account, value))
    assert google_calendar.setup_google(path)["ok"] is True
    assert calls == [(client, [config.GOOGLE_SCOPE])]
    assert stored == {"client-id": "fixture-client", "client-secret": "fixture-secret", "refresh-token": "fixture-refresh"}


def test_google_keychain_read_retries_then_succeeds():
    calls, delays = [], []

    def getter(_service, _account):
        calls.append(1)
        if len(calls) < 3:
            raise KeyringError("temporary keychain failure")
        return "stored-secret"

    assert get_secret("client-id", getter=getter, sleeper=delays.append) == "stored-secret"
    assert len(calls) == 3
    assert delays == [1.0, 2.0]


def test_google_keychain_write_retry_exhaustion_is_bounded():
    calls, delays = [], []

    def setter(_service, _account, _value):
        calls.append(1)
        raise KeyringError("secret-bearing diagnostic")

    with pytest.raises(CalendarError) as caught:
        store_secret("client-id", "secret", setter=setter, sleeper=delays.append)
    assert len(calls) == 4
    assert delays == [1.0, 2.0, 4.0]
    assert caught.value.code == "google_keychain_error"
    assert caught.value.cause_type == "KeyringError"
    assert "secret-bearing" not in str(caught.value)


def test_google_refresh_retries_transport_then_succeeds():
    calls, delays = [], []

    class Credentials:
        def refresh(self, _request):
            calls.append(1)
            if len(calls) < 3:
                raise TransportError("temporary transport failure")

    refresh_credentials(Credentials(), request_factory=object, sleeper=delays.append)
    assert len(calls) == 3
    assert delays == [1.0, 2.0]


def test_google_refresh_rejection_is_not_retried():
    calls, delays = [], []

    class Credentials:
        def refresh(self, _request):
            calls.append(1)
            raise RefreshError("invalid grant")

    with pytest.raises(CalendarError) as caught:
        refresh_credentials(Credentials(), request_factory=object, sleeper=delays.append)
    assert len(calls) == 1
    assert delays == []
    assert caught.value.cause_type == "RefreshError"


def test_google_retryable_refresh_error_retries_then_succeeds():
    calls, delays = [], []

    class Credentials:
        def refresh(self, _request):
            calls.append(1)
            if len(calls) < 3:
                raise RefreshError("temporarily unavailable", retryable=True)

    refresh_credentials(Credentials(), request_factory=object, sleeper=delays.append)
    assert len(calls) == 3
    assert delays == [1.0, 2.0]
