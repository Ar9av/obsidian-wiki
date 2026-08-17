---
name: wiki-switch
description: >
  Switch between multiple Obsidian wiki vault profiles. Use this skill when the user says
  "/wiki-switch NAME", "switch to my work wiki", "switch vault", "change wiki", "which wiki am I on",
  "list my wikis", "show my vaults", "create a new vault config", or "add a new wiki profile".
  The skill manages named config files at <global config dir>/config.NAME and activates one by
  symlinking it to <global config dir>/config.
---

# Wiki Switch — Manage Multiple Vault Profiles

**Global config dir.** Every path below is relative to the global config dir, resolved per the
Config Resolution Protocol in `llm-wiki/SKILL.md`: `$XDG_CONFIG_HOME/obsidian-wiki` (default
`~/.config/obsidian-wiki`), or the legacy `~/.obsidian-wiki` if that already exists on disk. Resolve
it once per invocation with:

```bash
CONFIG_DIR="$( [[ -d "$HOME/.obsidian-wiki" && ! -e "${XDG_CONFIG_HOME:-$HOME/.config}/obsidian-wiki" ]] && echo "$HOME/.obsidian-wiki" || echo "${XDG_CONFIG_HOME:-$HOME/.config}/obsidian-wiki" )"
```

Each vault is a complete config file at `$CONFIG_DIR/config.<name>`. The active vault is
whichever file `$CONFIG_DIR/config` symlinks to. Switching vaults means re-pointing that symlink.

**Switch vs. inline targeting.** `/wiki-switch <name>` changes your **persistent default** (re-points
the symlink, affecting all future requests). To touch a different vault for just one request without
changing your default, use the inline **`@name`** override in any request (e.g. `@work save this`,
`wiki-query @personal about X`). The `@name` override is handled by the **Config Resolution Protocol**
in `llm-wiki/SKILL.md`, not by this skill — it resolves `$CONFIG_DIR/config.<name>` for that one
invocation and never re-points the symlink.

## Dispatch

Parse the invocation and route to the right section:

| Invocation | Action |
|---|---|
| `/wiki-switch <name>` | → **Switch** |
| `/wiki-switch list` | → **List** |
| `/wiki-switch show [name]` | → **Show** |
| `/wiki-switch new <name>` | → **New** |
| `/wiki-switch` (no args) | → **List** (treat as list) |
| `@<name> …` (inline, in any request) | → Not this skill — the **Config Resolution Protocol** resolves that vault for one invocation without re-pointing the symlink |

---

## Switch (default action)

Activate a named vault profile.

1. Verify `$CONFIG_DIR/config.<name>` exists. If not, tell the user the vault doesn't exist and list what's available (run **List**).
2. Run:
   ```bash
   ln -sf "$CONFIG_DIR/config.<name>" "$CONFIG_DIR/config"
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

1. Find all files matching `$CONFIG_DIR/config.*` (exclude `config` itself — that's the symlink).
2. Resolve the current symlink target: `readlink "$CONFIG_DIR/config"`
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

- If a name is given, read `$CONFIG_DIR/config.<name>`.
- If no name given, read `$CONFIG_DIR/config` (the active vault).
- If the file doesn't exist, tell the user and list what's available.
- Print the file contents verbatim (redact any lines containing `API_KEY` or `SECRET` — show `***` instead of the value).

---

## New

Scaffold a new vault config from the current active config as a template.

1. Check `$CONFIG_DIR/config.<name>` doesn't already exist. Abort if it does.
2. Copy the active config:
   ```bash
   cp "$CONFIG_DIR/config" "$CONFIG_DIR/config.<name>"
   ```
3. Read the copied config. Config files use `# --- Section name ---` comment headers to group fields into sections (e.g., `# --- Vault-specific ---`, `# --- Vault-independent ---`, `# --- Secrets ---`). Use these sections to determine what to ask about:
   - Fields in sections labeled "vault-specific", "paths", or similar → ask the user for new values
   - Fields in sections labeled "vault-independent", "global", "shared" → keep as-is (copy over unchanged)
   - Fields in sections labeled "secrets" → ask if the new vault uses the same credentials or different ones
   - If there are no section headers, present all fields and let the user decide which to change
4. Ask the user for updated values for the vault-specific fields. Use the current values as visible defaults — the user only needs to supply what differs.
5. Write the updated values into `$CONFIG_DIR/config.<name>`.
6. Update the top comment line to describe the new vault (e.g., `# Obsidian Wiki — <name> vault`).
7. Confirm:
   ```
   Created: $CONFIG_DIR/config.<name>
   Run `/wiki-switch <name>` to activate it, then run `wiki-setup` to initialise the new vault.
   ```
   Do not switch automatically — let the user decide when to activate.
