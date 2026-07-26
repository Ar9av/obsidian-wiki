# obsidian-wiki

<p align="center">
  <a href="https://deepwiki.com/Ar9av/obsidian-wiki"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" /></a>
  <a href="https://github.com/ar9av/obsidian-wiki/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome" /></a>
  <a href="https://x.com/_ar9av"><img src="https://img.shields.io/badge/@__ar9av-black?logo=x&logoColor=white" alt="X" /></a>
</p>

<p align="center">
  <img width="768" height="512" alt="obisidan-wiki" src="https://github.com/user-attachments/assets/b44cf63b-3197-4fb1-8e18-dbc9a39f27a7" />
</p>

[English](README.md) | 繁體中文

一個由 AI agent 陪你一起養大的**數位大腦**。它會記住你弄懂的事，把新知識連到你已經知道的內容，並在你提問時回答。

這個模式來自 Andrej Karpathy 的 [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)：把知識一次編譯成彼此連結的 markdown 檔案，並持續維護，而不是每次都問 LLM 同樣的問題，或每次都重新跑 RAG。Obsidian 是你觀看這個大腦的方式；AI agent 是你讓它成長的方式。

我們圍繞這個想法建立了一個框架。每個 skill 都是一個 markdown 檔案，任何 AI coding agent（Claude Code、Cursor、Windsurf、Pi 等）都能讀取並執行。把它指向一個 Obsidian vault，告訴它要記住什麼，這個 vault 就會變成你自己擁有的第二大腦。

## 快速開始

### 讓你的 agent 幫你設定

最快的路徑，不需要手動輸入命令。把這個 repo 交給你的 agent，然後說：

```text
https://github.com/Ar9av/obsidian-wiki — set up my wiki
```

agent 會讀取 repo 裡的 [`.skills/wiki-setup/SKILL.md`](.skills/wiki-setup/SKILL.md)，詢問你希望 vault 放在哪裡，然後初始化完整結構：資料夾、index、log、Obsidian config，以及可選的自動捕捉 hook。就是這樣；skill 本身就是設定指南。

任何能讀取檔案的 agent 都能這樣使用，包括 Claude Code、Cursor、Windsurf、Codex、Gemini CLI、Kiro 等。設定完成後，所有 wiki skills 會立刻可用。

### 透過 pip 安裝（推薦）

```bash
pip install obsidian-wiki
obsidian-wiki setup --vault /path/to/your/digital/brain
```

`obsidian-wiki setup` 會把設定寫到 `~/.obsidian-wiki/config`，並把所有 wiki skills 安裝到你的 AI agents（Claude Code、Cursor、Codex、Gemini、Hermes、Pi 等）。Skills 會 symlink 到已安裝的 package，所以 `pip install -U obsidian-wiki` 會在同一處升級它們；之後重新執行 `obsidian-wiki setup` 即可讓所有 agent 取得新 skills。接著在 agent 中開啟一個 project，說 **"set up my wiki"**。

```bash
obsidian-wiki list              # 列出內建 skills
obsidian-wiki info              # 顯示安裝路徑、版本與設定
obsidian-wiki doctor            # 檢查 config、vault 結構與已安裝 skills
obsidian-wiki query "rate limiting"  # 從終端查詢已設定的 vault
obsidian-wiki lint              # 檢查已設定 vault 的 broken links / metadata gaps
obsidian-wiki setup --project . # 也把 project-local skills + AGENTS.md 放到目前 repo
obsidian-wiki setup --copy      # 複製 skill 檔案，而不是 symlink
```

`OBSIDIAN_VAULT_PATH` 可以是任何你想存放數位大腦的目錄；它可以是新的空資料夾，也可以是既有的 Obsidian vault。省略 `--vault` 時會提示你輸入，或之後在 `~/.obsidian-wiki/config` 中設定。

### 本機 CLI 工具

Python package 也提供幾個用於檢查與維護的本機命令：

```bash
obsidian-wiki doctor --json
obsidian-wiki query "what do I know about MCP security?"
obsidian-wiki lint --strict
obsidian-wiki graph-query /path/to/vault "transformer architecture"
obsidian-wiki graph-analyse /path/to/vault --pretty
```

使用 `doctor` 找出破損設定、過期安裝或格式錯誤的 vault 狀態。當你想快速取得本機答案、不想透過 agent prompt 時，可以使用 `query` 與 `lint`。較低階的 `graph-query`、`graph-analyse`、`batch-plan`、`cache-*`、`ast-extract` 仍可用於自動化與除錯。

### 多個 Vault

你可以在 `~/.obsidian-wiki/config` 中保留一個預設 vault，也可以用 `/wiki-switch new work` 建立像 `~/.obsidian-wiki/config.work` 這樣的命名設定。從任何目錄都能用 `@name` 把單次請求導向命名 vault，例如 `@work update wiki` 或 `wiki-query @personal what do I know about MCP security`。`@name` override 只套用在該次請求，永遠不會改變預設 vault。

執行 `obsidian-wiki setup` 或 `setup.sh` 後，所有支援的 agent 都可以使用這個語法，因為共用 skills 與 always-on bootstrap files 都會指回相同的 Config Resolution Protocol。routing token 可用於寫入 skills（`@work update wiki`、`@research save this`）與讀取 skills（`wiki-query @personal what do I know about X`）。

### 透過 Skills CLI 安裝（已不推薦）

```bash
npx skills add Ar9av/obsidian-wiki
```

這只會把 markdown skills 安裝到目前 agent。它**不會**寫入 `~/.obsidian-wiki/config`、安裝 `~/.obsidian-wiki/sync.sh`，也不會接上 `obsidian-wiki setup` / `setup.sh` 會設定的全域 multi-agent bootstrap。

只有在你明確想要部分、agent-local 的安裝，並且願意自行管理 config 時，才使用這條路徑。若要完整設定，請使用 **透過 pip 安裝** 或 **透過 git clone 安裝**。

完整 skill 清單可在 [skills.sh/ar9av/obsidian-wiki](https://skills.sh/ar9av/obsidian-wiki) 瀏覽。

### 透過 git clone 安裝

```bash
git clone https://github.com/Ar9av/obsidian-wiki.git
cd obsidian-wiki
bash setup.sh
```

`setup.sh` 會詢問你的 vault（數位大腦）路徑，將設定寫入 `~/.obsidian-wiki/config`，把 skills symlink 到所有 agent，並全域安裝 `wiki-update`，讓你能從任何 project 使用它。

在你的 agent 中開啟 project，說 **"set up my wiki"**。就完成了。

## Agent 相容性

只要是能讀檔的 **AI coding agent** 都能使用，包括 Claude Code、Cursor、Windsurf、Pi、Codex、Gemini CLI、Kiro 等。`setup.sh` 會自動處理每個 agent 的 skill discovery。

<details>
<summary><b>支援的 agents 與手動設定說明</b></summary>

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

> 每個 agent 都有自己的 skill discovery 慣例。`setup.sh` 會把 canonical `.skills/` 目錄 symlink 到每個 agent 預期的位置。你只需要寫一次 skills，每個 agent 都能使用。命名 vault routing 也是同樣道理：`@name` 記錄在共用 skills 與 bootstrap context 裡，所以 Claude Code、Cursor、Windsurf、Codex、Gemini、Kiro、Hermes、OpenClaw、Copilot CLI、Pi，以及一般讀取 `AGENTS.md` 的 agents 都會從同一份指令取得它。

### 手動設定（如果你偏好 `setup.sh`）

<details>
<summary>Claude Code</summary>

Skills 會從 `.claude/skills/` 自動 discovery。執行 `setup.sh`，或把 `.skills/*` 複製到 `.claude/skills/`。repo root 的 `CLAUDE.md` 會自動作為 project context 載入。

```bash
cd /path/to/obsidian-wiki && claude "set up my wiki"
```
</details>

<details>
<summary>Cursor</summary>

Skills 會從 `.cursor/skills/` 自動 discovery。`.cursor/rules/obsidian-wiki.mdc` 提供 always-on context。執行 `setup.sh`，或把 `.skills/*` 複製到 `.cursor/skills/`。接著在 chat 裡輸入 `/wiki-setup`。
</details>

<details>
<summary>Windsurf</summary>

Cascade 會讀取 `.windsurf/rules/` 的 rules 與 `.windsurf/skills/` 的 skills。執行 `setup.sh`，或把 `.skills/*` 複製到 `.windsurf/skills/`。接著告訴 Cascade：「set up my wiki」。
</details>

<details>
<summary>Codex</summary>

讀取 `AGENTS.md` 作為 project context。`setup.sh` 會把 skills 全域安裝到 `~/.codex/skills/`。執行 `setup.sh`，或手動把 `.skills/*` symlink 到 `~/.codex/skills/`。

```bash
cd /path/to/obsidian-wiki && codex "set up my wiki"
```
</details>

<details>
<summary>Gemini CLI</summary>

讀取 `GEMINI.md`，並從 `~/.gemini/skills/` discovery 全域 skills。執行 `setup.sh`，或手動把 `.skills/*` symlink 到 `~/.gemini/skills/`。

```bash
cd /path/to/obsidian-wiki && gemini "set up my wiki"
```
</details>

<details>
<summary>Google Antigravity</summary>

透過 `.agent/rules/` + `.agent/workflows/` always-on。`setup.sh` 會提供兩個檔案，並把 skills symlink 到 `.agents/skills/`。legacy 的 `~/.gemini/antigravity/skills/` 路徑也會接上。
</details>

<details>
<summary>Kiro IDE/CLI</summary>

透過 `.kiro/steering/*.md` always-on，且 `inclusion: always`。`setup.sh` 會把 `.skills/*` symlink 到 `.kiro/skills/` 與 `~/.kiro/skills/`。可用 `/wiki-ingest`、`/wiki-query` 等指令呼叫。
</details>

<details>
<summary>OpenCode / Aider / Factory Droid / Trae</summary>

都會讀取 repo root 的 `AGENTS.md`。`setup.sh` 會把 skills symlink 到 `~/.agents/skills/`（共用 discovery path）。Trae 也會取得 `~/.trae/skills/` 與 `~/.trae-cn/skills/`。
</details>

<details>
<summary>Hermes</summary>

優先讀取 `.hermes.md`，再 fallback 到 `AGENTS.md`。Skills 從 `~/.hermes/skills/` discovery。執行 `setup.sh`，或手動把 `.skills/*` symlink 到該處。

```bash
cd /path/to/obsidian-wiki && hermes "set up my wiki"
# 將 Hermes history 挖掘進 wiki：
/wiki-history-ingest hermes
```
</details>

<details>
<summary>OpenClaw</summary>

讀取 `AGENTS.md`（priority 10）。從 `~/.openclaw/skills/` 與 `~/.agents/skills/` discovery skills。Skills 會自動註冊為 slash commands。

```bash
cd /path/to/obsidian-wiki && openclaw "set up my wiki"
# 將 OpenClaw history 挖掘進 wiki：
/wiki-history-ingest openclaw
```
</details>

<details>
<summary>GitHub Copilot</summary>

**VS Code Chat:** 讀取 `.github/copilot-instructions.md`。在 Copilot Chat 裡說「set up my wiki」。

**CLI:** 從 `~/.copilot/skills/` discovery skills。執行 `setup.sh`，或手動把 `.skills/*` symlink 到該處。
</details>

<details>
<summary>Pi</summary>

讀取 `AGENTS.md`（從 cwd 往上找）。從 `.pi/skills/`、`.agents/skills/` 與 `~/.pi/agent/skills/` discovery skills。執行 `setup.sh`，或手動把 `.skills/*` symlink 到 `~/.pi/agent/skills/`。

```bash
cd /path/to/obsidian-wiki && pi "set up my wiki"
# 將 Pi session history 挖掘進 wiki：
/wiki-history-ingest pi
```
</details>

</details>

## 運作方式

每次你餵資料給這個大腦，它都會經過四個階段：

**1. Ingest** — agent 直接讀取你的來源材料。它能處理你丟給它的各種內容：markdown 檔、PDF（含頁碼範圍）、JSONL conversation exports、純文字 logs、chat exports、meeting transcripts，以及圖片（截圖、白板照片、diagram；需要支援 vision 的模型）。不需要前處理，也不需要額外 pipeline。agent 會像讀 code 一樣讀檔。

**2. Pull Information** — agent 從 raw source 中抽出 concepts、entities、claims、relationships 與 open questions。一次關於 React hook debugging 的對話，會產生「stale closure」pattern；一篇 research paper 會產生核心想法與 caveats；一份 work log 會產生決策與理由。雜訊會被丟掉，訊號會被留下。寫入時，每個 page 也會在 frontmatter 中得到 1–2 句 `summary:`；之後 query 可以用它預覽頁面，不必打開整頁。

**3. Merge** — 新知識會和 wiki 裡既有的內容合併。如果 concept page 已存在，agent 會更新它：合併新資訊、標記矛盾、強化 cross-references。如果真的是新內容，才會建立新 page。內容不會重複。來源會被追蹤在 frontmatter 裡，所以每個 claim 都能回到來源。

**4. Schema** — wiki schema 不會一開始就固定。它會從你的 sources 中浮現，並隨著你加入更多內容而演化。agent 會維持一致性：categories 保持一致、wikilinks 指向真實 pages、index 反映實際內容。當你加入新 domain（新 project、新研究領域）時，schema 會擴展來容納它，而不破壞既有內容。

`.manifest.json` 會追蹤每個已 ingest 的 source：路徑、timestamps、它產生了哪些 wiki pages。下一次 ingest 時，agent 會計算 delta，只處理新增或變更的內容。

## 視覺化

透過 Obsidian 的 Global Graph View，可以視覺化整個 vault 中的每個 note 與 link。

- **Ribbon Icon**：點左側 ribbon 上的 "Open graph view" icon（看起來像連接網路）。
- **Command Palette**：按 Ctrl + P（Windows/Linux）或 Cmd + P（Mac），輸入 "Open graph view"，然後按 Enter。

<img width="1632" height="963" alt="obsidian-wiki" src="https://github.com/user-attachments/assets/f2980840-4b5b-438a-8264-5ad1de42f483" />

### Graph 顏色標記

說 **"color my graph"**、**"color code by tag"**、**"color by category"** 或 **"highlight visibility in graph"**，`graph-colorize` skill 會重寫 `<vault>/.obsidian/graph.json`，讓 Obsidian 依照 tag、folder 或 visibility 為 nodes 上色。它會掃描你的實際 vocabulary，選擇 colorblind-friendly palette，先備份既有的 `graph.json`，並且只修改 `colorGroups` 欄位；你的 zoom、physics 與 filter preferences 會保持不變。重新載入 Obsidian（Cmd/Ctrl+R）即可看到變更。

模式：`by-tag`（預設，前 10 個 tags）、`by-category`（七個 vault folders）、`by-visibility`（highlight `visibility/pii` 與 `visibility/internal`）、`combined`（visibility + tags）或 `custom`（使用者提供的 mapping）。

## 我們在 Karpathy pattern 之上加入了什麼

- **Delta tracking.** manifest 會追蹤每個已 ingest 的 source file：路徑、timestamps、它產生了哪些 wiki pages。當你之後回來，它會計算 delta，只處理新增或變更的內容。你不需要每次都重新 ingest 整個文件庫。

- **Project-based organization.** project-specific 的知識會歸檔在 projects 下；非 project-specific 的知識則放在全域。兩者都會用 wikilinks cross-reference。如果你同時在 10 個 codebases 工作，每個 codebase 都會在 vault 中有自己的空間。

- **Archive and rebuild.** 當 wiki 偏離 sources 太遠時，可以把整個 wiki archive（timestamped snapshot，不會遺失內容）並從頭重建，也可以 restore 任一之前的 archive。

- **Multi-agent ingest.** Documents、PDFs、Claude Code history（`~/.claude`）、Codex sessions（`~/.codex/`）、Hermes memories and sessions（`~/.hermes/`）、OpenClaw MEMORY.md and sessions（`~/.openclaw/`）、Pi sessions（`~/.pi/agent/sessions/`）、Windsurf data（`~/.windsurf`）、ChatGPT exports、Slack logs、meeting transcripts、raw text。Claude、Codex、Hermes、OpenClaw 與 Pi history 都有 dedicated skills，另有 catch-all ingest skill 可處理任意文字 exports。

- **Cross-agent targeted search.** `/wiki-claude`、`/wiki-codex`、`/wiki-hermes`、`/wiki-openclaw`、`/wiki-copilot`、`/wiki-pi`：從特定 agent 的 raw history 做 query-driven ingest。在 Claude Code 中說 `/wiki-codex "rust ownership"`，它會找到你關於該主題的 Codex sessions，抽出相關 conversation blobs，蒸餾成 wiki pages，並回傳可立即使用的綜合答案。這不同於 bulk ingest：它是 topic-first，不是 session-first。每個 agent 都有自己的 extraction strategy（Codex rollout events、Claude JSONL turns、OpenClaw 的預先綜合 `MEMORY.md`、Pi 的 tree-structured JSONL sessions 等）。搭配 `/memory-bridge diff` 可以看出每個工具在某個 topic 上各自貢獻了什麼。

- **Audit and lint.** 找出 orphaned pages、broken wikilinks、stale content、contradictions、missing frontmatter。也能查看已 ingest 與 pending 內容的 dashboard。

- **Automated cross-linking.** ingest 新 pages 後，cross-linker 會掃描 vault 裡未連結的 mentions，並用 `[[wikilinks]]` 把它們織進 knowledge graph。不再有孤兒頁面。

- **Tag taxonomy.** canonical tags 的 controlled vocabulary 存在 `_meta/taxonomy.md`，並有 skill 可 audit 與 normalize 整個 vault 的 tags。

- **Provenance tracking.** wiki page 上每個 claim 都會標記來源類型：extracted（預設）、`^[inferred]`（LLM synthesis）或 `^[ambiguous]`（sources disagree）。frontmatter 中的 `provenance:` block 會摘要每個 page 的 mix，`wiki-lint` 會標出逐漸變成主要靠推測的 pages。你永遠能分辨 wiki 真正知道什麼、猜了什麼。

- **Multimodal sources.** Screenshots、whiteboard photos、slide captures 與 diagrams 的 ingest 方式和文字一樣；agent 會逐字轉錄可見文字，並把詮釋內容標成 inferred。需要支援 vision 的模型。

- **Wiki insights.** 除了 delta tracking，`wiki-status` 還能分析 vault 本身的形狀：top hubs、bridge pages（移除後會切開 graph 的 nodes）、tag cluster cohesion scores、scored surprising connections、上次執行以來的 graph delta，以及 wiki 結構特別適合回答的 suggested questions。輸出會寫到 `_insights.md`。

- **Graph export.** `wiki-export` 會把 vault 的 wikilink graph 轉成 `graph.json`（可 query）、`graph.graphml`（Gephi/yEd）、`cypher.txt`（Neo4j）與 self-contained 的 `graph.html` interactive browser visualization；不需要 server。

- **Tiered retrieval.** `wiki-query` 會先讀 titles、tags 與 page summaries，只有 cheap pass 無法回答時才開啟 page bodies。說 "quick answer" 或 "just scan" 可以強制 index-only mode。當 vault 從 20 pages 成長到 2000 pages 時，query cost 仍能大致維持平穩。

- **QMD semantic search（可選）.** [QMD](https://github.com/tobi/qmd) 會為你的 wiki 與 source documents 建立 semantic search index。當 `.env` 設定 `QMD_WIKI_COLLECTION` 時，`wiki-query` 會先對 collection 執行 lex+vec pass，再 fallback 到 Grep，讓 exact-string search 找不到的 concept-level matches 也能被找到。設定 `QMD_PAPERS_COLLECTION` 時，`wiki-ingest` 會在寫新 page 前查詢 indexed sources，以找出 related work、detect contradictions，並決定建立或合併。QMD 可以透過 MCP 或 local CLI 使用。沒有 QMD 時，兩個 skills 都會 fallback 到 Grep/Glob，仍完全可用。

- **`_raw/` staging directory.** 把 rough notes、clipboard pastes 或 quick captures 放進 vault 裡的 `_raw/`。下一次 `wiki-ingest` 會把它們 promote 成正式 wiki pages，並移除 originals。透過 `.env` 的 `OBSIDIAN_RAW_DIR` 設定（預設 `_raw`）。

## 可選：QMD Semantic Search

預設情況下，`wiki-ingest` 與 `wiki-query` 使用 `Grep`/`Glob` 搜尋，功能完整且不需要額外設定。如果你的 vault 變大，或你想跨 sources 做 concept-level matches，可以接上 [QMD](https://github.com/tobi/qmd)，透過 MCP 或讓 agent 呼叫本機 `qmd` CLI。

**設定：**

1. 安裝 QMD。若想使用 MCP mode，也把它加到你的 MCP config（請參考 QMD repo）。
2. Index 你的 wiki 或 source documents：
   ```bash
   qmd index --name wiki /path/to/your/vault
   qmd index --name papers /path/to/your/sources
   ```
3. 在 `.env` 中設定 collection names 與 transport：
   ```env
   QMD_WIKI_COLLECTION=wiki       # used by wiki-query
   QMD_PAPERS_COLLECTION=papers   # used by wiki-ingest (source discovery)
   QMD_TRANSPORT=mcp              # mcp | cli
   QMD_CLI_SEARCH_MODE=quality    # quality | balanced | fast
   ```

`QMD_TRANSPORT=mcp` 會保留原本行為，使用 agent-configured QMD MCP server。`QMD_TRANSPORT=cli` 會直接執行本機 `qmd` command。CLI mode 預設為 `quality`，使用 `qmd query` 搭配 reranking 取得最佳 relevance。如果 CPU 上太慢，可把 `QMD_CLI_SEARCH_MODE=balanced` 設成使用 `qmd query --no-rerank`，或設成 `fast` 使用較輕量的 semantic pass。

**啟用 QMD 後會改變什麼：**

- **`wiki-query`** 會先對你的 wiki collection 執行 semantic pass（lex+vec），再 fallback 到 Grep。即使 exact terms 不符合，也能找到 conceptually related pages。
- **`wiki-ingest`** 會在寫新 page 前查詢 papers collection，找出 related sources、spot contradictions，並決定建立新 page 或合併進既有 page。

兩個 skills 都會 graceful degradation：如果沒有設定 `QMD_WIKI_COLLECTION` / `QMD_PAPERS_COLLECTION`，它們會安靜地略過 QMD step，改用 Grep。

### `_raw/` Staging Directory

`_raw/` 是 vault 內用來放未處理 captures 的 staging area，例如 rough notes、clipboard pastes、quick voice-memo transcripts。把檔案丟進去，下一次 `wiki-ingest` 會把它們 promote 成正式 wiki pages，並移除 originals。

在 live coding session 中餵資料給 `_raw/` 的最快方式是 `/wiki-capture --quick`：它會掃描目前 conversation，抽出 bugs 與 gotchas，並在 60 秒內寫出 structured draft files，不使用 subagents，也不寫 manifest。

此目錄會由 `wiki-setup` 自動建立。路徑可透過 `.env` 中的 `OBSIDIAN_RAW_DIR` 設定（預設 `_raw`）。

### Browser Capture Extension

這個 repo 包含一個零建置 Chrome extension，位於 `extensions/brain-capture/`，可將網頁與選取文字儲存到 vault 的 `_raw/` folder。

安裝方式：

1. 開啟 `chrome://extensions`
2. 啟用 **Developer mode**
3. 點 **Load unpacked**
4. 選擇 `extensions/brain-capture`

從這個 repo 找出已設定的 `_raw` folder：

```bash
awk -F= '/^OBSIDIAN_VAULT_PATH=/{print $2 "/_raw"; exit}' "$(git rev-parse --show-toplevel)/.env"
```

把 pages capture 到 `_raw/` 後，請 agent 處理它們：

```text
/wiki-ingest promote my raw pages
```

`wiki-ingest` 會讀取每個 `_raw/` capture，蒸餾到正確的 wiki pages，更新 manifest/index/log，並移除已 promote 的 raw files，避免重複處理。

---

## 將 vault 同步到 GitHub

你的 vault 是 plain markdown files 的目錄；把它 push 到 private GitHub repo，就能免費得到 version history、backup 與 cross-device sync。`setup.sh`（以及 `obsidian-wiki setup`）會在初始安裝時詢問你是否設定。

**setup 會做什麼：**

1. 如果 vault 還不是 repo，執行 `git init`
2. 建立 `.gitignore`，排除 Obsidian workspace/cache files
3. 設定你提供的 GitHub remote
4. 寫入 `~/.obsidian-wiki/sync.sh`，這是一個 one-shot script，會 stage 所有 changes、用 timestamp commit，並 push
5. 可選擇加入 `wiki-sync` shell alias
6. 可選擇安裝 hourly cron job

**隨時執行同步：**

```bash
wiki-sync                    # setup 加入的 alias
~/.obsidian-wiki/sync.sh     # 或直接呼叫 script
```

每次執行都會以 `sync 2026-06-08 14:00` 這樣的訊息 commit staged changes 並 push。

**手動設定（略過 prompt）：**

```bash
cd /path/to/your/vault
git init
git remote add origin https://github.com/you/my-wiki.git

# then commit and push manually, or re-run setup.sh to get the sync script
```

**透過 cron 每小時自動同步（可於 setup 時啟用）：**

```cron
0 * * * * ~/.obsidian-wiki/sync.sh >> ~/.obsidian-wiki/sync.log 2>&1
```

> 如果你的 vault 包含個人筆記，請保持 repo **private**。不會傳送任何內容到第三方服務；vault 只存在你的機器與你的 GitHub account 中。

---

## Skills

所有內容都在 `.skills/`。每個 skill 都是 agent 被觸發時會讀取的 markdown 檔案：

| Skill | 功能 | Slash Command |
|---|---|---|
| `wiki-setup` | 初始化 vault structure | `/wiki-setup` |
| `wiki-ingest` | 將 documents 蒸餾成 wiki pages，也支援 chat exports、logs、transcripts、URLs | `/wiki-ingest` |
| `wiki-history-ingest` | Unified history router（`claude`、`codex`、`hermes`、`pi`） | `/wiki-history-ingest <claude|codex|hermes|pi>` |
| `claude-history-ingest` | 挖掘你的 `~/.claude` Claude code 與 desktop conversations/memories | `/claude-history-ingest` |
| `codex-history-ingest` | 挖掘你的 `~/.codex` sessions 與 rollout logs | `/codex-history-ingest` |
| `hermes-history-ingest` | 挖掘你的 `~/.hermes` memories 與 sessions | `/hermes-history-ingest` |
| `openclaw-history-ingest` | 挖掘你的 `~/.openclaw` MEMORY.md 與 sessions | `/openclaw-history-ingest` |
| `copilot-history-ingest` | 挖掘你的 `~/.copilot` CLI session history | `/copilot-history-ingest` |
| `pi-history-ingest` | 挖掘你的 `~/.pi/agent/sessions` JSONL history | `/pi-history-ingest` |
| `wiki-status` | 顯示已 ingest、pending 與 delta | `/wiki-status` |
| `wiki-rebuild` | Archive、從頭 rebuild 或 restore | `/wiki-rebuild` |
| `wiki-query` | 從 wiki 回答問題 | `/wiki-query` |
| `wiki-lint` | 找 broken links、orphans、contradictions | `/wiki-lint` |
| `cross-linker` | 自動發現並插入 missing wikilinks | `/cross-linker` |
| `tag-taxonomy` | 在 pages 間強制一致的 tag vocabulary | `/tag-taxonomy` |
| `llm-wiki` | 核心 pattern 與 architecture reference | `/llm-wiki` |
| `wiki-update` | 將目前 project 的知識同步進 vault | `/wiki-update` |
| `wiki-export` | 將 vault graph 匯出為 JSON、GraphML、Neo4j、HTML | `/wiki-export` |
| `wiki-capture` | 將目前 conversation 儲存為 wiki note；`--quick` 會把 findings staged 到 `_raw/` | `/wiki-capture` |
| `wiki-research` | Autonomous multi-round web research，並自動歸檔 | `/wiki-research [topic]` |
| `wiki-dashboard` | 建立 dynamic Obsidian Bases dashboard views | `/wiki-dashboard` |
| `wiki-synthesize` | 發現並補齊 concepts 間的 synthesis gaps | `/wiki-synthesize` |
| `wiki-agent` | 從特定 agent history 做 query-driven ingest | `/wiki-claude [topic]`, `/wiki-codex [topic]`, etc. |
| `memory-bridge` | 依 AI tool 瀏覽與比較 knowledge | `/memory-bridge` |
| `daily-update` | Daily maintenance cycle：freshness、index、hot cache | `/daily-update` |
| `impl-validator` | 根據 stated goal 驗證 implementation | `/impl-validator` |
| `graph-colorize` | 依 tag/category/visibility 為 Obsidian graph 上色 | `/graph-colorize` |
| `skill-creator` | 建立新的 skills | `/skill-creator` |

> **Note:** Slash commands（`/skill-name`）可在 Claude Code、Cursor 與 Windsurf 使用。在其他 agents 中，只要描述你想做什麼，agent 會找到正確的 skill。

### 推薦：Kepano 的 Obsidian Skills

我們負責 knowledge management workflow：ingest、query、lint、rebuild。若要精通 Obsidian 格式，建議把 [**kepano/obsidian-skills**](https://github.com/kepano/obsidian-skills) 和這個 framework 一起安裝。這些 skills 是 optional，但能提升 wiki output 品質：

| Skill | 增加的能力 |
|---|---|
| `obsidian-markdown` | 教 agent 正確的 Obsidian-flavored syntax：wikilinks、callouts、embeds、properties |
| `obsidian-bases` | 建立與編輯 `.base` files（像 database 的 notes views） |
| `json-canvas` | 建立與編輯 `.canvas` files（visual mind maps、flowcharts） |
| `obsidian-cli` | 透過 CLI 操作正在執行的 Obsidian instance（search、create、manage notes） |
| `defuddle` | 從 web pages 擷取乾淨 markdown；比 raw fetch 更少雜訊，ingest 時省 tokens |

兩個 projects 都使用相同的 [Agent Skills spec](https://agentskills.io/specification)，因此能在同一個 `.skills/` directory 共存，不會衝突。

**安裝：**

```bash
npx skills add kepano/obsidian-skills
```

安裝後，你的 agent 會自動和既有 wiki skills 一起取得新 skills。

## Project Structure

```text
obsidian-wiki/
├── .skills/                          # ← Canonical skill definitions (source of truth)
│   ├── wiki-setup/SKILL.md
│   ├── wiki-ingest/SKILL.md
│   ├── wiki-history-ingest/SKILL.md
│   ├── claude-history-ingest/SKILL.md
│   ├── codex-history-ingest/SKILL.md
│   ├── hermes-history-ingest/SKILL.md
│   ├── openclaw-history-ingest/SKILL.md
│   ├── pi-history-ingest/SKILL.md
│   ├── wiki-status/SKILL.md
│   ├── wiki-rebuild/SKILL.md
│   ├── wiki-query/SKILL.md
│   ├── wiki-lint/SKILL.md
│   ├── cross-linker/SKILL.md
│   ├── tag-taxonomy/SKILL.md
│   ├── wiki-update/SKILL.md
│   ├── llm-wiki/SKILL.md
│   ├── wiki-export/SKILL.md
│   └── skill-creator/SKILL.md
│
├── CLAUDE.md                            # Bootstrap → Claude Code / Kilocode (→ AGENTS.md)
├── GEMINI.md                            # Bootstrap → Gemini CLI (→ AGENTS.md)
├── AGENTS.md                            # Bootstrap → Codex, OpenCode, Aider, Droid, Trae, Hermes, OpenClaw, Kilocode
├── .hermes.md                           # Bootstrap → Hermes (symlink → AGENTS.md)
├── .cursor/rules/obsidian-wiki.mdc      # Always-on → Cursor (alwaysApply: true)
├── .windsurf/rules/obsidian-wiki.md     # Always-on → Windsurf
├── .kiro/steering/obsidian-wiki.md      # Always-on → Kiro (inclusion: always)
├── .agent/rules/obsidian-wiki.md        # Always-on → Google Antigravity
├── .agent/workflows/obsidian-wiki.md    # Slash-command registry → Google Antigravity
├── .github/copilot-instructions.md      # Always-on → GitHub Copilot (VS Code Chat)
│
├── .claude/skills/   → symlinks to .skills/*  (created by setup.sh)
├── .cursor/skills/   → symlinks to .skills/*  (created by setup.sh)
├── .windsurf/skills/ → symlinks to .skills/*  (created by setup.sh)
├── .agents/skills/   → symlinks to .skills/*  (created by setup.sh)
├── .pi/skills/       → symlinks to .skills/*  (created by setup.sh)
├── .kiro/skills/     → symlinks to .skills/*  (created by setup.sh)
│
├── ~/.claude/skills/              → portable skills (wiki-update, wiki-query)
├── ~/.gemini/skills/              → global symlinks — Gemini CLI
├── ~/.gemini/antigravity/skills/  → global symlinks — Antigravity (legacy path)
├── ~/.codex/skills/               → global symlinks — Codex
├── ~/.hermes/skills/              → global symlinks — Hermes
├── ~/.openclaw/skills/            → global symlinks — OpenClaw (managed)
├── ~/.copilot/skills/             → global symlinks — GitHub Copilot CLI
├── ~/.trae/skills/                → global symlinks — Trae
├── ~/.trae-cn/skills/             → global symlinks — Trae CN
├── ~/.kiro/skills/                → global symlinks — Kiro CLI
├── ~/.pi/agent/skills/            → global symlinks — Pi
├── ~/.agents/skills/              → global symlinks — OpenCode, Aider, Droid, generic
│
├── setup.sh                          # One-command agent setup
├── .env.example                      # Configuration template
├── README.md                         # English README
├── README_TW.md                      # Traditional Chinese README
└── SETUP.md                          # Detailed setup guide
```

## 從其他 projects 使用

你的大腦應該隨著你在不同 codebases 工作而成長，而不是只有打開 obsidian-wiki repo 時才成長。因此 `setup.sh` 會安裝兩個能從任何 project 觸達 vault 的 global skills：`wiki-update` 與 `wiki-query`。

執行 `bash setup.sh` 時，它會做以下事情：

1. 將 vault path 與 repo location 寫入 `~/.obsidian-wiki/config`。這是 skills 知道要去哪裡讀寫的方式。
2. 把 `wiki-update` 與 `wiki-query` symlink 到 `~/.claude/skills/`，讓 Claude Code 在任何地方都能使用。
3. 把所有 skills symlink 到每個 agent 的 global discovery path：
   - `~/.gemini/skills/` — Gemini CLI（canonical）
   - `~/.gemini/antigravity/skills/` — Google Antigravity（legacy）
   - `~/.codex/skills/` — Codex
   - `~/.hermes/skills/` — Hermes
   - `~/.openclaw/skills/` — OpenClaw（managed）
   - `~/.copilot/skills/` — GitHub Copilot CLI
   - `~/.trae/skills/` + `~/.trae-cn/skills/` — Trae / Trae CN
   - `~/.kiro/skills/` — Kiro CLI
   - `~/.pi/agent/skills/` — Pi
   - `~/.agents/skills/` — OpenCode、Aider、Factory Droid 與其他 AGENTS.md-aware agents

之後，假設你正在某個 project（例如 `~/projects/my-cool-app`）中，用 Claude 或 Pi 工作。兩個 commands：

```bash
# You're working on some project
cd ~/projects/my-cool-app
claude

# Write to the wiki: distill what you've learned
> /wiki-update

# Read from the wiki: pull context about anything you've captured before
> /wiki-query what do I know about rate limiting?
```

`/wiki-update` 會讀取你的 project，判斷哪些內容值得保存，然後寫進大腦：architecture decisions、你發現的 patterns、key concepts、你評估過的 trade-offs。它會跳過 code 與 file listings，保存三個月後你可能會忘記的東西。從同一個 project 再跑一次時，它會檢查上次 sync 以來的變更（透過 git log），只處理 delta。

`/wiki-query` 則反過來。你正在工作中，想知道大腦是否已經有某個 topic 的脈絡。也許你兩個月前在另一個 project 解過同樣問題，答案已經在 vault 裡。agent 會搜尋 vault、讀取相關 pages，並給出帶 citations 的綜合答案。

兩個 skills 都遵循和其他部分相同的 Karpathy pattern。如果某個 concept page 已存在於 vault 中，就會合併進去。所有內容都會用 `[[wikilinks]]` cross-link，追蹤在 `.manifest.json`，並寫入 log。

## Contributing

這還很早期。skills 已可用，但還有很多地方能讓這個大腦更聰明：更好的 cross-referencing、更精準的 deduplication、更大的 vaults、新的 ingest sources。如果你也一直在思考這個問題，或有某個 workflow 可以變成 skill，歡迎 PR。

### 保持兩份 README 同步

`README.md` 是英文文件，`README_TW.md` 是其繁體中文翻譯；兩者共同構成同一份文件介面。兩份翻譯的標題、範例、連結與面向使用者的行為，應在結構與語意上保持一致。同步是建議性的，不會擋下合併：`readme-translation-drift` CI job 只會在翻譯落後時提出回報。要補齊時，執行 `python tools/check_readme_sync.py` — 它會列出動到 `README.md` 但之後沒有更新 `README_TW.md` 的 commits，以及尚未翻譯的英文 diff — 接著將這些變更翻譯並補進 `README_TW.md`。翻譯品質由 reviewers 評估。

### 新增 skill

1. 在 `.skills/your-skill-name/` 建立資料夾
2. 加入含 YAML frontmatter（`name`、`description`）與 markdown instructions 的 `SKILL.md`
3. 執行 `bash setup.sh`，symlink 到所有 agent directories
4. 對你的 agent 說出符合 description 的需求來測試

請參考 `.skills/skill-creator/SKILL.md`，了解撰寫有效 skills 的完整指南。
