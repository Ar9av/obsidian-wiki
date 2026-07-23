# Git Project Manifest Identity Design

**Date:** 2026-07-24

**Status:** Approved design

**Scope:** Git-backed project entries used by `wiki-update`, `wiki-query`, and `wiki-status`

## Problem

Project entries in `.manifest.json` currently identify source repositories with
`source_cwd`, an absolute path on one machine. The same repository therefore
appears different when two team members clone it to different locations. The
path also leaks local usernames and directory layouts into a shared vault.

The existing `last_commit_synced` cursor is evaluated against the current local
`HEAD`. That makes the tracked knowledge depend on whichever feature branch a
user happens to have checked out, even when the team intends the wiki to
describe the canonical default branch.

## Goals

- Identify the same Git repository consistently across machines, clone paths,
  SSH/HTTPS remote spellings, and local remote aliases.
- Track a canonical remote branch independently of the current checkout.
- Keep absolute clone paths out of the shared manifest and generated project
  frontmatter.
- Preserve existing path-based behavior for local-only repositories.
- Read legacy project entries while writing the new schema for safely
  identified repositories.
- Make identity, delta, migration, and locator behavior deterministic and
  testable without a provider API or network access.
- Leave the existing generic `sources` manifest schema unchanged.

## Non-goals

- Replacing `.manifest.json` with SQLite or a sharded manifest.
- Redesigning generic file, URL, paper, or conversation source identities.
- Solving cross-machine Git merge conflicts for the shared vault.
- Adding GitHub, GitLab, or Bitbucket API integrations.
- Automatically identifying a repository after a remote rename or transfer.
- Ingesting uncommitted changes or arbitrary feature-branch state by default.

## Chosen Approach

Use a deterministic Python core with skill orchestration.

Python modules own Git inspection, identity normalization, manifest
compatibility, atomic updates, local locator state, and machine-readable CLI
output. Skills decide when to invoke those operations and remain responsible
for knowledge distillation and user-facing reporting.

Pure skill instructions were rejected because each agent would independently
reimplement remote normalization and migration behavior. A complete manifest
storage redesign was rejected as outside this feature's scope.

## Architecture

### `obsidian_wiki/git_project.py`

This module performs read-only Git discovery and delta calculation. It does not
read or write the vault.

Its public responsibilities are:

- `normalize_remote_url(url)` — normalize supported SSH, HTTPS, and scp-like
  remote spellings into a stable repository identity.
- `select_canonical_remote(repo, override=None)` — choose an explicit override,
  then `upstream`, then `origin`.
- `resolve_default_ref(repo, remote, branch_override=None)` — return a
  canonical shared ref such as `refs/heads/main`.
- `identify_git_project(repo, ...)` — return the repository identity, canonical
  remote URL, shared tracked ref, local remote alias, target commit, and tree.
- `compute_project_delta(repo, previous_commit, target_commit)` — classify the
  cursor relationship and return commit/file delta metadata.
- `materialize_project_snapshot(repo, target_commit)` — expose committed source
  content matching the cursor.

The module returns typed values and structured errors. It never fetches,
pushes, or calls a hosting-provider API.

### `obsidian_wiki/project_manifest.py`

This module owns project tracking state and local repository locators.

Its responsibilities are:

- Read legacy and version 2 project entries.
- Match the current repository to one unambiguous legacy entry.
- Write only version 2 entries for remotely identified Git projects.
- Preserve generic `sources`, `stats`, and unknown top-level manifest fields.
- Atomically update `.manifest.json`.
- Detect any concurrent manifest change before replacing an entry.
- Migrate safe legacy entries and explicitly relink renamed repositories.
- Read and write vault-scoped local locator state.

### CLI

The deterministic operations are exposed as JSON-capable commands:

```text
obsidian-wiki project-identify <repo> [--remote <name>] [--branch <name>] [--slug <slug>]
obsidian-wiki project-delta <repo> --since <sha>
obsidian-wiki project-locate <vault> <repo-id>
obsidian-wiki manifest migrate-projects <vault> [--write]
obsidian-wiki manifest relink-project <vault> --from <repo-id> --repo <path> [--write]
```

Migration and relinking default to dry-run. Mutation requires `--write`.

### Skills

- `wiki-update` calls identity, delta, and snapshot operations, distills the
  committed snapshot, then advances the version 2 cursor.
- `wiki-query` resolves a shared `repo_id` through local locator state. Missing
  local code never prevents a knowledge answer.
- `wiki-status` reports counts for version 2 projects, legacy projects, and
  unresolved locators.
- `llm-wiki` defines the project identity schema while leaving generic source
  identity rules intact.

## Repository Identity

### Canonical remote selection

For a project without an existing version 2 entry, selection order is:

1. Explicit remote override.
2. A remote named `upstream`.
3. A remote named `origin`.

An invalid explicit override is a hard error. It does not silently fall back.

Once a version 2 entry exists, its canonical URL is authoritative. Each clone
finds whichever local remote normalizes to that URL. Local alias names such as
`origin` and `upstream` never become part of the shared identity.

### URL normalization

Normalization must:

- Parse HTTPS, SSH URI, and scp-like Git remote syntax.
- Remove credentials and SSH usernames.
- Lowercase the hostname.
- Retain a non-default port so distinct servers do not collide.
- Normalize leading, duplicate, and trailing path separators.
- Remove one trailing `.git`.
- Produce a repository ID in `host/path` form.
- Produce a credential-free canonical remote URL deterministically from the
  normalized identity, rather than preserving the input transport spelling.
- Treat common SSH and HTTPS spellings of the same default-port repository as
  identical.
- Preserve path case on unknown providers. Provider-specific case folding is
  allowed only where repository paths are documented as case-insensitive.

Example:

```text
git@github.com:acme/payment-service.git
https://github.com/acme/payment-service.git
```

Both normalize to:

```text
github.com/acme/payment-service
```

They also serialize the same identity URL:

```text
https://github.com/acme/payment-service.git
```

The identity URL is a stable manifest representation, not a fetch instruction.
Git operations use the matching clone-local remote URL and alias.

### Tracked ref

The shared manifest stores a canonical remote-side ref:

```text
refs/heads/main
```

It never stores a clone-local remote-tracking ref such as
`refs/remotes/upstream/main`.

On each machine, the resolver maps the canonical remote URL to a local remote
alias, then maps the shared ref to:

```text
refs/remotes/<local-alias>/main
```

For a new project, branch selection order is:

1. Explicit branch override.
2. The local symbolic remote default branch for the selected remote.

The resolver does not guess `main` or `master`. If the default branch is not
available in local metadata, the command requests an explicit branch.

## Shared Manifest Schema

The canonical repository identity is the project key:

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
        "tree": "abcdef0123456789abcdef0123456789abcdef01",
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

- The map key uses the `git:` namespace and normalized repository ID.
- `project_slug` controls vault placement but is not repository identity.
- One `project_slug` may belong to only one repository identity. A collision
  requires an explicit alternative slug and is never silently overwritten.
- `tracked_ref` defines the shared knowledge scope.
- `cursor.commit` is the immutable version successfully distilled.
- `cursor.tree` avoids work when a merge commit does not change tracked
  content.
- Version 2 entries never store `source_cwd` or local remote aliases.
- Generic `sources` entries are untouched.

## Project Page Frontmatter

New or updated Git-backed project pages use:

```yaml
source_repo: git:github.com/acme/payment-service
source_ref: refs/heads/main
```

They do not add an absolute `source_path`.

Readers continue accepting legacy `source_path` frontmatter. A successful
project update replaces it with `source_repo` and `source_ref`.

## Vault-scoped Local Locator

Clone paths and local aliases are stored outside the shared vault:

```text
~/.obsidian-wiki/state/<vault-id>/repositories.json
```

Example:

```json
{
  "version": 1,
  "repositories": {
    "git:github.com/acme/payment-service": {
      "preferred_path": "/Users/alice/src/payment-service",
      "remote_name": "upstream",
      "last_seen": "2026-07-24T10:00:00+08:00"
    }
  }
}
```

Before using `preferred_path`, the resolver verifies that the directory exists
and that one of its remotes still matches the stored project identity. A stale
or mismatched locator is ignored.

## `wiki-update` Data Flow

1. Discover the Git root from the current working directory.
2. Identify the canonical remote and shared tracked ref.
3. Record or refresh the local locator.
4. Look up the version 2 entry by `git:<repo_id>`.
5. If absent, find one unambiguous legacy entry using its project slug and
   `source_cwd`.
6. Resolve the shared tracked ref to a local remote-tracking ref and immutable
   target commit.
7. Classify the previous cursor:
   - Same commit: no content delta.
   - Ancestor: incremental delta.
   - Missing, divergent, or no longer reachable: full scan.
8. Read content that exactly matches the target commit:
   - Use the current worktree only when it is clean and `HEAD` equals the
     target.
   - Otherwise materialize tracked files from `git archive <target>` in a
     temporary directory.
9. Run project scanning, AST extraction, and distillation against that source
   snapshot.
10. Write all intended wiki pages.
11. Re-read the manifest and verify that its full fingerprint has not changed.
12. Advance the cursor to the target commit only after all wiki writes
    succeed.
13. Atomically replace the manifest.

Feature branches and uncommitted changes are excluded by default. A project can
track a different committed remote branch through an explicit shared branch
override.

If there is no content delta but a legacy entry can be safely converted, the
operation may still rewrite that project entry as version 2.

## `wiki-query` Data Flow

1. Resolve a project page to its version 2 entry using `project_slug` or
   `source_repo`.
2. Look up `git:<repo_id>` in vault-scoped locator state.
3. Revalidate the local clone identity.
4. Include a `Source code:` path only after successful validation.
5. If the locator is missing or stale, answer from wiki content without a code
   path.
6. Continue supporting legacy `source_cwd`, marked internally as legacy.

## Migration

`manifest migrate-projects` inspects each legacy project entry.

Dry-run classifies entries as:

- **Convertible:** source path exists, is a Git repository, and has a resolvable
  canonical remote and branch.
- **Legacy local-only:** repository has no remote.
- **Unavailable:** source path does not exist on this machine.
- **Full scan required:** identity is known, but the previous commit is not an
  ancestor of the tracked ref.
- **Collision:** multiple legacy entries resolve to one repository identity.

With `--write`, only unambiguous convertible entries are replaced. A reachable
`last_commit_synced` becomes the version 2 cursor. An unreachable cursor is
omitted so the next update performs a full scan. Page lists and the newest
valid synchronization timestamp are preserved.

Collisions are never automatically merged. The command reports all colliding
keys and leaves them unchanged.

## Explicit Repository Relinking

Remote rename and repository transfer cannot be inferred reliably without a
provider API. Recovery is explicit:

```text
obsidian-wiki manifest relink-project <vault> \
  --from git:github.com/old-org/repo \
  --repo /local/path/to/renamed-repo \
  --write
```

Relinking:

1. Verifies that the old entry exists.
2. Computes the new identity from the supplied repository.
3. Refuses to overwrite an existing new key.
4. Preserves pages and a cursor only when the old commit exists in the new
   repository and is valid for the tracked ref.
5. Clears an invalid cursor so the next update performs a full scan.
6. Updates local locator state.

## Atomicity and Concurrent Modification

Manifest writes use a temporary file in the manifest's directory, flush file
contents, call `fsync`, replace the destination with `os.replace`, and `fsync`
the parent directory where the platform supports it.

Before replacement, `project_manifest.py` re-reads the file and compares its
full content fingerprint with the fingerprint observed at operation start. Any
change aborts the manifest update, including changes to another project or to
generic sources. Generated pages remain in place, the cursor does not advance,
and a later run safely reprocesses the delta. This intentionally favors
duplicate work over lost manifest updates.

A vault-scoped local lock serializes cooperating obsidian-wiki processes on one
machine during the final compare-and-replace phase. Cross-machine serialization
and Git merge policy remain outside this feature.

Malformed or unreadable JSON is a hard error. It is never interpreted as an
empty manifest.

## Snapshot Boundaries

The committed snapshot contains tracked repository files only. The snapshot
layer detects submodule gitlinks and likely Git LFS pointer content and reports
them as skipped when their real content cannot be materialized locally. It does
not silently ingest pointer metadata as source content.

Temporary snapshot directories are cleaned after success and failure.

## Error Handling

| Condition | Result |
|---|---|
| Current directory is not in a Git repository | Stop without creating an entry |
| Repository has no remote | Continue using legacy path mode |
| Explicit remote does not exist | Hard error; no fallback |
| No local remote matches a version 2 canonical URL | Locator unresolved; update stops |
| Remote-tracking branch is missing | Stop and suggest fetching the matching remote |
| Default branch cannot be resolved offline | Require explicit branch |
| Previous cursor is missing or divergent | Full scan |
| Snapshot creation fails | Clean up and leave pages/cursor unchanged |
| Locator path is missing or has a different identity | Ignore locator; query still answers |
| Manifest changes during the operation | Preserve pages, refuse cursor advance |
| Project slug belongs to a different repository | Require an explicit alternative slug |
| Manifest JSON is malformed | Hard error; never overwrite |
| Submodule/LFS content is unavailable | Report skipped content |

CLI exit codes:

- `0` — success.
- `2` — usage or configuration error.
- `3` — Git identity or ref cannot be resolved.
- `4` — migration or relinking conflict.
- `5` — malformed manifest or concurrent modification.

## Testing

### Unit tests

`git_project.py` tests cover:

- SSH, HTTPS, and scp-like normalization.
- Credential removal, `.git` stripping, path normalization, case policy, and
  non-default ports.
- Explicit, `upstream`, and `origin` selection order.
- Mapping a shared branch to differently named local remotes.
- Symbolic default branch and explicit branch resolution.
- Same, ancestor, divergent, and missing cursor relationships.

`project_manifest.py` tests cover:

- Version 1/version 2 dual-read and version 2 single-write.
- Removal of `source_cwd` from converted entries.
- Preservation of generic sources, stats, and unknown fields.
- Atomic replacement failure.
- Full-manifest fingerprint conflicts, including unrelated source changes.
- Locator validation and stale paths.
- Project slug ownership collisions.
- Migration collisions and relink safety.

### Integration tests

Temporary repositories verify:

1. Two clones at different paths and with different remote aliases produce the
   same project identity.
2. A fork with `origin` and `upstream` selects `upstream`.
3. A checked-out feature branch does not change the default-branch snapshot.
4. Uncommitted changes do not enter the snapshot.
5. Force-push or divergent history triggers a full scan.
6. A repository without a remote remains legacy.
7. Migration preserves reachable cursors and clears unreachable cursors.
8. Explicit relinking preserves pages and valid cursors.
9. Malformed manifests, snapshot failures, and locator mismatches do not
   advance the cursor.
10. Temporary snapshots are cleaned in success and failure paths.

### Compatibility tests

- Existing generic source cache and delta tests continue passing.
- Legacy manifests remain readable by `wiki-update` and `wiki-query`.
- Missing locators do not prevent knowledge answers.
- Skill documentation no longer treats `source_cwd` as authoritative for
  version 2 projects.
- Tests complete without `git fetch`, provider credentials, or network access.

## Acceptance Criteria

Given two team members with independent clones of the same canonical
repository:

- Both produce the same `git:<repo_id>` manifest key.
- The shared manifest and generated project frontmatter contain no absolute
  clone paths.
- Both resolve the same shared branch and target commit from equivalent local
  remote-tracking state.
- Feature branches and uncommitted changes do not alter shared project
  knowledge.
- Existing version 1 vaults continue working and can migrate incrementally.
- Generic source tracking behavior does not change.
- All existing and new automated tests pass.

## Rollout

1. Add deterministic identity, snapshot, manifest, and locator modules with
   tests.
2. Add CLI commands and JSON output contracts.
3. Update `wiki-update` and `wiki-query` to use dual-read/single-write behavior.
4. Update `wiki-status`, `llm-wiki`, documentation, and examples.
5. Ship migration and relinking commands.
6. Keep legacy readers until a separate future design explicitly removes them.
