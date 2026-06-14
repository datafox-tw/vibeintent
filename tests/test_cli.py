from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        ["python3", "-m", "vibeintent", *args],
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {args}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


class VibeIntentCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init"], cwd=self.repo, check=True, stdout=subprocess.PIPE)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.repo, check=True)
        (self.repo / "auth.py").write_text(
            "def login_view(request):\n"
            "    return 'ok'\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "auth.py"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.repo, check=True, stdout=subprocess.PIPE)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_intent_and_check_create_report_with_symbols(self) -> None:
        run(["init"], self.repo)
        run(["intent", "Add login rate limiting, do not change unrelated files"], self.repo)
        (self.repo / "auth.py").write_text(
            "RATE_LIMIT = 5\n\n"
            "def login_view(request):\n"
            "    ip = request.META['REMOTE_ADDR']\n"
            "    return f'limited {ip}'\n",
            encoding="utf-8",
        )
        (self.repo / "settings.py").write_text("DEBUG = True\n", encoding="utf-8")
        result = run(["check"], self.repo)
        self.assertIn("auth.py", result.stdout)
        self.assertIn("function login_view", result.stdout)
        self.assertIn("settings.py", result.stdout)
        self.assertIn("Review", result.stdout)
        self.assertIn("Security Delta", result.stdout)
        reports = list((self.repo / ".vibeintent" / "sessions").glob("*.md"))
        self.assertEqual(len(reports), 1)

    def test_init_installs_non_blocking_post_commit_hook(self) -> None:
        run(["init"], self.repo)
        hook = (self.repo / ".git" / "hooks" / "post-commit").read_text(encoding="utf-8")
        self.assertIn(") >/dev/null 2>&1 &", hook)
        self.assertIn("vibeintent check --from-hook --quiet", hook)
        self.assertNotIn("pre-commit", hook)

        old_hook = hook.replace(") >/dev/null 2>&1 &", ">/dev/null 2>&1 || true")
        (self.repo / ".git" / "hooks" / "post-commit").write_text(old_hook, encoding="utf-8")
        run(["init"], self.repo)
        upgraded = (self.repo / ".git" / "hooks" / "post-commit").read_text(encoding="utf-8")
        self.assertIn(") >/dev/null 2>&1 &", upgraded)
        self.assertNotIn("|| true", upgraded)

    def test_log_and_show_latest_report(self) -> None:
        run(["intent", "Update auth module"], self.repo)
        (self.repo / "auth.py").write_text(
            "def login_view(request):\n"
            "    return 'changed'\n",
            encoding="utf-8",
        )
        run(["check", "--quiet"], self.repo)
        log = run(["log"], self.repo).stdout
        session_id = log.split("\t", 1)[0]
        shown = run(["show", session_id], self.repo).stdout
        self.assertIn("Update auth module", shown)
        self.assertIn("auth.py", shown)

    def test_explain_file(self) -> None:
        output = run(["explain", "auth.py"], self.repo).stdout
        self.assertIn("Module Snapshot", output)
        self.assertIn("function login_view", output)


if __name__ == "__main__":
    unittest.main()
