import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
p = Path(__file__).resolve().parent
image = (p / 'Image').read_bytes()
assert image[56:60] == b'ARM\x64'
offset, size, flags = struct.unpack_from('<QQQ', image, 8)
# Header image_size includes in-memory sections such as BSS, not just file bytes.
assert size >= len(image) > 64
config = (p / 'kernel.config').read_text()
for value in ('CONFIG_PREEMPT_RT=y', 'CONFIG_BLK_DEV_INITRD=y', 'CONFIG_RD_GZIP=y',
              'CONFIG_DEVTMPFS=y', 'CONFIG_PROC_FS=y', 'CONFIG_SYSFS=y'):
    assert value in config.splitlines(), value
builder = root / 'platforms/rk3568/boards/aiot-3568pq/build-initramfs.py'
busybox = root / '.deps/busybox-firstboot/busybox-1.36.1/busybox'
qemu = root / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
assert subprocess.check_output([str(qemu), str(busybox), 'ash', '-c', 'echo ARM64-shell-ok']).strip() == b'ARM64-shell-ok'
with tempfile.TemporaryDirectory() as d:
    output = Path(d) / 'test.gz'
    manifest = output.with_suffix('.manifest.json')
    manifest.write_text('preserve')
    result = subprocess.run(['python3', str(builder), '--busybox', str(busybox), '--output', str(output)], capture_output=True)
    assert result.returncode != 0 and manifest.read_text() == 'preserve' and not output.exists()
    manifest.unlink()
    subprocess.run(['python3', str(builder), '--busybox', str(busybox), '--output', str(output)], check=True)
    assert output.read_bytes() == (p / 'initramfs.cpio.gz').read_bytes()
archive = gzip.decompress((p / 'initramfs.cpio.gz').read_bytes())
assert b'070701' == archive[:6]
files = ('Image', 'initramfs.cpio.gz', 'rk3568-aiot-3568pq-firstboot.dtb', 'kernel.config',
         'busybox.config', '0001-arm64-cache-kasan-include.patch')
hashes = {name: hashlib.sha256((p / name).read_bytes()).hexdigest() for name in files}
manifest = {'deployable': False, 'board_boot_tested': False,
            'source_commit': '9f9e9d18574d0914c0d192a90c3babfe1fd63c95',
            'source_patch': '0001-arm64-cache-kasan-include.patch',
            'image_bytes': len(image), 'image_text_offset': offset,
            'image_size': size, 'image_flags': flags, 'sha256': hashes,
            'checks': ['ARM64 Image header', 'static AArch64 shell via user-mode QEMU',
                       'deterministic initramfs', 'manifest overwrite refused']}
(p / 'artifacts.json').write_text(json.dumps(manifest, indent=2) + '\n')
(p / 'SHA256SUMS').write_text(''.join(f'{h}  {name}\n' for name, h in hashes.items()))
print(json.dumps(manifest, indent=2))
