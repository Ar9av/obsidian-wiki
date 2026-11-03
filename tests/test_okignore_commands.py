"""A page listed in `.okignore` must not surface in any command that walks the vault.

Each command runs twice, against a fresh vault: without `.okignore`, to prove it
really does reach the protected pages (so a crash or an empty answer can't pass
for protection), then with it, where they must be gone from its output and from
every file it writes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import _run_cli

CANARY = "zebracanary"
OKIGNORE = (
    "# gitignore-style subset\n"
    "Private/\n"
    "My Inbox/\n"
    "Areas/Personal/\n"
    "_raw/_archived/private\n"
    "_staging/private\n"
    "_raw/quarantine\n"
)
TRUST = ("--reviewed-at", "2026-01-02T00:00:00+00:00", "--approved")
TOPIC = "wombat quokka"

# Each entry is the commands to run, in order; "{v}" is the vault path.
COMMANDS = {
    "context-pack": [("context-pack", TOPIC, "--vault", "{v}", "--json")],
    "context-pack-recent": [("context-pack", "--recent", "--vault", "{v}", "--json")],
    "recall": [("recall", TOPIC, "--vault", "{v}")],
    "query": [("query", TOPIC, "--vault", "{v}", "--json")],
    "graph-query": [("graph-query", "{v}", TOPIC)],
    "graph-analyse": [("graph-analyse", "{v}")],
    "lint": [("lint", "{v}", "--json")],
    "trust": [("trust-record", "{v}", "--all", *TRUST), ("trust-check", "{v}", "--json")],
    "staging-list": [("staging", "list", "--vault", "{v}", "--json")],
    "memory-index": [("memory", "index", "--vault", "{v}")],
    "memory-timezone": [("memory", "timezone", "America/Detroit", "--vault", "{v}", "--json")],
    "batch-plan": [("batch-plan", "{v}", "{v}/_raw", "--no-cache")],
}


def _page(title: str, *links: str) -> str:
    related = "".join(f"\n[[{link}]]\n" for link in links)
    return (
        f"---\ntitle: {title}\ncategory: concepts\ntags: [wombat, quokka]\nsources: []\n"
        f"summary: {title} about wombat and quokka habitats\n"
        "created: 2026-01-01T00:00:00Z\nupdated: 2026-01-01T00:00:00Z\n"
        "base_confidence: 0.8\nlifecycle: reviewed\nlifecycle_changed: 2026-01-01\n---\n\n"
        f"# {title}\n\nBody of {title}.\n{related}"
    )


def _vault(root: Path, *, ignored: bool) -> Path:
    vault = root / "vault"
    pages = {
        "concepts/public-one.md": _page("public one", "public-two"),
        "concepts/public-two.md": _page("public two", "public-one"),
        f"Private/{CANARY}-a.md": _page(f"{CANARY} a", "public-one", "ghost-a"),
        f"My Inbox/{CANARY}-b.md": _page(f"{CANARY} b", "public-one", "ghost-b"),
        f"Areas/Personal/{CANARY}-c.md": _page(f"{CANARY} c", "public-one", "ghost-c"),
        f"_raw/_archived/private/{CANARY}-clip.md": f"---\nurl: https://example.test/{CANARY}\n---\n\nclip\n",
        f"_raw/quarantine/{CANARY}.md": "a source awaiting ingest\n",
        f"_staging/private/{CANARY}-staged.md": _page(f"{CANARY} staged"),
    }
    for rel, text in pages.items():
        path = vault / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    if ignored:
        (vault / ".okignore").write_text(OKIGNORE, encoding="utf-8")
    return vault


def _run(name: str, root: Path, *, ignored: bool) -> str:
    """Everything the command told the caller or left behind, minus the pages themselves."""
    vault = _vault(root, ignored=ignored)
    seen = []
    for command in COMMANDS[name]:
        args = [arg.replace("{v}", str(vault)) for arg in command]
        proc = _run_cli(root, *args)
        assert "Traceback" not in proc.stderr, proc.stderr
        seen += [proc.stdout, proc.stderr]
    for path in vault.rglob("*"):
        if path.is_file() and CANARY not in path.as_posix():
            seen.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(seen)


@pytest.mark.parametrize("name", sorted(COMMANDS))
def test_command_reaches_pages_until_they_are_ignored(tmp_path: Path, name: str) -> None:
    (tmp_path / "control").mkdir()
    (tmp_path / "ignored").mkdir()
    assert CANARY in _run(name, tmp_path / "control", ignored=False)
    assert CANARY not in _run(name, tmp_path / "ignored", ignored=True)


def test_ledger_entries_stop_naming_a_page_once_it_is_ignored(tmp_path: Path) -> None:
    vault = _vault(tmp_path, ignored=False)
    assert _run_cli(tmp_path, "trust-record", str(vault), "--all", *TRUST).returncode == 0
    ledger = vault / "_meta" / "trust-ledger.json"
    assert CANARY in ledger.read_text(encoding="utf-8")
    (vault / ".okignore").write_text(OKIGNORE, encoding="utf-8")

    check = _run_cli(tmp_path, "trust-check", str(vault), "--json")
    assert CANARY not in check.stdout + check.stderr
    assert json.loads(check.stdout)["ignored_entries"] == 3

    page = "concepts/public-one.md"
    record = _run_cli(tmp_path, "trust-record", str(vault), "--page", page, *TRUST, "--json")
    assert CANARY not in record.stdout + record.stderr
    assert CANARY not in ledger.read_text(encoding="utf-8")
