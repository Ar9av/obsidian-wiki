"""Delegate skill ownership and updates to Hermes, not its private lockfile."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def install(args: argparse.Namespace, skills: list[str]) -> int:
    """Install selected upstream skills without bypassing Hermes' security policy."""
    raw_home = args.hermes_home or os.environ.get("HERMES_HOME", "")
    home = Path(raw_home).expanduser()
    if not raw_home or not home.is_absolute() or not home.is_dir():
        print("error: set HERMES_HOME or --hermes-home to an existing absolute profile directory", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*", args.source):
        print("error: --source must be a GitHub owner/repo identifier", file=sys.stderr)
        return 1
    home = home.resolve()
    selected = list(dict.fromkeys(args.skill or skills))
    if any(name not in skills for name in selected):
        print("error: unknown wiki skill; use obsidian-wiki list", file=sys.stderr)
        return 1
    for name in selected:
        target = home / "skills" / name
        if target.exists() or target.is_symlink():
            print(f"error: {target} already exists; preserve local edits and use hermes skills check/update instead", file=sys.stderr)
            return 1
    print(f"Hermes home: {home}")
    # Direct SKILL.md URLs avoid native source adapters resolving a fully
    # qualified GitHub identifier to an unrelated same-named official skill.
    commands = [["hermes", "skills", "install",
                 f"https://raw.githubusercontent.com/{args.source}/HEAD/skills/{name}/SKILL.md",
                 "--name", name, *(["--yes"] if args.yes else [])]
                for name in selected]
    for command in commands:
        print(subprocess.list2cmdline(command))
    if args.dry_run:
        return 0
    executable = shutil.which("hermes")
    if not executable:
        print("error: Hermes CLI not found on PATH", file=sys.stderr)
        return 1
    env = dict(os.environ, HERMES_HOME=str(home), HERMES_PROFILE="")
    # Keep going past a failed skill: Hermes' scanner and URL adapter reject
    # some skills on their own (and exit 0 when they do), so stopping at the
    # first one would leave every later skill uninstalled.
    failed: list[str] = []
    for command in commands:
        name = command[5]
        try:
            subprocess.run([executable, *command[1:]], env=env, shell=False)
        except OSError as exc:
            print(f"error: could not launch Hermes: {exc}", file=sys.stderr)
            return 1
        if not (home / "skills" / name / "SKILL.md").is_file():
            failed.append(name)
    installed = len(commands) - len(failed)
    print(f"\nInstalled {installed}/{len(commands)} skill(s) into {home}")
    if failed:
        print(f"Not installed (blocked, unfetchable or cancelled): {', '.join(failed)}", file=sys.stderr)
        print("Review the Hermes output above, then retry with --skill " + " --skill ".join(failed), file=sys.stderr)
        return 1
    return 0
