# Deterministic Index Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `obsidian-wiki index` generate unambiguous, configuration-aware indexes and migrate every page-writing skill to use it with a manual fallback.

**Architecture:** Keep lint's frontmatter parser as the metadata source, adding structured tag extraction without changing existing fields. Make the index renderer accept an explicit link format and render from vault-relative paths, while the CLI resolves configuration precedence. Document one canonical refresh contract and duplicate its executable command in each page-writing skill so agents cannot silently drift back to manual-only maintenance.

**Tech Stack:** Python 3.9+ standard library, argparse, pytest, Markdown skill instructions, Git.

## Global Constraints

- Add no third-party runtime dependencies.
- Preserve `--check` as a read-only exact-content comparison.
- Accept only `wikilink` and `markdown` link formats.
- Use full vault-relative paths for link identity.
- Preserve the existing `— summary ( #tag)` entry format.
- Do not modify the configured user vault.
- Do not run index refreshes in read-only, audit-only, dry-run, no-op, or staged-only flows.
- If the CLI exists but fails, report the failure; manual fallback is only for an unavailable executable.

---

### Task 1: Parse Inline and Block-List Tags

**Files:**
- Modify: `obsidian_wiki/lint.py:38-165`
- Modify: `tests/test_index_cmd.py`

**Interfaces:**
- Produces: `_parse_frontmatter_list(frontmatter: str, key: str) -> list[str]`
- Extends: `_parse_page(path: Path, vault: Path) -> dict[str, Any]` with `tag_list: list[str]`
- Preserves: existing `tags: str` return field for current lint consumers

- [ ] **Step 1: Write failing inline/block-list tag tests**

Import `_parse_page` from `obsidian_wiki.lint`. Add a `frontmatter_lines` argument to the existing `_page` helper so a test can supply block-list YAML, then add:

```python
def test_index_renders_inline_and_block_list_tags(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    inline = _page(vault, "concepts/inline.md", tags="[ml, architecture]")
    block = _page(
        vault,
        "concepts/block.md",
        tags=None,
        frontmatter_lines=["tags:", "  - ml", "  - 'architecture'"],
    )

    assert _parse_page(inline, vault)["tag_list"] == ["ml", "architecture"]
    assert _parse_page(block, vault)["tag_list"] == ["ml", "architecture"]
```

Change the helper signature to `tags: str | None = "[test]"` and `frontmatter_lines: list[str] | None = None`; append `f"tags: {tags}"` only when `tags is not None`, then append `frontmatter_lines or []`.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
uv run --no-project --python 3.12 --with pytest pytest tests/test_index_cmd.py::test_index_renders_inline_and_block_list_tags -q
```

Expected: FAIL with a missing `tag_list` key because `_parse_page` exposes only the raw tag string.

- [ ] **Step 3: Implement structured tag parsing in lint**

Add these helpers immediately after `_parse_frontmatter_values`:

```python
def _strip_frontmatter_scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.split(" #", 1)[0].strip().lstrip("#")


def _parse_frontmatter_list(frontmatter: str, key: str) -> list[str]:
    values = _parse_frontmatter_values(frontmatter)
    inline = values.get(key, "").strip()
    if inline:
        if inline.startswith("[") and inline.endswith("]"):
            inline = inline[1:-1]
        return [
            value
            for part in inline.split(",")
            if (value := _strip_frontmatter_scalar(part))
        ]

    lines = frontmatter.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != f"{key}:":
            continue
        items: list[str] = []
        for child in lines[index + 1 :]:
            if child and not child.startswith((" ", "\t")):
                break
            stripped = child.strip()
            if not stripped:
                continue
            if not stripped.startswith("-"):
                break
            value = _strip_frontmatter_scalar(stripped[1:])
            if value:
                items.append(value)
        return items
    return []
```

Add `"tag_list": _parse_frontmatter_list(frontmatter, "tags")` to `_parse_page` while retaining `"tags"`.

- [ ] **Step 4: Run the parser test and verify GREEN**

Run the targeted test again. Expected: PASS with identical `tag_list` values for inline and block-list YAML.

- [ ] **Step 5: Commit the metadata parser change**

```bash
git add obsidian_wiki/lint.py tests/test_index_cmd.py
git commit -m "fix(index): parse structured page tags"
```

---

### Task 2: Render Full Paths, Titles, Categories, and Both Link Formats

**Files:**
- Modify: `obsidian_wiki/index.py`
- Modify: `tests/test_index_cmd.py`

**Interfaces:**
- Produces: `build_index(vault: Path, *, link_format: str = "wikilink") -> str`
- Produces: `rebuild_index(vault: Path, *, check: bool = False, link_format: str = "wikilink") -> dict[str, Any]`
- Internal: `_render_link(page: dict[str, Any], link_format: str) -> str`
- Consumes: `_parse_page(...)["tag_list"]` from Task 1

- [ ] **Step 1: Write failing renderer tests**

Add these tests:

```python
def test_index_uses_full_paths_and_frontmatter_titles(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "projects/alpha/shared.md", title="Alpha Shared", category="project")
    _page(vault, "projects/beta/shared.md", title="Beta Shared", category="project")

    text = build_index(vault)

    assert "[[projects/alpha/shared|Alpha Shared]]" in text
    assert "[[projects/beta/shared|Beta Shared]]" in text
    assert text.count("[[shared]]") == 0


def test_index_renders_root_relative_markdown_links(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/friendly-slug.md", title="Friendly Name")

    text = build_index(vault, link_format="markdown")

    assert "[Friendly Name](concepts/friendly-slug.md)" in text
    assert "[[" not in text


def test_index_preserves_noncanonical_category_case(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "AI/guide.md", title="Guide", category="AI")

    text = build_index(vault)

    assert "## AI" in text
    assert "## Ai" not in text


def test_index_renders_block_list_tags(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(
        vault,
        "concepts/block.md",
        tags=None,
        frontmatter_lines=["tags:", "  - ml", "  - architecture"],
    )

    text = build_index(vault)

    assert "[[concepts/block]] — Short summary. ( #ml #architecture)" in text
```

Extend `_page` with `title: str | None = None`; render `title or path.stem` in frontmatter. Update the pre-existing assertions in `test_index_rebuild_groups_and_sorts`, `test_index_skips_excluded_dirs_and_special_files`, and `test_index_cli_uses_configured_vault` to expect full vault-relative targets such as `[[concepts/alpha]]`, `[[entities/tool]]`, and `[[projects/proj]]`.

- [ ] **Step 2: Run renderer tests and verify RED**

```bash
uv run --no-project --python 3.12 --with pytest pytest tests/test_index_cmd.py -q
```

Expected: the new full-path, Markdown, and category-case tests fail against the stem-only renderer.

- [ ] **Step 3: Implement path-aware grouping and link rendering**

Replace `_collect_pages`, `_entry`, and `_render` with functions following these exact contracts:

```python
def _category_key(raw: str) -> str:
    normalized = raw.strip().lower()
    return _CATEGORY_ALIASES.get(normalized, normalized)


def _collect_pages(
    vault: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, set[str]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    labels: dict[str, set[str]] = defaultdict(set)
    for path in sorted(vault.rglob("*.md")):
        rel = path.relative_to(vault)
        if any(part in SKIP_DIRS for part in rel.parts) or rel.name in SPECIAL_FILES:
            continue
        page = _parse_page(path, vault)
        raw_category = page["category"] or (rel.parts[0] if len(rel.parts) > 1 else "uncategorized")
        key = _category_key(raw_category)
        groups[key].append(page)
        labels[key].add(raw_category)
    return groups, labels


def _render_link(page: dict[str, Any], link_format: str) -> str:
    path = Path(page["path"])
    target = path.with_suffix("").as_posix()
    title = page["title"]
    if link_format == "markdown":
        return f"[{title}]({path.as_posix()})"
    if link_format != "wikilink":
        raise ValueError(f"unsupported link format: {link_format}")
    if title != path.stem:
        return f"[[{target}|{title}]]"
    return f"[[{target}]]"


def _entry(page: dict[str, Any], link_format: str) -> str:
    entry = f"- {_render_link(page, link_format)}"
    if page["summary"]:
        entry += f" — {page['summary']}"
    if page["tag_list"]:
        entry += " ( " + " ".join(f"#{tag}" for tag in page["tag_list"]) + ")"
    return entry


def _render(
    groups: dict[str, list[dict[str, Any]]],
    labels: dict[str, set[str]],
    link_format: str,
) -> str:
    lines = list(_HEADER_LINES)
    ordered = [category for category in _CATEGORY_ORDER if category in groups]
    ordered.extend(sorted(category for category in groups if category not in _CATEGORY_ORDER))
    for category in ordered:
        heading = (
            category.title()
            if category in _CATEGORY_ORDER
            else min(labels[category], key=lambda label: (label.casefold(), label))
        )
        lines.extend(("", f"## {heading}"))
        for page in sorted(
            groups[category],
            key=lambda item: (item["path"].casefold(), item["path"]),
        ):
            lines.append(_entry(page, link_format))
    return "\n".join(lines) + "\n"
```

Update `build_index` to collect both structures and render explicitly:

```python
def build_index(vault: Path, *, link_format: str = "wikilink") -> str:
    groups, labels = _collect_pages(vault)
    return _render(groups, labels, link_format)
```

In `rebuild_index`, add keyword-only `link_format: str = "wikilink"`, replace `groups = _collect_pages(vault)` with `groups, labels = _collect_pages(vault)`, and replace `generated = _render(groups)` with `generated = _render(groups, labels, link_format)`. Remove the old `_parse_tags` because `_entry` now consumes `page["tag_list"]`.

- [ ] **Step 4: Run renderer and tag tests; verify GREEN**

```bash
uv run --no-project --python 3.12 --with pytest pytest tests/test_index_cmd.py -q
```

Expected: all index tests pass, including inline/block tags from Task 1.

- [ ] **Step 5: Commit renderer behavior**

```bash
git add obsidian_wiki/index.py obsidian_wiki/lint.py tests/test_index_cmd.py
git commit -m "fix(index): render unambiguous configured links"
```

---

### Task 3: Resolve CLI Link-Format Precedence and Validation

**Files:**
- Modify: `obsidian_wiki/cli.py:840-863,1050-1065`
- Modify: `tests/test_index_cmd.py`

**Interfaces:**
- Produces: `_resolve_index_link_format(cli_value: str | None) -> str`
- CLI: `obsidian-wiki index [VAULT] [--check] [--link-format {wikilink,markdown}]`
- Consumes: `rebuild_index(..., link_format=...)` from Task 2

- [ ] **Step 1: Write failing CLI precedence tests**

Extend `_run` with `extra_env: dict[str, str] | None = None`, applying it after `HOME`, then add:

```python
def test_index_cli_link_format_precedence(tmp_path: Path) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md", title="Alpha")
    config_dir = home / ".obsidian-wiki"
    config_dir.mkdir(parents=True)
    (config_dir / "config").write_text("OBSIDIAN_LINK_FORMAT=markdown\n", encoding="utf-8")

    assert _run(home, "index", str(vault)).returncode == 0
    assert "[Alpha](concepts/alpha.md)" in (vault / "index.md").read_text()

    assert _run(
        home,
        "index",
        str(vault),
        extra_env={"OBSIDIAN_LINK_FORMAT": "wikilink"},
    ).returncode == 0
    assert "[[concepts/alpha]]" in (vault / "index.md").read_text()

    assert _run(
        home,
        "index",
        str(vault),
        "--link-format",
        "markdown",
        extra_env={"OBSIDIAN_LINK_FORMAT": "wikilink"},
    ).returncode == 0
    assert "[Alpha](concepts/alpha.md)" in (vault / "index.md").read_text()


def test_index_cli_rejects_invalid_configured_link_format(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _page(vault, "concepts/alpha.md")

    proc = _run(
        tmp_path / "home",
        "index",
        str(vault),
        extra_env={"OBSIDIAN_LINK_FORMAT": "invalid"},
    )

    assert proc.returncode == 1
    assert "invalid OBSIDIAN_LINK_FORMAT" in proc.stderr
    assert not (vault / "index.md").exists()
```

- [ ] **Step 2: Run precedence tests and verify RED**

```bash
uv run --no-project --python 3.12 --with pytest pytest tests/test_index_cmd.py -q
```

Expected: CLI output remains wikilink regardless of config and the invalid environment value does not fail.

- [ ] **Step 3: Implement resolution and parser option**

Add near `cmd_index`:

```python
_INDEX_LINK_FORMATS = frozenset({"wikilink", "markdown"})


def _resolve_index_link_format(cli_value: str | None) -> str:
    value = (
        cli_value
        or os.environ.get("OBSIDIAN_LINK_FORMAT", "")
        or _read_config_value("OBSIDIAN_LINK_FORMAT")
        or "wikilink"
    ).strip().lower()
    if value not in _INDEX_LINK_FORMATS:
        raise ValueError(
            "invalid OBSIDIAN_LINK_FORMAT: "
            f"{value!r}; expected wikilink or markdown"
        )
    return value
```

In `cmd_index`, resolve inside `try/except ValueError`, print `error: {exc}` to stderr, return 1, and call `rebuild_index(vault, check=args.check, link_format=link_format)`.

Add to the index subparser:

```python
ix.add_argument(
    "--link-format",
    choices=sorted(_INDEX_LINK_FORMATS),
    help="index link syntax (defaults to environment/config, then wikilink)",
)
```

- [ ] **Step 4: Run all index tests and verify GREEN**

```bash
uv run --no-project --python 3.12 --with pytest pytest tests/test_index_cmd.py -q
```

Expected: all tests pass with no warnings.

- [ ] **Step 5: Commit CLI behavior**

```bash
git add obsidian_wiki/cli.py tests/test_index_cmd.py
git commit -m "feat(cli): configure index link rendering"
```

---

### Task 4: Migrate Every Index-Writing Skill

**Files:**
- Modify: `.skills/llm-wiki/SKILL.md`
- Modify: `.skills/claude-history-ingest/SKILL.md`
- Modify: `.skills/codex-history-ingest/SKILL.md`
- Modify: `.skills/copilot-history-ingest/SKILL.md`
- Modify: `.skills/cross-linker/SKILL.md`
- Modify: `.skills/daily-update/SKILL.md`
- Modify: `.skills/hermes-history-ingest/SKILL.md`
- Modify: `.skills/openclaw-history-ingest/SKILL.md`
- Modify: `.skills/pi-history-ingest/SKILL.md`
- Modify: `.skills/tag-taxonomy/SKILL.md`
- Modify: `.skills/wiki-agent/SKILL.md`
- Modify: `.skills/wiki-capture/SKILL.md`
- Modify: `.skills/wiki-dedup/SKILL.md`
- Modify: `.skills/wiki-digest/SKILL.md`
- Modify: `.skills/wiki-import/SKILL.md`
- Modify: `.skills/wiki-ingest/SKILL.md`
- Modify: `.skills/wiki-research/SKILL.md`
- Modify: `.skills/wiki-stage-commit/SKILL.md`
- Modify: `.skills/wiki-synthesize/SKILL.md`
- Modify: `.skills/wiki-update/SKILL.md`
- Create: `tests/test_index_skill_integration_docs.py`

**Interfaces:**
- Canonical command: `obsidian-wiki index "$OBSIDIAN_VAULT_PATH" --link-format "$OBSIDIAN_LINK_FORMAT"`
- Canonical fallback sentence: `If the \`obsidian-wiki\` executable is unavailable, manually reconcile \`index.md\` using the format in \`llm-wiki/SKILL.md\`.`

- [ ] **Step 1: Write the failing documentation-contract test**

Create:

```python
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMMAND = 'obsidian-wiki index "$OBSIDIAN_VAULT_PATH" --link-format "$OBSIDIAN_LINK_FORMAT"'
FALLBACK = (
    "If the `obsidian-wiki` executable is unavailable, manually reconcile "
    "`index.md` using the format in `llm-wiki/SKILL.md`."
)
INDEX_WRITING_SKILLS = (
    "claude-history-ingest",
    "codex-history-ingest",
    "copilot-history-ingest",
    "cross-linker",
    "daily-update",
    "hermes-history-ingest",
    "openclaw-history-ingest",
    "pi-history-ingest",
    "tag-taxonomy",
    "wiki-agent",
    "wiki-capture",
    "wiki-dedup",
    "wiki-digest",
    "wiki-import",
    "wiki-ingest",
    "wiki-research",
    "wiki-stage-commit",
    "wiki-synthesize",
    "wiki-update",
)


@pytest.mark.parametrize("skill", INDEX_WRITING_SKILLS)
def test_index_writing_skills_use_deterministic_cli_with_fallback(skill: str) -> None:
    text = (ROOT / ".skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    assert COMMAND in text, skill
    assert FALLBACK in text, skill
    assert "OBSIDIAN_LINK_FORMAT" in text, skill


def test_llm_wiki_defines_the_deterministic_index_contract() -> None:
    text = (ROOT / ".skills/llm-wiki/SKILL.md").read_text(encoding="utf-8")
    assert "### Deterministic Index Refresh" in text
    assert COMMAND in text
    assert FALLBACK in text
```

- [ ] **Step 2: Run the contract test and verify RED**

```bash
uv run --no-project --python 3.12 --with pytest pytest tests/test_index_skill_integration_docs.py -q
```

Expected: all parameterized cases fail because no skill invokes the command yet.

- [ ] **Step 3: Add the canonical contract to llm-wiki**

Immediately after the `index.md` format rule, add:

````markdown
### Deterministic Index Refresh

After a workflow changes any visible wiki page's path, title, category, summary, or tags, rebuild the root index after all page writes succeed:

```bash
obsidian-wiki index "$OBSIDIAN_VAULT_PATH" --link-format "$OBSIDIAN_LINK_FORMAT"
```

If the `obsidian-wiki` executable is unavailable, manually reconcile `index.md` using the format in `llm-wiki/SKILL.md`.

If the executable exists but the command fails, report the failure and stop before claiming bookkeeping is complete. Do not use the manual fallback to hide a generator failure. Skip refresh during read-only, audit-only, dry-run, no-op, and staged-only flows that changed no visible page.
````

- [ ] **Step 4: Migrate the 19 write skills**

For each file in `INDEX_WRITING_SKILLS`:

1. Ensure its config-resolution step explicitly includes `OBSIDIAN_LINK_FORMAT` with default `wikilink`.
2. Replace the existing manual-only index instruction, or add a refresh immediately after visible page writes, with this exact block:

````markdown
**`index.md`** — After all visible page writes succeed, run:

```bash
obsidian-wiki index "$OBSIDIAN_VAULT_PATH" --link-format "$OBSIDIAN_LINK_FORMAT"
```

If the `obsidian-wiki` executable is unavailable, manually reconcile `index.md` using the format in `llm-wiki/SKILL.md`.
If the executable exists but the command fails, report the failure and stop before claiming bookkeeping is complete.
````

Apply these guards at the insertion point:

| Skill group | Insertion point and guard |
|---|---|
| Six `*-history-ingest` skills | Special-files step, after page writes and before log/hot completion; only when pages changed |
| `daily-update` | Replace Step 2 manual `find` reconciliation; run every maintenance cycle |
| `cross-linker` | Before Step 7; only if link application or page promotion wrote visible files |
| `tag-taxonomy` | After tag fixes; only outside audit mode and only when tags changed |
| `wiki-agent` | Step 7 before log/hot; only when pages were created or updated |
| `wiki-capture` | Full Mode Step 6 only; Quick Mode remains excluded |
| `wiki-dedup` | Step 5e after merge writes; Audit Mode remains excluded |
| `wiki-digest` | Save flow only; conversational digest mode remains read-only |
| `wiki-import` | Replace per-entry index mutation after created/merged pages are complete |
| `wiki-ingest` | Tracking-files step; skip staged-only runs with no visible-page writes |
| `wiki-research` | Special-files step after research pages are written |
| `wiki-stage-commit` | Once after the accepted batch, not once per file; skip all-rejected runs |
| `wiki-synthesize` | Step 7 after new synthesis pages are written |
| `wiki-update` | Replace the manual `Add entries` section; skip no-delta exits |

- [ ] **Step 5: Run contract and related documentation tests; verify GREEN**

```bash
uv run --no-project --python 3.12 --with pytest pytest \
  tests/test_index_skill_integration_docs.py \
  tests/test_inline_vault_targeting_docs.py \
  tests/test_wiki_narrate_docs.py -q
```

Expected: all tests pass; read-only and quick-mode exclusion wording remains intact.

- [ ] **Step 6: Commit skill integration**

```bash
git add .skills tests/test_index_skill_integration_docs.py
git commit -m "docs(skills): use deterministic index refresh"
```

---

### Task 5: Update User Documentation and Verify the Branch

**Files:**
- Modify: `README.md`
- Modify: `SETUP.md`
- Test: entire repository

**Interfaces:**
- Documents: `obsidian-wiki index --link-format markdown`
- Preserves: existing basic `obsidian-wiki index` and `--check` examples

- [ ] **Step 1: Add CLI documentation**

In the README CLI examples, add:

```markdown
obsidian-wiki index --link-format markdown  # emit root-relative Markdown links
```

Expand the index paragraph to state that entries use full vault-relative paths and frontmatter titles, and that flag precedence is CLI → environment → global config → wikilink.

In SETUP's command list, keep the existing index command and add one sentence that configured `OBSIDIAN_LINK_FORMAT` controls generated links unless `--link-format` overrides it.

- [ ] **Step 2: Run focused tests**

```bash
uv run --no-project --python 3.12 --with pytest pytest \
  tests/test_index_cmd.py \
  tests/test_index_skill_integration_docs.py -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Run the complete suite and diff checks**

```bash
git diff --check
uv run --no-project --python 3.12 --with pytest pytest -q
```

Expected: zero diff errors and the full suite passes.

- [ ] **Step 4: Verify the configured vault without writing**

Resolve `OBSIDIAN_VAULT_PATH`, read its `AGENTS.md`, then run:

```bash
obsidian-wiki index --check "$OBSIDIAN_VAULT_PATH"
```

An exit code of 1 is acceptable when the current index predates the deterministic format. Inspect the bounded diff and verify that generated entries retain full paths, frontmatter display titles, noncanonical category casing, and tags. Do not run a mutating rebuild against the user's vault.

- [ ] **Step 5: Verify upstream PR scope**

```bash
git fetch upstream main
git merge-tree $(git merge-base upstream/main HEAD) upstream/main HEAD | rg '^(<<<<<<<|=======|>>>>>>>)'
git diff --stat upstream/main...HEAD
git status --short --branch
```

Expected: no conflict markers, only design/plan docs plus index implementation, tests, user docs, and the enumerated skill instructions; no unrelated working-tree files.

- [ ] **Step 6: Commit documentation**

```bash
git add README.md SETUP.md docs/superpowers/plans/2026-07-15-cli-index-command.md
git commit -m "docs: document deterministic index rendering"
```

- [ ] **Step 7: Run final verification after the commit**

```bash
git diff --check HEAD^..HEAD
uv run --no-project --python 3.12 --with pytest pytest -q
git status --short --branch
```

Expected: full suite passes and the working tree is clean. Do not push or create the upstream PR until the user explicitly requests publication.
