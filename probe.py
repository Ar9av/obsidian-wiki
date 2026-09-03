import sys, tempfile, pathlib, json
sys.path.insert(0, ".")
from obsidian_wiki.lint import lint_vault

def page(v, rel, links=()):
    p = v / rel; p.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"- [[{l}]]" for l in links)
    p.write_text(
        "---\ntitle: T\ncategory: concepts\ntags: [a]\nsources: []\n"
        "created: 2026-01-01\nupdated: 2026-01-01\nsummary: s\n---\n\n" + body + "\n",
        encoding="utf-8")

v = pathlib.Path(tempfile.mkdtemp()) / "vault"
page(v, "entities/Node.js.md")
page(v, "concepts/index.md", links=["Node.js"])
r = lint_vault(v)
print("broken_links:", r["findings"]["broken_links"])
print("orphan_pages:", r["findings"]["orphan_pages"])
print("link_count:", r["stats"]["link_count"])
