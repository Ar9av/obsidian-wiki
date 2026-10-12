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
- Existing stamps are not touched. Converting a vault's history is a separate, previewable command, decided on its own.

## Considered Options

- **An `OBSIDIAN_TIMEZONE` variable in `.env` / the profile.** Rejected. The memory writers take a vault path, not a config; the zone would have to be threaded through a dozen signatures or kept as process-global state, and the Python API and the Docker server would each need their own resolution. Two `.env` files pointing at one vault could also disagree. The frontmatter key is resolvable from the vault path alone.
- **Module-level `set_timezone()`.** Rejected: hidden state, and two `Memory` objects for two vaults in one process would share it.
- **Reading the host's local zone.** Rejected: a vault shared between a laptop and a server would get two clocks again.
- **Converting the existing stamps as part of this change.** Deferred to its own command with a preview and a backup; this change is additive and leaves every byte of an unconfigured vault as it was.

## Compatibility

- Unconfigured vaults see no change in any output.
- Every parser in the tree (`trust.py`, `temporal.py`, the log-line regex, `session_graph.py`) already accepts offset forms, so a vault that adopts a zone keeps linting and sorting correctly beside its older `Z` stamps.
- `memory status --json` gains a `timezone` field; `memory now --json` is new.
