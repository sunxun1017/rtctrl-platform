#!/usr/bin/env python3
"""Execute old/new real policy declarations without unavailable production Image."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--core', choices=('audio-package-v2.py', 'audio-package-v3.py'), required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = HERE / 'build' / args.out
    out.mkdir(parents=True, exist_ok=False)
    path = HERE / args.core
    spec = importlib.util.spec_from_file_location('transition_core', path)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    expected = 'outputs/rk3568-audio-runtime-20261005/'
    checks = [
        ('exact-new-production-directory', core.PRODUCTION == expected + 'build/integration-v2/'),
        ('exact-new-CPU-freeze', core.CPU_MANIFEST == '39fd8b0f1ccabd5d93d26ba540786865740a2b4c29295e392e7dcf4d65393e13'),
        ('explicit-runtime-inputs', callable(getattr(core, 'runtime_inputs', None))),
        ('exact-guard-v4-binary', getattr(core, 'RUNTIME_FIXED', {}).get('audio-session-guard', (None,))[0] ==
         expected + 'session-guard-v4/build/audio-session-guard'),
    ]
    result = {'scope': 'REAL_POLICY_DECLARATIONS_NOT_IMAGE_OR_BOARD', 'core': args.core,
              'core_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'test_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'passed': sum(ok for _, ok in checks), 'total': len(checks),
              'cases': [{'name': name, 'passed': ok} for name, ok in checks],
              'board_tested': False, 'production_Image_faked': False}
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['passed'] == result['total'] else 1)


if __name__ == '__main__':
    main()
