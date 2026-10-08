#!/usr/bin/env python3
"""Read v3 vmlinux notes, preserving the complete input ELF."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'build/live-image-v3-id'
VMLINUX = ROOT / '.deps/kernel/aiot-3568pq-audio-v3/vmlinux'
IMAGE = HERE / 'build/integration-v3/Image'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


assert not OUT.exists() and not OUT.is_symlink(), 'fresh identity evidence required'
manifest = json.loads((IMAGE.parent / 'manifest.json').read_text())
assert manifest['build_exit_code'] == 0
assert manifest['cpu_source_sha256'] == '7b56bad38b5824b6fdbfb30c735f79f6134f3dd67c87975144598fb31a553141'
assert manifest['review_gate_sha256'] == '181786c4a71065614f744ad609a0dc1a2c3a0dff0eaea21cda3a9fb319faf55d'
assert not manifest['battery_algorithm_enabled']
image_sha = sha(IMAGE)
assert image_sha == manifest['image_sha256']
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
assert notes[:16].hex() == '040000001400000003000000474e5500'
assert notes[36:].hex() == '0600000001000000000100004c696e757800000000000000'
assert notes[16:36] != b'\0' * 20
assert sha(VMLINUX) == before
OUT.mkdir()
(OUT / 'readelf-notes.stdout').write_bytes(result.stdout)
(OUT / 'kernel.notes').write_bytes(notes)
record = {
    'image_sha256': image_sha,
    'image_manifest_sha256': sha(IMAGE.parent / 'manifest.json'),
    'vmlinux_sha256_before_and_after': before,
    'notes_bytes': len(notes),
    'notes_sha256': hashlib.sha256(notes).hexdigest(),
    'notes_hex': notes.hex(),
    'gnu_build_id': notes[16:36].hex(),
    'readelf_stdout_sha256': hashlib.sha256(result.stdout).hexdigest(),
    'tool_sha256': sha(Path(__file__)),
    'scope': 'build identity for fresh /sys/kernel/notes comparison; not a full live RAM Image hash',
    'board_verified': False,
}
(OUT / 'identity.json').write_bytes((json.dumps(record, indent=2) + '\n').encode())
print(json.dumps(record))
