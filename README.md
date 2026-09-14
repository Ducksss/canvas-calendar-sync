# Canvas Calendar Sync

[![Tests](https://github.com/Ducksss/canvas-calendar-sync/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Ducksss/canvas-calendar-sync/actions/workflows/tests.yml)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue)](pyproject.toml)
[![Platform: macOS](https://img.shields.io/badge/platform-macOS-lightgrey)](#quick-start)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Sync future Canvas coursework deadlines to a Google Calendar you own. Runs
locally on macOS with Python, Keychain and launchd. No LLM, hosted backend or
shared developer credentials are needed for normal operation.

**Early release:** macOS and Python 3.11 are supported. Configure your own
Canvas institution and Google OAuth client. Institutional API restrictions may
prevent access; the app stops rather than treating denied access as no deadlines.

[Quick start](#quick-start) · [Google setup](docs/GOOGLE_SETUP.md) ·
[Commands](#command-reference) · [Scheduling](#automatic-daily-execution) ·
[Troubleshooting](#status-and-troubleshooting) · [Contributing](CONTRIBUTING.md)

## Features

- **One-way deadline sync:** create events for upcoming coursework and update
  the same events when Canvas changes a title or due date.
- **Your institution and timezone:** configure a Canvas HTTPS origin, owned
  Google calendar, IANA timezone and daily execution time.
- **Preview before writing:** inspect create/update/delete counts with a dry-run.
- **Calendar-friendly reminders:** private 15-minute events, marked Free, with
  reminders one day and one hour ahead. No guests or meeting links.
- **Local daily automation:** macOS launchd handles execution and catch-up;
  Codex and other LLMs are not involved at runtime.
- **Guarded reconciliation:** complete discovery before writes, hidden ownership
  markers, read-back verification and retention of past events.
- **Local credential storage:** macOS Keychain, separate per-profile state,
  structured rotating logs and bounded retries at API/credential boundaries.

For example, a fictional assignment appears as:

```text
[Canvas] BIO101 — Lab report due
18 Sep, 17:00–17:15 · Private · Free
Course: Introduction to Biology
Canvas: https://canvas.example.edu/courses/123/assignments/456
```

This is a command-line application, not a browser extension or hosted service.
Google Calendar edits do not change Canvas. It never submits coursework.

## What gets synced

- Published assignments in active student courses, including graded quizzes,
  discussions and external-tool work represented as Canvas assignments.
- Relevant dated planner items: quizzes, discussions, peer reviews,
  sub-assignments and course-linked planner notes. Quiz/discussion representations
  of an existing assignment are deduplicated; separate peer-review dates remain.
- Student-specific assignment dates returned by Canvas; submitted work stays
  visible. Only future deadlines are imported.

Events start at the exact deadline and last 15 minutes. They are private,
transparent, attendee-free and have popup reminders 24 hours and 1 hour before.
The description includes the course and Canvas link. Ordinary classes,
announcements, wiki pages and dates only present inside an external tool are
not imported. This is not a general Canvas content scraper.

## Quick start

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), clone this
repository into a stable folder, and run:

```sh
git clone https://github.com/Ducksss/canvas-calendar-sync.git
cd canvas-calendar-sync
uv sync --locked
uv run --locked canvas-calendar-sync init \
  --canvas-url https://canvas.example.edu \
  --timezone America/New_York
uv run --locked canvas-calendar-sync setup-canvas
```

Replace the example URL with your institution's Canvas HTTPS origin (without
`/api` or a course path) and choose an IANA timezone such as `Europe/London`,
`Asia/Singapore` or `America/Los_Angeles`. Create a personal access token in your
Canvas account settings if your institution allows it. `setup-canvas` prompts
without echoing the token and stores it in macOS Keychain. It accepts no token
argument. Never paste a credential into an issue or commit.

For Google setup, create your own Google Cloud project, enable the Calendar API,
configure OAuth consent, and create a **Desktop app** OAuth client. Download its
client-secrets JSON temporarily outside the checkout. Follow the
[step-by-step Google setup guide](docs/GOOGLE_SETUP.md), then run:

```sh
uv run --locked canvas-calendar-sync setup-google --client-secrets /private/path/client-secrets.json
uv run --locked canvas-calendar-sync probe
uv run --locked canvas-calendar-sync sync --dry-run --json
```

Review the dry-run's counts and source keys, especially planned deletions. It
reads the APIs and records a local run, but makes no Calendar changes. When the
plan looks right, perform the first live sync:

```sh
uv run --locked canvas-calendar-sync sync --json
uv run --locked canvas-calendar-sync status --json
```

The browser consent requests `calendar.events.owned`. Use your primary calendar
or an owned calendar ID supplied to `init --calendar-id ...`. Each user brings
their own OAuth client: this repository does not distribute one. The app stores
client credentials and the refresh token in Keychain; access tokens stay in
memory. Remove the downloaded JSON after successful import; setup does not
delete it for you.

External OAuth apps left in Testing commonly receive refresh tokens that expire
after seven days for this scope. Configure the project's publishing status and
consent appropriately; organizational policy may also apply. See Google's
[OAuth token expiration guidance](https://developers.google.com/identity/protocols/oauth2#expiration).

## Command reference

Run commands as `uv run --locked canvas-calendar-sync COMMAND` from the checkout.
Use `--help` or `COMMAND --help` for all options.

| Command | Purpose | Calendar writes? |
| --- | --- | --- |
| `init --canvas-url URL --timezone ZONE` | Create a non-secret profile | No |
| `setup-canvas` | Store a token through a hidden terminal prompt | No |
| `setup-google --client-secrets PATH` | Browser authorization and Keychain import | No |
| `probe` | Check Canvas and Calendar access | No |
| `sync --dry-run --json` | Discover deadlines and preview reconciliation | No |
| `sync --json` | Run immediately | Yes |
| `sync --scheduled --json` | Run only when the daily guard permits | When due |
| `status --json` | Read local run history and query owned-event count | No |
| `install-schedule [--dry-run]` | Preview or write a LaunchAgent; does not load it | No |

`probe` and `status` need network access. A successful `probe` confirms access,
not that every course can be discovered; the complete dry-run checks that path.

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
They are not automatically migrated. See [migration notes](docs/MIGRATION.md).

## Development and release

```sh
uv sync --locked
uv run --locked pytest
uv run --locked python -m compileall -q src tests
uv build
```

Tests use temporary profiles and fake service boundaries; they need no credentials
or live calendars. See [contributing](CONTRIBUTING.md), [security](SECURITY.md),
and the [release checklist](docs/PUBLIC_RELEASE.md).
[GitHub Actions](https://github.com/Ducksss/canvas-calendar-sync/actions/workflows/tests.yml)
runs the offline tests, compilation check and package build on macOS for pull
requests and pushes to `main`. CI never uses personal API credentials or calendars.

Licensed under [MIT](LICENSE). This project is not affiliated with Instructure,
Google or any institution. API behavior is described by the official
[Canvas assignments documentation](https://developerdocs.instructure.com/services/canvas/resources/assignments)
and [Apple launchd scheduling documentation](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html).
