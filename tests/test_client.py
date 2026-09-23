"""Tests for the Python client (`obsidian_wiki.Memory`).

The client exists so a vault can be used as agent memory by importing it,
rather than by shelling out to the CLI on every turn. These tests pin the
ergonomics that makes true: a short constructor, add/search that round-trip,
and per-user scoping that actually isolates.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from obsidian_wiki import Memory
from obsidian_wiki import memory as mem
from obsidian_wiki.client import MemoryError_, _title_from


@pytest.fixture()
def memory(tmp_path: Path) -> Memory:
    return Memory(str(tmp_path / "brain"), create=True)


# --------------------------------------------------------------------------
# construction
# --------------------------------------------------------------------------


def test_create_scaffolds_a_usable_vault(tmp_path: Path) -> None:
    vault = tmp_path / "brain"
    client = Memory(str(vault), create=True)
    assert vault.is_dir()
    assert client.status()["migrated"] is True  # born adopted, so sync works


def test_a_missing_vault_says_how_to_fix_it(tmp_path: Path) -> None:
    with pytest.raises(MemoryError_) as excinfo:
        Memory(str(tmp_path / "nope"))
    assert "create=True" in str(excinfo.value)


def test_no_vault_configured_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(MemoryError_) as excinfo:
        Memory()
    assert "obsidian-wiki setup" in str(excinfo.value)


def test_env_var_configures_the_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "brain"
    Memory(str(vault), create=True)
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    assert Memory().vault == vault.resolve()


def test_a_dot_env_up_the_tree_configures_the_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "brain"
    Memory(str(vault), create=True)
    project = tmp_path / "project" / "nested"
    project.mkdir(parents=True)
    (tmp_path / "project" / ".env").write_text(f"OBSIDIAN_VAULT_PATH={vault}\n", encoding="utf-8")
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.chdir(project)
    assert Memory().vault == vault.resolve()


# --------------------------------------------------------------------------
# add / search — the round trip that has to work
# --------------------------------------------------------------------------


def test_add_then_search_finds_it(memory: Memory) -> None:
    """The contract a memory layer lives or dies on."""
    added = memory.add("Postgres was chosen over MySQL for partial index support.")
    hits = memory.search("postgres")
    assert hits, "a page added a moment ago must be findable"
    assert hits[0]["path"] == added["path"]
    assert hits[0]["path"].endswith(".md")


def test_search_returns_a_fetchable_path(memory: Memory) -> None:
    """graphrag calls the key `page`; reading it as `path` returned nothing."""
    memory.add("The parser uses recursive descent.", title="Parser design")
    hit = memory.search("parser")[0]
    assert memory.get(hit["path"]).startswith("---")


def test_add_accepts_openai_shaped_messages(memory: Memory) -> None:
    result = memory.add(
        [{"role": "user", "content": "we use pytest"},
         {"role": "assistant", "content": "noted, with fixtures"}],
        title="Testing setup",
    )
    body = memory.get(result["path"])
    assert "**user:** we use pytest" in body
    assert "**assistant:** noted, with fixtures" in body


def test_add_derives_a_short_filename_safe_title(memory: Memory) -> None:
    result = memory.add(
        "Postgres was chosen over MySQL because partial indexes matter here, "
        "and the predicate cannot be expressed otherwise."
    )
    assert len(Path(result["path"]).stem) <= 60
    assert "..." not in result["path"]


def test_an_explicit_title_wins(memory: Memory) -> None:
    result = memory.add("Some long rambling body text about databases.", title="DB choice")
    assert result["path"] == "references/db-choice.md"
    assert result["title"] == "DB choice"


def test_rewriting_a_title_updates_and_preserves_created(memory: Memory) -> None:
    first = memory.add("Version one.", title="Note")
    memory.add("Version two.", title="Note")
    body = memory.get(first["path"])
    assert "Version two." in body and "Version one." not in body
    assert f"created: {first['created']}" in body


def test_add_refuses_empty_content(memory: Memory) -> None:
    for empty in ("", "   ", []):
        with pytest.raises(MemoryError_):
            memory.add(empty)


def test_add_reconciles_the_index(memory: Memory) -> None:
    memory.add("A fact.", title="Fact one")
    assert "fact-one" in (memory.vault / "index.md").read_text(encoding="utf-8")


def test_categories_are_honoured_and_validated(memory: Memory) -> None:
    assert memory.add("x", title="C", category="concepts")["path"] == "concepts/c.md"
    with pytest.raises(mem.MemoryError_):
        memory.add("x", title="C", category="../escape")


def test_get_refuses_to_escape_the_vault(memory: Memory) -> None:
    with pytest.raises(MemoryError_) as excinfo:
        memory.get("../../etc/passwd")
    assert "escapes the vault" in str(excinfo.value)


def test_context_returns_a_bounded_pack(memory: Memory) -> None:
    memory.add("Postgres supports partial indexes.", title="Postgres")
    pack = memory.context("postgres", budget=2000)
    assert "Postgres" in pack


# --------------------------------------------------------------------------
# person-shaped memory
# --------------------------------------------------------------------------


def test_remember_and_forget(memory: Memory) -> None:
    fact = memory.remember("stack", "Python, FastAPI", confidence=0.9)
    assert fact["value"] == "Python, FastAPI"
    assert memory.profile()[0]["key"] == "stack"
    assert memory.forget("stack") is True
    assert memory.profile() == []


def test_remember_replaces_rather_than_duplicating(memory: Memory) -> None:
    memory.remember("editor", "vim")
    memory.remember("editor", "neovim", confidence=0.95)
    assert [f["value"] for f in memory.profile()] == ["neovim"]


def test_todo_lifecycle(memory: Memory) -> None:
    todo = memory.todo("Ship the parser", origin="projects/p.md")
    assert memory.todos()[0]["id"] == todo["id"]
    memory.close_todo(todo["id"])
    assert memory.todos() == []
    assert memory.todos(include_closed=True)[0]["status"] == "done"


def test_recap_gathers_everything_a_new_session_needs(memory: Memory) -> None:
    memory.remember("stack", "Python")
    memory.todo("Ship the parser")
    memory.add("A page.", title="Page")
    recap = memory.recap()
    assert "stack" in recap and "Ship the parser" in recap and "MEMORY_ADD" in recap


# --------------------------------------------------------------------------
# scoping — the multi-tenancy the vector stores put in every call
# --------------------------------------------------------------------------


def test_user_id_isolates_profiles(tmp_path: Path) -> None:
    owner = Memory(str(tmp_path / "brain"), create=True)
    alice = Memory(str(tmp_path / "brain"), user_id="alice")
    bob = Memory(str(tmp_path / "brain"), user_id="bob")

    owner.remember("stack", "Python")
    alice.remember("stack", "Go")
    bob.remember("stack", "Rust")

    assert owner.profile()[0]["value"] == "Python"
    assert alice.profile()[0]["value"] == "Go"
    assert bob.profile()[0]["value"] == "Rust"
    assert sorted(owner.scopes()) == ["alice", "bob"]


def test_user_id_isolates_todos_and_recap(tmp_path: Path) -> None:
    alice = Memory(str(tmp_path / "brain"), create=True, user_id="alice")
    bob = Memory(str(tmp_path / "brain"), user_id="bob")
    alice.todo("Alice's thread")
    bob.todo("Bob's thread")
    assert [t["text"] for t in alice.todos()] == ["Alice's thread"]
    assert "Bob's thread" not in alice.recap()
    assert "Alice's thread" not in bob.recap()


def test_pages_are_shared_across_scopes(tmp_path: Path) -> None:
    """Knowledge is a shared brain; only memory *about a person* is scoped."""
    alice = Memory(str(tmp_path / "brain"), create=True, user_id="alice")
    bob = Memory(str(tmp_path / "brain"), user_id="bob")
    alice.add("Partial indexes are a Postgres feature.", title="Partial indexes")
    assert bob.search("partial indexes")[0]["title"] == "Partial indexes"


def test_a_per_call_user_id_overrides_the_default(tmp_path: Path) -> None:
    client = Memory(str(tmp_path / "brain"), create=True, user_id="alice")
    client.remember("stack", "Go")
    client.remember("stack", "Rust", user_id="bob")
    assert client.profile()[0]["value"] == "Go"
    assert client.profile(user_id="bob")[0]["value"] == "Rust"


def test_a_scope_can_never_escape_the_meta_directory(tmp_path: Path) -> None:
    """A user_id arrives from a request in a server deployment."""
    for hostile in ("../../etc/passwd", "a/b", "..", "x" * 100):
        with pytest.raises(mem.MemoryError_) as excinfo:
            Memory(str(tmp_path / "brain"), create=True, user_id=hostile)
        assert excinfo.value.code == "bad_scope"


def test_scoped_files_are_readable_markdown(tmp_path: Path) -> None:
    """The differentiator: a human opens this in Obsidian and edits it."""
    alice = Memory(str(tmp_path / "brain"), create=True, user_id="alice")
    alice.remember("stack", "Go")
    path = tmp_path / "brain" / "_meta" / "profile.alice.md"
    assert path.is_file()
    assert "| stack | Go |" in path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# sync
# --------------------------------------------------------------------------


def test_sync_degrades_on_an_unmigrated_vault(tmp_path: Path) -> None:
    vault = tmp_path / "brain"
    client = Memory(str(vault), create=True)
    (vault / "index.md").write_text("# Hand written\n", encoding="utf-8")
    (vault / mem.ADOPTED_REL).unlink()
    result = client.sync("INGEST", source="x.md")
    assert result["log_line"], "the append-only log write must still land"
    assert "migrate" in result["skipped"]
    assert (vault / "index.md").read_text(encoding="utf-8") == "# Hand written\n"


def test_title_helper_stays_short_and_marks_truncation() -> None:
    assert _title_from("Short one.") == "Short one"
    long = _title_from("one two three four five six seven eight nine ten eleven")
    assert long.endswith("...") and len(long) <= 51
