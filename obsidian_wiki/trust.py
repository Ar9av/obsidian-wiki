"""Manual trust-review ledger for confidence linting.

Confidence depends on semantic judgments that source-string heuristics cannot make:
independent evidence lineages must be collapsed and material claim coverage must be
reviewed.  This module therefore validates an approved review ledger instead of
pretending to recompute confidence from URLs.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
import tempfile
from collections.abc import Collection
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

TRUST_LEDGER_RELATIVE_PATH = Path("_meta/trust-ledger.json")
TRUST_LEDGER_SCHEMA_VERSION = 1
TRUST_REVIEW_METHOD = "manual-lineage-and-claim-coverage-v1"
TRUST_SKIP_DIRS = frozenset(
    "_raw _archived _staging _archives _bootstrap .obsidian .git".split()
)
TRUST_RESERVED_STEMS = frozenset({"index", "log", "hot", "_insights"})
ALLOWED_LIFECYCLES = frozenset({"draft", "reviewed", "verified", "disputed", "archived"})
# Transitions the llm-wiki state machine forbids outright: only ingest sets
# `draft`, so nothing may fall back to it, and `archived` is terminal (a restore
# is a deliberate human delete-and-recreate, not a transition).
#
# Deliberately NOT listed: draft -> verified. Ledger snapshots are sparse, so an
# intermediate `reviewed` may well have happened between two reviews; flagging
# that pair would fire on legitimate history.
ILLEGAL_TRANSITIONS = frozenset(
    {("reviewed", "draft"), ("verified", "draft"), ("disputed", "draft")}
    | {("archived", nxt) for nxt in ALLOWED_LIFECYCLES - {"archived"}}
)
TRUST_REQUIRED_FIELD_ALLOWLIST = frozenset(
    {"base_confidence", "lifecycle", "lifecycle_changed", "updated"}
)
_REQUIRED_TRUST_KEYS = ("base_confidence", "lifecycle", "updated")
_VOLATILE_CONFIDENCE_KEYS = (
    "updated",
    "base_confidence",
    "lifecycle",
    "lifecycle_changed",
    "lifecycle_reason",
    "superseded_by",
)
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---(?:\n|$)", re.DOTALL)
_TOP_LEVEL_FIELD_RE = re.compile(r"^([A-Za-z_][\w-]*):")


def _normalise_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _validate_reviewed_at(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("reviewed_at must be an ISO-8601 timestamp with timezone")
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("reviewed_at must be an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("reviewed_at must be an ISO-8601 timestamp with timezone")
    return candidate


def _validate_updated(value: str) -> str:
    candidate = value.strip()
    try:
        # Page metadata intentionally permits either an ISO date or an ISO date-time.
        datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("updated is not an ISO-8601 date or timestamp") from exc
    return candidate


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON number: {value}")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _frontmatter(text: str) -> str:
    match = _FRONTMATTER_RE.match(_normalise_text(text))
    return match.group(1) if match else ""


def _frontmatter_scalar(raw: str) -> str:
    value = raw.strip().split(" #", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


def _effective_schema(
    *,
    allowed_lifecycles: Collection[str] | None = None,
    required_trust_keys: Collection[str] | None = None,
) -> tuple[frozenset[str], tuple[str, ...]]:
    lifecycles = frozenset(
        ALLOWED_LIFECYCLES if allowed_lifecycles is None else allowed_lifecycles
    )
    required = tuple(required_trust_keys) if required_trust_keys is not None else _REQUIRED_TRUST_KEYS
    unknown = set(required) - TRUST_REQUIRED_FIELD_ALLOWLIST
    if unknown:
        raise ValueError(f"unknown required trust field(s): {', '.join(sorted(unknown))}")
    return lifecycles, required


def _trust_metadata(
    path: Path,
    *,
    allowed_lifecycles: Collection[str] | None = None,
    required_trust_keys: Collection[str] | None = None,
) -> dict[str, Any]:
    """Parse and validate trust-sensitive frontmatter without YAML ambiguity."""
    lifecycles, required = _effective_schema(
        allowed_lifecycles=allowed_lifecycles,
        required_trust_keys=required_trust_keys,
    )
    try:
        text = _normalise_text(path.read_text(encoding="utf-8"))
    except UnicodeError as exc:
        raise ValueError("page is not valid UTF-8") from exc
    frontmatter = _frontmatter(text)
    if not frontmatter:
        raise ValueError("missing frontmatter")

    records: dict[str, list[tuple[str, list[str]]]] = {}
    current: tuple[str, list[str]] | None = None
    for line in frontmatter.splitlines():
        field = _TOP_LEVEL_FIELD_RE.match(line)
        if field:
            key = field.group(1)
            raw = line.split(":", 1)[1].strip()
            children: list[str] = []
            records.setdefault(key, []).append((raw, children))
            current = (key, children)
            continue
        if line.startswith((" ", "\t")) and current is not None:
            current[1].append(line)

    for key in _VOLATILE_CONFIDENCE_KEYS:
        entries = records.get(key, [])
        if len(entries) > 1:
            raise ValueError(f"duplicate top-level field: {key}")
    for key in required:
        if key not in records:
            raise ValueError(f"missing {key}")

    for key in _VOLATILE_CONFIDENCE_KEYS:
        entries = records.get(key, [])
        if not entries:
            continue
        raw, children = entries[0]
        scalar = _frontmatter_scalar(raw)
        if not scalar or scalar in {">", ">-", "|", "|-"} or children:
            raise ValueError(f"{key} must be a scalar")

    if "updated" in records:
        updated = _frontmatter_scalar(records["updated"][0][0])
        _validate_updated(updated)

    confidence: float | None = None
    if "base_confidence" in records:
        confidence_raw = _frontmatter_scalar(records["base_confidence"][0][0])
        try:
            confidence = float(confidence_raw)
        except ValueError as exc:
            raise ValueError("base_confidence is not numeric") from exc
        if not math.isfinite(confidence):
            raise ValueError("base_confidence is not finite")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("base_confidence is outside [0.0, 1.0]")

    lifecycle: str | None = None
    if "lifecycle" in records:
        lifecycle = _frontmatter_scalar(records["lifecycle"][0][0])
        if lifecycle not in lifecycles:
            raise ValueError(f"invalid lifecycle: {lifecycle}")
    return {
        "text": text,
        "frontmatter": frontmatter,
        "confidence": confidence,
        "lifecycle": lifecycle,
        "review_status": "reviewable" if confidence is not None else "not_applicable",
    }


def _strip_volatile_confidence_fields(frontmatter: str) -> str:
    """Remove confidence/lifecycle bookkeeping while retaining material metadata."""
    kept: list[str] = []
    skipping = False
    for line in frontmatter.splitlines():
        field = _TOP_LEVEL_FIELD_RE.match(line)
        if field:
            skipping = field.group(1) in _VOLATILE_CONFIDENCE_KEYS
        if not skipping:
            kept.append(line.rstrip())
    return "\n".join(kept).strip()


def page_fingerprint(
    path: Path,
    *,
    allowed_lifecycles: Collection[str] | None = None,
    required_trust_keys: Collection[str] | None = None,
) -> str:
    """Hash material claims and evidence, excluding validated volatile bookkeeping."""
    metadata = _trust_metadata(
        path,
        allowed_lifecycles=allowed_lifecycles,
        required_trust_keys=required_trust_keys,
    )
    text = metadata["text"]
    match = _FRONTMATTER_RE.match(text)
    assert match is not None
    stable_frontmatter = _strip_volatile_confidence_fields(metadata["frontmatter"])
    body = text[match.end() :].strip()
    material = f"---\n{stable_frontmatter}\n---\n{body}\n"
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def validate_trust_metadata(
    path: Path,
    *,
    allowed_lifecycles: Collection[str] | None = None,
    required_trust_keys: Collection[str] | None = None,
) -> dict[str, Any]:
    """Validate present trust fields even when no review ledger is configured."""
    return _trust_metadata(
        path,
        allowed_lifecycles=allowed_lifecycles,
        required_trust_keys=required_trust_keys,
    )


def _parse_confidence(
    path: Path,
    *,
    allowed_lifecycles: Collection[str] | None = None,
    required_trust_keys: Collection[str] | None = None,
) -> float:
    value = _trust_metadata(
        path,
        allowed_lifecycles=allowed_lifecycles,
        required_trust_keys=required_trust_keys,
    )["confidence"]
    if value is None:
        raise ValueError("missing base_confidence for trust review")
    return float(value)


def iter_trust_pages(vault: Path) -> list[Path]:
    """Return every non-reserved content page that must participate in trust review."""
    pages: list[Path] = []
    for path in vault.rglob("*.md"):
        rel = path.relative_to(vault)
        if any(part in TRUST_SKIP_DIRS for part in rel.parts):
            continue
        if path.stem in TRUST_RESERVED_STEMS:
            continue
        pages.append(path)
    return sorted(pages, key=lambda item: item.relative_to(vault).as_posix())


def build_trust_ledger(
    vault: Path,
    *,
    reviewed_at: str,
    allowed_lifecycles: Collection[str] | None = None,
    required_trust_keys: Collection[str] | None = None,
) -> dict[str, Any]:
    """Capture explicitly approved confidence values and material fingerprints."""
    reviewed_at = _validate_reviewed_at(reviewed_at)
    pages: dict[str, dict[str, Any]] = {}
    not_applicable: list[str] = []
    for path in iter_trust_pages(vault):
        rel = path.relative_to(vault).as_posix()
        metadata = _trust_metadata(
            path,
            allowed_lifecycles=allowed_lifecycles,
            required_trust_keys=required_trust_keys,
        )
        if metadata["review_status"] == "not_applicable":
            not_applicable.append(rel)
            continue
        pages[rel] = _review_entry(
            path,
            reviewed_at,
            allowed_lifecycles=allowed_lifecycles,
            required_trust_keys=required_trust_keys,
        )
    return {
        "schema_version": TRUST_LEDGER_SCHEMA_VERSION,
        "method": TRUST_REVIEW_METHOD,
        "reviewed_at": reviewed_at,
        "pages": pages,
        "not_applicable": not_applicable,
    }


def _review_entry(
    path: Path,
    reviewed_at: str,
    *,
    allowed_lifecycles: Collection[str] | None = None,
    required_trust_keys: Collection[str] | None = None,
) -> dict[str, Any]:
    metadata = _trust_metadata(
        path,
        allowed_lifecycles=allowed_lifecycles,
        required_trust_keys=required_trust_keys,
    )
    if metadata["review_status"] == "not_applicable":
        raise ValueError("trust review is not applicable: base_confidence is absent")
    return {
        "reviewed_confidence": _parse_confidence(
            path,
            allowed_lifecycles=allowed_lifecycles,
            required_trust_keys=required_trust_keys,
        ),
        "material_fingerprint": page_fingerprint(
            path,
            allowed_lifecycles=allowed_lifecycles,
            required_trust_keys=required_trust_keys,
        ),
        "reviewed_at": reviewed_at,
        # Recorded so lint can check the next transition against
        # ILLEGAL_TRANSITIONS. Ledgers written before this field simply skip
        # the check.
        "lifecycle": metadata["lifecycle"],
    }


def _validate_ledger_entry(entry: Any) -> tuple[str, float, str]:
    if not isinstance(entry, dict):
        raise ValueError("invalid_ledger_entry")
    fingerprint = entry.get("material_fingerprint")
    reviewed_confidence = entry.get("reviewed_confidence")
    if (
        not isinstance(fingerprint, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint) is None
    ):
        raise ValueError("invalid_ledger_entry")
    if not isinstance(reviewed_confidence, (int, float)) or isinstance(reviewed_confidence, bool):
        raise ValueError("invalid_ledger_entry")
    reviewed_value = float(reviewed_confidence)
    if not math.isfinite(reviewed_value) or not 0.0 <= reviewed_value <= 1.0:
        raise ValueError("invalid_ledger_entry")
    try:
        reviewed_at = _validate_reviewed_at(entry.get("reviewed_at"))
    except ValueError as exc:
        raise ValueError("invalid_ledger_entry") from exc
    return fingerprint, reviewed_value, reviewed_at


def _validate_ledger_page_path(raw: Any) -> str:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise ValueError("invalid_ledger_page_path")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != raw:
        raise ValueError("invalid_ledger_page_path")
    return raw


def update_trust_ledger(
    vault: Path,
    ledger_path: Path,
    *,
    reviewed_at: str,
    page_paths: list[str],
    allowed_lifecycles: Collection[str] | None = None,
    required_trust_keys: Collection[str] | None = None,
) -> dict[str, Any]:
    """Update reviewed pages and remove entries whose confidence is not applicable."""
    reviewed_at = _validate_reviewed_at(reviewed_at)
    if ledger_path.is_file():
        try:
            ledger = json.loads(
                ledger_path.read_text(encoding="utf-8"),
                parse_constant=_reject_json_constant,
                object_pairs_hook=_reject_duplicate_json_keys,
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise RuntimeError(f"cannot update unreadable trust ledger: {exc}") from exc
        if not isinstance(ledger, dict):
            raise RuntimeError("cannot update trust ledger: top level must be an object")
        if type(ledger.get("schema_version")) is not int or ledger.get("schema_version") != TRUST_LEDGER_SCHEMA_VERSION:
            raise RuntimeError("cannot update unsupported trust ledger schema")
        if ledger.get("method") != TRUST_REVIEW_METHOD or not isinstance(ledger.get("pages"), dict):
            raise RuntimeError("cannot update malformed trust ledger")
        try:
            _validate_reviewed_at(ledger.get("reviewed_at"))
            for rel, entry in ledger["pages"].items():
                _validate_ledger_page_path(rel)
                _validate_ledger_entry(entry)
        except ValueError as exc:
            raise RuntimeError("cannot update malformed trust ledger") from exc
    else:
        ledger = {
            "schema_version": TRUST_LEDGER_SCHEMA_VERSION,
            "method": TRUST_REVIEW_METHOD,
            "reviewed_at": reviewed_at,
            "pages": {},
        }

    current = {path.relative_to(vault).as_posix(): path for path in iter_trust_pages(vault)}
    not_applicable: list[str] = []
    for rel, page in current.items():
        metadata = _trust_metadata(
            page,
            allowed_lifecycles=allowed_lifecycles,
            required_trust_keys=required_trust_keys,
        )
        if metadata["review_status"] == "not_applicable":
            not_applicable.append(rel)
    removed_not_applicable = sorted(set(ledger["pages"]) & set(not_applicable))
    for rel in removed_not_applicable:
        del ledger["pages"][rel]

    selected: list[str] = []
    for raw in page_paths:
        candidate = Path(raw)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise RuntimeError(f"trust page must be a safe vault-relative path: {raw}")
        rel = candidate.as_posix().removeprefix("./")
        page = current.get(rel)
        if page is None:
            raise RuntimeError(f"trust page is missing or lacks the trust schema: {raw}")
        if rel not in selected:
            selected.append(rel)
            if rel in not_applicable:
                continue
            ledger["pages"][rel] = _review_entry(
                page,
                reviewed_at,
                allowed_lifecycles=allowed_lifecycles,
                required_trust_keys=required_trust_keys,
            )
    ledger["reviewed_at"] = reviewed_at
    ledger["not_applicable"] = sorted(not_applicable)
    ledger["removed_not_applicable"] = removed_not_applicable
    return ledger


def write_trust_ledger(
    path: Path,
    ledger: dict[str, Any],
    *,
    vault: Path | None = None,
) -> None:
    """Write a ledger atomically without following vault-internal symlinks."""
    vault_root = (vault or path.parent.parent).expanduser().resolve(strict=True)
    expected = vault_root / TRUST_LEDGER_RELATIVE_PATH
    requested = path.expanduser().absolute()
    if requested.resolve(strict=False) != expected:
        raise RuntimeError("trust ledger destination resolves outside the resolved vault")

    parent = expected.parent
    if parent.exists() and parent.is_symlink():
        raise RuntimeError("trust ledger parent must not be a symlink")
    parent.mkdir(parents=True, exist_ok=True)
    if parent.resolve(strict=True) != vault_root / TRUST_LEDGER_RELATIVE_PATH.parent:
        raise RuntimeError("trust ledger parent resolves outside the resolved vault")
    if expected.is_symlink():
        raise RuntimeError("trust ledger destination must not be a symlink")

    try:
        payload = json.dumps(ledger, indent=2, sort_keys=True, allow_nan=False) + "\n"
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"trust ledger is not valid JSON data: {exc}") from exc

    if os.name == "posix":
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            directory_fd = os.open(parent, directory_flags)
        except OSError as exc:
            raise RuntimeError(f"cannot securely open trust ledger directory: {exc}") from exc
        temporary_name = f".trust-ledger-{secrets.token_hex(16)}.tmp"
        temporary_created = False
        try:
            try:
                destination_stat = os.stat(
                    expected.name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                destination_stat = None
            if destination_stat is not None and stat.S_ISLNK(destination_stat.st_mode):
                raise RuntimeError("trust ledger destination must not be a symlink")

            descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_fd,
            )
            temporary_created = True
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(
                temporary_name,
                expected.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            temporary_created = False
            os.fsync(directory_fd)
        except OSError as exc:
            raise RuntimeError(f"cannot securely write trust ledger: {exc}") from exc
        finally:
            if temporary_created:
                try:
                    os.unlink(temporary_name, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
            os.close(directory_fd)
        return

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=".trust-ledger-",
            suffix=".tmp",
            text=True,
        )
    except OSError as exc:
        raise RuntimeError(f"cannot create trust ledger temporary file: {exc}") from exc
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(expected)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"cannot write trust ledger: {exc}") from exc


def _empty_report(
    ledger_path: Path,
    *,
    allowed_lifecycles: Collection[str],
    required_trust_keys: Collection[str],
    schema_source: str,
) -> dict[str, Any]:
    return {
        "status": "pass",
        "ledger_path": str(ledger_path),
        "schema": {
            "source": schema_source,
            "allowed_lifecycles": sorted(allowed_lifecycles),
            "required_trust_fields": list(required_trust_keys),
        },
        "reviewed": [],
        "not_applicable": [],
        "stale": [],
        "unreviewed": [],
        "score_mismatches": [],
        "missing_pages": [],
        "errors": [],
        "counts": {},
    }


def check_trust_ledger(
    vault: Path,
    ledger_path: Path | None = None,
    *,
    allowed_lifecycles: Collection[str] | None = None,
    required_trust_keys: Collection[str] | None = None,
    schema_source: str = "framework-defaults",
) -> dict[str, Any]:
    """Validate current pages against an approved manual review ledger."""
    lifecycles, required = _effective_schema(
        allowed_lifecycles=allowed_lifecycles,
        required_trust_keys=required_trust_keys,
    )
    path = ledger_path or vault / TRUST_LEDGER_RELATIVE_PATH
    report = _empty_report(
        path,
        allowed_lifecycles=lifecycles,
        required_trust_keys=required,
        schema_source=schema_source,
    )
    try:
        ledger = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except FileNotFoundError:
        report["errors"].append({"issue": "ledger_missing", "path": str(path)})
        return _finalise_report(report)
    except (OSError, UnicodeError, ValueError) as exc:
        report["errors"].append({"issue": "ledger_unreadable", "detail": str(exc)})
        return _finalise_report(report)

    if not isinstance(ledger, dict):
        report["errors"].append({"issue": "ledger_must_be_an_object"})
        return _finalise_report(report)
    if type(ledger.get("schema_version")) is not int or ledger.get("schema_version") != TRUST_LEDGER_SCHEMA_VERSION:
        report["errors"].append(
            {
                "issue": "unsupported_schema_version",
                "found": ledger.get("schema_version"),
                "expected": TRUST_LEDGER_SCHEMA_VERSION,
            }
        )
        return _finalise_report(report)
    if ledger.get("method") != TRUST_REVIEW_METHOD:
        report["errors"].append(
            {"issue": "unsupported_review_method", "found": ledger.get("method")}
        )
        return _finalise_report(report)
    try:
        _validate_reviewed_at(ledger.get("reviewed_at"))
    except ValueError:
        report["errors"].append({"issue": "invalid_reviewed_at"})
        return _finalise_report(report)
    entries = ledger.get("pages")
    if not isinstance(entries, dict):
        report["errors"].append({"issue": "pages_must_be_an_object"})
        return _finalise_report(report)

    validated_entries: dict[str, tuple[str, float, str]] = {}
    for raw_rel, entry in entries.items():
        try:
            rel = _validate_ledger_page_path(raw_rel)
            validated_entries[rel] = _validate_ledger_entry(entry)
        except ValueError as exc:
            report["errors"].append(
                {"page": raw_rel, "issue": str(exc)}
            )
    if report["errors"]:
        return _finalise_report(report)

    current: dict[str, Path] = {
        page.relative_to(vault).as_posix(): page for page in iter_trust_pages(vault)
    }
    for rel, page in current.items():
        try:
            page_metadata = _trust_metadata(
                page,
                allowed_lifecycles=lifecycles,
                required_trust_keys=required,
            )
        except ValueError as exc:
            report["errors"].append({"page": rel, "issue": str(exc)})
            continue
        if page_metadata["review_status"] == "not_applicable":
            report["not_applicable"].append(
                {"page": rel, "reason": "base_confidence_absent_by_owner_schema"}
            )
            if rel in validated_entries:
                report["stale"].append(
                    {
                        "page": rel,
                        "reason": "confidence_not_applicable_but_ledger_entry_exists",
                    }
                )
            continue
        stored_confidence = float(page_metadata["confidence"])
        if rel not in validated_entries:
            report["unreviewed"].append({"page": rel, "reason": "not_in_manual_ledger"})
            continue
        fingerprint, reviewed_value, reviewed_at = validated_entries[rel]
        if page_fingerprint(
            page,
            allowed_lifecycles=lifecycles,
            required_trust_keys=required,
        ) != fingerprint:
            report["stale"].append({"page": rel, "reason": "material_fingerprint_changed"})
            continue
        if abs(stored_confidence - reviewed_value) > 1e-9:
            report["score_mismatches"].append(
                {
                    "page": rel,
                    "stored": stored_confidence,
                    "reviewed": reviewed_value,
                }
            )
            continue
        report["reviewed"].append(
            {
                "page": rel,
                "reviewed_confidence": stored_confidence,
                "reviewed_at": reviewed_at,
            }
        )

    for rel in sorted(set(entries) - set(current)):
        report["missing_pages"].append({"page": rel, "reason": "reviewed_page_missing"})
    return _finalise_report(report)


def _finalise_report(report: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "reviewed",
        "not_applicable",
        "stale",
        "unreviewed",
        "score_mismatches",
        "missing_pages",
        "errors",
    )
    report["counts"] = {key: len(report[key]) for key in keys}
    if report["errors"] or report["score_mismatches"]:
        report["status"] = "fail"
    elif report["stale"] or report["unreviewed"] or report["missing_pages"]:
        report["status"] = "warn"
    else:
        report["status"] = "pass"
    return report


def check_lifecycle_transitions(
    vault: Path,
    ledger_path: Path | None = None,
    *,
    allowed_lifecycles: Collection[str] | None = None,
    required_trust_keys: Collection[str] | None = None,
) -> list[dict[str, str]]:
    """Report pages whose lifecycle moved along a forbidden edge.

    Compares each page's current ``lifecycle`` against the value recorded in the
    approved ledger at its last review. Ledgers written before the ``lifecycle``
    field existed carry no baseline, so those pages are skipped — the check is
    additive and silent on legacy vaults.
    """
    lifecycles, required = _effective_schema(
        allowed_lifecycles=allowed_lifecycles,
        required_trust_keys=required_trust_keys,
    )
    path = ledger_path or vault / TRUST_LEDGER_RELATIVE_PATH
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return []  # check_trust_ledger already reports unreadable ledgers
    entries = ledger.get("pages") if isinstance(ledger, dict) else None
    if not isinstance(entries, dict):
        return []

    findings: list[dict[str, str]] = []
    for page in iter_trust_pages(vault):
        rel = page.relative_to(vault).as_posix()
        entry = entries.get(rel)
        if not isinstance(entry, dict):
            continue
        previous = entry.get("lifecycle")
        if not isinstance(previous, str):
            continue  # pre-lifecycle ledger entry: no baseline to compare
        try:
            metadata = _trust_metadata(
                page,
                allowed_lifecycles=lifecycles,
                required_trust_keys=required,
            )
        except ValueError:
            continue  # malformed frontmatter is another check's finding
        current = metadata["lifecycle"]
        if not isinstance(current, str):
            continue
        if (previous, current) in ILLEGAL_TRANSITIONS:
            findings.append({"page": rel, "from": previous, "to": current})
    return sorted(findings, key=lambda f: f["page"])
