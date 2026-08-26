# Global Wiki Writing Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision a global, user-editable `WRITING.md` profile during setup and make every wiki content-writing skill apply it as prompt guidance with vault/project overrides.

**Architecture:** Reuse `GLOBAL_CONFIG_DIR` for the profile location and add one canonical starter asset under `.skills/llm-wiki/references/WRITING.md`. The CLI and shell setup copy that asset only when the global profile is absent; skills consume it through a shared contract in `llm-wiki/SKILL.md`, while `AGENTS.md` remains the more-specific owner layer.

**Tech Stack:** Python 3.9+ standard library CLI, Markdown skill instructions, POSIX shell setup, pytest/unittest test suite, Hatch wheel packaging.

**Spec:** `docs/superpowers/specs/2026-08-25-global-writing-profile-design.md`

## Global Constraints

- Store the user profile as `<resolved global config directory>/WRITING.md`; do not add `OBSIDIAN_WRITING_PROFILE` in this version.
- Preserve XDG-first resolution and the legacy `~/.obsidian-wiki` fallback.
- Create the profile only when it is absent; never overwrite, merge, or rewrite a user-edited profile during setup.
- Apply preferences only to wiki content generation/editing; do not affect ordinary agent replies, code, commits, or unrelated project documentation.
- Keep framework invariants, task/skill requirements, safety, provenance, frontmatter, staged writes, and machine-readable tracking formats higher priority than user style preferences.
- Do not add dependencies, a rule parser, deterministic style linting, or a migration of existing pages.
- Preserve the existing unstaged `.gitignore` change in the worktree; do not include it in feature commits.

---

## File Map

### Create

- `.skills/llm-wiki/references/WRITING.md` — canonical starter profile copied by all setup paths.
- `tests/test_writing_profile_contract.py` — regression checks for the shared skill contract and documented scope.

### Modify

- `obsidian_wiki/cli.py:367-407, 957-978` — create the profile during CLI setup without overwriting it.
- `setup.sh:116-154` — keep source-install setup behavior in parity with the CLI.
- `.skills/llm-wiki/SKILL.md:532-595` — define the shared profile resolution contract and precedence.
- `.skills/wiki-setup/SKILL.md:12-70` — make agent-driven setup create the same profile from the canonical asset.
- `tests/test_write_config_preserves_user_keys.py` — test XDG, legacy, and non-destructive CLI profile setup.
- `tests/test_scripts_packaging.py` — ensure the canonical profile asset and bundled skills tree are package inputs.
- `tests/test_sync_setup_parity.py` — pin the shell setup's profile-copy behavior.
- `docs/configuration.md` — document path, precedence, scope, and fallback behavior.
- `docs/installation.md` — document setup creation and post-setup editing.
- Content-producing skill docs listed in Task 4 — reference the shared profile contract.

### Explicitly unchanged

- `obsidian_wiki/server.py` — API content remains pass-through.
- `.skills/wiki-stage-commit/SKILL.md`, `.skills/wiki-export/SKILL.md`, `.skills/wiki-rebuild/SKILL.md`, and `.skills/graph-colorize/SKILL.md` behavior — these preserve, move, archive, serialize, or edit machine configuration rather than drafting wiki prose.
- Existing `.gitignore` user changes.

---

### Task 1: Add the canonical writing-profile template

**Files:**
- Create: `.skills/llm-wiki/references/WRITING.md`
- Modify: `tests/test_scripts_packaging.py`

**Interfaces:**
- Produces the exact starter content that CLI, shell setup, and agent-driven setup will copy.
- The template is bundled automatically because `pyproject.toml` already force-includes the complete `.skills/` tree as `obsidian_wiki/_data/skills`.

- [ ] **Step 1: Write the failing packaging/template tests**

Add these constants and tests to `tests/test_scripts_packaging.py`:

```python
WRITING_PROFILE_TEMPLATE = ROOT / ".skills" / "llm-wiki" / "references" / "WRITING.md"


def test_writing_profile_template_exists(self) -> None:
    self.assertTrue(WRITING_PROFILE_TEMPLATE.is_file())
    body = WRITING_PROFILE_TEMPLATE.read_text()
    self.assertIn("# Wiki Writing Profile", body)
    self.assertIn("## Language", body)
    self.assertIn("## Conditional Rules", body)


def test_wheel_force_includes_skills_tree(self) -> None:
    mapping = self.pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    self.assertEqual(mapping.get(".skills"), "obsidian_wiki/_data/skills")
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
pytest tests/test_scripts_packaging.py -q
```

Expected: `test_writing_profile_template_exists` fails because the canonical asset does not yet exist.

- [ ] **Step 3: Add the minimal canonical template**

Create `.skills/llm-wiki/references/WRITING.md` with exactly this starter structure:

```markdown
# Wiki Writing Profile

> These preferences apply to wiki content only.
> Preserve framework schema, provenance, and safety requirements.

## Language

## Tone and Voice

## Structure and Content Density

## Formatting

## Evidence and Uncertainty

## Terminology

## Linking and Citations

## Avoid

## Conditional Rules

### Concepts

### References

### Project Pages
```

Do not add frontmatter or machine-only keys to this file.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run:

```bash
pytest tests/test_scripts_packaging.py -q
```

Expected: all packaging/template tests pass.

- [ ] **Step 5: Commit the isolated asset change**

```bash
git add .skills/llm-wiki/references/WRITING.md tests/test_scripts_packaging.py
git commit -m "feat: add wiki writing profile template"
```

### Task 2: Provision `WRITING.md` from `obsidian-wiki setup`

**Files:**
- Modify: `obsidian_wiki/cli.py:367-407, 957-978`
- Modify: `tests/test_write_config_preserves_user_keys.py`

**Interfaces:**
- Add `ensure_global_writing_profile() -> Path` beside `write_config()`.
- The function returns `GLOBAL_CONFIG_DIR / "WRITING.md"`; it copies from `skills_dir() / "llm-wiki" / "references" / "WRITING.md"` only when the destination does not exist.
- `cmd_setup()` calls the helper immediately after `write_config(vault_path)` so `--project-only` and vault setup both provision the global profile.

- [ ] **Step 1: Write failing CLI setup tests**

Extend `tests/test_write_config_preserves_user_keys.py` with:

```python
def test_setup_creates_global_writing_profile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()

    proc = _setup(home, vault)
    assert proc.returncode == 0, proc.stderr

    profile = _config_dir(home) / "WRITING.md"
    template = REPO_ROOT / ".skills" / "llm-wiki" / "references" / "WRITING.md"
    assert profile.read_text() == template.read_text()


def test_setup_preserves_existing_writing_profile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config_dir = home / ".config" / "obsidian-wiki"
    config_dir.mkdir(parents=True)
    profile = config_dir / "WRITING.md"
    profile.write_text("# My custom profile\n\nUse concise Traditional Chinese.\n")
    vault = tmp_path / "vault"
    vault.mkdir()

    proc = _setup(home, vault)
    assert proc.returncode == 0, proc.stderr
    assert profile.read_text() == "# My custom profile\n\nUse concise Traditional Chinese.\n"
```

Also assert `WRITING.md` exists in the legacy-config test after setup.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run:

```bash
pytest tests/test_write_config_preserves_user_keys.py -q
```

Expected: the new profile tests fail because `cmd_setup()` does not create the file yet.

- [ ] **Step 3: Implement the minimal CLI helper**

Add this helper near `write_config()`:

```python
def ensure_global_writing_profile() -> Path:
    target = GLOBAL_CONFIG_DIR / "WRITING.md"
    if target.exists():
        return target
    template = skills_dir() / "llm-wiki" / "references" / "WRITING.md"
    target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return target
```

Call it after `write_config(vault_path)` in `cmd_setup()` and print the resolved path in the setup summary. Do not add an environment variable or modify `write_config()`'s user-key preservation logic.

- [ ] **Step 4: Run the focused tests to verify they pass**

Run:

```bash
pytest tests/test_write_config_preserves_user_keys.py tests/test_xdg_config_location.py -q
```

Expected: all setup/config tests pass, including both XDG and legacy behavior.

- [ ] **Step 5: Commit the CLI provisioning change**

```bash
git add obsidian_wiki/cli.py tests/test_write_config_preserves_user_keys.py
git commit -m "feat: provision global wiki writing profile"
```

### Task 3: Keep shell and agent-driven setup in parity

**Files:**
- Modify: `setup.sh:116-154`
- Modify: `.skills/wiki-setup/SKILL.md:12-70`
- Modify: `tests/test_sync_setup_parity.py`

**Interfaces:**
- `setup.sh` copies `.skills/llm-wiki/references/WRITING.md` into `$GLOBAL_CONFIG_DIR/WRITING.md` only when the destination is absent.
- The `wiki-setup` skill resolves the same global directory and copies the same canonical template. In a packaged install, use `$OBSIDIAN_WIKI_REPO/skills/llm-wiki/references/WRITING.md`; in a source checkout, use `$OBSIDIAN_WIKI_REPO/.skills/llm-wiki/references/WRITING.md`.

- [ ] **Step 1: Write the parity assertions**

Add to `SetupShDelegatesToCliTest` in `tests/test_sync_setup_parity.py`:

```python
def test_creates_global_writing_profile_from_canonical_template(self) -> None:
    self.assertIn("WRITING.md", self.setup_sh)
    self.assertIn("llm-wiki/references/WRITING.md", self.setup_sh)
```

- [ ] **Step 2: Run the parity test to verify it fails**

Run:

```bash
pytest tests/test_sync_setup_parity.py -q
```

Expected: the new assertion fails because `setup.sh` does not copy the profile yet.

- [ ] **Step 3: Add the non-destructive shell copy**

After `GLOBAL_CONFIG_DIR` is created and before the shell setup writes its config, add:

```bash
WRITING_PROFILE="$GLOBAL_CONFIG_DIR/WRITING.md"
WRITING_TEMPLATE="$SKILLS_DIR/llm-wiki/references/WRITING.md"
if [ ! -e "$WRITING_PROFILE" ]; then
  cp "$WRITING_TEMPLATE" "$WRITING_PROFILE"
fi
```

Update `.skills/wiki-setup/SKILL.md` with the same behavior and explicit instructions to preserve an existing profile. Do not make setup ask additional writing-style questions.

- [ ] **Step 4: Run shell and parity checks**

Run:

```bash
bash -n setup.sh
pytest tests/test_sync_setup_parity.py -q
```

Expected: shell syntax and setup parity tests pass.

- [ ] **Step 5: Commit setup parity**

```bash
git add setup.sh .skills/wiki-setup/SKILL.md tests/test_sync_setup_parity.py
git commit -m "feat: keep writing profile setup paths aligned"
```

### Task 4: Define the shared profile contract and wire every prose-writing skill

**Files:**
- Modify: `.skills/llm-wiki/SKILL.md:532-595`
- Modify: `.skills/wiki-capture/SKILL.md`
- Modify: `.skills/wiki-ingest/SKILL.md`
- Modify: `.skills/wiki-update/SKILL.md`
- Modify: `.skills/wiki-research/SKILL.md`
- Modify: `.skills/wiki-synthesize/SKILL.md`
- Modify: `.skills/wiki-agent/SKILL.md`
- Modify: `.skills/wiki-narrate/SKILL.md`
- Modify: `.skills/wiki-digest/SKILL.md`
- Modify: `.skills/wiki-dashboard/SKILL.md`
- Modify: `.skills/wiki-status/SKILL.md`
- Modify: `.skills/wiki-lint/SKILL.md`
- Modify: `.skills/wiki-import/SKILL.md`
- Modify: `.skills/wiki-dedup/SKILL.md`
- Modify: `.skills/cross-linker/SKILL.md`
- Modify: `.skills/claude-history-ingest/SKILL.md`
- Modify: `.skills/codex-history-ingest/SKILL.md`
- Modify: `.skills/copilot-history-ingest/SKILL.md`
- Modify: `.skills/hermes-history-ingest/SKILL.md`
- Modify: `.skills/openclaw-history-ingest/SKILL.md`
- Modify: `.skills/pi-history-ingest/SKILL.md`
- Create: `tests/test_writing_profile_contract.py`

**Interfaces:**
- The central section is named `Writing Profile Resolution` in `.skills/llm-wiki/SKILL.md`.
- Each listed skill adds this exact setup guidance before drafting or rewriting prose:

```markdown
**Writing profile:** Before drafting or rewriting natural-language Markdown, read and apply the `Writing Profile Resolution` section in `llm-wiki/SKILL.md`. Framework schema, provenance, safety, and operation-specific requirements take precedence.
```

- `wiki-status` applies the profile only to generated `_insights.md` prose; its analyser snapshot remains verbatim.
- `wiki-lint` applies it only to generated consolidation reports; deterministic findings and fixes keep their existing formats.
- `wiki-import` preserves imported source prose and applies the profile only to newly generated metadata or stubs.
- `wiki-dashboard` applies it only to optional Markdown dashboard prose; `.base` syntax remains unchanged.

- [ ] **Step 1: Write the contract regression test**

Create `tests/test_writing_profile_contract.py` with a fixed inventory of current prose-writing skills and assertions that the shared contract is present:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "Writing Profile Resolution"
REQUIRED_SKILLS = (
    "wiki-capture",
    "wiki-ingest",
    "wiki-update",
    "wiki-research",
    "wiki-synthesize",
    "wiki-agent",
    "wiki-narrate",
    "wiki-digest",
    "wiki-dashboard",
    "wiki-status",
    "wiki-lint",
    "wiki-import",
    "wiki-dedup",
    "cross-linker",
    "claude-history-ingest",
    "codex-history-ingest",
    "copilot-history-ingest",
    "hermes-history-ingest",
    "openclaw-history-ingest",
    "pi-history-ingest",
)


def test_llm_wiki_defines_writing_profile_resolution() -> None:
    body = (ROOT / ".skills" / "llm-wiki" / "SKILL.md").read_text()
    assert CONTRACT in body
    assert "WRITING.md" in body
    assert "AGENTS.md" in body


def test_every_current_prose_writer_references_the_contract() -> None:
    for skill in REQUIRED_SKILLS:
        body = (ROOT / ".skills" / skill / "SKILL.md").read_text()
        assert CONTRACT in body, skill
        assert "WRITING.md" in body, skill
```

- [ ] **Step 2: Run the contract test to verify it fails**

Run:

```bash
pytest tests/test_writing_profile_contract.py -q
```

Expected: the test fails because the central contract and skill references do not yet exist.

- [ ] **Step 3: Add the central resolution contract**

Add a `Writing Profile Resolution` section to `.skills/llm-wiki/SKILL.md` that specifies:

1. Resolve the global config directory with the existing XDG/legacy algorithm.
2. Read `WRITING.md` when present; missing/empty profiles mean no custom preferences.
3. Apply project and vault `AGENTS.md` writing guidance over global preferences.
4. Keep framework invariants and operation requirements above all user preferences.
5. Apply the profile to natural-language fields and body content, not YAML, JSON, structured logs, or pass-through content.
6. Warn and continue with defaults when an optional profile cannot be read.

Keep this section declarative and tool-agnostic; do not add a runtime parser or environment variable.

- [ ] **Step 4: Add the one-line contract reference to each listed skill**

Insert the exact guidance from the Interfaces block into each skill's existing `Before You Start` or equivalent writing step. Preserve each skill's current order, frontmatter rules, staged-write behavior, provenance rules, and QMD handling.

Do not add the profile reference to pass-through/machine-output skills. For skills with mixed behavior, document the narrow scope specified above rather than applying style to machine data.

- [ ] **Step 5: Run the contract test to verify it passes**

Run:

```bash
pytest tests/test_writing_profile_contract.py -q
```

Expected: all contract assertions pass.

- [ ] **Step 6: Commit the shared contract and skill wiring**

```bash
git add .skills/llm-wiki/SKILL.md .skills/wiki-capture/SKILL.md .skills/wiki-ingest/SKILL.md .skills/wiki-update/SKILL.md .skills/wiki-research/SKILL.md .skills/wiki-synthesize/SKILL.md .skills/wiki-agent/SKILL.md .skills/wiki-narrate/SKILL.md .skills/wiki-digest/SKILL.md .skills/wiki-dashboard/SKILL.md .skills/wiki-status/SKILL.md .skills/wiki-lint/SKILL.md .skills/wiki-import/SKILL.md .skills/wiki-dedup/SKILL.md .skills/cross-linker/SKILL.md .skills/claude-history-ingest/SKILL.md .skills/codex-history-ingest/SKILL.md .skills/copilot-history-ingest/SKILL.md .skills/hermes-history-ingest/SKILL.md .skills/openclaw-history-ingest/SKILL.md .skills/pi-history-ingest/SKILL.md tests/test_writing_profile_contract.py
git commit -m "docs: apply global writing profile contract"
```

### Task 5: Document the user-facing configuration

**Files:**
- Modify: `docs/configuration.md`
- Modify: `docs/installation.md`

**Interfaces:**
- Documentation names the exact file `WRITING.md`, the XDG and legacy paths, the project/vault/global precedence, and the prompt-only scope.
- Documentation explicitly says setup preserves an existing profile and missing profiles retain framework defaults.

- [ ] **Step 1: Add the configuration documentation**

Add a “Global wiki writing profile” section to `docs/configuration.md` immediately after global config resolution. Include:

- `~/.config/obsidian-wiki/WRITING.md` as the new default.
- `~/.obsidian-wiki/WRITING.md` when the legacy directory is active.
- A short starter example with `## Language`, `## Tone and Voice`, and `## Avoid`.
- Precedence: framework/task requirements, project `AGENTS.md`, vault `AGENTS.md`, global `WRITING.md`.
- Scope: wiki Markdown prose only; no lint/blocking behavior.
- Missing/empty/unreadable profile fallback.

- [ ] **Step 2: Add the installation documentation**

Update `docs/installation.md` to say that all setup entry points create the global profile, that the file is not overwritten on reruns, and that users can edit it to define their writing habits for every project using wiki skills.

- [ ] **Step 3: Run documentation and existing sync checks**

Run:

```bash
pytest tests/test_readme_sync.py tests/test_writing_profile_contract.py -q
```

Expected: documentation-related regression checks pass; no README translation change is required because this feature is documented under `docs/`.

- [ ] **Step 4: Commit the documentation**

```bash
git add docs/configuration.md docs/installation.md
git commit -m "docs: explain global wiki writing profile"
```

### Task 6: Run the complete verification pass

**Files:**
- Test: all existing `tests/` plus the new profile tests.
- Inspect: `git status --short` and the commits created by Tasks 1–5.

**Interfaces:**
- No new runtime dependency is allowed.
- The only expected pre-existing worktree change is the user's `.gitignore` modification.

- [ ] **Step 1: Run focused feature tests**

```bash
pytest tests/test_scripts_packaging.py tests/test_write_config_preserves_user_keys.py tests/test_xdg_config_location.py tests/test_sync_setup_parity.py tests/test_writing_profile_contract.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run shell and syntax checks**

```bash
bash -n setup.sh
python -m compileall -q obsidian_wiki
```

Expected: both commands exit 0.

- [ ] **Step 3: Run the full test suite**

```bash
pytest -q
```

Expected: the full suite passes with no new warnings or failures.

- [ ] **Step 4: Run a temporary-home setup smoke test**

Use a temporary home and vault so the real global profile is not changed:

```bash
TEST_HOME="$(mktemp -d)"
TEST_VAULT="$(mktemp -d)"
HOME="$TEST_HOME" PYTHONPATH="$(pwd)" python -m obsidian_wiki.cli setup --vault "$TEST_VAULT" --project-only
test -s "$TEST_HOME/.config/obsidian-wiki/WRITING.md"
```

Expected: setup reports the profile path and the file contains `# Wiki Writing Profile`.

- [ ] **Step 5: Verify the worktree and commits**

```bash
git status --short
git log --oneline -6
```

Expected: the feature commits contain only the planned files; the pre-existing `.gitignore` change remains uncommitted and intact.

## Plan Self-Review Checklist

- Spec coverage: storage, template, setup parity, precedence, loading, error handling, scope, docs, tests, compatibility, and acceptance criteria are covered by Tasks 1–6.
- Placeholder scan: no `TODO`, `TBD`, “implement later”, or unspecified edge-case steps remain.
- Type consistency: `ensure_global_writing_profile() -> Path` is the only new Python interface; all callers use its returned path only for reporting.
- Scope: one subsystem—global wiki writing guidance—implemented through the existing config/setup/skill documentation surfaces.
