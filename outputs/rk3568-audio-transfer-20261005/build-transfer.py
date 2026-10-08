#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build static real ARM64 helper and freeze all offline/source/ABI evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zlib
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = HERE / 'pcm-transfer.c'
UAPI = ROOT / 'third_party/linux-rk3588/include/uapi/sound/asound.h'
CROSS_UAPI = Path('/usr/aarch64-linux-gnu/include/sound/asound.h')
CONFIG = ROOT / 'outputs/rk3568-source-userspace-20261004/kernel.config'
QEMU = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(output, name, argv):
    r = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=30)
    (output / (name + '.stdout')).write_text(r.stdout)
    (output / (name + '.stderr')).write_text(r.stderr)
    if r.returncode: raise ValueError(name + ' failed: ' + r.stderr)
    return r.stdout
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'v[1-9][0-9]*', args.version): raise ValueError('version must be vN')
    locks = {UAPI:'138cb9e8de8df6cdf2abb05806d7f61078fb7ea44063e5914bea277ef55a0447', CROSS_UAPI:'b62c8bff11f4aeea5df38899dbb2e18af10c0ffba770c005a85a0bc827fcefbe', CONFIG:'1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912'}
    for p, value in locks.items():
        if p.is_symlink() or sha(p) != value: raise ValueError('input lock changed: ' + str(p))
    provenance = json.loads((HERE / 'source-provenance-final.json').read_text())
    if not provenance['final_source_reproduction_verified'] or provenance['source_sha256'] != sha(SOURCE): raise ValueError('source reproduction mismatch')
    output = HERE / 'build' / ('static-' + args.version)
    output.mkdir(exist_ok=False)
    compiler = save(output, 'compiler-version', ['aarch64-linux-gnu-gcc', '--version']).splitlines()[0]
    if compiler != 'aarch64-linux-gnu-gcc (Ubuntu 11.4.0-1ubuntu1~22.04.3) 11.4.0': raise ValueError('compiler mismatch')
    green_dir = HERE / 'build/tests-green-v6'
    green = json.loads((green_dir / 'result.json').read_text())
    if not green['passed'] or green['source_sha256'] != sha(SOURCE) or green['wrapper_sha256'] != sha(HERE / 'test-wrapper.c') or green['script_sha256'] != sha(HERE / 'test-transfer.py'): raise ValueError('final green source/tests changed')
    for mode, run in green['runs'].items():
        if run['compile_exit'] or len(run['cases']) != 143 or not all(c['passed'] for c in run['cases']): raise ValueError('incomplete test suite')
        if sha(green_dir / ('helper-' + mode)) != run['binary_sha256']: raise ValueError('test binary changed')
    missing = json.loads((HERE / 'build/tests-red-v5/result.json').read_text())
    logging = json.loads((HERE / 'build/tests-red-v4/result.json').read_text())
    deadline = json.loads((HERE / 'build/tests-red-v6/result.json').read_text())
    for red in [missing, logging, deadline]:
        if red['passed'] or any(r['compile_exit'] for r in red['runs'].values()): raise ValueError('red control did not genuinely compile/fail')
    shutil.copy2(SOURCE, output / 'pcm-transfer.c')
    shutil.copy2(UAPI, output / 'asound-locked.h')
    binary = output / 'pcm-transfer'
    argv = ['aarch64-linux-gnu-gcc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-fno-ident', '-fstack-protector-strong', '-D_FORTIFY_SOURCE=2', '-D__user=', '-D__force=', '-DALSA_LOCKED_UAPI="asound-locked.h"', '-I' + str(output), '-static', '-Wl,--build-id=sha1', str(output / 'pcm-transfer.c'), '-o', str(binary)]
    (output / 'build-argv.json').write_text(json.dumps(argv, indent=2) + '\n')
    save(output, 'compile', argv)
    data = binary.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 183: raise ValueError('not native ARM64 ELF64 LE')
    headers = save(output, 'elf-headers', ['aarch64-linux-gnu-readelf', '-h', '-l', '-d', binary])
    if 'INTERP' in headers or '(NEEDED)' in headers: raise ValueError('binary not static')
    save(output, 'undefined-symbols', ['aarch64-linux-gnu-nm', '-u', binary])
    if (output / 'undefined-symbols.stdout').read_text().strip(): raise ValueError('static unresolved symbols')
    # Verify both exact locked vendor and cross-libc ABI, including all new SW/state ioctls.
    abi_code = r'''#define __user
#define __force
#include <stdio.h>
#include <stddef.h>
#include <time.h>
#include <sys/ioctl.h>
#ifdef VENDOR
#include "asound-locked.h"
#else
#include <sound/asound.h>
#endif
int main(void) {
 printf("{\"card\":%zu,\"info\":%zu,\"hw\":%zu,\"sw\":%zu,\"start_offset\":%zu,\"status\":%zu,\"sw_ioctl\":%lu,\"prepare\":%lu,\"start\":%lu,\"drop\":%lu,\"hw_free\":%lu}\n",sizeof(struct snd_ctl_card_info),sizeof(struct snd_pcm_info),sizeof(struct snd_pcm_hw_params),sizeof(struct snd_pcm_sw_params),offsetof(struct snd_pcm_sw_params,start_threshold),sizeof(struct snd_pcm_status),(unsigned long)SNDRV_PCM_IOCTL_SW_PARAMS,(unsigned long)SNDRV_PCM_IOCTL_PREPARE,(unsigned long)SNDRV_PCM_IOCTL_START,(unsigned long)SNDRV_PCM_IOCTL_DROP,(unsigned long)SNDRV_PCM_IOCTL_HW_FREE); return 0;
}'''
    (output / 'abi.c').write_text(abi_code)
    abi_values = {}
    for label, flags in [('vendor', ['-DVENDOR']), ('cross', [])]:
        exe = output / ('abi-' + label)
        save(output, 'abi-' + label + '-compile', ['aarch64-linux-gnu-gcc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-static', '-I' + str(output), *flags, output / 'abi.c', '-o', exe])
        abi_values[label] = json.loads(save(output, 'abi-' + label + '-run', [QEMU, exe]))
    if abi_values['vendor'] != abi_values['cross']: raise ValueError('vendor/cross ABI differs')
    expected = dict(card=376,info=288,hw=608,sw=136,start_offset=32,status=152,sw_ioctl=0xc0884113,prepare=0x4140,start=0x4142,drop=0x4143,hw_free=0x4112)
    if abi_values['vendor'] != expected: raise ValueError('unexpected native64 ALSA ABI')
    probe = subprocess.run([str(QEMU), str(binary)], capture_output=True, text=True, timeout=5)
    (output / 'no-arguments.stdout').write_text(probe.stdout); (output / 'no-arguments.stderr').write_text(probe.stderr)
    if probe.returncode != 2 or 'usage:' not in probe.stderr: raise ValueError('static actual program invalid invocation failed')
    files = {}
    for folder in [HERE / 'build/tests-red-v5', HERE / 'build/tests-red-v4', HERE / 'build/tests-red-v6', green_dir, output]:
        for p in sorted(folder.rglob('*')):
            if p.is_file(): files[str(p.relative_to(HERE))] = sha(p)
    for p in sorted(HERE.glob('*')):
        if p.is_file(): files[p.name] = sha(p)
    record = dict(binary=str(binary), binary_sha256=sha(binary), binary_bytes=len(data), binary_crc32=format(zlib.crc32(data)&0xffffffff,'08x'), source_sha256=sha(SOURCE), locked_uapi_sha256=sha(UAPI), cross_uapi_sha256=sha(CROSS_UAPI), config_sha256=sha(CONFIG), compiler=compiler, abi=expected, qemu_sha256=sha(QEMU), test_cases_per_environment=143, tests=['host complete real C syscall boundaries', 'ASan/UBSan including fortify syscall boundaries', 'ARM64 QEMU complete real C program', 'real inherited SIGALRM ignore/block soft deadline with normal cleanup', 'vendor/cross exact ARM64 ABI'], files_sha256=files, board_tested=False, actual_bounded_transfer=False, real_alsa_device_access_on_host=False, audio_start_allowed=False, deployable=False, published=False, full_duplex_supported=False, permits_reboot=False, guard_owner='root session guard: exclusive device FDs, CPU sticky/uncertain/IRQ/clock and DMA poison/quarantine/lease/STOPPED proof', protocol=dict(card_id='rockchiprk809co', card_driver='rockchip_rk809-', card_name='rockchip,rk809-codec', card_longname='rockchip,rk809-codec', dynamic_cards='unique matching controlC0..31, no fixed card number', pcm='D0/subdevice0 full fe410000.i2s-rk817-hifi rk817-hifi-0 identity', format='S16_LE', access='RW_INTERLEAVED', rate=48000, channels=2, period_frames=256, periods=4, buffer_frames=1024, max_frames=48000, frames_multiple=256, recommended_frames=24576, timeout_ms_range=[100,10000], recommended_timeout_ms=5000, no_automatic_start=True, explicit_start_calls=1, playback='only zero samples, prefill1024, bounded queued count then DROP (no DRAIN)', capture='only frames/samples/zeros/zero_ppm, no acoustic files', trace_capacity_bytes=262144, cleanup_trace_reserve_bytes=4096, output='deferred until normal DROP/HW_FREE/close attempts, global soft timer through trace output', first_error_preserved=True, stateful_ioctl_retries=0, close_attempts_per_fd=1, cleanup_after_params_attempt=['DROP','STATUS if DROP succeeds','HW_FREE','STATUS if HW_FREE succeeds','close'], soft_deadline_only=True), limitations=['Uninterruptible or wedged kernel syscall cannot be forced to return by this helper; cancellation enters normal cleanup and never kills/reboots/unloads/resets', 'Buffered output or unschedulable user space can exceed a soft global deadline; root supervisor remains responsible for rescue', 'Read/write positive returns are native PCM bytes; frames count is bytes/4, queued playback is not proof all frames were consumed', 'STATUS hw_ptr advance is a userspace observation, not electrical/acoustic or DMA quiescence proof', 'Card/PCM identity snapshots do not exclude concurrent removal/rebind/activity; external exclusive guard is required', 'C3/Image/actual audio transfer/electrical and physical hardware acceptance remain with root'])
    (output / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({k:record[k] for k in ['binary','binary_sha256','source_sha256','binary_bytes','test_cases_per_environment','board_tested','actual_bounded_transfer']} | {'manifest':str(output / 'manifest.json')}))
if __name__ == '__main__': main()
