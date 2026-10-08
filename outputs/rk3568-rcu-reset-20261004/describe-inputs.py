#!/usr/bin/env python3
"""Describe new Image and identical verified DTB/initramfs; generate exact load steps."""
import hashlib
import json
from pathlib import Path
import struct
import tarfile
import zlib

here = Path(__file__).resolve().parent
repo = here.parents[1]
previous = here.parent / 'rk3568-source-userspace-20261004'
board = repo / 'platforms/rk3568/boards/aiot-3568pq'
old = json.loads((previous / 'kernel-artifacts.json').read_text())
artifacts = []
commands = []
checksums = ''
for name, address in (('Image', 0x400000), ('firstboot.dtb', 0x3000000), ('initramfs.cpio.gz', 0x4000000)):
    data = (here / name).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    crc = f'{zlib.crc32(data):08x}'
    if name != 'Image':
        expected = next(item['sha256'] for item in old['artifacts'] if item['file'] == name)
        assert sha == expected
    artifacts.append({'file': name, 'bytes': len(data), 'sha256': sha, 'crc32': crc, 'load_address': hex(address)})
    checksums += sha + '  ' + name + '\n'
    commands += [
        {'command': f'ext4load mmc 0:c {address:x} /rtctrl-rcu-reset-20261004/{name}',
         'wait': 4, 'expect': f'{len(data)} bytes read'},
        {'command': f'crc32 {address:x} {len(data):x}', 'expect': f'==> {crc}'}
    ]
data = (here / 'Image').read_bytes()
text_offset, memory_size, flags = struct.unpack_from('<QQQ', data, 8)
assert text_offset == 0 and 0x400000 + memory_size < 0x3000000
assert (here / 'kernel.config').read_bytes() == (previous / 'kernel.config').read_bytes()
metadata = {
    'kernel_release': (repo / '.deps/kernel/aiot-3568pq-rcu-reset/include/config/kernel.release').read_text().strip(),
    'source_commit': '9f9e9d18574d0914c0d192a90c3babfe1fd63c95',
    'artifacts': artifacts,
    'image_text_offset': text_offset, 'image_memory_bytes': memory_size, 'image_flags': flags,
    'kernel_config_sha256': hashlib.sha256((here / 'kernel.config').read_bytes()).hexdigest(),
    'patches': {name: hashlib.sha256((board / 'patches' / name).read_bytes()).hexdigest() for name in
                ('0001-arm64-cache-kasan-include.patch', '0002-rk817-feedback-diagnostic.patch',
                 '0003-printk-rcu-flush-context.patch')},
    'dtb_and_initramfs_reused_byte_for_byte': True,
    'board_tested_at_manifest_creation': False, 'deployable': False
}
(here / 'kernel-artifacts.json').write_text(json.dumps(metadata, indent=2) + '\n')
(here / 'boot-inputs.sha256').write_text(checksums)
commands += [{'command': 'fdt addr 3000000'}, {'command': 'fdt rsvmem print'},
             {'command': 'fdt print /reserved-memory', 'expect': 'no-map'}]
(here / 'load-ram.json').write_text(json.dumps(commands, indent=2) + '\n')
boot = json.loads((previous / 'boot-ram.json').read_text())
boot[-1] = {'command': f"booti 400000 4000000:{artifacts[2]['bytes']:x} 3000000", 'wait': 40}
(here / 'boot-ram.json').write_text(json.dumps(boot, indent=2) + '\n')
programs = json.loads((previous / 'userspace-artifacts.json').read_text())['source_programs']
source_checksums = ''
with tarfile.open(previous / 'rootfs.tar.gz') as archive:
    for item in programs:
        data = archive.extractfile('usr/bin/' + item['name']).read()
        assert len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256']
        with (here / item['name']).open('xb') as output:
            output.write(data)
        source_checksums += item['sha256'] + '  ' + item['name'] + '\n'
source_checksums += hashlib.sha256((here / 'test-source-programs.sh').read_bytes()).hexdigest() + '  test-source-programs.sh\n'
(here / 'source-inputs.sha256').write_text(source_checksums)
(here / 'source-programs.json').write_text(json.dumps(programs, indent=2) + '\n')
print(json.dumps(metadata, indent=2))
