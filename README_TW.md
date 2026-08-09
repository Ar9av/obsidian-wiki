<h1 align="center">obsidian-wiki</h1>

<p align="center"><b>一個由 AI agent 陪你一起養大的數位大腦。</b></p>

<p align="center">
  它會記住你弄懂的事，把新知識連到你已經知道的內容，<br>
  並在你提問時回答。
</p>

<p align="center">
  <a href="https://pypi.org/project/obsidian-wiki/"><img src="https://img.shields.io/pypi/v/obsidian-wiki?color=blue" alt="PyPI" /></a>
  <a href="https://deepwiki.com/Ar9av/obsidian-wiki"><img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki" /></a>
  <a href="https://github.com/ar9av/obsidian-wiki/pulls"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome" /></a>
  <a href="https://x.com/_ar9av"><img src="https://img.shields.io/badge/@__ar9av-black?logo=x&logoColor=white" alt="X" /></a>
</p>

<p align="center">
  <img width="768" alt="obsidian-wiki" src="https://github.com/user-attachments/assets/b44cf63b-3197-4fb1-8e18-dbc9a39f27a7" />
</p>

<p align="center">
  <a href="https://github.com/Ar9av/obsidian-wiki/blob/main/README.md">English</a> | 繁體中文
</p>

---

你在某個星期二解掉一個難題。三個月後，在另一個 repo 裡，你又從頭解了一次，因為答案躺在一份你永遠找不到的對話紀錄裡。

這個專案解決那個問題。指定一個資料夾，告訴你的 agent 要記住什麼，它就會把你學到的東西編譯成彼此連結、而且屬於你自己的 markdown。這個模式來自 Andrej Karpathy 的 [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)：把知識編譯一次並持續維護，而不是每次都問 LLM 同樣的問題，或每次都重新跑 RAG。

**Obsidian 是你觀看這個大腦的方式；AI agent 是你讓它成長的方式。**

這裡每個 skill 都是一個 markdown 檔案，任何 agent 都能讀取並執行，包括 Claude Code、Cursor、Codex、Windsurf、Gemini CLI，以及[另外十幾種](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/agents.md)。沒有 runtime、沒有 API key、不綁任何廠商。

## 60 秒上手

```bash
pip install obsidian-wiki
obsidian-wiki setup --vault ~/brain
```

然後在你的 agent 裡打開任何專案，說 **「set up my wiki」**。

不想碰終端機？把下面這行交給你的 agent，它會全部處理好：

```text
https://github.com/Ar9av/obsidian-wiki — set up my wiki
```

其他安裝方式（`git clone`、Skills CLI、多個 vault）請見 **[安裝說明](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/installation.md)**（英文）

## 你實際會做的事

**餵養它。** 任何文字形式的東西：文件、PDF、聊天匯出、會議逐字稿、截圖、網址。

```text
/wiki-ingest ~/research
/wiki-update                        # 蒸餾你目前所在的這個 repo
/wiki-capture                       # 把這段對話存下來
/wiki-history-ingest claude         # 挖出你問過 Claude 的所有東西
```

**問它。** 回答會附上 `[[wikilink]]` 引用，而不是憑感覺。

```text
/wiki-query what do I know about rate limiting?
/wiki-narrate MCP security          # 針對一個主題產生有引用的簡報
/wiki-digest week                   # 我這週學到了什麼？
```

**找出那個你叫不出名字的 session。**

```bash
obsidian-wiki sessions-build
obsidian-wiki sessions-query "the auth bug with the weird retry loop"
```

**維持它的品質。** vault 自己會變亂，這些 skill 負責整理。

```text
/wiki-lint            # 壞掉的連結、孤兒頁面、互相矛盾的內容
/wiki-dedup           # 「RSC」和「React Server Components」現在是同一頁了
/cross-linker         # 把新頁面編織進知識圖譜
/wiki-status          # 已匯入什麼、還有什麼待處理、樞紐頁面在哪
```

全部 39 個 skill 請見 **[Skills Reference](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/skills.md)**（英文）

## 看見它

在 Obsidian 打開 vault，然後開啟 graph view（Cmd/Ctrl+P → 「Open graph view」）。說 **「color my graph」**，它就會依照 tag、category 或 visibility 為節點上色。

<p align="center">
  <img width="900" alt="obsidian-wiki graph view" src="https://github.com/user-attachments/assets/f2980840-4b5b-438a-8264-5ad1de42f483" />
</p>

你也可以把整個圖譜匯出成 `graph.json`、GraphML（Gephi/yEd）、Neo4j Cypher，或一個自帶所有資源的互動式 `graph.html`。

## 為什麼不是一個筆記資料夾就好

- **它會編譯，而不是堆積。** 新知識會合併進既有頁面，矛盾會被標記出來，內容不會重複。
- **它只讀有變動的部分。** manifest 追蹤每個匯入過的來源，所以第二次執行只處理差異，而不是重跑整個資料庫。
- **你分得出哪些是知識、哪些是猜測。** 每個陳述都會標記為 `extracted`、`^[inferred]` 或 `^[ambiguous]`，lint 會標出開始偏向臆測的頁面。
- **查詢成本不隨規模爆炸。** 先讀標題、tag 和 summary，需要時才打開頁面內容。20 頁或 2000 頁，成本差不多。
- **它是你的。** 就是資料夾裡的純 markdown。推到私人 repo、用 Obsidian 打開、用 grep 搜、直接刪掉都行。沒有服務、沒有鎖定，什麼都不會離開你的機器。
- **在你原本工作的地方就能用。** 一個 `.skills/` 目錄，symlink 到你使用的每一個 agent。

更多細節請見 **[Architecture](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/architecture.md)**（英文）

## 文件

以下文件目前為英文版本。

| | |
|---|---|
| **[Installation](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/installation.md)** | pip、clone、由 agent 設定、多個 vault |
| **[Skills Reference](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/skills.md)** | 全部 39 個 skill 與其 slash command |
| **[Agent Compatibility](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/agents.md)** | 完整相容性表格與各 agent 手動設定 |
| **[CLI Reference](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/cli.md)** | 每一個 `obsidian-wiki` 子命令 |
| **[Configuration](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/configuration.md)** | 設定變數、QMD 語意搜尋、`_raw/` 暫存區、GitHub 同步 |
| **[Architecture](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/architecture.md)** | 四個匯入階段、vault 結構、我們在 Karpathy 模式上加了什麼 |
| **[Session Brain](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/session-brain.md)** | 建立在 agent session 歷史之上的主題圖譜 |
| **[Contributing](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/contributing.md)** | 新增 skill、維持兩份 README 同步 |

## 參與貢獻

這個專案還很早期。skills 是能用的，但還有很多空間讓這個大腦變得更聰明：更好的交叉引用、更精準的去重、支撐更大的 vault、更多匯入來源。如果你有一個工作流程適合做成 skill，[歡迎送 PR](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/contributing.md)。

## 授權

[MIT](https://github.com/Ar9av/obsidian-wiki/blob/main/LICENSE)
