import pytest
from google.auth.exceptions import RefreshError, TransportError
from keyring.errors import KeyringError

from canvas_calendar_sync.google_calendar import CalendarError, get_secret, refresh_credentials, store_secret


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
