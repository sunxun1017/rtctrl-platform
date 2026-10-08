#!/usr/bin/env python3
"""Keep complete host copies before reclaiming three obsolete cache Images."""
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INPUTS = [
    ('source-kernel', ROOT / '.deps/kernel/aiot-3568pq-firstboot-final-config/arch/arm64/boot/Image',
     '/cache/rtctrl-source-kernel-20261004/Image', 34888192,
     'c0efb3bb522005cf106500c26c5c2c02d5905c2bfa9ecb273c2663db20aad4ec'),
    ('source-userspace', ROOT / 'outputs/rk3568-source-userspace-20261004/Image',
     '/cache/rtctrl-source-userspace-20261004/Image', 34755072,
     'b230838582b655f7786564ff21670ab1cd29172488df9c367a77d7005708c260'),
    ('source-wifi', ROOT / 'outputs/rk3568-rcu-reset-20261004/Image',
     '/cache/rtctrl-source-wifi-20261004/Image', 34755072,
     'e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457'),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    output = HERE / 'build/host-backups-v1'
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for name, path, board_path, size, digest in INPUTS:
        if not path.is_file() or path.is_symlink() or path.stat().st_size != size or sha(path) != digest:
            raise ValueError('Frozen host Image mismatch: ' + name)
        destination = output / (name + '.Image')
        shutil.copyfile(path, destination)
        if destination.stat().st_size != size or sha(destination) != digest:
            raise ValueError('Host backup verification failed')
        records.append(dict(name=name, source=str(path.relative_to(ROOT)), board_path=board_path,
                            bytes=size, sha256=digest, backup=str(destination.relative_to(ROOT))))
    receipt = dict(board_changed=False, files=records, total_bytes=sum(r['bytes'] for r in records),
                   purpose='Space for genuine PID1 and original boot RAM verification; ordinary cache files only',
                   protected_rcu_image_path='/cache/rtctrl-rcu-reset-20261004/Image')
    (output / 'manifest.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
