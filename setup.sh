#!/bin/bash
#
# obsidian-wiki setup — configures skill discovery for all supported AI agents.
#
# Usage: bash setup.sh
#
# What it does:
#   1. Creates .env from .env.example (if not present)
#   2. Symlinks .skills/* into each agent's expected skills directory:
#      - .claude/skills/    (Claude Code)
#      - .cursor/skills/    (Cursor)
#      - .windsurf/skills/  (Windsurf)
#      - .agents/skills/    (Antigravity / generic agents)
#   3b. Symlinks skills globally into ~/.gemini/antigravity/skills/ (Gemini)
#   3c. Symlinks skills globally into ~/.codex/skills/ (Codex)
#   4. Prints a summary of what's ready
#
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/.skills"

# Symlink every skill in SKILLS_DIR into TARGET_DIR.
# Skips real directories to avoid data loss; updates stale symlinks.
install_skills() {
  local target_dir="$1"
  local label="$2"
  mkdir -p "$target_dir"
  for skill in "$SKILLS_DIR"/*/; do
    local skill_name link_path
    skill_name="$(basename "$skill")"
    link_path="$target_dir/$skill_name"
    if [ -L "$link_path" ]; then
      rm "$link_path"
    elif [ -d "$link_path" ]; then
      echo "⚠️   $link_path is a real directory, skipping symlink"
      continue
    fi
    ln -s "${skill%/}" "$link_path"
  done
  echo "✅  Installed global skills → $label"
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

# ── Step 1b: ~/.obsidian-wiki/config ─────────────────────────
GLOBAL_CONFIG_DIR="$HOME/.obsidian-wiki"
GLOBAL_CONFIG="$GLOBAL_CONFIG_DIR/config"
mkdir -p "$GLOBAL_CONFIG_DIR"

# Read vault path from .env if it's already set
VAULT_PATH=""
if [ -f "$SCRIPT_DIR/.env" ]; then
  # Strip quotes if present, but preserve the path (spaces or not)
  VAULT_PATH=$(grep -E '^OBSIDIAN_VAULT_PATH=' "$SCRIPT_DIR/.env" | cut -d'=' -f2- | sed 's/^"//;s/"$//')
fi

# If vault path is empty or placeholder, ask the user
if [ -z "$VAULT_PATH" ] || [ "$VAULT_PATH" = "/path/to/your/vault" ]; then
  echo ""
  read -p "  Where is your Obsidian vault? (absolute path): " VAULT_PATH
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
echo "✅  Global config written to ~/.obsidian-wiki/config"

# ── Step 2: Symlink skills into agent directories ─────────────
AGENT_DIRS=(
  ".claude/skills"
  ".cursor/skills"
  ".windsurf/skills"
  ".agents/skills"
)

for agent_dir in "${AGENT_DIRS[@]}"; do
  install_skills "$SCRIPT_DIR/$agent_dir" "$agent_dir/"
done

# ── Step 3: Install global skills ────────────────────────────
# ~/.claude/skills gets only the two portable skills (usable from any project)
GLOBAL_SKILL_DIR="$HOME/.claude/skills"
mkdir -p "$GLOBAL_SKILL_DIR"
for skill_name in "wiki-update" "wiki-query"; do
  link_path="$GLOBAL_SKILL_DIR/$skill_name"
  if [ -L "$link_path" ]; then
    rm "$link_path"
  elif [ -d "$link_path" ]; then
    echo "⚠️   $link_path is a real directory, skipping symlink"
    continue
  fi
  ln -s "$SKILLS_DIR/$skill_name" "$link_path"
done
echo "✅  Installed global skills → ~/.claude/skills/ (wiki-update, wiki-query)"

# Steps 3b–3d: Install all skills for Gemini, Codex, and generic agents
# OpenClaw discovers skills from ~/.agents/skills/ (per docs.openclaw.ai/skills);
# that path also covers OpenCode, Factory Droid, and any AGENTS.md-aware agent.
install_skills "$HOME/.gemini/antigravity/skills" "~/.gemini/antigravity/skills/"
install_skills "$HOME/.codex/skills"              "~/.codex/skills/"
install_skills "$HOME/.agents/skills"             "~/.agents/skills/ (OpenClaw + generic)"

# ── Step 4: Summary ──────────────────────────────────────────
SKILL_COUNT=$(echo "$SKILLS_DIR"/*/  | tr ' ' '\n' | grep -c /)

echo ""
echo "───────────────────────────────────────────────────"
echo " Setup complete!"
echo ""
echo " Skills found:    $SKILL_COUNT"
echo " Agents ready:    Claude Code, Cursor, Windsurf, Antigravity/Gemini, Codex, OpenClaw"
echo ""
echo " Bootstrap files:"
echo "   CLAUDE.md       → Claude Code"
echo "   GEMINI.md       → Gemini / Antigravity"
echo "   AGENTS.md       → Codex, OpenClaw, OpenCode, Droid"
echo "   .cursor/rules/  → Cursor"
echo "   .windsurf/rules/ → Windsurf"
echo "   .github/copilot-instructions.md → GitHub Copilot"
echo ""
echo " Next steps:"
echo "   1. Open this project in your agent"
echo "   2. Say: \"Set up my wiki\""
echo ""
echo " From any other project:"
echo "   /wiki-update    → sync knowledge into your vault"
echo "   /wiki-query    → ask questions against your wiki"
echo "───────────────────────────────────────────────────"
echo ""
