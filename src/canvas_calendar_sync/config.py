from __future__ import annotations

from pathlib import Path

APP_DIR = Path.home() / "Library" / "Application Support" / "CanvasCalendarSync"
LOG_DIR = Path.home() / "Library" / "Logs" / "CanvasCalendarSync"
DB_PATH = APP_DIR / "state.sqlite3"
LOCK_PATH = APP_DIR / "sync.lock"
LEGACY_STATE_PATH = Path.home() / ".codex" / "state" / "sync-canvas-calendar" / "state.json"
BASE_URL = "https://canvas.nus.edu.sg/"
CANVAS_KEYCHAIN_SERVICE = "codex-canvas-calendar-sync"
CANVAS_KEYCHAIN_ACCOUNT = "canvas.nus.edu.sg"
GOOGLE_KEYCHAIN_SERVICE = "canvas-calendar-sync-google-oauth"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
OWNER = "canvas-calendar-sync-v1"
TIME_ZONE = "Asia/Singapore"
