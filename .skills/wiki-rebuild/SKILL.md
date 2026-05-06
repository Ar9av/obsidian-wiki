---
name: wiki-rebuild
description: >
  Archive existing wiki knowledge and rebuild from scratch, or restore from a previous archive.
  Use this skill when the user wants to start fresh, rebuild the wiki from all sources, archive current
  knowledge before a major change, or restore an older version. Triggers on "rebuild the wiki",
  "start over", "archive and rebuild", "restore from archive", "nuke and repave", "clean rebuild".
  Also use when the wiki has drifted too far from sources and incremental fixes won't cut it.
---

# Wiki Rebuild — Archive, Rebuild, Restore

You are performing a destructive operation on the wiki. Always archive first, always confirm with the user before proceeding.

## Before You Start

1. **Resolve config** — follow the Config Resolution Protocol in `llm-wiki/SKILL.md` (walk up CWD for `.env` → `~/.obsidian-wiki/config` → prompt setup). This gives `OBSIDIAN_VAULT_PATH`
2. Read `.manifest.json` to understand current state
3. **Confirm the user's intent.** This skill supports three modes:
   - **Archive only** — snapshot current wiki, no rebuild
   - **Archive + Rebuild** — snapshot, then reprocess all sources from scratch
   - **Restore** — bring back a previous archive

## The Archive System

Archives live at `$OBSIDIAN_VAULT_PATH/_archives/`. Each archive is a timestamped directory containing a full copy of the wiki state at that point.

```
$OBSIDIAN_VAULT_PATH/
├── _archives/
│   ├── 2026-04-01T10-30-00Z/
│   │   ├── archive-meta.json
│   │   ├── concepts/
│   │   ├── entities/
│   │   ├── skills/
│   │   ├── references/
│   │   ├── synthesis/
│   │   ├── journal/
│   │   ├── projects/
│   │   ├── index.md
│   │   ├── log.md
│   │   └── .manifest.json
│   └── 2026-03-15T08-00-00Z/
│       └── ...
├── concepts/          ← live wiki
├── entities/
└── ...
```

### archive-meta.json

```json
{
  "archived_at": "2026-04-06T10:30:00Z",
  "reason": "rebuild",
  "total_pages": 87,
  "total_sources": 42,
  "total_projects": 6,
  "vault_path": "/Users/name/Knowledge",
  "manifest_snapshot": ".manifest.json"
}
```

## Mode 1: Archive Only

When the user wants to snapshot the current state without rebuilding.

### Steps:

1. Create archive directory: `_archives/YYYY-MM-DDTHH-MM-SSZ/`
2. Copy all category directories, `index.md`, `log.md`, `.manifest.json`, and `projects/` into the archive
3. Write `archive-meta.json` with reason `"snapshot"`
4. Append to `log.md`:
   ```
   - [TIMESTAMP] ARCHIVE reason="snapshot" pages=87 destination="_archives/2026-04-06T10-30-00Z"
   ```
5. Report: "Archived 87 pages. Current wiki is untouched."

## Mode 2: Archive + Rebuild

When the user wants to start fresh. This is the full sequence:

### Step 1: Archive current state

Same as Mode 1 above, but with reason `"rebuild"`.

### Step 2: Clear live wiki

Remove all content from the category directories (`concepts/`, `entities/`, `skills/`, etc.) and the `projects/` directory. Keep:
- `_archives/` (obviously)
- `.obsidian/` (Obsidian config)
- `.env` (if present in vault)

Reset `index.md` to the empty template. Reset `log.md` with just the rebuild entry. Delete `.manifest.json` (it'll be recreated during ingest).

### Step 3: Rebuild

Tell the user the vault is cleared and ready for a full re-ingest. They can now run:

1. `wiki-status` — to see all sources as "new"
2. `claude-history-ingest` — to reprocess Claude history
3. `codex-history-ingest` — to reprocess Codex session history
4. `wiki-ingest` — to reprocess documents
5. `data-ingest` — to reprocess any other data

Each of these will rebuild the manifest as they go.

**Important:** Don't run the ingest yourself automatically. The user should choose what to re-ingest and in what order. Some sources may no longer be relevant.

### Step 4: Log the rebuild

Append to `log.md`:
```
- [TIMESTAMP] REBUILD archived_to="_archives/2026-04-06T10-30-00Z" previous_pages=87
```

## Mode 3: Restore from Archive

When the user wants to go back to a previous state.

### Step 1: List available archives

Read `_archives/` directory. For each archive, read `archive-meta.json` and present:

```markdown
## Available Archives

| Date | Reason | Pages | Sources |
|---|---|---|---|
| 2026-04-06 10:30 | rebuild | 87 | 42 |
| 2026-03-15 08:00 | snapshot | 65 | 31 |
```

### Step 2: Confirm which archive to restore

Ask the user which archive they want. Warn them that restoring will overwrite the current live wiki.

### Step 3: Archive current state first

Before restoring, archive the current state (reason: `"pre-restore"`) so nothing is lost.

### Step 4: Restore

1. Clear the live wiki (same as Mode 2, Step 2)
2. Copy all content from the chosen archive back into the live wiki directories
3. Restore `index.md`, `log.md`, and `.manifest.json` from the archive
4. Append to `log.md`:
   ```
   - [TIMESTAMP] RESTORE from="_archives/2026-03-15T08-00-00Z" pages_restored=65
   ```

### Step 5: Report

Tell the user what was restored and suggest running `wiki-lint` to check for any issues with the restored state.

## Safety Rules

1. **Always archive before destructive operations.** No exceptions.
2. **Always confirm with the user** before clearing the live wiki.
3. **Never delete archives** unless the user explicitly asks. Archives are cheap insurance.
4. **The `.obsidian/` directory is sacred.** Never touch it during archive/rebuild/restore — it contains the user's Obsidian settings, plugins, and themes.
5. If something goes wrong mid-rebuild, the archive is there. Tell the user they can restore.
