---
name: wiki-update
description: >
  Sync the current project's knowledge into the Obsidian wiki. Use this skill from any project
  when the user says "update wiki", "sync to wiki", "save this to my wiki", "update obsidian",
  asks to extract a specific module, concept, command, feature, workflow, or subsystem, or
  wants to distill what they've been working on into their knowledge base. This cross-project
  skill pushes project-level or fine-grained knowledge from wherever you are into the vault.
---

# Wiki Update — Sync Any Project to Your Wiki

You are distilling knowledge from the current project into the user's Obsidian wiki. This skill works from any project directory, not just the obsidian-wiki repo.

## Before You Start

1. Read `~/.obsidian-wiki/config` to get:
   - `OBSIDIAN_VAULT_PATH` — where the wiki lives
   - `OBSIDIAN_WIKI_REPO` — where the obsidian-wiki repo is cloned (for reading other skills if needed)
2. If `~/.obsidian-wiki/config` doesn't exist, tell the user to run `bash setup.sh` from their obsidian-wiki repo first.
3. Read `$OBSIDIAN_VAULT_PATH/.manifest.json` to check if this project has been synced before.
4. Read `$OBSIDIAN_VAULT_PATH/index.md` to know what the wiki already contains.
5. Identify the requested sync mode:
   - **Project sync** — the user asked to sync/update the whole current project.
   - **Focused extraction** — the user named an abstract module, concept, command, feature, workflow, subsystem, behavior, package, folder, or component to extract in finer detail.

## Step 1: Understand the Project

Figure out what this project is by scanning the current working directory:

- `README.md`, docs/, any markdown files
- Source structure (frameworks, languages, key abstractions)
- `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml` or whatever defines the project
- Git log (focus on commit messages that signal decisions, not "fix typo" stuff)
- Claude memory files if they exist (`.claude/` in the project)

Derive a clean project name from the directory name.

## Step 2: Build, Load, or Refresh the Project-Local Index

The project index is the orientation layer for all future fine-grained extraction. It is especially important for projects that will not receive more commits but still need additional focused distillation.

The index belongs in the source project directory, not in the Obsidian vault. If the project has no local convention, create:

```
<source_cwd>/.wiki-index/
├── project-index.md                  ← semantic map for future focused extraction
├── project-structure.md              ← source tree, entry points, boundaries
└── modules/
    └── <module-or-topic-slug>.md      ← optional focused extraction notes/status
```

On the first sync for a project, create `project-index.md` and `project-structure.md` before doing deeper knowledge extraction. Do not add these local index files to the vault's `index.md`, and do not treat them as wiki pages. They are source-project orientation files that help future runs avoid rediscovering the same structure.

If the project has already been synced, read these local index files first, before scanning code:

- `<source_cwd>/.wiki-index/project-index.md`
- `<source_cwd>/.wiki-index/project-structure.md`
- Any focused extraction notes in `<source_cwd>/.wiki-index/modules/`
- Any wiki pages already listed for this project in `.manifest.json`

Every successful `wiki-update` run should refresh the local index opportunistically. Do this for full project syncs and focused extractions. Preserve stable existing notes, but update anything the run just clarified:

- New or renamed source roots, entry points, commands, tests, docs, and tooling surfaces.
- Topic rows, relevant paths, related wiki pages, and extraction status.
- Cross-topic relationships, data/control flow, and next extraction candidates.
- Ambiguity notes when the scan finds conflicting structure, duplicated patterns, or migration-in-progress signals.

### `project-index.md`

Use this local index file as a compact semantic map, not as a dump of every file. It should include:

- What the project does and the primary user/developer workflows.
- A focused extraction map table with: topic/module name, abstraction type, relevant paths, purpose, entry points, key dependencies, related wiki pages, extraction status.
- Known relationships and data/control flow across topics, even when the implementation is distributed across multiple directories.
- Important terms used by the project, linked to existing or new wiki pages.
- A short "next extraction candidates" section for modules, commands, workflows, or concepts that deserve deeper future passes.

A "module" in this skill is an abstract extraction target, not necessarily a directory or package. It can be:

- A command implementation spread across CLI parsing, handlers, services, tests, and docs.
- A distributed feature or workflow whose logic lives in several modules.
- A subsystem, domain concept, protocol, data flow, integration, or lifecycle.
- A conventional source folder or component, when that is the natural boundary.

### `project-structure.md`

Use this local index file to capture structure that helps a future agent aim its scan quickly:

- Top-level directory tree, excluding generated, vendored, cache, build, and dependency directories.
- Source roots, test roots, configuration files, docs, and runtime entry points.
- Module boundaries, package boundaries, and obvious ownership splits.
- Build/test/tooling surfaces and where to look for each.
- Any ambiguity, duplicated patterns, or migration-in-progress signals. Mark those as ambiguous.

Keep both local index files short enough to be loaded at the start of future focused extraction. Prefer stable paths, concise purpose summaries, and links to deeper pages over large file listings.

## Step 3: Compute the Delta or Requested Scope

Check `.manifest.json` for this project:

- **First time?** Full scan. Everything is new. Build the project-local index before creating detailed concept/skill/reference pages in the vault.
- **Synced before and the user asked for focused extraction?** Do not stop just because `last_commit_synced` equals `HEAD` or there are no new commits. Use `.wiki-index/project-index.md` and `.wiki-index/project-structure.md` to locate the requested abstraction, then scan only the relevant files, docs, tests, and related existing wiki pages.
- **Synced before and no focused scope was requested?** Look at `last_commit_synced` if commits exist. Only consider what changed since then. Use `git log <last_commit>..HEAD --oneline` to see what's new.
- **No useful git history or the project will not receive more commits?** Treat `.manifest.json`, `.wiki-index/project-index.md`, and focused extraction status as the source of progress tracking. Continue when the user requests a not-yet-extracted topic.

For focused extraction, update or add a topic/module record in `.manifest.json` and, when useful, a local note in `.wiki-index/modules/`. Track the topic name, abstraction type, requested scope, relevant paths, files scanned, pages produced, last extracted timestamp, and extraction status (`indexed`, `partial`, or `distilled`).

If nothing meaningful changed since last sync and the user did not request a specific focused extraction, tell the user and stop.

## Step 4: Decide What to Distill

This is the core question from Karpathy's pattern: **what would you want to know about this project if you came back in 3 months with zero context?**

For focused extraction, narrow that question: **what would you want to know about this abstraction if you had the project-local index but had never traced this topic through the implementation?**

Worth distilling:

- Architecture decisions and *why* they were made
- Process chains: triggers, inputs, stages, state transitions, side effects, outputs, and failure paths.
- Implementation methods at the design level: how the project realizes a workflow across modules, services, commands, data stores, or external systems.
- Patterns discovered while building (things you'd Google again otherwise)
- What tools, services, APIs the project depends on and how they're wired together
- Key abstractions, how they connect, what the mental model is
- Trade-offs that were evaluated, what was picked and why
- Things learned while building that aren't obvious from reading the code
- For focused extraction: public API or command surface, internal responsibilities, entry points, collaborators, invariants, extension points, failure modes, and non-obvious coupling across files or modules

Not worth distilling:

- File listings, boilerplate, config that's obvious
- Individual bug fixes with no broader lesson
- Dependency versions, lock file contents
- Implementation details the code already says clearly
- Variable names, function names, class names, and call-by-call traces unless they are necessary to explain a public API, command surface, extension point, or key abstraction
- Code snippets, pseudocode, or line-by-line walkthroughs when a diagram and prose explanation can explain the same implementation method
- Routine changes anyone could read from the diff
- Exhaustive function inventories, private helper catalogs, edge-case lists, and source-order walkthroughs. Keep those in the source code or local `.wiki-index/` notes unless they are essential to the mental model.

The heuristic: **if reading the codebase answers the question, don't wiki it. If you'd have to re-derive the reasoning by reading git blame across 20 commits, wiki it.**

## Step 5: Distill into Wiki Pages

### Project-specific knowledge

Goes under `$VAULT/projects/<project-name>/`:

```
projects/<project-name>/
├── <project-name>.md                 ← project overview (named after the project, NOT _project.md)
├── concepts/                         ← project-specific ideas, architectures
├── skills/                           ← project-specific how-tos, patterns
└── references/
    └── ...                           ← project-specific source summaries
```

The overview page (`<project-name>.md`) should have:
- What the project is (one paragraph)
- Key concepts and how they connect
- Links to project-specific and global wiki pages

For a focused extraction, create or update pages that match the knowledge type:

- `projects/<project-name>/concepts/<topic-or-concept>.md` for architecture, responsibilities, mental models, and distributed behavior.
- `projects/<project-name>/skills/<topic-task>.md` for reusable procedures and how-tos around that topic.
- `projects/<project-name>/references/<topic-source>.md` for factual summaries of APIs, commands, configs, schemas, or file groups.

Also update the project-local `.wiki-index/project-index.md` so the topic row points to the new wiki pages and reflects the latest extraction status.

### Global knowledge

Things that aren't project-specific go in the global categories:

| What you found | Where it goes |
|---|---|
| A general concept learned | `concepts/` |
| A reusable pattern or technique | `skills/` |
| A tool/service/person | `entities/` |
| Cross-project analysis | `synthesis/` |

### Writing style: abstraction first

The wiki is for understanding the project's process chains and implementation methods, not for reading the code through the wiki. Write at the highest useful abstraction level:

- Default to concise mental-model pages. A focused concept/project page should usually be 40-120 lines with 3-6 short sections, not a long implementation report.
- Start with the core model in 2-5 sentences: what this subsystem is, why it exists, and what makes the implementation worth remembering.
- Prefer simple bullets over dense prose. Each bullet should preserve one reusable idea, invariant, coupling, or tradeoff.
- Prefer domain concepts, responsibilities, state, data flow, control flow, and handoff points over code identifiers.
- Avoid naming private variables, helper functions, internal classes, and file-local details unless they are essential to the explanation.
- When an identifier is necessary, introduce it in project terms. Keep identifier glossaries short and only include names a future reader must recognize.
- Do not paste code unless the exact syntax is the knowledge being preserved. If syntax is necessary, keep the snippet short and explain the concept before the code.
- For focused extraction, explain the distributed implementation simply: trigger, main participants, state/data movement, outputs, and important failure or cleanup paths.
- Preserve important ambiguity and non-obvious coupling, but do not enumerate every edge case unless the user asked for a deep dive.

Use this compression test before saving: if a reader can rediscover the detail by opening one obvious source file, leave it out. If they would need to reconstruct the mental model across several files, keep it.

### Diagrams

Use diagrams when explaining process chains, workflows, command implementations, distributed features, state transitions, or cross-module behavior. Prefer Mermaid because Obsidian renders it directly.

Include at least one diagram for any focused extraction whose main value is understanding a flow or implementation chain. Pick the diagram type that fits the knowledge:

- `flowchart` for process chains, command execution, data flow, and module handoffs.
- `sequenceDiagram` for request/response, CLI-to-service, agent/tool, or multi-system interactions.
- `stateDiagram-v2` for lifecycles, status transitions, retry/failure behavior, or staged processing.

Put the diagram before dense prose when it helps orientation. Keep node labels conceptual, and only use function or variable names in labels if they have already been explained.
Prefer one compact diagram per focused page. Add more only when each diagram answers a different question.

### Page format

Every vault page needs YAML frontmatter. Local `.wiki-index/` files are project orientation files and do not need this frontmatter unless the project has its own convention.

```markdown
---
title: >-
    Page Title
category: concepts
tags: [tag1, tag2]
sources: [projects/<project-name>]
summary: >-
    One or two sentences (≤200 chars) describing what this page covers.
provenance:
  extracted: 0.6
  inferred: 0.35
  ambiguous: 0.05
created: TIMESTAMP
updated: TIMESTAMP
---

Use folded scalar syntax (summary: >-) for title and summary to keep frontmatter parser-safe across punctuation (:, #, quotes) without escaping rules.
Keep the title and summary contents indented by two spaces under summary: >-.

# Page Title

- A fact the codebase or a doc actually states.
- A reason the design works this way. ^[inferred]

Use [[wikilinks]] to connect to other pages.
```

**Write a `summary:` frontmatter field** on every new/updated page (1–2 sentences, ≤200 chars), using `>-` folded style. For project sync, a good summary answers "what does this page tell me about the project I wouldn't guess from its title?" This field powers cheap retrieval by `wiki-query`.

**Apply provenance markers** per `llm-wiki` (Provenance Markers section). For project sync specifically:

- **Extracted** — anything visible in the code, config, or a doc/commit message: file structure, dependencies, function signatures, what a file does.
- **Inferred** — *why* a decision was made, design rationale, trade-offs, "the team chose X because Y" — unless a commit message, doc, or ADR states it explicitly.
- **Ambiguous** — when the code and docs disagree, or when there's clearly an in-progress migration with two patterns living side by side.

Compute the rough fractions and write the `provenance:` block on every new/updated page.

### Updating vs creating

- If a page already exists in the vault, **merge** new information into it. Don't create duplicates.
- If you're adding to an existing page, update the `updated` timestamp and add the new source.
- Check `index.md` to see what's already there before creating anything new.

## Step 6: Cross-link

After creating/updating pages:

- Add `[[wikilinks]]` from new pages to existing related pages
- Add `[[wikilinks]]` from existing pages back to the new ones where relevant
- Link the project overview to all project-specific pages and relevant global pages
- For focused extraction, link the topic page back to `[[<project-name>]]`, related sibling topics, and any global concept/entity pages it depends on. Do not link to local `.wiki-index/` files with wikilinks; they are not vault pages.

## Step 7: Update Tracking

### Update `.manifest.json`

Add or update this project's entry:

```json
{
  "projects": {
    "<project-name>": {
      "source_cwd": "/absolute/path/to/project",
      "last_synced": "TIMESTAMP",
      "last_commit_synced": "abc123f",
      "local_index": {
        "dir": "/absolute/path/to/project/.wiki-index",
        "files": [
          ".wiki-index/project-index.md",
          ".wiki-index/project-structure.md"
        ]
      },
      "topics": {
        "<topic-or-module-name>": {
          "abstraction_type": "command|workflow|feature|subsystem|concept|folder|component|package|other",
          "requested_scope": "module, concept, command, feature, workflow, subsystem, behavior, package, folder, or component",
          "paths": ["src/module", "docs/module.md"],
          "status": "indexed|partial|distilled",
          "last_extracted": "TIMESTAMP",
          "files_scanned": ["src/module/file.ext"],
          "local_notes": [".wiki-index/modules/<topic-or-module-slug>.md"],
          "pages_in_vault": ["projects/<project-name>/concepts/<topic>.md"]
        }
      },
      "pages_in_vault": ["projects/<project-name>/<project-name>.md", "..."]
    }
  }
}
```

Keep `last_commit_synced` when git history exists, but do not rely on it as the only progress marker. For stable projects with no future commits, the project-local index, `topics` records, and page update timestamps are how future extraction avoids duplicating work.

### Refresh the project-local index

After each successful update, write the index changes back to `<source_cwd>/.wiki-index/`:

- Update `project-index.md` with newly discovered topics, changed extraction statuses, new related wiki pages, and revised next extraction candidates.
- Update `project-structure.md` when the run discovers structure, entry points, commands, tests, docs, or tooling surfaces that were missing or stale.
- For focused extraction, create or update `.wiki-index/modules/<topic-or-module-slug>.md` with a short status note: requested scope, abstraction type, paths scanned, pages produced, remaining questions, and last extracted timestamp.
- Keep these files concise and orientation-focused. They are for future extraction planning, not for long-term knowledge storage; long-term distilled knowledge belongs in the vault pages.

### Update `index.md`

Add entries for any new pages created.

### Update `log.md`

Append:
```
- [TIMESTAMP] WIKI_UPDATE project=<project-name> pages_updated=X pages_created=Y source_cwd=/path/to/project
```

### Update `hot.md`

Read `$OBSIDIAN_VAULT_PATH/hot.md` (create from the template in `wiki-ingest` if missing). Rewrite **Recent Activity** with what was just synced — last 3 operations max. Update **Active Threads** if this project is an ongoing focus. Update **Key Takeaways** with the most important architectural insight or decision surfaced during this sync. Update `updated` timestamp.

Write conceptually: "Synced obsidian-wiki — added wiki-capture and wiki-research skills, core new capabilities are autonomous web research and conversation capture."

## Tips

- **Be aggressive about merging.** If the project uses React Server Components, don't create a new page if `concepts/react-server-components.md` already exists. Update the existing one and add this project as a source.
- **Consult the tag taxonomy.** Read `$VAULT/_meta/taxonomy.md` if it exists, and use canonical tags.
- **Don't copy code.** Distill the *knowledge*, not the implementation. "This project uses a debounced search pattern with 300ms delay" is useful. Pasting the actual debounce function is not.
- **Project overview is the anchor.** The `<project-name>.md` file is what you'd read to get oriented. Make it good.
