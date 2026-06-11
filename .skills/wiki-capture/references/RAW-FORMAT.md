# Raw File Format Reference

Full specification for `_raw/` files written by `wiki-capture` (quick mode).
These files are designed to be promoted by `/wiki-ingest`.

## Frontmatter

```yaml
---
title: "<Descriptive cluster title>"
category: skills
tags:
  - topic/<primary-tech>
  - <1-3 additional domain tags from vault taxonomy>
summary: "<1–2 sentences, ≤200 chars — what is this finding about?>"
tier: supporting
related: []
extends: null
contradicts: null
superseded_by: null
capture_source: claude-session
project: "<project name or null>"
base_confidence: 0.75
lifecycle: draft
lifecycle_changed: <YYYY-MM-DD>
provenance:
  extracted: 0.85
  inferred: 0.15
sources:
  - "<project> session (<YYYY-MM-DD>)"
---
```

## Body: Finding Block

For bugs and fixes:

```markdown
## <Finding Title>

**Problem:** <what was non-obvious or broken — be specific about the symptom>

**Root cause:** <why it happened — the underlying mechanism, not just the error message>

**Fix:**
```<lang>
// ❌ before
// ✅ after
```

**Confirmed by:** <build pass / test pass / live app / error disappeared>
```

For gotchas and API quirks (no traditional bug/fix arc):

```markdown
## <Gotcha Title>

**Behavior:** <what surprised the user>

**Explanation:** <why it works this way>

**Workaround / Pattern:** <what to do instead>

**Confirmed by:** <how it was validated>
```

Omit sections that have nothing to say. Add a `**Notes:**` block at the end for caveats,
related edge cases, or follow-up questions.

---

## Provenance + Confidence Calibration

Apply provenance markers inline per the `llm-wiki` convention:

| Marker | When to use |
|---|---|
| *(none)* | Explicitly stated in the conversation |
| `^[inferred]` | Synthesized or generalized beyond what was directly said |
| `^[ambiguous]` | Uncertain, potentially incomplete, or contradicted elsewhere |

Use the table below to set `base_confidence` and the `provenance` split:

| Evidence strength | `extracted` | `inferred` | `base_confidence` |
|---|---|---|---|
| Build error + test pass | 0.90 | 0.10 | 0.80–0.90 |
| Fix applied, appeared to work | 0.75 | 0.25 | 0.70–0.75 |
| Discussed, not fully confirmed | 0.60 | 0.40 | 0.60 |
| Reasoned from a single case | 0.50 | 0.50 | 0.55 |

`extracted + inferred` should sum to 1.0 (or include a small `ambiguous` fraction if applicable).

---

## Multiple Findings in One File

When several related findings belong to the same topic cluster, place them sequentially
in the body — each as its own finding block with a `##` heading. Use a short intro paragraph
before the first block to explain what ties them together.

```markdown
# Swift 6 Concurrency Gotchas

Findings from migrating an iOS app to strict concurrency checking. All confirmed during
the build phase.

## Actor reentrancy in async forEach

**Problem:** ...

## MainActor isolation not inferred on @Observable

**Problem:** ...
```
