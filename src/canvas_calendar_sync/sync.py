from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .canvas import CanvasClient, discover, keychain_token, parse_time
from .config import LEGACY_STATE_PATH, OWNER, TIME_ZONE
from .google_calendar import CalendarError, confirms_deleted, desired_event, execute, get_event, index_owned, is_future, list_owned, private_props, verify_event
from .state import State


def legacy_marker(source_key: str) -> str:
    return "CSYNC:" + hashlib.sha256(source_key.encode()).hexdigest()[:24]


def load_legacy(path: Path = LEGACY_STATE_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists(): return {}
    try: payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error: raise CalendarError("invalid_legacy_state", "Legacy event mapping is unreadable.") from error
    events = payload.get("events", {})
    if not isinstance(events, dict): raise CalendarError("invalid_legacy_state", "Legacy event mapping has an invalid shape.")
    return {str(k): v for k, v in events.items() if isinstance(v, dict) and isinstance(v.get("eventId"), str)}


def preflight_legacy(api: Any, legacy: dict[str, dict[str, Any]], owned: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    pending = {}
    for source, record in legacy.items():
        if source in owned: continue
        try:
            event = get_event(api, record["eventId"])
        except CalendarError as error:
            if error.code == "calendar_api_error" and error.status in {404, 410}:
                continue
            raise
        if confirms_deleted(event):
            continue
        if legacy_marker(source) not in str(event.get("description", "")):
            raise CalendarError("legacy_marker_mismatch", "A legacy mapped event did not contain its expected ownership marker.")
        pending[source] = event
    return pending


def migration_body(event: dict[str, Any], source: str, item: dict[str, Any] | None, record: dict[str, Any]) -> dict[str, Any]:
    if item: return desired_event(item)
    body = {key: event[key] for key in ("summary", "description", "start", "end", "visibility", "transparency", "reminders") if key in event}
    body["description"] = str(body.get("description", "")).replace(legacy_marker(source), "").lstrip("\n")
    body["extendedProperties"] = {"private": {"canvasSyncOwner": OWNER, "canvasSourceKey": source, "canvasFingerprint": str(record.get("fingerprint", "legacy"))}}
    return body


def reconcile(api: Any, state: State, payload: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    items = {x["sourceKey"]: x for x in payload["items"]}
    owned = index_owned(list_owned(api))
    legacy = load_legacy()
    pending_migration = preflight_legacy(api, legacy, owned)

    projected = dict(owned)
    for source, event in pending_migration.items(): projected[source] = event
    create, update, unchanged, delete, retain_past = [], [], [], [], []
    for source, item in items.items():
        event = projected.get(source)
        if not event: create.append(source)
        elif private_props(event).get("canvasFingerprint") != item["fingerprint"] or source in pending_migration: update.append(source)
        else: unchanged.append(source)
    for source, event in projected.items():
        if source not in items:
            (delete if is_future(event, now) else retain_past).append(source)
    counts = {"create": len(create), "update": len(update), "delete": len(delete), "unchanged": len(unchanged), "retainPast": len(retain_past), "migrate": len(pending_migration)}
    if dry_run: return {"ok": True, "dryRun": True, "courseCount": payload["courseCount"], "itemCount": payload["itemCount"], "counts": counts, "changes": {"create": create, "update": update, "delete": delete}}

    # Migration is resumable: each patched event is verified and immediately recorded.
    for source, event in pending_migration.items():
        item, record = items.get(source), legacy[source]
        patched = execute(api.events().update(calendarId="primary", eventId=event["id"], body=migration_body(event, source, item, record), sendUpdates="none"))
        reread = get_event(api, patched["id"])
        props = private_props(reread)
        if props.get("canvasSyncOwner") != OWNER or props.get("canvasSourceKey") != source or legacy_marker(source) in str(reread.get("description", "")):
            raise CalendarError("migration_readback_mismatch", "Legacy event migration read-back failed.")
        fingerprint = item["fingerprint"] if item else str(record.get("fingerprint", "legacy")); due = item["dueAt"] if item else str(record.get("dueAt", ""))
        state.upsert_event(source, reread["id"], fingerprint, due)

    # A fresh complete ownership read is required before reconciliation mutations.
    owned = index_owned(list_owned(api))
    create, update, unchanged, delete, retain_past = [], [], [], [], []
    for source, item in items.items():
        event = owned.get(source)
        if not event: create.append(source)
        elif private_props(event).get("canvasFingerprint") != item["fingerprint"]: update.append(source)
        else: unchanged.append(source)
    for source, event in owned.items():
        if source not in items: (delete if is_future(event, now) else retain_past).append(source)

    # Creates and updates precede deletion; any failure aborts the deletion phase.
    for source in create:
        item = items[source]
        created = execute(api.events().insert(calendarId="primary", body=desired_event(item), sendUpdates="none"))
        reread = get_event(api, created["id"]); verify_event(reread, item)
        state.upsert_event(source, reread["id"], item["fingerprint"], item["dueAt"])
    for source in update:
        item, event = items[source], owned[source]
        changed = execute(api.events().update(calendarId="primary", eventId=event["id"], body=desired_event(item), sendUpdates="none"))
        reread = get_event(api, changed["id"]); verify_event(reread, item)
        state.upsert_event(source, reread["id"], item["fingerprint"], item["dueAt"])
    for source in unchanged:
        item, event = items[source], owned[source]
        verify_event(get_event(api, event["id"]), item)
        state.upsert_event(source, event["id"], item["fingerprint"], item["dueAt"])
    for source in delete:
        event = owned[source]
        execute(api.events().delete(calendarId="primary", eventId=event["id"], sendUpdates="none"))
        try: deleted_readback = get_event(api, event["id"])
        except CalendarError as error:
            if error.code != "calendar_api_error" or error.status not in {404, 410}: raise
        else:
            if not confirms_deleted(deleted_readback):
                raise CalendarError("calendar_delete_readback_failed", "Deleted Calendar event was still active after deletion.")
        state.remove_event(source)
    final = index_owned(list_owned(api))
    if any(source not in final for source in items): raise CalendarError("final_verification_failed", "Final ownership verification found a missing event.")
    counts = {"create": len(create), "update": len(update), "delete": len(delete), "unchanged": len(unchanged), "retainPast": len(retain_past), "migrate": len(pending_migration)}
    return {"ok": True, "dryRun": False, "courseCount": payload["courseCount"], "itemCount": payload["itemCount"], "ownedEventCount": len(final), "counts": counts}


def run_sync(api: Any, state: State, dry_run: bool = False, on_stage: Callable[[str], None] | None = None) -> dict[str, Any]:
    stage = on_stage or (lambda _value: None)
    stage("canvas_keychain")
    token = keychain_token()
    stage("canvas_discovery")
    payload = discover(CanvasClient(token))
    stage("calendar_reconciliation")
    return reconcile(api, state, payload, dry_run)


def scheduled_due(state: State, now: dt.datetime | None = None) -> tuple[bool, str]:
    local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo(TIME_ZONE))
    today = local.date().isoformat()
    if local.hour < 3: return False, "before_daily_window"
    if state.get_meta("last_successful_singapore_date") == today: return False, "already_succeeded_today"
    return True, today
