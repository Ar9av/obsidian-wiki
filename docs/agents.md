# Agent Compatibility

Works with **any AI coding agent that can read files**. `setup.sh` and `obsidian-wiki setup` handle skill discovery for each one automatically.

Each agent has its own convention for discovering skills. Setup symlinks the canonical `.skills/` directory into each agent's expected location — you write skills once, every agent can use them.

## Matrix

| Agent | Bootstrap | Skills Directory | Slash Commands |
|---|---|---|---|
| **[Claude Code](https://claude.ai/code)** | `CLAUDE.md` | `.claude/skills/` + `~/.claude/skills/` | ✅ `/wiki-ingest`, `/wiki-status`, etc. |
| **[Cursor](https://cursor.com)** | `.cursor/rules/obsidian-wiki.mdc` | `.cursor/skills/` | ✅ `/wiki-ingest`, `/wiki-status`, etc. |
| **[Windsurf](https://windsurf.com)** | `.windsurf/rules/obsidian-wiki.md` | `.windsurf/skills/` | ✅ via Cascade |
| **[Codex (OpenAI)](https://openai.com/codex)** | `AGENTS.md` | `~/.codex/skills/` | `$wiki-ingest` (Codex uses `$`) |
| **[Gemini CLI](https://github.com/google-gemini/gemini-cli)** | `GEMINI.md` | `~/.gemini/skills/` | ✅ `/wiki-ingest`, `/wiki-query`, etc. |
| **[Google Antigravity](https://antigravity.google)** | `.agent/rules/` + `.agent/workflows/` | `.agents/skills/` | ✅ via workflows registry |
| **[Kiro IDE/CLI](https://kiro.dev)** | `.kiro/steering/obsidian-wiki.md` | `.kiro/skills/` + `~/.kiro/skills/` | ✅ `/wiki-ingest`, `/wiki-status`, etc. |
| **[Hermes](https://hermes-agent.nousresearch.com)** | `.hermes.md` | `~/.hermes/skills/` | ✅ `/wiki-history-ingest hermes`, etc. |
| **[OpenClaw](https://openclaw.ai)** | `AGENTS.md` | `~/.openclaw/skills/` + `~/.agents/skills/` | ✅ `/wiki-ingest`, `/wiki-history-ingest openclaw`, etc. |
| **[OpenCode](https://opencode.ai)** | `AGENTS.md` | `~/.agents/skills/` | ✅ `/wiki-ingest`, `/wiki-query`, etc. |
| **[Aider](https://aider.chat)** | `AGENTS.md` | `~/.agents/skills/` | Describe intent in chat |
| **[Factory Droid](https://factory.ai)** | `AGENTS.md` | `~/.agents/skills/` | ✅ `/wiki-ingest`, `/wiki-query`, etc. |
| **[Trae](https://trae.ai)** / **Trae CN** | `AGENTS.md` | `~/.trae/skills/` / `~/.trae-cn/skills/` | ✅ via Agent tool |
| **GitHub Copilot (VS Code)** | `.github/copilot-instructions.md` | — | Describe intent in chat |
| **GitHub Copilot (CLI)** | — | `~/.copilot/skills/` | ✅ `/wiki-ingest`, `/wiki-query`, etc. |
| **[Kilocode](https://kilo.ai/)** | `AGENTS.md` / `CLAUDE.md` | `.agents/skills/` + `.claude/skills/` | ✅ `/wiki-ingest`, `/wiki-status`, etc. |
| **[Pi](https://pi.dev)** | `AGENTS.md` | `.pi/skills/` + `~/.pi/agent/skills/` | ✅ `/wiki-ingest`, `/wiki-history-ingest pi`, etc. |

> Slash commands work in Claude Code, Cursor, Windsurf, and most CLI agents. Everywhere else, just describe what you want — the agent matches your intent against the skill descriptions.

Named-vault routing (`@work update wiki`) works in every agent above, because `@name` is documented in the shared skills and bootstrap context that all of them load.

## Manual setup

Only needed if you're not running `setup.sh` or `obsidian-wiki setup`.

<details>
<summary><b>Claude Code</b></summary>

Skills are auto-discovered from `.claude/skills/`. Either run `setup.sh` or copy `.skills/*` to `.claude/skills/`. The `CLAUDE.md` file at the repo root is automatically loaded as project context.

```bash
cd /path/to/obsidian-wiki && claude "set up my wiki"
```
</details>

<details>
<summary><b>Cursor</b></summary>

Skills are auto-discovered from `.cursor/skills/`. The `.cursor/rules/obsidian-wiki.mdc` file provides always-on context. Either run `setup.sh` or copy `.skills/*` to `.cursor/skills/`. Then type `/wiki-setup` in the chat.
</details>

<details>
<summary><b>Windsurf</b></summary>

Cascade reads rules from `.windsurf/rules/` and skills from `.windsurf/skills/`. Either run `setup.sh` or copy `.skills/*` to `.windsurf/skills/`. Then tell Cascade: "set up my wiki".
</details>

<details>
<summary><b>Codex</b></summary>

Reads `AGENTS.md` for project context. `setup.sh` installs skills globally to `~/.codex/skills/`. Either run `setup.sh` or manually symlink `.skills/*` to `~/.codex/skills/`.

```bash
cd /path/to/obsidian-wiki && codex "set up my wiki"
```
</details>

<details>
<summary><b>Gemini CLI</b></summary>

Reads `GEMINI.md` and discovers global skills from `~/.gemini/skills/`. Either run `setup.sh` or manually symlink `.skills/*` to `~/.gemini/skills/`.

```bash
cd /path/to/obsidian-wiki && gemini "set up my wiki"
```
</details>

<details>
<summary><b>Google Antigravity</b></summary>

Always-on via `.agent/rules/` + `.agent/workflows/`. `setup.sh` ships both files and symlinks skills into `.agents/skills/`. The legacy `~/.gemini/antigravity/skills/` path is also wired.
</details>

<details>
<summary><b>Kiro IDE/CLI</b></summary>

Always-on via `.kiro/steering/*.md` with `inclusion: always`. `setup.sh` symlinks `.skills/*` into both `.kiro/skills/` and `~/.kiro/skills/`. Invoke with `/wiki-ingest`, `/wiki-query`, etc.
</details>

<details>
<summary><b>OpenCode / Aider / Factory Droid / Trae</b></summary>

All read `AGENTS.md` at the repo root. `setup.sh` symlinks skills into `~/.agents/skills/` (shared discovery path). Trae also gets `~/.trae/skills/` and `~/.trae-cn/skills/`.
</details>

<details>
<summary><b>Hermes</b></summary>

Reads `.hermes.md` first, then falls back to `AGENTS.md`. Skills discovered from `~/.hermes/skills/`. Run `setup.sh` or manually symlink `.skills/*` there.

```bash
cd /path/to/obsidian-wiki && hermes "set up my wiki"
# Mine Hermes history into the wiki:
/wiki-history-ingest hermes
```
</details>

<details>
<summary><b>OpenClaw</b></summary>

Reads `AGENTS.md` (priority 10). Discovers skills from `~/.openclaw/skills/` and `~/.agents/skills/`. Skills auto-register as slash commands.

```bash
cd /path/to/obsidian-wiki && openclaw "set up my wiki"
# Mine OpenClaw history:
/wiki-history-ingest openclaw
```
</details>

<details>
<summary><b>GitHub Copilot</b></summary>

**VS Code Chat:** reads `.github/copilot-instructions.md`. Say "set up my wiki" in Copilot Chat.

**CLI:** discovers skills from `~/.copilot/skills/`. Run `setup.sh` or manually symlink `.skills/*` there.
</details>

<details>
<summary><b>Pi</b></summary>

Reads `AGENTS.md` (walking up from cwd). Discovers skills from `.pi/skills/`, `.agents/skills/`, and `~/.pi/agent/skills/`. Run `setup.sh` or manually symlink `.skills/*` to `~/.pi/agent/skills/`.

```bash
cd /path/to/obsidian-wiki && pi "set up my wiki"
# Mine Pi session history:
/wiki-history-ingest pi
```
</details>
