"""Contract tests for destructive-skill pre-write snapshots."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATHS = (
    ".skills/cross-linker/SKILL.md",
    ".skills/wiki-dedup/SKILL.md",
    ".skills/wiki-lint/SKILL.md",
)


def _skill_texts() -> list[tuple[str, str]]:
    return [
        (path, (ROOT / path).read_text(encoding="utf-8"))
        for path in SKILL_PATHS
    ]


def test_snapshot_only_runs_for_standalone_vault_repositories() -> None:
    for path, text in _skill_texts():
        assert "rev-parse --show-toplevel" in text, path
        assert '"$VAULT_GIT_ROOT" = "$VAULT_REAL_PATH"' in text, path


def test_snapshot_distinguishes_clean_repository_from_commit_failure() -> None:
    for path, text in _skill_texts():
        assert "diff --quiet" in text, path
        assert "diff --cached --quiet" in text, path
        assert "ls-files --others --exclude-standard" in text, path
        assert 'if ! git -C "$OBSIDIAN_VAULT_PATH" add -A; then' in text, path
        assert "abort the skill without writing any vault files" in text, path


def test_snapshot_records_an_actionable_rollback_point() -> None:
    for path, text in _skill_texts():
        assert 'SNAPSHOT_SHA=$(git -C "$OBSIDIAN_VAULT_PATH" rev-parse HEAD)' in text, path
        assert 'reset --hard "$SNAPSHOT_SHA"' in text, path
        assert "clean -fd" in text, path
