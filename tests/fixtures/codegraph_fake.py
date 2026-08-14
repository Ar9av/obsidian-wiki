#!/usr/bin/env python3
"""Fake codegraph CLI for tests.

Mimics the real codegraph v1.5.0 CLI contract (https://github.com/ar9av/codegraph):

    fake-codegraph [options] <command> [args...]

Commands: init, index, sync, status (accept an optional positional target
path, default CWD) and query <search>, callers <sym>, callees <sym>,
impact <sym>, affected [files...], files (resolve .codegraph from CWD).

The --json flag is accepted on query/callers/callees/impact/affected and
mirrors the real CLI's output shapes exactly. Behavior is canned and
deterministic — the fake never reads the project — driven by one env var:

  FAKE_CODEGRAPH_MODE=broke  -> print an error to stderr and exit 1 for
                               every command.

Stdlib only; intended to be executed as a binary (shebang + chmod +x).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def _fake_hash(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]


def _affected_entry(name: str, file_path: str = "src/foo.py", start_line: int = 5) -> dict:
    return {
        "name": name,
        "kind": "function",
        "filePath": file_path,
        "startLine": start_line,
    }


def _query_result(search: str) -> dict:
    node = {
        "id": "function:" + _fake_hash(search),
        "kind": "function",
        "name": search,
        "qualifiedName": f"src.mod.{search}",
        "filePath": "src/foo.py",
        "language": "python",
        "startLine": 10,
        "endLine": 42,
        "startColumn": 0,
        "endColumn": 12,
        "signature": "(args) -> int",
        "visibility": None,
        "isExported": False,
        "isAsync": False,
        "isStatic": False,
        "isAbstract": False,
    }
    return {"node": node, "score": 55.49}


def _respond(command: str, args: list[str], json_out: bool) -> int:
    if command == "init":
        target = _target_dir(args)
        (target / ".codegraph").mkdir(parents=True, exist_ok=True)
        (target / ".codegraph" / "codegraph.db").touch()
        print(f"codegraph: initialized {target}")
        return 0
    if command == "index":
        target = _target_dir(args)
        (target / ".codegraph").mkdir(parents=True, exist_ok=True)
        (target / ".codegraph" / "codegraph.db").touch()
        print(f"codegraph: indexed {target}")
        return 0
    if command == "sync":
        target = _target_dir(args)
        (target / ".codegraph").mkdir(parents=True, exist_ok=True)
        (target / ".codegraph" / "codegraph.db").touch()
        print(f"codegraph: synced {target}")
        return 0
    if command == "status":
        # Human text, never JSON (matches the real CLI).
        print("index: current")
        print("nodes: 2, edges: 1")
        return 0
    if command == "query":
        search = args[0]
        _emit([_query_result(search)], json_out, human_lines=[f"query {search}: 1 result"])
        return 0
    if command == "impact":
        symbol = args[0]
        payload = {
            "symbol": symbol,
            "depth": 2,
            "nodeCount": 2,
            "edgeCount": 1,
            "affected": [
                _affected_entry(symbol, file_path="src/foo.py", start_line=10),
                _affected_entry(f"caller_of_{symbol}", file_path="src/foo.py", start_line=5),
            ],
        }
        _emit(payload, json_out, human_lines=[f"impact of {symbol} (depth 2):"])
        return 0
    if command == "callers":
        symbol = args[0]
        payload = {
            "symbol": symbol,
            "callers": [_affected_entry(f"caller_of_{symbol}", start_line=5)],
        }
        _emit(payload, json_out, human_lines=[f"callers of {symbol}:"])
        return 0
    if command == "callees":
        symbol = args[0]
        payload = {
            "symbol": symbol,
            "callees": [_affected_entry(f"callee_of_{symbol}", start_line=20)],
        }
        _emit(payload, json_out, human_lines=[f"callees of {symbol}:"])
        return 0
    if command == "affected":
        payload = {
            "changedFiles": list(args),
            "affectedTests": ["tests/test_utils.py"],
            "totalDependentsTraversed": 5,
        }
        _emit(payload, json_out, human_lines=[f"affected by {', '.join(args)}:"])
        return 0
    if command == "files":
        for path in ("src/foo.py", "src/bar.py"):
            print(path)
        return 0
    print(f"codegraph: unknown command '{command}'", file=sys.stderr)
    return 2


def _target_dir(args: list[str]) -> Path:
    return Path(args[0]) if args else Path.cwd()


def _emit(payload: dict | list, json_out: bool, *, human_lines: list[str]) -> None:
    if json_out:
        print(json.dumps(payload))
    else:
        for line in human_lines:
            print(line)


def main(argv: list[str]) -> int:
    if os.environ.get("FAKE_CODEGRAPH_MODE") == "broke":
        print("codegraph: broken (FAKE_CODEGRAPH_MODE=broke)", file=sys.stderr)
        return 1

    options: list[str] = []
    positionals: list[str] = []
    for arg in argv:
        if arg.startswith("-"):
            options.append(arg)
        else:
            positionals.append(arg)

    if not positionals:
        print(
            "usage: codegraph [--json] <command> [args...]\n"
            "commands: init, index, sync, status, query, callers, callees,"
            " impact, affected, files",
            file=sys.stderr,
        )
        return 2

    command = positionals[0]
    args = positionals[1:]

    valid = ("init", "index", "sync", "status", "query", "callers", "callees",
             "impact", "affected", "files")
    if command not in valid:
        print(f"codegraph: unknown command '{command}'", file=sys.stderr)
        return 2

    if command == "query" and not args:
        print("codegraph: query requires a search term", file=sys.stderr)
        return 2
    if command in ("callers", "callees", "impact") and not args:
        print(f"codegraph: {command} requires a symbol", file=sys.stderr)
        return 2

    json_out = "--json" in options
    return _respond(command, args, json_out)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
