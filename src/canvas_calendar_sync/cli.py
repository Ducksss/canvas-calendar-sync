from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import logging.handlers
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .canvas import CanvasClient, CanvasError, keychain_token
from .config import LOG_DIR, TIME_ZONE
from .google_calendar import CalendarError, list_owned, service, setup_google
from .state import State, process_lock
from .sync import run_sync, scheduled_due


def emit(value: dict[str, Any], as_json: bool = True) -> None:
    print(json.dumps(value, sort_keys=True) if as_json else value)


def logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700); os.chmod(LOG_DIR, 0o700)
    result = logging.getLogger("canvas-calendar-sync")
    if not result.handlers:
        handler = logging.handlers.RotatingFileHandler(LOG_DIR / "sync.jsonl", maxBytes=1_000_000, backupCount=5)
        handler.setFormatter(logging.Formatter('%(message)s')); result.addHandler(handler); result.setLevel(logging.INFO)
    return result


def notify_failure() -> None:
    subprocess.run(["/usr/bin/osascript", "-e", 'display notification "Canvas calendar sync failed. Run status for details." with title "Canvas Calendar Sync"'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def safe_failure(error: Exception, stage: str) -> dict[str, str]:
    known = isinstance(error, (CanvasError, CalendarError))
    exception_type = getattr(error, "cause_type", None) or type(error).__name__
    safe_type = exception_type if isinstance(exception_type, str) and exception_type.replace("_", "").isalnum() else "UnknownError"
    code = error.code if known else "unexpected_error"
    message = str(error) if known else f"Unexpected {safe_type} during {stage}."
    return {"code": str(code), "message": message, "exceptionType": safe_type, "stage": stage}


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="canvas-calendar-sync")
    commands = root.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup-google"); setup.add_argument("--client-secrets", required=True, type=Path)
    commands.add_parser("probe")
    sync = commands.add_parser("sync"); sync.add_argument("--dry-run", action="store_true"); sync.add_argument("--scheduled", action="store_true"); sync.add_argument("--json", action="store_true")
    status = commands.add_parser("status"); status.add_argument("--json", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "setup-google": emit(setup_google(args.client_secrets)); return 0
        with process_lock():
            state = State()
            try:
                if args.command == "probe":
                    CanvasClient(keychain_token()).probe(); api = service(); owned = list_owned(api)
                    emit({"ok": True, "canvas": True, "calendar": True, "ownedEventCount": len(owned)}); return 0
                if args.command == "status":
                    result = {"ok": True, **state.status()}
                    try: result["ownedEventCount"] = len(list_owned(service()))
                    except CalendarError as error: result["calendarError"] = error.code
                    emit(result, args.json); return 0
                if args.scheduled:
                    due, reason = scheduled_due(state)
                    if not due: emit({"ok": True, "skipped": True, "reason": reason}, args.json); return 0
                mode = "scheduled" if args.scheduled else "dry-run" if args.dry_run else "manual"
                run_id = state.begin_run(mode)
                stage = "google_authentication"
                try:
                    api = service()

                    def update_stage(value: str) -> None:
                        nonlocal stage
                        stage = value

                    result = run_sync(api, state, args.dry_run, on_stage=update_stage)
                    stage = "record_success"
                    state.finish_run(run_id, "success", result.get("counts"))
                    if not args.dry_run:
                        today = dt.datetime.now(dt.timezone.utc).astimezone(ZoneInfo(TIME_ZONE)).date().isoformat()
                        state.set_meta("last_successful_singapore_date", today)
                    logger().info(json.dumps({"timestamp": dt.datetime.now(dt.timezone.utc).isoformat(), "status": "success", "mode": mode, "counts": result.get("counts")}, sort_keys=True))
                    emit(result, args.json); return 0
                except Exception as error:
                    failure = safe_failure(error, stage)
                    state.finish_run(run_id, "failed", code=failure["code"], message=failure["message"])
                    logger().error(json.dumps({"timestamp": dt.datetime.now(dt.timezone.utc).isoformat(), "status": "failed", "mode": mode, **failure}, sort_keys=True))
                    if args.scheduled: notify_failure()
                    raise
            finally: state.close()
    except (CanvasError, CalendarError) as error:
        emit({"ok": False, "code": getattr(error, "code", "runtime_error"), "message": str(error)}); return 2
    except Exception:
        emit({"ok": False, "code": "unexpected_error", "message": "Unexpected failure; inspect the local structured log."}); return 2


if __name__ == "__main__": raise SystemExit(main())
