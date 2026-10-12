"""Tests for the wiki clock (`obsidian_wiki.clock`) and the writers that use it.

The guarantees: a vault without ``timezone:`` gets byte-identical stamps to
before (UTC, ``Z``); a vault with one gets that zone's own offset on every
stamp, correct across a daylight-saving transition; bare dates are calendar
days in the zone; a misspelled zone fails the write instead of silently
writing UTC; and the docs name the knob.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from obsidian_wiki import clock
from obsidian_wiki import memory as mem

ROOT = Path(__file__).resolve().parent.parent
DETROIT = ZoneInfo("America/Detroit")
Z_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
OFFSET_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
DETROIT_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-0[45]:00$")
BARE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _index(vault: Path, *extra: str) -> Path:
    lines = ["---", "title: Wiki Index", *extra, "generated_by: obsidian-wiki memory index", "---", "", "# Wiki Index", ""]
    path = vault / "index.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    for name in ("concepts", "_meta"):
        (tmp_path / name).mkdir()
    (tmp_path / "concepts" / "attention.md").write_text(
        "---\ntitle: Attention\nsummary: Core block\ntags: [ml]\nupdated: 2026-09-01\n---\n\n# Attention\n\nBody.\n",
        encoding="utf-8",
    )
    _index(tmp_path)
    return tmp_path


@pytest.fixture()
def detroit_vault(vault: Path) -> Path:
    _index(vault, "timezone: America/Detroit")
    return vault


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "memory", *args],
        capture_output=True, text=True,
    )


# --------------------------------------------------------------------------
# pure functions
# --------------------------------------------------------------------------


class TestParse:
    def test_empty_and_utc_mean_the_default(self) -> None:
        for name in ("", "  ", "UTC", "utc", "Z", '"UTC"'):
            assert clock.parse_timezone(name) is None, name

    def test_an_iana_name_resolves(self) -> None:
        assert clock.parse_timezone("America/Detroit") == DETROIT
        assert clock.parse_timezone("'Europe/Berlin'") == ZoneInfo("Europe/Berlin")

    def test_an_unknown_name_fails_loudly(self) -> None:
        with pytest.raises(clock.TimezoneError, match="Mars/Olympus"):
            clock.parse_timezone("Mars/Olympus")
        assert issubclass(clock.TimezoneError, ValueError)


class TestStamp:
    SUMMER = datetime(2026, 10, 10, 18, 40, 37, tzinfo=timezone.utc)   # EDT
    WINTER = datetime(2026, 11, 2, 18, 40, 37, tzinfo=timezone.utc)    # EST

    def test_default_is_the_original_z_form(self) -> None:
        assert clock.stamp(None, now=self.SUMMER) == "2026-10-10T18:40:37Z"
        assert clock.compact(None, now=self.SUMMER) == "20261010T184037Z"
        assert clock.today(None, now=self.SUMMER) == "2026-10-10"

    def test_a_zone_carries_its_own_offset_for_that_instant(self) -> None:
        assert clock.stamp(DETROIT, now=self.SUMMER) == "2026-10-10T14:40:37-04:00"
        assert clock.stamp(DETROIT, now=self.WINTER) == "2026-11-02T13:40:37-05:00"
        assert clock.compact(DETROIT, now=self.SUMMER) == "20261010T144037-0400"

    def test_a_zone_input_is_fine_too(self) -> None:
        local = self.SUMMER.astimezone(ZoneInfo("Asia/Tokyo"))
        assert clock.stamp(DETROIT, now=local) == "2026-10-10T14:40:37-04:00"
        assert clock.stamp(None, now=local) == "2026-10-10T18:40:37Z"

    def test_a_bare_date_is_the_calendar_day_in_the_zone(self) -> None:
        evening = datetime(2026, 10, 11, 0, 30, 0, tzinfo=timezone.utc)   # 20:30 the 10th in Detroit
        assert clock.today(None, now=evening) == "2026-10-11"
        assert clock.today(DETROIT, now=evening) == "2026-10-10"

    def test_live_stamps_have_the_expected_shape(self) -> None:
        assert Z_STAMP.match(clock.stamp(None))
        assert DETROIT_STAMP.match(clock.stamp(DETROIT))
        assert BARE_DATE.match(clock.today(DETROIT))

    def test_a_naive_now_is_refused(self) -> None:
        with pytest.raises(ValueError, match="aware"):
            clock.stamp(DETROIT, now=datetime(2026, 10, 10, 12, 0, 0))


class TestVaultLookup:
    def test_no_index_or_no_key_means_default(self, tmp_path: Path) -> None:
        assert clock.wiki_timezone(tmp_path) is None
        assert clock.timezone_name(tmp_path) == ""
        _index(tmp_path)
        assert clock.wiki_timezone(tmp_path) is None
        assert clock.timezone_name(tmp_path) == ""

    def test_the_key_is_read_from_index_frontmatter(self, detroit_vault: Path) -> None:
        assert clock.wiki_timezone(detroit_vault) == DETROIT
        assert clock.timezone_name(detroit_vault) == "America/Detroit"

    def test_quotes_are_tolerated(self, vault: Path) -> None:
        _index(vault, 'timezone: "Europe/Berlin"')
        assert clock.wiki_timezone(vault) == ZoneInfo("Europe/Berlin")

    def test_the_key_in_the_body_does_not_count(self, vault: Path) -> None:
        (vault / "index.md").write_text(
            "---\ntitle: Wiki Index\n---\n\n# Wiki Index\n\ntimezone: America/Detroit\n", encoding="utf-8"
        )
        assert clock.wiki_timezone(vault) is None

    def test_a_typo_raises(self, vault: Path) -> None:
        _index(vault, "timezone: America/Detroi")
        with pytest.raises(clock.TimezoneError):
            clock.wiki_timezone(vault)


# --------------------------------------------------------------------------
# the writers
# --------------------------------------------------------------------------


class TestWritersWithoutAZone:
    """The regression guard: nothing changes for a vault that never set the key."""

    def test_log_hot_adopted_and_tables_stay_utc_z(self, vault: Path) -> None:
        line = mem.append_log(vault, "INGEST", {"source": "x"})
        assert Z_STAMP.match(mem.parse_log_line(line).timestamp)
        hot = mem.rebuild_hot(vault, force=True)
        assert Z_STAMP.match(mem.parse_frontmatter(mem.split_frontmatter(hot.text)[0])["updated"])
        mem.mark_adopted(vault)
        adopted = (vault / mem.ADOPTED_REL).read_text(encoding="utf-8")
        assert re.search(r"^adopted: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", adopted, re.MULTILINE)
        todo = mem.add_todo(vault, "Ship the parser")
        assert BARE_DATE.match(todo.created) and todo.created == clock.today(None)
        fact = mem.set_fact(vault, "stack", "Python")
        assert fact.updated == clock.today(None)
        assert mem.memory_status(vault)["timezone"] == "UTC"


class TestWritersWithAZone:
    def test_every_stamp_carries_the_zone_offset(self, detroit_vault: Path) -> None:
        vault = detroit_vault
        line = mem.append_log(vault, "INGEST", {"source": "x"})
        assert DETROIT_STAMP.match(mem.parse_log_line(line).timestamp), line
        hot = mem.rebuild_hot(vault, force=True)
        updated = mem.parse_frontmatter(mem.split_frontmatter(hot.text)[0])["updated"]
        assert DETROIT_STAMP.match(updated), updated
        mem.mark_adopted(vault)
        adopted = (vault / mem.ADOPTED_REL).read_text(encoding="utf-8")
        assert re.search(r"^adopted: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-0[45]:00$", adopted, re.MULTILINE)

    def test_bare_dates_are_the_zone_calendar_day(self, detroit_vault: Path) -> None:
        vault = detroit_vault
        todo = mem.add_todo(vault, "Ship the parser", origin="projects/x.md")
        assert todo.created == clock.today(DETROIT) == todo.touched
        closed = mem.set_todo_status(vault, todo.id, "done")
        assert closed.touched == clock.today(DETROIT)
        fact = mem.set_fact(vault, "stack", "Python")
        assert fact.updated == clock.today(DETROIT)
        table = (vault / "_meta" / "todos.md").read_text(encoding="utf-8")
        assert f"created: {clock.today(DETROIT)}" in table
        assert mem.memory_status(vault)["timezone"] == "America/Detroit"

    def test_an_explicit_log_timestamp_still_wins(self, detroit_vault: Path) -> None:
        line = mem.append_log(detroit_vault, "INGEST", {}, timestamp="2026-01-01T00:00:00Z")
        assert line.startswith("- [2026-01-01T00:00:00Z] INGEST")

    def test_rebuilding_the_index_keeps_the_key(self, detroit_vault: Path) -> None:
        mem.rebuild_index(detroit_vault, force=True)
        assert clock.timezone_name(detroit_vault) == "America/Detroit"
        text = (detroit_vault / "index.md").read_text(encoding="utf-8")
        assert text.count("timezone:") == 1

    def test_the_migration_backup_uses_the_zone(self, detroit_vault: Path) -> None:
        (detroit_vault / "hot.md").write_text("# Hot\n\n## Key Takeaways\n\nhand-written\n", encoding="utf-8")
        result = mem.migrate(detroit_vault)
        assert re.search(r"pre-memory-migration-\d{8}T\d{6}-0[45]00$", result["backup_dir"]), result["backup_dir"]

    def test_a_typo_fails_the_write(self, vault: Path) -> None:
        _index(vault, "timezone: America/Detroi")
        with pytest.raises(clock.TimezoneError):
            mem.append_log(vault, "INGEST", {})
        assert not (vault / "log.md").exists()


# --------------------------------------------------------------------------
# the CLI
# --------------------------------------------------------------------------


class TestCli:
    def test_now_prints_the_stamp_to_write(self, detroit_vault: Path) -> None:
        result = _cli("now", "--vault", str(detroit_vault))
        assert result.returncode == 0, result.stderr
        assert DETROIT_STAMP.match(result.stdout.strip()), result.stdout

    def test_now_without_a_zone_is_utc_z(self, vault: Path) -> None:
        result = _cli("now", "--vault", str(vault))
        assert result.returncode == 0, result.stderr
        assert Z_STAMP.match(result.stdout.strip()), result.stdout

    def test_now_date_and_json(self, detroit_vault: Path) -> None:
        date = _cli("now", "--date", "--vault", str(detroit_vault))
        assert date.returncode == 0 and date.stdout.strip() == clock.today(DETROIT)
        as_json = _cli("now", "--json", "--vault", str(detroit_vault))
        assert as_json.returncode == 0, as_json.stderr
        import json
        payload = json.loads(as_json.stdout)
        assert set(payload) == {"timestamp", "date", "timezone"}
        assert payload["timezone"] == "America/Detroit"
        assert DETROIT_STAMP.match(payload["timestamp"]) and BARE_DATE.match(payload["date"])

    def test_status_names_the_zone(self, detroit_vault: Path, vault: Path) -> None:
        result = _cli("status", "--vault", str(detroit_vault))
        assert result.returncode == 0, result.stderr
        assert "timezone: America/Detroit" in result.stdout

    def test_a_typo_is_an_error_not_a_utc_stamp(self, vault: Path) -> None:
        _index(vault, "timezone: Americas/Detroit")
        result = _cli("now", "--vault", str(vault))
        assert result.returncode == 1
        assert "Americas/Detroit" in result.stderr
        assert result.stdout.strip() == ""

    def test_sync_stamps_the_log_in_the_zone(self, detroit_vault: Path) -> None:
        mem.mark_adopted(detroit_vault)
        result = _cli("sync", "INGEST", "source=x", "--vault", str(detroit_vault))
        assert result.returncode == 0, result.stderr
        log = (detroit_vault / "log.md").read_text(encoding="utf-8")
        assert re.search(r"^- \[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-0[45]:00\] INGEST", log, re.MULTILINE), log


# --------------------------------------------------------------------------
# docs
# --------------------------------------------------------------------------


class TestDocs:
    def test_the_knob_and_the_command_are_documented(self) -> None:
        memory_doc = (ROOT / "docs" / "memory.md").read_text(encoding="utf-8")
        cli_doc = (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
        reference = (ROOT / ".skills" / "llm-wiki" / "references" / "MEMORY.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for text, name in ((memory_doc, "docs/memory.md"), (cli_doc, "docs/cli.md"), (reference, "MEMORY.md")):
            assert "timezone:" in text, f"{name} does not name the timezone key"
            assert "memory now" in text, f"{name} does not name `memory now`"
        assert "memory now" in agents, "AGENTS.md does not tell agents where a stamp comes from"
        assert "memory now" in (ROOT / "docs" / "python-api.md").read_text(encoding="utf-8") or \
            "now()" in (ROOT / "docs" / "python-api.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# setup
# --------------------------------------------------------------------------


class TestSetup:
    def test_set_timezone_inserts_replaces_and_validates(self, vault: Path) -> None:
        assert clock.set_timezone(vault, "America/Detroit") == "America/Detroit"
        text = (vault / "index.md").read_text(encoding="utf-8")
        assert text.startswith("---\ntitle: Wiki Index\ntimezone: America/Detroit\n"), text
        assert "# Wiki Index" in text and text.count("timezone:") == 1
        clock.set_timezone(vault, "Europe/Berlin")
        text = (vault / "index.md").read_text(encoding="utf-8")
        assert text.count("timezone:") == 1 and "timezone: Europe/Berlin" in text
        assert clock.set_timezone(vault, "") == "" and "Europe/Berlin" in (vault / "index.md").read_text()
        with pytest.raises(clock.TimezoneError):
            clock.set_timezone(vault, "America/Detroi")
        assert "Europe/Berlin" in (vault / "index.md").read_text(encoding="utf-8")

    def test_set_timezone_on_an_index_without_frontmatter(self, tmp_path: Path) -> None:
        (tmp_path / "index.md").write_text("# Wiki Index\n\n## Concepts\n", encoding="utf-8")
        clock.set_timezone(tmp_path, "America/Detroit")
        text = (tmp_path / "index.md").read_text(encoding="utf-8")
        assert text.startswith("---\ntitle: Wiki Index\ntimezone: America/Detroit\n---\n\n# Wiki Index\n"), text
        assert clock.wiki_timezone(tmp_path) == DETROIT

    def test_scaffold_writes_the_key_and_stamps_in_the_zone(self, tmp_path: Path) -> None:
        from obsidian_wiki.cli import scaffold_vault

        vault = tmp_path / "brain"
        assert scaffold_vault(vault, timezone_name="America/Detroit") is True
        text = (vault / "index.md").read_text(encoding="utf-8")
        assert "timezone: America/Detroit" in mem.split_frontmatter(text)[0]
        assert re.search(r"Last updated: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}-0[45]:00", text), text
        assert clock.wiki_timezone(vault) == DETROIT
        plain = tmp_path / "plain"
        scaffold_vault(plain)
        plain_text = (plain / "index.md").read_text(encoding="utf-8")
        assert "timezone:" not in plain_text and re.search(r"Last updated: \S+Z\*", plain_text)

    def test_setup_cli_records_the_zone(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT)}
        vault = tmp_path / "brain"
        proc = subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", "setup", "--vault", str(vault),
             "--project-only", "--no-hooks", "--timezone", "America/Detroit"],
            capture_output=True, text=True, env=env, timeout=300,
        )
        assert proc.returncode == 0, proc.stderr
        assert "Timezone: America/Detroit" in proc.stdout
        assert clock.timezone_name(vault) == "America/Detroit"
        again = subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", "setup", "--vault", str(vault), "--project-only", "--no-hooks"],
            capture_output=True, text=True, env=env, timeout=300,
        )
        assert again.returncode == 0, again.stderr
        assert "Timezone: America/Detroit (index.md)" in again.stdout
        assert (vault / "index.md").read_text(encoding="utf-8").count("timezone:") == 1

    def test_setup_cli_refuses_a_bad_zone_before_touching_anything(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT)}
        vault = tmp_path / "brain"
        proc = subprocess.run(
            [sys.executable, "-m", "obsidian_wiki.cli", "setup", "--vault", str(vault),
             "--project-only", "--no-hooks", "--timezone", "Americas/Detroit"],
            capture_output=True, text=True, env=env, timeout=300,
        )
        assert proc.returncode == 1
        assert "Americas/Detroit" in proc.stderr
        assert not vault.exists()
