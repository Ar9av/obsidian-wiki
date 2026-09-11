"""Unit tests for the portable source key contract (v2).

The contract is defined in ``.skills/llm-wiki/SKILL.md``: a stored key is
vault-relative, home-relative (``~``), or a namespaced pseudo-key — never a bare
machine absolute path. These tests pin the resolution and normalization rules
that back it.
"""
from __future__ import annotations

import json

import pytest

from obsidian_wiki.cache import (
    check_sources,
    compute_hash,
    resolve_key,
    stored_key,
    update_source,
    _load_raw,
    _manifest_path,
    _same_source,
)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    return v


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake $HOME so home-relative behavior is testable without touching real files."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


class TestResolveKey:
    def test_vault_relative_resolves_against_vault(self, vault):
        assert resolve_key("Raw/x.pdf", vault) == vault / "Raw" / "x.pdf"

    def test_home_relative_expands(self, vault, home):
        assert resolve_key("~/.claude/x.jsonl", vault) == home / ".claude" / "x.jsonl"

    def test_env_var_expands(self, vault, monkeypatch):
        monkeypatch.setenv("WIKI_TEST_ROOT", "/srv/docs")
        assert resolve_key("$WIKI_TEST_ROOT/a.md", vault) == vault.__class__("/srv/docs/a.md")

    def test_absolute_used_as_is(self, vault, tmp_path):
        abs_path = tmp_path / "outside" / "a.md"
        assert resolve_key(str(abs_path), vault) == abs_path

    @pytest.mark.parametrize(
        "key",
        ["repo:github.com/o/n", "url:https://example.com/x", "agent:claude/abc", "src:1f2a9c3d"],
    )
    def test_pseudo_keys_are_not_file_paths(self, key, vault):
        assert resolve_key(key, vault) is None

    def test_empty_and_none(self, vault):
        assert resolve_key(None, vault) is None
        assert resolve_key("", vault) is None


class TestStoredKey:
    def test_in_vault_is_vault_relative(self, vault):
        src = vault / "Raw" / "database" / "x.pdf"
        assert stored_key(src, vault) == "Raw/database/x.pdf"

    def test_under_home_is_home_relative(self, vault, home):
        src = home / ".claude" / "projects" / "abc.jsonl"
        assert stored_key(src, vault) == "~/.claude/projects/abc.jsonl"

    def test_vault_wins_when_vault_is_under_home(self, home, monkeypatch):
        # A vault inside $HOME must produce vault-relative, not home-relative.
        v = home / "Knowledge"
        src = v / "Clippings" / "a.md"
        assert stored_key(src, v) == "Clippings/a.md"

    def test_outside_both_is_not_portable(self, vault, tmp_path):
        assert stored_key(tmp_path / "elsewhere" / "a.md", vault) is None


class TestWriteNormalization:
    def test_new_in_vault_source_stored_vault_relative(self, vault):
        src = vault / "_raw" / "articles" / "foo.md"
        src.parent.mkdir(parents=True)
        src.write_text("body", encoding="utf-8")
        update_source(vault, src)
        sources = _load_raw(vault)["sources"]
        assert "_raw/articles/foo.md" in sources
        assert str(src) not in sources

    def test_new_in_vault_source_does_not_warn(self, vault, capsys):
        src = vault / "_raw" / "foo.md"
        src.parent.mkdir(parents=True)
        src.write_text("body", encoding="utf-8")
        update_source(vault, src)
        assert capsys.readouterr().err == ""

    def test_new_home_source_stored_home_relative(self, vault, home):
        src = home / ".claude" / "sessions" / "abc.jsonl"
        src.parent.mkdir(parents=True)
        src.write_text("{}\n", encoding="utf-8")
        update_source(vault, src)
        sources = _load_raw(vault)["sources"]
        assert "~/.claude/sessions/abc.jsonl" in sources

    def test_non_portable_fallback_warns_on_stderr(self, vault, tmp_path, capsys):
        # A source outside both the vault and $HOME has no portable key. The
        # path is still stored for backward compatibility, but never silently.
        src = tmp_path / "mnt" / "data"
        src.mkdir(parents=True)
        (src / "a.md").write_text("body", encoding="utf-8")
        update_source(vault, src)
        err = capsys.readouterr().err
        assert "no portable key" in err
        assert "absolute path" in err
        assert str(src) in _load_raw(vault)["sources"]

    def test_explicit_key_does_not_warn(self, vault, tmp_path, capsys):
        src = tmp_path / "mnt" / "data"
        src.mkdir(parents=True)
        (src / "a.md").write_text("body", encoding="utf-8")
        update_source(vault, src, key="repo:github.com/o/n")
        assert capsys.readouterr().err == ""

    def test_explicit_pseudo_key_used_verbatim(self, vault, tmp_path):
        src = tmp_path / "checkout"  # outside vault and $HOME
        src.mkdir()
        (src / "a.py").write_text("x = 1")
        update_source(vault, src, key="repo:github.com/o/n")
        sources = _load_raw(vault)["sources"]
        assert "repo:github.com/o/n" in sources

    def test_updating_legacy_absolute_entry_keeps_its_key(self, vault):
        # Backward compatibility: an existing absolute key is matched and updated
        # in place, not silently re-keyed.
        src = vault / "_raw" / "foo.md"
        src.parent.mkdir(parents=True)
        src.write_text("body", encoding="utf-8")
        _manifest_path(vault).write_text(
            json.dumps({"sources": {str(src): {"content_hash": "old"}}}), encoding="utf-8"
        )
        update_source(vault, src)
        sources = _load_raw(vault)["sources"]
        assert str(src) in sources

    def test_explicit_key_rekeys_an_existing_path_entry(self, vault, tmp_path):
        # An explicit key is authoritative even when the manifest already tracked
        # the source by (absolute) path.
        src = tmp_path / "checkout"
        src.mkdir()
        (src / "a.py").write_text("x = 1")
        _manifest_path(vault).write_text(
            json.dumps({"sources": {str(src): {"content_hash": "old"}}}), encoding="utf-8"
        )
        update_source(vault, src, key="repo:github.com/o/n")
        sources = _load_raw(vault)["sources"]
        assert "repo:github.com/o/n" in sources
        assert str(src) not in sources


class TestMatchingAcrossForms:
    def test_home_relative_key_matches_absolute_query(self, vault, home):
        stored = "~/.claude/sessions/abc.jsonl"
        query = home / ".claude" / "sessions" / "abc.jsonl"
        assert _same_source(stored, query, vault)

    def test_vault_relative_key_matches_absolute_query(self, vault):
        assert _same_source("_raw/foo.md", vault / "_raw" / "foo.md", vault)

    def test_pseudo_key_only_matches_exactly(self, vault, tmp_path):
        assert _same_source("repo:o/n", tmp_path / "x", vault) is False

    def test_home_relative_key_not_falsely_missing(self, vault, home):
        src = home / ".claude" / "sessions" / "abc.jsonl"
        src.parent.mkdir(parents=True)
        src.write_text("{}\n", encoding="utf-8")
        _manifest_path(vault).write_text(
            json.dumps(
                {
                    "sources": {
                        "~/.claude/sessions/abc.jsonl": {"content_hash": "x", "last_ingested": "2026-01-01"}
                    }
                }
            ),
            encoding="utf-8",
        )
        result = check_sources(vault, [])
        assert result["missing"] == []

    def test_cross_machine_home_key_is_unavailable_not_missing(self, vault, home):
        # The source lives on another machine: its home-relative key resolves to
        # a path that does not exist here. That must not be reported as `missing`
        # (a real loss of a vault-local source) but as `unavailable`.
        _manifest_path(vault).write_text(
            json.dumps(
                {
                    "sources": {
                        "~/.claude/sessions/other-host.jsonl": {"content_hash": "x", "last_ingested": "2026-01-01"}
                    }
                }
            ),
            encoding="utf-8",
        )
        result = check_sources(vault, [])
        assert result["missing"] == []
        assert "~/.claude/sessions/other-host.jsonl" in result["unavailable"]


class TestVaultLocalClassification:
    """A relative key is vault-local only if it names something the vault holds.

    Path shape alone cannot separate a vault-relative key from a legacy key
    relative to some *other* ingest root; the vault's own top-level entries do.
    """

    def _write(self, vault, entries: dict) -> None:
        _manifest_path(vault).write_text(
            json.dumps({"sources": entries}), encoding="utf-8"
        )

    def test_vault_relative_key_in_a_real_dir_is_missing(self, vault):
        (vault / "Raw").mkdir()
        self._write(vault, {"Raw/gone.md": {"content_hash": "x", "last_ingested": "2026-01-01"}})
        result = check_sources(vault, [])
        assert result["missing"] == ["Raw/gone.md"]
        assert result["unavailable"] == []

    def test_legacy_ingest_root_key_is_unavailable_not_missing(self, vault):
        # "-Users-x-github/abc.jsonl" is relative to ~/.claude/projects on the
        # machine that ingested it, not to this vault. It is not a vault loss.
        (vault / "Raw").mkdir()
        self._write(vault, {
            "-Users-x-github/abc.jsonl": {"content_hash": "x", "last_ingested": "2026-01-01"}
        })
        result = check_sources(vault, [])
        assert result["missing"] == []
        assert "-Users-x-github/abc.jsonl" in result["unavailable"]

    def test_out_of_vault_source_parked_in_a_foreign_namespace_is_unavailable(self, vault):
        # Real vaults park an out-of-vault source under a made-up namespace
        # (e.g. external/.hermes/...). The vault has no such top-level entry, so
        # the honest report is unavailable, not a missing vault source.
        (vault / "Raw").mkdir()
        self._write(vault, {
            "external/.hermes/cache/doc.md": {"content_hash": "x", "last_ingested": "2026-01-01"}
        })
        result = check_sources(vault, [])
        assert result["missing"] == []
        assert "external/.hermes/cache/doc.md" in result["unavailable"]

    def test_root_level_relative_key_is_missing(self, vault):
        # A bare filename sits at the vault root: it has no leading component
        # that could be a foreign root, so a deleted one is a real vault loss.
        # (PK3: the top-name check used to sink it into unavailable.)
        (vault / "Raw").mkdir()
        self._write(vault, {"欢迎.md": {"content_hash": "x", "last_ingested": "2026-01-01"}})
        result = check_sources(vault, [])
        assert result["missing"] == ["欢迎.md"]
        assert result["unavailable"] == []

    def test_windows_form_key_is_unavailable_not_missing(self, vault):
        # A drive-absolute path, and a legacy key that uses backslash
        # separators, are keys written for another OS. Neither resolves here, and
        # neither may be mistaken for a vault-root file (PK4).
        (vault / "Raw").mkdir()
        self._write(vault, {
            r"C:\Users\me\wiki\Raw\a.md": {"content_hash": "x", "last_ingested": "2026-01-01"},
            "C:/Users/me/wiki/Raw/b.md": {"content_hash": "x", "last_ingested": "2026-01-01"},
            r"-Users-x\abc.jsonl": {"content_hash": "x", "last_ingested": "2026-01-01"},
        })
        result = check_sources(vault, [])
        assert result["missing"] == []
        assert sorted(result["unavailable"]) == sorted([
            r"-Users-x\abc.jsonl",
            r"C:\Users\me\wiki\Raw\a.md",
            "C:/Users/me/wiki/Raw/b.md",
        ])

    def test_existing_vault_relative_key_is_still_matched_as_unchanged(self, vault):
        # The topology check must not stop a present in-vault source matching.
        src = vault / "Raw" / "here.md"
        src.parent.mkdir()
        src.write_text("body", encoding="utf-8")
        self._write(vault, {
            "Raw/here.md": {
                "content_hash": compute_hash(src),
                "last_ingested": "2026-01-01",
            }
        })
        result = check_sources(vault, [src])
        assert result["unchanged"] == [str(src)]
        assert result["missing"] == []
        assert result["unavailable"] == []
