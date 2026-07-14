# Deterministic Index Command — PR-Readiness Design

## Goal

Make `feat/cli-index-command` safe and complete enough for an upstream pull request by ensuring that `obsidian-wiki index` produces unambiguous, configuration-aware index entries and that every skill which mutates wiki pages uses the command instead of relying only on manual index edits.

## Scope

This change covers four areas:

1. Correct deterministic rendering in `obsidian_wiki/index.py`.
2. Explicit link-format selection in the CLI.
3. Migration of every skill that instructs an agent to add, remove, or update `index.md` entries.
4. Regression and documentation-contract tests.

Read-only skills that only consult `index.md`, and skills that explicitly must not update it, remain unchanged.

## Index Data Model

The existing lint frontmatter parser remains the source of page metadata. It will expose enough structured metadata for index generation without breaking current lint consumers:

- vault-relative page path;
- frontmatter title, falling back to the filename stem;
- raw category label;
- parsed tag list supporting both inline YAML (`tags: [a, b]`) and block-list YAML;
- summary.

Index grouping uses a normalized lowercase category key. Canonical singular aliases map to their plural categories. Canonical categories retain the documented order and headings: Concepts, Entities, Skills, References, Synthesis, Journal, Projects. For noncanonical categories, the renderer preserves a deterministic original spelling selected from the page metadata instead of applying title case, so an existing category such as `AI` does not become `Ai`.

Entries sort by normalized vault-relative path. This remains stable when pages in different directories share a filename.

## Link Rendering

Every entry uses the complete vault-relative path, without `.md`, as its identity.

For `wikilink` mode:

```markdown
- [[projects/alpha/shared|Alpha Shared]] — Summary. ( #alpha)
```

The display alias is included when the frontmatter title differs from the filename stem. A page whose title and stem are identical may use the shorter `[[projects/alpha/shared]]` form.

For `markdown` mode:

```markdown
- [Alpha Shared](projects/alpha/shared.md) — Summary. ( #alpha)
```

The root `index.md` makes these paths naturally vault-relative. Both modes preserve the existing summary and `( #tag)` formatting contract.

Accepted link formats are exactly `wikilink` and `markdown`. Invalid values fail with a clear CLI error instead of silently choosing a format.

## CLI Contract

`obsidian-wiki index` gains:

```text
--link-format {wikilink,markdown}
```

Resolution precedence is:

1. explicit `--link-format`;
2. `OBSIDIAN_LINK_FORMAT` from the process environment;
3. `OBSIDIAN_LINK_FORMAT` from `~/.obsidian-wiki/config`;
4. `wikilink`.

The selected value is passed explicitly into `rebuild_index`. The Python API keeps `wikilink` as its default for backward compatibility.

`--check` remains read-only. It returns zero when the existing file exactly matches generated output and nonzero with a bounded unified diff when stale. Normal rebuilds only write when content differs.

## Skill Migration

`llm-wiki` will define one canonical "Deterministic Index Refresh" procedure. Every skill that creates, modifies, deletes, merges, promotes, or archives knowledge pages will invoke the CLI after its page writes:

```bash
obsidian-wiki index "$OBSIDIAN_VAULT_PATH" --link-format "$OBSIDIAN_LINK_FORMAT"
```

Each migrated skill must resolve `OBSIDIAN_LINK_FORMAT` alongside `OBSIDIAN_VAULT_PATH` before reaching this step.

Fallback behavior is narrow:

- If the `obsidian-wiki` executable is unavailable, manually reconcile `index.md` using the format in `llm-wiki` so non-CLI installations remain functional.
- If the executable exists but the command fails, report the failure and stop the workflow's bookkeeping completion; do not silently fall back and hide a generator error.
- Do not run the command during read-only, audit-only, dry-run, no-op, or staged-only flows that have not changed visible vault pages.

A documentation-contract test will maintain an explicit list of index-writing skills and require each to contain the deterministic command and fallback instruction. This prevents future skills from drifting back to manual-only maintenance.

## Error Handling

- Missing or invalid vault paths continue to use the shared CLI vault resolver.
- Invalid link formats return a concise error on stderr and a nonzero exit code.
- Frontmatter without a title, category, summary, or tags uses the existing fallbacks without crashing.
- Duplicate filename stems remain safe because link targets include their full paths.
- A failed index refresh never rewrites `index.md` partially; generation completes in memory before the existing write step.

## Testing

Tests will be written before implementation for each missing behavior:

1. Wikilinks use full paths and frontmatter display titles.
2. Same-stem pages in different directories produce distinct targets.
3. Markdown mode emits root-relative `.md` links.
4. CLI flag, environment, global config, and default precedence select the expected format.
5. Invalid configured formats fail clearly.
6. Inline and block-list YAML tags render identically.
7. Noncanonical category casing is preserved deterministically.
8. `--check` remains read-only.
9. Every index-writing skill contains the CLI invocation and fallback contract.
10. The complete repository test suite passes, `git diff --check` is clean, and the branch merges cleanly with current `upstream/main`.

The final verification will also run `obsidian-wiki index --check` against the configured vault without writing it and inspect the proposed diff for path, title, category, and tag regressions.

## Non-Goals

- Reformatting unrelated skill prose.
- Reorganizing or modifying pages in the user's configured vault.
- Adding third-party YAML or Markdown dependencies.
- Changing `index.md` into a full-text or semantic search index.
- Automatically committing, pushing, or opening the upstream PR before explicit user approval.
