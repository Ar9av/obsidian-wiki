"""Gated native Hermes verification for isolated profile delivery.

This module is intentionally conservative:
- it never touches a live profile;
- it requires explicit disposable homes;
- it can run a fixture-only integration path with mocked transport;
- it reports inventories instead of claiming success from exit code alone.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, asdict
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import argparse
import socket
import threading
import hashlib
import json
import os
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class NativeRun:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


def _require_explicit_scratch() -> Path:
    scratch = Path(os.environ.get("TMPDIR") or os.environ.get("TEMP") or os.environ.get("TMP") or "").expanduser()
    if not scratch.is_absolute() or not scratch.is_dir():
        raise ValueError("TMPDIR/TEMP/TMP must point to an existing scratch directory")
    return scratch.resolve()


def build_native_env(home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    scratch = _require_explicit_scratch()
    env = {
        "HERMES_HOME": str(home.resolve()),
        "HERMES_PROFILE": "",
        "HOME": str(scratch),
        "USERPROFILE": str(scratch),
        "XDG_CONFIG_HOME": str(scratch / "xdg-config"),
        "TMPDIR": str(scratch),
        "TEMP": str(scratch),
        "TMP": str(scratch),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": os.environ.get("PATH", ""),
    }
    if extra:
        raise ValueError('Environment overrides are not allowed for native verification')
    env.update({k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT') if k in os.environ})
    env.update(HERMES_ALLOW_PRIVATE_URLS='false',
               APPDATA=str(home / 'user' / 'roaming'), LOCALAPPDATA=str(home / 'user' / 'local'),
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    return env


def native_home(root: Path) -> Path:
    root = Path(root)
    if not root.is_absolute():
        raise ValueError("native profile root must be absolute")
    if root.name.startswith("native-profile-"):
        return root
    return root / f"native-profile-{os.getpid()}"


def artifact_inventory(root: Path) -> dict[str, dict[str, str | int]]:
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"missing directory: {root}")
    inventory: dict[str, dict[str, str | int]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlinks are not allowed in native inventories: {path}")
        if path.is_file():
            data = path.read_bytes()
            inventory[path.relative_to(root).as_posix()] = {
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    return inventory


def compare_inventories(expected: Path, candidate: Path) -> dict[str, object]:
    left = artifact_inventory(expected)
    right = artifact_inventory(candidate)
    missing = sorted(left.keys() - right.keys())
    extra = sorted(right.keys() - left.keys())
    changed = sorted(name for name in left.keys() & right.keys() if left[name] != right[name])
    return {
        "equal": not (missing or extra or changed),
        "missing": missing,
        "extra": extra,
        "changed": changed,
        "expected": left,
        "candidate": right,
    }


def run_native(command: list[str], *, env: dict[str, str], cwd: Path | None = None, timeout=90) -> NativeRun:
    if not env.get('HERMES_HOME') or env.get('HERMES_PROFILE') != '':
        raise ValueError('Exact disposable HERMES_HOME required')
    proc = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding='utf-8', errors='replace', timeout=timeout, stdin=subprocess.DEVNULL,
        cwd=str(cwd) if cwd else None,
        env=env,
        shell=False,
        check=False,
    )
    return NativeRun(command=command, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def print_runtime_command(*, hermes: Path, env: dict[str, str]) -> list[str]:
    if not hermes.is_absolute() or not hermes.is_file():
        raise ValueError('Explicit existing absolute Hermes executable required')
    result = run_native([str(hermes), '--print-runtime-command'], env=env)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout or 'failed to print runtime command')
    command = json.loads(result.stdout)
    if not isinstance(command, list) or not all(isinstance(p, str) for p in command):
        raise ValueError('Invalid runtime command')
    return command


def prepare_disposable_home(root: Path) -> Path:
    if not root.is_absolute() or not root.name.startswith('native-profile-'):
        raise ValueError('New explicit absolute native-profile-* home required')
    if root.exists() or any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (root, *root.parents)):
        raise ValueError('Existing or redirected profile refused')
    root.mkdir(parents=True, exist_ok=False)
    (root / 'skills').mkdir()
    (root / 'user').mkdir()
    for name in ('roaming', 'local', 'config'):
        (root / 'user' / name).mkdir()
    (root / '.no-bundled-skills').write_text('', encoding='utf-8')
    return root


@contextmanager
def loopback_server(candidate):
    artifact_inventory(candidate)  # refuse redirected files before serving
    handler = partial(SimpleHTTPRequestHandler, directory=str(candidate))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        with socket.socket() as probe:
            probe.settimeout(1)
            if thread.is_alive() or probe.connect_ex(server.server_address) == 0:
                raise RuntimeError('Owned loopback server did not shut down')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Real local HTTP native candidate probe; no network-policy bypass.')
    for name in ('candidate', 'hermes', 'home', 'scratch', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--bootstrap-reviewed', action='store_true',
                        help='Operator reviewed/approved launcher dependency preparation for this exact disposable home')
    args = parser.parse_args(argv)
    if args.output.exists() or not args.scratch.is_absolute() or not args.scratch.is_dir():
        parser.error('New evidence output and existing absolute scratch required')
    if not args.candidate.is_absolute() or not (args.candidate / 'skills').is_dir():
        parser.error('Absolute candidate checkout required')
    if not args.hermes.is_absolute() or not args.hermes.is_file():
        parser.error('Explicit existing Hermes executable required')
    for key in ('TMPDIR', 'TEMP', 'TMP'):
        os.environ[key] = str(args.scratch)
    report = {'kind': 'local-http-native-probe', 'candidate': str(args.candidate),
              'hermes': str(args.hermes), 'home': str(args.home), 'commands': [],
              'native_candidate_installation': 'not_verified', 'public_source': 'not_exercised',
              'changed_upstream_update': 'not_exercised', 'hosted_mcp': 'not_exercised'}
    code = 2
    try:
        if not args.bootstrap_reviewed:
            report['native_candidate_installation'] = 'prerequisite_failed'
            raise ValueError('Launcher may prepare dependencies for a new data root; separate bootstrap review/approval required')
        home = prepare_disposable_home(args.home)
        env = build_native_env(home)
        # These exact paths prevent platform config fallbacks to the operator's home.
        env.update(HOME=str(home / 'user'), USERPROFILE=str(home / 'user'),
                   XDG_CONFIG_HOME=str(home / 'user/config'))
        report['environment_paths'] = {k: env[k] for k in ('HERMES_HOME', 'HERMES_PROFILE', 'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'XDG_CONFIG_HOME', 'TMPDIR')}
        runtime = print_runtime_command(hermes=args.hermes, env=env)
        report['runtime_command'] = runtime
        ok = True
        with loopback_server(args.candidate / 'skills') as server:
            report['loopback_address'] = list(server.server_address)
            for name in ('wiki-ingest', 'wiki-stage-commit'):
                url = f'http://127.0.0.1:{server.server_port}/{name}/SKILL.md'
                done = run_native([str(args.hermes), 'skills', 'install', url, '--name', name, '--yes'], env=env, cwd=args.candidate)
                report['commands'].append(asdict(done))
                installed = home / 'skills' / name
                if installed.is_dir():
                    report[name] = compare_inventories(args.candidate / 'skills' / name, installed)
                    ok = ok and done.returncode == 0 and report[name]['equal']
                else:
                    report[name] = {'installed': False}
                    ok = False
        report['loopback_shutdown_verified'] = True
        report['native_candidate_installation'] = 'content_present_provenance_unverified' if ok else 'blocked'
        # Provenance/check/update acceptance is intentionally a further gate, never inferred.
        code = 1
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        report['error'] = str(exc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({'report': str(args.output), 'native': report['native_candidate_installation'], 'exit_code': code}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())

