#!/usr/bin/env python3
"""Append a helper-only newc archive to the staged initramfs, reducing transfer."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

out = Path('outputs/rk3568-source-wifi-20261004')
stage = out/'build/helper-overlay-final'
assert not stage.exists()
(stage/'bin').mkdir(parents=True)
(stage/'bin/network-helper').write_bytes((out/'network-helper').read_bytes())
(stage/'bin/network-helper').chmod(0o755)
packed = subprocess.run(['cpio', '-o', '--format=newc', '--owner=0:0'], cwd=stage,
                        input=b'bin/network-helper\n', capture_output=True, check=True).stdout
overlay = gzip.compress(packed, mtime=0)
previous = (out/'initramfs.cpio.gz').read_bytes()
assert hashlib.sha256(previous).hexdigest() == '61f44b9a46f0b15b2947fedf5de67f95914520a6f20c15701057f85957343f49'
(out/'helper-overlay-final.cpio.gz').write_bytes(overlay)
(out/'initramfs-v5.cpio.gz').write_bytes(previous + overlay)
record = {name: {'bytes': (out/name).stat().st_size,
                 'sha256': hashlib.sha256((out/name).read_bytes()).hexdigest()}
          for name in ['initramfs.cpio.gz', 'helper-overlay-final.cpio.gz', 'initramfs-v5.cpio.gz', 'network-helper']}
(out/'overlay-inputs-final.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record, indent=2))
