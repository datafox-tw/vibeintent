# Changelog

All notable changes to VibeIntent will be documented here.

This project follows a simple versioning rule before `1.0.0`:

- Patch versions fix bugs or packaging issues.
- Minor versions may change report format or CLI behavior while the product is still experimental.

## 0.1.0 - 2026-06-15

Initial MVP.

- Added offline `vibeintent` CLI.
- Added `init`, `intent`, `check`, `report`, `log`, `show`, and `explain` commands.
- Added non-blocking `post-commit` hook installation.
- Added file-level Git diff summaries.
- Added best-effort Python function/class/constant change detection using `ast`.
- Added basic added-line security delta checks.
- Added local session reports under `.vibeintent/sessions/`.

