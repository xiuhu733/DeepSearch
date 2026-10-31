"""Offline tests for installing the same skill in supported agent layouts."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "install.py"
SKILL = "deepseek-web-search"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = {**os.environ, "HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        self.env.pop("CODEX_HOME", None)

    def run_install(self, *args):
        return subprocess.run([sys.executable, str(INSTALLER), *args], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_installs_selected_layouts_and_does_not_copy_bytecode(self):
        agents = ["codex", "claude", "gemini", "opencode", "copilot", "agents"]
        args = [value for agent in agents for value in ("--agent", agent)]
        run = self.run_install(*args)
        self.assertEqual(run.returncode, 0, run.stderr)
        roots = [".codex/skills", ".claude/skills", ".gemini/skills",
                 ".config/opencode/skills", ".copilot/skills", ".agents/skills"]
        for root in roots:
            directory = self.home / root / SKILL
            self.assertTrue((directory / "SKILL.md").is_file())
            self.assertTrue((directory / "scripts" / "deepseek_search.py").is_file())
            self.assertTrue((directory / "scripts" / "deepseek_batch.py").is_file())
            self.assertFalse(any(directory.rglob("__pycache__")))

    def test_honors_codex_home(self):
        self.env["CODEX_HOME"] = str(self.home / "custom-codex")
        run = self.run_install("--agent", "codex")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue((self.home / "custom-codex/skills" / SKILL / "SKILL.md").exists())
        self.assertFalse((self.home / ".codex/skills" / SKILL).exists())

    def test_repeated_install_is_idempotent(self):
        self.assertEqual(self.run_install("--agent", "claude").returncode, 0)
        target = self.home / ".claude/skills" / SKILL / "SKILL.md"
        before = target.stat().st_mtime_ns
        run = self.run_install("--agent", "claude")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("Already installed", run.stdout)
        self.assertEqual(target.stat().st_mtime_ns, before)

    def test_conflict_does_not_overwrite_or_partially_install(self):
        target = self.home / ".claude/skills" / SKILL
        target.mkdir(parents=True)
        (target / "custom.txt").write_text("user data", encoding="utf-8")
        run = self.run_install("--agent", "gemini", "--agent", "claude")
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual((target / "custom.txt").read_text(), "user data")
        self.assertFalse((self.home / ".gemini/skills" / SKILL).exists())

    def test_force_replaces_target_but_preserves_neighbor(self):
        target = self.home / ".claude/skills" / SKILL
        target.mkdir(parents=True)
        (target / "old.txt").write_text("old", encoding="utf-8")
        sibling = target.parent / "another-skill"
        sibling.mkdir()
        (sibling / "keep.txt").write_text("untouched", encoding="utf-8")
        run = self.run_install("--agent", "claude", "--force")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue((target / "SKILL.md").exists())
        self.assertFalse((target / "old.txt").exists())
        self.assertEqual((sibling / "keep.txt").read_text(), "untouched")

    def test_refuses_symlink_target_even_with_force(self):
        outside = self.home / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep", encoding="utf-8")
        parent = self.home / ".claude/skills"
        parent.mkdir(parents=True)
        (parent / SKILL).symlink_to(outside, target_is_directory=True)
        run = self.run_install("--agent", "claude", "--force")
        self.assertNotEqual(run.returncode, 0)
        self.assertTrue((parent / SKILL).is_symlink())
        self.assertEqual((outside / "keep.txt").read_text(), "keep")

    def test_shared_parent_symlinks_are_idempotent(self):
        shared = self.home / "shared-skills"
        shared.mkdir()
        for owner in (".claude", ".agents"):
            parent = self.home / owner
            parent.mkdir()
            (parent / "skills").symlink_to(shared, target_is_directory=True)
        run = self.run_install("--agent", "claude", "--agent", "agents")
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.count("Installed:"), 1)
        self.assertEqual(run.stdout.count("Already installed:"), 1)
        self.assertTrue((shared / SKILL / "SKILL.md").is_file())

    def test_invalid_or_missing_agent_is_rejected(self):
        self.assertNotEqual(self.run_install().returncode, 0)
        self.assertNotEqual(self.run_install("--agent", "unknown").returncode, 0)


if __name__ == "__main__":
    unittest.main()
