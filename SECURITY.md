# Security Policy

## Supported versions

obsidian-wiki is released from `main` with CalVer tags (`vYYYY.MM.N`). Only the
latest release on PyPI receives fixes — there are no maintenance branches for
older tags. If you are on an older version, upgrade before reporting:

```bash
pip install --upgrade obsidian-wiki
```

## Reporting a vulnerability

Report privately through GitHub's
[**Report a vulnerability**](https://github.com/Ar9av/obsidian-wiki/security/advisories/new)
form, which opens a draft advisory only the maintainers can see. Please do not
open a public issue for anything exploitable.

Include what you have: the version (`obsidian-wiki --version`), the steps or a
vault layout that reproduces it, and what an attacker gets out of it. A rough
report filed early beats a polished one filed late.

Expect an acknowledgement within a week. Once a fix ships, the advisory is
published with credit unless you ask otherwise.

## What is in scope

The threat model worth reporting against is **a vault, source document, or
agent session whose content you do not control**, because ingestion is the one
place where untrusted input meets your machine:

- Writes that escape `OBSIDIAN_VAULT_PATH` — a crafted page title, source path,
  or `[[link]]` that makes a skill or the CLI read or write outside the vault.
- Secrets leaving the vault: a config value, `.env` line, or API key that ends
  up in a page, an export bundle, or `log.md`.
- Prompt injection in ingested content that redirects the agent into running
  commands or exfiltrating vault contents, where the framework could reasonably
  have contained it.
- Anything in `obsidian-wiki serve` reachable from off-machine. It binds to
  loopback by default; a bypass of that, or an endpoint that serves files from
  outside the vault, is in scope.

## What is not in scope

- **Your own agent doing what you told it.** The skills are instructions for an
  agent you run, with the permissions you grant it. Reporting that an agent with
  write access can write is not a vulnerability.
- Exposing a vault yourself, by committing it to a public repo, by passing
  `--host 0.0.0.0`, or by pointing the tool at a directory you share.
- Vulnerabilities in Obsidian, Python, or a dependency — report those upstream.
  Tell us if obsidian-wiki is what makes one reachable.
- Scanner findings from prose. The `vault/` directory in this repo is a real
  knowledge base, so notes *about* sandboxes, permissions, and approval
  bypasses are content, not configuration.
