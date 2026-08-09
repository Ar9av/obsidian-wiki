"""Session cache adapters: read agent session histories into weighted text docs.

This is the input layer of the "session brain". It turns a directory of raw
agent transcripts into `SessionDoc` records — small, field-weighted bags of text
that `session_index` can turn into TF-IDF vectors.

Claude is the only source registered in v1. `SessionDoc` is the seam: adding
Codex (`~/.codex/sessions/**/rollout-*.jsonl`) or Copilot means writing another
reader that emits the same dataclass.

Two tiers of session exist, and both matter:

  full  — a transcript exists at ~/.claude/projects/<slug>/<id>.jsonl
  thin  — the transcript has been pruned from disk, but the session still
          appears in ~/.claude/history.jsonl with its prompts. Roughly 40% of
          all sessions on a long-lived machine are thin. They can never be
          loaded, but they can absolutely be found, so they get graph nodes.

Nothing here hardcodes ~/.claude: `claude_dir` is always a parameter, so tests
run against synthetic fixtures under tmp_path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# --- Truncation budget ------------------------------------------------------
# These caps are the performance lever for the whole feature. Tokenization, not
# I/O, dominates build time (a full json.loads pass over 800 MB is ~2s warm), so
# the way to keep builds fast is to tokenize less text — not to read less of it.
# With these caps a 40 MB session costs about the same as a 2 MB one.
MAX_PROMPT_CHARS = 4_000       # per user prompt
MAX_ASSISTANT_BLOCKS = 40      # assistant text blocks retained per session
MAX_ASSISTANT_CHARS = 400      # per assistant block — enough for the topic sentence
MAX_DOC_CHARS = 120_000        # hard ceiling on retained text per session
TITLE_FROM_PROMPT_CHARS = 100

# Slash-command wrappers, caveats, and hook output all arrive as user-role lines
# that start with a tag. They are machine boilerplate, not what the human asked.
_WRAPPED_PROMPT = ("<",)

_PR_REPO_RE = re.compile(r"github\.com[:/]([^/]+/[^/\s]+?)(?:\.git)?/?$")


@dataclass
class SessionDoc:
    """One session, reduced to weighted text fields plus display metadata."""

    session_id: str
    tier: str = "full"                       # "full" | "thin"
    title: str = ""
    title_source: str = ""                   # ai-title|last-prompt|first-prompt|sessions-json|history-display|derived
    project: str = ""                        # basename of cwd
    project_slug: str = ""                   # -Users-me-projects-foo
    cwd: str = ""
    git_branch: str = ""
    start_ts: str = ""                       # ISO-8601
    end_ts: str = ""
    n_turns: int = 0
    n_user_prompts: int = 0
    n_user_words: int = 0
    transcript: str | None = None            # absolute path, None for thin
    transcript_bytes: int = 0
    subagents: list[dict] = field(default_factory=list)
    pr_links: list[str] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)
    bookmark: dict | None = None
    fields: dict[str, list[str]] = field(default_factory=dict)

    def add(self, name: str, text: str) -> None:
        """Append text to a weighted field, ignoring blanks."""
        if text and text.strip():
            self.fields.setdefault(name, []).append(text.strip())

    def text_size(self) -> int:
        return sum(len(t) for texts in self.fields.values() for t in texts)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _iso(ts: Any) -> str:
    """Normalise a timestamp to ISO-8601 UTC. Accepts ISO strings or epoch ms."""
    if not ts:
        return ""
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            return ""
    return str(ts)


def _project_from_cwd(cwd: str) -> str:
    return Path(cwd).name if cwd else ""


def _slug_to_cwd(slug: str) -> str:
    """Best-effort inverse of Claude's cwd encoding (slashes replaced by dashes).

    The encoding is lossy — a real dash in a directory name is indistinguishable
    from a separator — so this is only a fallback when no line in the transcript
    carried an actual `cwd`.
    """
    return "/" + slug.lstrip("-").replace("-", "/") if slug else ""


def _is_real_prompt(rec: dict) -> bool:
    """True for a line that is genuinely something the human typed.

    User-role lines also carry tool results (content is a list), sidechain
    (subagent) traffic, and injected meta content. Only a plain string content
    on a non-sidechain, non-meta line is a real prompt.
    """
    if rec.get("type") != "user":
        return False
    if rec.get("isSidechain") or rec.get("isMeta"):
        return False
    content = (rec.get("message") or {}).get("content")
    if not isinstance(content, str):
        return False
    return not content.lstrip().startswith(_WRAPPED_PROMPT)


def _assistant_text(rec: dict) -> Iterator[str]:
    """Yield the plain-text blocks of an assistant turn, skipping thinking/tools."""
    if rec.get("type") != "assistant" or rec.get("isSidechain"):
        return
    content = (rec.get("message") or {}).get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if text:
                yield text


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def iter_transcripts(claude_dir: Path, *, skip: list[str] | None = None) -> Iterator[Path]:
    """Yield every top-level session transcript, newest project dirs included.

    Subagent transcripts under `<session-id>/subagents/` are deliberately not
    yielded — they are folded into their parent session instead.
    """
    projects = claude_dir / "projects"
    if not projects.is_dir():
        return
    skip_set = {s.strip() for s in (skip or []) if s.strip()}
    for project_dir in sorted(projects.iterdir()):
        if not project_dir.is_dir():
            continue
        if project_dir.name in skip_set:
            continue
        if any(s in project_dir.name for s in skip_set):
            continue
        for path in sorted(project_dir.glob("*.jsonl")):
            if path.is_file():
                yield path


def read_subagents(project_dir: Path, session_id: str) -> list[dict]:
    """Read the `agent-*.meta.json` sidecars for a session's subagents.

    Each carries an `agentType` and a human-written `description` of what the
    subagent was asked to do — a dense, cheap topic signal with no transcript
    parsing at all.
    """
    meta_dir = project_dir / session_id / "subagents"
    if not meta_dir.is_dir():
        return []
    out: list[dict] = []
    for meta_path in sorted(meta_dir.glob("agent-*.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict):
            out.append({
                "agentType": str(meta.get("agentType") or ""),
                "description": str(meta.get("description") or ""),
            })
    return out


def read_transcript(path: Path) -> SessionDoc | None:
    """Stream one session transcript into a SessionDoc.

    Streams line by line and never holds the whole file: the largest sessions on
    a real machine are tens of MB.
    """
    session_id = path.stem
    doc = SessionDoc(session_id=session_id, tier="full")
    doc.transcript = str(path)
    try:
        doc.transcript_bytes = path.stat().st_size
    except OSError:
        return None

    ai_title = ""
    last_prompt = ""
    first_prompt = ""
    assistant_blocks = 0
    truncated = False

    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return None

    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue

            rtype = rec.get("type")

            # Title candidates. Both repeat throughout the file; last one wins.
            if rtype == "ai-title":
                ai_title = str(rec.get("aiTitle") or "") or ai_title
                continue
            if rtype == "last-prompt":
                last_prompt = str(rec.get("lastPrompt") or "") or last_prompt
                continue
            if rtype == "pr-link":
                url = str(rec.get("prUrl") or "")
                repo = str(rec.get("prRepository") or "")
                if url:
                    doc.pr_links.append(url)
                if repo:
                    m = _PR_REPO_RE.search(repo) or _PR_REPO_RE.search(url)
                    doc.repos.append(m.group(1) if m else repo)
                continue

            if rtype not in ("user", "assistant"):
                continue

            # Envelope metadata — take the first non-empty value we see.
            doc.n_turns += 1
            if not doc.cwd:
                doc.cwd = str(rec.get("cwd") or "")
            if not doc.git_branch:
                doc.git_branch = str(rec.get("gitBranch") or "")
            ts = _iso(rec.get("timestamp"))
            if ts:
                if not doc.start_ts:
                    doc.start_ts = ts
                doc.end_ts = ts

            if truncated:
                continue

            if _is_real_prompt(rec):
                text = (rec["message"]["content"] or "")[:MAX_PROMPT_CHARS]
                doc.n_user_prompts += 1
                doc.n_user_words += len(text.split())
                if not first_prompt:
                    first_prompt = text
                    doc.add("first_prompt", text)
                else:
                    doc.add("prompt", text)
            else:
                for block in _assistant_text(rec):
                    if assistant_blocks >= MAX_ASSISTANT_BLOCKS:
                        break
                    doc.add("assistant", block[:MAX_ASSISTANT_CHARS])
                    assistant_blocks += 1

            if doc.text_size() >= MAX_DOC_CHARS:
                truncated = True

    if doc.n_turns == 0:
        return None

    doc.project_slug = path.parent.name
    if not doc.cwd:
        doc.cwd = _slug_to_cwd(doc.project_slug)
    doc.project = _project_from_cwd(doc.cwd)
    doc.subagents = read_subagents(path.parent, session_id)

    _resolve_title(doc, ai_title=ai_title, last_prompt=last_prompt, first_prompt=first_prompt)
    _add_meta_fields(doc)
    return doc


def _resolve_title(doc: SessionDoc, *, ai_title: str, last_prompt: str, first_prompt: str) -> None:
    """Pick the best available title.

    Only about half of sessions carry an `ai-title`, so the fallback chain does
    real work. `title_source` is recorded because downstream weighting trusts a
    generated title more than a truncated first prompt.
    """
    if ai_title:
        doc.title, doc.title_source = ai_title, "ai-title"
    elif last_prompt:
        doc.title, doc.title_source = last_prompt, "last-prompt"
    elif first_prompt:
        doc.title = first_prompt[:TITLE_FROM_PROMPT_CHARS]
        doc.title_source = "first-prompt"
    else:
        doc.title, doc.title_source = "", ""


def _add_meta_fields(doc: SessionDoc) -> None:
    """Fold structured metadata into the weighted text fields."""
    if doc.title:
        doc.add("title", doc.title)
    for sub in doc.subagents:
        doc.add("subagent", f"{sub.get('agentType', '')} {sub.get('description', '')}")
    for repo in doc.repos:
        doc.add("repo", repo.replace("/", " ") + " repo:" + repo.replace("/", "-"))
    if doc.project:
        doc.add("project", f"{doc.project} proj:{doc.project}")
    if doc.git_branch and doc.git_branch not in ("main", "master"):
        doc.add("branch", doc.git_branch)


def read_history(claude_dir: Path) -> dict[str, dict]:
    """Read ~/.claude/history.jsonl — the authoritative universe of session ids.

    This file long outlives the transcripts it describes, so it is both the
    source of thin nodes and a cross-check that no session is missed.
    """
    path = claude_dir / "history.jsonl"
    if not path.is_file():
        return {}
    sessions: dict[str, dict] = {}
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return {}
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            sid = rec.get("sessionId")
            if not sid:
                continue
            entry = sessions.setdefault(sid, {
                "project": rec.get("project") or "",
                "prompts": [],
                "first_ms": None,
                "last_ms": None,
            })
            display = rec.get("display")
            if isinstance(display, str):
                text = display.strip()
                # Slash commands and tag-wrapped lines carry no topic signal.
                if text and not text.startswith(("/", "<")):
                    entry["prompts"].append(text[:MAX_PROMPT_CHARS])
            ts = rec.get("timestamp")
            if isinstance(ts, (int, float)):
                if entry["first_ms"] is None or ts < entry["first_ms"]:
                    entry["first_ms"] = ts
                if entry["last_ms"] is None or ts > entry["last_ms"]:
                    entry["last_ms"] = ts
    return sessions


def read_session_names(claude_dir: Path) -> dict[str, str]:
    """Read ~/.claude/sessions/*.json for human-ish session names.

    These files are keyed by PID and describe live sessions, but they carry a
    derived `name` that beats a truncated first prompt as a title.
    """
    sessions_dir = claude_dir / "sessions"
    if not sessions_dir.is_dir():
        return {}
    names: dict[str, str] = {}
    for path in sessions_dir.glob("*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        sid, name = rec.get("sessionId"), rec.get("name")
        if sid and isinstance(name, str) and name.strip():
            names[sid] = name.strip()
    return names


def load_bookmarks(path: Path | None) -> dict[str, dict]:
    """Read ~/.bookmark-agent/bookmarks.json — the only curated tags available.

    Human-chosen tags are worth far more per token than anything mined from a
    transcript, so they get a high field weight and a retrieval boost.
    """
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, list):
        return {}
    out: dict[str, dict] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        sid = entry.get("sessionId")
        if not sid:
            continue
        out[sid] = {
            "id": entry.get("id") or "",
            "tool": entry.get("tool") or "",
            "title": entry.get("title") or "",
            "tags": [t for t in (entry.get("tags") or []) if isinstance(t, str)],
            "note": entry.get("note") or "",
            "created_at": entry.get("createdAt") or "",
        }
    return out


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

def _source_stat(path: Path) -> dict | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return {"path": str(path), "size": st.st_size, "mtime": round(st.st_mtime, 3)}


def _thin_doc(session_id: str, entry: dict, names: dict[str, str]) -> SessionDoc:
    """Build a node for a session whose transcript no longer exists on disk."""
    cwd = entry.get("project") or ""
    doc = SessionDoc(session_id=session_id, tier="thin", cwd=cwd)
    doc.project = _project_from_cwd(cwd)
    doc.start_ts = _iso(entry.get("first_ms"))
    doc.end_ts = _iso(entry.get("last_ms"))
    prompts: list[str] = entry.get("prompts") or []
    doc.n_user_prompts = len(prompts)
    doc.n_user_words = sum(len(p.split()) for p in prompts)
    doc.n_turns = len(prompts)

    for i, prompt in enumerate(prompts):
        doc.add("first_prompt" if i == 0 else "prompt", prompt)

    name = names.get(session_id, "")
    if name:
        doc.title, doc.title_source = name, "sessions-json"
    elif prompts:
        doc.title = prompts[0][:TITLE_FROM_PROMPT_CHARS]
        doc.title_source = "history-display"
    _add_meta_fields(doc)
    return doc


def collect(
    claude_dir: Path,
    *,
    bookmarks_path: Path | None = None,
    skip: list[str] | None = None,
    since: str | None = None,
    state: dict | None = None,
) -> tuple[list[SessionDoc], dict[str, Any]]:
    """Read every session that has changed since the last build.

    Returns `(docs, info)`. `docs` holds only sessions actually read this run;
    `info["unchanged"]` lists ids whose cached term maps remain valid, so the
    caller can reuse them instead of re-reading 800 MB. `info["state"]` is the
    new gating table to persist.
    """
    claude_dir = Path(claude_dir).expanduser()
    prev_sources: dict[str, dict] = (state or {}).get("sources", {}) or {}
    since_ts = None
    if since:
        try:
            since_ts = datetime.fromisoformat(since.replace("Z", "+00:00")).timestamp()
        except ValueError:
            since_ts = None

    bookmarks = load_bookmarks(bookmarks_path)
    names = read_session_names(claude_dir)

    docs: list[SessionDoc] = []
    new_sources: dict[str, dict] = {}
    unchanged: list[str] = []
    on_disk: set[str] = set()
    skipped_since = 0

    for path in iter_transcripts(claude_dir, skip=skip):
        session_id = path.stem
        on_disk.add(session_id)
        stat = _source_stat(path)
        if stat is None:
            continue
        if since_ts is not None and stat["mtime"] < since_ts:
            skipped_since += 1
            continue

        stat["tier"] = "full"
        new_sources[session_id] = stat

        prev = prev_sources.get(session_id)
        if prev and prev.get("size") == stat["size"] and prev.get("mtime") == stat["mtime"]:
            unchanged.append(session_id)
            continue

        doc = read_transcript(path)
        if doc is None:
            new_sources.pop(session_id, None)
            on_disk.discard(session_id)
            continue
        docs.append(doc)

    # Thin nodes: in history.jsonl but with no transcript on disk.
    history = read_history(claude_dir)
    thin_ids = [sid for sid in history if sid not in on_disk]
    history_stat = _source_stat(claude_dir / "history.jsonl")
    prev_history = (state or {}).get("history")
    history_changed = history_stat != prev_history

    for sid in thin_ids:
        new_sources[sid] = {"path": None, "size": 0, "mtime": 0.0, "tier": "thin"}
        if not history_changed and sid in prev_sources:
            unchanged.append(sid)
            continue
        doc = _thin_doc(sid, history[sid], names)
        # A thin node is only worth a graph node if it retains real prompt text.
        # Sessions whose every history entry was a slash command survive with
        # nothing but a project token, which would cluster on the project name
        # alone and add hundreds of meaningless nodes to the graph.
        if doc.n_user_prompts > 0:
            docs.append(doc)
        else:
            new_sources.pop(sid, None)

    # Bookmarks are cheap and change independently of transcripts; attach to
    # everything read this run.
    for doc in docs:
        bm = bookmarks.get(doc.session_id)
        if bm:
            doc.bookmark = bm
            doc.add("bookmark", " ".join([bm.get("title", ""), *bm.get("tags", []), bm.get("note", "")]))

    info: dict[str, Any] = {
        "state": {
            "sources": new_sources,
            "history": history_stat,
            "bookmarks": _source_stat(bookmarks_path) if bookmarks_path else None,
        },
        "unchanged": unchanged,
        "read": len(docs),
        "full_on_disk": len(on_disk),
        "thin": len(thin_ids),
        "skipped_since": skipped_since,
        "bookmarks": len(bookmarks),
    }
    return docs, info
