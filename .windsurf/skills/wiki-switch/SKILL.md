---
name: wiki-switch
description: >
  Switch between multiple Obsidian wiki vault profiles. Use this skill when the user says
  "/wiki-switch NAME", "switch to my work wiki", "switch vault", "change wiki", "which wiki am I on",
  "list my wikis", "show my vaults", "create a new vault config", or "add a new wiki profile".
  The skill manages named config files at ~/.obsidian-wiki/config.NAME and activates one by
  symlinking it to ~/.obsidian-wiki/config.
---

# Wiki Switch — Manage Multiple Vault Profiles

Each vault is a complete config file at `~/.obsidian-wiki/config.<name>`. The active vault is
whichever file `~/.obsidian-wiki/config` symlinks to. Switching vaults means re-pointing that symlink.

## Dispatch

Parse the invocation and route to the right section:

| Invocation | Action |
|---|---|
| `/wiki-switch <name>` | → **Switch** |
| `/wiki-switch list` | → **List** |
| `/wiki-switch show [name]` | → **Show** |
| `/wiki-switch new <name>` | → **New** |
| `/wiki-switch` (no args) | → **List** (treat as list) |

---

## Switch (default action)

Activate a named vault profile.

1. Verify `~/.obsidian-wiki/config.<name>` exists. If not, tell the user the vault doesn't exist and list what's available (run **List**).
2. Run:
   ```bash
   ln -sf ~/.obsidian-wiki/config.<name> ~/.obsidian-wiki/config
   ```
3. Read `OBSIDIAN_VAULT_PATH` from the newly active config.
4. Confirm to the user:
   ```
   Switched to vault: <name>
   Vault path: <value of OBSIDIAN_VAULT_PATH from the config>
   ```

---

## List

Show all registered vault profiles and which is active.

1. Find all files matching `~/.obsidian-wiki/config.*` (exclude `config` itself — that's the symlink).
2. Resolve the current symlink target: `readlink ~/.obsidian-wiki/config`
3. For each config file, read the first non-empty comment line (lines starting with `#`) as a human description of the vault. Fall back to the file's suffix as the label if no comment exists.
4. Display:
   ```
   Vaults:
     personal   My personal research wiki    ← active
     work       Work projects wiki
   ```
   Mark the active one with `← active`. If the symlink is broken or `config` doesn't exist, show `(none active)`.

---

## Show

Print the full config for a vault.

- If a name is given, read `~/.obsidian-wiki/config.<name>`.
- If no name given, read `~/.obsidian-wiki/config` (the active vault).
- If the file doesn't exist, tell the user and list what's available.
- Print the file contents verbatim (redact any lines containing `API_KEY` or `SECRET` — show `***` instead of the value).

---

## New

Scaffold a new vault config from the current active config as a template.

1. Check `~/.obsidian-wiki/config.<name>` doesn't already exist. Abort if it does.
2. Copy the active config:
   ```bash
   cp ~/.obsidian-wiki/config ~/.obsidian-wiki/config.<name>
   ```
3. Read the copied config. Config files use `# --- Section name ---` comment headers to group fields into sections (e.g., `# --- Vault-specific ---`, `# --- Vault-independent ---`, `# --- Secrets ---`). Use these sections to determine what to ask about:
   - Fields in sections labeled "vault-specific", "paths", or similar → ask the user for new values
   - Fields in sections labeled "vault-independent", "global", "shared" → keep as-is (copy over unchanged)
   - Fields in sections labeled "secrets" → ask if the new vault uses the same credentials or different ones
   - If there are no section headers, present all fields and let the user decide which to change
4. Ask the user for updated values for the vault-specific fields. Use the current values as visible defaults — the user only needs to supply what differs.
5. Write the updated values into `~/.obsidian-wiki/config.<name>`.
6. Update the top comment line to describe the new vault (e.g., `# Obsidian Wiki — <name> vault`).
7. Confirm:
   ```
   Created: ~/.obsidian-wiki/config.<name>
   Run `/wiki-switch <name>` to activate it, then run `wiki-setup` to initialise the new vault.
   ```
   Do not switch automatically — let the user decide when to activate.
