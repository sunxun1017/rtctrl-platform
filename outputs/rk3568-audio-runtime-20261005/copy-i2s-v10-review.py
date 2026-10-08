#!/usr/bin/env python3
"""Preserve the independent review only after verifying its exact inventory."""
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
SOURCE = Path('/tmp/rtctrl-i2s-v10-review-sf8086ia')
DEST = HERE / 'build/i2s-v10-independent-review'
INVENTORY_SHA = '111c020d389bfcaab0088888bf85b1afc47bc62aeea14b00917e771bb48bfd8d'
CPU_SHA = 'cbd19c1a8b128d442f6321ebb9ce1d51524633536282862b6c06fa76b4f77b59'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    inventory = SOURCE / 'inventory.json'
    if sha(inventory) != INVENTORY_SHA:
        raise ValueError('Independent inventory changed')
    record = json.loads(inventory.read_text())
    if record['source_sha256'] != CPU_SHA or DEST.exists():
        raise ValueError('Expected CPU source and fresh destination required')
    files = record['files_sha256']
    for name, expected in files.items():
        src = SOURCE / name
        if not src.resolve().is_relative_to(SOURCE) or src.is_symlink() or sha(src) != expected:
            raise ValueError('Invalid independent evidence: ' + name)
    DEST.mkdir(parents=True)
    for name, expected in files.items():
        dst = DEST / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE / name, dst)
        if sha(dst) != expected:
            raise ValueError('Copy mismatch: ' + name)
    shutil.copyfile(inventory, DEST / 'inventory.json')
    result = {'files_verified': len(files), 'inventory_sha256': INVENTORY_SHA,
              'cpu_source_sha256': CPU_SHA, 'all_copied_hashes_match': True}
    (DEST / 'copy-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
