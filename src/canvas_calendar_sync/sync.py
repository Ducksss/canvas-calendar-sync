from __future__ import annotations

import datetime as dt
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import config
from .canvas import CanvasClient, discover, keychain_token
from .google_calendar import CalendarError, confirms_deleted, desired_event, execute, get_event, index_owned, is_future, list_owned, private_props, verify_event
from .state import State


def reconcile(api: Any, state: State, payload: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc)
    items = {x["sourceKey"]: x for x in payload["items"]}
    owned = index_owned(list_owned(api))
    create, update, unchanged, delete, retain_past = [], [], [], [], []
    for source, item in items.items():
        event = owned.get(source)
        if not event:
            create.append(source)
        elif private_props(event).get("canvasFingerprint") != item["fingerprint"]:
            update.append(source)
        else:
            unchanged.append(source)
    for source, event in owned.items():
        if source not in items:
            (delete if is_future(event, now) else retain_past).append(source)
    counts = {"create": len(create), "update": len(update), "delete": len(delete), "unchanged": len(unchanged), "retainPast": len(retain_past)}
    if dry_run:
        return {"ok": True, "dryRun": True, "courseCount": payload["courseCount"], "itemCount": payload["itemCount"], "counts": counts, "changes": {"create": create, "update": update, "delete": delete}}

    # No deletion begins until every create/update and unchanged read-back succeeds.
    for source in create:
        item = items[source]
        created = execute(api.events().insert(calendarId=config.settings.calendar_id, body=desired_event(item), sendUpdates="none"))
        reread = get_event(api, created["id"])
        verify_event(reread, item)
        state.upsert_event(source, reread["id"], item["fingerprint"], item["dueAt"])
    for source in update:
        item, event = items[source], owned[source]
        changed = execute(api.events().update(calendarId=config.settings.calendar_id, eventId=event["id"], body=desired_event(item), sendUpdates="none"))
        reread = get_event(api, changed["id"])
        verify_event(reread, item)
        state.upsert_event(source, reread["id"], item["fingerprint"], item["dueAt"])
    for source in unchanged:
        item, event = items[source], owned[source]
        verify_event(get_event(api, event["id"]), item)
        state.upsert_event(source, event["id"], item["fingerprint"], item["dueAt"])
    for source in delete:
        event = owned[source]
        execute(api.events().delete(calendarId=config.settings.calendar_id, eventId=event["id"], sendUpdates="none"))
        try:
            deleted_readback = get_event(api, event["id"])
        except CalendarError as error:
            if error.code != "calendar_api_error" or error.status not in {404, 410}:
                raise
        else:
            if not confirms_deleted(deleted_readback):
                raise CalendarError("calendar_delete_readback_failed", "Deleted Calendar event was still active after deletion.")
        state.remove_event(source)
    final = index_owned(list_owned(api))
    if any(source not in final for source in items):
        raise CalendarError("final_verification_failed", "Final ownership verification found a missing event.")
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
    local = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo(config.settings.timezone))
    today = local.date().isoformat()
    if (local.hour, local.minute) < (config.settings.daily_hour, config.settings.daily_minute):
        return False, "before_daily_window"
    if state.get_meta("last_successful_local_date") == today:
        return False, "already_succeeded_today"
    # A scheduler tick must not turn bounded request retries into a minute-by-minute storm.
    raw = state.get_meta("last_scheduled_attempt")
    if raw:
        previous = dt.datetime.fromisoformat(raw)
        current = local.astimezone(dt.timezone.utc)
        if (current - previous).total_seconds() < 3600:
            return False, "retry_cooldown"
    return True, today
