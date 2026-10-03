"""Report README translation drift.

Every tracked README_<LANG>.md at the repo root is a translation of
README.md. For each one, lists commits that changed README.md after the
last commit that touched the translation, plus the combined English diff
that still needs to be translated and backfilled. Advisory only — exits 1
on drift so callers can detect it, but CI never uses it to block a merge.
"""
from __future__ import annotations

import subprocess


ENGLISH = "README.md"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def translations() -> list[str]:
    # Tracked files only: an untracked draft isn't a translation yet.
    return sorted(git("ls-files", "README_*.md").split())


def report(translation: str) -> bool:
    """Print the drift for one translation; True if it is behind."""
    # ponytail: a translation-only commit marks everything before it as
    # synced; per-commit pairing if that ever misleads
    last = git("log", "-1", "--format=%H", "--", translation).strip()
    log_range = f"{last}..HEAD" if last else "HEAD"
    pending = git(
        "log", "--format=%h %s", log_range, "--", ENGLISH
    ).strip()

    if not pending:
        print(f"{translation} is up to date with {ENGLISH}.")
        return False

    print(f"Commits that changed {ENGLISH} without a later {translation} update:")
    print(pending)
    print()
    print(f"English changes not yet reflected in {translation}:")
    if last:
        print(git("diff", log_range, "--", ENGLISH))
    else:
        print(f"{translation} has no history - the entire {ENGLISH} is untranslated.")
    print(f"Translate the changes above and backfill them into {translation}.")
    return True


def main() -> int:
    found = translations()
    if not found:
        print(f"No README_<LANG>.md translations of {ENGLISH} found.")
        return 0
    behind = [t for t in found if report(t)]
    return 1 if behind else 0


if __name__ == "__main__":
    raise SystemExit(main())
