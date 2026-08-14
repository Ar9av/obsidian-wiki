"""Builtin focus-map provider: regex AST extraction + ripgrep references.

Zero-dependency backend for obsidian_wiki.code_understanding. Seeds are the
class/function symbols ast_extractor finds in the seed files; ripgrep adds
cross-file reference items (best-effort — a missing rg only degrades output).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from obsidian_wiki.code_understanding import _item, _SUBPROCESS_TIMEOUT


class BuiltinProvider:
    def __init__(self, project: Path) -> None:
        self.project = project

    def build_focus_map(
        self,
        seed_files: list[str],
        origin_files: set[str],
        max_symbols: int,
        warnings: list[str],
    ) -> list[dict]:
        from obsidian_wiki.ast_extractor import extract
        from obsidian_wiki.code_understanding import _finalize

        data = extract(self.project)
        nodes = data["nodes"]
        degree: dict[str, int] = {}
        for e in data["edges"]:
            degree[e["source"]] = degree.get(e["source"], 0) + 1
            degree[e["target"]] = degree.get(e["target"], 0) + 1

        seed_set = set(seed_files)
        defined = [n for n in nodes if n["kind"] in ("class", "function")]
        items: list[dict] = []
        seen: set[tuple] = set()
        for n in defined:
            if n["file"] not in seed_set:
                continue
            if (n["label"], n["file"]) in seen:
                continue
            seen.add((n["label"], n["file"]))
            changed = n["file"] in origin_files
            item = _item(n["label"], n["kind"], n["file"], [n["line"]])
            item["evidence"] = "changed-file" if changed else "ast"
            item["relation"] = "changed-file" if changed else "defines"
            items.append(item)
        items = self._rg_references(items, seen, defined, seed_set, warnings)
        items.sort(
            key=lambda it: (
                0 if it["evidence"] == "changed-file" else 1,
                0 if it["evidence"] in ("changed-file", "ast") else 1,
                -degree.get(it["symbol"], 0),
                it["symbol"],
            )
        )
        return _finalize(items, max_symbols)

    def _rg_references(
        self,
        items: list[dict],
        seen: set[tuple],
        defined: list[dict],
        seed_set: set[str],
        warnings: list[str],
    ) -> list[dict]:
        """Add cross-file references via ripgrep (best-effort; never crash)."""
        if shutil.which("rg") is None:
            warnings.append("rg not available; skipping cross-file reference detection")
            return items
        seed_files = sorted(f for f in seed_set if (self.project / f).exists())
        # References to seed symbols in files other than their defining file.
        for n in defined:
            if n["file"] not in seed_set:
                continue
            for f, line in self._rg(n["label"], None):
                if f != n["file"]:
                    item = _item(n["label"], n["kind"], f, [line])
                    item["evidence"] = "rg-reference"
                    item["relation"] = "reference"
                    item["via"] = n["label"]
                    self._merge(items, seen, item)
                    break
        # External symbols referenced inside seed files.
        for n in defined:
            if n["file"] in seed_set or not seed_files:
                continue
            if not any(n["label"] in _file_text(self.project / f) for f in seed_files):
                continue
            for f, line in self._rg(n["label"], seed_files):
                if f not in seed_set:
                    continue
                via = next((m["label"] for m in defined if m["file"] == f), "")
                item = _item(n["label"], n["kind"], f, [line])
                item["evidence"] = "rg-reference"
                item["relation"] = "reference"
                item["via"] = via
                self._merge(items, seen, item)
                break
        return items

    def _rg(self, name: str, files: list[str] | None) -> list[tuple[str, int]]:
        """rg --json matches of \\bname\\b; returns [(file, line), ...]."""
        args = ["rg", "--json", "-n", "--no-messages", "--no-heading", f"\\b{name}\\b"]
        if files:
            args.extend(files)
        try:
            proc = subprocess.run(
                args,
                cwd=str(self.project),
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        matches: list[tuple[str, int]] = []
        for raw in proc.stdout.splitlines():
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            if obj.get("type") != "match":
                continue
            path = obj.get("data", {}).get("path", {}).get("text", "")
            line = obj.get("data", {}).get("line_number")
            if path and isinstance(line, int):
                matches.append((path, line))
        return matches

    @staticmethod
    def _merge(items: list[dict], seen: set[tuple], item: dict) -> None:
        key = (item["symbol"], item["file"])
        if key in seen:
            return
        seen.add(key)
        items.append(item)


def _file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
