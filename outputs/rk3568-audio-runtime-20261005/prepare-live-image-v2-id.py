#!/usr/bin/env python3
"""Read the actual vmlinux notes without modifying the ELF or frozen package."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'build/live-image-v2-id'
VMLINUX = ROOT / '.deps/kernel/aiot-3568pq-audio-v2/vmlinux'
IMAGE = HERE / 'build/integration-v2/Image'

def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

assert not OUT.exists(), 'preserve previous identity evidence'
image_sha = sha(IMAGE)
assert image_sha == '974c6b88d53095cec2dd4488ae673bd2dbebc90861a689e93a83d5f6798d3620'
before = sha(VMLINUX)
result = subprocess.run(['aarch64-linux-gnu-readelf', '-x', '.notes', str(VMLINUX)],
                        capture_output=True, check=True)
assert not result.stderr
words = []
for line in result.stdout.decode('ascii').splitlines():
    match = re.match(r'\s+0x[0-9a-f]+\s+(.*)', line)
    if match:
        for word in match.group(1).split()[:4]:
            if re.fullmatch(r'[0-9a-f]{8}', word):
                words.append(word)
            else:
                break
notes = bytes.fromhex(''.join(words))
assert len(notes) == 60
assert notes.hex() == ('040000001400000003000000474e5500'
                       '66eae96027cd89c53d2857bc971d23cccb298360'
                       '0600000001000000000100004c696e757800000000000000')
assert sha(VMLINUX) == before
OUT.mkdir()
(OUT / 'readelf-notes.stdout').write_bytes(result.stdout)
(OUT / 'kernel.notes').write_bytes(notes)
record = {
    'image_sha256': image_sha,
    'vmlinux_sha256_before_and_after': before,
    'notes_bytes': len(notes),
    'notes_sha256': hashlib.sha256(notes).hexdigest(),
    'notes_hex': notes.hex(),
    'gnu_build_id': '66eae96027cd89c53d2857bc971d23cccb298360',
    'readelf_stdout_sha256': hashlib.sha256(result.stdout).hexdigest(),
    'scope': 'build identity for fresh /sys/kernel/notes comparison; not a full live RAM Image hash',
    'board_verified': False,
}
(OUT / 'identity.json').write_bytes((json.dumps(record, indent=2) + '\n').encode())
print(json.dumps(record))
