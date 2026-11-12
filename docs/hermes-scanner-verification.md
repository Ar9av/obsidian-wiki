# Hermes scanner compatibility verification

This is an opt-in local gate, not a skill installer or a scanner-policy exception.
A successful source scan does not certify a delivered bundle, a hosted MCP server,
a published source, or deployment. Keep these statuses separate.

## Prerequisites and boundaries

- Read repository policy and preserve the original working tree. Use separate
  worktrees for prose, retrieval and verification changes; record a combined
  candidate explicitly. Do not use a live editable installation as a sandbox.
- Use Python 3.12 for the inspected `skills-guard-v10` scanner. The wiki source
  harness needs no runtime dependencies. The declared test setup uses `pytest`
  and, on Windows, `tzdata`; install only in a dedicated test environment.
- Use only operator-reviewed local candidate Python: the runtime-discovery probe
  imports it. `-I -S -B` prevents ambient package selection and bytecode writes;
  it is **not** an OS sandbox for malicious candidate code.
- Supply an already reviewed local Hermes scanner file and its SHA-256. Nothing
  fetches or installs a scanner automatically. Record the source revision, tag,
  full dirty status, digest and scanner version. A clean tag is not independent
  verification of release signatures.
- No force, trust override, scanner edit, exclusion file, cached-verdict editing,
  or private-URL-policy relaxation belongs in this workflow.
- Explicitly set `TMPDIR`, `TEMP` and `TMP` to an approved scratch directory;
  Windows pytest may otherwise use a different system temp directory.

## Full source / delivered artifact gate

Run from the isolated candidate, with its dedicated Python:

```text
python -B tools/verify_hermes_artifacts.py --candidate <absolute-candidate> --scanner <reviewed-hermes-root>/tools/skills_guard.py --scanner-sha256 <reviewed-sha256> --output <new-evidence-file.json>
```

The report records complete file inventories and hashes, all findings, unchanged
community policy and `force=False`. It refuses skill exclusion files and symlinks
instead of silently dropping operational content, and lists extensions the native
scanner cannot inspect. Such files fail this full-artifact gate (`gate_passed`),
while the unchanged native scanner decision is retained separately (`allowed`).
It checks that a fresh isolated interpreter imports the
candidate CLI and resolves its assets to the candidate, and that the selected
skill names have one canonical source definition.

Exit 0 means the requested artifact scan gate passed; exit 1 means blocked, and
exit 2 means a prerequisite failed. A missing scanner must not count as a pass.
The supported scanner version is currently `skills-guard-v10` plus an explicit
reviewed digest. Other versions require review and extension of the checks.

For real adapter-generated artifacts or native installed copies, add
`--delivered-skills <actual-delivered-skill-root>`. The gate scans those complete
artifacts too and requires byte-identical inventories to source, reporting missing,
extra and changed files. **Do not manufacture this evidence by copying the source
and naming it delivered.** Adapter fixtures must be labeled fixtures, not public
HTTP/GitHub delivery. The comparison cannot establish where files came from;
`delivery_provenance` remains unverified and requires separately reviewed adapter
or installer logs and source provenance. A byte-identical copied tree is not
native-install evidence.

Run focused tests with `OW_SCANNER_FILE` set to that reviewed scanner path:

```text
python -B -m pytest tests/test_hermes_artifacts.py tests/test_scanner_prose.py tests/test_native_mcp_guidance.py tests/test_staging.py -q
```

Without an explicit scanner the optional scanner tests skip with a stated reason;
that is not scanner acceptance. Malicious role override, instruction injection and
credential-exfiltration examples live only in the test harness. They are scanned
as complete synthetic bundles and must stay blocked. They are not operational
skill instructions and are not part of URL skill delivery.

## Native installation boundary

Use `tools/verify_hermes_native.py --help` for the separately guarded local HTTP
probe. It defaults to a prerequisite failure until launcher/bootstrap review is
explicitly acknowledged with `--bootstrap-reviewed` after separate operator
approval. A new data root can trigger dependency preparation before the installer
runs; inspect that behavior first. It uses a new explicit disposable home, not a
named/live profile, and retains evidence. Never copy live configuration or
credentials into it. Source
provenance, support-file delivery and check/update/local-edit preservation each
need their own read-back; CLI exit zero alone is insufficient.

The inspected Hermes URL adapter guards requests against private targets,
including loopback. If it refuses the local candidate, retain that failure and
stop: do not modify the adapter, enable private URLs, or substitute the previously
published baseline. A public candidate URL then requires separate publication
approval. Controlled HTTP/adapter/update fixtures can establish behavior below
that boundary but do not establish public source delivery or deployment.

No-update checks do not prove changed-upstream replacement. Test replacement with
controlled changing fixtures where supported and explicitly report any gap.

### Native probe exit/status contract

This incomplete probe **never returns exit 0 for native acceptance**. Exit 2 means
prerequisites or execution failed (the default unapproved-bootstrap path is
`prerequisite_failed`). Exit 1 with `blocked` means installation/content comparison
failed. Exit 1 with `content_present_provenance_unverified` means matching content
was observed but provenance/check/update acceptance remains unfinished. Do not
turn byte equality into a success gate. A mocked CLI regression exercises this
last branch; copying fixture files is not native installation evidence.

## Retrieval and security scope

The native-MCP skill consumes host results directly, with no bundled Python
retrieval helper or custom response schema. Documentation tests preserve the
privacy/error/host-control instructions; they do not prove model behavior or
network enforcement. No live connection or real secret is required for those
tests. Client/server DNS, redirects, transport bounds, remote deployment behavior
and data retention require separate verification.
Live keyless MCP interoperability, authenticated service access, publication and
live installation each remain separate approvals. No passing test authorizes
wiki writes, hooks, shared config updates or profile migration.
