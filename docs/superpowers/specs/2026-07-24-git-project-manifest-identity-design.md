# Git Project Manifest Identity — Small Safe MVP

**Date:** 2026-07-24

**Status:** Awaiting written-spec review

**Scope:** Git-backed project entries used by `wiki-update` and `wiki-query`

## Problem

Project entries in `.manifest.json` currently use `source_cwd`, an absolute
clone path, as their source locator. Two team members therefore describe the
same repository differently when it is cloned into different directories. The
shared vault also exposes local usernames and filesystem layouts.

The current `last_commit_synced` workflow compares against the local checkout,
so a feature branch or uncommitted change can accidentally influence shared
project knowledge.

## MVP Goal

Give Git-backed projects a portable repository identity while refusing to
distill content that does not exactly match the configured canonical remote
branch.

The MVP must:

- Normalize SSH and HTTPS remotes into the same `repo_id`.
- Select an explicit remote, then `upstream`, then `origin`.
- Store `repo_id`, a canonical remote URL, `refs/heads/<branch>`, and a full
  commit cursor.
- Read legacy project entries and lazily replace one after a successful update.
- Stop writing absolute clone paths into shared Git project entries and project
  page frontmatter.
- Require a clean worktree whose `HEAD` exactly matches the local
  remote-tracking commit for the configured shared branch.
- Keep generic `sources` behavior unchanged.

## Explicitly Deferred

The MVP does not include:

- Temporary snapshots or detached worktrees.
- A persistent `repo_id → local_path` locator.
- Bulk migration or migration dashboards.
- Repository rename/transfer relinking commands.
- Manifest compare-and-swap, locking, or cross-machine serialization.
- Git LFS and submodule materialization.
- `wiki-status` extensions.
- Provider APIs or automatic `git fetch`.
- Redesign of non-Git source identities.

These are follow-up features, not hidden requirements for this implementation.

## Chosen Approach

Add one deterministic Python module plus two CLI commands. Skills keep their
existing orchestration role.

### `obsidian_wiki/git_project.py`

This module owns:

- Remote URL parsing and normalization.
- Canonical remote selection.
- Remote default-branch resolution.
- Mapping a shared `refs/heads/<branch>` to a clone-local
  `refs/remotes/<alias>/<branch>`.
- Clean-worktree and `HEAD == tracked commit` safety checks.
- Commit ancestry and delta classification.
- Legacy/version 2 project-entry conversion.
- Atomic project manifest updates.

Keeping these related behaviors together limits the MVP to one new module. Its
internal functions remain separated into Git identity, safety checks, and
manifest adapter sections so they can be split later without changing the CLI
contract.

### CLI

```text
obsidian-wiki project-state <repo> \
  [--expected-repo-id <id>] \
  [--remote <name>] [--branch <name>] [--since <sha>] [--json]

obsidian-wiki project-record <vault> \
  --repo <path> --slug <slug> \
  [--expected-repo-id <id>] \
  [--remote <name>] [--branch <name>] \
  [--page <vault-relative-path>]... [--json]
```

`project-state` is read-only. It reports identity, shared ref, local tracked
commit, safety status, and optional delta classification. When
`--expected-repo-id` is supplied, it must find a local remote with that
identity instead of applying new-project remote selection.

`project-record` runs the same safety checks again, then atomically creates or
updates one version 2 project entry. `wiki-update` calls it only after all page
writes succeed.

## Repository Identity

### Remote selection

For a project without a version 2 entry:

1. Use an explicit `--remote`.
2. Otherwise use `upstream` when present.
3. Otherwise use `origin`.
4. If none exists, report `legacy_local_only`.

An invalid explicit remote is a hard error. It never falls back.

For an existing version 2 entry, its canonical remote identity is
authoritative. The local clone must contain a remote whose normalized identity
matches it.

### URL normalization

Normalization must:

- Accept HTTPS, SSH URI, and scp-like Git syntax.
- Remove credentials and SSH usernames.
- Lowercase the hostname.
- Retain non-default ports.
- Normalize redundant and trailing path separators.
- Remove one trailing `.git`.
- Produce `repo_id` as `host/path`.
- Serialize a deterministic credential-free canonical URL from the normalized
  identity instead of retaining the input transport spelling.
- Preserve path case for unknown providers; provider-specific case folding is
  allowed only for documented case-insensitive hosts.

For example:

```text
git@github.com:acme/payment-service.git
https://github.com/acme/payment-service.git
```

Both produce:

```text
repo_id: github.com/acme/payment-service
canonical_url: https://github.com/acme/payment-service.git
```

The canonical URL is an identity representation, not a fetch instruction.

### Shared branch

The manifest stores:

```text
refs/heads/main
```

It never stores the local alias:

```text
refs/remotes/upstream/main
```

On each clone, the matching local remote alias is discovered by normalized URL,
then the shared branch is mapped to its remote-tracking ref.

For a new entry, branch selection order is:

1. Explicit `--branch`.
2. The selected remote's local symbolic default branch.

The MVP does not guess `main` or `master`. Missing branch metadata requires an
explicit branch or a user-performed fetch.

## Manifest Schema

The version 2 project key is its canonical Git identity:

```json
{
  "projects": {
    "git:github.com/acme/payment-service": {
      "project_schema": 2,
      "kind": "git",
      "repo_id": "github.com/acme/payment-service",
      "project_slug": "payment-service",
      "remote": {
        "canonical_url": "https://github.com/acme/payment-service.git"
      },
      "tracked_ref": "refs/heads/main",
      "cursor": {
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "synced_at": "2026-07-24T10:00:00+08:00"
      },
      "pages_in_vault": [
        "projects/payment-service/payment-service.md"
      ]
    }
  }
}
```

Rules:

- The project key is `git:<repo_id>`.
- `project_slug` controls vault placement but is not identity.
- One slug may belong to only one repository identity.
- `tracked_ref` is always a shared `refs/heads/<branch>` value.
- `cursor.commit` is the full commit successfully distilled.
- Version 2 entries never contain `source_cwd` or local remote aliases.
- Generic `sources`, `stats`, and unknown top-level fields are preserved.

## Project Page Frontmatter

New or updated Git-backed project pages use:

```yaml
source_repo: git:github.com/acme/payment-service
source_ref: refs/heads/main
```

They do not add an absolute `source_path`.

Readers continue accepting legacy `source_path`. A successful lazy upgrade
replaces it with `source_repo` and `source_ref`.

## Safety Gate

Before reading project content, `project-state` verifies:

1. The shared tracked branch maps to an existing local remote-tracking ref.
2. `git status --porcelain` is empty, including untracked files.
3. Local `HEAD` equals the remote-tracking commit exactly.

If any check fails, `wiki-update` stops before writing pages or advancing the
cursor.

This replaces snapshot support in the MVP. The user must fetch and check out
the canonical branch before updating the shared wiki.

## `wiki-update` Flow

1. Find the Git root and determine the intended project slug.
2. Read the manifest and find a unique version 2 entry by `project_slug`, or a
   legacy entry by `source_cwd` and slug.
3. For a version 2 entry, call `project-state` with its `repo_id` as
   `--expected-repo-id` and its shared branch as `--branch`. For a new or
   legacy entry, call `project-state` with ordinary remote selection.
4. If it reports `legacy_local_only`, continue the existing path-based
   personal workflow and do not create a version 2 entry.
5. If the safety gate fails, stop with exact remediation guidance.
6. Confirm that the resolved `git:<repo_id>` key does not conflict with another
   project entry.
7. Classify the old cursor:
   - Same commit: no content delta.
   - Ancestor of `HEAD`: incremental delta.
   - Missing, divergent, or unreachable: full scan.
8. Scan and distill the verified current worktree.
9. Write the intended wiki pages.
10. Call `project-record` to re-run the safety gate and atomically write the
    version 2 entry with the current full commit.

If no content delta exists but a legacy entry is safely identifiable,
`project-record` may still perform the lazy upgrade.

If `project-record` observes a different `HEAD` or dirty worktree after page
writes, it refuses to advance the cursor. Generated pages remain and the next
run safely reprocesses the project.

## `wiki-query` Flow

The MVP does not persist local clone paths.

For a version 2 project:

1. Inspect the current working directory.
2. If it is inside a Git repository with the matching `repo_id`, use that root
   for the optional `Source code:` line.
3. Otherwise answer from wiki content without a local code path.

For a legacy entry, `source_cwd` remains available as a compatibility fallback
after verifying that the path exists.

## Lazy Compatibility

Legacy entries remain readable indefinitely during the MVP.

On successful `wiki-update`:

- A resolvable remote identity creates the version 2 key.
- `last_commit_synced` becomes `cursor.commit` only when it resolves and is an
  ancestor of the tracked commit.
- Otherwise the operation performs a full scan and records the verified
  current commit.
- Page paths and the newest valid sync timestamp are preserved.
- The migrated legacy key is removed only in the same successful atomic
  manifest replacement.

If multiple legacy entries map to one `repo_id`, or a slug is already owned by
another identity, the upgrade stops and reports the collision. The MVP does not
merge or relink entries.

## Atomic Manifest Write

`project-record`:

1. Parses the existing manifest and treats malformed JSON as a hard error.
2. Preserves unrelated top-level fields.
3. Writes a temporary file in the manifest directory.
4. Flushes and `fsync`s the temporary file.
5. Replaces `.manifest.json` with `os.replace`.
6. `fsync`s the parent directory where supported.

This prevents partial JSON files. It does not provide compare-and-swap or
cross-machine conflict resolution; those remain explicitly deferred.

## Error Handling

| Condition | Result |
|---|---|
| Not inside a Git repository | Stop without creating a project entry |
| No Git remote | Continue existing legacy path mode |
| Explicit remote is invalid | Hard error |
| Existing canonical remote has no matching local alias | Stop and report required remote |
| Default branch metadata is unavailable | Require `--branch` or user-performed fetch |
| Remote-tracking branch is missing | Stop and suggest fetching the matching remote |
| Worktree is dirty or has untracked files | Stop before wiki writes |
| `HEAD` differs from tracked remote commit | Stop and request checkout/update |
| Old cursor is divergent or unreachable | Full scan after the safety gate passes |
| Slug or identity collision | Stop; do not merge automatically |
| Manifest JSON is malformed | Hard error; never overwrite |
| State changes before `project-record` | Refuse cursor advance |

CLI exit codes:

- `0` — safe/successful.
- `2` — usage or explicit configuration error.
- `3` — Git identity/ref cannot be resolved.
- `4` — unsafe worktree or branch state.
- `5` — malformed manifest or project collision.

## Tests

### Unit tests

- SSH, HTTPS, and scp-like normalization.
- Credential removal, `.git` stripping, path and port handling.
- Explicit, `upstream`, and `origin` selection order.
- Shared branch to local remote-tracking ref mapping.
- Expected repository identity overriding new-project remote selection.
- Symbolic default branch and explicit branch resolution.
- Clean/dirty/untracked worktree classification.
- `HEAD` alignment with the tracked commit.
- Same, ancestor, divergent, and missing cursor classification.
- Version 1/version 2 dual-read and version 2 single-write.
- Preservation of generic sources, stats, and unknown fields.
- Atomic replacement failure and malformed JSON.
- Identity and slug collisions.

### Integration tests

Using temporary bare repositories and clones:

1. Two clone paths and different remote aliases produce the same project key.
2. A fork with `origin` and `upstream` selects `upstream`.
3. A feature branch is rejected.
4. Uncommitted and untracked content is rejected.
5. A clean checkout matching the remote branch is accepted.
6. Divergent history triggers a full scan.
7. A repository without a remote remains legacy.
8. A legacy entry upgrades lazily after a successful update.
9. Malformed manifests are never overwritten.

### Compatibility tests

- Existing generic source cache and delta tests continue passing.
- Legacy manifests remain readable.
- `wiki-query` still answers when no matching clone is in the current CWD.
- Tests require no network, provider token, or automatic fetch.

## Acceptance Criteria

Given two team members with clean clones of the same canonical repository and
equivalent remote-tracking state:

- Both produce the same `git:<repo_id>` key.
- Shared project entries and updated project pages contain no absolute clone
  path.
- Both track the same shared branch and full commit cursor.
- Feature branches, uncommitted files, and untracked files are rejected before
  distillation.
- Legacy path-based projects continue working and upgrade lazily.
- Generic source tracking behavior does not change.
- All existing and new tests pass.

## Expected Size

The MVP is expected to touch 6–10 files:

- One new Python module.
- CLI wiring.
- Focused unit and temporary-repository integration tests.
- `wiki-update`, `wiki-query`, and `llm-wiki` instructions.
- Relevant README/schema examples.

Expected implementation size is approximately 600–1,000 changed lines,
including tests and documentation.
