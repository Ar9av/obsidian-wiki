"""Recoverable commits for the official memory writer, under its existing lock.

Prepared transactions roll back; committed transactions finish cleanup. This is
not snapshot isolation for readers that ignore the lock. Unknown external edits
block recovery without overwriting them.
"""
import base64
import json
import os
import tempfile
from pathlib import Path

JOURNAL = ".memory-transaction.json"
TARGETS = ("log.md", "index.md", "hot.md")


def fsync_directory(path):
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        if path.exists() and path.name != JOURNAL:
            os.chmod(tmp, path.stat().st_mode & 0o777)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        fsync_directory(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def _read(path):
    from .memory import MemoryError_
    if path.is_symlink():
        raise MemoryError_("memory_symlink", f"refusing memory symlink: {path}")
    return path.read_bytes() if path.exists() else None


def _encode(data):
    return base64.b64encode(data).decode("ascii") if data is not None else None


def _decode(data):
    return base64.b64decode(data, validate=True) if data is not None else None


def _save(vault, transaction):
    atomic_bytes(vault / JOURNAL, json.dumps(transaction).encode("utf-8"))


def recover(vault):
    from .memory import MemoryError_
    journal = vault / JOURNAL
    if not journal.exists():
        return
    try:
        t = json.loads(_read(journal))
        if (t["version"] != 1 or t["state"] not in ("prepared", "committed")
                or set(t["before"]) != set(TARGETS) or set(t["after"]) != set(TARGETS)):
            raise ValueError("invalid transaction shape")
        before = {name: _decode(t["before"][name]) for name in TARGETS}
        after = {name: _decode(t["after"][name]) for name in TARGETS}
        # Validate every target before modifying any of them.
        for name in TARGETS:
            if _read(vault / name) not in (before[name], after[name]):
                raise MemoryError_("memory_recovery_conflict",
                                   f"{name} changed outside interrupted sync; retain journal and reconcile")
    except (ValueError, KeyError, TypeError) as exc:
        raise MemoryError_("memory_recovery_invalid", f"invalid memory journal: {exc}") from exc
    desired = before if t["state"] == "prepared" else after
    for name in TARGETS:
        path = vault / name
        if _read(path) == desired[name]:
            continue
        if desired[name] is None:
            path.unlink(missing_ok=True)
            fsync_directory(vault)
        else:
            atomic_bytes(path, desired[name])
    journal.unlink()
    fsync_directory(vault)


def commit(vault, texts):
    """Caller holds memory_lock and has finished all validation and rendering."""
    before = {name: _read(vault / name) for name in TARGETS}
    after = {name: texts[name].encode("utf-8") if texts[name] is not None else None for name in TARGETS}
    if before == after:
        return
    t = {"version": 1, "state": "prepared",
         "before": {k: _encode(v) for k, v in before.items()},
         "after": {k: _encode(v) for k, v in after.items()}}
    try:
        _save(vault, t)
        for name in TARGETS:
            if before[name] != after[name]:
                if after[name] is None:
                    (vault / name).unlink(missing_ok=True)
                    fsync_directory(vault)
                else:
                    atomic_bytes(vault / name, after[name])
        t["state"] = "committed"
        _save(vault, t)
    except BaseException:
        # Durable intent remains if recovery itself is interrupted or conflicts.
        recover(vault)
        raise
    (vault / JOURNAL).unlink()
    fsync_directory(vault)
