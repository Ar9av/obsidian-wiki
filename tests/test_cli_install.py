from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path

import pytest

import obsidian_wiki.cli as cli


def test_configure_console_output_replaces_unencodable_status_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="gbk", errors="strict")
    monkeypatch.setattr(cli.sys, "stdout", stream)

    cli._configure_console_output()
    print("✅", file=cli.sys.stdout)
    cli.sys.stdout.flush()

    assert raw.getvalue()
    stream.detach()


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are Windows-only")
def test_install_skills_replaces_windows_junction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_root = tmp_path / "bundled-skills"
    skill = source_root / "junction-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: junction-skill\n---\n", encoding="utf-8")

    target_root = tmp_path / "target-skills"
    target_root.mkdir()
    old_root = tmp_path / "old-skills"
    old_skill = old_root / "junction-skill"
    old_skill.mkdir(parents=True)
    (old_skill / "SKILL.md").write_text("old\n", encoding="utf-8")

    junction = target_root / "junction-skill"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(old_skill)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"directory junctions unavailable: {result.stderr or result.stdout}")

    monkeypatch.setattr(cli, "skills_dir", lambda: source_root)

    cli.install_skills(target_root, "test", mode="copy")

    assert junction.is_dir()
    assert (junction / "SKILL.md").read_text(encoding="utf-8") != "old\n"
    assert (old_skill / "SKILL.md").read_text(encoding="utf-8") == "old\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows symlink privileges are Windows-only")
def test_install_skills_falls_back_to_copy_without_symlink_privilege(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "bundled-skills"
    skill = source_root / "privilege-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("copied\n", encoding="utf-8")
    target_root = tmp_path / "target-skills"

    def deny_symlink(self: Path, target: Path, target_is_directory: bool = False) -> None:
        error = OSError("symbolic links are not permitted")
        error.winerror = 1314
        raise error

    monkeypatch.setattr(cli, "skills_dir", lambda: source_root)
    monkeypatch.setattr(Path, "symlink_to", deny_symlink)

    cli.install_skills(target_root, "test")

    installed = target_root / "privilege-skill"
    assert installed.is_dir()
    assert not installed.is_symlink()
    assert (installed / "SKILL.md").read_text(encoding="utf-8") == "copied\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows symlink errors are Windows-only")
def test_install_skills_keeps_unrelated_symlink_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "bundled-skills"
    skill = source_root / "broken-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("broken\n", encoding="utf-8")

    def fail_symlink(self: Path, target: Path, target_is_directory: bool = False) -> None:
        error = OSError("access denied")
        error.winerror = 5
        raise error

    monkeypatch.setattr(cli, "skills_dir", lambda: source_root)
    monkeypatch.setattr(Path, "symlink_to", fail_symlink)

    with pytest.raises(OSError, match="access denied"):
        cli.install_skills(tmp_path / "target-skills", "test")


def test_symlink_fallback_reports_copy_mode_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = tmp_path / "bundled-skills"
    for name in ("a-skill", "b-skill"):
        skill = source_root / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")

    monkeypatch.setattr(cli, "skills_dir", lambda: source_root)
    monkeypatch.setattr(cli, "_SYMLINK_FALLBACK", False)

    def deny_symlink(self, target, target_is_directory=False):  # noqa: ANN001
        error = OSError(1314, "A required privilege is not held by the client")
        error.winerror = 1314
        raise error

    monkeypatch.setattr(Path, "symlink_to", deny_symlink)
    monkeypatch.setattr(cli, "_is_symlink_privilege_error", lambda error: True)

    for target in ("agent-one", "agent-two"):
        assert cli.install_skills(tmp_path / target, target, mode="symlink") == 2

    out = capsys.readouterr().out
    assert out.count("symbolic links are unavailable") == 1
    assert cli._SYMLINK_FALLBACK is True
    assert (tmp_path / "agent-two" / "a-skill" / "SKILL.md").is_file()
