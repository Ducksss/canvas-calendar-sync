# Canvas Calendar Sync

Standalone Python 3.11 application that reads future NUS Canvas coursework
deadlines and reconciles them with the primary Google Calendar. Routine runs
call the APIs directly; no Codex session or LLM is required.

## What it syncs

Active student courses, published assignments (including graded quizzes,
discussions and external-tool assignments), and relevant dated planner items.
Canvas returns user-specific assignment dates with `override_assignment_dates=true`.
Submitted coursework stays visible; only future deadlines enter discovery.
Planner items linked to an already discovered assignment are deduplicated.
Deadlines never exposed through Canvas cannot be discovered.

Each deadline becomes a private, transparent, 15-minute event starting at its
exact due time, with popup reminders 24 hours and 1 hour beforehand. Events
contain the course and Canvas link, without attendees or conferencing.

## Install and authorize

Requires macOS, Python 3.11, `uv`, a Canvas access token, and a Google Desktop
OAuth client with Calendar API enabled. Use the `calendar.events.owned` scope.
Keep the consent app in Production for a durable personal refresh token;
Testing-mode refresh tokens can expire after seven days.

Copy this repository's source files to
`~/Library/Application Support/CanvasCalendarSync`, preserving any existing
runtime database and credentials. Do not replace a working installation's
state with repository files. Then:

```sh
cd "$HOME/Library/Application Support/CanvasCalendarSync"
uv sync --locked
```

Use macOS Keychain Access to create a generic password item with service
`codex-canvas-calendar-sync`, account `canvas.nus.edu.sg`, and the Canvas token
as its password. Do not put the token in a shell command or this repository.

Authorize Google once from a temporary Desktop client-secrets file:

```sh
.venv/bin/canvas-calendar-sync setup-google --client-secrets /private/path/client-secrets.json
.venv/bin/canvas-calendar-sync probe
.venv/bin/canvas-calendar-sync sync --dry-run --json
```

Setup stores the client ID, client secret and refresh token in macOS Keychain
under service `canvas-calendar-sync-google-oauth`. Access tokens stay in memory.
Setup does not remove its input file: remove the temporary client-secrets file
yourself after successful import. Never commit it.

## Commands and scheduling

```sh
.venv/bin/canvas-calendar-sync sync --json              # reconcile now
.venv/bin/canvas-calendar-sync sync --dry-run --json    # plan; no Calendar writes
.venv/bin/canvas-calendar-sync sync --scheduled --json  # daily guard
.venv/bin/canvas-calendar-sync status --json
```

Dry-runs record a local run outcome, but do not mark the day successfully synced.
`status` reports the latest run (which may be a dry-run), the last successful
Singapore date, local mappings and a live owned-event count.

The template in `launchd/` targets the existing personal installation. Adjust
its absolute home paths before using it on another Mac. Copy it to
`~/Library/LaunchAgents/`, create `~/Library/Logs/CanvasCalendarSync`, and load it:

```sh
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.chaipinzheng.canvas-calendar-sync.plist"
launchctl print "gui/$(id -u)/com.chaipinzheng.canvas-calendar-sync"
```

The LaunchAgent triggers at 03:00 in the Mac's system timezone. Keep the Mac
set to Asia/Singapore: the plist's `TZ` environment variable does not control
launchd's wall-clock trigger. The program separately enforces its Singapore
daily guard. RunAtLoad checks for a missed run after 03:00 on login/load.
The Mac must be logged in, online, and able to access Keychain. There is no
periodic offline-recovery trigger beyond bounded retries and load/login;
after a persistent outage, run `sync --scheduled --json` to catch up.

To unload the schedule while retaining state:

```sh
launchctl bootout "gui/$(id -u)/com.chaipinzheng.canvas-calendar-sync"
```

## Failure safety and retries

Complete Canvas discovery and Calendar preflight reads precede reconciliation.
Canvas access, pagination and malformed-response failures stop Calendar writes.
Creates and updates precede deletion. An earlier Calendar error aborts the
remaining run; successfully completed writes are not rolled back.

Hidden event properties identify ownership: `canvasSyncOwner`,
`canvasSourceKey`, and `canvasFingerprint`. Only owned future events absent
from a complete discovery can be deleted. Writes are read back before their
mapping is recorded. SQLite and an exclusive process lock coordinate runs.
Legacy CSYNC marker migration is resumable. Google insert retries do not
guarantee exactly-once creation after an ambiguous network failure; duplicate
ownership is detected on subsequent reconciliation and requires investigation.

New boundary retries permit an initial attempt plus three retries, usually
after 1, 2 and 4 seconds:

- Canvas transport failures and HTTP 408, 429, 500, 502, 503, 504 retry.
  Numeric Retry-After delays are capped at 30 seconds. Requests use a 30-second
  timeout; Keychain security commands use a 10-second timeout per attempt.
- Canvas Keychain command failures retry. Google Keychain errors retry;
  a missing Google credential fails immediately.
- Google OAuth transport errors and explicitly retryable refresh errors retry.
  Permanent refresh rejection fails immediately. Google libraries may also
  retry internally, so four wrapper attempts are not a four-HTTP-call limit.
- Calendar API requests retain the client's existing `num_retries=3` policy.
  No additional wrapper retries were added around Calendar writes.

Failures log an error code, execution stage and exception class in
`~/Library/Logs/CanvasCalendarSync/sync.jsonl`. Known application errors use
controlled messages; unexpected exception text is omitted. The underlying
exception class is retained when wrapping supported boundary errors. Logs
rotate at 1 MB with five backups. A scheduled failure raises a generic local
notification. Credential values and API response bodies must never be logged.

If authentication is rejected, rotate the appropriate Keychain credential or
repeat Google setup, then run `probe` and a dry-run. If discovery is incomplete,
resolve that failure before reconciling. Do not treat an error as an empty course
list or manually clear event mappings. Historical generic failures cannot be
diagnosed retroactively from the new fields.

## Development and verification

```sh
uv sync --locked
uv run --locked pytest
uv run --locked python -m compileall -q src tests
```

The suite uses fake API boundaries and temporary state. The optional workflow
template in `docs/github-actions-tests.yml` needs no credentials and makes no
live Canvas or Calendar calls. It is not active: the current GitHub OAuth login
lacks workflow-upload scope. Once authorized, copy the template to
`.github/workflows/tests.yml` to enable PR checks. Tests cover discovery, ownership,
reconciliation, read-back, retries, failure reporting and secret hygiene.
Runtime databases, logs, virtual environments, OAuth downloads, and unrelated
hosting files are excluded from version control. This is a source repository;
merging a PR does not automatically deploy to the installed LaunchAgent.
