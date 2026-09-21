"""Tests for the shared memory writer (`obsidian_wiki.memory`).

These cover the guarantees the prose instructions could not make: that a
parallel writer cannot drop an update, that the hot cache honours its word cap,
that reconciling the index does not eat a human's own section, and that the
profile and todo tables round-trip content containing table syntax.
"""

from __future__ import annotations

import concurrent.futures
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from obsidian_wiki import memory as mem


def _page(vault: Path, rel: str, **fields: str) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "\n".join(f"{key}: {value}" for key, value in fields.items())
    path.write_text(f"---\n{header}\n---\n\n# {fields.get('title', rel)}\n\nBody.\n", encoding="utf-8")
    return path


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    for name in ("concepts", "entities", "projects", "_meta"):
        (tmp_path / name).mkdir(parents=True)
    _page(tmp_path, "concepts/attention.md", title="Attention", summary="Core transformer block", tags="[ml, nlp]", updated="2026-09-01")
    _page(tmp_path, "entities/karpathy.md", title="Andrej Karpathy", summary="AI researcher", tags="[person]", updated="2026-09-10")
    return tmp_path


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "memory", *args],
        capture_output=True, text=True,
    )


# --------------------------------------------------------------------------
# log.md
# --------------------------------------------------------------------------


def test_log_line_matches_the_documented_format(vault: Path) -> None:
    line = mem.append_log(vault, "INGEST", {"source": "papers/attention.pdf", "pages_created": 3})
    assert line.startswith("- [")
    entry = mem.parse_log_line(line)
    assert entry is not None
    assert entry.verb == "INGEST"
    assert entry.fields == {"source": "papers/attention.pdf", "pages_created": "3"}


def test_log_quotes_values_containing_spaces(vault: Path) -> None:
    line = mem.append_log(vault, "QUERY", {"query": "how do transformers work", "result_pages": 4})
    assert 'query="how do transformers work"' in line
    assert mem.parse_log_line(line).fields["query"] == "how do transformers work"


def test_log_rejects_a_lowercase_verb(vault: Path) -> None:
    with pytest.raises(mem.MemoryError_) as excinfo:
        mem.append_log(vault, "ingest something")
    assert excinfo.value.code == "bad_verb"


def test_log_creates_the_file_and_never_rewrites_history(vault: Path) -> None:
    first = mem.append_log(vault, "INIT", {"pages": 2})
    mem.append_log(vault, "LINT", {"issues_found": 0})
    text = (vault / "log.md").read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: Wiki Log\n---")
    assert first in text
    assert len(mem.read_log(vault)) == 2


def test_log_filters_by_verb_and_limit(vault: Path) -> None:
    for index in range(5):
        mem.append_log(vault, "INGEST", {"n": index})
    mem.append_log(vault, "LINT", {"issues_found": 1})
    assert len(mem.read_log(vault, verbs=["INGEST"])) == 5
    assert len(mem.read_log(vault, limit=2)) == 2


def test_parallel_writers_do_not_drop_a_log_line(vault: Path) -> None:
    """The regression the lock exists for: wholesale rewrites lost updates."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda n: mem.append_log(vault, "CAPTURE", {"n": n}), range(60)))
    entries = mem.read_log(vault, verbs=["CAPTURE"])
    assert len(entries) == 60
    assert {entry.fields["n"] for entry in entries} == {str(n) for n in range(60)}


# --------------------------------------------------------------------------
# index.md
# --------------------------------------------------------------------------


def test_index_lists_every_page_under_its_category(vault: Path) -> None:
    result = mem.rebuild_index(vault)
    text = (vault / "index.md").read_text(encoding="utf-8")
    assert result.total == 2
    assert "## Concepts" in text and "## Entities" in text
    assert "[[concepts/attention]]" in text
    assert set(result.added) == {"concepts/attention", "entities/karpathy"}


def test_index_keeps_the_space_after_the_opening_paren(vault: Path) -> None:
    """The documented format rule — `(#tag)` breaks Obsidian tag parsing."""
    mem.rebuild_index(vault)
    text = (vault / "index.md").read_text(encoding="utf-8")
    assert "( #ml #nlp)" in text
    assert "(#ml" not in text


def test_index_honours_the_markdown_link_format(vault: Path) -> None:
    mem.rebuild_index(vault, link_format="markdown")
    text = (vault / "index.md").read_text(encoding="utf-8")
    assert "[Attention](concepts/attention.md)" in text
    assert "[[" not in text


def test_index_drops_a_deleted_page_but_keeps_a_human_section(vault: Path) -> None:
    mem.rebuild_index(vault)
    index = vault / "index.md"
    index.write_text(index.read_text(encoding="utf-8") + "\n## Reading Queue\n\n- A book I mean to read\n", encoding="utf-8")
    (vault / "concepts/attention.md").unlink()

    result = mem.rebuild_index(vault)
    text = index.read_text(encoding="utf-8")
    assert result.removed == ("concepts/attention",)
    assert "concepts/attention" not in text
    assert "A book I mean to read" in text


def test_index_drops_a_stale_section_when_its_category_empties(vault: Path) -> None:
    """Deriving categories from pages alone stranded the emptied section."""
    mem.rebuild_index(vault)
    (vault / "concepts/attention.md").unlink()
    mem.rebuild_index(vault)
    text = (vault / "index.md").read_text(encoding="utf-8")
    assert "## Concepts" not in text
    assert "## Entities" in text


def test_index_check_mode_reports_drift_without_writing(vault: Path) -> None:
    mem.rebuild_index(vault)
    before = (vault / "index.md").read_text(encoding="utf-8")
    _page(vault, "concepts/rag.md", title="RAG", summary="Retrieval augmented generation")
    result = mem.rebuild_index(vault, write=False)
    assert result.changed is True
    assert result.added == ("concepts/rag",)
    assert (vault / "index.md").read_text(encoding="utf-8") == before


def test_index_ignores_staging_and_memory_files(vault: Path) -> None:
    _page(vault, "_raw/2026-09-21-scratch.md", title="Scratch")
    _page(vault, "_staging/concepts/pending.md", title="Pending")
    _page(vault, "_meta/taxonomy.md", title="Taxonomy")
    result = mem.rebuild_index(vault)
    text = (vault / "index.md").read_text(encoding="utf-8")
    assert result.total == 2
    for excluded in ("scratch", "pending", "taxonomy"):
        assert excluded not in text


def test_index_is_idempotent(vault: Path) -> None:
    mem.rebuild_index(vault)
    first = (vault / "index.md").read_text(encoding="utf-8")
    second = mem.rebuild_index(vault)
    assert second.changed is False
    assert second.text == first


# --------------------------------------------------------------------------
# hot.md
# --------------------------------------------------------------------------


def test_hot_has_the_four_documented_sections(vault: Path) -> None:
    mem.rebuild_hot(vault)
    text = (vault / "hot.md").read_text(encoding="utf-8")
    for heading in ("Recent Activity", "Active Threads", "Key Takeaways", "Flagged Contradictions"):
        assert f"## {heading}" in text
    assert "generated_by: obsidian-wiki memory hot" in text


def test_hot_preserves_key_takeaways_across_a_rebuild(vault: Path) -> None:
    """The one LLM-owned slot: mechanical rebuilds must not erase it."""
    mem.rebuild_hot(vault, takeaways="Retrieval is lexical only; precision is the weak metric.")
    mem.append_log(vault, "INGEST", {"source": "x"})
    mem.rebuild_hot(vault)
    assert "Retrieval is lexical only" in (vault / "hot.md").read_text(encoding="utf-8")


def test_hot_replaces_takeaways_when_given_new_text(vault: Path) -> None:
    mem.rebuild_hot(vault, takeaways="Old conclusion.")
    mem.rebuild_hot(vault, takeaways="New conclusion.")
    text = (vault / "hot.md").read_text(encoding="utf-8")
    assert "New conclusion." in text and "Old conclusion." not in text


def test_hot_enforces_the_word_cap(vault: Path) -> None:
    for index in range(50):
        mem.append_log(vault, "INGEST", {"source": f"file-{index}.pdf", "note": "a fairly long note value"})
    for index in range(20):
        mem.add_todo(vault, f"Thread number {index} with a reasonably long description")
    result = mem.rebuild_hot(vault, takeaways=" ".join(["takeaway"] * 400), max_words=200, activity_limit=40)
    assert result.trimmed is True
    assert result.words <= 200
    assert mem.content_words((vault / "hot.md").read_text(encoding="utf-8")) <= 200


def test_hot_word_cap_excludes_frontmatter_and_boilerplate(vault: Path) -> None:
    """Counting the header against the cap put the floor within a few words of it."""
    text = (vault / "hot.md")
    result = mem.rebuild_hot(vault)
    raw = text.read_text(encoding="utf-8")
    assert result.words == mem.content_words(raw)
    assert result.words < mem.word_count(raw)


def test_hot_respects_the_env_override(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSIDIAN_HOT_MAX_WORDS", "80")
    assert mem.hot_max_words() == 80
    for index in range(30):
        mem.append_log(vault, "INGEST", {"source": f"file-{index}.pdf"})
    assert mem.rebuild_hot(vault, activity_limit=30).words <= 80


def test_hot_falls_back_when_the_env_override_is_junk(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSIDIAN_HOT_MAX_WORDS", "not-a-number")
    assert mem.hot_max_words() == mem.DEFAULT_HOT_MAX_WORDS


def test_hot_lists_open_threads_and_omits_closed_ones(vault: Path) -> None:
    open_todo = mem.add_todo(vault, "Wire the systemd timer")
    closed = mem.add_todo(vault, "Already finished")
    mem.set_todo_status(vault, closed.id, "done")
    mem.rebuild_hot(vault)
    text = (vault / "hot.md").read_text(encoding="utf-8")
    assert open_todo.text in text
    assert "Already finished" not in text


def test_hot_flags_disputed_pages_and_contradiction_edges(vault: Path) -> None:
    _page(vault, "concepts/scaling.md", title="Scaling", lifecycle="disputed", updated="2026-09-11")
    (vault / "concepts/rebuttal.md").write_text(
        "---\ntitle: Rebuttal\nupdated: 2026-09-12\nrelationships:\n"
        '  - target: "[[concepts/scaling]]"\n    type: contradicts\n---\n\nBody.\n',
        encoding="utf-8",
    )
    mem.rebuild_hot(vault)
    text = (vault / "hot.md").read_text(encoding="utf-8")
    assert "marked disputed" in text
    assert "contradicts [[concepts/scaling]]" in text


# --------------------------------------------------------------------------
# profile
# --------------------------------------------------------------------------


def test_profile_round_trips_a_fact(vault: Path) -> None:
    mem.set_fact(vault, "stack", "Python, FastAPI", confidence=0.85, source="session:abc")
    facts = mem.load_profile(vault)
    assert len(facts) == 1
    assert facts[0].key == "stack"
    assert facts[0].value == "Python, FastAPI"
    assert facts[0].confidence == pytest.approx(0.85)
    assert facts[0].source == "session:abc"


def test_profile_round_trips_a_value_containing_a_pipe(vault: Path) -> None:
    """A raw `|` would tear the markdown row into extra cells."""
    mem.set_fact(vault, "shell", "bash | zsh")
    assert mem.load_profile(vault)[0].value == "bash | zsh"


def test_profile_set_replaces_rather_than_duplicates(vault: Path) -> None:
    mem.set_fact(vault, "editor", "vim", confidence=0.5)
    mem.set_fact(vault, "EDITOR", "neovim", confidence=0.9)
    facts = mem.load_profile(vault)
    assert len(facts) == 1
    assert facts[0].value == "neovim"


def test_profile_rejects_confidence_outside_the_unit_interval(vault: Path) -> None:
    for bad in (-0.1, 1.5):
        with pytest.raises(mem.MemoryError_) as excinfo:
            mem.set_fact(vault, "k", "v", confidence=bad)
        assert excinfo.value.code == "bad_confidence"


def test_profile_forget_reports_whether_it_removed_anything(vault: Path) -> None:
    mem.set_fact(vault, "timezone", "Asia/Kolkata")
    assert mem.forget_fact(vault, "timezone") is True
    assert mem.forget_fact(vault, "timezone") is False
    assert mem.load_profile(vault) == []


def test_profile_survives_a_hand_edit_in_obsidian(vault: Path) -> None:
    mem.set_fact(vault, "stack", "Python")
    path = vault / mem.PROFILE_REL
    path.write_text(
        path.read_text(encoding="utf-8") + "| timezone | Asia/Kolkata | 0.90 | manual | 2026-09-21 |\n",
        encoding="utf-8",
    )
    assert {fact.key for fact in mem.load_profile(vault)} == {"stack", "timezone"}


# --------------------------------------------------------------------------
# todos
# --------------------------------------------------------------------------


def test_todo_add_assigns_sequential_ids(vault: Path) -> None:
    assert mem.add_todo(vault, "First").id == "t1"
    assert mem.add_todo(vault, "Second").id == "t2"


def test_todo_add_is_idempotent_for_an_open_thread(vault: Path) -> None:
    first = mem.add_todo(vault, "Wire the systemd timer")
    again = mem.add_todo(vault, "wire the SYSTEMD timer")
    assert first.id == again.id
    assert len(mem.load_todos(vault)) == 1


def test_todo_status_transitions_and_prune(vault: Path) -> None:
    keep = mem.add_todo(vault, "Still open")
    done = mem.add_todo(vault, "Finished")
    dropped = mem.add_todo(vault, "Abandoned")
    mem.set_todo_status(vault, done.id, "done")
    mem.set_todo_status(vault, dropped.id, "dropped")
    assert mem.prune_todos(vault) == 2
    remaining = mem.load_todos(vault)
    assert [todo.id for todo in remaining] == [keep.id]


def test_todo_rejects_an_unknown_id_and_status(vault: Path) -> None:
    todo = mem.add_todo(vault, "Something")
    with pytest.raises(mem.MemoryError_) as unknown:
        mem.set_todo_status(vault, "t99", "done")
    assert unknown.value.code == "no_such_todo"
    with pytest.raises(mem.MemoryError_) as bad:
        mem.set_todo_status(vault, todo.id, "maybe")
    assert bad.value.code == "bad_status"


def test_todo_staleness_is_reported_not_enforced(vault: Path) -> None:
    mem.add_todo(vault, "Old thread")
    path = vault / mem.TODOS_REL
    old = (datetime.now(timezone.utc) - timedelta(days=45)).date().isoformat()
    path.write_text(path.read_text(encoding="utf-8").replace(mem.today(), old), encoding="utf-8")
    todo = mem.load_todos(vault)[0]
    assert todo.is_stale() is True
    assert todo.status == "open"  # still open; staleness is a signal, not a close


def test_closed_todos_are_never_stale(vault: Path) -> None:
    todo = mem.add_todo(vault, "Done long ago")
    mem.set_todo_status(vault, todo.id, "done")
    assert mem.load_todos(vault)[0].is_stale(days=0) is False


# --------------------------------------------------------------------------
# recap + status
# --------------------------------------------------------------------------


def test_recap_gathers_profile_threads_and_activity(vault: Path) -> None:
    mem.set_fact(vault, "stack", "Python")
    mem.add_todo(vault, "Persist the retrieval index")
    mem.append_log(vault, "INGEST", {"source": "papers/rag.pdf"})
    recap = mem.build_recap(vault)
    assert "**stack**: Python" in recap
    assert "Persist the retrieval index" in recap
    assert "INGEST" in recap


def test_recap_is_honest_about_an_empty_vault(vault: Path) -> None:
    assert "No vault memory recorded yet" in mem.build_recap(vault)


def test_recap_filters_low_confidence_facts(vault: Path) -> None:
    mem.set_fact(vault, "guess", "maybe Postgres", confidence=0.2)
    mem.set_fact(vault, "certain", "Python", confidence=0.95)
    recap = mem.build_recap(vault, min_confidence=0.5)
    assert "certain" in recap and "guess" not in recap


def test_recap_respects_its_word_budget(vault: Path) -> None:
    for index in range(60):
        mem.set_fact(vault, f"fact-{index}", f"a reasonably long value number {index}")
    assert mem.word_count(mem.build_recap(vault, max_words=100)) <= 101  # +1 for the ellipsis


def test_status_reports_index_drift_and_hot_budget(vault: Path) -> None:
    status = mem.memory_status(vault)
    assert status["pages"] == 2
    assert status["index_drift"]["stale"] is True
    assert status["hot"]["generated"] is False

    mem.rebuild_index(vault)
    mem.rebuild_hot(vault)
    status = mem.memory_status(vault)
    assert status["index_drift"]["stale"] is False
    assert status["hot"]["generated"] is True
    assert status["hot"]["over_budget"] is False


def test_operations_refuse_a_missing_vault(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    for call in (
        lambda: mem.append_log(missing, "INGEST"),
        lambda: mem.rebuild_index(missing),
        lambda: mem.rebuild_hot(missing),
        lambda: mem.build_recap(missing),
    ):
        with pytest.raises(mem.MemoryError_) as excinfo:
            call()
        assert excinfo.value.code == "vault_not_found"


# --------------------------------------------------------------------------
# CLI surface
# --------------------------------------------------------------------------


def test_cli_status_and_sync_round_trip(vault: Path) -> None:
    stale = _cli("status", "--vault", str(vault), "--json")
    assert stale.returncode == 0
    assert '"stale": true' in stale.stdout

    synced = _cli("sync", "--verb", "INGEST", "--field", "source=papers/rag.pdf", "--vault", str(vault))
    assert synced.returncode == 0
    assert "INGEST" in synced.stdout

    after = _cli("status", "--vault", str(vault), "--json")
    assert '"stale": false' in after.stdout
    assert (vault / "index.md").is_file()
    assert (vault / "hot.md").is_file()


def test_cli_index_check_exits_two_on_drift(vault: Path) -> None:
    assert _cli("index", "--vault", str(vault)).returncode == 0
    assert _cli("index", "--check", "--vault", str(vault)).returncode == 0
    _page(vault, "concepts/rag.md", title="RAG", summary="Retrieval augmented generation")
    drifted = _cli("index", "--check", "--vault", str(vault))
    assert drifted.returncode == 2
    assert "concepts/rag" in drifted.stdout


def test_cli_rejects_a_malformed_field(vault: Path) -> None:
    result = _cli("log", "INGEST", "--field", "no-equals-sign", "--vault", str(vault))
    assert result.returncode == 1
    assert "key=value" in result.stderr


def test_cli_profile_and_todo_lifecycle(vault: Path) -> None:
    assert _cli("profile", "set", "stack", "Python, FastAPI", "--confidence", "0.8", "--vault", str(vault)).returncode == 0
    listed = _cli("profile", "list", "--vault", str(vault))
    assert "stack: Python, FastAPI" in listed.stdout

    added = _cli("todo", "add", "Persist the retrieval index", "--vault", str(vault))
    assert added.returncode == 0
    assert _cli("todo", "done", "t1", "--vault", str(vault)).returncode == 0
    assert "no todos recorded" in _cli("todo", "list", "--vault", str(vault)).stdout
    assert "done" in _cli("todo", "list", "--all", "--vault", str(vault)).stdout


def test_cli_forget_exits_one_when_nothing_was_removed(vault: Path) -> None:
    assert _cli("profile", "forget", "absent", "--vault", str(vault)).returncode == 1


def test_cli_takeaways_can_be_piped_in(vault: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "memory", "hot", "--takeaways", "-", "--vault", str(vault)],
        input="Retrieval is lexical only.", capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "Retrieval is lexical only." in (vault / "hot.md").read_text(encoding="utf-8")


def test_cli_recap_prints_the_injectable_block(vault: Path) -> None:
    _cli("profile", "set", "stack", "Python", "--vault", str(vault))
    recap = _cli("recap", "--vault", str(vault))
    assert recap.returncode == 0
    assert recap.stdout.startswith("# Vault memory")
