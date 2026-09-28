#!/usr/bin/env python3
"""Build a deterministic RAM-only diagnostic archive from a static ARM64 BusyBox."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct

INIT = b'''#!/bin/sh
export PATH=/bin
mount -t devtmpfs devtmpfs /dev
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t tmpfs tmpfs /tmp
echo 'rtctrl firstboot diagnostic environment; no block filesystems mounted'
uname -a
cat /proc/cmdline
cat /proc/partitions
echo 'No automatic network, recording, reboot or poweroff. Exit restarts shell.'
while :; do
    setsid cttyhack /bin/sh </dev/console >/dev/console 2>&1
    sleep 1
done
'''

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--busybox', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    data = a.busybox.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
        p.error('BusyBox must be little-endian ELF64 AArch64')
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', data, 54)
    if any(struct.unpack_from('<I', data, phoff + i * phsize)[0] == 3 for i in range(phnum)):
        p.error('BusyBox must not require a dynamic interpreter')
    manifest = a.output.with_suffix('.manifest.json')
    if any(path.exists() or path.is_symlink() for path in (a.output, manifest)):
        p.error('output must be new; refusing to overwrite')
    entries = [(d, 0o40755, b'', 0, 0) for d in ('bin', 'dev', 'proc', 'sys', 'tmp')]
    entries += [('dev/console', 0o20600, b'', 5, 1), ('dev/null', 0o20666, b'', 1, 3),
                ('bin/busybox', 0o100755, data, 0, 0), ('init', 0o100755, INIT, 0, 0)]
    for name in ('sh', 'mount', 'echo', 'uname', 'cat', 'setsid', 'cttyhack', 'sleep',
                 'ls', 'dmesg', 'grep', 'readlink', 'hexdump', 'mkdir'):
        entries.append(('bin/' + name, 0o120777, b'busybox', 0, 0))
    archive = bytearray()
    for ino, (name, mode, payload, major, minor) in enumerate(entries + [('TRAILER!!!', 0, b'', 0, 0)], 1):
        encoded = name.encode() + b'\0'
        fields = (ino, mode, 0, 0, 1, 0, len(payload), 0, 0, major, minor, len(encoded), 0)
        archive += b'070701' + ''.join(f'{v:08x}' for v in fields).encode() + encoded
        archive += bytes((-len(archive)) % 4)
        archive += payload
        archive += bytes((-len(archive)) % 4)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('xb') as stream:
        stream.write(gzip.compress(archive, mtime=0))
    with manifest.open('x') as stream:
        stream.write(json.dumps({
        'deployable': False, 'board_boot_tested': False,
        'busybox_sha256': hashlib.sha256(data).hexdigest(),
        'archive_sha256': hashlib.sha256(a.output.read_bytes()).hexdigest(),
        'entries': [e[0] for e in entries],
        'policy': 'RAM mounts only; interactive root shell; no automatic block writes'
    }, indent=2) + '\n')

if __name__ == '__main__':
    main()
