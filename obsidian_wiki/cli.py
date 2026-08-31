"""obsidian-wiki installer CLI.

Python port of ``setup.sh`` for the pip-installed package. The skill content
lives inside the installed package (``obsidian_wiki/_data/skills``) instead of a
cloned repo, so this wires the bundled skills into every supported AI agent's
skills directory and writes the global config (XDG-style, under
``$XDG_CONFIG_HOME/obsidian-wiki`` by default) so the skills resolve the vault
from any project.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from obsidian_wiki import __version__

HOME = Path.home()


def _resolve_global_config_dir() -> Path:
    """Resolve the global config directory, XDG-first with legacy fallback.

    New installs land under ``$XDG_CONFIG_HOME/obsidian-wiki`` (default
    ``~/.config/obsidian-wiki``, per the XDG Base Directory spec). Installs that
    already have a ``~/.obsidian-wiki`` directory keep using it, so upgrading
    doesn't strand a working config.
    """
    xdg_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    xdg_dir = (Path(xdg_home).expanduser() if xdg_home else HOME / ".config") / "obsidian-wiki"
    legacy_dir = HOME / ".obsidian-wiki"
    if legacy_dir.is_dir() and not xdg_dir.exists():
        return legacy_dir
    return xdg_dir


GLOBAL_CONFIG_DIR = _resolve_global_config_dir()
GLOBAL_CONFIG = GLOBAL_CONFIG_DIR / "config"

# Skills usable from any project (no vault context needed beyond the global
# config). These are also installed globally for agents that only scope skills
# per-project, so cross-project sync/query/context work everywhere.
PORTABLE_SKILLS = ("wiki-update", "wiki-query", "wiki-context-pack")


class SchemaOptions(TypedDict):
    allowed_lifecycles: frozenset[str]
    allowed_relationship_types: frozenset[str]
    required_trust_fields: tuple[str, ...]
    schema_source: str


# ── Data resolution ──────────────────────────────────────────────────────────
# Works for both a built wheel (data under <pkg>/_data) and an editable/source
# checkout (data at the repo root next to the package).
def _pkg_dir() -> Path:
    return Path(__file__).resolve().parent


def skills_dir() -> Path:
    """Return the directory holding the bundled skill folders."""
    for cand in (_pkg_dir() / "_data" / "skills", _pkg_dir().parent / ".skills"):
        if cand.is_dir():
            return cand
    raise FileNotFoundError(
        "Could not locate bundled skills. Reinstall obsidian-wiki "
        "(`pip install --force-reinstall obsidian-wiki`)."
    )


def extension_dir() -> Path | None:
    """Return the browser extension folder to load unpacked, if bundled.

    Wheel installs get it at ``_data/extension``; a source checkout keeps it at
    ``extensions/brain``.
    """
    for cand in (_pkg_dir() / "_data" / "extension", _pkg_dir().parent / "extensions" / "brain"):
        if (cand / "manifest.json").is_file():
            return cand
    return None


def bootstrap_dir() -> Path | None:
    """Return the directory containing agent bootstrap context files.

    For a wheel this is ``_data/bootstrap``; for a source checkout the files are
    spread across the repo root, so we return the repo root and resolve each
    file via the repo-relative layout in ``_bootstrap_files``.
    """
    built = _pkg_dir() / "_data" / "bootstrap"
    if built.is_dir():
        return built
    repo = _pkg_dir().parent
    if (repo / "AGENTS.md").is_file():
        return repo
    return None


def list_skills() -> list[str]:
    return sorted(p.name for p in skills_dir().iterdir() if p.is_dir())


# ── Skill installation ───────────────────────────────────────────────────────
def _is_link_or_junction(path: Path) -> bool:
    """Return whether *path* is a link, including a Windows directory junction."""
    if path.is_symlink():
        return True

    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None:
        return bool(is_junction())

    if os.name != "nt":
        return False
    try:
        file_info = path.lstat()
    except OSError:
        return False

    reparse_tag = getattr(file_info, "st_reparse_tag", None)
    if reparse_tag is not None:
        return reparse_tag == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)

    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    return bool(getattr(file_info, "st_file_attributes", 0) & reparse_flag)


def _is_symlink_privilege_error(error: OSError) -> bool:
    """Return whether Windows rejected link creation for missing privilege."""
    return os.name == "nt" and getattr(error, "winerror", None) == 1314


# Set when a symlink install falls back to copying, so the warning prints once
# and the setup summary can report the mode that actually happened.
_SYMLINK_FALLBACK = False


def install_skills(
    target_dir: Path,
    label: str,
    *,
    subset: tuple[str, ...] | None = None,
    mode: str = "symlink",
    quiet: bool = False,
) -> int:
    """Install bundled skills into *target_dir*. Returns the count installed."""
    src_root = skills_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    global _SYMLINK_FALLBACK
    installed = 0
    install_mode = "copy" if _SYMLINK_FALLBACK else mode
    for skill in sorted(p for p in src_root.iterdir() if p.is_dir()):
        name = skill.name
        if subset is not None and name not in subset:
            continue
        link_path = target_dir / name

        if _is_link_or_junction(link_path) or link_path.is_file():
            link_path.unlink()
        elif link_path.is_dir():
            # A real directory we previously copied here is safe to replace;
            # anything else is the user's and we leave it alone.
            if (link_path / "SKILL.md").exists():
                shutil.rmtree(link_path)
            else:
                print(f"   ⚠️  {link_path} is not a managed skill, skipping")
                continue

        if install_mode == "symlink":
            try:
                link_path.symlink_to(skill, target_is_directory=True)
            except OSError as error:
                if not _is_symlink_privilege_error(error):
                    raise
                install_mode = "copy"
                if not _SYMLINK_FALLBACK:
                    print(
                        "Warning: symbolic links are unavailable; "
                        "copying skills instead. Use Developer Mode or "
                        "--copy to choose this explicitly."
                    )
                _SYMLINK_FALLBACK = True
                shutil.copytree(skill, link_path)
        else:  # copy
            shutil.copytree(skill, link_path)

        if not (link_path / "SKILL.md").exists():
            raise RuntimeError(f"broken skill install: {link_path} -> {skill}")
        installed += 1

    if not quiet:
        print(f"✅  Installed {installed} skills → {label}")
    return installed


# Agents whose skills directory lives under $HOME. (path-under-home, label,
# subset). All get every skill — pip users have no cloned repo to host
# project-scoped skills, so everything must be globally discoverable.
GLOBAL_AGENT_DIRS: list[tuple[str, str, tuple[str, ...] | None]] = [
    (".claude/skills", "~/.claude/skills/ (Claude Code)", None),
    (".gemini/skills", "~/.gemini/skills/ (Gemini CLI)", None),
    (".gemini/antigravity/skills", "~/.gemini/antigravity/skills/ (Antigravity, legacy)", None),
    (".codex/skills", "~/.codex/skills/ (Codex)", None),
    (".hermes/skills", "~/.hermes/skills/ (Hermes default)", None),
    (".openclaw/skills", "~/.openclaw/skills/ (OpenClaw)", None),
    (".copilot/skills", "~/.copilot/skills/ (GitHub Copilot CLI)", None),
    (".trae/skills", "~/.trae/skills/ (Trae)", None),
    (".trae-cn/skills", "~/.trae-cn/skills/ (Trae CN)", None),
    (".kiro/skills", "~/.kiro/skills/ (Kiro CLI)", None),
    (".pi/agent/skills", "~/.pi/agent/skills/ (Pi)", None),
    (".agents/skills", "~/.agents/skills/ (OpenCode, Aider, Droid, generic)", None),
]


def install_global_skills(mode: str) -> None:
    for rel, label, subset in GLOBAL_AGENT_DIRS:
        install_skills(HOME / rel, label, subset=subset, mode=mode)
    _install_hermes_profiles(mode)


def _install_hermes_profiles(mode: str) -> None:
    """Mirror setup.sh: install into the active and all named Hermes profiles."""
    hermes_home = os.environ.get("HERMES_HOME")
    handled: set[Path] = set()
    if hermes_home:
        hp = Path(hermes_home).expanduser()
        if hp != HOME / ".hermes":
            install_skills(hp / "skills", f"{hp}/skills/ (Hermes active profile)", mode=mode)
            handled.add(hp)
    profiles = HOME / ".hermes" / "profiles"
    if profiles.is_dir():
        for prof in sorted(p for p in profiles.iterdir() if p.is_dir()):
            if prof in handled:
                continue
            install_skills(
                prof / "skills",
                f"~/.hermes/profiles/{prof.name}/skills/ (Hermes profile: {prof.name})",
                mode=mode,
            )


# ── Project-local install (opt-in) ───────────────────────────────────────────
PROJECT_AGENT_DIRS = [
    (".claude/skills", "Claude Code"),
    (".cursor/skills", "Cursor"),
    (".windsurf/skills", "Windsurf"),
    (".agents/skills", "OpenCode / generic"),
    (".pi/skills", "Pi"),
    (".kiro/skills", "Kiro"),
]

# (bootstrap-relative source path, destination relative to project dir).
# The source path is resolved against bootstrap_dir() for a wheel, or mapped to
# the repo layout for a source checkout (see _resolve_bootstrap_src).
BOOTSTRAP_FILES = [
    ("AGENTS.md", "AGENTS.md"),
    ("cursor/rules/obsidian-wiki.mdc", ".cursor/rules/obsidian-wiki.mdc"),
    ("windsurf/rules/obsidian-wiki.md", ".windsurf/rules/obsidian-wiki.md"),
    ("kiro/steering/obsidian-wiki.md", ".kiro/steering/obsidian-wiki.md"),
    ("agent/rules/obsidian-wiki.md", ".agent/rules/obsidian-wiki.md"),
    ("agent/workflows/obsidian-wiki.md", ".agent/workflows/obsidian-wiki.md"),
    ("github/copilot-instructions.md", ".github/copilot-instructions.md"),
]

# AGENTS.md aliases created as symlinks within the project (single source).
AGENTS_ALIASES = ("CLAUDE.md", "GEMINI.md", ".hermes.md")


def _resolve_bootstrap_src(boot_root: Path, rel: str) -> Path | None:
    """Resolve a bootstrap source path under a wheel layout or repo layout."""
    built = boot_root / rel
    if built.exists():
        return built
    # Source checkout: boot_root is the repo root; files use the repo layout.
    repo_rel = {
        "AGENTS.md": "AGENTS.md",
        "cursor/rules/obsidian-wiki.mdc": ".cursor/rules/obsidian-wiki.mdc",
        "windsurf/rules/obsidian-wiki.md": ".windsurf/rules/obsidian-wiki.md",
        "kiro/steering/obsidian-wiki.md": ".kiro/steering/obsidian-wiki.md",
        "agent/rules/obsidian-wiki.md": ".agent/rules/obsidian-wiki.md",
        "agent/workflows/obsidian-wiki.md": ".agent/workflows/obsidian-wiki.md",
        "github/copilot-instructions.md": ".github/copilot-instructions.md",
    }.get(rel)
    if repo_rel and (boot_root / repo_rel).exists():
        return boot_root / repo_rel
    return None


def install_project(project_dir: Path, mode: str) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n📁  Installing project-local files → {project_dir}")
    for rel, _label in PROJECT_AGENT_DIRS:
        install_skills(project_dir / rel, f"{rel}/", mode=mode)

    boot_root = bootstrap_dir()
    if boot_root is None:
        print("   ⚠️  Bootstrap files not found in package; skipping context files")
        return

    for rel, dest in BOOTSTRAP_FILES:
        src = _resolve_bootstrap_src(boot_root, rel)
        if src is None:
            continue
        dst = project_dir / dest
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink() or dst.exists():
            if dst.is_dir() and not dst.is_symlink():
                continue
            dst.unlink()
        shutil.copyfile(src, dst)
    print("✅  Installed bootstrap context files (AGENTS.md, rules, workflows)")

    # AGENTS.md aliases as relative symlinks (copy fallback for symlink-hostile FS).
    for alias in AGENTS_ALIASES:
        link = project_dir / alias
        if link.is_symlink() or link.exists():
            link.unlink()
        try:
            link.symlink_to("AGENTS.md")
        except OSError:
            shutil.copyfile(project_dir / "AGENTS.md", link)
    print(f"✅  Linked AGENTS.md aliases ({', '.join(AGENTS_ALIASES)})")


# ── Config ───────────────────────────────────────────────────────────────────
def _read_config_value(key: str) -> str:
    if not GLOBAL_CONFIG.is_file():
        return ""
    for line in GLOBAL_CONFIG.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def _read_config() -> dict[str, str]:
    if not GLOBAL_CONFIG.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in GLOBAL_CONFIG.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def resolve_vault_path(cli_vault: str | None) -> str:
    if cli_vault:
        return os.path.expanduser(cli_vault)
    existing = _read_config_value("OBSIDIAN_VAULT_PATH")
    if existing and existing != "/path/to/your/vault":
        return existing
    if sys.stdin.isatty():
        try:
            entered = input("  Where is your Obsidian vault? (absolute path): ").strip()
        except EOFError:
            entered = ""
        if entered:
            return os.path.expanduser(entered)
    return existing


def write_config(vault_path: str) -> None:
    """Write the setup-managed keys, preserving everything else in the file.

    Only ``OBSIDIAN_VAULT_PATH``, ``OBSIDIAN_WIKI_REPO`` and
    ``OBSIDIAN_WIKI_VERSION`` are owned by setup. Any other key the user added
    (``OBSIDIAN_LINK_FORMAT``, ``QMD_WIKI_COLLECTION``, sync settings, …) is
    carried over untouched, along with comments and ordering, so re-running
    setup on an existing install is non-destructive.
    """
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # OBSIDIAN_WIKI_REPO points at the bundled data root so skills that reference
    # framework assets (templates, references) can find them post-install.
    repo_root = skills_dir().parent
    managed = {
        "OBSIDIAN_VAULT_PATH": vault_path,
        "OBSIDIAN_WIKI_REPO": str(repo_root),
        "OBSIDIAN_WIKI_VERSION": __version__,
    }

    existing: list[str] = []
    if GLOBAL_CONFIG.is_file():
        existing = GLOBAL_CONFIG.read_text().splitlines()

    out: list[str] = []
    seen: set[str] = set()
    for raw in existing:
        stripped = raw.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if key in managed and not stripped.startswith("#"):
            if key not in seen:
                out.append(f'{key}="{managed[key]}"')
                seen.add(key)
            # Drop duplicate definitions of a managed key.
            continue
        out.append(raw)
    for key, value in managed.items():
        if key not in seen:
            out.append(f'{key}="{value}"')

    GLOBAL_CONFIG.write_text("\n".join(out) + "\n")
    print(f"✅  Global config written to {GLOBAL_CONFIG}")


def ensure_global_writing_profile() -> Path:
    target = GLOBAL_CONFIG_DIR / "WRITING.md"
    if target.exists():
        return target
    template = skills_dir() / "llm-wiki" / "references" / "WRITING.md"
    target.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return target


VAULT_SUBDIRS = (
    "concepts",
    "entities",
    "skills",
    "references",
    "synthesis",
    "journal",
    "projects",
    "_archives",
    "_raw",
    "_staging",
    ".obsidian",
)


def scaffold_vault(vault_path: Path) -> bool:
    """Create the vault directory structure and special files if they don't exist yet.

    Idempotent: existing files/dirs are left untouched. Returns True if the vault
    directory itself had to be created (i.e. this is a brand new vault).
    """
    created = not vault_path.is_dir()
    for name in VAULT_SUBDIRS:
        (vault_path / name).mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    index_md = vault_path / "index.md"
    if not index_md.exists():
        index_md.write_text(
            "---\n"
            "title: Wiki Index\n"
            "---\n\n"
            "# Wiki Index\n\n"
            f"*This index is automatically maintained. Last updated: {timestamp}*\n\n"
            "## Concepts\n\n"
            "*No pages yet. Use `wiki-ingest` to add your first source.*\n\n"
            "## Entities\n\n"
            "## Skills\n\n"
            "## References\n\n"
            "## Synthesis\n\n"
            "## Journal\n"
        )

    log_md = vault_path / "log.md"
    if not log_md.exists():
        log_md.write_text(
            "---\n"
            "title: Wiki Log\n"
            "---\n\n"
            "# Wiki Log\n\n"
            f'- [{timestamp}] INIT vault_path="{vault_path}" '
            "categories=concepts,entities,skills,references,synthesis,journal\n"
        )

    hot_md = vault_path / "hot.md"
    if not hot_md.exists():
        hot_md.write_text(
            "---\n"
            "title: Hot Cache\n"
            f"updated: {timestamp}\n"
            "---\n\n"
            "# Hot Cache\n\n"
            "*A ~500-word semantic snapshot of recent activity. Updated after every major write operation.*\n\n"
            "## Recent Activity\n\n"
            f"- [{timestamp}] INIT — vault created at {vault_path}\n\n"
            "## Active Threads\n\n"
            "*None yet — start ingesting sources to populate.*\n\n"
            "## Key Takeaways\n\n"
            "*None yet.*\n\n"
            "## Flagged Contradictions\n\n"
            "*None yet.*\n"
        )

    manifest_json = vault_path / ".manifest.json"
    if not manifest_json.exists():
        manifest_json.write_text("{}\n")

    app_json = vault_path / ".obsidian" / "app.json"
    if not app_json.exists():
        app_json.write_text(
            json.dumps(
                {
                    "strictLineBreaks": False,
                    "showFrontmatter": False,
                    "defaultViewMode": "preview",
                    "livePreview": True,
                },
                indent=2,
            )
            + "\n"
        )

    appearance_json = vault_path / ".obsidian" / "appearance.json"
    if not appearance_json.exists():
        appearance_json.write_text(json.dumps({"baseFontSize": 16}, indent=2) + "\n")

    return created


def _check_stale() -> None:
    """Warn if the installed version doesn't match when setup last ran, or if skills are missing."""
    if not GLOBAL_CONFIG.is_file():
        print(
            f"⚠️  obsidian-wiki {__version__} is installed but setup has never been run.\n"
            f"   Run: obsidian-wiki setup --vault /path/to/your/vault",
            file=sys.stderr,
        )
        return

    setup_version = _read_config_value("OBSIDIAN_WIKI_VERSION")
    if setup_version and setup_version != __version__:
        print(
            f"⚠️  obsidian-wiki upgraded {setup_version} → {__version__} but setup hasn't been re-run.\n"
            f"   New skills won't be available until you run: obsidian-wiki setup",
            file=sys.stderr,
        )
        return

    # Even if the version matches, check that ~/.claude/skills has the full set.
    claude_skills_dir = HOME / ".claude" / "skills"
    if claude_skills_dir.is_dir():
        bundled = set(list_skills())
        installed = {p.name for p in claude_skills_dir.iterdir() if p.is_dir()}
        missing = bundled - installed
        if missing:
            print(
                f"⚠️  {len(missing)} skill(s) missing from ~/.claude/skills/ "
                f"(e.g. {', '.join(sorted(missing)[:3])}{', ...' if len(missing) > 3 else ''}).\n"
                f"   Run: obsidian-wiki setup",
                file=sys.stderr,
            )


def _doctor_add(
    checks: list[dict[str, str]],
    *,
    name: str,
    status: str,
    detail: str,
    hint: str = "",
) -> None:
    checks.append({
        "name": name,
        "status": status,
        "detail": detail,
        "hint": hint,
    })


def _doctor_status(checks: list[dict[str, str]]) -> str:
    statuses = {check["status"] for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def _required_vault_paths(vault: Path) -> list[Path]:
    return [
        vault / "index.md",
        vault / "log.md",
        vault / "hot.md",
        vault / ".manifest.json",
    ]


def _doctor_project_check(project_dir: Path) -> dict[str, str]:
    required = [project_dir / "AGENTS.md", *[project_dir / dest for _src, dest in BOOTSTRAP_FILES[1:]]]
    missing = [str(path.relative_to(project_dir)) for path in required if not path.exists()]
    if missing:
        return {
            "status": "warn",
            "detail": f"missing {len(missing)} bootstrap file(s)",
            "hint": f"run: obsidian-wiki setup --project {project_dir}",
        }
    aliases_missing = [alias for alias in AGENTS_ALIASES if not (project_dir / alias).exists()]
    if aliases_missing:
        return {
            "status": "warn",
            "detail": f"missing AGENTS aliases: {', '.join(aliases_missing)}",
            "hint": f"run: obsidian-wiki setup --project {project_dir}",
        }
    return {"status": "pass", "detail": "bootstrap files and aliases present", "hint": ""}


def _doctor_code_understanding_checks(
    project_dir: Path, backend_setting: str, bin_path: str | None
) -> list[dict[str, str]]:
    """Code-understanding readiness checks for a project (issue #167)."""
    checks: list[dict[str, str]] = []

    from obsidian_wiki.ast_extractor import extract

    try:
        data = extract(project_dir)
        if data.get("nodes"):
            checks.append({
                "name": "code-understanding.builtin",
                "status": "pass",
                "detail": f"found {len(data['nodes'])} AST node(s)",
                "hint": "",
            })
        else:
            checks.append({
                "name": "code-understanding.builtin",
                "status": "warn",
                "detail": "no code files found",
                "hint": "code-understand will produce an empty focus map",
            })
    except (OSError, ValueError) as exc:
        checks.append({
            "name": "code-understanding.builtin",
            "status": "warn",
            "detail": f"AST extraction failed: {exc}",
            "hint": "code-understand may not find any symbols",
        })

    rg_path = shutil.which("rg")
    checks.append({
        "name": "code-understanding.rg",
        "status": "pass" if rg_path else "warn",
        "detail": rg_path or "ripgrep (rg) not found on PATH",
        "hint": "" if rg_path else "install ripgrep for cross-file reference evidence",
    })

    from obsidian_wiki.code_understanding import index_state

    codegraph_path = bin_path or shutil.which("codegraph")
    if codegraph_path:
        checks.append({
            "name": "code-understanding.codegraph",
            "status": "pass",
            "detail": str(codegraph_path),
            "hint": "",
        })
    elif backend_setting == "codegraph":
        checks.append({
            "name": "code-understanding.codegraph",
            "status": "fail",
            "detail": "codegraph backend requested but binary not found",
            "hint": "set CODE_UNDERSTANDING_CODEGRAPH_BIN or install codegraph",
        })
    else:
        # info (not warn): optional backend absent must not fail doctor --strict.
        checks.append({
            "name": "code-understanding.codegraph",
            "status": "info",
            "detail": "codegraph binary not found (builtin backend will be used)",
            "hint": "set CODE_UNDERSTANDING_CODEGRAPH_BIN or install codegraph",
        })

    if codegraph_path:
        initialized, fresh, detail = index_state(project_dir)
        checks.append({
            "name": "code-understanding.codegraph-index",
            "status": "pass" if initialized else "warn",
            "detail": detail,
            "hint": "" if initialized else "run: obsidian-wiki code-understand --project <project>",
        })
        if initialized:
            if not (project_dir / ".git").exists():
                # index_state's freshness heuristic needs git-tracked files;
                # without git it cannot see a stale index — compare mtimes directly.
                db = project_dir / ".codegraph" / "codegraph.db"
                codegraph_prefix = str((project_dir / ".codegraph").resolve())
                try:
                    newest = max(
                        p.stat().st_mtime
                        for p in project_dir.rglob("*")
                        if p.is_file()
                        and not str(p.resolve()).startswith(codegraph_prefix)
                    )
                except OSError:
                    newest = 0.0
                if db.stat().st_mtime < newest:
                    fresh = False
                    detail = "stale (codegraph.db older than sources)"
            checks.append({
                "name": "code-understanding.codegraph-fresh",
                "status": "pass" if fresh else "warn",
                "detail": detail,
                "hint": "" if fresh else "re-run: obsidian-wiki code-understand --project <project>",
            })
        gitignore = project_dir / ".gitignore"
        ignored = False
        if gitignore.is_file():
            for line in gitignore.read_text(encoding="utf-8").splitlines():
                pattern = line.strip()
                if not pattern or pattern.startswith("#"):
                    continue
                if pattern in (".codegraph", ".codegraph/"):
                    ignored = True
                    break
        checks.append({
            "name": "code-understanding.codegraph-gitignore",
            "status": "pass" if ignored else "warn",
            "detail": ".codegraph/ is ignored" if ignored else ".codegraph/ is not ignored",
            "hint": "" if ignored else "add .codegraph/ to .gitignore",
        })
    return checks


def run_doctor(*, vault_override: str | None = None, project_dir: str | None = None) -> dict[str, object]:
    checks: list[dict[str, str]] = []

    try:
        bundled = list_skills()
        _doctor_add(
            checks,
            name="bundled-skills",
            status="pass" if bundled else "fail",
            detail=f"{len(bundled)} bundled skill(s) available",
            hint="" if bundled else "reinstall obsidian-wiki",
        )
    except FileNotFoundError as exc:
        _doctor_add(checks, name="bundled-skills", status="fail", detail=str(exc), hint="reinstall obsidian-wiki")
        bundled = []

    boot = bootstrap_dir()
    _doctor_add(
        checks,
        name="bootstrap-assets",
        status="pass" if boot else "fail",
        detail=str(boot) if boot else "bootstrap files not found",
        hint="" if boot else "reinstall obsidian-wiki",
    )

    config = _read_config()
    config_present = GLOBAL_CONFIG.is_file()
    _doctor_add(
        checks,
        name="global-config",
        status="pass" if config_present else "fail",
        detail=str(GLOBAL_CONFIG) if config_present else "global config not written",
        hint="" if config_present else "run: obsidian-wiki setup --vault /path/to/your/vault",
    )

    vault_path = ""
    if vault_override:
        vault_path = os.path.expanduser(vault_override)
    elif config_present:
        vault_path = config.get("OBSIDIAN_VAULT_PATH", "")

    if not vault_path:
        _doctor_add(
            checks,
            name="vault-config",
            status="fail",
            detail="OBSIDIAN_VAULT_PATH is not set",
            hint="run: obsidian-wiki setup --vault /path/to/your/vault",
        )
        vault = None
    else:
        vault = Path(vault_path).expanduser().resolve()
        _doctor_add(
            checks,
            name="vault-config",
            status="pass",
            detail=str(vault),
            hint="",
        )

    setup_version = config.get("OBSIDIAN_WIKI_VERSION", "") if config_present else ""
    if setup_version and setup_version != __version__:
        _doctor_add(
            checks,
            name="setup-version",
            status="warn",
            detail=f"setup ran with {setup_version}; installed package is {__version__}",
            hint="run: obsidian-wiki setup",
        )
    elif config_present:
        _doctor_add(
            checks,
            name="setup-version",
            status="pass",
            detail=f"setup version matches installed package ({__version__})" if setup_version else "setup version not recorded",
            hint="" if setup_version else "re-run setup to record install metadata",
        )

    if vault is not None:
        if vault.is_dir():
            _doctor_add(checks, name="vault-path", status="pass", detail="vault directory exists", hint="")
            missing_core = [str(path.relative_to(vault)) for path in _required_vault_paths(vault) if not path.exists()]
            if missing_core:
                _doctor_add(
                    checks,
                    name="vault-core-files",
                    status="warn",
                    detail=f"missing {len(missing_core)} core file(s): {', '.join(missing_core)}",
                    hint="run the wiki setup skill or create the missing files",
                )
            else:
                _doctor_add(checks, name="vault-core-files", status="pass", detail="core vault files present", hint="")

            manifest_path = vault / ".manifest.json"
            if manifest_path.exists():
                try:
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    sources = data.get("sources", {})
                    _doctor_add(
                        checks,
                        name="manifest-json",
                        status="pass",
                        detail=f"valid JSON with {len(sources)} tracked source(s)",
                        hint="",
                    )
                except (json.JSONDecodeError, OSError) as exc:
                    _doctor_add(
                        checks,
                        name="manifest-json",
                        status="fail",
                        detail=f"invalid manifest: {exc}",
                        hint="repair or regenerate .manifest.json",
                    )
        else:
            _doctor_add(
                checks,
                name="vault-path",
                status="fail",
                detail=f"vault directory not found: {vault}",
                hint="fix OBSIDIAN_VAULT_PATH or re-run setup",
            )

    agent_summaries: list[str] = []
    partial_agents: list[str] = []
    full_agents = 0
    bundled_set = set(bundled)
    for rel, label, _subset in GLOBAL_AGENT_DIRS:
        agent_dir = HOME / rel
        if not agent_dir.is_dir():
            continue
        installed = {p.name for p in agent_dir.iterdir() if (p.is_dir() or p.is_symlink())}
        missing = bundled_set - installed
        count = len(installed & bundled_set)
        agent_summaries.append(f"{label}: {count}/{len(bundled_set)}")
        if missing:
            partial_agents.append(label)
        else:
            full_agents += 1

    if not agent_summaries:
        _doctor_add(
            checks,
            name="agent-installs",
            status="warn",
            detail="no global agent skill installs found",
            hint="run: obsidian-wiki setup",
        )
    elif partial_agents:
        _doctor_add(
            checks,
            name="agent-installs",
            status="warn",
            detail="; ".join(agent_summaries),
            hint="re-run obsidian-wiki setup to fill missing skills",
        )
    else:
        _doctor_add(
            checks,
            name="agent-installs",
            status="pass",
            detail=f"{full_agents} agent install(s) fully provisioned",
            hint="",
        )

    if project_dir:
        project = Path(project_dir).expanduser().resolve()
        if project.is_dir():
            project_check = _doctor_project_check(project)
            _doctor_add(
                checks,
                name="project-bootstrap",
                status=project_check["status"],
                detail=project_check["detail"],
                hint=project_check["hint"],
            )
            backend_setting, bin_path = _resolve_code_understanding_settings(project)
            for check in _doctor_code_understanding_checks(project, backend_setting, bin_path):
                _doctor_add(
                    checks,
                    name=check["name"],
                    status=check["status"],
                    detail=check["detail"],
                    hint=check.get("hint", ""),
                )
        else:
            _doctor_add(
                checks,
                name="project-bootstrap",
                status="fail",
                detail=f"project directory not found: {project}",
                hint="pass an existing directory",
            )

    return {
        "status": _doctor_status(checks),
        "checks": checks,
    }


def _print_doctor(report: dict[str, object]) -> None:
    icon = {"pass": "✅", "info": "ℹ️", "warn": "⚠️ ", "fail": "❌"}
    print(f"obsidian-wiki doctor: {report['status']}")
    for check in report["checks"]:
        name = check["name"]
        status = check["status"]
        detail = check["detail"]
        hint = check["hint"]
        print(f"{icon.get(status, '•')} {name}: {detail}")
        if hint:
            print(f"   hint: {hint}")


# ── Commands ─────────────────────────────────────────────────────────────────
def _maybe_configure_sync(vault_path: Path, remote_arg: str | None) -> bool:
    """Offer (or apply) GitHub sync setup for the vault.

    Non-interactive (`--remote` passed, or no TTY and no remote given): only
    acts when a remote was explicitly supplied. Interactive: prompts, mirroring
    setup.sh's flow, so pip/uv installs get the same offer shell/curl installs
    always had (see #153).
    """
    from obsidian_wiki.sync import configure_sync, get_remote

    if get_remote(vault_path):
        return True  # already configured — nothing to do

    remote = remote_arg
    if not remote:
        if not sys.stdin.isatty():
            return False
        print()
        try:
            answer = input("  Set up GitHub sync for your vault? [y/N]: ").strip()
        except EOFError:
            answer = ""
        if answer.lower() != "y":
            return False
        try:
            remote = input("  GitHub repo URL (e.g. https://github.com/you/my-wiki.git): ").strip()
        except EOFError:
            remote = ""
        if not remote:
            return False

    try:
        messages = configure_sync(vault_path, remote)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"⚠️  GitHub sync setup skipped: {exc}", file=sys.stderr)
        return False
    for m in messages:
        print(f"✅  {m}")
    print("✅  Run `obsidian-wiki sync` any time to commit and push vault changes.")
    return True


def cmd_setup(args: argparse.Namespace) -> int:
    mode = "copy" if args.copy else "symlink"
    print("\n╔══════════════════════════════════════════════════╗")
    print("║         obsidian-wiki — Agent Setup              ║")
    print("╚══════════════════════════════════════════════════╝\n")

    vault_path = resolve_vault_path(args.vault)
    write_config(vault_path)
    writing_profile = ensure_global_writing_profile()
    if not vault_path:
        print("    → Vault path not set yet. Re-run with `--vault /path/to/vault`")
        print(f"      or edit OBSIDIAN_VAULT_PATH in {GLOBAL_CONFIG}.")
    else:
        vault_dir = Path(vault_path).expanduser()
        vault_created = scaffold_vault(vault_dir)
        if vault_created:
            print(f"✅  Vault created at {vault_dir}")
        else:
            print(f"✅  Vault verified at {vault_dir}")

    if not args.project_only:
        print()
        install_global_skills(mode)

    if args.project is not None:
        project_dir = Path(args.project or os.getcwd()).expanduser().resolve()
        install_project(project_dir, mode)

    sync_configured = False
    if vault_path and Path(vault_path).expanduser().is_dir():
        sync_configured = _maybe_configure_sync(Path(vault_path).expanduser(), args.remote)

    n = len(list_skills())
    print("\n───────────────────────────────────────────────────")
    print(" Setup complete!\n")
    print(f" Skills installed: {n}  (mode: {'copy' if _SYMLINK_FALLBACK else mode})")
    if vault_path:
        print(f" Vault:            {vault_path}")
    print(f" Writing profile:  {writing_profile.resolve()}")
    if sync_configured:
        print(" GitHub sync:      obsidian-wiki sync")
    print("\n Next steps:")
    print("   1. Open a project in your agent")
    print('   2. Say: "set up my wiki"\n')
    print(" From any project:")
    print("   /wiki-update    → sync knowledge into your vault")
    print("   /wiki-query     → ask questions against your wiki")
    print("   /wiki-context-pack → compile bounded context for another agent")
    print("───────────────────────────────────────────────────\n")
    return 0


def cmd_sync_setup(args: argparse.Namespace) -> int:
    from obsidian_wiki.sync import configure_sync

    vault_str = resolve_vault_path(args.vault)
    if not vault_str:
        print("error: no vault configured — pass --vault or run `obsidian-wiki setup` first", file=sys.stderr)
        return 1
    vault_path = Path(vault_str).expanduser()
    try:
        messages = configure_sync(vault_path, args.remote)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for m in messages:
        print(f"✅  {m}")
    print("✅  Run `obsidian-wiki sync` any time to commit and push vault changes.")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    from obsidian_wiki.sync import run_sync

    vault_str = resolve_vault_path(args.vault)
    if not vault_str:
        print("error: no vault configured — pass --vault or run `obsidian-wiki setup` first", file=sys.stderr)
        return 1
    code, message = run_sync(Path(vault_str).expanduser())
    print(message)
    return code


def cmd_graph_query(args: argparse.Namespace) -> int:
    from obsidian_wiki.graphrag import query
    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 1
    result = query(vault, args.question, top_n=args.top, max_should_read=args.max_read)
    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))
    return 0


def cmd_batch_plan(args: argparse.Namespace) -> int:
    from obsidian_wiki.batch import plan_batches
    source_dir = Path(args.source_dir).expanduser().resolve()
    vault = Path(args.vault).expanduser().resolve()
    if not source_dir.is_dir():
        print(f"error: source directory not found: {source_dir}", file=sys.stderr)
        return 1
    result = plan_batches(
        source_dir,
        vault,
        max_batch_mb=args.max_mb,
        max_batch_files=args.max_files,
        skip_unchanged=not args.no_cache,
        include_code=args.include_code,
    )
    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))
    return 0


def cmd_graph_analyse(args: argparse.Namespace) -> int:
    from obsidian_wiki import graph_analysis as ga
    vault = Path(args.vault).expanduser().resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 1

    if args.path or args.around:
        # Query modes: no full analysis, just the graph walk.
        outgoing, _ = ga.parse_vault_graph(vault)
        if args.path:
            src, tgt = args.path
            path = ga.shortest_path(outgoing, src, tgt, directed=args.direction == "out")
            result: dict = {"source": ga._slug(src), "target": ga._slug(tgt), "path": path,
                            "hops": (len(path) - 1) if path else None}
        else:
            hits = ga.neighborhood(outgoing, args.around, depth=args.depth, direction=args.direction)
            result = {"seed": ga._slug(args.around), "depth": args.depth,
                      "direction": args.direction, "pages": hits, "count": len(hits),
                      "note": "pages and count exclude the seed itself"}
    else:
        previous = None
        if args.diff_against:
            previous = ga.load_snapshot(Path(args.diff_against).expanduser())
            if previous is None:
                print(f"warning: no GRAPH_SNAPSHOT found in {args.diff_against}; skipping diff",
                      file=sys.stderr)
        result = ga.analyse_vault(vault, top_n=args.top, previous_snapshot=previous,
                                  include_snapshot=args.snapshot)
    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))
    return 0


DEFAULT_CLAUDE_DIR = "~/.claude"
DEFAULT_BRAIN_DIR = "~/.claude/session-brain"


def _brain_dir(args: argparse.Namespace) -> Path:
    return Path(
        args.out or os.environ.get("WIKI_SESSION_BRAIN_DIR") or DEFAULT_BRAIN_DIR
    ).expanduser()


def _skip_list(args: argparse.Namespace) -> list[str]:
    raw = args.skip or os.environ.get("WIKI_SKIP_PROJECTS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def cmd_sessions_build(args: argparse.Namespace) -> int:
    from obsidian_wiki.session_graph import build
    claude_dir = Path(args.claude_dir).expanduser()
    bookmarks = Path(args.bookmarks).expanduser() if args.bookmarks else \
        Path("~/.bookmark-agent/bookmarks.json").expanduser()

    def progress(message: str) -> None:
        if args.verbose:
            print(f"… {message}", file=sys.stderr)

    result = build(
        claude_dir,
        _brain_dir(args),
        k=args.k,
        min_sim=args.min_sim,
        mutual=args.mutual,
        half_life_days=args.half_life,
        full=args.full,
        since=args.since,
        skip=_skip_list(args),
        bookmarks_path=bookmarks,
        write_html=not args.no_html,
        progress=progress,
    )
    if args.json:
        print(json.dumps(result, indent=2) if args.pretty else json.dumps(result))
        return 0

    stats = result["stats"]
    print(f"{stats['sessions']} sessions ({stats['full']} with transcripts, "
          f"{stats['thin']} history-only) · {stats['edges']} links · "
          f"{stats['clusters']} topics · {stats['unclustered']} unclustered")
    print(f"read {stats['read_this_run']} this run, reused {stats['reused']} cached")
    for cluster in result["clusters"][:15]:
        flag = " [dormant]" if cluster["dormant"] else (" [hot]" if cluster["momentum"] >= 2 else "")
        print(f"  {cluster['size']:4}  {cluster['name'] or cluster['label']}{flag}")
    if result["unnamed"]:
        print(f"{result['unnamed']} unnamed topic(s) — run the session-brain skill to name them")
    print(f"-> {result['out_dir']}")
    return 0


def cmd_sessions_query(args: argparse.Namespace) -> int:
    from obsidian_wiki.session_query import query
    try:
        result = query(
            _brain_dir(args), args.question,
            top_n=args.top, max_load=args.max_load, half_life_days=args.half_life,
            project=args.project, cluster=args.cluster, since=args.since,
            min_score=args.min_score,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2) if args.pretty else json.dumps(result))
        return 0
    if not result["candidates"]:
        print("no matching sessions")
        return 0
    for c in result["candidates"]:
        loadable = "" if c["loadable"] else "  (no transcript)"
        print(f"{c['score']:.2f}  {c['end_ts'][:10]}  {c['project'][:18]:18}  "
              f"{(c['title'] or '(untitled)')[:52]:52}{loadable}")
        print(f"      {c['why']}")
    if result["should_load"]:
        print(f"\nload: {result['load_command']}")
    return 0


def cmd_sessions_show(args: argparse.Namespace) -> int:
    from obsidian_wiki.session_query import show
    try:
        result = show(_brain_dir(args), args.session_id, neighbors=args.neighbors)
    except (FileNotFoundError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2) if args.pretty else json.dumps(result))
    return 0


def cmd_sessions_clusters(args: argparse.Namespace) -> int:
    from obsidian_wiki.session_graph import load_graph
    try:
        _, clusters_doc = load_graph(_brain_dir(args))
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    clusters = clusters_doc.get("clusters", [])
    if args.unnamed:
        clusters = [c for c in clusters if not c.get("name")]
    clusters = clusters[:args.top]
    if args.json:
        payload = {"clusters": clusters}
        print(json.dumps(payload, indent=2) if args.pretty else json.dumps(payload))
        return 0
    for c in clusters:
        flag = " [dormant]" if c.get("dormant") else (" [hot]" if c.get("momentum", 0) >= 2 else "")
        print(f"{c['id']:3}  {c['size']:4}  {c.get('name') or c['label']}{flag}")
        print(f"      terms: {', '.join(t for t, _ in c['top_terms'][:8])}")
    return 0


def cmd_sessions_name(args: argparse.Namespace) -> int:
    from obsidian_wiki.session_graph import set_cluster_names
    raw = sys.stdin.read() if args.from_file == "-" else \
        Path(args.from_file).expanduser().read_text(encoding="utf-8")
    try:
        updates = json.loads(raw)
    except ValueError as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(updates, list):
        print('error: expected a JSON array of {"id": N, "name": "...", "summary": "..."}',
              file=sys.stderr)
        return 1
    try:
        result = set_cluster_names(_brain_dir(args), updates)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


def cmd_cache_check(args: argparse.Namespace) -> int:
    from obsidian_wiki.cache import check_sources
    vault = Path(args.vault).expanduser().resolve()
    sources = [Path(p).expanduser().resolve() for p in args.sources]
    result = check_sources(vault, sources)
    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))
    return 0


def cmd_cache_update(args: argparse.Namespace) -> int:
    from obsidian_wiki.cache import update_source
    vault = Path(args.vault).expanduser().resolve()
    source = Path(args.source).expanduser().resolve()
    pages = args.pages or []
    h = update_source(vault, source, pages_produced=pages)
    print(json.dumps({"path": str(source), "content_hash": h}))
    return 0


def cmd_cache_hash(args: argparse.Namespace) -> int:
    from obsidian_wiki.cache import hash_file
    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"error: {path} does not exist", file=sys.stderr)
        return 1
    print(json.dumps({"path": str(path), "sha256": hash_file(path)}))
    return 0


def cmd_ast_extract(args: argparse.Namespace) -> int:
    from pathlib import Path
    from obsidian_wiki.ast_extractor import extract
    path = Path(args.path).expanduser().resolve()
    try:
        result = extract(path)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.pretty:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result))
    return 0


def cmd_code_understand(args: argparse.Namespace) -> int:
    from obsidian_wiki.code_understanding import ProviderError, code_understand

    project = Path(args.project or os.getcwd())
    backend, bin_path = _resolve_code_understanding_settings(project)
    env = dict(os.environ)
    env["CODE_UNDERSTANDING_BACKEND"] = backend
    env["CODE_UNDERSTANDING_CODEGRAPH_BIN"] = bin_path or ""
    try:
        result = code_understand(
            project,
            # "auto" must pass through as None so the resolved config can win (flag > config > auto).
            backend_flag=None if args.backend == "auto" else args.backend,
            changed=args.changed,
            since=args.since,
            max_symbols=args.max_symbols,
            env=env,
        )
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.pretty:
        print(f"backend: {result['backend']}")
        print(f"project: {result['project']}")
        print(f"focus map: {len(result['focus_map'])} symbol(s)")
        for item in result["focus_map"]:
            lines = item.get("lines") or []
            span = str(lines[0]) if lines else ""
            if len(lines) > 1:
                span += f"-{lines[-1]}"
            print(
                f"  {item.get('rank', '?')}. {item['symbol']} "
                f"({item['kind']}) {item['file']}:{span} [{item.get('evidence', '')}]"
            )
        if result["warnings"]:
            print("warnings:")
            for warning in result["warnings"]:
                print(f"  - {warning}")
        else:
            print("warnings: none")
    else:
        print(json.dumps(result, indent=2))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    report = run_doctor(vault_override=args.vault, project_dir=args.project)
    if args.json:
        if args.pretty:
            print(json.dumps(report, indent=2))
        else:
            print(json.dumps(report))
    else:
        _print_doctor(report)
    statuses = {check["status"] for check in report["checks"]}
    if "fail" in statuses or (args.strict and "warn" in statuses):
        return 1
    return 0


def _print_lint(report: dict[str, object]) -> None:
    print(f"obsidian-wiki lint: {report['status']}")
    stats = report["stats"]
    print(f"pages: {stats['pages']}  links: {stats['link_count']}")
    for name, count in stats["findings"].items():
        print(f"{name}: {count}")


def _schema_csv(config: dict[str, str], key: str) -> list[str]:
    if key not in config:
        return []
    values = [item.strip() for item in config[key].split(",")]
    if any(not item for item in values):
        raise ValueError(f"invalid {key} value: entries must not be empty")
    return values


def _schema_cli_values(values: list[str] | None, flag: str) -> list[str]:
    normalised = [item.strip() for item in values or []]
    if any(not item for item in normalised):
        raise ValueError(f"invalid {flag} value: must not be empty")
    return normalised


def _schema_source_value(
    args: argparse.Namespace,
    config: dict[str, str],
) -> str | None:
    configured_value: str | None = None
    if "OBSIDIAN_SCHEMA_SOURCE" in config:
        configured_value = config["OBSIDIAN_SCHEMA_SOURCE"].strip()
        if not configured_value:
            raise ValueError("invalid OBSIDIAN_SCHEMA_SOURCE value: must not be empty")

    cli_value = getattr(args, "schema_source", None)
    if cli_value is not None:
        value = cli_value.strip()
        if not value:
            raise ValueError("invalid --schema-source value: must not be empty")
        return value
    return configured_value


def _read_config_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _resolve_schema_command_context(
    vault_arg: str | None,
) -> tuple[Path, dict[str, str], str] | None:
    config: dict[str, str]
    config_source: str
    if vault_arg and vault_arg.startswith("@"):
        name = vault_arg[1:]
        if not name or re.fullmatch(r"[A-Za-z0-9_-]+", name) is None:
            print("error: named vault must use @ followed by letters, digits, _ or -", file=sys.stderr)
            return None
        path = GLOBAL_CONFIG_DIR / f"config.{name}"
        config = _read_config_file(path)
        config_source = str(path)
        resolved = config.get("OBSIDIAN_VAULT_PATH", "")
    elif vault_arg is not None:
        config = {}
        config_source = "explicit-vault"
        resolved = vault_arg
    else:
        current = Path.cwd().resolve()
        config = {}
        config_source = str(GLOBAL_CONFIG)
        while True:
            candidate = current / ".env"
            local = _read_config_file(candidate)
            if "OBSIDIAN_VAULT_PATH" in local:
                config = local
                config_source = str(candidate)
                break
            if current == HOME or current.parent == current:
                break
            current = current.parent
        if not config:
            config = _read_config_file(GLOBAL_CONFIG)
        resolved = config.get("OBSIDIAN_VAULT_PATH", "")
    if not resolved:
        print("error: vault not configured; pass a path, @name, or run obsidian-wiki setup", file=sys.stderr)
        return None
    vault = Path(resolved).expanduser().resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return None
    return vault, config, config_source


def _schema_options(
    args: argparse.Namespace,
    config: dict[str, str],
    config_source: str,
    *,
    default_required_trust_fields: tuple[str, ...] | None = None,
) -> SchemaOptions:
    from obsidian_wiki.lint import (
        ALLOWED_RELATIONSHIP_TYPES,
        TRUST_REQUIRED_FRONTMATTER,
    )
    from obsidian_wiki.trust import (
        ALLOWED_LIFECYCLES,
        TRUST_REQUIRED_FIELD_ALLOWLIST,
    )

    cli_lifecycles = _schema_cli_values(
        getattr(args, "allow_lifecycle", None), "--allow-lifecycle"
    )
    cli_relationships = _schema_cli_values(
        getattr(args, "allow_relationship_type", None), "--allow-relationship-type"
    )
    raw_cli_required = getattr(args, "required_trust_field", None)
    cli_required = (
        _schema_cli_values(raw_cli_required, "--required-trust-field")
        if raw_cli_required is not None
        else None
    )
    configured_lifecycles = _schema_csv(config, "OBSIDIAN_ALLOWED_LIFECYCLES")
    configured_relationships = _schema_csv(config, "OBSIDIAN_ALLOWED_RELATIONSHIP_TYPES")
    configured_required = _schema_csv(config, "OBSIDIAN_REQUIRED_TRUST_FIELDS")
    unknown_required = sorted(
        set(configured_required).union(cli_required or ()) - TRUST_REQUIRED_FIELD_ALLOWLIST
    )
    if unknown_required:
        allowed = ", ".join(sorted(TRUST_REQUIRED_FIELD_ALLOWLIST))
        unknown = ", ".join(unknown_required)
        raise ValueError(
            "invalid OBSIDIAN_REQUIRED_TRUST_FIELDS value(s): "
            f"{unknown}; allowed values: {allowed}"
        )
    required = tuple(
        cli_required
        if cli_required is not None
        else configured_required
        or list(default_required_trust_fields or TRUST_REQUIRED_FRONTMATTER)
    )
    cli_overrides = bool(
        cli_lifecycles
        or cli_relationships
        or cli_required is not None
    )
    configured_overrides = bool(
        configured_lifecycles
        or configured_relationships
        or configured_required
    )
    source = _schema_source_value(args, config)
    if not source:
        if cli_overrides and configured_overrides:
            source = f"cli+config:{config_source}"
        elif cli_overrides:
            source = f"cli:{config_source}"
        elif configured_overrides:
            source = f"config:{config_source}"
        else:
            source = "framework-defaults"
    return {
        "allowed_lifecycles": ALLOWED_LIFECYCLES.union(configured_lifecycles, cli_lifecycles),
        "allowed_relationship_types": ALLOWED_RELATIONSHIP_TYPES.union(
            configured_relationships, cli_relationships
        ),
        "required_trust_fields": required,
        "schema_source": source,
    }


def cmd_lint(args: argparse.Namespace) -> int:
    from obsidian_wiki.lint import lint_vault

    context = _resolve_schema_command_context(args.vault)
    if context is None:
        return 1
    vault, config, config_source = context

    strict_trust = args.strict_trust or config.get("OBSIDIAN_TRUST_STRICT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    try:
        schema = _schema_options(args, config, config_source)
        report = lint_vault(
            vault,
            require_trust_ledger=True,
            strict_trust=strict_trust,
            **schema,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        if args.pretty:
            print(json.dumps(report, indent=2))
        else:
            print(json.dumps(report))
    else:
        _print_lint(report)
    if report["status"] == "fail" or (args.strict and report["status"] == "warn"):
        return 1
    return 0


def _resolve_command_vault(vault_arg: str | None) -> Path | None:
    resolved = (
        vault_arg
        if vault_arg is not None
        else _read_config_value("OBSIDIAN_VAULT_PATH")
    )
    if not resolved:
        print("error: vault not configured; pass a path or run obsidian-wiki setup", file=sys.stderr)
        return None
    vault = Path(resolved).expanduser().resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return None
    return vault


def _read_env_value(path: Path, key: str) -> tuple[bool, str]:
    if not path.is_file():
        return False, ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith(f"{key}="):
            return True, line.split("=", 1)[1].strip().strip('"')
    return False, ""


def _resolve_context_pack_vault(vault_arg: str | None) -> Path | None:
    if vault_arg is not None:
        return _resolve_command_vault(vault_arg)

    current = Path.cwd().resolve()
    home = HOME.resolve()
    while True:
        found, local_vault = _read_env_value(
            current / ".env",
            "OBSIDIAN_VAULT_PATH",
        )
        if found:
            if not local_vault:
                print(
                    "error: vault not configured; pass a path or run obsidian-wiki setup",
                    file=sys.stderr,
                )
                return None
            return _resolve_command_vault(local_vault)
        if current == home or current.parent == current:
            break
        current = current.parent
    return _resolve_command_vault(None)


_CODE_UNDERSTANDING_KEYS = ("CODE_UNDERSTANDING_BACKEND", "CODE_UNDERSTANDING_CODEGRAPH_BIN")


def _resolve_code_understanding_settings(project: Path) -> tuple[str, str | None]:
    """Resolve (backend, bin_path) for code-understanding.

    Precedence: os.environ (empty = unset) > nearest walk-up project .env
    (project dir to HOME, stopping at the first .env setting a
    CODE_UNDERSTANDING key) > global config > defaults ("auto", None).
    Mirrors the OBSIDIAN_VAULT_PATH resolution used by the schema/context-pack
    commands.
    """
    backend = os.environ.get("CODE_UNDERSTANDING_BACKEND") or ""
    bin_path = os.environ.get("CODE_UNDERSTANDING_CODEGRAPH_BIN") or ""
    if not backend or not bin_path:
        current = Path(project).resolve()
        home = HOME.resolve()
        local: dict[str, str] = {}
        while True:
            candidate = _read_config_file(current / ".env")
            if any(key in candidate for key in _CODE_UNDERSTANDING_KEYS):
                local = candidate
                break
            if current == home or current.parent == current:
                break
            current = current.parent
        global_config = _read_config()
        if not backend:
            backend = (
                local.get("CODE_UNDERSTANDING_BACKEND")
                or global_config.get("CODE_UNDERSTANDING_BACKEND")
                or "auto"
            )
        if not bin_path:
            bin_path = (
                local.get("CODE_UNDERSTANDING_CODEGRAPH_BIN")
                or global_config.get("CODE_UNDERSTANDING_CODEGRAPH_BIN")
                or ""
            )
    return backend, bin_path or None


def cmd_trust_record(args: argparse.Namespace) -> int:
    from obsidian_wiki.trust import (
        TRUST_LEDGER_RELATIVE_PATH,
        build_trust_ledger,
        check_trust_ledger,
        update_trust_ledger,
        write_trust_ledger,
    )

    context = _resolve_schema_command_context(args.vault)
    if context is None:
        return 1
    vault, config, config_source = context
    try:
        schema = _schema_options(
            args,
            config,
            config_source,
            default_required_trust_fields=("base_confidence", "lifecycle", "updated"),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    path = vault / TRUST_LEDGER_RELATIVE_PATH
    try:
        if args.all:
            removed_not_applicable: list[str] = []
            if path.is_file():
                previous = check_trust_ledger(
                    vault,
                    path,
                    allowed_lifecycles=schema["allowed_lifecycles"],
                    required_trust_keys=schema["required_trust_fields"],
                    schema_source=schema["schema_source"],
                )
                removed_not_applicable = sorted(
                    item["page"]
                    for item in previous["stale"]
                    if item.get("reason")
                    == "confidence_not_applicable_but_ledger_entry_exists"
                )
            ledger = build_trust_ledger(
                vault,
                reviewed_at=args.reviewed_at,
                allowed_lifecycles=schema["allowed_lifecycles"],
                required_trust_keys=schema["required_trust_fields"],
            )
            ledger["removed_not_applicable"] = removed_not_applicable
            recorded_pages = len(ledger["pages"])
        else:
            ledger = update_trust_ledger(
                vault,
                path,
                reviewed_at=args.reviewed_at,
                page_paths=args.page,
                allowed_lifecycles=schema["allowed_lifecycles"],
                required_trust_keys=schema["required_trust_fields"],
            )
            requested = {
                Path(raw).as_posix().removeprefix("./") for raw in args.page
            }
            recorded_pages = len(requested.intersection(ledger["pages"]))
        write_trust_ledger(path, ledger, vault=vault)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    result = {
        "status": "recorded",
        "ledger_path": str(path),
        "recorded_pages": recorded_pages,
        "not_applicable_pages": list(ledger.get("not_applicable", [])),
        "removed_not_applicable": list(ledger.get("removed_not_applicable", [])),
        "reviewed_at": args.reviewed_at,
        "method": ledger["method"],
        "schema": {
            "source": schema["schema_source"],
            "allowed_lifecycles": sorted(schema["allowed_lifecycles"]),
            "required_trust_fields": list(schema["required_trust_fields"]),
        },
    }
    if args.json:
        print(json.dumps(result, indent=2 if args.pretty else None))
    else:
        print(f"recorded {result['recorded_pages']} reviewed page(s) in {path}")
        print(
            "not applicable (excluded from trust review): "
            f"{len(result['not_applicable_pages'])} page(s)"
        )
        for page in result["not_applicable_pages"]:
            print(f"  - {page}")
        print(
            "obsolete ledger entries removed: "
            f"{len(result['removed_not_applicable'])} page(s)"
        )
        for page in result["removed_not_applicable"]:
            print(f"  - {page}")
        if result["removed_not_applicable"]:
            removed = ", ".join(result["removed_not_applicable"])
            print(
                "warning: removed obsolete trust ledger entries because "
                f"base_confidence is not applicable: {removed}",
                file=sys.stderr,
            )
    return 0


def cmd_trust_check(args: argparse.Namespace) -> int:
    from obsidian_wiki.trust import check_trust_ledger

    context = _resolve_schema_command_context(args.vault)
    if context is None:
        return 1
    vault, config, config_source = context
    try:
        schema = _schema_options(
            args,
            config,
            config_source,
            default_required_trust_fields=("base_confidence", "lifecycle", "updated"),
        )
        report = check_trust_ledger(
            vault,
            allowed_lifecycles=schema["allowed_lifecycles"],
            required_trust_keys=schema["required_trust_fields"],
            schema_source=schema["schema_source"],
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2 if args.pretty else None))
    else:
        print(f"obsidian-wiki trust-check: {report['status']}")
        for name, count in report["counts"].items():
            print(f"{name}: {count}")
    if report["status"] == "fail" or (args.strict and report["status"] == "warn"):
        return 1
    return 0


def _print_query(result: dict[str, object]) -> None:
    print(f"answer_type: {result['answer_type']}")
    candidates = result.get("candidates", [])
    if candidates:
        print("candidates:")
        for item in candidates:
            print(f"- {item['title']} ({item['page']}) score={item['score']}")
    path = result.get("path") or []
    if path:
        print("path:")
        print(" -> ".join(path))
    should_read = result.get("should_read") or []
    if should_read:
        print("should_read:")
        for page in should_read:
            print(f"- {page}")


def cmd_query(args: argparse.Namespace) -> int:
    from obsidian_wiki.graphrag import query

    vault_arg = args.vault or _read_config_value("OBSIDIAN_VAULT_PATH")
    if not vault_arg:
        print("error: vault not configured; pass --vault or run obsidian-wiki setup", file=sys.stderr)
        return 1

    vault = Path(vault_arg).expanduser().resolve()
    if not vault.is_dir():
        print(f"error: vault not found: {vault}", file=sys.stderr)
        return 1

    result = query(vault, args.question, top_n=args.top, max_should_read=args.max_read)
    if args.json:
        if args.pretty:
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps(result))
    else:
        _print_query(result)
    return 0


def cmd_context_pack(args: argparse.Namespace) -> int:
    from obsidian_wiki.context_pack import ContextError, build_context_pack, render_markdown

    vault = _resolve_context_pack_vault(args.vault)
    if vault is None:
        return 1
    try:
        pack = build_context_pack(
            vault,
            args.topic or "",
            budget=args.budget,
            recent=args.recent,
            public_only=args.public_only,
            metadata_only=args.metadata_only,
        )
    except ContextError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(pack, indent=2 if args.pretty else None))
    else:
        print(render_markdown(pack), end="")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    for name in list_skills():
        print(name)
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    bundled = list_skills()
    print(f"obsidian-wiki {__version__}")
    print(f"skills:    {skills_dir()}")
    boot = bootstrap_dir()
    print(f"bootstrap: {boot if boot else '(not found)'}")
    ext = extension_dir()
    print(f"extension: {ext if ext else '(not bundled)'}")
    print(f"config:    {GLOBAL_CONFIG}{'' if GLOBAL_CONFIG.exists() else ' (not written yet)'}")
    if GLOBAL_CONFIG.exists():
        vp = _read_config_value("OBSIDIAN_VAULT_PATH")
        setup_ver = _read_config_value("OBSIDIAN_WIKI_VERSION")
        print(f"vault:     {vp or '(unset)'}")
        print(f"setup ran: {setup_ver or '(never)'}")
        if vp:
            from obsidian_wiki.sync import get_remote
            remote = get_remote(Path(vp).expanduser())
            print(f"sync:      {remote if remote else '(not configured — run: obsidian-wiki sync-setup <url>)'}")
    print(f"bundled skills: {len(bundled)}")
    print()
    print("Agent skill install status:")
    bundled_set = set(bundled)
    for rel, label, _subset in GLOBAL_AGENT_DIRS:
        agent_dir = HOME / rel
        if not agent_dir.is_dir():
            print(f"  {label}: not installed")
            continue
        installed = {p.name for p in agent_dir.iterdir() if p.is_dir()}
        wiki_installed = installed & bundled_set
        missing = bundled_set - installed
        status = "✅" if not missing else "⚠️ "
        print(f"  {status} {label}: {len(wiki_installed)}/{len(bundled_set)}", end="")
        if missing:
            print(f"  (run: obsidian-wiki setup)", end="")
        print()
    _check_stale()
    return 0


# ── Argument parsing ─────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="obsidian-wiki",
        description="Install the LLM-Wiki agent skills into your AI coding agents.",
    )
    p.add_argument("-V", "--version", action="version", version=f"obsidian-wiki {__version__}")
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("setup", help="install skills into your agents and write config (default)")
    _add_setup_args(sp)
    sp.set_defaults(func=cmd_setup)

    ssp = sub.add_parser(
        "sync-setup",
        help="configure GitHub sync for your vault (git init, .gitignore, remote)",
    )
    ssp.add_argument("remote", help="GitHub (or any git host) repo URL, e.g. https://github.com/you/my-wiki.git")
    ssp.add_argument("--vault", metavar="PATH", help="absolute path to your Obsidian vault")
    ssp.set_defaults(func=cmd_sync_setup)

    syp = sub.add_parser("sync", help="commit and push pending vault changes (git add -A, commit, push)")
    syp.add_argument("--vault", metavar="PATH", help="absolute path to your Obsidian vault")
    syp.set_defaults(func=cmd_sync)

    lp = sub.add_parser("list", help="list bundled skills")
    lp.set_defaults(func=cmd_list)

    ip = sub.add_parser("info", help="show install paths, version, and config")
    ip.set_defaults(func=cmd_info)

    gq = sub.add_parser(
        "graph-query",
        help="answer a question from the vault's wikilink index without reading page bodies",
    )
    gq.add_argument("vault", help="path to the Obsidian vault")
    gq.add_argument("question", help="question to answer")
    gq.add_argument("--top", type=int, default=8, help="number of candidate pages to rank (default: 8)")
    gq.add_argument("--max-read", type=int, default=3, help="max pages to return in should_read (default: 3)")
    gq.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    gq.set_defaults(func=cmd_graph_query)

    bp = sub.add_parser(
        "batch-plan",
        help="split a source directory into parallel-ingest batches, skipping unchanged files",
    )
    bp.add_argument("vault", help="path to the Obsidian vault")
    bp.add_argument("source_dir", help="directory of source documents to ingest")
    bp.add_argument("--max-mb", type=float, default=2.0, help="max MB per batch (default: 2)")
    bp.add_argument("--max-files", type=int, default=20, help="max files per batch (default: 20)")
    bp.add_argument("--no-cache", action="store_true", help="disable manifest-based skip of unchanged files")
    bp.add_argument("--include-code", action="store_true", help="include code files (default: excluded; use ast-extract instead)")
    bp.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    bp.set_defaults(func=cmd_batch_plan)

    ga = sub.add_parser(
        "graph-analyse",
        help="analyse the vault's wikilink graph: god nodes, bridges, communities, "
             "surprising connections, suggested questions; or walk paths/neighbourhoods",
    )
    ga.add_argument("vault", help="path to the Obsidian vault")
    ga.add_argument("--top", type=int, default=20, help="number of top results to return (default: 20)")
    ga.add_argument("--path", nargs=2, metavar=("FROM", "TO"),
                    help="shortest link path between two pages (query mode)")
    ga.add_argument("--around", metavar="PAGE",
                    help="pages within --depth hops of PAGE (query mode; blast radius with --direction in)")
    ga.add_argument("--depth", type=int, default=2, help="hops for --around (default: 2)")
    ga.add_argument("--direction", choices=["both", "in", "out"], default="both",
                    help="link direction for --around / --path (default: both)")
    ga.add_argument("--diff-against", metavar="FILE",
                    help="previous _insights.md (GRAPH_SNAPSHOT comment) or snapshot JSON to diff against")
    ga.add_argument("--snapshot", action="store_true",
                    help="include a compact graph snapshot in the output for future --diff-against")
    ga.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    ga.set_defaults(func=cmd_graph_analyse)

    sb = sub.add_parser(
        "sessions-build",
        help="build a topic graph over your agent session history (writes a sidecar, not the vault)",
    )
    sb.add_argument("--claude-dir", default=DEFAULT_CLAUDE_DIR,
                    help=f"agent session cache to read (default: {DEFAULT_CLAUDE_DIR})")
    sb.add_argument("--out", default=None,
                    help=f"output directory (default: $WIKI_SESSION_BRAIN_DIR or {DEFAULT_BRAIN_DIR})")
    sb.add_argument("--k", type=int, default=8, help="neighbours per session (default: 8)")
    sb.add_argument("--min-sim", type=float, default=0.08,
                    help="minimum cosine similarity for an edge (default: 0.08)")
    sb.add_argument("--mutual", action="store_true",
                    help="keep only mutual kNN edges — tighter, smaller clusters")
    sb.add_argument("--half-life", type=float, default=90.0,
                    help="recency half-life in days (default: 90)")
    sb.add_argument("--since", help="only read sessions modified on or after this ISO date")
    sb.add_argument("--skip",
                    help="comma-separated substrings of project dirs to skip (or $WIKI_SKIP_PROJECTS). "
                         "Cache dir names begin with '-', which argparse reads as a flag — pass the "
                         "bare name ('game') or use --skip=-w-game")
    sb.add_argument("--full", action="store_true", help="ignore caches and re-read every session")
    sb.add_argument("--no-html", action="store_true", help="skip writing graph.html")
    sb.add_argument("--bookmarks", help="path to bookmarks.json (default: ~/.bookmark-agent/bookmarks.json)")
    sb.add_argument("--json", action="store_true", help="emit JSON instead of a human summary")
    sb.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    sb.add_argument("-v", "--verbose", action="store_true", help="report progress to stderr")
    sb.set_defaults(func=cmd_sessions_build)

    sq = sub.add_parser(
        "sessions-query",
        help="find the sessions most relevant to a topic, ranked by similarity and recency",
    )
    sq.add_argument("question", help="topic or question to search for")
    sq.add_argument("--out", default=None, help="session-brain directory")
    sq.add_argument("--top", type=int, default=10, help="candidates to return (default: 10)")
    sq.add_argument("--max-load", type=int, default=3,
                    help="max sessions to recommend loading (default: 3)")
    sq.add_argument("--half-life", type=float, default=None,
                    help="override the recency half-life used at build time")
    sq.add_argument("--project", help="restrict to one project")
    sq.add_argument("--cluster", type=int, help="restrict to one topic cluster id")
    sq.add_argument("--since", help="only consider sessions ending on or after this ISO date")
    sq.add_argument("--min-score", type=float, default=0.05, help="drop candidates below this score")
    sq.add_argument("--json", action="store_true", help="emit JSON instead of a human summary")
    sq.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    sq.set_defaults(func=cmd_sessions_query)

    ssh = sub.add_parser(
        "sessions-show",
        help="show one session's graph node and its nearest neighbours",
    )
    ssh.add_argument("session_id", help="session id (full or unique prefix)")
    ssh.add_argument("--out", default=None, help="session-brain directory")
    ssh.add_argument("--neighbors", type=int, default=8, help="neighbours to include (default: 8)")
    ssh.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    ssh.set_defaults(func=cmd_sessions_show)

    scl = sub.add_parser("sessions-clusters", help="list the discovered topic clusters")
    scl.add_argument("--out", default=None, help="session-brain directory")
    scl.add_argument("--unnamed", action="store_true", help="only clusters that still need a name")
    scl.add_argument("--top", type=int, default=20, help="max clusters to list (default: 20)")
    scl.add_argument("--json", action="store_true", help="emit JSON instead of a human summary")
    scl.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    scl.set_defaults(func=cmd_sessions_clusters)

    snm = sub.add_parser("sessions-name", help="assign names to topic clusters (durable across rebuilds)")
    snm.add_argument("--out", default=None, help="session-brain directory")
    snm.add_argument("--from", dest="from_file", required=True, metavar="FILE",
                     help='JSON array of {"id": N, "name": "...", "summary": "..."}; use - for stdin')
    snm.set_defaults(func=cmd_sessions_name)

    cc = sub.add_parser(
        "cache-check",
        help="check which sources are new/modified/unchanged vs. .manifest.json",
    )
    cc.add_argument("vault", help="path to the Obsidian vault")
    cc.add_argument("sources", nargs="+", help="source file or directory paths to check")
    cc.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    cc.set_defaults(func=cmd_cache_check)

    cu = sub.add_parser(
        "cache-update",
        help="record a source's current SHA-256 hash in .manifest.json after ingestion",
    )
    cu.add_argument("vault", help="path to the Obsidian vault")
    cu.add_argument("source", help="source file or directory that was just ingested")
    cu.add_argument("--pages", nargs="*", metavar="PAGE", help="vault-relative paths of pages produced")
    cu.set_defaults(func=cmd_cache_update)

    ch = sub.add_parser(
        "cache-hash",
        help="compute the SHA-256 hash of a file or directory (no manifest I/O)",
    )
    ch.add_argument("path", help="file or directory to hash")
    ch.set_defaults(func=cmd_cache_hash)

    ap = sub.add_parser(
        "ast-extract",
        help="extract code structure (classes, functions, imports) from a file or directory — no LLM, no API calls",
    )
    ap.add_argument("path", help="file or directory to extract from")
    ap.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    ap.set_defaults(func=cmd_ast_extract)

    cdu = sub.add_parser(
        "code-understand",
        help="build a ranked code-understanding focus map for a project — CodeGraph when available, builtin AST + rg otherwise",
    )
    cdu.add_argument("--project", default=None, help="project directory (defaults to the current directory)")
    cdu.add_argument(
        "--backend",
        choices=["auto", "builtin", "codegraph"],
        default="auto",
        help="code-understanding backend (default: auto)",
    )
    cdu.add_argument(
        "--changed",
        action="append",
        default=None,
        metavar="FILE",
        help="treat FILE as a seed file (repeatable; overrides --since)",
    )
    cdu.add_argument(
        "--since",
        default=None,
        metavar="SHA",
        help="seed files changed since this git ref",
    )
    cdu.add_argument(
        "--max-symbols",
        type=int,
        default=50,
        help="maximum focus-map entries (default: 50)",
    )
    cdu.add_argument("--pretty", action="store_true", help="print a human-readable summary instead of JSON")
    cdu.set_defaults(func=cmd_code_understand)

    dr = sub.add_parser(
        "doctor",
        help="check config, vault shape, bootstrap assets, installed skills, and code-understanding readiness",
    )
    dr.add_argument("--vault", help="override OBSIDIAN_VAULT_PATH for this health check")
    dr.add_argument("--project", help="also check project-local bootstrap files in this directory")
    dr.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    dr.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    dr.add_argument("--strict", action="store_true", help="exit non-zero on warnings as well as failures")
    dr.set_defaults(func=cmd_doctor)

    lt = sub.add_parser(
        "lint",
        help="lint a vault for missing frontmatter, broken links, duplicates, and orphans",
    )
    lt.add_argument("vault", nargs="?", help="vault path or @name (defaults via CWD .env, then global config)")
    lt.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    lt.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    lt.add_argument("--strict", action="store_true", help="exit non-zero on warnings as well as failures")
    lt.add_argument(
        "--strict-trust",
        action="store_true",
        help=(
            "fail lint on missing trust fields, ledger errors, stale reviews, and "
            "score mismatches (default: legacy mode, these are warnings only). "
            "Also settable per-vault via OBSIDIAN_TRUST_STRICT=1 in the config."
        ),
    )
    lt.add_argument(
        "--allow-lifecycle",
        action="append",
        metavar="VALUE",
        help="extend the framework lifecycle allowlist (repeatable)",
    )
    lt.add_argument(
        "--allow-relationship-type",
        action="append",
        metavar="VALUE",
        help="extend the framework relationship-type allowlist (repeatable)",
    )
    lt.add_argument(
        "--required-trust-field",
        action="append",
        choices=("base_confidence", "lifecycle", "lifecycle_changed", "updated"),
        help="replace default trust-field requiredness (repeatable)",
    )
    lt.add_argument(
        "--schema-source",
        help="authority locator recorded in the lint report (for example, vault/AGENTS.md)",
    )
    lt.set_defaults(func=cmd_lint)

    tr = sub.add_parser(
        "trust-record",
        help="record explicitly approved manual confidence reviews in the vault trust ledger",
    )
    tr.add_argument("vault", nargs="?", help="vault path or @name (defaults via CWD .env, then global config)")
    selection = tr.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true", help="record every current trust-schema page")
    selection.add_argument(
        "--page",
        action="append",
        metavar="VAULT_RELATIVE_PATH",
        help="record only this explicitly reviewed page (repeatable)",
    )
    tr.add_argument("--reviewed-at", required=True, help="ISO timestamp for the approved review")
    tr.add_argument(
        "--approved",
        action="store_true",
        required=True,
        help="confirm a human approved every confidence value being recorded",
    )
    tr.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    tr.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tr.add_argument(
        "--allow-lifecycle",
        action="append",
        metavar="VALUE",
        help="extend the resolved vault lifecycle allowlist (repeatable)",
    )
    tr.add_argument(
        "--required-trust-field",
        action="append",
        choices=("base_confidence", "lifecycle", "lifecycle_changed", "updated"),
        help="replace resolved vault trust-field requiredness (repeatable)",
    )
    tr.add_argument("--schema-source", help="authority locator recorded in the result")
    tr.set_defaults(func=cmd_trust_record)

    tc = sub.add_parser(
        "trust-check",
        help="validate confidence values and material fingerprints against the manual trust ledger",
    )
    tc.add_argument("vault", nargs="?", help="vault path or @name (defaults via CWD .env, then global config)")
    tc.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    tc.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    tc.add_argument("--strict", action="store_true", help="exit non-zero on warnings as well as failures")
    tc.add_argument(
        "--allow-lifecycle",
        action="append",
        metavar="VALUE",
        help="extend the framework lifecycle allowlist (repeatable)",
    )
    tc.add_argument(
        "--required-trust-field",
        action="append",
        choices=("base_confidence", "lifecycle", "lifecycle_changed", "updated"),
        help="replace default trust-field requiredness (repeatable)",
    )
    tc.add_argument(
        "--schema-source",
        help="authority locator recorded in the trust report",
    )
    tc.set_defaults(func=cmd_trust_check)

    qq = sub.add_parser(
        "query",
        help="query the configured vault without passing the raw path each time",
    )
    qq.add_argument("question", help="question to ask against the vault index")
    qq.add_argument("--vault", help="override OBSIDIAN_VAULT_PATH for this query")
    qq.add_argument("--top", type=int, default=8, help="number of candidate pages to rank (default: 8)")
    qq.add_argument("--max-read", type=int, default=3, help="max pages to return in should_read (default: 3)")
    qq.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    qq.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    qq.set_defaults(func=cmd_query)

    cp = sub.add_parser(
        "context-pack",
        aliases=["context"],
        help="compile a token-bounded vault slice for a downstream agent",
    )
    cp.add_argument("topic", nargs="?", help="topic to retrieve; omit only with --recent")
    cp.add_argument("--vault", help="override OBSIDIAN_VAULT_PATH")
    cp.add_argument(
        "--budget",
        type=int,
        default=8_000,
        help="maximum estimated output tokens, 256..100000 (default: 8000)",
    )
    cp.add_argument("--recent", action="store_true", help="select recently updated notes")
    cp.add_argument(
        "--public-only",
        action="store_true",
        help="exclude visibility/internal and visibility/pii notes",
    )
    cp.add_argument(
        "--metadata-only",
        action="store_true",
        help="emit titles, provenance, and summaries without body excerpts",
    )
    cp.add_argument("--json", action="store_true", help="emit structured JSON")
    cp.add_argument("--pretty", action="store_true", help="pretty-print JSON output")
    cp.set_defaults(func=cmd_context_pack)

    return p


def _add_setup_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--vault", metavar="PATH", help="absolute path to your Obsidian vault")
    sp.add_argument(
        "--project",
        nargs="?",
        const="",
        default=None,
        metavar="DIR",
        help="also install project-local skills + bootstrap files into DIR "
        "(defaults to the current directory if no DIR given)",
    )
    sp.add_argument(
        "--project-only",
        action="store_true",
        help="skip the global agent install (use with --project)",
    )
    sp.add_argument(
        "--copy",
        action="store_true",
        help="copy skill files instead of symlinking to the installed package",
    )
    sp.add_argument(
        "--remote",
        metavar="URL",
        help="GitHub (or any git host) repo URL for vault sync — skips the interactive "
        "prompt and configures it non-interactively (see also: obsidian-wiki sync-setup)",
    )


def _configure_console_output() -> None:
    """Keep status output from aborting when a console encoding lacks Unicode."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (OSError, ValueError):
            continue


def main(argv: list[str] | None = None) -> int:
    _configure_console_output()
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    # No subcommand → default to `setup` (the common case).
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "-V", "--version")):
        argv = ["setup", *argv]
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    # Warn about stale installs on every command except `setup` (which fixes it)
    # and `info` (which calls _check_stale itself with richer output).
    if getattr(args, "command", None) not in ("setup", "info", "doctor", None):
        _check_stale()
    try:
        return args.func(args)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
