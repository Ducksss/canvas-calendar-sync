# Contributing

Use Python 3.11 on macOS and install the locked environment with `uv sync --locked`.
Run `uv run --locked pytest`, `uv run --locked python -m compileall -q src tests`
and `git diff --check` before submitting a PR. Describe the observable change,
test evidence, compatibility and any limits.

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
