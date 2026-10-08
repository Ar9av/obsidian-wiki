"""Links resolve the way Obsidian resolves them, across every graph consumer.

A vault of per-project sub-wikis has pages that share a name
(`projects/*/index.md`, the same concept in two projects) and links written
relative to their project. Before `obsidian_wiki/links.py`, graph-analyse,
graph-query, and lint keyed pages by bare filename, so those pages merged into
one node and project-relative links were reported missing.
"""

from __future__ import annotations

from pathlib import Path

from obsidian_wiki.graph_analysis import neighborhood, parse_vault_graph, shortest_path
from obsidian_wiki.graphrag import build_index
from obsidian_wiki.links import PageIndex, strip_code
from obsidian_wiki.lint import lint_vault


def _write(vault: Path, rel: str, body: str = "", frontmatter: str = "") -> None:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    head = (
        f"---\ntitle: {path.stem}\ncategory: concepts\ntags: [a]\nsources: []\n"
        f"created: 2026-01-01\nupdated: 2026-01-01\nsummary: s\n{frontmatter}---\n\n"
    )
    path.write_text(head + body + "\n", encoding="utf-8")


def _two_projects(vault: Path) -> None:
    for name in ("alpha", "beta"):
        _write(vault, f"projects/{name}/index.md", f"[[concepts/plan]] [[decisions/{name}-choice]]")
        _write(vault, f"projects/{name}/concepts/plan.md", "See [[index]].")
        _write(vault, f"projects/{name}/decisions/{name}-choice.md", "[[../concepts/plan]]")
    _write(vault, "concepts/shared.md", "No collision here: [[projects/alpha/concepts/plan]]")


# -- PageIndex --------------------------------------------------------------


def test_unique_names_keep_their_bare_ids() -> None:
    index = PageIndex(["concepts/Vector Search.md", "entities/karpathy.md"])
    assert sorted(index.ids()) == ["karpathy", "vector-search"]
    assert index.resolve("Vector Search", "synthesis/x.md") == "vector-search"
    assert index.resolve("concepts/vector-search.md", None) == "vector-search"


def test_shared_names_get_path_ids_and_resolve_to_the_nearest_page() -> None:
    index = PageIndex(["projects/a/concepts/plan.md", "projects/b/concepts/plan.md"])
    assert sorted(index.ids()) == ["projects/a/concepts/plan", "projects/b/concepts/plan"]
    assert index.resolve("plan", "projects/b/index.md") == "projects/b/concepts/plan"
    assert index.resolve("concepts/plan", "projects/a/index.md") == "projects/a/concepts/plan"
    assert index.resolve("../concepts/plan", "projects/b/decisions/d.md") == "projects/b/concepts/plan"
    assert not index.is_ambiguous("plan", "projects/a/index.md")
    assert index.is_ambiguous("plan", "synthesis/elsewhere.md")  # nothing breaks the tie


def test_relative_link_cannot_escape_the_vault() -> None:
    assert PageIndex(["a.md"]).resolve("../../a", "x/y.md") is None


def test_strip_code_drops_fences_and_inline_spans_only() -> None:
    text = "Real [[a]]. Example `[[b]]`.\n```\n[[c]]\n```\nAfter [[d]]."
    kept = strip_code(text)
    assert "[[a]]" in kept and "[[d]]" in kept
    assert "[[b]]" not in kept and "[[c]]" not in kept


# -- every consumer ---------------------------------------------------------


def test_graph_keeps_same_named_pages_apart(tmp_path: Path) -> None:
    _two_projects(tmp_path)
    outgoing, _ = parse_vault_graph(tmp_path)
    assert "projects/alpha/index" in outgoing and "projects/beta/index" in outgoing
    assert "index" not in outgoing
    assert sorted(outgoing["projects/beta/index"]) == ["beta-choice", "projects/beta/concepts/plan"]
    assert outgoing["projects/alpha/concepts/plan"] == ["projects/alpha/index"]
    assert outgoing["beta-choice"] == ["projects/beta/concepts/plan"]
    assert outgoing["shared"] == ["projects/alpha/concepts/plan"]


def test_graph_queries_accept_a_bare_name_for_a_shared_page(tmp_path: Path) -> None:
    _two_projects(tmp_path)
    outgoing, _ = parse_vault_graph(tmp_path)
    assert shortest_path(outgoing, "beta-choice", "projects/beta/index") is not None
    assert neighborhood(outgoing, "plan", depth=1)  # a bare shared name still finds a node


def test_graph_query_index_matches_the_graph(tmp_path: Path) -> None:
    _two_projects(tmp_path)
    index = build_index(tmp_path)
    assert index["projects/alpha/index"]["path"] == "projects/alpha/index.md"
    assert sorted(index["projects/alpha/concepts/plan"]["in_links"]) == [
        "alpha-choice", "projects/alpha/index", "shared",
    ]


def test_lint_resolves_project_relative_links_and_relationships(tmp_path: Path) -> None:
    _two_projects(tmp_path)
    _write(
        tmp_path,
        "projects/alpha/concepts/router.md",
        "Uses the plan.",
        frontmatter='relationships:\n  - target: "[[concepts/plan]]"\n    type: uses\n',
    )
    findings = lint_vault(tmp_path, require_trust_ledger=False)["findings"]
    assert findings["broken_links"] == []
    assert findings["typed_relationship_issues"] == []


def test_lint_ignores_links_in_code_and_still_reports_real_breaks(tmp_path: Path) -> None:
    _write(tmp_path, "concepts/a.md", "Write `[[wikilinks]]` like this.\n\n```\n[[example]]\n```\n[[missing]]")
    broken = lint_vault(tmp_path, require_trust_ledger=False)["findings"]["broken_links"]
    assert broken == [{"page": "concepts/a.md", "target": "missing"}]


def test_agent_instruction_files_are_not_pages(tmp_path: Path) -> None:
    _write(tmp_path, "concepts/a.md", "Conventions live in [[CLAUDE]].")  # still a real link target
    for rel in ("AGENTS.md", "README.md", "projects/alpha/CLAUDE.md", "projects/alpha/AGENTS.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("# Instructions\n", encoding="utf-8")
    _write(tmp_path, "projects/alpha/README.md")  # below the root a README can be a page

    report = lint_vault(tmp_path, require_trust_ledger=False)
    assert report["stats"]["pages"] == 2
    assert "README" not in str(report["findings"]["missing_frontmatter"])
    assert report["findings"]["broken_links"] == []
