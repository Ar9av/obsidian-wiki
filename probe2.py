import sys, tempfile, pathlib
sys.path.insert(0, ".")
from obsidian_wiki.lint import lint_vault

def page(v, rel, links=()):
    p = v / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\ntitle: T\ncategory: concepts\ntags: [a]\nsources: []\n"
        "created: 2026-01-01\nupdated: 2026-01-01\nsummary: s\n---\n\n"
        + "\n".join(f"- [[{l}]]" for l in links) + "\n", encoding="utf-8")

for name, link in [("Node.js", "Node.js"), ("Next.js", "Next.js"),
                   ("v1.2 release notes", "v1.2 release notes"),
                   ("GPT-4.1 eval", "GPT-4.1 eval"), ("plain", "plain")]:
    v = pathlib.Path(tempfile.mkdtemp()) / "vault"
    page(v, f"entities/{name}.md"); page(v, "concepts/index.md", links=[link])
    r = lint_vault(v)
    print(f"{name:22} links={r['stats']['link_count']} orphans={r['findings']['orphan_pages']}")
