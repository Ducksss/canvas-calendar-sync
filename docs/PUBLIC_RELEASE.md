# Release checklist

Use this checklist before a release, source export or visibility change.
It records required checks, not a claim that historical content has been audited.

The current source tree is intended for general use, but visibility changes also
publish Git history and may expose old PR descriptions and comments. Removing a
personal path from HEAD does not remove it from earlier commits.

1. Finish code review and run tests/build from the final revision.
2. Audit all reachable Git history, branches, tags, release assets and PR text
   for credentials, student data, calendar IDs, personal paths and local diagnostics.
3. This repository began as a private personal source import. Its older history
   and first PR contain installation paths and operational details. For a clean
   public release, create a new public repository from an audited source snapshot
   with fresh history, or explicitly approve publishing the reviewed history.
   Do not rewrite shared private history without agreement.
4. Confirm the MIT license and private vulnerability reporting settings. Require
   a passing run of `.github/workflows/tests.yml` on the release revision; it
   tests and builds source without live credentials.
5. Verify onboarding with a fresh macOS profile and an owned test calendar. Mock
   tests do not prove a particular institution permits the required API access.
6. Publish source only. Each user must create their own OAuth client and token.
   Never ship runtime state or client-secrets files with a release.

No repository visibility change, credential sharing, production migration or
PyPI publication is performed by the generalization PR itself.
