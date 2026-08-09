# CLI 參考（繁體中文）

完整的 CLI 參考請見 [cli.md](cli.md)（英文）。本頁目前翻譯 context pack 與 trust ledger 兩節：前者包含下游 agent 必須遵守的安全性約定，後者記錄人工核准的 confidence reviews。

## 將既有 vault 作為有界限的 agent context

`wiki-context-pack` 會從既有 Markdown 編譯出 task-scoped snapshot。筆記不需
搬進 wiki-generated folders，也不必先補齊完整 frontmatter schema；整個
流程是 read-only。

```bash
obsidian-wiki context-pack "authentication architecture" --budget 8000
obsidian-wiki context-pack --recent --budget 4000
obsidian-wiki context-pack "release notes" --budget 8000 --public-only
```

省略 `--budget` 會使用預設的 8000 個估算 token。

輸出包含 source paths、summaries、選定 excerpts 與不可超過的 token 估算
上限。Vault excerpts 會明確標成 untrusted reference data：下游 agent
可以使用其中的知識，但不得執行筆記內嵌的指令。使用 `--metadata-only`
可產生最小 context，使用 `--json` 可供 tool-to-tool integration。

| 參數 | 作用 |
|---|---|
| `--budget N` | 估算輸出 token 上限，範圍 256–100000（預設 8000） |
| `--recent` | 選取最近更新的筆記，這是唯一能省略 topic 的方式 |
| `--public-only` | 排除 `visibility/internal` 與 `visibility/pii` 筆記 |
| `--metadata-only` | 只輸出標題、provenance 與 summary，不含內文 excerpts |
| `--json` | 輸出結構化 JSON，供 tool-to-tool integration 使用 |
| `--vault PATH` | 覆寫 `OBSIDIAN_VAULT_PATH` |

`context` 是 `context-pack` 的別名。

## Trust ledger（信任帳本）

記錄並驗證人工核准的 confidence reviews，讓你在 CI 上把關「這些 pages 真的有人檢查過」。

| 指令 | 作用 |
|---|---|
| `trust-record` | 記錄明確核准的人工 confidence reviews |
| `trust-check` | 依帳本驗證 confidence values 與 material fingerprints |

```bash
obsidian-wiki trust-record --all --reviewed-at 2026-07-30T10:00:00+00:00 --approved
obsidian-wiki trust-record --page concepts/rate-limiting.md --reviewed-at <ISO> --approved
obsidian-wiki trust-check --strict
obsidian-wiki trust-record @research --all --reviewed-at <ISO> --approved --allow-lifecycle active
obsidian-wiki trust-check @research --allow-lifecycle active --schema-source /vault/AGENTS.md
```

`--reviewed-at` 必須帶時區。`--approved` 是必要且強制的參數 — 它代表你斷言每個被記錄的 confidence value 都有人類核准。`trust-check --strict` 是 CI/排程 gate。`trust-record` 與 `trust-check` 使用與 lint 相同的 vault-scoped schema；可傳相同的 lifecycle 與 required-field overrides。若 owner schema 不要求 `base_confidence`，缺少該欄位的 pages 會被回報為 `not_applicable`、被 `trust-record --all` 排除；過時的 ledger entries 會被 `trust-check` 警告，再由 `trust-record --page` 或 rebuild 移除。JSON 與人讀的 record output 都會列出被排除的 pages 與被移除的過時 entries；人讀 output 發生移除時也會在 stderr 輸出警告。Required-field config 只接受 `base_confidence`、`lifecycle`、`lifecycle_changed`、`updated`；拼錯會 fail closed。Lifecycle、relationship-type 與 required-field override values 會去除空白，空或只有空白的 entries 會被拒絕，不會加進 allowlist。沒有明確的 `--schema-source` 時，explicit vault 上的 CLI overrides 會標記為 `cli:explicit-vault`；CLI 與 config overrides 合併使用時標記為 `cli+config:<resolved-config-path>`。
