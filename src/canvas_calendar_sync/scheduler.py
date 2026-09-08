"""Generate a per-profile macOS LaunchAgent without machine-specific templates."""
from __future__ import annotations

import hashlib
import os
import plistlib
import shlex
import sys
import tempfile
from pathlib import Path

from . import config


def label() -> str:
    suffix = hashlib.sha256(str(config.APP_DIR).encode()).hexdigest()[:12]
    return f"org.canvas-calendar-sync.{suffix}"


def build_agent(python: Path | None = None) -> dict:
    return {
        "Label": label(),
        "ProgramArguments": [str(python or Path(sys.executable).absolute()), "-m", "canvas_calendar_sync.cli", "sync", "--scheduled", "--json"],
        "RunAtLoad": True,
        "StartInterval": 60,
        "ProcessType": "Background",
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1", "CANVAS_CALENDAR_SYNC_HOME": str(config.APP_DIR)},
        # Run outcomes already go to rotating sync.jsonl; avoid unbounded tick logs.
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }


def install(dry_run: bool = False) -> dict:
    if sys.platform != "darwin":
        raise config.ConfigError("The built-in scheduler supports macOS only.")
    path = Path.home() / "Library/LaunchAgents" / f"{label()}.plist"
    agent = build_agent()
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                existing = plistlib.loads(path.read_bytes())
            except (OSError, ValueError):
                raise config.ConfigError("Existing LaunchAgent cannot be verified; installation stopped.") from None
            if existing.get("Label") != label():
                raise config.ConfigError("Existing LaunchAgent belongs to another job.")
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".canvas-sync-", suffix=".plist")
        try:
            with os.fdopen(fd, "wb") as handle:
                plistlib.dump(agent, handle)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {
        "ok": True, "dryRun": dry_run, "launchAgent": str(path),
        "label": label(), "timezone": config.settings.timezone,
        "dailyTime": f"{config.settings.daily_hour:02}:{config.settings.daily_minute:02}",
        "loadCommand": shlex.join(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)]),
    }
