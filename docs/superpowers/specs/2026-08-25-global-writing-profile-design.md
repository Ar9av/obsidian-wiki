# Global Wiki Writing Profile

- Status: Approved design
- Date: 2026-08-25

## Summary

Add a user-editable global `WRITING.md` profile that supplies writing preferences to every wiki skill used from any project. The profile is loaded through the existing configuration and owner-rule model, with more specific project and vault guidance taking precedence over the global defaults.

The feature is prompt guidance only. It does not add a rule language, deterministic style linting, or content transformation.

## Goals

- Let a user define language, tone, structure, terminology, evidence, and other wiki-writing habits once.
- Create the profile during `obsidian-wiki setup` without requiring a questionnaire.
- Apply the profile to wiki content generated or edited from any project.
- Preserve the existing XDG global-config path and legacy `~/.obsidian-wiki` fallback.
- Support vault- and project-specific overrides through the existing `AGENTS.md` conventions.
- Keep machine-readable metadata, safety constraints, and provenance requirements intact.
- Make setup reruns non-destructive.

## Non-goals

- The profile does not affect ordinary agent replies, code, commit messages, or unrelated project documentation.
- The profile does not validate or block a write when a preference is missed.
- The profile does not replace `AGENTS.md`, the Config Resolution Protocol, or the wiki schema.
- The profile does not rewrite existing pages or migrate existing style.
- The HTTP/MCP server does not reinterpret or transform API-provided content.
- No `OBSIDIAN_WRITING_PROFILE` environment variable is introduced in the first version.

## Existing extension points

The implementation reuses three existing mechanisms:

1. `GLOBAL_CONFIG_DIR` already resolves the XDG path and the legacy fallback.
2. `llm-wiki/SKILL.md` already owns the Config Resolution Protocol and tells skills to read the vault's `AGENTS.md`.
3. Skills already share the framework schema through `llm-wiki`, while individual write skills define operation-specific behavior.

The global profile is therefore a new file in the existing global config directory, not a second configuration system.

## Design

### 1. Profile storage

The user-facing profile is:

```text
<global-config-dir>/WRITING.md
```

For a new installation this resolves to:

```text
~/.config/obsidian-wiki/WRITING.md
```

If the legacy global config directory is active, the profile is stored beside its existing `config` file:

```text
~/.obsidian-wiki/WRITING.md
```

The repository contains one canonical starter template at:

```text
.skills/llm-wiki/references/WRITING.md
```

The packaged CLI can locate the same asset through its bundled skills directory. `setup.sh`, the CLI setup command, and the agent-driven `wiki-setup` flow all use this template so their behavior cannot drift.

`WRITING.md` is created only when it does not already exist. Re-running setup never overwrites it.

### 2. Profile format

The profile is ordinary Markdown. There is no YAML schema, DSL, required frontmatter, or parser-specific syntax. The starter template provides useful headings while allowing the user to write, remove, rename, or extend them:

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

Natural-language rules such as “先講結論” or “技術名詞保留英文，第一次出現時補中文說明” are valid. Empty sections have no effect.

### 3. Effective rule precedence

The effective instruction stack is:

```text
framework invariants
  > current task and skill requirements
  > current project AGENTS.md guidance
  > vault AGENTS.md guidance
  > global WRITING.md preferences
```

The first two layers are not user-style preferences and cannot be disabled. They cover safety, data preservation, required frontmatter, provenance, source tracking, staged writes, paper-specific templates, and other operation contracts.

Within user-defined writing guidance, unspecified rules are inherited and a more specific rule wins when it addresses the same topic. A project may therefore say “for this project, use English headings” without replacing the rest of the global profile.

The vault's `AGENTS.md` keeps its current owner-authority semantics. Project-specific writing guidance follows the host agent's existing `AGENTS.md` context; the documentation recommends a `## Wiki Writing Rules` section so writing preferences remain distinguishable from build and code instructions.

### 4. Loading contract

Every skill that composes or edits natural-language Markdown in the vault follows this sequence:

1. Resolve the vault and config using the existing Config Resolution Protocol.
2. Resolve the global config directory using the existing XDG/legacy rule.
3. Read `<global-config-dir>/WRITING.md` when present.
4. Apply the vault `AGENTS.md` and current project `AGENTS.md` writing guidance.
5. Apply the effective guidance while performing the skill's existing operation.

`llm-wiki/SKILL.md` owns the common loading contract. Each write-capable skill references that contract in its setup section rather than duplicating the profile algorithm. The rule is capability-based: any future skill that writes wiki Markdown must load the contract, so a fixed list of skill names does not become a missed-update trap.

The profile applies to natural-language fields and body content, including page titles, summaries, headings, link display text, index descriptions, hot-cache takeaways, and readouts. It does not alter YAML syntax, JSON manifests, structured log records, or existing staged content being promoted unchanged.

Read-only skills do not need to load the profile. A skill that only moves, archives, exports, or promotes already-written content preserves that content instead of regenerating it. The API server remains a pass-through writer because it has no LLM prompt stage.

### 5. Setup behavior

`obsidian-wiki setup` performs the following after resolving the global config directory:

1. Create the directory if needed.
2. Copy the canonical `WRITING.md` template only when the destination is absent.
3. Report the profile path in the setup summary.
4. Leave an existing profile byte-for-byte unchanged.

`setup.sh` and the agent-driven `wiki-setup` instructions provide the same behavior and path. No editor is launched and no detailed writing questionnaire is required; the user edits the template when ready.

Existing installations remain valid. If the profile is absent, skills use current framework defaults exactly as they do today.

### 6. Error handling

- Missing profile: silently use framework defaults; setup may report that the file was not present before creation.
- Empty profile: treat it as no custom preferences.
- Read failure or invalid text encoding: warn the user, skip the profile, and continue with framework defaults. Do not block a wiki write solely because an optional preference file is unreadable.
- Conflicting user preferences: use the more specific project/vault rule when the intent is clear; preserve framework and task requirements regardless.
- Existing profile during setup: never overwrite, merge, or rewrite it.

### 7. Documentation and verification

Update the following documentation surfaces:

- `docs/configuration.md`: profile path, precedence, scope, and fallback behavior.
- `docs/installation.md`: setup creates `WRITING.md` and the user edits it after installation.
- `.skills/llm-wiki/SKILL.md`: loading contract and profile scope.
- `.skills/wiki-setup/SKILL.md`: setup behavior and starter template reference.
- Relevant write-capable skill instructions: reference the shared contract.

Automated checks should cover:

- Fresh XDG setup creates `<config-dir>/WRITING.md`.
- Existing legacy setup creates the profile beside `~/.obsidian-wiki/config`.
- Re-running setup preserves a user-edited profile.
- The packaged/source canonical template is available to setup.
- The documented write-capable skill contract is present for the skills that generate or edit wiki prose.

Natural-language adherence is not unit-tested because this feature intentionally provides prompt guidance rather than deterministic validation. A manual acceptance check should customize the profile with a distinctive language or tone rule, run a wiki-writing skill from a separate project, and verify that the generated prose follows the rule while frontmatter and tracking files remain valid.

## Compatibility and rollout

The change is additive and backward-compatible:

- No existing vault files are migrated.
- No existing config keys are removed or rewritten.
- No profile means no behavior change.
- Legacy global config locations continue to work.
- Existing `AGENTS.md` owner rules remain authoritative.
- Staged-write review and all existing provenance/trust workflows remain unchanged.

## Acceptance criteria

The design is complete when all of the following are true:

1. A fresh `obsidian-wiki setup` creates `WRITING.md` at the resolved global config directory.
2. A user can edit that Markdown file and have its preferences available to wiki-writing skills from another project.
3. Vault and project `AGENTS.md` guidance can override global preferences without replacing unrelated inherited rules.
4. Framework invariants and operation-specific requirements remain effective even when a profile conflicts with them.
5. Missing or unreadable optional profile content never causes data loss or blocks a write.
6. Re-running setup preserves user customizations.
7. The behavior is documented consistently for CLI, shell, and agent-driven setup.
