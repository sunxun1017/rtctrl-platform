#!/usr/bin/env python3
"""One ordinary WSL launcher retry, with real byte streams and no service changes."""
from pathlib import Path
import hashlib
import json
import os
import subprocess


def main():
    here = Path(__file__).resolve().parent
    out = here / 'launcher-retry-v1'
    out.mkdir(exist_ok=False)
    argv = ['wsl.exe', '-d', 'Ubuntu-22.04', '--cd', '/home/sx/projects/rtctrl-platform',
            '--exec', '/usr/bin/python3', '-B',
            'outputs/rk3568-audio-runtime-20261005/codec-image-v4-v1/preflight.py']
    try:
        result = subprocess.run(argv, cwd='C:\\', capture_output=True, timeout=55)
        stdout, stderr = result.stdout, result.stderr
        code, timed_out = result.returncode, False
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.stdout or b'', error.stderr or b''
        code, timed_out = None, True
    (out / 'launcher.stdout').write_bytes(stdout)
    (out / 'launcher.stderr').write_bytes(stderr)
    record = {'argv': argv, 'exit': code, 'timed_out': timed_out,
              'stdout_sha256': hashlib.sha256(stdout).hexdigest(),
              'stderr_sha256': hashlib.sha256(stderr).hexdigest(),
              'Linux_preflight_result_exists': (here / 'preflight-v1/result.json').is_file(),
              'module_build_invoked': False, 'services_TUN_or_network_modified': False}
    (out / 'command.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record))
    if stdout:
        print(stdout.decode('utf-16-le' if b'\0' in stdout else 'utf-8', errors='replace'))
    if stderr:
        print(stderr.decode('utf-16-le' if b'\0' in stderr else 'utf-8', errors='replace'))
    return 1 if timed_out or code else 0


if __name__ == '__main__':
    raise SystemExit(main())
