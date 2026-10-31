#!/usr/bin/env python3
"""Install the DeepSeek web-search skill for selected local agents."""
import argparse
import filecmp
import os
from pathlib import Path
import shutil
import sys
import tempfile

SKILL_NAME = "deepseek-web-search"
SOURCE = Path(__file__).resolve().parent / SKILL_NAME
AGENTS = ("codex", "claude", "gemini", "opencode", "copilot", "agents")


def target_for(agent):
    home = Path.home()
    roots = {
        "codex": Path(os.environ.get("CODEX_HOME") or home / ".codex").expanduser() / "skills",
        "claude": home / ".claude" / "skills",
        "gemini": home / ".gemini" / "skills",
        "opencode": home / ".config" / "opencode" / "skills",
        "copilot": home / ".copilot" / "skills",
        "agents": home / ".agents" / "skills",
    }
    return roots[agent] / SKILL_NAME


def ignored(directory, names):
    return {name for name in names if name == "__pycache__" or name.endswith((".pyc", ".pyo"))}


def same_files(left, right):
    """Compare files exactly, excluding transient Python bytecode."""
    if left.is_symlink() or right.is_symlink() or not left.is_dir() or not right.is_dir():
        return False
    left_names = {p.name for p in left.iterdir()} - ignored(left, [p.name for p in left.iterdir()])
    right_names = {p.name for p in right.iterdir()} - ignored(right, [p.name for p in right.iterdir()])
    if left_names != right_names:
        return False
    for name in left_names:
        a, b = left / name, right / name
        if a.is_symlink() or b.is_symlink():
            return False
        if a.is_dir() and b.is_dir():
            if not same_files(a, b):
                return False
        elif a.is_file() and b.is_file():
            if not filecmp.cmp(a, b, shallow=False):
                return False
        else:
            return False
    return True


def install_one(target, force):
    if target.is_symlink():
        raise ValueError(f"Refusing symlink target: {target}")
    if target.exists():
        if not target.is_dir():
            raise ValueError(f"Install target is not a directory: {target}")
        if same_files(SOURCE, target):
            print(f"Already installed: {target}")
            return
        if not force:
            raise ValueError(f"Existing skill differs: {target}; use --force to replace it")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Stage and back up in the target's filesystem, so the target changes only
    # after the complete skill has been copied and can be restored on failure.
    with tempfile.TemporaryDirectory(prefix=".deepseek-install-", dir=target.parent) as tmp:
        tmp_dir = Path(tmp)
        staged = tmp_dir / "new"
        backup = tmp_dir / "old"
        shutil.copytree(SOURCE, staged, ignore=ignored)
        if target.is_symlink():
            raise ValueError(f"Refusing symlink target: {target}")
        had_target = target.exists()
        if had_target:
            if not force:
                raise ValueError(f"Install target appeared during install: {target}")
            os.replace(target, backup)
        try:
            os.replace(staged, target)
        except OSError:
            if had_target:
                os.replace(backup, target)
            raise
    print(f"Installed: {target}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", action="append", choices=AGENTS, required=True,
                        help="Target agent; repeat for multiple targets")
    parser.add_argument("--force", action="store_true", help="Replace an existing differing skill directory")
    args = parser.parse_args(argv)
    if not SOURCE.is_dir() or not (SOURCE / "SKILL.md").is_file():
        print("Skill source is missing SKILL.md.", file=sys.stderr)
        return 1
    targets = list(dict.fromkeys(target_for(agent) for agent in args.agent))
    try:
        # Check every destination before making changes, where possible.
        for target in targets:
            if target.is_symlink():
                raise ValueError(f"Refusing symlink target: {target}")
            if target.exists() and (not target.is_dir() or (not args.force and not same_files(SOURCE, target))):
                raise ValueError(f"Install target exists or differs: {target}; use --force to replace a directory")
        for target in targets:
            install_one(target, args.force)
    except (OSError, ValueError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
