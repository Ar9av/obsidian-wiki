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
  VAULT_PATH=$(grep -E '^OBSIDIAN_VAULT_PATH=' "$SCRIPT_DIR/.env" | cut -d'=' -f2-)
fi

# If vault path is empty or placeholder, ask the user
if [ -z "$VAULT_PATH" ] || [ "$VAULT_PATH" = "/path/to/your/vault" ]; then
  echo ""
  read -p "  Where is your Obsidian vault? (absolute path): " VAULT_PATH
  if [ -n "$VAULT_PATH" ]; then
    # Update .env with the provided path
    sed -i.bak "s|^OBSIDIAN_VAULT_PATH=.*|OBSIDIAN_VAULT_PATH=$VAULT_PATH|" "$SCRIPT_DIR/.env"
    rm -f "$SCRIPT_DIR/.env.bak"
  fi
fi

# Write global config (repo path is just where we're running from)
cat > "$GLOBAL_CONFIG" <<EOF
OBSIDIAN_VAULT_PATH=$VAULT_PATH
OBSIDIAN_WIKI_REPO=$SCRIPT_DIR
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
  target="$SCRIPT_DIR/$agent_dir"
  mkdir -p "$target"

  for skill in "$SKILLS_DIR"/*/; do
    skill_name="$(basename "$skill")"
    link_path="$target/$skill_name"

    if [ -L "$link_path" ]; then
      # Already a symlink — update it
      rm "$link_path"
    elif [ -d "$link_path" ]; then
      # Real directory exists — skip to avoid data loss
      echo "⚠️   $agent_dir/$skill_name is a real directory, skipping symlink"
      continue
    fi

    ln -s "${skill%/}" "$link_path"
  done

  echo "✅  Symlinked skills → $agent_dir/"
done

# ── Step 3: Install global skills ────────────────────────────
# These are available from any project, not just this repo
GLOBAL_SKILLS=("wiki-update" "wiki-query")
GLOBAL_SKILL_DIR="$HOME/.claude/skills"
mkdir -p "$GLOBAL_SKILL_DIR"

for skill_name in "${GLOBAL_SKILLS[@]}"; do
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

# ── Step 3b: Install all skills globally for Gemini/Antigravity ──
GEMINI_SKILL_DIR="$HOME/.gemini/antigravity/skills"
mkdir -p "$GEMINI_SKILL_DIR"

for skill in "$SKILLS_DIR"/*/; do
  skill_name="$(basename "$skill")"
  link_path="$GEMINI_SKILL_DIR/$skill_name"
  if [ -L "$link_path" ]; then
    rm "$link_path"
  elif [ -d "$link_path" ]; then
    echo "⚠️   $link_path is a real directory, skipping symlink"
    continue
  fi
  ln -s "$skill" "$link_path"
done
echo "✅  Installed global skills → ~/.gemini/antigravity/skills/"

# ── Step 3c: Install all skills globally for Codex ───────────
CODEX_SKILL_DIR="$HOME/.codex/skills"
mkdir -p "$CODEX_SKILL_DIR"

for skill in "$SKILLS_DIR"/*/; do
  skill_name="$(basename "$skill")"
  link_path="$CODEX_SKILL_DIR/$skill_name"
  if [ -L "$link_path" ]; then
    rm "$link_path"
  elif [ -d "$link_path" ]; then
    echo "⚠️   $link_path is a real directory, skipping symlink"
    continue
  fi
  ln -s "$skill" "$link_path"
done
echo "✅  Installed global skills → ~/.codex/skills/"

# ── Step 3d: Install all skills globally for OpenClaw / generic agents ──
# OpenClaw discovers skills from ~/.agents/skills/ (per docs.openclaw.ai/skills).
# This path is also a generic standard for any agent following the AGENTS.md
# convention, so it covers OpenClaw, OpenCode, Factory Droid, etc.
AGENTS_SKILL_DIR="$HOME/.agents/skills"
mkdir -p "$AGENTS_SKILL_DIR"

for skill in "$SKILLS_DIR"/*/; do
  skill_name="$(basename "$skill")"
  link_path="$AGENTS_SKILL_DIR/$skill_name"
  if [ -L "$link_path" ]; then
    rm "$link_path"
  elif [ -d "$link_path" ]; then
    echo "⚠️   $link_path is a real directory, skipping symlink"
    continue
  fi
  ln -s "$skill" "$link_path"
done
echo "✅  Installed global skills → ~/.agents/skills/ (OpenClaw + generic)"

# ── Step 4: Summary ──────────────────────────────────────────
SKILL_COUNT=$(ls -d "$SKILLS_DIR"/*/ 2>/dev/null | wc -l | tr -d ' ')

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
