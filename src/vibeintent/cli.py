from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from . import __version__


EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
HOOK_MARKER_START = "# >>> vibeintent post-commit hook >>>"
HOOK_MARKER_END = "# <<< vibeintent post-commit hook <<<"


class VibeIntentError(RuntimeError):
    pass


@dataclass
class IntentRecord:
    session_id: str
    created_at: str
    intent: str
    base_ref: str
    base_label: str


@dataclass
class FileChange:
    path: str
    status: str
    added: int
    deleted: int
    old_path: str | None = None


@dataclass
class SymbolChange:
    path: str
    symbol: str
    kind: str
    status: str
    line: int | None


@dataclass
class SecurityFinding:
    severity: str
    path: str
    line: int | None
    message: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(dt: datetime | None = None) -> str:
    return (dt or utc_now()).strftime("%Y%m%dT%H%M%SZ")


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def run_git(args: Sequence[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise VibeIntentError(detail or f"git {' '.join(args)} failed")
    return result


def repo_root(start: Path | None = None) -> Path:
    start = start or Path.cwd()
    result = run_git(["rev-parse", "--show-toplevel"], start, check=False)
    if result.returncode != 0:
        raise VibeIntentError("vibeintent must be run inside a git repository")
    return Path(result.stdout.strip())


def has_head(root: Path) -> bool:
    return run_git(["rev-parse", "--verify", "HEAD"], root, check=False).returncode == 0


def current_head(root: Path) -> tuple[str, str]:
    if not has_head(root):
        return EMPTY_TREE, "empty tree"
    full = run_git(["rev-parse", "HEAD"], root).stdout.strip()
    short = run_git(["rev-parse", "--short", "HEAD"], root).stdout.strip()
    return full, short


def vibe_dir(root: Path) -> Path:
    return root / ".vibeintent"


def sessions_dir(root: Path) -> Path:
    return vibe_dir(root) / "sessions"


def ensure_workspace(root: Path) -> None:
    sessions_dir(root).mkdir(parents=True, exist_ok=True)
    config = vibe_dir(root) / "config.toml"
    if not config.exists():
        config.write_text(
            '# vibeintent local config\n'
            'language = "en"\n'
            'llm_enabled = false\n',
            encoding="utf-8",
        )


def slug(text: str, limit: int = 10) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    raw = "-".join(words[:4]) or "session"
    return raw[:limit].strip("-") or "session"


def make_session_id(intent: str) -> str:
    digest = hashlib.sha1(f"{iso_now()}:{intent}".encode("utf-8")).hexdigest()[:8]
    return f"{stamp()}-{slug(intent)}-{digest}"


def current_intent_path(root: Path) -> Path:
    return vibe_dir(root) / "current.json"


def save_intent(root: Path, record: IntentRecord) -> None:
    ensure_workspace(root)
    data = {
        "session_id": record.session_id,
        "created_at": record.created_at,
        "intent": record.intent,
        "base_ref": record.base_ref,
        "base_label": record.base_label,
    }
    current_intent_path(root).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    intent_log = vibe_dir(root) / "intents.jsonl"
    with intent_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")


def load_current_intent(root: Path) -> IntentRecord | None:
    path = current_intent_path(root)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return IntentRecord(
        session_id=data["session_id"],
        created_at=data["created_at"],
        intent=data["intent"],
        base_ref=data.get("base_ref", EMPTY_TREE),
        base_label=data.get("base_label", "unknown"),
    )


def install_post_commit_hook(root: Path) -> Path:
    hook = root / ".git" / "hooks" / "post-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    block = f"""{HOOK_MARKER_START}
(
  if command -v vibeintent >/dev/null 2>&1; then
    vibeintent check --from-hook --quiet
  else
    python -m vibeintent check --from-hook --quiet
  fi
) >/dev/null 2>&1 &
:
{HOOK_MARKER_END}
"""
    existing = hook.read_text(encoding="utf-8") if hook.exists() else "#!/bin/sh\n"
    if HOOK_MARKER_START in existing:
        pattern = re.compile(re.escape(HOOK_MARKER_START) + r".*?" + re.escape(HOOK_MARKER_END), re.DOTALL)
        hook.write_text(pattern.sub(block.strip(), existing), encoding="utf-8")
    else:
        if not existing.startswith("#!"):
            existing = "#!/bin/sh\n" + existing
        hook.write_text(existing.rstrip() + "\n\n" + block, encoding="utf-8")
    hook.chmod(0o755)
    return hook


def parse_numstat(output: str) -> dict[str, tuple[int, int]]:
    stats: dict[str, tuple[int, int]] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added_raw, deleted_raw = parts[0], parts[1]
        path = parts[-1]
        added = 0 if added_raw == "-" else int(added_raw)
        deleted = 0 if deleted_raw == "-" else int(deleted_raw)
        stats[path] = (added, deleted)
    return stats


def parse_name_status(output: str, stats: dict[str, tuple[int, int]]) -> list[FileChange]:
    changes: list[FileChange] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        raw = parts[0]
        code = raw[0]
        if code == "R" and len(parts) >= 3:
            old_path, path = parts[1], parts[2]
        else:
            old_path, path = None, parts[-1]
        added, deleted = stats.get(path, (0, 0))
        status = {
            "A": "added",
            "M": "modified",
            "D": "deleted",
            "R": "renamed",
            "C": "copied",
        }.get(code, raw.lower())
        changes.append(FileChange(path=path, old_path=old_path, status=status, added=added, deleted=deleted))
    return changes


def untracked_files(root: Path) -> list[FileChange]:
    result = run_git(["ls-files", "--others", "--exclude-standard"], root, check=False)
    changes: list[FileChange] = []
    for rel in result.stdout.splitlines():
        path = root / rel
        if path.is_file():
            try:
                added = len(path.read_text(encoding="utf-8").splitlines())
            except UnicodeDecodeError:
                added = 0
            changes.append(FileChange(path=rel, status="untracked", added=added, deleted=0))
    return changes


def commit_parent(root: Path, commit: str) -> str:
    line = run_git(["rev-list", "--parents", "-n", "1", commit], root).stdout.strip()
    parts = line.split()
    if len(parts) >= 2:
        return parts[1]
    return EMPTY_TREE


def diff_changes(root: Path, base: str, target: str | None = None, include_untracked: bool = True) -> list[FileChange]:
    args_base = [base]
    if target:
        args_base.append(target)
    stats = parse_numstat(run_git(["diff", "--numstat", "--find-renames", *args_base], root).stdout)
    changes = parse_name_status(run_git(["diff", "--name-status", "--find-renames", *args_base], root).stdout, stats)
    if target is None and include_untracked:
        known = {change.path for change in changes}
        changes.extend(change for change in untracked_files(root) if change.path not in known)
    return sorted(changes, key=lambda change: change.path)


def diff_text(root: Path, base: str, target: str | None = None) -> str:
    args = ["diff", "--unified=80", "--find-renames", base]
    if target:
        args.append(target)
    return run_git(args, root).stdout


def untracked_diff_text(root: Path, changes: Sequence[FileChange]) -> str:
    chunks: list[str] = []
    for change in changes:
        if change.status != "untracked":
            continue
        path = root / change.path
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        chunks.append(f"diff --git a/{change.path} b/{change.path}")
        chunks.append(f"new file mode 100644")
        chunks.append("--- /dev/null")
        chunks.append(f"+++ b/{change.path}")
        chunks.append(f"@@ -0,0 +1,{len(lines)} @@")
        chunks.extend(f"+{line}" for line in lines)
    return "\n".join(chunks)


def git_show(root: Path, ref: str, path: str) -> str | None:
    if ref == "WORKTREE":
        full_path = root / path
        if not full_path.exists() or not full_path.is_file():
            return None
        try:
            return full_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return None
    result = run_git(["show", f"{ref}:{path}"], root, check=False)
    if result.returncode != 0:
        return None
    return result.stdout


def symbol_map(source: str | None) -> dict[str, tuple[str, int, str]]:
    if not source:
        return {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    lines = source.splitlines()
    symbols: dict[str, tuple[str, int, str]] = {}

    def digest(node: ast.AST) -> str:
        start = getattr(node, "lineno", 1)
        end = getattr(node, "end_lineno", start)
        segment = "\n".join(lines[start - 1 : end])
        return hashlib.sha1(segment.encode("utf-8")).hexdigest()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols[node.name] = ("function", node.lineno, digest(node))
        elif isinstance(node, ast.ClassDef):
            symbols[node.name] = ("class", node.lineno, digest(node))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets: Iterable[ast.expr]
            if isinstance(node, ast.Assign):
                targets = node.targets
            else:
                targets = [node.target]
            for target_node in targets:
                if isinstance(target_node, ast.Name) and target_node.id.isupper():
                    symbols[target_node.id] = ("constant", node.lineno, digest(node))
    return symbols


def symbol_changes(root: Path, changes: Sequence[FileChange], base: str, target: str | None) -> list[SymbolChange]:
    rows: list[SymbolChange] = []
    new_ref = target or "WORKTREE"
    for change in changes:
        if not change.path.endswith(".py"):
            continue
        old_source = None if change.status in {"added", "untracked"} else git_show(root, base, change.old_path or change.path)
        new_source = None if change.status == "deleted" else git_show(root, new_ref, change.path)
        old_symbols = symbol_map(old_source)
        new_symbols = symbol_map(new_source)
        for name in sorted(set(old_symbols) | set(new_symbols)):
            if name not in old_symbols:
                kind, line, _ = new_symbols[name]
                rows.append(SymbolChange(change.path, name, kind, "added", line))
            elif name not in new_symbols:
                kind, line, _ = old_symbols[name]
                rows.append(SymbolChange(change.path, name, kind, "deleted", line))
            elif old_symbols[name][2] != new_symbols[name][2]:
                kind, line, _ = new_symbols[name]
                rows.append(SymbolChange(change.path, name, kind, "modified", line))
    return rows


def tokenize(text: str) -> set[str]:
    aliases = {
        "rate": "ratelimit",
        "limiting": "ratelimit",
        "limit": "ratelimit",
        "login": "auth",
        "signin": "auth",
        "password": "auth",
        "setting": "config",
        "settings": "config",
        "env": "config",
        "database": "db",
        "schema": "db",
        "migration": "db",
        "test": "test",
        "tests": "test",
    }
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    return {aliases.get(word, word) for word in words if len(word) > 1}


def path_tokens(path: str) -> set[str]:
    bits = tokenize(path.replace("/", " ").replace("_", " ").replace("-", " "))
    if re.search(r"(^|/)(test_|tests?/|.*_test\.|.*\.test\.)", path):
        bits.add("test")
    if any(part in path.lower() for part in ("setting", "config", ".env", "pyproject", "requirements", "package.json")):
        bits.add("config")
    if any(part in path.lower() for part in ("auth", "login", "signin", "oauth")):
        bits.add("auth")
    if any(part in path.lower() for part in ("migration", "schema", "models")):
        bits.add("db")
    return bits


def has_boundary_language(intent: str) -> bool:
    lowered = intent.lower()
    markers = [
        "其他不要",
        "不要動其他",
        "不要改其他",
        "only",
        "nothing else",
        "do not change unrelated",
        "don't change unrelated",
    ]
    return any(marker in lowered for marker in markers)


def classify_file(intent: str, change: FileChange) -> str:
    if not intent:
        return "needs review"
    intent_bits = tokenize(intent)
    file_bits = path_tokens(change.path)
    if file_bits & intent_bits:
        return "matches intent"
    if "test" in file_bits and "test" not in intent_bits:
        return "supporting change"
    risky_scopes = {"config", "db"}
    if file_bits & risky_scopes and not (intent_bits & risky_scopes):
        return "unexpected"
    if has_boundary_language(intent):
        return "unexpected"
    return "needs review"


def intent_gap(intent: str, changes: Sequence[FileChange]) -> tuple[list[str], list[str], list[str]]:
    matches: list[str] = []
    unexpected: list[str] = []
    missing: list[str] = []
    for change in changes:
        classification = classify_file(intent, change)
        if classification in {"matches intent", "supporting change"}:
            matches.append(f"{change.path} ({classification})")
        elif classification == "unexpected":
            unexpected.append(f"{change.path} ({change.status})")
    test_changed = any("test" in path_tokens(change.path) for change in changes)
    if intent and not test_changed and any(change.status in {"added", "modified", "untracked"} for change in changes):
        missing.append("No test file changes detected. Be ready to explain manual coverage or add tests.")
    if not matches and changes and intent:
        missing.append("No changed file clearly matches the intent keywords. Review the intent/change alignment manually.")
    return matches, unexpected, missing


def scan_security_delta(diff: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    current_file = ""
    new_line: int | None = None
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:]
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            new_line = int(match.group(1)) - 1 if match else None
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            if new_line is not None:
                new_line += 1
            line = raw[1:]
            lowered = line.lower()
            checks = [
                (r"\b(eval|exec)\s*\(", "red", "Dynamic code execution added."),
                (r"shell\s*=\s*true", "red", "Subprocess shell=True added."),
                (r"(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}", "red", "Possible hard-coded secret added."),
                (r"remote_addr|x-forwarded-for", "yellow", "IP-derived logic added. Verify reverse proxy trust boundaries."),
                (r"debug\s*=\s*true", "yellow", "Debug mode appears to be enabled."),
                (r"select .*%|select .*\.format|select .*f['\"]", "yellow", "SQL string construction added. Check injection safety."),
            ]
            for pattern, severity, message in checks:
                if re.search(pattern, lowered):
                    findings.append(SecurityFinding(severity, current_file, new_line, message))
        elif raw.startswith("-") and not raw.startswith("---"):
            continue
        elif new_line is not None:
            new_line += 1
    return findings


def render_status(classification: str) -> str:
    if classification == "matches intent":
        return "OK"
    if classification == "supporting change":
        return "Support"
    if classification == "unexpected":
        return "Review"
    return "Check"


def markdown_report(
    *,
    root: Path,
    session: IntentRecord | None,
    changes: Sequence[FileChange],
    symbols: Sequence[SymbolChange],
    findings: Sequence[SecurityFinding],
    base_label: str,
    target_label: str,
    commit: str | None,
) -> str:
    intent = session.intent if session else ""
    session_id = session.session_id if session else f"{stamp()}-ad-hoc"
    matches, unexpected, missing = intent_gap(intent, changes)
    lines: list[str] = []
    lines.append("# vibeintent Session Report")
    lines.append("")
    lines.append(f"**Session:** `{session_id}`")
    lines.append(f"**Generated:** {iso_now()}")
    lines.append(f"**Intent:** {intent or 'No intent recorded'}")
    lines.append(f"**Range:** `{base_label}` -> `{target_label}`")
    if commit:
        lines.append(f"**Commit:** `{commit}`")
    lines.append("")
    lines.append("## Changed Files")
    lines.append("")
    if changes:
        lines.append("| File | Status | + | - | Intent Fit |")
        lines.append("|---|---:|---:|---:|---|")
        for change in changes:
            classification = classify_file(intent, change)
            path = change.path if not change.old_path else f"{change.old_path} -> {change.path}"
            lines.append(
                f"| `{path}` | {change.status} | {change.added} | {change.deleted} | {render_status(classification)} |"
            )
    else:
        lines.append("No Git changes detected.")
    lines.append("")
    lines.append("## Function And Class Changes")
    lines.append("")
    if symbols:
        for item in symbols:
            line = f":{item.line}" if item.line else ""
            lines.append(f"- `{item.path}{line}` `{item.kind} {item.symbol}` {item.status}")
    else:
        lines.append("No Python function/class-level changes detected.")
    lines.append("")
    lines.append("## Intent Gap")
    lines.append("")
    if matches:
        lines.append("**Matches intent**")
        for item in matches:
            lines.append(f"- {item}")
    else:
        lines.append("**Matches intent**")
        lines.append("- No clear match detected by offline heuristics.")
    lines.append("")
    lines.append("**Unexpected or needs reviewer attention**")
    if unexpected:
        for item in unexpected:
            lines.append(f"- {item}")
    else:
        lines.append("- No high-confidence unexpected file changes detected.")
    lines.append("")
    lines.append("**Missing or unproven**")
    if missing:
        for item in missing:
            lines.append(f"- {item}")
    else:
        lines.append("- No obvious missing item detected by offline heuristics.")
    lines.append("")
    lines.append("## Security Delta")
    lines.append("")
    if findings:
        for finding in findings:
            label = "RED" if finding.severity == "red" else "YELLOW"
            line = f":{finding.line}" if finding.line else ""
            lines.append(f"- {label} `{finding.path}{line}` - {finding.message}")
    else:
        lines.append("No basic added-line security findings.")
    lines.append("")
    lines.append("## Reviewer Prep")
    lines.append("")
    lines.append("- Explain why each changed file belongs in this session.")
    lines.append("- For every `Review` file above, decide whether to revert, keep, or split into another commit.")
    lines.append("- Be ready to describe test coverage, especially if no test file changed.")
    return "\n".join(lines) + "\n"


def write_report(root: Path, session: IntentRecord | None, markdown: str) -> Path:
    ensure_workspace(root)
    session_id = session.session_id if session else f"{stamp()}-ad-hoc"
    path = sessions_dir(root) / f"{session_id}.md"
    if path.exists():
        path = sessions_dir(root) / f"{session_id}-{stamp()}.md"
    path.write_text(markdown, encoding="utf-8")
    latest = vibe_dir(root) / "latest_report"
    latest.write_text(str(path.relative_to(root)) + "\n", encoding="utf-8")
    return path


def latest_report_path(root: Path) -> Path | None:
    latest = vibe_dir(root) / "latest_report"
    if latest.exists():
        candidate = root / latest.read_text(encoding="utf-8").strip()
        if candidate.exists():
            return candidate
    reports = sorted(sessions_dir(root).glob("*.md")) if sessions_dir(root).exists() else []
    return reports[-1] if reports else None


def generate_report(root: Path, from_hook: bool = False, commit: str | None = None) -> tuple[str, Path]:
    ensure_workspace(root)
    session = load_current_intent(root)
    target: str | None = None
    commit_label = None
    if from_hook:
        target = commit or "HEAD"
        base = commit_parent(root, target)
        target_hash = run_git(["rev-parse", "--short", target], root).stdout.strip()
        base_label = run_git(["rev-parse", "--short", base], root, check=False).stdout.strip() or "empty tree"
        target_label = target_hash
        commit_label = target_hash
        include_untracked = False
    else:
        base = session.base_ref if session else current_head(root)[0]
        base_label = session.base_label if session else current_head(root)[1]
        target_label = "working tree"
        include_untracked = True
    changes = diff_changes(root, base, target, include_untracked=include_untracked)
    symbols = symbol_changes(root, changes, base, target)
    raw_diff = diff_text(root, base, target)
    if target is None:
        extra_diff = untracked_diff_text(root, changes)
        if extra_diff:
            raw_diff = raw_diff.rstrip() + "\n" + extra_diff + "\n"
    findings = scan_security_delta(raw_diff)
    markdown = markdown_report(
        root=root,
        session=session,
        changes=changes,
        symbols=symbols,
        findings=findings,
        base_label=base_label,
        target_label=target_label,
        commit=commit_label,
    )
    path = write_report(root, session, markdown)
    return markdown, path


def cmd_init(_: argparse.Namespace) -> int:
    root = repo_root()
    ensure_workspace(root)
    hook = install_post_commit_hook(root)
    print(f"Initialized vibeintent in {root}")
    print(f"Installed post-commit hook: {hook}")
    return 0


def cmd_intent(args: argparse.Namespace) -> int:
    root = repo_root()
    intent = " ".join(args.intent).strip()
    if not intent:
        raise VibeIntentError("intent text cannot be empty")
    base_ref, base_label = current_head(root)
    record = IntentRecord(
        session_id=make_session_id(intent),
        created_at=iso_now(),
        intent=intent,
        base_ref=base_ref,
        base_label=base_label,
    )
    save_intent(root, record)
    print(f"Recorded intent `{record.session_id}` at {record.base_label}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = repo_root()
    markdown, path = generate_report(root, from_hook=args.from_hook, commit=args.commit)
    if not args.quiet:
        print(markdown)
        print(f"Saved report: {path}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    root = repo_root()
    path = latest_report_path(root)
    if path is None:
        markdown, path = generate_report(root)
    else:
        markdown = path.read_text(encoding="utf-8")
    if args.pr:
        print(pr_summary(markdown))
    else:
        print(markdown)
    return 0


def pr_summary(markdown: str) -> str:
    keep_sections = {"# vibeintent Session Report", "## Changed Files", "## Intent Gap", "## Security Delta"}
    lines = markdown.splitlines()
    output: list[str] = []
    include = False
    for line in lines:
        if line.startswith("#"):
            include = line in keep_sections
        if include:
            output.append(line)
    return "\n".join(output).strip() + "\n"


def cmd_log(_: argparse.Namespace) -> int:
    root = repo_root()
    if not sessions_dir(root).exists():
        print("No vibeintent sessions yet.")
        return 0
    reports = sorted(sessions_dir(root).glob("*.md"))
    if not reports:
        print("No vibeintent sessions yet.")
        return 0
    for report in reports:
        text = report.read_text(encoding="utf-8")
        intent_match = re.search(r"\*\*Intent:\*\* (.+)", text)
        generated_match = re.search(r"\*\*Generated:\*\* (.+)", text)
        intent = intent_match.group(1) if intent_match else "Unknown intent"
        generated = generated_match.group(1) if generated_match else "unknown time"
        print(f"{report.stem}\t{generated}\t{intent}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    root = repo_root()
    query = args.session_id
    candidates = sorted(sessions_dir(root).glob(f"*{query}*.md")) if sessions_dir(root).exists() else []
    if not candidates:
        raise VibeIntentError(f"No session report matched `{query}`")
    print(candidates[-1].read_text(encoding="utf-8"))
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    root = repo_root()
    rel = args.path
    path = root / rel
    if not path.exists():
        raise VibeIntentError(f"{rel} does not exist")
    source = path.read_text(encoding="utf-8")
    symbols = symbol_map(source)
    print(f"# Module Snapshot: `{rel}`")
    print("")
    print(f"- Lines: {len(source.splitlines())}")
    if not symbols:
        print("- No Python functions/classes/constants detected.")
        return 0
    for name, (kind, line, _) in sorted(symbols.items(), key=lambda item: item[1][1]):
        print(f"- `{kind} {name}` at line {line}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vibeintent", description="Intent-aware Git diff reports for AI coding.")
    parser.add_argument("--version", action="version", version=f"vibeintent {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize .vibeintent and install git hooks.")
    init.set_defaults(func=cmd_init)

    intent = sub.add_parser("intent", help="Record the intent for the current AI coding session.")
    intent.add_argument("intent", nargs=argparse.REMAINDER)
    intent.set_defaults(func=cmd_intent)

    check = sub.add_parser("check", help="Generate a report for current changes.")
    check.add_argument("--from-hook", action="store_true", help=argparse.SUPPRESS)
    check.add_argument("--commit", help=argparse.SUPPRESS)
    check.add_argument("--quiet", action="store_true", help="Write the report without printing it.")
    check.set_defaults(func=cmd_check)

    report = sub.add_parser("report", help="Print the latest report, generating one if needed.")
    report.add_argument("--pr", action="store_true", help="Print a shorter PR-description oriented report.")
    report.set_defaults(func=cmd_report)

    log = sub.add_parser("log", help="List session reports.")
    log.set_defaults(func=cmd_log)

    show = sub.add_parser("show", help="Show a previous report by id or id fragment.")
    show.add_argument("session_id")
    show.set_defaults(func=cmd_show)

    explain = sub.add_parser("explain", help="Print a local module snapshot for a Python file.")
    explain.add_argument("path")
    explain.set_defaults(func=cmd_explain)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except VibeIntentError as exc:
        print(f"vibeintent: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
