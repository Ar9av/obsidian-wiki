"""Graphify focus-map provider: reads a Graphify graph already in the project.

Graphify (https://github.com/Graphify-Labs/graphify) writes a NetworkX
node-link graph to ``graphify-out/graph.json``. This provider only reads that
file; it never runs graphify, so building and refreshing the graph stay the
user's call (and their token spend). Nodes carry ``source_file`` and
``source_location`` ("L31"); links carry ``relation`` and a ``confidence`` of
EXTRACTED, INFERRED or AMBIGUOUS, which becomes the item's evidence so
wiki-update can weigh an inferred edge below an extracted one.
"""

from __future__ import annotations

import json
from pathlib import Path

from obsidian_wiki.code_understanding import (
    ProviderError,
    _finalize,
    _item,
    _rel,
    _tracked_files_only,
)

GRAPH_RELATIVE_PATH = Path("graphify-out") / "graph.json"


def graph_path(project: Path) -> Path:
    return project / GRAPH_RELATIVE_PATH


def graph_state(project: Path) -> tuple[bool, bool, str]:
    """Return (present, fresh, detail): fresh means graph.json is no older than
    the newest committed file (no git or no files counts as fresh)."""
    path = graph_path(project)
    if not path.is_file():
        return False, False, f"no graph (missing {GRAPH_RELATIVE_PATH.as_posix()})"
    out_prefix = str((project / "graphify-out").resolve())
    try:
        mtimes = [
            p.stat().st_mtime
            for p in (_tracked_files_only(project) or [])
            if p.exists() and not str(p.resolve()).startswith(out_prefix)
        ]
        fresh = not mtimes or path.stat().st_mtime >= max(mtimes)
    except OSError:
        fresh = True
    return True, fresh, "fresh" if fresh else "stale (graph.json older than sources)"


def _lines(location: object) -> list[int]:
    text = str(location or "").lstrip("Ll").split("-")[0]
    return [int(text)] if text.isdigit() else []


class GraphifyProvider:
    def __init__(self, project: Path) -> None:
        self.project = project

    def _load(self) -> tuple[list[dict], list[dict]]:
        path = graph_path(self.project)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProviderError(
                f"graphify backend requested but {GRAPH_RELATIVE_PATH.as_posix()} "
                "was not found (run graphify on the project first)"
            ) from exc
        except (OSError, ValueError) as exc:
            raise ProviderError(f"graphify graph.json is unreadable: {exc}") from exc
        if not isinstance(data, dict):
            raise ProviderError("graphify graph.json is not a node-link graph")
        nodes = [n for n in data.get("nodes") or [] if isinstance(n, dict) and "id" in n]
        links = data.get("links") if "links" in data else data.get("edges")
        return nodes, [l for l in links or [] if isinstance(l, dict)]

    def _node_item(self, node: dict) -> dict:
        return _item(
            str(node.get("label") or node["id"]),
            str(node.get("file_type") or "symbol"),
            _rel(self.project, node.get("source_file") or ""),
            _lines(node.get("source_location")),
        )

    def build_focus_map(
        self,
        seed_files: list[str],
        origin_files: set[str],
        max_symbols: int,
        warnings: list[str],
    ) -> list[dict]:
        present, fresh, detail = graph_state(self.project)
        if present and not fresh:
            warnings.append(f"graphify graph is {detail}; re-run graphify to refresh it")
        nodes, links = self._load()
        by_id = {str(n["id"]): n for n in nodes}
        seed_set = set(seed_files)
        seeds = [n for n in nodes if _rel(self.project, n.get("source_file") or "") in seed_set]
        seed_ids = {str(n["id"]) for n in seeds}

        items: list[dict] = []
        seen: set[tuple] = set()

        def add(item: dict) -> None:
            key = (item["symbol"], item["file"], tuple(item["lines"]))
            if key not in seen:
                seen.add(key)
                items.append(item)

        degree: dict[str, int] = {}
        for link in links:
            for end in ("source", "target"):
                node_id = str(link.get(end))
                degree[node_id] = degree.get(node_id, 0) + 1

        # Most-connected seed symbols first: graphify's "god nodes" are the
        # abstractions the rest of the code hangs on.
        for node in sorted(seeds, key=lambda n: (-degree.get(str(n["id"]), 0), str(n["id"]))):
            item = self._node_item(node)
            if item["file"] in origin_files:
                item["evidence"] = item["relation"] = "changed-file"
            else:
                item["relation"] = "defines"
                item["evidence"] = "graphify-node"
            add(item)

        neighbours: list[dict] = []
        for link in links:
            src, tgt = str(link.get("source")), str(link.get("target"))
            if (src in seed_ids) == (tgt in seed_ids):
                continue
            seed, other = (src, tgt) if src in seed_ids else (tgt, src)
            if other not in by_id:
                continue
            item = self._node_item(by_id[other])
            seed_label = str(by_id[seed].get("label") or seed)
            item["relation"] = f"{link.get('relation') or 'related'}-{seed_label}"
            item["via"] = seed_label
            item["depth"] = 1
            item["evidence"] = f"graphify-{str(link.get('confidence') or 'EXTRACTED').lower()}"
            neighbours.append(item)
        # EXTRACTED edges before INFERRED/AMBIGUOUS ones.
        neighbours.sort(key=lambda it: (it["evidence"] != "graphify-extracted", it["symbol"]))
        for item in neighbours:
            add(item)
        if not seeds:
            warnings.append("no graphify nodes matched the seed files")
        return _finalize(items, max_symbols)
