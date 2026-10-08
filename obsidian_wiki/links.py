"""One link resolver for every module that builds a graph or checks links.

`graph_analysis`, `graphrag`, and `lint` each identified a page by its slugged
filename stem and resolved a link by its last path segment. Two pages with the
same name — `projects/a/index.md` and `projects/b/index.md`, or the same
concept in two project sub-wikis — therefore became ONE graph node, and a
project-relative link such as `[[concepts/plan]]` written inside `projects/a/`
was reported missing. This module resolves links the way Obsidian does and
gives colliding pages distinct ids, while a vault without collisions keeps
exactly the ids it always had (the slugged stem).
"""

from __future__ import annotations

import posixpath
import re
from collections import defaultdict
from typing import Iterable, Optional

#: Obsidian does not treat a `[[link]]` inside inline code or a fenced block as
#: a link, so neither does anything that walks the link graph.
_FENCE_RE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.MULTILINE | re.DOTALL)
# Single-line on purpose: a stray backtick must not swallow the rest of a page.
_INLINE_CODE_RE = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)")


def strip_code(text: str) -> str:
    """`text` with fenced code blocks and inline code spans removed."""
    return _INLINE_CODE_RE.sub("", _FENCE_RE.sub("", text))


def slug(name: str) -> str:
    """Normalise one page name / path segment the way page ids are keyed."""
    return name.strip().lower().replace(" ", "-")


def _key(path: str) -> str:
    """Slugged vault-relative path without `.md`: `Concepts/My Page.md` -> `concepts/my-page`."""
    path = path.strip().rstrip("\\")
    if path.lower().endswith(".md"):
        path = path[:-3]
    return "/".join(slug(part) for part in path.strip("/").split("/") if part and part != ".")


def _shared_dirs(a: str, b: str) -> int:
    """How many leading directories two keys have in common."""
    count = 0
    for left, right in zip(a.split("/")[:-1], b.split("/")[:-1]):
        if left != right:
            break
        count += 1
    return count


class PageIndex:
    """Page ids and Obsidian-style link resolution over one set of pages.

    A page's id is its slugged stem when no other page shares that stem, and
    its slugged vault-relative path otherwise, so ids stay stable for any vault
    without name collisions.
    """

    def __init__(self, rel_paths: Iterable[str]) -> None:
        self._keys: dict[str, str] = {}
        self._by_stem: dict[str, list[str]] = defaultdict(list)
        # Files whose paths normalise to the same key (`Foo Bar.md` and
        # `foo-bar.md`) share one id, as they always have; a link to that key
        # is ambiguous because nothing distinguishes them.
        self._key_files: dict[str, int] = defaultdict(int)
        for rel in rel_paths:
            key = _key(rel)
            if not key:
                continue
            self._key_files[key] += 1
            if key not in self._keys:
                self._keys[key] = rel
                self._by_stem[key.rsplit("/", 1)[-1]].append(key)
        self._ids = {
            key: key.rsplit("/", 1)[-1] if len(self._by_stem[key.rsplit("/", 1)[-1]]) == 1 else key
            for key in self._keys
        }

    def ids(self) -> list[str]:
        return list(self._ids.values())

    def id_for(self, rel_path: str) -> str:
        return self._ids[_key(rel_path)]

    def path_for(self, page_id: str) -> Optional[str]:
        """Vault-relative path of an id (or of any unambiguous key)."""
        for key, value in self._ids.items():
            if value == page_id:
                return self._keys[key]
        return None

    def _nearest(self, candidates: list[str], source_key: str) -> str:
        """The candidate Obsidian would pick from `source_key`: the one sharing
        the most folders with the linking page, then the shortest path."""
        return min(
            candidates,
            key=lambda key: (-_shared_dirs(key, source_key) if source_key else 0, key.count("/"), key),
        )

    def _candidates(self, target: str, source: Optional[str]) -> list:
        """Keys a link could mean, in resolution order: one key when the link
        is exact, several when it is a suffix or bare name shared by pages."""
        raw = target.strip().rstrip("\\")
        source_key = _key(source) if source else ""
        source_dir = source_key.rsplit("/", 1)[0] if "/" in source_key else ""
        if raw.startswith(("./", "../")):
            joined = posixpath.normpath(posixpath.join(source_dir, raw))
            key = "" if joined.startswith("..") else _key(joined)
            return [key] if key in self._keys else []
        key = _key(raw)
        if not key:
            return []
        if "/" in key:
            if key in self._keys:
                return [key]
            local = f"{source_dir}/{key}" if source_dir else key
            if local in self._keys:
                return [local]
            suffixed = [k for k in self._keys if k.endswith(f"/{key}")]
            if suffixed:
                return suffixed
        return list(self._by_stem.get(key.rsplit("/", 1)[-1], []))

    def resolve(self, target: str, source: Optional[str] = None) -> Optional[str]:
        """Id of the page a link `target` points at from page `source`, or None.

        `target` is the bare link target (no `[[`, alias, or heading anchor).
        Order: `./` / `../` relative to the linking file, an exact vault path,
        a path relative to the linking file's folder, a path suffix (the
        nearest when several match), and finally the bare name (the nearest
        page with that stem) so an over-qualified link still resolves.
        """
        candidates = self._candidates(target, source)
        if not candidates:
            return None
        return self._ids[self._nearest(candidates, _key(source) if source else "")]

    def is_ambiguous(self, target: str, source: Optional[str] = None) -> bool:
        """True when several pages match and none is nearer to `source` than
        the rest, so the link's meaning depends on a tie-break."""
        candidates = self._candidates(target, source)
        if len(candidates) == 1:
            return self._key_files[candidates[0]] > 1
        if len(candidates) < 2:
            return False
        source_key = _key(source) if source else ""
        scores = sorted((_shared_dirs(key, source_key) for key in candidates), reverse=True)
        return scores[0] == scores[1]

    def match(self, term: str) -> Optional[str]:
        """Id for a free-text page reference (a CLI argument): an id, a path, or
        a bare name. A bare name shared by several pages picks the shortest path."""
        key = _key(term)
        if key in self._ids.values():
            return key
        return self.resolve(term)
