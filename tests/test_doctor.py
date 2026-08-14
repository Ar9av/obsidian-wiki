"""Tests for the doctor CLI command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from obsidian_wiki.cli import list_skills

from conftest import build_index_state, make_fake_codegraph_bin, make_project


def _run(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _run_env(
    home: Path, env_overrides: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _write_config(home: Path, vault: Path, *, version: str | None = None) -> None:
    config_dir = home / ".obsidian-wiki"
    config_dir.mkdir(parents=True, exist_ok=True)
    lines = [f'OBSIDIAN_VAULT_PATH="{vault}"']
    if version is not None:
        lines.append(f'OBSIDIAN_WIKI_VERSION="{version}"')
    (config_dir / "config").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_vault(vault: Path, *, manifest: str = '{"sources": {}}') -> None:
    vault.mkdir(parents=True, exist_ok=True)
    for name in ("index.md", "log.md", "hot.md"):
        (vault / name).write_text(f"# {name}\n", encoding="utf-8")
    (vault / ".manifest.json").write_text(manifest, encoding="utf-8")


def _install_all_skills(home: Path) -> None:
    target = home / ".claude" / "skills"
    target.mkdir(parents=True, exist_ok=True)
    for name in list_skills():
        skill_dir = target / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")


def test_doctor_json_clean_install(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _make_vault(vault)
    _write_config(home, vault)
    _install_all_skills(home)

    proc = _run(home, "doctor", "--json")

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["status"] == "pass"
    assert any(check["name"] == "manifest-json" and check["status"] == "pass" for check in data["checks"])


def test_doctor_warns_without_agent_installs_but_exits_zero(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _make_vault(vault)
    _write_config(home, vault)

    proc = _run(home, "doctor", "--json")

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["status"] == "warn"
    assert any(check["name"] == "agent-installs" and check["status"] == "warn" for check in data["checks"])


def test_doctor_fails_on_invalid_manifest(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _make_vault(vault, manifest="{not json")
    _write_config(home, vault)
    _install_all_skills(home)

    proc = _run(home, "doctor", "--json")

    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["status"] == "fail"
    assert any(check["name"] == "manifest-json" and check["status"] == "fail" for check in data["checks"])


def test_doctor_strict_turns_warnings_into_nonzero_exit(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _make_vault(vault)
    _write_config(home, vault, version="0.0.0")

    proc = _run(home, "doctor", "--json", "--strict")

    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert any(check["name"] == "setup-version" and check["status"] == "warn" for check in data["checks"])


def test_doctor_without_project_has_no_code_understanding_checks(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _make_vault(vault)
    _write_config(home, vault)
    _install_all_skills(home)

    proc = _run(home, "doctor", "--json")

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert not any(check["name"].startswith("code-understanding") for check in data["checks"])


def test_doctor_project_shows_builtin_checks(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _make_vault(vault)
    _write_config(home, vault)
    _install_all_skills(home)
    project = make_project(tmp_path, {"src/foo.py": "def foo():\n    return 1\n"}, git=False)

    proc = _run(home, "doctor", "--json", "--project", str(project))

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    names = {check["name"] for check in data["checks"]}
    assert "code-understanding.builtin" in names
    assert "code-understanding.rg" in names
    assert data["status"] != "fail"


def test_doctor_project_auto_missing_codegraph_is_warn_not_fail(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _make_vault(vault)
    _write_config(home, vault)
    _install_all_skills(home)
    project = make_project(tmp_path, {"src/foo.py": "def foo():\n    return 1\n"}, git=False)
    no_bin = tmp_path / "no-bin"
    no_bin.mkdir()

    proc = _run_env(home, {"PATH": str(no_bin), "CODE_UNDERSTANDING_CODEGRAPH_BIN": ""}, "doctor", "--json", "--project", str(project))

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["status"] != "fail"
    check = next(c for c in data["checks"] if c["name"] == "code-understanding.codegraph")
    assert check["status"] == "warn"


def test_doctor_project_explicit_codegraph_broken_fails(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _make_vault(vault)
    _write_config(home, vault)
    _install_all_skills(home)
    project = make_project(tmp_path, {"src/foo.py": "def foo():\n    return 1\n"}, git=False)
    no_bin = tmp_path / "no-bin"
    no_bin.mkdir()

    proc = _run_env(
        home,
        {"PATH": str(no_bin), "CODE_UNDERSTANDING_BACKEND": "codegraph", "CODE_UNDERSTANDING_CODEGRAPH_BIN": ""},
        "doctor",
        "--json",
        "--project",
        str(project),
    )

    assert proc.returncode == 1
    data = json.loads(proc.stdout)
    assert data["status"] == "fail"
    check = next(c for c in data["checks"] if c["name"] == "code-understanding.codegraph")
    assert check["status"] == "fail"


def test_doctor_project_codegraph_enhanced_checks_pass(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _make_vault(vault)
    _write_config(home, vault)
    _install_all_skills(home)
    project = make_project(tmp_path, {"src/foo.py": "def foo():\n    return 1\n"}, git=False)
    codegraph_bin = make_fake_codegraph_bin(tmp_path)
    build_index_state(project)
    no_bin = tmp_path / "no-bin"
    no_bin.mkdir()

    proc = _run_env(
        home,
        {"PATH": str(no_bin), "CODE_UNDERSTANDING_CODEGRAPH_BIN": str(codegraph_bin)},
        "doctor",
        "--json",
        "--project",
        str(project),
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    statuses = {check["name"]: check["status"] for check in data["checks"]}
    assert statuses["code-understanding.codegraph"] == "pass"
    assert statuses["code-understanding.codegraph-index"] == "pass"
    assert statuses["code-understanding.codegraph-fresh"] == "pass"


def test_doctor_project_index_stale_warns(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _make_vault(vault)
    _write_config(home, vault)
    _install_all_skills(home)
    project = make_project(tmp_path, {"src/foo.py": "def foo():\n    return 1\n"}, git=False)
    codegraph_bin = make_fake_codegraph_bin(tmp_path)
    build_index_state(project, fresh=False)
    no_bin = tmp_path / "no-bin"
    no_bin.mkdir()

    proc = _run_env(
        home,
        {"PATH": str(no_bin), "CODE_UNDERSTANDING_CODEGRAPH_BIN": str(codegraph_bin)},
        "doctor",
        "--json",
        "--project",
        str(project),
    )

    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    check = next(c for c in data["checks"] if c["name"] == "code-understanding.codegraph-fresh")
    assert check["status"] == "warn"
