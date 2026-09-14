## Summary

Explain the user-visible change and link the issue, if any.

## Verification

List commands, results and any checks not performed. Separate offline/mocked
tests from explicitly authorized live integration checks.

- [ ] `uv run --locked pytest`
- [ ] `uv run --locked python -m compileall -q src tests`
- [ ] `uv build` (when relevant)
- [ ] `git diff --check`

## Compatibility and safety

- [ ] Documentation and feature claims match the implementation.
- [ ] No secrets, student records, personal paths or runtime state are included.
- [ ] Discovery, ownership and deletion changes have regression coverage.
- [ ] Profile/state/scheduler migration requirements are documented, or unchanged.
- [ ] No installed app, credentials or live calendars were changed without approval.
