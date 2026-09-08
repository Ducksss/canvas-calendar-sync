# Earlier personal installations

This release is a generalized source version, not an in-place deployment to an
existing personal installation. It uses a separate `CanvasCalendarSyncCommunity`
profile directory, profile-specific Keychain services, configuration-derived v2
ownership markers and `lastSuccessfulLocalDate` in status output. It does not
read any Codex skill state or automatically import legacy CSYNC markers.

Do not run both versions against the same set of deadlines in the same calendar:
v2 will not adopt v1 events automatically and could create a parallel set. Keep
the existing installed version running until a migration is explicitly planned.

For a safe trial, use a new profile and a separate owned test calendar. Configure
and authorize both APIs, review a dry-run and validate a manual sync. Stop the
trial's scheduler before changing its target.

An in-place migration requires a separate migration tool: prove ownership of
every old event, preserve IDs/fields, translate markers and state, verify read-back,
and disable the old scheduler only after validation. That tool is not supplied
in this release. Copying or deleting the old database is not a migration.
