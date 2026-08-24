"""Optional code-graph-assisted ingest support (issue #167).

``code_understand()`` produces a *focus map*: the symbols defined in a
project's seed files (changed files, files changed since a git ref, or all
tracked files) plus the cross-file references around them, ranked by
importance. Two backends:

- ``builtin`` — regex AST extraction (obsidian_wiki.ast_extractor) plus
  ripgrep for cross-file references; zero dependencies. Implemented in
  obsidian_wiki.code_understanding_builtin.
- ``codegraph`` — the optional codegraph CLI (https://github.com/ar9av/codegraph)
  when installed and explicitly requested (or auto-selected when available).
  Implemented in obsidian_wiki.code_understanding_codegraph.

Backend precedence: explicit flag > CODE_UNDERSTANDING_BACKEND env > 'auto'.
Only an explicitly selected codegraph backend is validated eagerly
(resolve_backend); the auto -> builtin fallback happens inside
code_understand() so the warning can be reported in the output dict.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

_SUBPROCESS_TIMEOUT = 60


class ProviderError(Exception):
    """Raised when a requested backend cannot be used."""


# ---------------------------------------------------------------------------
# Mode selection (pure; 'auto' is resolved by code_understand)
# ---------------------------------------------------------------------------


def resolve_backend(
    *,
    flag: str | None = None,
    env_backend: str | None = None,
    env_bin: str | None = None,
) -> tuple[str, list[str]]:
    """Select the backend mode. Returns (mode, warnings).

    Precedence: flag > env_backend > 'auto'. An explicit 'codegraph'
    selection validates that the binary is resolvable (env_bin, else
    shutil.which) and raises ProviderError otherwise; every other mode is
    returned unresolved with no warnings.
    """
    mode = flag or env_backend or "auto"
    if mode == "codegraph":
        if not (env_bin or shutil.which("codegraph")):
            raise ProviderError(
                "codegraph backend requested but the codegraph binary was not found"
            )
    return mode, []


# ---------------------------------------------------------------------------
# Index freshness heuristic
# ---------------------------------------------------------------------------


def index_state(project: Path) -> tuple[bool, bool, str]:
    """Return (initialized, fresh, detail) for project/.codegraph.

    initialized: codegraph.db exists. If source.json is also present (not
    guaranteed — codegraph 1.5.0 never writes it), it must parse with a
    sourceDir resolving to *project*, else the index is treated as
    uninitialized (mismatch guard). fresh: codegraph.db mtime >= the newest
    git-tracked source file (no git or no files counts as fresh).
    """
    db = project / ".codegraph" / "codegraph.db"
    src = project / ".codegraph" / "source.json"
    if not db.exists():
        return False, False, "no index (missing .codegraph/codegraph.db)"
    if src.exists():
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            source_dir = Path(str(data.get("sourceDir", ""))).resolve()
        except (OSError, ValueError, TypeError):
            return False, False, "source.json is invalid"
        if source_dir != project.resolve():
            return False, False, f"sourceDir {source_dir} does not match project"
    fresh = True
    try:
        tracked = _tracked_files_only(project)
        # Exclude the index's own artifacts — freshness vs committed code only.
        codegraph_prefix = str((project / ".codegraph").resolve())
        mtimes = [
            p.stat().st_mtime
            for p in (tracked or [])
            if p.exists() and not str(p.resolve()).startswith(codegraph_prefix)
        ]
        if mtimes:
            fresh = db.stat().st_mtime >= max(mtimes)
    except OSError:
        fresh = True
    return True, fresh, "fresh" if fresh else "stale (codegraph.db older than sources)"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _tracked_files_only(project: Path) -> list[Path] | None:
    """Committed files only — unlike batch._git_tracked_files (--cached
    --others), excludes untracked junk so seeds/freshness stay clean."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(project), "ls-files", "--cached", "--exclude-standard"],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [project / line for line in proc.stdout.splitlines() if line]


def _rel(project: Path, path: Path | str) -> str:
    """Normalize *path* to project-relative posix separators."""
    p = Path(path)
    try:
        return p.relative_to(project).as_posix()
    except ValueError:
        pass
    try:
        return p.resolve().relative_to(project.resolve()).as_posix()
    except ValueError:
        return p.as_posix().lstrip("./")


def _seed_files(
    project: Path,
    changed: list[str] | None,
    since: str | None,
    warnings: list[str],
) -> list[str]:
    """Resolve the seed file list: changed list, git diff since, all tracked."""
    if changed is not None:
        return [_rel(project, p) for p in changed if p]
    if since is not None:
        proc = None
        try:
            proc = subprocess.run(
                ["git", "-C", str(project), "diff", "--name-only", f"{since}..HEAD"],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        if proc is not None and proc.returncode == 0:
            return [line for line in proc.stdout.splitlines() if line]
        warnings.append(
            f"could not compute git diff since {since} (using all tracked files)"
        )
    tracked = _tracked_files_only(project)
    if tracked is not None:
        return [_rel(project, p) for p in tracked]
    # Not a git repo: all code files discovered by ast_extractor.
    from obsidian_wiki.ast_extractor import extract

    data = extract(project)
    return sorted({n["file"] for n in data["nodes"] if n["kind"] in ("class", "function")})


def _item(symbol: str, kind: str, file: str, lines: list[int]) -> dict:
    """Base focus-map item; providers patch relation/evidence/via/depth."""
    return {
        "symbol": symbol,
        "kind": kind,
        "file": file,
        "lines": lines,
        "relation": "reference",
        "via": "",
        "depth": 0,
        "evidence": "ast",
        "signature": "",
    }


def _finalize(items: list[dict], max_symbols: int) -> list[dict]:
    items = items[:max_symbols]
    for i, item in enumerate(items):
        item["rank"] = i + 1
    return items


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def code_understand(
    project: Path,
    *,
    backend_flag: str | None = None,
    changed: list[str] | None = None,
    since: str | None = None,
    max_symbols: int = 50,
    env: dict[str, str] | None = None,
) -> dict:
    """Return the focus-map contract dict for *project*.

    *env* supplies CODE_UNDERSTANDING_BACKEND / CODE_UNDERSTANDING_CODEGRAPH_BIN
    (falling back to os.environ) and is merged into the subprocess environment
    so test/consumer variables (e.g. FAKE_CODEGRAPH_MODE) reach the binary.
    Raises ProviderError on hard failure.
    """
    project = Path(project)
    if not project.is_dir():
        raise ProviderError(f"project directory does not exist: {project}")
    environ = env if env is not None else os.environ
    proc_env = dict(os.environ)
    if env:
        proc_env.update(env)

    mode, warnings = resolve_backend(
        flag=backend_flag,
        env_backend=environ.get("CODE_UNDERSTANDING_BACKEND"),
        env_bin=environ.get("CODE_UNDERSTANDING_CODEGRAPH_BIN"),
    )
    warnings = list(warnings)
    if mode == "auto":
        if environ.get("CODE_UNDERSTANDING_CODEGRAPH_BIN") or shutil.which("codegraph"):
            mode = "codegraph"
        else:
            mode = "builtin"
            warnings.append("codegraph not available; using builtin extractor")

    seed_files = _seed_files(project, changed, since, warnings)
    origin_files: set[str] = set(seed_files) if (changed is not None or since is not None) else set()

    if mode == "codegraph":
        from obsidian_wiki.code_understanding_codegraph import CodeGraphProvider

        bin_path = environ.get("CODE_UNDERSTANDING_CODEGRAPH_BIN") or shutil.which("codegraph")
        provider = CodeGraphProvider(bin_path or "", project, proc_env)
    else:
        from obsidian_wiki.code_understanding_builtin import BuiltinProvider

        provider = BuiltinProvider(project)

    focus_map = provider.build_focus_map(seed_files, origin_files, max_symbols, warnings)
    changed_symbols = list(
        dict.fromkeys(it["symbol"] for it in focus_map if it["evidence"] == "changed-file")
    )
    files: list[str] = []
    for it in focus_map:
        if it["file"] and it["file"] not in files:
            files.append(it["file"])
    for f in seed_files:
        if f not in files:
            files.append(f)

    return {
        "backend": mode,
        "project": str(project.resolve()),
        "seed_files": seed_files,
        "changed_symbols": changed_symbols,
        "focus_map": focus_map,
        "files": files,
        "warnings": warnings,
    }
