"""Tests for `obsidian-wiki memory timezone`: converting a vault's existing stamps.

The guarantees: the preview writes nothing; every zoned stamp — frontmatter,
log line, hot cache, page body, the adoption record — is re-rendered by its own
instant, so DST is right per stamp; bare dates, naive stamps, backup-directory
names, JSON ledgers, `_archives/` and `_raw/_archived/` are left alone; every
file that changes is backed up first; the run is logged; running twice changes
nothing; and the docs name the command.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from obsidian_wiki import clock
from obsidian_wiki import memory as mem

ROOT = Path(__file__).resolve().parent.parent
DETROIT = ZoneInfo("America/Detroit")

PAGE = """---
title: Attention
summary: Core block
tags: [ml]
created: 2026-10-10T18:40:37Z
updated: 2026-11-02T18:40:37Z
lifecycle_changed: 2026-10-10
---

# Attention

Quoted at 2026-10-10T18:40:37Z and again at 2026-10-10T20:40:37+02:00; naive 2026-10-10T18:40:37 stays.
Backup dir _archives/pre-memory-migration-20261010T184037Z stays too.
"""


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    for name in ("concepts", "_meta", "_raw/_archived", "_staging", "_archives/old"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "index.md").write_text(
        "---\ntitle: Wiki Index\ngenerated_by: obsidian-wiki memory index\n---\n\n# Wiki Index\n\n"
        "*Last updated: 2026-10-10T18:40:37Z*\n\n## Concepts\n\n- [[concepts/attention]] — Core block\n",
        encoding="utf-8",
    )
    (tmp_path / "concepts" / "attention.md").write_text(PAGE, encoding="utf-8")
    (tmp_path / "log.md").write_text(
        "---\ntitle: Wiki Log\n---\n\n# Wiki Log\n\n"
        "- [2026-10-10T20:27:32Z] INGEST source=x\n"
        "- [2026-09-24T17:38:12-06:00] UPDATE pages_updated=1\n",
        encoding="utf-8",
    )
    (tmp_path / "hot.md").write_text(
        "---\ntitle: Hot Cache\nupdated: 2026-10-10T20:32:54Z\npages: 1\ngenerated_by: obsidian-wiki memory hot\n---\n\n# Hot Cache\n",
        encoding="utf-8",
    )
    (tmp_path / "_meta" / ".memory-adopted").write_text("adopted: 2026-10-02T15:43:45Z\nby: obsidian-wiki memory\n", encoding="utf-8")
    (tmp_path / "_meta" / "ledger.json").write_text('{"reviewed_at": "2026-10-10T18:40:37Z"}', encoding="utf-8")
    (tmp_path / "_raw" / "draft.md").write_text("draft 2026-10-10T18:40:37Z\n", encoding="utf-8")
    (tmp_path / "_raw" / "_archived" / "source.md").write_text("Date: 2026-10-10T18:40:37Z\n", encoding="utf-8")
    (tmp_path / "_staging" / "staged.md").write_text("staged 2026-10-10T18:40:37Z\n", encoding="utf-8")
    (tmp_path / "_archives" / "old" / "index.md").write_text("old 2026-10-10T18:40:37Z\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("Example stamp: 2026-10-10T18:40:37Z\n", encoding="utf-8")
    return tmp_path


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "memory", *args],
        capture_output=True, text=True,
    )


def _snapshot(vault: Path) -> dict:
    return {p.relative_to(vault).as_posix(): p.read_text(encoding="utf-8")
            for p in vault.rglob("*") if p.is_file()}


# --------------------------------------------------------------------------
# pure conversion
# --------------------------------------------------------------------------


class TestConvert:
    def test_each_stamp_converts_by_its_own_instant(self) -> None:
        assert clock.convert_stamp("2026-10-10T18:40:37Z", DETROIT) == "2026-10-10T14:40:37-04:00"
        assert clock.convert_stamp("2026-11-02T18:40:37Z", DETROIT) == "2026-11-02T13:40:37-05:00"
        assert clock.convert_stamp("2026-09-24T17:38:12-06:00", DETROIT) == "2026-09-24T19:38:12-04:00"

    def test_spellings_without_colon_or_seconds_and_with_fractions(self) -> None:
        assert clock.convert_stamp("2026-10-10T18:40:37.123456+0000", DETROIT) == "2026-10-10T14:40:37-04:00"
        assert clock.convert_stamp("2026-10-10T18:40Z", DETROIT) == "2026-10-10T14:40:00-04:00"

    def test_already_in_the_zone_is_identical(self) -> None:
        assert clock.convert_stamp("2026-10-10T14:40:37-04:00", DETROIT) == "2026-10-10T14:40:37-04:00"
        assert clock.convert_stamp("2026-10-10T18:40:37Z", None) == "2026-10-10T18:40:37Z"

    def test_back_to_utc(self) -> None:
        assert clock.convert_stamp("2026-10-10T14:40:37-04:00", None) == "2026-10-10T18:40:37Z"

    def test_what_is_not_a_zoned_stamp(self) -> None:
        for text in ("2026-10-10", "2026-10-10T18:40:37", "20261010T184037Z", "not a stamp", "2026-13-45T99:99:99Z"):
            assert clock.convert_stamp(text, DETROIT) is None, text

    def test_convert_text_reports_lines_and_leaves_the_rest(self) -> None:
        new, changes, naive = clock.convert_text(PAGE, DETROIT)
        assert [(c.line, c.old) for c in changes] == [
            (5, "2026-10-10T18:40:37Z"), (6, "2026-11-02T18:40:37Z"),
            (12, "2026-10-10T18:40:37Z"), (12, "2026-10-10T20:40:37+02:00"),
        ]
        assert naive == 1
        assert "created: 2026-10-10T14:40:37-04:00" in new
        assert "updated: 2026-11-02T13:40:37-05:00" in new
        assert "lifecycle_changed: 2026-10-10\n" in new
        assert "again at 2026-10-10T14:40:37-04:00;" in new
        assert "naive 2026-10-10T18:40:37 stays" in new
        assert "pre-memory-migration-20261010T184037Z" in new
        again, changes2, _ = clock.convert_text(new, DETROIT)
        assert again == new and changes2 == []


# --------------------------------------------------------------------------
# plan and apply
# --------------------------------------------------------------------------


class TestPlan:
    def test_preview_counts_and_writes_nothing(self, vault: Path) -> None:
        before = _snapshot(vault)
        plan = mem.timezone_migration_plan(vault, "America/Detroit")
        assert _snapshot(vault) == before
        paths = {f["path"]: len(f["stamps"]) for f in plan["files"]}
        assert paths == {
            "index.md": 1, "concepts/attention.md": 4, "log.md": 2, "hot.md": 1,
            "_meta/.memory-adopted": 1, "_raw/draft.md": 1, "_staging/staged.md": 1,
        }
        assert plan["file_count"] == 7 and plan["stamp_count"] == 11
        assert plan["naive_skipped"] == 1 and plan["bare_dates"] == 1
        assert plan["timezone"] == "America/Detroit" and plan["key_current"] == ""

    def test_needs_a_zone_from_somewhere(self, vault: Path) -> None:
        with pytest.raises(mem.MemoryError_, match="no timezone"):
            mem.timezone_migration_plan(vault)
        clock.set_timezone(vault, "America/Detroit")
        assert mem.timezone_migration_plan(vault)["timezone"] == "America/Detroit"
        with pytest.raises(clock.TimezoneError):
            mem.timezone_migration_plan(vault, "America/Detroi")

    def test_skip_globs(self, vault: Path) -> None:
        plan = mem.timezone_migration_plan(vault, "America/Detroit", skip=["_raw/*", "concepts/attention.md"])
        assert {f["path"] for f in plan["files"]} == {"index.md", "log.md", "hot.md", "_meta/.memory-adopted", "_staging/staged.md"}


class TestApply:
    def test_converts_backs_up_records_and_logs(self, vault: Path) -> None:
        before = _snapshot(vault)
        result = mem.migrate_timezone(vault, "America/Detroit")
        assert result["key_set"] is True and clock.timezone_name(vault) == "America/Detroit"
        assert result["file_count"] == 7 and result["stamp_count"] == 11
        # every changed file has its original in the backup, index.md included
        backup = Path(result["backup_dir"])
        assert re.search(r"pre-timezone-migration-\d{8}T\d{6}-0[45]00$", backup.name)
        assert sorted(result["backup"]) == sorted(f["path"] for f in result["files"])
        for rel in result["backup"]:
            assert (backup / rel).read_text(encoding="utf-8") == before[rel], rel
        # the content moved as promised
        page = (vault / "concepts" / "attention.md").read_text(encoding="utf-8")
        assert "created: 2026-10-10T14:40:37-04:00" in page and "lifecycle_changed: 2026-10-10\n" in page
        log = (vault / "log.md").read_text(encoding="utf-8")
        assert "- [2026-10-10T16:27:32-04:00] INGEST" in log
        assert "- [2026-09-24T19:38:12-04:00] UPDATE" in log
        assert re.search(r"^- \[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-0[45]:00\] TIMEZONE zone=America/Detroit files=7 stamps=11 backup=_archives/pre-timezone-migration-\S+$", log, re.MULTILINE), log
        assert "adopted: 2026-10-02T11:43:45-04:00" in (vault / "_meta" / ".memory-adopted").read_text(encoding="utf-8")
        assert "timezone: America/Detroit" in (vault / "index.md").read_text(encoding="utf-8")
        # untouched on purpose
        after = _snapshot(vault)
        for rel in ("_meta/ledger.json", "_raw/_archived/source.md", "_archives/old/index.md", "AGENTS.md"):
            assert after[rel] == before[rel], rel

    def test_running_twice_changes_nothing(self, vault: Path) -> None:
        mem.migrate_timezone(vault, "America/Detroit")
        after_first = _snapshot(vault)
        plan = mem.timezone_migration_plan(vault)
        assert plan["file_count"] == 0 and plan["stamp_count"] == 0
        result = mem.migrate_timezone(vault)
        assert result["file_count"] == 0 and result["backup"] == [] and result["backup_dir"] == ""
        changed = {k for k in after_first if _snapshot(vault).get(k) != after_first[k]}
        assert changed == {"log.md"}  # only the second TIMEZONE line

    def test_back_to_utc_is_symmetric(self, vault: Path) -> None:
        mem.migrate_timezone(vault, "America/Detroit")
        page_detroit = (vault / "concepts" / "attention.md").read_text(encoding="utf-8")
        result = mem.migrate_timezone(vault, "UTC")
        assert result["timezone"] == "UTC" and clock.timezone_name(vault) == "UTC"
        page = (vault / "concepts" / "attention.md").read_text(encoding="utf-8")
        assert "created: 2026-10-10T18:40:37Z" in page and page != page_detroit
        assert re.search(r"^- \[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\] TIMEZONE zone=UTC", (vault / "log.md").read_text(encoding="utf-8"), re.MULTILINE)

    def test_the_memory_writer_keeps_working_afterwards(self, vault: Path) -> None:
        mem.migrate_timezone(vault, "America/Detroit")
        mem.mark_adopted(vault)
        line = mem.append_log(vault, "INGEST", {"source": "y"})
        assert re.match(r"^- \[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-0[45]:00\] INGEST", line)
        hot = mem.rebuild_hot(vault, force=True)
        assert re.search(r"^updated: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-0[45]:00$", hot.text, re.MULTILINE)
        assert mem.memory_status(vault)["timezone"] == "America/Detroit"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


class TestCli:
    def test_preview_is_the_default_and_exits_2_when_there_is_work(self, vault: Path) -> None:
        before = _snapshot(vault)
        result = _cli("timezone", "America/Detroit", "--vault", str(vault))
        assert result.returncode == 2, result.stderr
        assert _snapshot(vault) == before
        out = result.stdout
        assert "timezone: America/Detroit (not yet in index.md; --apply records it)" in out
        assert "7 file(s), 11 stamp(s) would change; 1 naive stamp(s) and 1 bare date(s) left alone" in out
        assert "concepts/attention.md" in out and "2026-10-10T18:40:37Z  ->  2026-10-10T14:40:37-04:00" in out
        assert "Apply with: obsidian-wiki memory timezone America/Detroit --apply" in out

    def test_apply_and_then_nothing_to_do(self, vault: Path) -> None:
        result = _cli("timezone", "America/Detroit", "--apply", "--vault", str(vault))
        assert result.returncode == 0, result.stderr
        assert "timezone: America/Detroit (recorded in index.md)" in result.stdout
        assert "backed up 7 file(s) to" in result.stdout
        assert "TIMEZONE zone=America/Detroit files=7 stamps=11" in result.stdout
        again = _cli("timezone", "--vault", str(vault))
        assert again.returncode == 0, again.stderr
        assert "0 file(s), 0 stamp(s) would change" in again.stdout

    def test_json_skip_and_errors(self, vault: Path) -> None:
        result = _cli("timezone", "America/Detroit", "--skip", "_raw/*", "--json", "--vault", str(vault))
        assert result.returncode == 2, result.stderr
        plan = json.loads(result.stdout)
        assert plan["skip"] == ["_raw/*"] and "_raw/draft.md" not in {f["path"] for f in plan["files"]}
        missing = _cli("timezone", "--vault", str(vault))
        assert missing.returncode == 1 and "no timezone to convert to" in missing.stderr
        bad = _cli("timezone", "Americas/Detroit", "--vault", str(vault))
        assert bad.returncode == 1 and "Americas/Detroit" in bad.stderr


class TestDocs:
    def test_the_command_is_documented(self) -> None:
        for name in ("docs/cli.md", "docs/memory.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            assert "memory timezone" in text, f"{name} does not name `memory timezone`"
            assert "pre-timezone-migration" in text, f"{name} does not name the backup directory"
