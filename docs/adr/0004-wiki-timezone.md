---
status: accepted
---

# One clock per vault: `timezone:` in `index.md`

Every stamp the memory writer produced was UTC in the `Z` spelling, and every bare date was the UTC calendar day. For an owner west of Greenwich that files an evening's work under tomorrow's date, and it puts two clocks in one vault the moment a skill writes a local stamp into a page beside the writer's UTC one. The fix is one clock, chosen per vault.

## Decision

- The zone is the `timezone:` key in the frontmatter of the root `index.md`, an IANA name (`America/Detroit`). It lives in the file it governs, like `index_folder_hubs` (#272): it travels with the vault and applies to the CLI, the server, and the Python API, whichever `.env` or profile the caller resolved. `rebuild_index` preserves the frontmatter, so the key survives every rebuild.
- `obsidian_wiki.clock` is the only producer of stamps. `stamp()` gives the full form with the zone's own offset for that instant (`2026-10-10T14:40:37-04:00`), `today()` the calendar day in the zone, `compact()` the backup-directory form. Every writer in `memory.py` (log, hot, adoption record, profile, todos, migration backup) and the page writers in `client.py` and `server.py` go through it.
- No key means no change: UTC, `Z` spelling, byte for byte what the writer wrote before. `UTC` as a value means the same.
- A zone name Python cannot resolve raises `TimezoneError` (a `ValueError`) and the write does not happen. A typo must not quietly write UTC under a local label.
- `obsidian-wiki memory now` (`--date` for the bare day) prints the stamp a skill should write into `created:` / `updated:` / `lifecycle_changed:`. Skills are prompts; one command replaces a per-vault `TZ=… date` incantation they would otherwise have to carry. `memory status` reports the zone in use.
- Setting the key does not touch existing stamps. `obsidian-wiki memory timezone [ZONE]` converts them on request: preview by default (exit 2 while there is work, like `--check`), `--apply` backs every changed file up under `_archives/pre-timezone-migration-<stamp>/`, records the key, rewrites under the memory lock, and logs one `TIMEZONE` line. Each stamp is re-rendered by its own instant, so DST is right per stamp and a second run is a no-op. Bare dates and naive stamps cannot be converted without guessing and are counted instead; `_archives/`, `_raw/_archived/`, instruction files and non-Markdown ledgers are never touched; `--skip GLOB` protects quoted source text.

## Considered Options

- **An `OBSIDIAN_TIMEZONE` variable in `.env` / the profile.** Rejected. The memory writers take a vault path, not a config; the zone would have to be threaded through a dozen signatures or kept as process-global state, and the Python API and the Docker server would each need their own resolution. Two `.env` files pointing at one vault could also disagree. The frontmatter key is resolvable from the vault path alone.
- **Module-level `set_timezone()`.** Rejected: hidden state, and two `Memory` objects for two vaults in one process would share it.
- **Reading the host's local zone.** Rejected: a vault shared between a laptop and a server would get two clocks again.
- **Converting the existing stamps when the key is set.** Rejected: setting a key must stay additive. Conversion is its own command with a preview and a backup, so the owner sees the per-file list before anything is rewritten.
- **Converting only frontmatter keys and the memory files.** Rejected: a vault's ledgers and reports carry stamps in prose too, and a half-converted page still has two clocks. Bodies convert; `--skip` covers the rare file that quotes a source's stamp.
- **Guessing a zone for naive stamps and bare dates.** Rejected: a bare date shifted by a guessed time can land on the wrong day, which is the defect this fixes.

## Compatibility

- Unconfigured vaults see no change in any output.
- Every parser in the tree (`trust.py`, `temporal.py`, the log-line regex, `session_graph.py`) already accepts offset forms, so a vault that adopts a zone keeps linting and sorting correctly beside its older `Z` stamps.
- `memory status --json` gains a `timezone` field; `memory now --json` is new.
