from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import config


def prepare_private_path() -> None:
    config.APP_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config.APP_DIR, 0o700)


@contextmanager
def process_lock(path: Path | None = None) -> Iterator[None]:
    path = path or config.APP_DIR / "sync.lock"
    prepare_private_path()
    with path.open("a+", encoding="utf-8") as handle:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another sync process is already running") from error
        yield


class State:
    def __init__(self, path: Path | None = None):
        prepare_private_path()
        path = path or config.APP_DIR / "state.sqlite3"
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=FULL;
        CREATE TABLE IF NOT EXISTS events (
          source_key TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE,
          fingerprint TEXT NOT NULL, due_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
          id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
          status TEXT NOT NULL, mode TEXT NOT NULL, counts_json TEXT, error_code TEXT, error_message TEXT
        );
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self.db.commit()
        self.secure_files()

    def bind_identity(self) -> None:
        existing = self.get_meta("sync_identity")
        if (existing and existing != config.settings.owner) or (not existing and self.event_count()):
            raise config.ConfigError("State belongs to another Canvas/calendar configuration or an older installation. Use a separate profile; do not reuse its mappings.")
        self.set_meta("sync_identity", config.settings.owner)

    def secure_files(self) -> None:
        for path in (self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm")):
            if path.exists(): os.chmod(path, 0o600)

    def close(self) -> None:
        self.db.close(); self.secure_files()

    def begin_run(self, mode: str) -> int:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        cursor = self.db.execute("INSERT INTO runs(started_at,status,mode) VALUES(?,?,?)", (now, "running", mode))
        self.db.commit(); return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, counts: dict[str, Any] | None = None, code: str | None = None, message: str | None = None) -> None:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        self.db.execute("UPDATE runs SET completed_at=?,status=?,counts_json=?,error_code=?,error_message=? WHERE id=?", (now, status, json.dumps(counts, sort_keys=True) if counts else None, code, message, run_id))
        self.db.commit()

    def upsert_event(self, source_key: str, event_id: str, fingerprint: str, due_at: str) -> None:
        self.db.execute("INSERT INTO events VALUES(?,?,?,?,?) ON CONFLICT(source_key) DO UPDATE SET event_id=excluded.event_id,fingerprint=excluded.fingerprint,due_at=excluded.due_at,updated_at=excluded.updated_at", (source_key, event_id, fingerprint, due_at, dt.datetime.now(dt.timezone.utc).isoformat()))
        self.db.commit()

    def remove_event(self, source_key: str) -> None:
        self.db.execute("DELETE FROM events WHERE source_key=?", (source_key,)); self.db.commit()

    def event_count(self) -> int:
        return int(self.db.execute("SELECT count(*) FROM events").fetchone()[0])

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO metadata VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)); self.db.commit()

    def status(self) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return {"eventMappingCount": self.event_count(), "lastRun": dict(row) if row else None, "lastSuccessfulLocalDate": self.get_meta("last_successful_local_date"), "timezone": config.settings.timezone}
