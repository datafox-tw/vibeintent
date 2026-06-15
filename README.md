# vibeintent

[繁體中文 README](README.zh-TW.md)

VibeIntent is a local, tool-agnostic audit layer for AI-assisted coding. It records your intent, watches Git diffs, and produces a Markdown report you can use before code review.

Version `0.1.0` is intentionally offline-first:

- `vibeintent intent "..."` records what you asked the AI to do.
- `vibeintent check` analyzes the current Git diff and writes a session report.
- `vibeintent init` installs a non-blocking post-commit hook so committed changes get reported automatically.
- Python files get function/class level summaries via the standard `ast` module.
- Basic security delta checks run on added lines only.

## Quick Start

```bash
pip install -e .
cd your-git-repo
vibeintent init
vibeintent intent "Add login rate limiting, do not change unrelated auth behavior"
# Use Codex / Claude Code / Cursor / manual edits
vibeintent check
```

Reports are stored in `.vibeintent/sessions/`.

Packaging and release notes:

- [Publishing guide](docs/publishing.md)
- [Changelog](CHANGELOG.md)

## v0.1 Design Boundaries

- No pre-commit blocking and no commit-time TUI. IDE commits from VS Code, Cursor, and other GUI clients should not hang waiting for terminal input.
- The post-commit hook runs in the background and never blocks the commit. For an explicit review step before push, run `vibeintent check` or `vibeintent report` manually.
- No parsing of private AI-tool state such as Claude Code JSONL logs. Intent capture is manual in v0.1 so the tool stays stable and tool-agnostic.
- Python symbol detection is best-effort. It compares function/class/constant definitions with the standard `ast` module; it does not claim full semantic diffing or line-to-AST mapping.

## Commands

```bash
vibeintent init
vibeintent intent "your intent"
vibeintent check
vibeintent report
vibeintent log
vibeintent show <session-or-report-id>
vibeintent explain path/to/file.py
```

## Privacy

VibeIntent does not upload code or prompts. Version `0.1.0` does not read your clipboard and does not call an LLM.
