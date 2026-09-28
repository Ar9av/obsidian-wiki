---
status: proposed
---

# `/ingest-url` should snapshot to `_raw/` then ingest as a file

Live URLs change and disappear, so a page whose only distill provenance is `url:` in `sources:` is not lastingly verifiable. A later change should fetch the page, write markdown under `_raw/` (then `_raw/_archived/` as today), and run normal file ingest so **`snapshots:`** can point at that file. `sources:` may still record `url:` as origin. Out of scope for ADR 0001 (optional `snapshots:`, do not rewrite `sources:`).
