---
name: code-understand
description: >
  Build a ranked, citation-backed focus map of a codebase — the files and symbols an
  architecture actually hangs on — using CodeGraph when available and a dependency-free
  builtin (regex AST extraction + `rg` cross-file references) otherwise. Use this any time
  you (the coding agent) need to orient in an unfamiliar or large codebase before making a
  change: the user says "help me understand this codebase", "what's load-bearing here",
  "what would break if I change X", "who calls this", "map out this project's architecture",
  or you're about to touch code you haven't read yet and want to know what matters before
  scanning everything by hand. This is the same extractor `wiki-update` Step 3b uses
  internally — this skill exposes it directly so any agent session can call it on demand,
  not just during a wiki sync.
---

# Code Understand — On-Demand Architecture Focus Map

You are about to work in a codebase you don't fully know yet. Instead of grepping around or
reading files at random, ask the local extractor for a **focus map**: the ranked symbols the
architecture hangs on, each with a `file:line` citation and evidence type. Read only what it
points at — this is a map, not a substitute for reading the actual code it cites.

## When to reach for this

- Before editing an unfamiliar module — see what calls it and what it calls before changing
  its shape.
- The user asks "how does X work", "what's the impact of changing Y", "who else uses this
  function" for a codebase, not the wiki.
- You're about to do a large refactor and want a ranked list of load-bearing files instead of
  reading the whole tree.
- You already have a diff or a set of changed files and want to know their blast radius before
  finishing the change.

Not for: summarizing what a project *does* for the wiki (that's `wiki-update` Step 3b, which
calls this same command as part of a bigger sync flow) — use this skill directly only when you
need the focus map for your own immediate work, not to persist knowledge.

## Running it

```bash
obsidian-wiki code-understand --project <dir> [--backend auto|builtin|codegraph] \
    [--changed <file>...] [--since <sha>] [--max-symbols N] [--pretty]
```

- `--project` — defaults to the current directory.
- No `--changed`/`--since` — seeds from every tracked file (full-project scan).
- `--changed <file>` (repeatable) — seed from specific files you already know are relevant
  (e.g. files in the diff you're about to make).
- `--since <sha>` — seed from everything changed since a git ref (e.g. `--since HEAD~5` or a
  base branch).
- `--backend` — `auto` (default) uses CodeGraph when installed, falls back to the builtin
  extractor otherwise; force `builtin` for the dependency-free path, or `codegraph` to require
  the enhanced backend (fails loudly if it's not installed rather than silently degrading).
- `--max-symbols` — cap the focus map size (default 50); keep this small for a quick
  orientation pass, raise it for a thorough one.

**GUARD:** if the command is unavailable or errors, skip it and fall back to your normal
exploration (grep/read) — this is an accelerant, not a dependency. Don't block work on it.

## Reading the output

1. **Evidence type matters.** When `backend: codegraph`, focus-map entries are structural
   facts (real call-graph edges) — cite them directly. When `backend: builtin`, `defines`/
   `imports`/`changed-file` entries are facts, but `rg-reference` entries are text-match
   evidence only — open the file and confirm before treating it as a real relationship.
2. **Open what it cites, nothing else first.** The focus map tells you *where* to read; it
   never contains source bodies. Go read those `file:line` locations before forming an opinion
   on the architecture.
3. **Cite it in your own output.** If you explain the architecture back to the user or write
   it into a PR description/commit message, keep the `(file:lines)` citations from the focus
   map or from the source you opened — don't assert structure without a pointer to it.
4. **It's a cache, not a deliverable.** Never write the raw JSON or `.codegraph/` into the
   wiki vault, a PR description, or committed docs — it's a disposable sidecar in the project
   repo (git-ignored). Re-run it fresh next time rather than treating old output as durable.

## If CodeGraph isn't installed

`auto`/`builtin` still work with zero setup (uses the regex AST extractor + `rg`). If you want
the enhanced cross-file call-graph evidence and the user is fine with installing something:

```bash
npm install -g @colbymchenry/codegraph
```

or point `CODE_UNDERSTANDING_CODEGRAPH_BIN` at an existing binary. Never install without the
user's go-ahead — ask first, then re-run the command.

Check `obsidian-wiki doctor --project <dir>` for the `code-understanding.*` capability lines
(`builtin`, `rg`, `codegraph`, `codegraph-index`, `codegraph-fresh`) to see what's available
before deciding which backend to request explicitly.
