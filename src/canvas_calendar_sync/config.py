"""Non-secret configuration. Importing the package reads no files."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

APP_DIR = Path(os.environ.get("CANVAS_CALENDAR_SYNC_HOME", str(Path.home() / "Library/Application Support/CanvasCalendarSyncCommunity"))).expanduser().resolve()
LOG_DIR = APP_DIR / "logs"
CANVAS_KEYCHAIN_SERVICE = "canvas-calendar-sync-canvas"
GOOGLE_KEYCHAIN_SERVICE = "canvas-calendar-sync-google-oauth"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"


class ConfigError(RuntimeError):
    code = "configuration_error"


@dataclass(frozen=True)
class Settings:
    canvas_url: str = ""
    timezone: str = "UTC"
    calendar_id: str = "primary"
    daily_hour: int = 3
    daily_minute: int = 0

    @property
    def owner(self) -> str:
        identity = json.dumps([self.canvas_url, self.calendar_id], separators=(",", ":"))
        return "canvas-calendar-sync-v2:" + hashlib.sha256(identity.encode()).hexdigest()[:24]

    @property
    def canvas_account(self) -> str:
        return urlsplit(self.canvas_url).netloc


settings = Settings()


def keychain_service(base: str) -> str:
    return base + ":" + hashlib.sha256(str(APP_DIR).encode()).hexdigest()[:12]


def validate(data: dict) -> Settings:
    if not isinstance(data, dict) or set(data) - set(Settings.__dataclass_fields__):
        raise ConfigError("Configuration must contain only supported non-secret settings.")
    candidate = Settings(**data)
    try:
        url = urlsplit(candidate.canvas_url)
        valid_url = (url.scheme == "https" and bool(url.hostname) and not url.username
                     and not url.password and not url.query and not url.fragment
                     and url.path in {"", "/"} and url.port in {None, 443})
        if not valid_url or any(c.isspace() for c in candidate.canvas_url):
            raise ValueError()
        ZoneInfo(candidate.timezone)
        if not isinstance(candidate.calendar_id, str) or not candidate.calendar_id.strip():
            raise ValueError()
        if any(ord(c) < 32 for c in candidate.calendar_id):
            raise ValueError()
        if type(candidate.daily_hour) is not int or not 0 <= candidate.daily_hour <= 23:
            raise ValueError()
        if type(candidate.daily_minute) is not int or not 0 <= candidate.daily_minute <= 59:
            raise ValueError()
    except (ValueError, TypeError, AttributeError, ZoneInfoNotFoundError):
        raise ConfigError("Use an HTTPS Canvas origin on port 443, an IANA timezone, a calendar ID and a valid daily time.") from None
    return Settings(**{**asdict(candidate), "canvas_url": f"https://{url.hostname.lower()}/"})


def load() -> Settings:
    global settings
    try:
        raw = json.loads((APP_DIR / "config.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError("Run init --canvas-url https://canvas.example.edu --timezone YOUR_TIMEZONE first.") from None
    except (OSError, ValueError):
        raise ConfigError("Configuration is unreadable or invalid JSON.") from None
    settings = validate(raw)
    return settings


def initialize(data: dict) -> dict:
    candidate = validate(data)
    APP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(APP_DIR, 0o700)
    path = APP_DIR / "config.json"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ConfigError("Configuration already exists; init never overwrites an existing profile.") from None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(asdict(candidate), handle, indent=2)
        handle.write("\n")
    return {"ok": True, "configPath": str(path)}
