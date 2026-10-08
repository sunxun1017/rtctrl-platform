#!/usr/bin/env python3
"""Pack source networking tools, same-kernel module and tracked binary firmware."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import argparse
import re

root = Path.cwd()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--revision', default='v1')
revision = parser.parse_args().revision
if not re.fullmatch(r'v[1-9][0-9]*', revision):
    parser.error('Revision must be v followed by a positive integer')
out = root/'outputs/rk3568-source-wifi-20261004'
stage = out/('build/ramfs-' + revision)
assert not stage.exists()
stage.mkdir()
for directory in ['bin', 'dev', 'proc', 'sys', 'tmp', 'etc', 'lib/firmware', 'lib/modules', 'mnt/cache', 'dev/pts']:
    (stage/directory).mkdir(parents=True, exist_ok=True)
busybox = root/'outputs/rk3568-persistent-linux-20261003/busybox/busybox-1.36.1/busybox'
assert hashlib.sha256(busybox.read_bytes()).hexdigest() == '5c2f1c653fdfe92d21c5baa68a64a460dd9aff3b8947d526048314700e1d5844'
shutil.copy2(busybox, stage/'bin/busybox')
for applet in (root/'outputs/rk3568-persistent-linux-20261003/busybox-applets.txt').read_text().splitlines():
    (stage/'bin'/applet).symlink_to('busybox')
for name in ['wpa_supplicant', 'wpa_cli', 'network-helper']:
    shutil.copy2(out/name, stage/'bin'/name)
    (stage/'bin'/name).chmod(0o755)
shutil.copy2(out/'bcmdhd.ko', stage/'lib/modules/bcmdhd.ko')
shutil.copy2(root/'outputs/rk3568-source-userspace-20261004/ram-init.sh', stage/'init')
(stage/'init').chmod(0o755)
shutil.copy2(out/'dhcp-script.sh', stage/'etc/udhcpc.sh')
(stage/'etc/udhcpc.sh').chmod(0o755)
(stage/'etc/resolv.conf').touch()
firmware = {
    'fw_bcm43456c5_ag.bin': '06d3bebe4b193b5db97b7f99bde94e2e85ca95dc35677079ecf86f8f9b0eb734',
    'nvram_ap6256.txt': 'c36643f35c32b9248bbb34870a3ab152237907713e999533592acd925dd04410',
}
with tarfile.open(root/'outputs/rk3568-persistent-linux-20261003/wifi-original.tar.gz') as archive:
    for name, expected in firmware.items():
        data = archive.extractfile('etc/firmware/' + name).read()
        assert hashlib.sha256(data).hexdigest() == expected
        (stage/'lib/firmware'/name).write_bytes(data)

files = sorted(p.relative_to(stage).as_posix() for p in stage.rglob('*'))
# Existing cpio host tool is local to the dependency runtime; use a bounded argv.
cpio = shutil.which('cpio')
assert cpio
packed = subprocess.run([cpio, '--null', '-o', '--format=newc', '--owner=0:0'], cwd=stage,
                        input=b'\0'.join(p.encode() for p in files) + b'\0', capture_output=True, check=True)
packed_path = out/('initramfs-' + revision + '.cpio.gz')
assert not packed_path.exists()
with packed_path.open('wb') as stream:
    with gzip.GzipFile(fileobj=stream, mode='wb', mtime=0, filename='') as compressor:
        compressor.write(packed.stdout)
shutil.copy2(out/'build/dtb-v3/rk3568-aiot-3568pq-wifi.dtb', out/'wifi.dtb')
inputs = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in [Path(__file__), out/'network-helper.c', out/'dhcp-script.sh',
                    root/'outputs/rk3568-source-userspace-20261004/ram-init.sh',
                    out/'bcmdhd.ko', out/'wpa_supplicant', out/'wpa_cli', out/'network-helper']}
(out/('ramfs-inputs-' + revision + '.json')).write_text(json.dumps({'sources_and_binaries': inputs, 'firmware_sha256': firmware}, indent=2)+'\n')
print('NETWORK_INITRAMFS_PREPARED', len(packed.stdout), packed_path.stat().st_size)
