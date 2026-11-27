"""Tests for the gated native Hermes verifier.

These tests use only disposable homes and explicit scratch overrides.
Fixture integration is labeled and does not perform real source delivery.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_hermes_native", ROOT / "tools" / "verify_hermes_native.py")
assert SPEC and SPEC.loader
native = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = native
SPEC.loader.exec_module(native)


@pytest.fixture()
def scratch(monkeypatch, tmp_path):
    root = tmp_path / "hermes scratch"
    root.mkdir()
    monkeypatch.setenv("TMPDIR", str(root))
    monkeypatch.setenv("TEMP", str(root))
    monkeypatch.setenv("TMP", str(root))
    return root


def test_build_native_env_uses_explicit_scratch(scratch, tmp_path):
    home = tmp_path / "native-profile-001"
    home.mkdir()
    env = native.build_native_env(home)
    assert env["HERMES_HOME"] == str(home.resolve())
    assert env["HERMES_PROFILE"] == ""
    assert env["TMPDIR"] == str(scratch.resolve())
    assert env["TEMP"] == str(scratch.resolve())
    assert env["TMP"] == str(scratch.resolve())
    assert env["HOME"] == str(scratch.resolve())
    assert env["USERPROFILE"] == str(scratch.resolve())
    assert env["XDG_CONFIG_HOME"] == str((scratch / "xdg-config").resolve())


def test_prepare_disposable_home_requires_absolute_root(tmp_path, scratch):
    with pytest.raises(ValueError):
        native.native_home(Path("relative"))
    home = native.prepare_disposable_home(tmp_path / "native-profile-root")
    assert home.name.startswith("native-profile-")
    assert (home / "skills").is_dir()


def test_inventory_and_compare_detect_full_support_closure(tmp_path):
    source = tmp_path / "source"
    candidate = tmp_path / "candidate"
    for root in (source, candidate):
        (root / "references").mkdir(parents=True)
    (source / "SKILL.md").write_text("Read references/policy.md\n", encoding="utf-8")
    (source / "references" / "policy.md").write_text("support text\n", encoding="utf-8")
    (candidate / "SKILL.md").write_text("Read references/policy.md\n", encoding="utf-8")
    (candidate / "references" / "policy.md").write_text("support text\n", encoding="utf-8")
    result = native.compare_inventories(source, candidate)
    assert result["equal"] is True
    assert result["missing"] == []
    assert result["extra"] == []
    assert result["changed"] == []
    assert len(result["expected"]) == 2


def test_disposable_home_refuses_existing_target(tmp_path, scratch):
    home = native.prepare_disposable_home(tmp_path / 'native-profile-retained')
    with pytest.raises(ValueError):
        native.prepare_disposable_home(home)



def test_runtime_command_reads_native_launcher(monkeypatch, tmp_path, scratch):
    fake = tmp_path / "hermes.exe"
    fake.write_text("binary", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, '["python","-I"]', ""))
    assert native.print_runtime_command(hermes=fake, env=native.build_native_env(tmp_path / 'native-profile-mock')) == ["python", "-I"]


def test_no_ambient_native_probe_and_bounded_execution(tmp_path):
    import inspect
    signature = inspect.signature(native.print_runtime_command)
    assert 'env' in signature.parameters
    assert 'hermes' in signature.parameters
    assert 'timeout' in inspect.signature(native.run_native).parameters


def test_environment_refuses_home_override(scratch, tmp_path):
    home = tmp_path / 'native-profile-test'
    home.mkdir()
    with pytest.raises(ValueError):
        native.build_native_env(home, {'HERMES_HOME': 'C:/live'})


def test_loopback_server_closes_and_delivers_exact_candidate(tmp_path):
    import urllib.request
    import socket
    (tmp_path / 'SKILL.md').write_bytes(b'candidate\n')
    with native.loopback_server(tmp_path) as server:
        host, port = server.server_address
        assert host == '127.0.0.1'
        with urllib.request.urlopen(f'http://{host}:{port}/SKILL.md') as response:
            assert response.read() == b'candidate\n'
    with socket.socket() as probe:
        assert probe.connect_ex((host, port)) != 0


def test_cli_is_real_entrypoint_with_required_paths():
    result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/verify_hermes_native.py'), '--help'], capture_output=True, text=True)
    assert result.returncode == 0
    for flag in ('--candidate', '--hermes', '--home', '--scratch', '--output'):
        assert flag in result.stdout


def test_native_requires_explicit_bootstrap_review_before_launch(tmp_path, monkeypatch):
    candidate = tmp_path / 'candidate'
    (candidate / 'skills').mkdir(parents=True)
    fake = tmp_path / 'hermes.exe'
    fake.write_text('not executed', encoding='utf-8')
    output = tmp_path / 'report.json'
    def forbidden(*args, **kwargs):
        pytest.fail('unreviewed launcher execution')
    monkeypatch.setattr(native, 'print_runtime_command', forbidden)
    result = native.main(['--candidate', str(candidate), '--hermes', str(fake),
                          '--home', str(tmp_path / 'native-profile-gated'),
                          '--scratch', str(tmp_path), '--output', str(output)])
    import json
    report = json.loads(output.read_text(encoding='utf-8'))
    assert result == 2
    assert report['native_candidate_installation'] == 'prerequisite_failed'
    assert not (tmp_path / 'native-profile-gated').exists()


def test_no_machine_specific_executable_fallback():
    assert not hasattr(native, '_hermes_executable')
    source = (ROOT / 'tools/verify_hermes_native.py').read_text(encoding='utf-8')
    assert 'C:/Users/' not in source


def test_matching_fixture_content_still_exits_incomplete(tmp_path, monkeypatch):
    """Mocked CLI contract only; no native install or provenance proof."""
    import json
    import shutil
    from contextlib import contextmanager
    from types import SimpleNamespace
    candidate = tmp_path / 'candidate'
    for name in ('wiki-ingest', 'wiki-stage-commit'):
        skill = candidate / 'skills' / name
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('fixture only', encoding='utf-8')
    fake = tmp_path / 'hermes-not-executed'
    fake.write_text('fixture', encoding='utf-8')
    home = tmp_path / 'native-profile-mock-success'
    output = tmp_path / 'report.json'
    monkeypatch.setattr(native, 'print_runtime_command', lambda **kwargs: ['fixture-python'])
    @contextmanager
    def fake_server(*args):
        yield SimpleNamespace(server_address=('127.0.0.1', 12345), server_port=12345)
    monkeypatch.setattr(native, 'loopback_server', fake_server)
    def fake_run(command, **kwargs):
        name = command[command.index('--name') + 1]
        shutil.copytree(candidate / 'skills' / name, home / 'skills' / name)
        return native.NativeRun(command, 0, 'fixture only', '')
    monkeypatch.setattr(native, 'run_native', fake_run)
    code = native.main(['--candidate', str(candidate), '--hermes', str(fake),
                        '--home', str(home), '--scratch', str(tmp_path),
                        '--output', str(output), '--bootstrap-reviewed'])
    report = json.loads(output.read_text(encoding='utf-8'))
    assert code == 1
    assert report['native_candidate_installation'] == 'content_present_provenance_unverified'
    assert report['changed_upstream_update'] == 'not_exercised'
    assert all(report[name]['equal'] for name in ('wiki-ingest', 'wiki-stage-commit'))


def test_native_exit_contract_documented():
    text = (ROOT / 'docs/hermes-scanner-verification.md').read_text(encoding='utf-8')
    assert 'content_present_provenance_unverified' in text
    assert 'never returns exit 0 for native acceptance' in text


def test_launcher_environment_directories_exist_before_probe(tmp_path, monkeypatch):
    """Exercise preparation; never invoke the real launcher or network."""
    import json
    candidate = tmp_path / 'candidate'
    (candidate / 'skills').mkdir(parents=True)
    executable = tmp_path / 'hermes-not-executed'
    executable.write_text('fixture', encoding='utf-8')
    home = tmp_path / 'native-profile-environment'
    output = tmp_path / 'report.json'
    reached = []

    def inspect_boundary(*, hermes, env):
        expected = {
            'HOME': home / 'user', 'USERPROFILE': home / 'user',
            'APPDATA': home / 'user/roaming',
            'LOCALAPPDATA': home / 'user/local',
            'XDG_CONFIG_HOME': home / 'user/config',
        }
        for key, path in expected.items():
            assert Path(env[key]) == path
            assert path.is_dir(), key
        for key in ('TMPDIR', 'TEMP', 'TMP'):
            assert Path(env[key]) == tmp_path
        assert env['HERMES_HOME'] == str(home.resolve())
        assert env['HERMES_PROFILE'] == ''
        assert env['HERMES_ALLOW_PRIVATE_URLS'] == 'false'
        reached.append(True)
        raise RuntimeError('fixture stopped at launcher boundary')

    monkeypatch.setattr(native, 'print_runtime_command', inspect_boundary)
    code = native.main(['--candidate', str(candidate), '--hermes', str(executable),
                        '--home', str(home), '--scratch', str(tmp_path),
                        '--output', str(output), '--bootstrap-reviewed'])
    assert reached == [True]
    assert code == 2
    report = json.loads(output.read_text(encoding='utf-8'))
    assert report['error'] == 'fixture stopped at launcher boundary'
    assert report['native_candidate_installation'] == 'not_verified'
