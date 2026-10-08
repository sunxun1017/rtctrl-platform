#!/usr/bin/env python3
"""Record one root-authorized WSL invocation without modifying any service."""
from pathlib import Path
import hashlib
import json
import subprocess


def main():
    here = Path(__file__).resolve().parent
    out = here / 'launch-build-v1'
    out.mkdir(exist_ok=False)
    argv = ['wsl.exe', '-d', 'Ubuntu-22.04', '--cd', '/home/sx/projects/rtctrl-platform',
            '--exec', '/usr/bin/python3', '-B',
            'outputs/rk3568-audio-runtime-20261005/codec-image-v4-v1/codec_builder.py',
            '--image-sha256', '48b9958d36e2b4821235520360530faac38c9f2dae072c2a2602dbda7e048595',
            '--image-manifest-sha256', '8df525843cac41fd0e272351bc41d0e573c25570cfed7e60f1990b9fe97aa33a',
            '--attempt', 'v1']
    result = subprocess.run(argv, cwd='C:/', capture_output=True)
    (out / 'launcher.stdout').write_bytes(result.stdout)
    (out / 'launcher.stderr').write_bytes(result.stderr)
    record = {'argv': argv, 'exit': result.returncode,
              'stdout_sha256': hashlib.sha256(result.stdout).hexdigest(),
              'stderr_sha256': hashlib.sha256(result.stderr).hexdigest(),
              'launcher_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'services_TUN_or_network_modified': False}
    (out / 'command.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record))
    for data in [result.stdout, result.stderr]:
        if data:
            print(data.decode('utf-16-le' if b'\0' in data else 'utf-8', errors='replace'))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
