"""Codegraph focus-map provider: the optional codegraph CLI (JSON output).

Talks to the codegraph binary (https://github.com/ar9av/codegraph) over
subprocess. Ensures the project index exists (init) and is current (sync),
then queries impact/callers/callees per seed symbol. Hard subprocess failure
raises ProviderError; malformed JSON entries are skipped with a warning.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from obsidian_wiki.code_understanding import (
    _item,
    _rel,
    _SUBPROCESS_TIMEOUT,
    ProviderError,
    index_state,
)


class CodeGraphProvider:
    def __init__(self, bin_path: str, project: Path, proc_env: dict[str, str]) -> None:
        self.bin_path = bin_path
        self.project = project
        self.proc_env = proc_env

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                [self.bin_path, *args],
                cwd=str(self.project),
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
                env=self.proc_env,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProviderError(f"codegraph command failed: {exc}") from exc

    def _check(self, proc: subprocess.CompletedProcess, command: str) -> None:
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise ProviderError(f"codegraph {command} failed: {detail}")

    def ensure_index(self) -> None:
        initialized, fresh, _ = index_state(self.project)
        if initialized and fresh:
            return
        command = "sync" if initialized else "init"
        self._check(self._run([command, str(self.project)]), command)

    def build_focus_map(
        self,
        seed_files: list[str],
        origin_files: set[str],
        max_symbols: int,
        warnings: list[str],
    ) -> list[dict]:
        from obsidian_wiki.ast_extractor import extract
        from obsidian_wiki.code_understanding import _finalize

        self.ensure_index()
        data = extract(self.project)
        seed_set = set(seed_files)
        seeds = sorted(
            {
                n["label"]
                for n in data["nodes"]
                if n["kind"] in ("class", "function") and n["file"] in seed_set
            }
        )
        items: list[dict] = []
        seen: set[tuple] = set()
        for symbol in seeds[:25]:
            payload = self._query("impact", symbol, warnings)
            if payload is None:
                continue
            seed_marked = False
            for entry in payload.get("affected") or []:
                item = self._from_entry(entry, symbol, payload.get("depth") or 0)
                if item is None:
                    warnings.append(f"codegraph impact entry for {symbol} malformed; skipping")
                    continue
                if not seed_marked and item["symbol"] == symbol:
                    item["evidence"] = "changed-file"
                    item["relation"] = "changed-file"
                    item["via"] = ""
                    item["depth"] = 0
                    seed_marked = True
                self._merge(items, seen, item)
        for symbol in seeds[:5]:
            for command, relation in (("callers", "caller-of"), ("callees", "callee-of")):
                payload = self._query(command, symbol, warnings)
                if payload is None:
                    continue
                for entry in payload.get(command) or []:
                    item = self._from_entry(entry, symbol, 0)
                    if item is None:
                        continue
                    item["relation"] = f"{relation}-{symbol}"
                    self._merge(items, seen, item)
        items.sort(
            key=lambda it: (
                0 if it["evidence"] == "changed-file" else 1,
                it["depth"],
                it["symbol"],
            )
        )
        return _finalize(items, max_symbols)

    def _query(self, command: str, symbol: str, warnings: list[str]) -> dict | None:
        proc = self._run([command, symbol, "--json"])
        self._check(proc, command)
        try:
            payload = json.loads(proc.stdout)
        except ValueError:
            warnings.append(f"codegraph {command} {symbol} returned invalid JSON; skipping")
            return None
        return payload if isinstance(payload, dict) else None

    def _from_entry(self, entry: dict, seed: str, depth: int) -> dict | None:
        name = entry.get("name")
        file_path = entry.get("filePath")
        start = entry.get("startLine")
        if not name or not file_path or not isinstance(start, int):
            return None
        end = entry.get("endLine")
        lines = [start, end] if isinstance(end, int) and end >= start else [start]
        item = _item(name, entry.get("kind") or "symbol", _rel(self.project, file_path), lines)
        item["evidence"] = "codegraph-edge"
        item["relation"] = f"affected-by-{seed}"
        item["via"] = seed
        item["depth"] = depth
        return item

    @staticmethod
    def _merge(items: list[dict], seen: set[tuple], item: dict) -> None:
        key = (item["symbol"], item["file"], tuple(item["lines"]))
        if key in seen:
            return
        seen.add(key)
        items.append(item)
