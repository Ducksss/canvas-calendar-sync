# Connect your Google Calendar

This is a one-time setup for your own Google account and OAuth client. The app
does not use a shared developer project, service account or API key. You need
macOS, a browser and a terminal on the same machine. First complete `init` in
the [README](../README.md#quick-start).

## 1. Prepare a Cloud project

In [Google Cloud Console](https://console.cloud.google.com/), select a project
you control or create one. Enable **Google Calendar API** for that project.
Reusing a project is possible; do not delete unrelated credentials or services.
An administrator may need to permit access on managed accounts.

## 2. Configure OAuth consent

In **Google Auth Platform**, configure Branding, Audience and Data Access.
Use accurate application/support details. For a personal Google account, use
an External audience and add your own account as a test user while testing.
The app requests only:

```text
https://www.googleapis.com/auth/calendar.events.owned
```

This scope can manage events on calendars you own, not just events created by
this app. The app's ownership markers provide the narrower reconciliation guard;
OAuth itself does not enforce that marker. It does not request Gmail access.
See the [official scope definitions](https://developers.google.com/workspace/calendar/api/auth).

For unattended daily use, resolve publishing/consent requirements rather than
leaving an External app in Testing. Google issues seven-day refresh tokens in
Testing for this scope. In Production removes that testing-specific limit, but
revocation, inactivity and organizational policies can still invalidate access.
Publishing status is not the same as Google verification; follow the requirements
shown for your app and audience. See [Google's token expiration guidance](https://developers.google.com/identity/protocols/oauth2#expiration).

## 3. Create and import a Desktop client

Under Clients, create an OAuth client with application type **Desktop app**.
Download its JSON to a private location outside the repository. Do not substitute
a Web application client or copy credentials into shell arguments.

```sh
uv run --locked canvas-calendar-sync setup-google --client-secrets /private/path/client-secrets.json
```

Replace the example path with your download. Sign in to the intended account and
review consent. The local browser callback completes authorization; you do not
need to paste an authorization code into an issue or chat.

The app imports the client ID, client secret and refresh token into macOS
Keychain. Access tokens remain in memory. After successful import, remove the
downloaded JSON yourself; the command does not delete it.

Google's [Python quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python)
explains the Console steps. Use this app's setup command, not the quickstart's
token-file storage or broader/different example scope.

## 4. Verify before scheduling

```sh
uv run --locked canvas-calendar-sync probe
uv run --locked canvas-calendar-sync sync --dry-run --json
```

Check the planned changes before running `sync --json`. The default destination
is the signed-in account's primary calendar. For a separate owned calendar,
supply its ID when initializing a new profile with `--calendar-id`; do not switch
an established profile's identity to bypass the state guard.

If consent is denied, check the selected account, audience/test-user settings,
requested scope, enabled API and any organization policy. If refresh is rejected,
resolve the cause and repeat `setup-google`. Reauthorizing does not itself change
calendar events. Do not share the downloaded JSON or raw OAuth error response.
