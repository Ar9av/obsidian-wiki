"""Install, remove, and inspect the Claude Code session hooks.

Two hooks bracket a session: ``wiki-session-recap.sh`` at SessionStart injects
the vault's memory, ``wiki-stop-capture.sh`` at Stop nudges a capture. They
only take effect once registered in ``~/.claude/settings.json``.

Until now that registration was a prose procedure in ``wiki-setup`` — locate
the script, hand-merge JSON, don't clobber other hooks — and only the Stop hook
had one. So a normal pip install got the storage and the CLI but never the
session-start injection, which is the headline feature. This is that procedure
as code, for both hooks, idempotent, and checkable by ``doctor``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

#: (event, script name) — the order they run in a session.
HOOKS = (
    ("SessionStart", "wiki-session-recap.sh"),
    ("Stop", "wiki-stop-capture.sh"),
)


def _pkg_dir() -> Path:
    return Path(__file__).resolve().parent


def hook_script(name: str) -> Optional[Path]:
    """Where the bundled hook lives: wheel ``_data/hooks`` or checkout ``.claude/hooks``."""
    for candidate in (
        _pkg_dir() / "_data" / "hooks" / name,
        _pkg_dir().parent / ".claude" / "hooks" / name,
    ):
        if candidate.is_file():
            return candidate
    return None


def settings_path(home: Optional[Path] = None) -> Path:
    return (home or Path.home()) / ".claude" / "settings.json"


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _command_for(script: Path) -> str:
    return f"bash {script}"


def _registered_commands(data: dict, event: str) -> list:
    commands = []
    for group in data.get("hooks", {}).get(event, []) or []:
        for entry in (group or {}).get("hooks", []) or []:
            if isinstance(entry, dict) and entry.get("type") == "command":
                commands.append(str(entry.get("command", "")))
    return commands


def is_registered(data: dict, event: str, script_name: str) -> bool:
    """True when some command for *event* runs a script by this name.

    Matched by basename rather than full path, so a checkout registration at a
    relative path and a global one at an absolute path both count. That is
    also why install is idempotent across the two.
    """
    return any(script_name in command for command in _registered_commands(data, event))


@dataclass(frozen=True)
class HookStatus:
    event: str
    script: str
    bundled: Optional[str]      # where the script was found, or None
    registered: bool
    executable: bool


def status(home: Optional[Path] = None) -> list:
    data = _load(settings_path(home))
    out = []
    for event, name in HOOKS:
        script = hook_script(name)
        out.append(HookStatus(
            event=event,
            script=name,
            bundled=str(script) if script else None,
            registered=is_registered(data, event, name),
            executable=bool(script and os.access(script, os.X_OK)),
        ))
    return out


def install(home: Optional[Path] = None, *, only: Optional[str] = None) -> dict:
    """Register the hooks, appending to whatever is already there.

    Never replaces an existing entry: a user's other hooks for the same event
    stay, and a hook already registered under any path is left alone.
    """
    path = settings_path(home)
    data = _load(path)
    hooks = data.setdefault("hooks", {})
    added, skipped, missing = [], [], []

    for event, name in HOOKS:
        if only and event != only:
            continue
        script = hook_script(name)
        if script is None:
            missing.append(name)
            continue
        if is_registered(data, event, name):
            skipped.append(name)
            continue
        groups = hooks.setdefault(event, [])
        groups.append({
            "matcher": "",
            "hooks": [{"type": "command", "command": _command_for(script)}],
        })
        added.append(name)

    if added:
        _write(path, data)
    return {"settings": str(path), "added": added, "already": skipped, "missing": missing}


def uninstall(home: Optional[Path] = None, *, only: Optional[str] = None) -> dict:
    """Remove our entries and nothing else."""
    path = settings_path(home)
    data = _load(path)
    removed = []
    hooks = data.get("hooks", {})
    for event, name in HOOKS:
        if only and event != only:
            continue
        kept = []
        for group in hooks.get(event, []) or []:
            entries = [
                entry for entry in (group or {}).get("hooks", []) or []
                if not (isinstance(entry, dict) and name in str(entry.get("command", "")))
            ]
            if len(entries) != len((group or {}).get("hooks", []) or []):
                removed.append(name)
            if entries:
                kept.append({**group, "hooks": entries})
        if event in hooks:
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
    if removed:
        _write(path, data)
    return {"settings": str(path), "removed": sorted(set(removed))}


def reachability() -> dict:
    """Can the recap hook actually run the package from a hook's environment?

    The hook prefers ``obsidian-wiki`` on PATH and falls back to
    ``python3 -m obsidian_wiki.cli``. If neither works it exits silently by
    design — safe, but invisible — so this is the one place that says so.
    """
    on_path = shutil.which("obsidian-wiki")
    python3 = shutil.which("python3")
    importable = False
    if python3:
        try:
            probe = subprocess.run(
                [python3, "-c", "import obsidian_wiki"],
                capture_output=True, text=True, timeout=15,
            )
            importable = probe.returncode == 0
        except (OSError, subprocess.SubprocessError):
            importable = False
    return {
        "console_script": on_path,
        "python3": python3,
        "python3_can_import": importable,
        "reachable": bool(on_path or importable),
        "hint": (
            "" if (on_path or importable) else
            f"install into the interpreter hooks use, or put `obsidian-wiki` on PATH "
            f"(this session's interpreter is {sys.executable})"
        ),
    }
