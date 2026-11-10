"""Durable memory regressions, including the two audit-pipeline reproductions."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from obsidian_wiki import memory as mem
from obsidian_wiki import memory_transaction as tx


@pytest.fixture
def vault(tmp_path):
    mem.sync_memory(tmp_path, "INIT")
    mem.rebuild_hot(tmp_path, takeaways="Owner revision B")
    return tmp_path


def snapshot(vault):
    return {name: (vault / name).read_bytes() if (vault / name).exists() else None for name in tx.TARGETS}


def test_v31_overflow_reproduction_is_rejected_without_any_memory_write(vault):
    # Existing oversized prose can predate the current limit. Never truncate it.
    h = (vault / "hot.md").read_text()
    a = h.index("\n## Key Takeaways\n") + 1
    b = h.index("\n## Flagged Contradictions\n") + 1
    long = " ".join("durableword" + str(i) for i in range(1000))
    (vault / "hot.md").write_text(h[:a] + "## Key Takeaways\n\n" + long + "\n\n" + h[b:])
    before = snapshot(vault)
    with pytest.raises(mem.MemoryError_) as exc:
        mem.sync_memory(vault, "INGEST", {"source": "new"})
    assert exc.value.code == "takeaways_overflow"
    assert snapshot(vault) == before
    assert not (vault / tx.JOURNAL).exists()


def test_v31_stale_replacement_and_legacy_caller_fail_closed(vault):
    before = snapshot(vault)
    with pytest.raises(mem.MemoryError_) as exc:
        mem.rebuild_hot(vault, takeaways="Stale revision A")
    assert exc.value.code == "takeaways_revision_required"
    revision = mem.takeaways_revision(vault)
    mem.sync_memory(vault, "INGEST", takeaways="Revision C", expected_takeaways_sha256=revision)
    after = snapshot(vault)
    with pytest.raises(mem.MemoryError_) as exc:
        mem.sync_memory(vault, "INGEST", takeaways="Stale revision A", expected_takeaways_sha256=revision)
    assert exc.value.code == "takeaways_conflict"
    assert snapshot(vault) == after and after != before


def test_proposed_overflow_with_current_revision_is_non_destructive(vault):
    before = snapshot(vault)
    with pytest.raises(mem.MemoryError_) as exc:
        mem.sync_memory(vault, "INGEST", takeaways="word " * 1000,
                        expected_takeaways_sha256=mem.takeaways_revision(vault))
    assert exc.value.code == "takeaways_overflow"
    assert snapshot(vault) == before


def test_carry_forward_has_no_revision_requirement(vault):
    revision = mem.takeaways_revision(vault)
    mem.sync_memory(vault, "INGEST", {"source": "new"})
    assert mem.takeaways_revision(vault) == revision
    assert "source=new" in (vault / "hot.md").read_text()


def test_two_revision_writers_have_one_winner(vault):
    revision = mem.takeaways_revision(vault)
    def write(i):
        try:
            mem.sync_memory(vault, "INGEST", {"writer": i}, takeaways="Writer " + str(i),
                            expected_takeaways_sha256=revision)
            return "ok"
        except mem.MemoryError_ as exc:
            return exc.code
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, [1, 2])) == ["ok", "takeaways_conflict"]
    assert len(mem.read_log(vault, verbs=["INGEST"])) == 1


def test_parallel_carry_forward_retains_all_updates(vault):
    revision = mem.takeaways_revision(vault)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: mem.sync_memory(vault, "INGEST", {"n": i}), range(12)))
    assert mem.takeaways_revision(vault) == revision
    assert len(mem.read_log(vault, verbs=["INGEST"])) == 12


def test_operation_id_retry_is_a_byte_identical_noop(vault):
    revision = mem.takeaways_revision(vault)
    args = dict(takeaways="Revision C", expected_takeaways_sha256=revision, operation_id="same-operation")
    mem.sync_memory(vault, "INGEST", {"source": "new"}, **args)
    before = snapshot(vault)
    assert mem.sync_memory(vault, "INGEST", {"source": "new"}, **args)["already_applied"]
    assert snapshot(vault) == before
    with pytest.raises(mem.MemoryError_) as exc:
        mem.sync_memory(vault, "INGEST", {"source": "other"}, **args)
    assert exc.value.code == "memory_operation_conflict"
    assert snapshot(vault) == before


@pytest.mark.parametrize("target", ["log.md", "index.md", "hot.md"])
def test_interruption_rolls_back_all_targets(vault, monkeypatch, target):
    (vault / "concepts").mkdir(exist_ok=True)
    (vault / "concepts/new.md").write_text(chr(10).join(["---", "title: New page", "category: concepts", "---"]))
    before = snapshot(vault)
    original = tx.atomic_bytes
    armed = True
    def interrupted(path, data):
        nonlocal armed
        original(path, data)
        if Path(path).name == target and armed:
            armed = False
            raise KeyboardInterrupt("after atomic replace")
    monkeypatch.setattr(tx, "atomic_bytes", interrupted)
    with pytest.raises(KeyboardInterrupt):
        mem.sync_memory(vault, "INGEST", {"source": "new"}, takeaways="New revision",
                        expected_takeaways_sha256=mem.takeaways_revision(vault))
    assert snapshot(vault) == before
    assert not (vault / tx.JOURNAL).exists()


def test_hard_exit_is_recovered_before_next_writer(vault):
    before = snapshot(vault)
    script = '''
import os,sys
from pathlib import Path
from obsidian_wiki import memory as m, memory_transaction as t
v=Path(sys.argv[1]);original=t.atomic_bytes
def crash(p,b):
 original(p,b)
 if p.name=='log.md':os._exit(42)
t.atomic_bytes=crash
m.sync_memory(v,'INGEST',{'source':'crash'},operation_id='crash')
'''
    r = subprocess.run([sys.executable, "-c", script, str(vault)])
    assert r.returncode == 42 and (vault / tx.JOURNAL).exists()
    # Simulate expiration of the existing official advisory lock after process death.
    os.utime(vault / mem.MEMORY_LOCK_NAME, (0, 0))
    with mem.memory_lock(vault):
        pass
    assert snapshot(vault) == before
    mem.sync_memory(vault, "INGEST", {"source": "crash"}, operation_id="crash")
    before = snapshot(vault)
    assert mem.sync_memory(vault, "INGEST", {"source": "crash"}, operation_id="crash")["already_applied"]
    assert snapshot(vault) == before


def test_recovery_preserves_unknown_external_edit(vault):
    before = {k: tx._encode(v) for k, v in snapshot(vault).items()}
    tx._save(vault, {"version": 1, "state": "prepared", "before": before, "after": before})
    (vault / "hot.md").write_text("External owner edit")
    changed = snapshot(vault)
    with pytest.raises(mem.MemoryError_) as exc:
        with mem.memory_lock(vault):
            pass
    assert exc.value.code == "memory_recovery_conflict"
    assert snapshot(vault) == changed and (vault / tx.JOURNAL).exists()


def test_cli_revision_json_and_actionable_legacy_error(vault):
    def cli(*args):
        return subprocess.run([sys.executable, "-m", "obsidian_wiki.cli", "memory", *args,
                               "--vault", str(vault)], capture_output=True, text=True)
    status = json.loads(cli("status", "--json").stdout)
    bad = cli("sync", "INGEST", "--takeaways", "New revision")
    assert bad.returncode == 1 and "--expect-takeaways-sha256" in bad.stderr
    good = cli("sync", "INGEST", "--takeaways", "New revision",
               "--expect-takeaways-sha256", status["hot"]["takeaways_sha256"], "--operation-id", "cli-retry")
    assert good.returncode == 0, good.stderr
    before = snapshot(vault)
    good = cli("sync", "INGEST", "--takeaways", "New revision",
               "--expect-takeaways-sha256", status["hot"]["takeaways_sha256"], "--operation-id", "cli-retry")
    assert good.returncode == 0 and snapshot(vault) == before


def test_sync_check_has_no_memory_writes(vault):
    before = snapshot(vault)
    mem.sync_memory(vault, "INGEST", {"source": "preview"}, check=True)
    assert snapshot(vault) == before


@pytest.mark.parametrize("state", ["prepared", "committed"])
def test_crash_after_journal_state_has_deterministic_recovery(vault, state):
    before = snapshot(vault)
    script = '''
import os,sys
from pathlib import Path
from obsidian_wiki import memory as m, memory_transaction as t
v=Path(sys.argv[1]);original=t._save
state=sys.argv[2]
def crash(v,record):
 original(v,record)
 if record['state']==state:os._exit(43)
t._save=crash
m.sync_memory(v,'INGEST',{'source':'state-crash'},operation_id='state-crash')
'''
    r = subprocess.run([sys.executable, "-c", script, str(vault), state])
    assert r.returncode == 43
    os.utime(vault / mem.MEMORY_LOCK_NAME, (0, 0))
    with mem.memory_lock(vault):
        pass
    if state == "prepared":
        assert snapshot(vault) == before
    else:
        assert len(mem.read_log(vault, verbs=["INGEST"])) == 1
        current = snapshot(vault)
        assert mem.sync_memory(vault, "INGEST", {"source": "state-crash"}, operation_id="state-crash")["already_applied"]
        assert snapshot(vault) == current


def test_invalid_journal_blocks_all_recovery_writes(vault):
    (vault / tx.JOURNAL).write_text('{"version": 1}')
    before = snapshot(vault)
    with pytest.raises(mem.MemoryError_) as exc:
        with mem.memory_lock(vault):
            pass
    assert exc.value.code == "memory_recovery_invalid"
    assert snapshot(vault) == before


def test_hot_preview_does_not_recover_pending_transaction(vault):
    before = {k: tx._encode(v) for k, v in snapshot(vault).items()}
    tx._save(vault, {"version": 1, "state": "prepared", "before": before, "after": before})
    unchanged = snapshot(vault)
    with pytest.raises(mem.MemoryError_) as exc:
        mem.rebuild_hot(vault, write=False)
    assert exc.value.code == "memory_recovery_required"
    assert snapshot(vault) == unchanged and (vault / tx.JOURNAL).exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits")
def test_memory_commit_preserves_existing_output_permissions(vault):
    for name in tx.TARGETS:
        (vault / name).chmod(0o640)
    mem.sync_memory(vault, "INGEST", {"source": "mode"})
    assert all((vault / name).stat().st_mode & 0o777 == 0o640 for name in tx.TARGETS)


def test_empty_revision_means_none_so_skill_examples_work_on_a_fresh_vault(tmp_path):
    # Skills pass --expect-takeaways-sha256 "$TAKEAWAYS_REVISION"; unset must seed, not error.
    mem.sync_memory(tmp_path, "INIT")
    mem.sync_memory(tmp_path, "CAPTURE", takeaways="first", expected_takeaways_sha256="")
    assert "first" in (tmp_path / "hot.md").read_text()
    with pytest.raises(mem.MemoryError_) as exc:
        mem.sync_memory(tmp_path, "CAPTURE", takeaways="second", expected_takeaways_sha256="")
    assert exc.value.code == "takeaways_revision_required"
