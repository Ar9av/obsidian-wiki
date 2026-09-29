"""Tests for the local AST code extractor."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from obsidian_wiki.ast_extractor import extract, extract_file, extract_directory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_py(tmp_path):
    src = tmp_path / "sample.py"
    src.write_text(textwrap.dedent("""\
        import os
        from pathlib import Path

        class Animal:
            pass

        class Dog(Animal):
            pass

        def fetch(item):
            return item
    """))
    return src


@pytest.fixture
def tmp_js(tmp_path):
    src = tmp_path / "app.js"
    src.write_text(textwrap.dedent("""\
        import { foo } from './utils';

        class Widget extends Base {
            render() {}
        }

        function init() {}
    """))
    return src


@pytest.fixture
def tmp_dir(tmp_path, tmp_py, tmp_js):
    return tmp_path


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

class TestExtractFile:
    def test_python_classes(self, tmp_py):
        g = extract_file(tmp_py)
        labels = {n.label for n in g.nodes}
        assert "Animal" in labels
        assert "Dog" in labels

    def test_python_functions(self, tmp_py):
        g = extract_file(tmp_py)
        labels = {n.label for n in g.nodes}
        assert "fetch" in labels

    def test_python_imports(self, tmp_py):
        g = extract_file(tmp_py)
        labels = {n.label for n in g.nodes}
        assert "os" in labels
        assert "pathlib" in labels

    def test_python_inheritance_edge(self, tmp_py):
        g = extract_file(tmp_py)
        relations = {(e.source.split("::")[-1], e.target.split("::")[-1], e.relation)
                     for e in g.edges}
        assert ("Dog", "Animal", "inherits") in relations

    def test_python_multiple_inheritance_edges(self, tmp_path):
        src = tmp_path / "multi.py"
        src.write_text(textwrap.dedent("""\
            class Animal:
                pass

            class Mixin:
                pass

            class Dog(Animal, Mixin):
                pass
        """))
        g = extract_file(src)
        relations = {(e.source.split("::")[-1], e.target.split("::")[-1], e.relation)
                     for e in g.edges}
        assert ("Dog", "Animal", "inherits") in relations
        assert ("Dog", "Mixin", "inherits") in relations
        assert not any(target == "Animal, Mixin" for _, target, _ in relations)

    def test_python_inheritance_skips_metaclass_kwarg(self, tmp_path):
        src = tmp_path / "meta.py"
        src.write_text(textwrap.dedent("""\
            class Base:
                pass

            class Foo(Base, metaclass=type):
                pass
        """))
        g = extract_file(src)
        inherits = {(e.source.split("::")[-1], e.target.split("::")[-1])
                    for e in g.edges if e.relation == "inherits"}
        assert inherits == {("Foo", "Base")}

    def test_python_inheritance_generic_base_not_split_on_internal_comma(self, tmp_path):
        src = tmp_path / "generic.py"
        src.write_text(textwrap.dedent("""\
            class Base:
                pass

            class Foo(Mapping[str, int], Base):
                pass
        """))
        g = extract_file(src)
        inherits = {(e.source.split("::")[-1], e.target.split("::")[-1])
                    for e in g.edges if e.relation == "inherits"}
        assert inherits == {("Foo", "Mapping"), ("Foo", "Base")}

    def test_javascript_class_and_function(self, tmp_js):
        g = extract_file(tmp_js)
        labels = {n.label for n in g.nodes}
        assert "Widget" in labels
        assert "init" in labels

    def test_javascript_inheritance(self, tmp_js):
        g = extract_file(tmp_js)
        relations = {(e.source.split("::")[-1], e.target.split("::")[-1], e.relation)
                     for e in g.edges}
        assert ("Widget", "Base", "inherits") in relations

    def test_file_node_present(self, tmp_py):
        g = extract_file(tmp_py)
        file_nodes = [n for n in g.nodes if n.kind == "file"]
        assert len(file_nodes) == 1

    def test_unknown_extension_returns_empty(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b,c\n1,2,3\n")
        g = extract_file(f)
        assert g.nodes == []
        assert g.edges == []


class TestExtractDirectory:
    def test_multi_language(self, tmp_dir):
        g = extract_directory(tmp_dir)
        langs = g.stats.get("languages", {})
        assert "python" in langs
        assert "javascript" in langs

    def test_files_processed_count(self, tmp_dir):
        g = extract_directory(tmp_dir)
        assert g.stats["files_processed"] == 2

    def test_nodes_merged(self, tmp_dir):
        g = extract_directory(tmp_dir)
        assert len(g.nodes) > 5


class TestExtractEntry:
    def test_file_path(self, tmp_py):
        result = extract(tmp_py)
        assert "nodes" in result
        assert "edges" in result
        assert "god_nodes" in result
        assert "stats" in result

    def test_dir_path(self, tmp_dir):
        result = extract(tmp_dir)
        assert result["stats"]["files_processed"] == 2

    def test_missing_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            extract(tmp_path / "nonexistent.py")

    def test_god_nodes_is_list(self, tmp_dir):
        result = extract(tmp_dir)
        assert isinstance(result["god_nodes"], list)

    def test_output_is_json_serialisable(self, tmp_dir):
        result = extract(tmp_dir)
        json.dumps(result)  # must not raise


class TestCLI:
    def test_cli_ast_extract_file(self, tmp_py):
        proc = subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", "ast-extract", str(tmp_py)],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data["stats"]["nodes"] > 0

    def test_cli_ast_extract_pretty(self, tmp_py):
        proc = subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", "ast-extract", str(tmp_py), "--pretty"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0
        # Pretty mode produces indented JSON
        assert "\n  " in proc.stdout

    def test_cli_missing_path_exits_nonzero(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", "ast-extract", str(tmp_path / "nope.py")],
            capture_output=True, text=True,
        )
        assert proc.returncode != 0
