# Contributing

Bug reports and focused improvements are welcome. Search existing issues first.
For larger changes, open a feature request describing the user problem before
starting implementation. Keep reports respectful, actionable and free of private
coursework or account details. Report vulnerabilities via [SECURITY.md](SECURITY.md),
not a public bug report.

Use Python 3.11 on macOS and install the locked environment with `uv sync --locked`.
Run `uv run --locked pytest`, `uv run --locked python -m compileall -q src tests`
and `git diff --check` before submitting a PR. Describe the observable change,
test evidence, compatibility and any limits.

Run `uv build` when changing packaging. The macOS GitHub Actions workflow runs
the offline suite, compilation and build on pull requests and `main`. Passing
CI does not establish live institutional API access. CI needs no repository
secrets. Use a focused branch and the pull-request checklist; avoid unrelated
dependency updates or generated artifacts.

Use the temporary-profile fixture for tests. Never use real Keychain values,
student records or Calendar writes in tests. Add regression tests for discovery,
ownership, deletion, configuration and retry changes. Network requests belong
behind testable boundaries. Keep raw exception text and request/response bodies
out of logs and error output.

Do not commit a config containing a real calendar ID, OAuth downloads, tokens,
databases, personal paths or logs. Use `canvas.example.edu` and invented course
fixtures. Avoid unrelated refactors and preserve user state when changing schema.

Opening a PR does not deploy the code or authorize changing a user's calendar.
Live integration checks require a separate test profile and an explicitly chosen
owned test calendar. Report mocked checks and live checks separately.
