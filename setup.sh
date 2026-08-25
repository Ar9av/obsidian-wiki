#!/bin/bash
#
# obsidian-wiki setup — configures skill discovery for all supported AI agents.
#
# Usage: bash setup.sh
#
# What it does:
#   1. Creates .env from .env.example (if not present)
#   2. Writes the global config (XDG-style, under ~/.config/obsidian-wiki by
#      default; legacy ~/.obsidian-wiki is honored if it already exists) so
#      skills work from any project
#   3. Symlinks .skills/* into each agent's expected skills directory:
#      Project-local:
#        - .claude/skills/        (Claude Code)
#        - .cursor/skills/        (Cursor)
#        - .windsurf/skills/      (Windsurf)
#        - .agents/skills/        (AGENTS.md-aware agents, generic)
#        - .kiro/skills/          (Kiro IDE/CLI)
#      Global:
#        - ~/.claude/skills/      (Claude Code, portable skills only)
#        - ~/.gemini/skills/      (Gemini CLI)
#        - ~/.codex/skills/       (Codex)
#        - ~/.hermes/skills/      (Hermes)
#        - ~/.openclaw/skills/    (OpenClaw)
#        - ~/.copilot/skills/     (GitHub Copilot CLI)
#        - ~/.trae/skills/        (Trae)
#        - ~/.trae-cn/skills/     (Trae CN)
#        - ~/.kiro/skills/        (Kiro CLI)
#        - ~/.agents/skills/      (OpenCode, Aider, Factory Droid, generic)
#   4. Bootstraps AGENTS.md aliases (CLAUDE.md, GEMINI.md, .hermes.md)
#   5. Prints a summary of what's ready
#
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/.skills"

# install_skills <target_dir> <label> [relative|absolute] [skill-subset...]
# "relative" requires target_dir under $SCRIPT_DIR and emits ../-prefixed
# targets matching the committed symlinks. Extra args restrict the install
# to a named subset of skills (e.g. portable-only into ~/.claude/skills).
install_skills() {
  local target_dir="$1"
  local label="$2"
  local mode="${3:-absolute}"
  shift 3 || shift $#
  local subset=("$@")  # empty = install all

  case "$mode" in
    relative|absolute) ;;
    *) echo "install_skills: bad mode '$mode' (want relative|absolute)" >&2; exit 1 ;;
  esac

  local rel_prefix=""
  if [ "$mode" = "relative" ]; then
    # Strip $SCRIPT_DIR prefix; if it doesn't match, target is outside the
    # repo and "relative" isn't meaningful — bail rather than emit a wrong link.
    local rel="${target_dir#"$SCRIPT_DIR"/}"
    if [ "$rel" = "$target_dir" ]; then
      echo "install_skills: relative mode requires target under \$SCRIPT_DIR ($target_dir)" >&2
      exit 1
    fi
    # One ../ per path component in $rel; e.g. .claude/skills → 2 components → ../../
    local slashes="${rel//[^\/]/}"
    local depth=$(( ${#slashes} + 1 )) i
    for (( i=0; i<depth; i++ )); do rel_prefix="../$rel_prefix"; done
  fi

  mkdir -p "$target_dir"
  for skill in "$SKILLS_DIR"/*/; do
    local skill_name link_path link_target
    skill_name="$(basename "$skill")"
    if [ ${#subset[@]} -gt 0 ]; then
      local match=0 want
      for want in "${subset[@]}"; do [ "$want" = "$skill_name" ] && match=1 && break; done
      [ "$match" = 1 ] || continue
    fi
    link_path="$target_dir/$skill_name"
    if [ "$mode" = "relative" ]; then
      link_target="${rel_prefix}.skills/$skill_name"
    else
      link_target="${skill%/}"
    fi
    if [ -L "$link_path" ]; then
      rm "$link_path"
    elif [ -d "$link_path" ]; then
      echo "⚠️   $link_path is a real directory, skipping symlink"
      continue
    elif [ -f "$link_path" ]; then
      # Git on Windows without core.symlinks=true writes committed symlinks
      # as regular files containing the target path. Replace with a real symlink.
      rm "$link_path"
    fi
    ln -s "$link_target" "$link_path"
    # Sanity check: every skill ships a SKILL.md, so a working symlink resolves it.
    [ -e "$link_path/SKILL.md" ] || { echo "install_skills: broken link $link_path → $link_target" >&2; exit 1; }
  done
  echo "✅  Installed skills → $label"
}

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║         obsidian-wiki — Agent Setup              ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Step 1: .env ──────────────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
  cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
  echo "✅  Created .env from .env.example"
  echo "    → Edit .env and set OBSIDIAN_VAULT_PATH before using skills."
else
  echo "✅  .env already exists"
fi

# ── Step 1b: global config ────────────────────────────────────
# XDG-style location by default; installs that already have the legacy
# ~/.obsidian-wiki keep using it so upgrading doesn't strand a working config.
XDG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/obsidian-wiki"
LEGACY_DIR="$HOME/.obsidian-wiki"
if [ -d "$LEGACY_DIR" ] && [ ! -e "$XDG_DIR" ]; then
  GLOBAL_CONFIG_DIR="$LEGACY_DIR"
else
  GLOBAL_CONFIG_DIR="$XDG_DIR"
fi
GLOBAL_CONFIG="$GLOBAL_CONFIG_DIR/config"
mkdir -p "$GLOBAL_CONFIG_DIR"

WRITING_PROFILE="$GLOBAL_CONFIG_DIR/WRITING.md"
WRITING_TEMPLATE="$SKILLS_DIR/llm-wiki/references/WRITING.md"
if [ ! -e "$WRITING_PROFILE" ]; then
  cp "$WRITING_TEMPLATE" "$WRITING_PROFILE"
fi

# Read vault path from .env if it's already set
VAULT_PATH=""
if [ -f "$SCRIPT_DIR/.env" ]; then
  # Strip quotes if present, but preserve the path (spaces or not)
  VAULT_PATH=$(grep -E '^OBSIDIAN_VAULT_PATH=' "$SCRIPT_DIR/.env" | cut -d'=' -f2- | sed 's/^"//;s/"$//')
fi

# If vault path is empty or placeholder, ask the user
if [ -z "$VAULT_PATH" ] || [ "$VAULT_PATH" = "/path/to/your/vault" ]; then
  echo ""
  read -p "  Where is your Obsidian vault? (absolute path): " VAULT_PATH || true
  if [ -n "$VAULT_PATH" ]; then
    # Escape the path for sed: replace '/' with '\/' and '"' with '\"'
    ESCAPED_PATH=$(printf '%s\n' "$VAULT_PATH" | sed -e 's/[\/&]/\\&/g' -e 's/"/\\"/g')
    # Update .env with quoted path to preserve spaces
    sed -i.bak "s|^OBSIDIAN_VAULT_PATH=.*|OBSIDIAN_VAULT_PATH=\"$ESCAPED_PATH\"|" "$SCRIPT_DIR/.env"
    rm -f "$SCRIPT_DIR/.env.bak"
  fi
fi

# Write global config with quoted path (preserves spaces)
cat > "$GLOBAL_CONFIG" <<EOF
OBSIDIAN_VAULT_PATH="$VAULT_PATH"
OBSIDIAN_WIKI_REPO="$SCRIPT_DIR"
EOF
echo "✅  Global config written to $GLOBAL_CONFIG"

# ── Step 1c: Bootstrap symlinks ──────────────────────────────
# .hermes.md → AGENTS.md  (Hermes resolves .hermes.md before AGENTS.md;
# a symlink keeps a single source of truth)
HERMES_BOOTSTRAP="$SCRIPT_DIR/.hermes.md"
if [ -L "$HERMES_BOOTSTRAP" ]; then
  rm "$HERMES_BOOTSTRAP"
elif [ -f "$HERMES_BOOTSTRAP" ]; then
  echo "⚠️   .hermes.md is a regular file, replacing with symlink"
  rm "$HERMES_BOOTSTRAP"
fi
ln -s AGENTS.md "$HERMES_BOOTSTRAP"
echo "✅  .hermes.md → AGENTS.md"

# ── Step 2: Symlink skills into agent directories ─────────────
# Project-local skill dirs. Each of these is where the matching agent looks
# for skills scoped to this repo.
AGENT_DIRS=(
  ".claude/skills"
  ".cursor/skills"
  ".windsurf/skills"
  ".agents/skills"
  ".pi/skills"         # Pi coding agent
  ".kiro/skills"        # Kiro IDE/CLI (paired with .kiro/steering/obsidian-wiki.md)
)

for agent_dir in "${AGENT_DIRS[@]}"; do
  install_skills "$SCRIPT_DIR/$agent_dir" "$agent_dir/" relative
done

# ── Step 3: Install global skills ────────────────────────────
# ~/.claude/skills gets only the portable skills (usable from any project).
install_skills "$HOME/.claude/skills" "~/.claude/skills/ (portable wiki skills)" absolute wiki-update wiki-query wiki-context-pack

# Steps 3b–3j: Install all skills for every supported agent.
# OpenClaw discovers skills from ~/.agents/skills/ (per docs.openclaw.ai/skills);
# that path also covers OpenCode, Factory Droid, Aider, and any AGENTS.md-aware
# agent. Platforms that have a dedicated skills dir get their own symlink tree
# so discovery works regardless of whether the user relies on AGENTS.md.
install_skills "$HOME/.gemini/skills"             "~/.gemini/skills/ (Gemini CLI)"
install_skills "$HOME/.gemini/antigravity/skills" "~/.gemini/antigravity/skills/ (Antigravity, legacy)"
install_skills "$HOME/.codex/skills"              "~/.codex/skills/"
install_skills "$HOME/.hermes/skills"             "~/.hermes/skills/ (Hermes default)"
# Hermes: active named profile (if $HERMES_HOME points to a non-default location)
if [ -n "$HERMES_HOME" ] && [ "$HERMES_HOME" != "$HOME/.hermes" ]; then
  install_skills "$HERMES_HOME/skills" "$HERMES_HOME/skills/ (Hermes active profile: $(basename "$HERMES_HOME"))"
fi
# Hermes: all named profiles under ~/.hermes/profiles/
if [ -d "$HOME/.hermes/profiles" ]; then
  for _hermes_profile_dir in "$HOME/.hermes/profiles"/*/; do
    [ -d "$_hermes_profile_dir" ] || continue
    _hermes_profile_name="$(basename "$_hermes_profile_dir")"
    # Skip if already handled via $HERMES_HOME above
    if [ -n "$HERMES_HOME" ] && [ "$HERMES_HOME" = "${_hermes_profile_dir%/}" ]; then
      continue
    fi
    install_skills "${_hermes_profile_dir}skills" \
      "~/.hermes/profiles/${_hermes_profile_name}/skills/ (Hermes profile: ${_hermes_profile_name})"
  done
fi
install_skills "$HOME/.openclaw/skills"           "~/.openclaw/skills/ (OpenClaw managed)"
install_skills "$HOME/.copilot/skills"            "~/.copilot/skills/ (GitHub Copilot CLI)"
install_skills "$HOME/.trae/skills"               "~/.trae/skills/ (Trae)"
install_skills "$HOME/.trae-cn/skills"            "~/.trae-cn/skills/ (Trae CN)"
install_skills "$HOME/.kiro/skills"               "~/.kiro/skills/ (Kiro CLI)"
install_skills "$HOME/.pi/agent/skills"           "~/.pi/agent/skills/ (Pi)"
install_skills "$HOME/.agents/skills"             "~/.agents/skills/ (OpenCode, Aider, Droid, generic)"

# ── Step 4: GitHub sync (optional) ───────────────────────────
# Delegates to obsidian_wiki/sync.py — the same module `obsidian-wiki
# setup`/`sync-setup` (pip/uv installs) use — so this flow can't drift out of
# sync with the Python CLI again (see #153). Always runs the CLI straight out
# of this checkout via PYTHONPATH rather than trusting a possibly-older
# `obsidian-wiki` already on PATH (which may predate this subcommand); falls
# back to that installed binary only if python3 isn't available at all.
SYNC_CONFIGURED=false
VAULT_REMOTE=""

run_owiki() {
  if command -v python3 &>/dev/null; then
    PYTHONPATH="$SCRIPT_DIR" python3 -m obsidian_wiki.cli "$@"
  elif command -v obsidian-wiki &>/dev/null; then
    obsidian-wiki "$@"
  else
    echo "⚠️  Skipping GitHub sync setup — neither 'python3' nor 'obsidian-wiki' found on PATH." >&2
    return 1
  fi
}

echo ""
read -p "  Set up GitHub sync for your vault? [y/N]: " SETUP_SYNC || true
if [[ "$SETUP_SYNC" =~ ^[Yy]$ ]]; then
  read -p "  GitHub repo URL (e.g. https://github.com/you/my-wiki.git): " VAULT_REMOTE || true
  if [ -n "$VAULT_REMOTE" ] && [ -n "$VAULT_PATH" ] && [ -d "$VAULT_PATH" ]; then
    if run_owiki sync-setup "$VAULT_REMOTE" --vault "$VAULT_PATH"; then
      SYNC_CONFIGURED=true

      # Offer shell alias
      echo ""
      read -p "  Add 'wiki-sync' alias to your shell? [Y/n]: " ADD_ALIAS || true
      if [[ ! "$ADD_ALIAS" =~ ^[Nn]$ ]]; then
        SHELL_RC=""
        [ -f "$HOME/.zshrc" ]  && SHELL_RC="$HOME/.zshrc"
        [ -z "$SHELL_RC" ] && [ -f "$HOME/.bashrc" ] && SHELL_RC="$HOME/.bashrc"
        if [ -n "$SHELL_RC" ]; then
          if ! grep -q "wiki-sync" "$SHELL_RC"; then
            printf '\n# wiki-sync — push Obsidian vault to GitHub\nalias wiki-sync='"'"'obsidian-wiki sync'"'"'\n' >> "$SHELL_RC"
            echo "✅  Added wiki-sync alias to $SHELL_RC"
            echo "    → Run: source $SHELL_RC  (or open a new terminal)"
          else
            echo "    ℹ️  wiki-sync alias already in $SHELL_RC"
          fi
        fi
      fi

      # Offer hourly cron
      echo ""
      read -p "  Enable hourly auto-sync (cron)? [y/N]: " ADD_CRON || true
      if [[ "$ADD_CRON" =~ ^[Yy]$ ]]; then
        # Same preference as run_owiki: PYTHONPATH into this checkout over a
        # possibly-older installed binary. If this checkout is later moved or
        # deleted, re-run setup.sh (or edit the crontab) to point it elsewhere.
        SYNC_CMD="$(command -v python3 &>/dev/null && echo "env PYTHONPATH=$SCRIPT_DIR python3 -m obsidian_wiki.cli sync" || echo "obsidian-wiki sync")"
        CRON_LINE="0 * * * * $SYNC_CMD --vault $VAULT_PATH >> $GLOBAL_CONFIG_DIR/sync.log 2>&1"
        ( crontab -l 2>/dev/null; echo "$CRON_LINE" ) | sort -u | crontab -
        echo "✅  Hourly cron installed  (logs: $GLOBAL_CONFIG_DIR/sync.log)"
      fi
    fi
  fi
fi

# ── Step 5: Summary ──────────────────────────────────────────
SKILL_COUNT=$(echo "$SKILLS_DIR"/*/  | tr ' ' '\n' | grep -c /)

echo ""
echo "───────────────────────────────────────────────────"
echo " Setup complete!"
echo ""
echo " Skills found:    $SKILL_COUNT"
echo " Writing profile:  $WRITING_PROFILE"
echo " Agents ready:    Claude Code, Cursor, Windsurf, Gemini CLI, Antigravity,"
echo "                  Codex, Hermes, OpenClaw, OpenCode, Aider, Factory Droid,"
echo "                  Trae, Trae CN, Kiro, Pi, GitHub Copilot (CLI + VS Code Chat)"
if $SYNC_CONFIGURED; then
echo " GitHub sync:     wiki-sync  (obsidian-wiki sync)"
fi
echo ""
echo " Bootstrap files:"
echo "   CLAUDE.md                            → Claude Code"
echo "   GEMINI.md                            → Gemini / Antigravity"
echo "   AGENTS.md                            → Codex, OpenClaw, OpenCode, Aider, Droid, Trae, Hermes, Pi"
echo "   .hermes.md                           → Hermes (symlink → AGENTS.md)"
echo "   .cursor/rules/obsidian-wiki.mdc      → Cursor (alwaysApply)"
echo "   .windsurf/rules/obsidian-wiki.md     → Windsurf (always-on)"
echo "   .kiro/steering/obsidian-wiki.md      → Kiro (inclusion: always)"
echo "   .agent/rules/obsidian-wiki.md        → Google Antigravity (alwaysApply)"
echo "   .agent/workflows/obsidian-wiki.md    → Google Antigravity (slash commands)"
echo "   .github/copilot-instructions.md      → GitHub Copilot (VS Code Chat)"
echo ""
echo " Next steps:"
echo "   1. Open this project in your agent"
echo "   2. Say: \"Set up my wiki\""
echo ""
echo " From any other project:"
echo "   /wiki-update    → sync knowledge into your vault"
echo "   /wiki-query     → ask questions against your wiki"
echo "   /wiki-context-pack → compile bounded context for another agent"
if $SYNC_CONFIGURED; then
echo "   wiki-sync       → push all vault changes to GitHub"
fi
echo "───────────────────────────────────────────────────"
echo ""
