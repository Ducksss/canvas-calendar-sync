# Operations guide

[Back to the README](../README.md#usage)

Configuration, daily scheduling, troubleshooting and safety limits for an initialized
profile. Complete [Getting Started](../README.md#getting-started) first.

## Configuration and profiles

`init` creates a private `config.json` under
`~/Library/Application Support/CanvasCalendarSyncCommunity`. It never overwrites
existing configuration. No institution, username, email or secret is built in.

```json
{
  "canvas_url": "https://canvas.example.edu/",
  "timezone": "America/New_York",
  "calendar_id": "primary",
  "daily_hour": 3,
  "daily_minute": 0
}
```

Use `--daily-hour` and `--daily-minute` during init for another daily time.
To isolate another installation, set the non-secret `CANVAS_CALENDAR_SYNC_HOME`
environment variable to an absolute directory **before every command**. Profile
state, logs, Keychain services and LaunchAgent labels are isolated by that path.
The generated LaunchAgent remembers it automatically.

Keep a stable profile path and back up its configuration and SQLite state. Moving
it changes Keychain service names and the scheduler label. One profile supports
one Canvas account and one Google account. Do not run multiple Canvas accounts
from the same institution into the same calendar: event ownership is derived
from Canvas origin and the configured calendar ID. Use distinct owned calendars.

Changing the Canvas origin or destination in an established profile is rejected
by the state identity guard. Create a separate profile and plan cleanup/migration
of the old events first. Changing only timezone or daily time is supported by
editing the non-secret configuration while no sync is running.

## Automatic daily execution

After a successful manual sync:

```sh
uv run --locked canvas-calendar-sync install-schedule --dry-run
uv run --locked canvas-calendar-sync install-schedule
```

Run the exact `loadCommand` printed by the second command to activate the
LaunchAgent. Installation writes the plist but does not silently load it.
The agent references this checkout's Python environment: keep the folder and
virtual environment available. If the same label is already loaded, unload
that job before loading its replacement.

The job wakes every 60 seconds and on login/load. The program decides whether
the configured local time has passed, independently of the Mac's system
timezone. It catches up when awake and online, usually within a minute, and
skips after one successful run per local date. A failed scheduled attempt has
a one-hour cooldown; each API/Keychain operation also has bounded retries.
Daylight-saving changes use IANA rules. A nonexistent daily time runs after the
clock jumps past it; a repeated time still gets only one successful daily run.
The Mac must be logged in, and Keychain must be accessible. Sleeping or powered
off machines cannot sync; next execution checks whether catch-up is due.

Inspect or unload the job using the `label` printed during installation:

```sh
launchctl print "gui/$(id -u)/LABEL_FROM_INSTALL"
launchctl bootout "gui/$(id -u)/LABEL_FROM_INSTALL"
```

Unloading stops the job for the current login session. To prevent future login
loads, also remove the generated plist identified by `launchAgent` in the
installation output. Credentials and calendar events are retained.

## Status and troubleshooting

```sh
uv run --locked canvas-calendar-sync status --json
uv run --locked canvas-calendar-sync probe
uv run --locked canvas-calendar-sync sync --scheduled --json
```

`lastSuccessfulLocalDate` and `timezone` describe the daily guard. `lastRun` can
be a dry-run: a dry-run records its outcome but does not mark the day synced.
Manual `sync --json` runs immediately even before the daily time or during a
scheduled retry cooldown. A manual success also satisfies the daily guard.

A healthy live result has `ok: true` and `dryRun: false`. Counts of zero are normal
when nothing changed. In `status`, check `lastRun.status` and
`lastSuccessfulLocalDate`, and look for `calendarError`: top-level `ok: true`
alone does not establish Calendar connectivity or a successful daily sync.

Structured logs are under the profile's `logs/sync.jsonl` and rotate at 1 MB
with five backups. Scheduled failures show a generic macOS notification. Logs
include safe error codes, exception classes and execution stages, not unexpected
exception text, tokens or HTTP bodies. Routine scheduler stdout is discarded
to avoid unbounded logs of skipped ticks. Use `status` for the latest run.

For a missing Canvas token, rerun `setup-canvas`. For rejected Google refresh
credentials, repeat `setup-google`. Resolve API denial or incomplete discovery
before writing to Calendar. Inspect a dry-run after any credential/configuration
change. Do not clear mappings to work around a failed fetch.

## Safety and limits

Canvas discovery completes before Calendar mutations. Pagination and redirects
must stay on the configured HTTPS origin. Calendar ownership reads are paginated
and reject repeated tokens and foreign ownership. Creates/updates precede
deletions; each write is read back before its mapping is recorded. Only owned
future events absent from complete discovery can be deleted. Past events remain.
The SQLite database uses private permissions and an exclusive process lock.

Canvas network errors and transient HTTP responses (408/429/500/502/503/504)
allow three retries after the first attempt, normally after 1/2/4 seconds;
numeric Retry-After is capped at 30 seconds. Canvas Keychain commands time out
after 10 seconds each. Google Keychain and transient OAuth refresh failures have
bounded retries; permanent OAuth rejection fails immediately. Google libraries
may retry internally too. Calendar writes retain the SDK's existing retry policy.

Successful earlier writes are not rolled back after a later failure. An ambiguous
Calendar insert response can produce a duplicate; duplicate ownership stops the
next reconciliation for investigation. This is not an exactly-once transaction
across two APIs. Discovery covers Canvas APIs, not all material a course may
publish. Planner discovery looks at least 550 days ahead (extended for later
course term ends); assignments have no equivalent future cutoff. No
Windows/Linux scheduler or credential backend is currently supported.

The app does not crawl module pages, attachments, syllabuses or external-tool
websites. Missing deadlines in those sources cannot be inferred. It is a useful
reminder aid, not a replacement for checking your course's official requirements.

Older personal installations use a different state directory and event marker.
They are not automatically migrated. See [migration notes](MIGRATION.md).


