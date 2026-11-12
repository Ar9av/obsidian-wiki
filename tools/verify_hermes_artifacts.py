"""Explicit, offline Hermes artifact compatibility gate (no installation)."""
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path


def load_scanner(path, expected_sha256=None):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('Explicit scanner source file is missing')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('Reviewed scanner SHA-256 does not match')
    spec = importlib.util.spec_from_file_location('ow_reviewed_skills_guard', path)
    if spec is None or spec.loader is None:
        raise ValueError('Cannot load scanner')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module.SCANNER_VERSION != 'skills-guard-v10':
        raise ValueError('Unsupported scanner version; review before extending support')
    return module


def audit_composition(root, scannable=None):
    files = inventory(root)
    if 'SKILL.md' not in files:
        raise ValueError('Artifact lacks SKILL.md')
    if any(Path(p).name in ('.skillignore', '.clawhubignore') for p in files):
        raise ValueError('Artifact exclusion files are not allowed in this gate')
    extensions = scannable if scannable is not None else {'.md', '.py', '.sh', '.json', '.yaml', '.yml', '.txt'}
    return {'files': sorted(files), 'unscannable': sorted(
        p for p in files if p != 'SKILL.md' and Path(p).suffix.lower() not in extensions)}


def scan_artifact(scanner, root):
    composition = audit_composition(root, scanner.SCANNABLE_EXTENSIONS)
    result = scanner.scan_skill(Path(root), source='community')
    allowed, reason = scanner.should_allow_install(result, force=False)
    if result.trust_level != 'community':
        raise ValueError('Scanner did not apply community policy')
    return {**asdict(result), 'allowed': allowed, 'reason': reason, 'force': False,
            'gate_passed': allowed is True and not composition['unscannable'],
            'composition': composition, 'inventory': inventory(root)}


def inventory(root):
    root = Path(root)
    if not root.is_dir():
        raise ValueError('Artifact directory is missing')
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlinks require separate delivery review: ' + str(path))
        if path.is_file():
            data = path.read_bytes()
            result[path.relative_to(root).as_posix()] = {
                'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return result


def compare_artifacts(source, delivered):
    left, right = inventory(source), inventory(delivered)
    missing = sorted(left.keys() - right.keys())
    extra = sorted(right.keys() - left.keys())
    changed = sorted(k for k in left.keys() & right.keys() if left[k] != right[k])
    return {'equal': not (missing or extra or changed), 'missing': missing,
            'extra': extra, 'changed': changed, 'source': left, 'delivered': right}


def git_identity(root):
    result = {'root': str(Path(root).resolve())}
    for key, args in {'head': ['rev-parse', 'HEAD'],
                      'status': ['status', '--porcelain=v1', '-uall'],
                      'describe': ['describe', '--tags', '--always', '--dirty']}.items():
        done = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
        result[key] = done.stdout.strip() if done.returncode == 0 else None
    return result


def runtime_identity(candidate):
    candidate = Path(candidate).resolve()
    # Isolated interpreter: no installed editable packages or startup .pth files.
    code = ('import sys,json; from pathlib import Path; '
            'sys.path.insert(0,sys.argv[1]); import obsidian_wiki.cli as c; '
            'print(json.dumps({"module":str(Path(c.__file__).resolve()),'
            '"assets":str(c.skills_dir().resolve())}))')
    done = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', code, str(candidate)],
                          cwd=candidate, capture_output=True, text=True, check=True)
    report = json.loads(done.stdout)
    if not Path(report['module']).is_relative_to(candidate):
        raise ValueError('Runtime imported outside candidate')
    if Path(report['assets']) != candidate / 'skills':
        raise ValueError('Runtime assets do not point at candidate skills')
    names = []
    for name in ('wiki-ingest', 'wiki-stage-commit'):
        paths = list((candidate / 'skills').glob('**/' + name + '/SKILL.md'))
        if paths != [candidate / 'skills' / name / 'SKILL.md']:
            raise ValueError('Missing or duplicate implementation: ' + name)
        names.append(name)
    report['selected_skill_names'] = names
    report['scope'] = 'isolated source harness; not installed wheel or live skill discovery'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--scanner', type=Path, required=True)
    parser.add_argument('--scanner-sha256', required=True,
                        help='SHA-256 of operator-reviewed unchanged scanner source')
    parser.add_argument('--delivered-skills', type=Path,
                        help='Optional actual adapter/installed skill root; never copied to manufacture a pass')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('Refusing to overwrite an existing evidence report')
    report = {'candidate': git_identity(args.candidate), 'native_installation': 'not_exercised',
              'hosted_mcp': 'not_exercised', 'publication': 'not_exercised',
              'delivery_provenance': 'not_verified_by_this_content_comparison',
              'candidate_execution': 'reviewed_local_code; interpreter isolation is not a security sandbox',
              'source_artifacts': {}, 'delivered_artifacts': {}}
    code = 2
    try:
        scanner = load_scanner(args.scanner, args.scanner_sha256)
        report['scanner'] = {**git_identity(args.scanner.resolve().parents[1]),
                             'path': str(args.scanner.resolve()),
                             'sha256': hashlib.sha256(args.scanner.read_bytes()).hexdigest(),
                             'version': scanner.SCANNER_VERSION,
                             'policy': scanner.INSTALL_POLICY, 'force': False}
        report['runtime'] = runtime_identity(args.candidate)
        allowed = True
        for name in ('wiki-ingest', 'wiki-stage-commit'):
            source = args.candidate / 'skills' / name
            scan = scan_artifact(scanner, source)
            report['source_artifacts'][name] = scan
            allowed = allowed and scan['gate_passed'] is True
            if args.delivered_skills is not None:
                delivered = args.delivered_skills / name
                comparison = compare_artifacts(source, delivered)
                scan = scan_artifact(scanner, delivered)
                report['delivered_artifacts'][name] = {'comparison': comparison, 'scan': scan}
                allowed = allowed and comparison['equal'] and scan['gate_passed'] is True
        code = 0 if allowed else 1
        report['status'] = 'passed' if allowed else 'blocked'
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        report['status'] = 'prerequisite_failed'
        report['error'] = str(exc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({'status': report['status'], 'report': str(args.output), 'exit_code': code}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
