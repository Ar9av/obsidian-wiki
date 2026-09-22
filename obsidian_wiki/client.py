"""A small Python client, so a vault can be used as agent memory by importing it.

Everything here already existed as a CLI and an MCP server. Neither is usable
from inside an agent framework: you cannot ``pip install`` a memory layer and
then shell out to it on every turn. This is the missing third face.

    from obsidian_wiki import Memory

    memory = Memory("~/brain")
    memory.remember("stack", "Python, FastAPI", confidence=0.9)
    memory.add("Postgres was chosen over MySQL for partial index support.")
    memory.search("database choice")
    memory.recap()

How this differs from the vector-store memory layers, deliberately
--------------------------------------------------------------------
``mem0`` and friends take raw conversation messages and run an LLM *inside*
``add()`` to decide what is worth keeping. That is the right call when memory
is a black box. It is the wrong call here: this package has no LLM, no API key
and no dependencies, and the whole point of the vault is that a human can read
and edit what it stored.

So the routing decision stays with the caller, and is made explicit rather than
guessed:

* :meth:`Memory.add` stores knowledge as a page — a thing that is true.
* :meth:`Memory.remember` stores a durable fact about a person.
* :meth:`Memory.todo` stores a thread to pick up next time.

Three verbs instead of one magic one. The caller already has an LLM; it does
not need a second one hidden in the storage layer.

Scoping
-------
``user_id`` namespaces the person-shaped memory — the profile and the todo
list — so one deployment can serve several people. Pages stay shared: a vault
is a shared brain, and only what it remembers *about someone* is per-someone.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Union

from obsidian_wiki import memory as _mem

DEFAULT_CATEGORY = "references"
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s")

Content = Union[str, Sequence[dict]]


class MemoryError_(RuntimeError):
    """Re-exported so callers can catch one exception type from this module."""


def _slug(text: str, *, limit: int = 60) -> str:
    slug = _SLUG_RE.sub("-", text.strip().casefold()).strip("-")
    return (slug[:limit].rstrip("-") or "note")


def _title_from(text: str, *, limit: int = 48, words: int = 8) -> str:
    """A short title from the opening sentence. Deterministic on purpose.

    Generating a title is where it would be easy to reach for an LLM. Doing so
    would make this package depend on a model and a key, which is exactly what
    it does not do. So: the first sentence, capped hard in both words and
    characters, because it becomes a filename.

    Pass ``title=`` to :meth:`Memory.add` when you want a better one — the
    caller has an LLM and should use it.
    """
    first = _SENTENCE_END_RE.split(text.strip(), 1)[0].strip() or text.strip()
    tokens = first.split()
    clipped = " ".join(tokens[:words])
    if len(clipped) > limit:
        clipped = clipped[:limit].rsplit(" ", 1)[0]
    truncated = len(tokens) > words or clipped != " ".join(tokens)
    return clipped.rstrip(",;:.") + ("..." if truncated else "")


def _summary_from(text: str, *, limit: int = 180) -> str:
    """The opening sentence, for the `summary:` field the index reads."""
    first = " ".join(_SENTENCE_END_RE.split(text.strip(), 1)[0].split())
    return first if len(first) <= limit else first[:limit].rsplit(" ", 1)[0] + "..."


def _render_messages(messages: Sequence[dict]) -> str:
    """OpenAI-shaped messages into readable prose.

    Accepted because it is the universal input shape; rendered verbatim rather
    than summarised, because summarising is the caller's job.
    """
    lines = []
    for message in messages:
        role = str(message.get("role", "")).strip() or "message"
        body = str(message.get("content", "")).strip()
        if body:
            lines.append(f"**{role}:** {body}")
    return "\n\n".join(lines)


def resolve_vault(explicit: Optional[str] = None) -> Path:
    """Explicit path, then ``OBSIDIAN_VAULT_PATH``, then the Config Resolution
    Protocol: a ``.env`` up the tree, then the global config."""
    if explicit:
        return Path(explicit).expanduser().resolve()

    from_env = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
    if from_env:
        return Path(from_env).expanduser().resolve()

    def read(path: Path) -> str:
        if not path.is_file():
            return ""
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("OBSIDIAN_VAULT_PATH="):
                return line.split("=", 1)[1].strip().strip("'\"")
        return ""

    current, home = Path.cwd().resolve(), Path.home().resolve()
    while True:
        found = read(current / ".env")
        if found:
            return Path(found).expanduser().resolve()
        if current == home or current.parent == current:
            break
        current = current.parent

    config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "obsidian-wiki"
    legacy = Path.home() / ".obsidian-wiki"
    if legacy.is_dir() and not config_dir.exists():
        config_dir = legacy
    found = read(config_dir / "config")
    if found:
        return Path(found).expanduser().resolve()

    raise MemoryError_(
        "No vault configured. Pass Memory('/path/to/vault'), set "
        "OBSIDIAN_VAULT_PATH, or run `obsidian-wiki setup`."
    )


class Memory:
    """A vault, used as agent memory.

    :param vault: vault path. Omit to use the Config Resolution Protocol.
    :param user_id: default scope for profile and todo operations.
    :param create: scaffold the vault if it does not exist yet.
    """

    def __init__(
        self,
        vault: Optional[str] = None,
        *,
        user_id: str = "",
        link_format: str = "wikilink",
        create: bool = False,
    ) -> None:
        self.vault = resolve_vault(vault)
        self.user_id = _mem.check_scope(user_id)
        self.link_format = link_format
        if create and not self.vault.is_dir():
            from obsidian_wiki.cli import scaffold_vault

            scaffold_vault(self.vault)
        if not self.vault.is_dir():
            raise MemoryError_(
                f"vault not found: {self.vault} — pass create=True to scaffold it"
            )

    def __repr__(self) -> str:
        scope = f", user_id={self.user_id!r}" if self.user_id else ""
        return f"Memory({str(self.vault)!r}{scope})"

    def _scope(self, user_id: Optional[str]) -> str:
        return _mem.check_scope(self.user_id if user_id is None else user_id)

    # -- knowledge ---------------------------------------------------------

    def add(
        self,
        content: Content,
        *,
        title: Optional[str] = None,
        category: str = DEFAULT_CATEGORY,
        tags: Optional[Iterable[str]] = None,
        sources: Optional[Iterable[str]] = None,
        summary: str = "",
        sync: bool = True,
    ) -> dict:
        """Store knowledge as a page, and return where it went.

        Accepts a string or OpenAI-shaped messages. The page is written
        verbatim — nothing here distils, dedupes or cross-links, because doing
        so needs an LLM the caller already has. ``/wiki-ingest`` and
        ``cross-linker`` are the passes that do that work.

        Writing an existing title updates that page and preserves its
        ``created`` date.
        """
        body = _render_messages(content) if not isinstance(content, str) else content.strip()
        if not body:
            raise MemoryError_("nothing to add: content is empty")
        title = (title or _title_from(body)).strip()
        category = _mem.check_scope(category) or DEFAULT_CATEGORY

        relative = f"{category}/{_slug(title.rstrip(chr(46)))}.md"
        target = _mem.resolve_in_vault(self.vault, relative) if hasattr(_mem, "resolve_in_vault") else self.vault / relative
        today = date.today().isoformat()
        created = today
        if target.is_file():
            match = re.search(r"^created:\s*(\S+)", target.read_text(encoding="utf-8"), re.MULTILINE)
            created = match.group(1) if match else today

        front = "\n".join([
            "---",
            f"title: {title}",
            f"category: {category}",
            "tags: [" + ", ".join(tags or []) + "]",
            "sources: [" + ", ".join(sources or ["conversation"]) + "]",
            f"summary: {summary or _summary_from(body)}",
            f"created: {created}",
            f"updated: {today}",
            "---",
            "",
            f"# {title}",
            "",
        ])
        _mem.atomic_write(target, front + body.rstrip() + "\n")

        result = {"path": relative, "title": title, "category": category, "created": created}
        if sync:
            result["sync"] = self.sync("MEMORY_ADD", page=relative)
        return result

    def search(self, query: str, *, limit: int = 8) -> list:
        """Rank pages against *query*. Lexical and index-backed, never remote."""
        from obsidian_wiki import graphrag

        found = graphrag.query(self.vault, query, top_n=limit)
        should_read = {str(p).removesuffix(".md") for p in (found.get("should_read") or [])}
        results = []
        for candidate in (found.get("candidates") or [])[:limit]:
            page = candidate.get("page", "")
            results.append({
                "path": f"{page}.md" if page and not page.endswith(".md") else page,
                "title": candidate.get("title", ""),
                "summary": candidate.get("summary", ""),
                "score": candidate.get("score", 0.0),
                "tier": candidate.get("tier", ""),
                # graphrag's judgement on which pages are worth opening in full;
                # the rest are answerable from the summary alone.
                "should_read": page in should_read,
            })
        return results

    def get(self, path: str) -> str:
        """One page as markdown, by vault-relative path."""
        target = (self.vault / path).resolve()
        if target != self.vault.resolve() and self.vault.resolve() not in target.parents:
            raise MemoryError_(f"path escapes the vault: {path}")
        if not target.is_file():
            raise MemoryError_(f"no such page: {path}")
        return target.read_text(encoding="utf-8")

    def context(self, topic: str = "", *, budget: int = 8000, recent: bool = False) -> str:
        """A token-bounded slice of the vault, for a downstream prompt."""
        from obsidian_wiki.context_pack import build_context_pack, render_markdown

        return render_markdown(build_context_pack(self.vault, topic, budget=budget, recent=recent))

    # -- person-shaped memory ---------------------------------------------

    def remember(
        self,
        key: str,
        value: str,
        *,
        confidence: float = 0.6,
        source: str = "agent",
        user_id: Optional[str] = None,
    ) -> dict:
        """Record a durable fact about the person. Re-keying replaces it.

        Only record what they actually told you. A fact inferred from a
        document you ingested is that document's content and belongs on a page.
        """
        fact = _mem.set_fact(
            self.vault, key, value,
            confidence=confidence, source=source, scope=self._scope(user_id),
        )
        return dict(fact.__dict__)

    def forget(self, key: str, *, user_id: Optional[str] = None) -> bool:
        return _mem.forget_fact(self.vault, key, scope=self._scope(user_id))

    def profile(self, *, user_id: Optional[str] = None) -> list:
        return [dict(f.__dict__) for f in _mem.load_profile(self.vault, self._scope(user_id))]

    def todo(self, text: str, *, origin: str = "", user_id: Optional[str] = None) -> dict:
        """Record an open thread. Re-adding the same text touches it."""
        todo = _mem.add_todo(self.vault, text, origin=origin, scope=self._scope(user_id))
        return dict(todo.__dict__)

    def todos(self, *, include_closed: bool = False, user_id: Optional[str] = None) -> list:
        items = _mem.load_todos(self.vault, self._scope(user_id))
        if not include_closed:
            items = [t for t in items if t.status == "open"]
        return [dict(t.__dict__, stale=t.is_stale()) for t in items]

    def close_todo(self, todo_id: str, *, dropped: bool = False, user_id: Optional[str] = None) -> dict:
        todo = _mem.set_todo_status(
            self.vault, todo_id, "dropped" if dropped else "done", scope=self._scope(user_id),
        )
        return dict(todo.__dict__)

    def scopes(self) -> list:
        """Scope names with memory in this vault."""
        return _mem.list_scopes(self.vault)

    # -- session -----------------------------------------------------------

    def recap(
        self,
        *,
        project: str = "",
        max_words: int = 350,
        min_confidence: float = 0.0,
        user_id: Optional[str] = None,
    ) -> str:
        """Profile, open threads and recent activity as one injectable block.

        This is the call to make when a session starts.
        """
        return _mem.build_recap(
            self.vault,
            max_words=max_words,
            min_confidence=min_confidence,
            project=project or None,
            scope=self._scope(user_id),
        )

    def sync(self, verb: str = "", **fields: Any) -> dict:
        """Reconcile the index and hot cache after writing, under one lock.

        Degrades rather than failing on a vault whose memory files predate this
        writer: the log line still lands and the skip is reported.
        """
        index = hot = None
        skipped = ""
        with _mem.memory_lock(self.vault):
            line = _mem.append_log(self.vault, verb, fields, lock=False) if verb else ""
            try:
                index = _mem.rebuild_index(self.vault, link_format=self.link_format, lock=False)
                hot = _mem.rebuild_hot(self.vault, lock=False, link_format=self.link_format)
            except _mem.MemoryError_ as exc:
                if exc.code != "unmigrated":
                    raise
                skipped = str(exc)
        return {
            "log_line": line,
            "pages": index.total if index else None,
            "hot_words": hot.words if hot else None,
            "skipped": skipped,
        }

    def status(self) -> dict:
        return _mem.memory_status(self.vault)
