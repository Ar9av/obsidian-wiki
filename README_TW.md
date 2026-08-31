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
  <img width="768" alt="obsidian-wiki" src="assets/hero.png" />
</p>

<p align="center">
  <a href="https://github.com/Ar9av/obsidian-wiki/blob/main/README.md">English</a> | 繁體中文
</p>

---

你在某個星期二解掉一個難題。三個月後，在另一個 repo 裡，你又從頭解了一次，因為答案躺在一份你永遠找不到的對話紀錄裡。

這個專案解決那個問題。指定一個資料夾，告訴你的 agent 要記住什麼，它就會把你學到的東西編譯成彼此連結、而且屬於你自己的 markdown。這個模式來自 Andrej Karpathy 的 [LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)：把知識編譯一次並持續維護，而不是每次都問 LLM 同樣的問題，或每次都重新跑 RAG。

**你的第二大腦；AI agent 是你讓它成長的方式。**

這裡每個 skill 都是一個 markdown 檔案，任何 agent 都能讀取並執行，包括 Claude Code、Cursor、Codex、Windsurf、Gemini CLI，以及[另外十幾種](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/agents.md)。沒有 runtime、沒有 API key、不綁任何廠商。

## 60 秒上手

```bash
pip install obsidian-wiki
obsidian-wiki setup --vault ~/brain
```

使用 `uv` 或 `pipx`？`uv tool install obsidian-wiki` 與 `pipx install obsidian-wiki` 的效果相同。（不要用 `uvx`，原因見[安裝說明](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/installation.md#install-via-pip-uv-or-pipx-recommended)。）

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
/wiki-update                        # 蒸餾你目前所在的這個 repo（支持使用 codegraph 增強程式碼結構解析）
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

你也可以把整個圖譜匯出成 `graph.json`、GraphML（Gephi/yEd）、Neo4j Cypher、Postgres SQL，或一個自帶所有資源的互動式 `graph.html`。

## 為什麼不是一個筆記資料夾就好

- **它會編譯，而不是堆積。** 新知識會合併進既有頁面，矛盾會被標記出來，內容不會重複。
- **它只讀有變動的部分。** manifest 追蹤每個匯入過的來源，所以第二次執行只處理差異，而不是重跑整個資料庫。
- **你分得出哪些是知識、哪些是猜測。** 每個陳述都會標記為 `extracted`、`^[inferred]` 或 `^[ambiguous]`，lint 會標出開始偏向臆測的頁面。
- **查詢成本不隨規模爆炸。** 先讀標題、tag 和 summary，需要時才打開頁面內容。20 頁或 2000 頁，成本差不多。
- **它是你的。** 就是資料夾裡的純 markdown。推到私人 repo、用 Obsidian 打開、用 grep 搜、直接刪掉都行。沒有服務、沒有鎖定，什麼都不會離開你的機器。
- **在你原本工作的地方就能用。** 一個 `.skills/` 目錄，symlink 到你使用的每一個 agent。

更多細節請見 **[Architecture](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/architecture.md)**（英文）

## 真的有幫助嗎？

結構性問題——「X 和 Y 是怎麼連起來的」、「哪些頁面撐住了整個 vault」、「刪掉這頁會壞掉什麼」——正是一般 agent 最不擅長的。它每一次都得 grep 過所有檔案，再自己把連結圖重建一遍。

同一個模型、同一個 vault、同樣的問題，唯一的差別是有沒有裝 `obsidian-wiki`：

| | 一般 agent | 裝了 obsidian-wiki |
|---|---|---|
| **回答耗時** | 81 秒 | **19 秒** — 快 4.4 倍 |
| **答對比例** | 44% | **83%** |
| **使用的工具呼叫次數** | 9.9 | **4.6** |
| **API 成本** | $0.202 | $0.208 — 沒有變化 |

| 問題 | 一般 agent | 裝了 obsidian-wiki |
|---|---|---|
| 「X 和 Y 是怎麼連起來的？」 | 122 秒 | 18 秒 |
| 「我有哪些主題叢集？」 | 117 秒 | 21 秒 |
| 「哪些頁面撐住了整個 vault？」 | 61 秒 | 12 秒 |
| 「刪掉 X 會壞掉什麼？」 | 26 秒 | 24 秒 |

正確率的差距不是誤差。被要求追出一條連結路徑時，一般 agent 會繞過 `index.md`——那頁連到*每一個*頁面，所以它「找到」了一條毫無意義的短路徑。兩次執行都犯了同樣的錯，而且還把 `index` 說成 vault 裡最重要的頁面之一。這些 skill 查詢的圖已經排除了記帳用的檔案，所以那種答案根本不會出現。

<details>
<summary>方法，以及這個測試無法證明的事</summary>

使用 Claude Sonnet，以 headless 模式在一個真實的 38 頁 vault 上執行。問題都用一般口語提出，沒有另外說明圖的定義——一般 agent 有 `Read`/`Grep`/`Glob`/`Bash`，得自己想辦法（它做得不錯，甚至自己寫了一份中心性演算法，而不是隨便猜）。4 個問題 × 2 種條件 × 2 次重複，序列執行，避免互搶 CPU。

基準答案來自 **networkx**，而不是本專案自己的程式碼：betweenness 在每個節點上的誤差都在 3.5e-18 以內，630 組最短路徑也全部一致。

這是個小規模測試——每格 n=2，只用了一個 38 頁的 vault——所以確切的百分比僅供參考。時間差距（3～6 倍）遠大於各次執行之間的波動；正確率的數字則建立在較少的樣本上。「裝了」那一欄有一次執行完全失敗：模型沒有使用 CLI，自己 grep，然後答錯了。

完整資料、每次執行的紀錄與規模測試結果都在 [PR #175](https://github.com/Ar9av/obsidian-wiki/pull/175)。

</details>

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
| **[Browser Extension](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/browser-extension.md)** | 將網頁擷取進 vault，並用 vault 內容填寫網頁表單 |
| **[Deployment](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/deployment.md)** | 以 Docker 將 vault 部署成記憶服務，讓 agent 透過 HTTP/MCP 存取 |
| **[Contributing](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/contributing.md)** | 新增 skill、維持兩份 README 同步 |

## 參與貢獻

這個專案還很早期。skills 是能用的，但還有很多空間讓這個大腦變得更聰明：更好的交叉引用、更精準的去重、支撐更大的 vault、更多匯入來源。如果你有一個工作流程適合做成 skill，[歡迎送 PR](https://github.com/Ar9av/obsidian-wiki/blob/main/docs/contributing.md)。

## 授權

[MIT](https://github.com/Ar9av/obsidian-wiki/blob/main/LICENSE)
