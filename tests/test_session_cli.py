"""Tests for the session-brain CLI surface.

Every run gets a synthetic HOME and an explicit --claude-dir, so no test can
touch the developer's real session cache.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

TELEMETRY = [
    "add telemetry batching to the warden runtime with a redacted sink",
    "the telemetry sink drops spans under load, add warden batching retries",
    "warden telemetry chain signing broke, redacted spans never reach the sink",
]
SPRITES = [
    "slice the generated sprite sheet into aligned animation frames",
    "the sprite sheet flood fill leaves halos around each animation frame",
    "generate a sprite sheet and slice it into frames for the walk animation",
]


def _run(home: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("WIKI_SESSION_BRAIN_DIR", None)
    env.pop("WIKI_SKIP_PROJECTS", None)
    return subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", *args],
        capture_output=True, text=True, env=env, input=stdin,
    )


def _cache(tmp_path: Path) -> Path:
    claude = tmp_path / "cache"
    for topic, texts, cwd in (("tel", TELEMETRY, "/w/warden"), ("spr", SPRITES, "/w/game")):
        project = claude / "projects" / cwd.replace("/", "-")
        project.mkdir(parents=True, exist_ok=True)
        for i, text in enumerate(texts):
            sid = f"{topic}{i}"
            lines = [
                json.dumps({"type": "user", "message": {"role": "user", "content": text},
                            "timestamp": f"2026-07-{10 + i:02d}T10:00:00.000Z",
                            "cwd": cwd, "gitBranch": "main", "sessionId": sid}),
                json.dumps({"type": "ai-title", "aiTitle": text[:40], "sessionId": sid}),
            ]
            (project / f"{sid}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return claude


def _build(tmp_path: Path) -> tuple[Path, Path]:
    home, claude, out = tmp_path / "home", _cache(tmp_path), tmp_path / "brain"
    home.mkdir(exist_ok=True)
    proc = _run(home, "sessions-build", "--claude-dir", str(claude), "--out", str(out),
                "--k", "3", "--min-sim", "0.05", "--json")
    assert proc.returncode == 0, proc.stderr
    return home, out


def test_build_emits_json_and_artifacts(tmp_path: Path) -> None:
    home, claude, out = tmp_path / "home", _cache(tmp_path), tmp_path / "brain"
    home.mkdir()
    proc = _run(home, "sessions-build", "--claude-dir", str(claude), "--out", str(out),
                "--k", "3", "--min-sim", "0.05", "--json")

    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["stats"]["sessions"] == 6
    assert data["stats"]["clusters"] >= 2
    for name in ("graph.json", "clusters.json", "graph.html", "docs.jsonl", "state.json"):
        assert (out / name).is_file(), f"missing {name}"


def test_build_human_output_is_readable(tmp_path: Path) -> None:
    home, claude, out = tmp_path / "home", _cache(tmp_path), tmp_path / "brain"
    home.mkdir()
    proc = _run(home, "sessions-build", "--claude-dir", str(claude), "--out", str(out),
                "--k", "3", "--min-sim", "0.05")
    assert proc.returncode == 0, proc.stderr
    assert "sessions" in proc.stdout
    assert str(out) in proc.stdout


def test_build_on_an_empty_cache_succeeds(tmp_path: Path) -> None:
    """A machine with no session history is not an error condition."""
    home = tmp_path / "home"
    home.mkdir()
    proc = _run(home, "sessions-build", "--claude-dir", str(tmp_path / "nothing"),
                "--out", str(tmp_path / "brain"), "--json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["stats"]["sessions"] == 0
    assert "Traceback" not in proc.stderr


def test_build_respects_skip(tmp_path: Path) -> None:
    """Skip matches on substrings, so a project can be named without the leading
    dash that Claude's cwd encoding puts on every cache directory (and that
    argparse would otherwise parse as a flag)."""
    home, claude, out = tmp_path / "home", _cache(tmp_path), tmp_path / "brain"
    home.mkdir()
    proc = _run(home, "sessions-build", "--claude-dir", str(claude), "--out", str(out),
                "--skip", "game", "--json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["stats"]["sessions"] == 3

    explicit = _run(home, "sessions-build", "--claude-dir", str(claude),
                    "--out", str(tmp_path / "b2"), "--skip=-w-game", "--json")
    assert explicit.returncode == 0, explicit.stderr
    assert json.loads(explicit.stdout)["stats"]["sessions"] == 3


def test_query_returns_ranked_json(tmp_path: Path) -> None:
    home, out = _build(tmp_path)
    proc = _run(home, "sessions-query", "warden telemetry sink", "--out", str(out), "--json")

    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["candidates"]
    assert not data["candidates"][0]["session_id"].startswith("spr")
    assert data["should_load"]


def test_query_before_build_fails_with_guidance(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    proc = _run(home, "sessions-query", "anything", "--out", str(tmp_path / "nope"), "--json")
    assert proc.returncode == 1
    assert "sessions-build" in proc.stderr


def test_show_reports_neighbours(tmp_path: Path) -> None:
    home, out = _build(tmp_path)
    proc = _run(home, "sessions-show", "tel0", "--out", str(out))
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["session"]["id"] == "tel0"
    assert data["neighbors"]


def test_show_unknown_session_fails_cleanly(tmp_path: Path) -> None:
    home, out = _build(tmp_path)
    proc = _run(home, "sessions-show", "does-not-exist", "--out", str(out))
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr


def test_clusters_lists_and_filters_unnamed(tmp_path: Path) -> None:
    home, out = _build(tmp_path)
    proc = _run(home, "sessions-clusters", "--out", str(out), "--json")
    assert proc.returncode == 0, proc.stderr
    clusters = json.loads(proc.stdout)["clusters"]
    assert clusters
    assert all(c["name"] is None for c in clusters)

    unnamed = json.loads(
        _run(home, "sessions-clusters", "--out", str(out), "--unnamed", "--json").stdout)
    assert len(unnamed["clusters"]) == len(clusters)


def test_name_round_trips_through_stdin(tmp_path: Path) -> None:
    home, out = _build(tmp_path)
    clusters = json.loads(
        _run(home, "sessions-clusters", "--out", str(out), "--json").stdout)["clusters"]
    target = clusters[0]["id"]

    proc = _run(home, "sessions-name", "--out", str(out), "--from", "-",
                stdin=json.dumps([{"id": target, "name": "warden telemetry",
                                   "summary": "the telemetry pipeline work"}]))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["named"] == 1

    after = json.loads(
        _run(home, "sessions-clusters", "--out", str(out), "--json").stdout)["clusters"]
    assert any(c["name"] == "warden telemetry" for c in after)

    still_unnamed = json.loads(
        _run(home, "sessions-clusters", "--out", str(out), "--unnamed", "--json").stdout)["clusters"]
    assert all(c["name"] is None for c in still_unnamed)


def test_name_rejects_malformed_input(tmp_path: Path) -> None:
    home, out = _build(tmp_path)
    proc = _run(home, "sessions-name", "--out", str(out), "--from", "-", stdin="not json")
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr


def test_brain_dir_env_var_is_honoured(tmp_path: Path) -> None:
    home, claude, out = tmp_path / "home", _cache(tmp_path), tmp_path / "envbrain"
    home.mkdir()
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["WIKI_SESSION_BRAIN_DIR"] = str(out)
    proc = subprocess.run(
        [sys.executable, "-m", "obsidian_wiki.cli", "sessions-build",
         "--claude-dir", str(claude), "--json"],
        capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    assert (out / "graph.json").is_file()
