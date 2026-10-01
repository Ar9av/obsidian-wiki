# Browser Extension

`extensions/brain/` is a zero-build Chrome extension that connects your browser
to your vault in both directions:

- **Capture** — save the current page, or a selection, into `_raw/` as markdown.
- **Fill form** — answer the form on the current page from what your vault
  already knows, using the Claude Code or Codex CLI you already pay for.

Capture needs nothing but the extension. Fill also needs a small native
messaging host, because no reasoning model can run inside a browser extension.

<p align="center">
  <img width="800" alt="Brain extension filling a job application from the vault" src="images/brain-extension.gif" />
</p>


---

## Install

1. Open `chrome://extensions` and enable **Developer mode**.
2. **Load unpacked** → select `extensions/brain`.

Installed from PyPI rather than a checkout? The extension ships in the package.
Ask for its path:

```bash
obsidian-wiki info        # → extension: …/obsidian_wiki/_data/extension
```

and load that folder unpacked instead.

That is all capture needs. For form filling, also run:

```bash
extensions/brain/host/install.sh
```

then fully quit Chrome (⌘Q — closing the window is not enough) and reopen it, so
it reads the new host manifest.

The extension carries a fixed public `key`, so its unpacked ID is stable and the
host can be registered before the extension has ever been loaded. A Web Store
listing gets a different ID; pass it in with `install.sh <extension-id>`.

---

## Capture

Pick your vault's `_raw` folder once:

```bash
awk -F= '/^OBSIDIAN_VAULT_PATH=/{print $2 "/_raw"; exit}' "$(git rev-parse --show-toplevel)/.env"
```

Then **Capture current page**, or right-click a page or selection and use the
context menu. Each capture is written as `YYYY-MM-DD-page-title.md` with YAML
frontmatter (title, source URL, timestamps), your optional note, any selected
text, and the readable page text capped at 140,000 characters.

Captures are staged, not finished pages. Promote them with:

```text
/wiki-ingest promote my raw pages
```

---

## Fill form

Open a form, switch to the **Fill form** tab, pick a vault and an engine, click
**Fill from brain**.

```
content script          popup + native host        native host (python)
──────────────────      ───────────────────        ─────────────────────────────
extract form schema  →  sendNativeMessage       →  1. obsidian-wiki context-pack --json
(label, type,                                         deterministic, no LLM
 options, maxLength)                               2. claude -p / codex exec
                                                      subscription-billed
apply values         ←  {fills:[…]}             ←  3. validated {id, value,
+ outline each field                                  confidence, source}
```

The split is the point. **Retrieval never calls a model** — `context-pack` is
plain ranking over the vault, the same machinery `wiki-context-pack` uses. The
model is handed the pages and does one narrow job: map facts onto fields. That
keeps each fill to a single CLI invocation and means the model never gets to
decide what "searching your vault" means.

Filled fields are outlined green (confidence ≥ 0.7) or red (below it, worth
re-reading) and carry a tooltip naming their source page. The popup lists every
value with its confidence and origin.

**It never submits.** Filling is the entire feature.

### Choosing which vault answers

The **Answer from** dropdown lists every vault profile `wiki-switch` knows about
— `Default vault` (whatever `~/.obsidian-wiki/config` currently points at) plus
one entry per `~/.obsidian-wiki/config.<name>`. It is the extension's equivalent
of the `@name` override: a job application answers from `personal`, a vendor
questionnaire from `work`, without re-pointing the symlink for everything else.

A second vault only shows up once it has a profile file. Owning the folder is
not enough — create one with `/wiki-switch new <name>`, or by hand:

```bash
printf '# My other vault\nOBSIDIAN_VAULT_PATH="%s"\n' ~/Knowledge \
  > ~/.obsidian-wiki/config.knowledge
```

If the dropdown shows only `Default vault` when profiles do exist, the staged
host predates this feature — re-run `install.sh` and restart Chrome. The popup
says so explicitly rather than pretending you have one vault.

The choice is remembered per browser profile, so a vault picked once stays
picked. A profile whose `OBSIDIAN_VAULT_PATH` no longer exists is listed as
`(missing)` and cannot be selected — and if it was the remembered one, the popup
says so and falls back to the default rather than quietly answering from a vault
you did not choose. Only the fill side reads this; capture writes to the `_raw`
folder you picked with the folder picker.

### What it will not fill

- Anything the retrieved pages do not support — omitted, never guessed.
- Personal identity fields (name, email, phone, address, ID numbers) unless the
  vault explicitly contains that exact value.
- Passwords and file inputs, which are never read into the schema at all.
- Any value that fails validation against the real form — an option absent from
  the `<select>`, a field id the page never advertised — is dropped by the host
  before it reaches the page.

A field asking for several things at once ("name, email, and company") is
answered with the parts the vault supports, at reduced confidence, rather than
skipped outright.

---

## Getting good fills

Two properties of retrieval decide almost all of the quality.

**Put what matters at the top of the page.** When many pages compete for the
token budget, `context-pack` compresses each one to roughly its opening block.
Anything below that — a table halfway down, a detail in the last section — is
invisible to the model even though the page was retrieved. Keep fillable facts
in the `summary:` frontmatter and the first paragraph.

**Keep one profile page for personal details.** Something like
`entities/<you>.md`, tagged `visibility/pii` so it stays out of public-facing
queries, whose opening paragraph states the values in prose:

```markdown
---
title: Your Name
tags: [owner, profile, visibility/pii]
summary: "Vault owner: <name>, email <email>, GitHub <handle>, site <url>."
---

# Your Name

First name **X**. Email **y@example.com**. GitHub **github.com/z**.
```

Leave unknown fields *absent* rather than filling them with placeholders. A
`TODO` is a value the model can autofill into a real form; an absent field simply
stays blank. Listing the missing field names under a "Not recorded" heading gives
you the checklist without the risk.

Forms whose questions your vault genuinely does not cover will come back mostly
empty. That is the system working — the alternative is plausible fiction in a
form you are about to submit.

---

## Security model

Vault excerpts and scraped form labels are both untrusted input. The context
pack carries an `instruction_policy` string that is forwarded into the prompt
verbatim, and the model is told to treat all page content as data rather than
instruction. The host then re-validates every returned fill against the form
schema, so an injection that convinces the model to emit a value still cannot
write to a field the page never offered.

Nothing leaves your machine except the model call itself, which goes through the
same CLI — and the same account — you already use in the terminal.

---

## Why the host is staged outside the repo

`install.sh` copies the host and a snapshot of the `obsidian_wiki` package into
`~/.obsidian-wiki/brain-fill/` rather than running them from your checkout.
Three things force this, all variations on "Chrome's child processes do not
inherit your shell":

1. **macOS TCC.** `~/Documents` is mode 700 with a TCC ACL. A native messaging
   host inherits Chrome's TCC context, so a checkout living there cannot even be
   exec'd. Chrome reports this as `Native host has exited`, which is
   indistinguishable from a crash.
2. **PATH.** Chrome hands children a minimal PATH, so `claude` and `codex` in
   `~/.local/bin` are invisible. The launcher bakes in the install-time PATH.
3. **USER / LOGNAME.** Claude Code reads its OAuth credentials from the macOS
   login Keychain and needs these set to find them. Without them it reports
   `Not logged in · Please run /login` despite a perfectly valid session.

Re-run `install.sh` after editing the host or updating the package — the staged
copy does not track the repo.

---

## Cost

Retrieval is free. Each fill is one `claude -p` or `codex exec` invocation
billed to your existing subscription. Cost scales with the size of the context
pack, so a tighter `--budget` and a well-summarised vault make fills cheaper as
well as better.

---

## Troubleshooting

Logs live at `~/.obsidian-wiki/brain-fill.log`. Every run brackets itself with
`── start` and `── exit`, which is what separates the failure modes:

| Symptom | Meaning |
|---|---|
| `Native host has exited`, **no** new `── start` | Chrome could not launch the process at all — path or permissions. Re-run `install.sh`. |
| `── start` with no `── exit` | It launched and died; a `fatal:` traceback follows. |
| `── start` … `── exit: clean` but the popup errors | The pipe closed before the answer was ready. |

| Message | Fix |
|---|---|
| `Specified native messaging host not found` | Not registered. Run `install.sh`, ⌘Q Chrome, reopen. |
| `claude: Not logged in` | Launcher missing USER/LOGNAME. Re-run `install.sh`. |
| `No obsidian-wiki with context-pack support` | Staged package snapshot is stale. Re-run `install.sh` — it verifies the subcommand and refuses to install without it. |
| `Read N pages, but none of them answer these fields` | Retrieval worked; the vault does not cover it. See [Getting good fills](#getting-good-fills). |

Drive the host without Chrome at all:

```bash
python3 extensions/brain/host/test_host.py claude          # or: codex
python3 extensions/brain/host/test_host.py claude work     # answer from config.work
python3 extensions/brain/host/test_host.py vaults          # list what the popup would offer
```
