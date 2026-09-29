"""Local AST-based code structure extractor.

Extracts classes, functions, and imports from source files using regex patterns
(no LLM, no API calls). Outputs a node-link graph that wiki-ingest uses to seed
entity pages and map dependencies before any token is spent on the LLM.

Optional tree-sitter upgrade: install `obsidian-wiki[ast]` for higher-fidelity
extraction on the same languages. Falls back to regex automatically.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Node:
    id: str
    label: str
    kind: str          # "class" | "function" | "import" | "file"
    file: str
    line: int = 0
    language: str = ""
    docstring: str = ""

@dataclass
class Edge:
    source: str
    target: str
    relation: str      # "imports" | "calls" | "inherits" | "defines"
    confidence: str = "EXTRACTED"
    source_file: str = ""

@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def merge(self, other: "Graph") -> None:
        seen_nodes = {n.id for n in self.nodes}
        seen_edges = {(e.source, e.target, e.relation) for e in self.edges}
        for n in other.nodes:
            if n.id not in seen_nodes:
                self.nodes.append(n)
                seen_nodes.add(n.id)
        for e in other.edges:
            key = (e.source, e.target, e.relation)
            if key not in seen_edges:
                self.edges.append(e)
                seen_edges.add(key)

    def to_dict(self) -> dict:
        # Compute god nodes (top 10 by degree)
        degree: dict[str, int] = {}
        for e in self.edges:
            degree[e.source] = degree.get(e.source, 0) + 1
            degree[e.target] = degree.get(e.target, 0) + 1
        god_nodes = sorted(degree, key=lambda x: -degree[x])[:10]

        langs: dict[str, int] = {}
        for n in self.nodes:
            if n.language:
                langs[n.language] = langs.get(n.language, 0) + 1

        return {
            "nodes": [
                {
                    "id": n.id,
                    "label": n.label,
                    "kind": n.kind,
                    "file": n.file,
                    "line": n.line,
                    "language": n.language,
                    "docstring": n.docstring,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "relation": e.relation,
                    "confidence": e.confidence,
                    "source_file": e.source_file,
                }
                for e in self.edges
            ],
            "god_nodes": god_nodes,
            "stats": {
                "nodes": len(self.nodes),
                "edges": len(self.edges),
                "languages": langs,
                **self.stats,
            },
        }


# ---------------------------------------------------------------------------
# Language pattern definitions
# ---------------------------------------------------------------------------

@dataclass
class LangSpec:
    extensions: tuple[str, ...]
    name: str
    class_pat: str
    func_pat: str
    import_pats: tuple[str, ...]
    inherit_pat: str = ""    # optional group(1)=child, group(2)=parent clause
                              # (one name, or several comma-separated for
                              # multi-base languages like Python)
    docstring_pat: str = ""  # line immediately after def/class


LANGUAGES: list[LangSpec] = [
    LangSpec(
        name="python",
        extensions=(".py",),
        class_pat=r"^class\s+(\w+)",
        func_pat=r"^(?:async\s+)?def\s+(\w+)",
        import_pats=(
            r"^import\s+([\w.]+)",
            r"^from\s+([\w.]+)\s+import",
        ),
        inherit_pat=r"^class\s+(\w+)\s*\(([^)]+)\)",
        docstring_pat=r'^\s*"""(.+?)"""',
    ),
    LangSpec(
        name="javascript",
        extensions=(".js", ".jsx", ".mjs", ".cjs"),
        class_pat=r"^(?:export\s+)?class\s+(\w+)",
        func_pat=r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)|^(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(",
        import_pats=(
            r"""^import\s+.*?from\s+['"]([^'"]+)['"]""",
            r"""^(?:const|let|var)\s+\w+\s*=\s*require\s*\(['"]([^'"]+)['"]\)""",
        ),
        inherit_pat=r"^class\s+(\w+)\s+extends\s+(\w+)",
    ),
    LangSpec(
        name="typescript",
        extensions=(".ts", ".tsx"),
        class_pat=r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)",
        func_pat=r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)|^(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s+)?\(",
        import_pats=(r"""^import\s+.*?from\s+['"]([^'"]+)['"]""",),
        inherit_pat=r"^(?:export\s+)?class\s+(\w+)\s+extends\s+(\w+)",
    ),
    LangSpec(
        name="go",
        extensions=(".go",),
        class_pat=r"^type\s+(\w+)\s+struct",
        func_pat=r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(",
        import_pats=(r'"([\w./]+)"',),
    ),
    LangSpec(
        name="rust",
        extensions=(".rs",),
        class_pat=r"^(?:pub\s+)?struct\s+(\w+)|^(?:pub\s+)?enum\s+(\w+)|^(?:pub\s+)?trait\s+(\w+)",
        func_pat=r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)",
        import_pats=(r"^use\s+([\w:]+(?:::\{[^}]+\})?)",),
        inherit_pat=r"^impl(?:<[^>]+>)?\s+(\w+)\s+for\s+(\w+)",
    ),
    LangSpec(
        name="java",
        extensions=(".java",),
        class_pat=r"^(?:public\s+)?(?:abstract\s+)?(?:final\s+)?class\s+(\w+)|^(?:public\s+)?interface\s+(\w+)",
        func_pat=r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:\w+\s+)+(\w+)\s*\(",
        import_pats=(r"^import\s+([\w.]+);",),
        inherit_pat=r"class\s+(\w+)\s+extends\s+(\w+)",
    ),
    LangSpec(
        name="kotlin",
        extensions=(".kt", ".kts"),
        class_pat=r"^(?:data\s+)?class\s+(\w+)|^interface\s+(\w+)|^object\s+(\w+)",
        func_pat=r"^(?:suspend\s+)?fun\s+(\w+)",
        import_pats=(r"^import\s+([\w.]+)",),
        inherit_pat=r"class\s+(\w+)\s*[:(]\s*(\w+)",
    ),
    LangSpec(
        name="ruby",
        extensions=(".rb",),
        class_pat=r"^class\s+(\w+)",
        func_pat=r"^\s*def\s+(\w+)",
        import_pats=(
            r"""^require\s+['"]([^'"]+)['"]""",
            r"""^require_relative\s+['"]([^'"]+)['"]""",
        ),
        inherit_pat=r"^class\s+(\w+)\s*<\s*(\w+)",
    ),
    LangSpec(
        name="c",
        extensions=(".c", ".h"),
        class_pat=r"^typedef\s+struct\s+(\w+)|^struct\s+(\w+)\s*\{",
        func_pat=r"^(?:static\s+)?(?:inline\s+)?(?:\w+\s+)+(\w+)\s*\([^)]*\)\s*\{",
        import_pats=(r'^#include\s+[<"]([^>"]+)[>"]',),
    ),
    LangSpec(
        name="cpp",
        extensions=(".cpp", ".cc", ".cxx", ".hpp", ".hh"),
        class_pat=r"^class\s+(\w+)|^struct\s+(\w+)",
        func_pat=r"^(?:virtual\s+)?(?:static\s+)?(?:inline\s+)?(?:\w+[\w:*&<> ]+)\s+(\w+)\s*\(",
        import_pats=(r'^#include\s+[<"]([^>"]+)[>"]',),
        inherit_pat=r"^class\s+(\w+)\s*:\s*(?:public|protected|private)\s+(\w+)",
    ),
    LangSpec(
        name="swift",
        extensions=(".swift",),
        class_pat=r"^(?:public\s+)?(?:final\s+)?class\s+(\w+)|^struct\s+(\w+)|^protocol\s+(\w+)",
        func_pat=r"^(?:public\s+)?(?:private\s+)?(?:static\s+)?(?:override\s+)?func\s+(\w+)",
        import_pats=(r"^import\s+(\w+)",),
        inherit_pat=r"class\s+(\w+)\s*:\s*(\w+)",
    ),
    LangSpec(
        name="shell",
        extensions=(".sh", ".bash", ".zsh"),
        class_pat="",
        func_pat=r"^(?:function\s+)?(\w+)\s*\(\s*\)\s*\{",
        import_pats=(r"^source\s+(\S+)", r"^\.\s+(\S+)"),
    ),
]

_EXT_TO_LANG: dict[str, LangSpec] = {}
for _spec in LANGUAGES:
    for _ext in _spec.extensions:
        _EXT_TO_LANG[_ext] = _spec


# ---------------------------------------------------------------------------
# Per-file extraction
# ---------------------------------------------------------------------------

# File extensions we consider code (and should extract from)
CODE_EXTENSIONS = frozenset(_EXT_TO_LANG.keys())

# Extensions we skip entirely (binary, generated, etc.)
SKIP_EXTENSIONS = frozenset(
    ".pyc .pyo .pyd .so .dylib .dll .exe .class .jar .war .egg "
    ".zip .tar .gz .bz2 .whl .lock .png .jpg .jpeg .gif .ico .svg "
    ".pdf .mp4 .mov .mp3 .wav .ttf .woff .eot".split()
)

# Directories to skip (mirrors .gitignore defaults)
SKIP_DIRS = frozenset(
    "node_modules .git __pycache__ .pytest_cache dist build target "
    ".venv venv env .mypy_cache .ruff_cache coverage .tox".split()
)


def _file_id(path: str, name: str) -> str:
    """Stable node ID: <relative_path>::<name>."""
    return f"{path}::{name}"


def _split_base_clause(clause: str) -> list[str]:
    """Split an inherit_pat parent capture into real base-class names.

    Python's clause can hold several comma-separated bases plus keyword args
    (e.g. "Animal, Mixin, metaclass=ABCMeta"); other languages already
    capture a single identifier here and pass through unchanged.
    """
    bases: list[str] = []
    depth = 0
    current = ""
    for ch in clause:
        if ch in "([{":
            depth += 1
            current += ch
        elif ch in ")]}":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            bases.append(current)
            current = ""
        else:
            current += ch
    bases.append(current)

    names = []
    for base in bases:
        base = base.strip()
        if not base or "=" in base:
            continue  # keyword arg (metaclass=..., **kwargs), not a base class
        m = re.match(r"[\w.]+", base)
        if m:
            names.append(m.group(0))
    return names


def extract_file(path: Path, root: Path | None = None) -> Graph:
    """Extract nodes and edges from a single code file."""
    rel = str(path.relative_to(root)) if root else path.name
    ext = path.suffix.lower()
    spec = _EXT_TO_LANG.get(ext)
    if spec is None:
        return Graph()

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return Graph()

    graph = Graph()
    file_node_id = rel
    graph.nodes.append(Node(id=file_node_id, label=path.name, kind="file",
                            file=rel, language=spec.name))

    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        stripped = line.rstrip()

        # Classes / structs
        if spec.class_pat:
            m = re.match(spec.class_pat, stripped)
            if m:
                name = next((g for g in m.groups() if g), None)
                if name:
                    nid = _file_id(rel, name)
                    graph.nodes.append(Node(id=nid, label=name, kind="class",
                                            file=rel, line=i, language=spec.name))
                    graph.edges.append(Edge(source=file_node_id, target=nid,
                                            relation="defines", source_file=rel))

        # Functions / methods
        if spec.func_pat:
            m = re.match(spec.func_pat, stripped)
            if m:
                name = next((g for g in m.groups() if g), None)
                if name and not name.startswith("_"):  # skip private/dunder
                    nid = _file_id(rel, name)
                    graph.nodes.append(Node(id=nid, label=name, kind="function",
                                            file=rel, line=i, language=spec.name))
                    graph.edges.append(Edge(source=file_node_id, target=nid,
                                            relation="defines", source_file=rel))

        # Imports
        for pat in spec.import_pats:
            m = re.search(pat, stripped)
            if m:
                target = m.group(1).split(".")[0].split("/")[-1].split("::")[0]
                if target:
                    nid = f"import::{target}"
                    if not any(n.id == nid for n in graph.nodes):
                        graph.nodes.append(Node(id=nid, label=target, kind="import",
                                                file=rel, line=i, language=spec.name))
                    graph.edges.append(Edge(source=file_node_id, target=nid,
                                            relation="imports", source_file=rel))
                break

        # Inheritance
        if spec.inherit_pat:
            m = re.match(spec.inherit_pat, stripped)
            if m and len(m.groups()) >= 2:
                child, parent_clause = m.group(1), m.group(2)
                if child and parent_clause:
                    child_id = _file_id(rel, child)
                    for parent in _split_base_clause(parent_clause):
                        parent_id = _file_id(rel, parent)
                        graph.edges.append(Edge(source=child_id, target=parent_id,
                                                relation="inherits",
                                                confidence="EXTRACTED",
                                                source_file=rel))

    return graph


# ---------------------------------------------------------------------------
# Directory extraction
# ---------------------------------------------------------------------------

def _walk_code_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in root.walk() if hasattr(root, "walk") else _os_walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in CODE_EXTENSIONS and p.suffix.lower() not in SKIP_EXTENSIONS:
                yield p


def _os_walk(root: Path):
    import os
    for dirpath, dirnames, filenames in os.walk(root):
        yield Path(dirpath), dirnames, filenames


def extract_directory(root: Path, *, max_files: int = 2000) -> Graph:
    """Extract all code files under *root*, merging into one graph."""
    graph = Graph()
    count = 0
    lang_counts: dict[str, int] = {}

    for path in _walk_code_files(root):
        if count >= max_files:
            break
        fg = extract_file(path, root=root)
        graph.merge(fg)
        lang = _EXT_TO_LANG.get(path.suffix.lower())
        if lang:
            lang_counts[lang.name] = lang_counts.get(lang.name, 0) + 1
        count += 1

    graph.stats = {"files_processed": count, "languages": lang_counts}
    return graph


# ---------------------------------------------------------------------------
# Convenience entry point (used by the CLI)
# ---------------------------------------------------------------------------

def extract(path: Path) -> dict:
    """Extract from a file or directory, return serialisable dict."""
    if path.is_dir():
        graph = extract_directory(path)
    elif path.is_file():
        graph = extract_file(path)
    else:
        raise FileNotFoundError(f"Path not found: {path}")
    return graph.to_dict()
