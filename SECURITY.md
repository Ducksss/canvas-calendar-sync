# Security

Never post credentials, OAuth authorization codes, raw API responses or student
records in public issues. For a suspected vulnerability, use GitHub's private
vulnerability reporting feature if enabled; otherwise request a private contact
channel without disclosing exploit details or private data.

Each user provides their own Canvas token and Google OAuth client. Runtime
credentials live in macOS Keychain. Non-secret configuration and SQLite state
live outside the source checkout. State and logs still contain operational
metadata and should not be published. There is no telemetry service.

Canvas access tokens are sent only to the configured HTTPS origin; cross-origin
pagination and redirects are rejected. Canvas token retrieval is read-only.
Calendar access is limited by the `calendar.events.owned` scope and sync markers.
The tool does not submit assignments, invite attendees or add conferencing.

Only the current source version is supported on a best-effort basis. This is an
early community project; no security audit or availability guarantee is claimed.
