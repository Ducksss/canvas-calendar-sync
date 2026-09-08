from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Callable

import keyring
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from keyring.errors import KeyringError

from . import config


class CalendarError(RuntimeError):
    def __init__(self, code: str, message: str, status: int | None = None, cause_type: str | None = None):
        super().__init__(message); self.code, self.status, self.cause_type = code, status, cause_type


MAX_BOUNDARY_RETRIES = 3


def retry_delay(attempt: int) -> float:
    return float(min(2 ** attempt, 8))


def store_secret(
    account: str,
    value: str,
    setter: Callable[[str, str, str], None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    secret_setter = setter or keyring.set_password
    for attempt in range(MAX_BOUNDARY_RETRIES + 1):
        try:
            secret_setter(config.keychain_service(config.GOOGLE_KEYCHAIN_SERVICE), account, value)
            return
        except (KeyringError, OSError, TimeoutError) as error:
            if attempt >= MAX_BOUNDARY_RETRIES:
                raise CalendarError(
                    "google_keychain_error",
                    "Google OAuth credential could not be stored in macOS Keychain after bounded retries.",
                    cause_type=type(error).__name__,
                ) from None
            sleeper(retry_delay(attempt))


def get_secret(
    account: str,
    getter: Callable[[str, str], str | None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> str:
    secret_getter = getter or keyring.get_password
    for attempt in range(MAX_BOUNDARY_RETRIES + 1):
        try:
            value = secret_getter(config.keychain_service(config.GOOGLE_KEYCHAIN_SERVICE), account)
        except (KeyringError, OSError, TimeoutError) as error:
            if attempt >= MAX_BOUNDARY_RETRIES:
                raise CalendarError(
                    "google_keychain_error",
                    "Google OAuth credential could not be read from macOS Keychain after bounded retries.",
                    cause_type=type(error).__name__,
                ) from None
            sleeper(retry_delay(attempt)); continue
        if value:
            return value
        raise CalendarError("missing_google_credentials", f"Google OAuth {account} is unavailable in macOS Keychain.")
    raise AssertionError("unreachable")


def setup_google(path: Path) -> dict[str, Any]:
    try: config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error: raise CalendarError("invalid_client_secrets", "OAuth client-secrets file is unreadable or invalid.") from error
    desktop = config.get("installed")
    if not isinstance(desktop, dict) or not desktop.get("client_id") or not desktop.get("client_secret"):
        raise CalendarError("invalid_client_secrets", "A Google Desktop OAuth client-secrets file is required.")
    flow = InstalledAppFlow.from_client_config(config, [config.GOOGLE_SCOPE])
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent", open_browser=True)
    if not credentials.refresh_token: raise CalendarError("missing_refresh_token", "Google did not return an offline refresh token.")
    store_secret("client-id", desktop["client_id"]); store_secret("client-secret", desktop["client_secret"]); store_secret("refresh-token", credentials.refresh_token)
    return {"ok": True, "scope": config.GOOGLE_SCOPE, "storedIn": "macOS Keychain"}


def refresh_credentials(
    credentials: Any,
    request_factory: Callable[[], Any] = Request,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    for attempt in range(MAX_BOUNDARY_RETRIES + 1):
        try:
            credentials.refresh(request_factory())
            return
        except RefreshError as error:
            if error.retryable and attempt < MAX_BOUNDARY_RETRIES:
                sleeper(retry_delay(attempt)); continue
            message = "Google OAuth refresh retries were exhausted." if error.retryable else "Google OAuth refresh was rejected."
            raise CalendarError("google_auth_failed", message, cause_type=type(error).__name__) from None
        except (TransportError, TimeoutError, ConnectionError, OSError) as error:
            if attempt >= MAX_BOUNDARY_RETRIES:
                raise CalendarError(
                    "google_auth_failed",
                    "Google OAuth refresh transport retries were exhausted.",
                    cause_type=type(error).__name__,
                ) from None
            sleeper(retry_delay(attempt))
        except Exception as error:
            raise CalendarError("google_auth_failed", "Google OAuth refresh failed.", cause_type=type(error).__name__) from None


def service():
    credentials = Credentials(token=None, refresh_token=get_secret("refresh-token"), token_uri="https://oauth2.googleapis.com/token", client_id=get_secret("client-id"), client_secret=get_secret("client-secret"), scopes=[config.GOOGLE_SCOPE])
    refresh_credentials(credentials)
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def execute(request: Any) -> Any:
    try: return request.execute(num_retries=3)
    except HttpError as error: raise CalendarError("calendar_api_error", f"Google Calendar returned HTTP {error.resp.status}.", int(error.resp.status), cause_type="HttpError") from None
    except Exception as error: raise CalendarError("calendar_transport_error", "Google Calendar request failed after bounded retries.", cause_type=type(error).__name__) from None


def list_owned(api: Any) -> list[dict[str, Any]]:
    token, events, seen = None, [], set()
    for _ in range(1000):
        result = execute(api.events().list(calendarId=config.settings.calendar_id, privateExtendedProperty=f"canvasSyncOwner={config.settings.owner}", maxResults=2500, pageToken=token, showDeleted=False, singleEvents=True))
        items = result.get("items", []) if isinstance(result, dict) else None
        if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
            raise CalendarError("malformed_calendar_response", "Google Calendar returned an invalid event collection.")
        events.extend(items); token = result.get("nextPageToken")
        if not token: return events
        if not isinstance(token, str) or token in seen:
            raise CalendarError("calendar_pagination_error", "Google Calendar pagination is incomplete or repeated.")
        seen.add(token)
    raise CalendarError("calendar_pagination_error", "Google Calendar pagination exceeded the safety limit.")


def desired_event(item: dict[str, Any]) -> dict[str, Any]:
    return {"summary": item["calendarTitle"], "description": item["calendarDescription"], "start": {"dateTime": item["dueAt"], "timeZone": config.settings.timezone}, "end": {"dateTime": item["eventEndAt"], "timeZone": config.settings.timezone}, "visibility": "private", "transparency": "transparent", "attendees": [], "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 1440}, {"method": "popup", "minutes": 60}]}, "extendedProperties": {"private": {"canvasSyncOwner": config.settings.owner, "canvasSourceKey": item["sourceKey"], "canvasFingerprint": item["fingerprint"]}}}


def private_props(event: dict[str, Any]) -> dict[str, str]:
    value = event.get("extendedProperties", {}).get("private", {})
    return value if isinstance(value, dict) else {}


def index_owned(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        props = private_props(event); source = props.get("canvasSourceKey")
        if props.get("canvasSyncOwner") != config.settings.owner:
            raise CalendarError("foreign_event", "Calendar returned an event outside this sync configuration's ownership.")
        if not source: raise CalendarError("owned_event_missing_source", "An owned Calendar event lacks its Canvas source key.")
        if source in result: raise CalendarError("duplicate_owned_event", "Multiple owned Calendar events share a Canvas source key.")
        result[source] = event
    return result


def verify_event(event: dict[str, Any], item: dict[str, Any]) -> None:
    expected, props = desired_event(item), private_props(event)
    checks = [event.get("summary") == expected["summary"], event.get("description", "") == expected["description"], same_instant(event.get("start", {}).get("dateTime"), expected["start"]["dateTime"]), same_instant(event.get("end", {}).get("dateTime"), expected["end"]["dateTime"]), event.get("visibility") == "private", event.get("transparency") == "transparent", not event.get("attendees"), not event.get("conferenceData"), props.get("canvasSyncOwner") == config.settings.owner, props.get("canvasSourceKey") == item["sourceKey"], props.get("canvasFingerprint") == item["fingerprint"]]
    reminders = {(x.get("method"), x.get("minutes")) for x in event.get("reminders", {}).get("overrides", [])}
    checks.append(reminders == {("popup", 1440), ("popup", 60)})
    if not all(checks): raise CalendarError("calendar_readback_mismatch", "Calendar event read-back did not match the requested state.")


def same_instant(actual: Any, expected: Any) -> bool:
    if not isinstance(actual, str) or not isinstance(expected, str): return False
    try:
        left = dt.datetime.fromisoformat(actual.replace("Z", "+00:00"))
        right = dt.datetime.fromisoformat(expected.replace("Z", "+00:00"))
    except ValueError:
        return False
    if left.tzinfo is None or right.tzinfo is None: return False
    return left.astimezone(dt.timezone.utc) == right.astimezone(dt.timezone.utc)


def get_event(api: Any, event_id: str) -> dict[str, Any]:
    result = execute(api.events().get(calendarId=config.settings.calendar_id, eventId=event_id))
    if not isinstance(result, dict): raise CalendarError("malformed_calendar_response", "Google Calendar returned an invalid event.")
    return result


def confirms_deleted(event: dict[str, Any]) -> bool:
    return event.get("status") == "cancelled"


def is_future(event: dict[str, Any], now: dt.datetime) -> bool:
    raw = event.get("start", {}).get("dateTime")
    if not isinstance(raw, str): return False
    try: return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(dt.timezone.utc) > now
    except ValueError: return False
