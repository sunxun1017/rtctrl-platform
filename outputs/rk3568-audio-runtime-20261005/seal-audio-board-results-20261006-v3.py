#!/usr/bin/env python3
"""Summarize the captured finite trial; it does not perform device operations."""
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIVATE = ROOT / 'outputs/rk3568-pid1-20261005/private'
OUT = HERE / 'build/board-results-20261006-v3'
OUT.mkdir(exist_ok=False)
files = {}
checks = []


def read(name):
    path = PRIVATE / name
    data = path.read_bytes()
    files[path.relative_to(ROOT).as_posix()] = {
        'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return data.decode('ascii', errors='replace').replace('\r', '')


def require(name, passed):
    checks.append({'name': name, 'passed': bool(passed)})
    assert passed, name


require('new_v3_RAM_aux_full_SHA_marker', re.search(
    r'^AUDIO_PACKAGE_V3_RAM_AUX_VERIFIED_NO_MODULE_OR_START$',
    read('audio-v3-copy-aux-20261006-v1.raw.txt'), re.M))

snapshots = {}
for label, filename, stage, allocated in [
    ('pre_playback', 'audio-v3-pre-playback-after-pm-diagnostic-20261006-v1.raw.txt', 'bound', 2),
    ('post_playback', 'audio-v3-post-playback-20261006-v1.raw.txt', 'bound', 2),
    ('pre_capture', 'audio-v3-pre-capture-20261006-v1.raw.txt', 'bound', 2),
    ('post_capture', 'audio-v3-post-capture-20261006-v1.raw.txt', 'bound', 2),
    ('card_unbound', 'audio-v3-card-unbound-20261006-v1.raw.txt', 'card-unbound', 2),
    ('cpu_unbound', 'audio-v3-cpu-unbound-20261006-v1.raw.txt', 'cpu-unbound', 0),
]:
    text = read(filename)
    marker = f'AUDIO_SESSION_IDLE_VERIFIED stage={stage} allocated={allocated} board_start_permission=0 reboot_permission=0'
    require(label + '_complete_guard', re.search('^' + re.escape(marker) + '$', text, re.M))
    require(label + '_zero_quarantine', re.search(r'^AUDIO_QUARANTINE 0$', text, re.M))
    cpu = re.search(r'^AUDIO_CPU (.*)$', text, re.M).group(1)
    dma = re.search(r'^AUDIO_DMA (.*)$', text, re.M).group(1)
    require(label + '_zero_software_and_PM', all(
        (' ' + key + '=0') in (' ' + dma)
        for key in ['error', 'pm_usage', 'leases', 'software', 'queued', 'descriptors']))
    require(label + '_STOP_cached_proven', ' stop_proven=1 ' in (' ' + dma + ' '))
    snapshots[label] = {'CPU': cpu, 'DMA': dma,
                        'clocks': re.search(r'AUDIO_CLOCKS_BEGIN\n(.*?)AUDIO_CLOCKS_END', text, re.S).group(1)}

streams = {}
for stream in ['playback', 'capture']:
    text = read(f'audio-v3-{stream}-20261006-v1.raw.txt')
    require(stream + '_exit_0', re.search('^' + stream.upper() + '_BOUNDED_V4_EXIT_0$', text, re.M))
    for operation in ['START', 'DROP', 'HW_FREE', 'CLOSE_PCM']:
        require(stream + '_' + operation + '_one_success', len(re.findall(
            '^PCM_STAGE name=' + operation + r' rc=0 errno=0$', text, re.M)) == 1)
    require(stream + '_no_helper_first_error', not re.search(r'^PCM_FIRST_ERROR', text, re.M))
    result = re.search('^PCM_TRANSFER card=1 stream=' + stream + r' frames=24576 (.*)$', text, re.M)
    require(stream + '_finite_transfer', result)
    streams[stream] = result.group(0)
    if stream == 'capture':
        require('capture_OFF_stats_only', 'samples=49152 zeros=49152 zero_ppm=1000000' in result.group(1))
    require(stream + '_old_close_error_absent', len(re.findall(
        r'ASoC: error at snd_soc_dai_set_sysclk on fe410000.i2s: -22', text)) == 0)

for filename, marker in [
    ('audio-v3-unbind-card-20261006-v1.raw.txt', 'AUDIO_NORMAL_CARD_UNBOUND'),
    ('audio-v3-unload-codec-20261006-v1.raw.txt', 'AUDIO_NORMAL_CODEC_UNLOADED'),
    ('audio-v3-unbind-cpu-20261006-v1.raw.txt', 'AUDIO_NORMAL_CPU_UNBOUND'),
    ('audio-v3-debug-unmount-20261006-v1.raw.txt', 'AUDIO_DEBUGFS_NORMAL_UNMOUNTED'),
    ('audio-v3-pre-native-return-20261006-v1.raw.txt', 'AUDIO_PRE_NATIVE_RETURN_ZERO_QUARANTINE'),
    ('audio-v3-native-return-check-20261006-v1.raw.txt', 'PID1_INDEPENDENT_RAM_ONLY_RETURN_READY'),
]:
    require(marker, re.search('^' + marker + '$', read(filename), re.M))

tests = read('audio-v3-native-tests-20261006-v1.raw.txt')
for test in ['codec', 'pty']:
    require('native_' + test, re.search('^SOFTWARE_TEST_PASSED path=/usr/bin/' + test + '-test exit=0$', tests, re.M))
require('native_real_return', re.search(
    r'^PID1_STATUS phase=4 loop=0 owned=1 forward=63 backward=63 pivot=1 old_unmounted=1 loop_detached=1 cache_unmounted=1$',
    read('audio-v3-native-return-20261006-v1.raw.txt'), re.M))

restart = read('audio-v3-normal-reboot-20261006-v1.raw.txt')
start = restart.index('\nNORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN\n')
end = restart.index('\nDDR ', start)
window = restart[start:end]
require('normal_restart_not_sysrq', 'reboot: Restarting system' in window and 'sysrq' not in window.lower())
require('restart_to_first_DDR_no_trace', not re.search(r'WARNING:|BUG:|Call trace:|Kernel panic', window))
require('new_close_diagnostics_absent_through_return', len(re.findall(
    r'ASoC: error at snd_soc_dai_set_sysclk on fe410000.i2s: -22',
    read('audio-v3-native-return-check-20261006-v1.raw.txt'))) == 0)

return_path = HERE / 'build/audio-return-v3-r2.json'
return_data = return_path.read_bytes()
files[return_path.relative_to(ROOT).as_posix()] = {
    'bytes': len(return_data), 'sha256': hashlib.sha256(return_data).hexdigest()}
receipt = json.loads(return_data)
require('fresh_original_Android_seven_and_native_SHA', receipt['completed'] is True)
require('no_partition_write_no_network_configuration_change', all(
    receipt[x] is False for x in ['partition_write', 'flash', 'saveenv', 'network_configuration_changed']))


initial = read('audio-v3-pre-playback-20261006-v1.raw.txt')
require('initial_idle_rejection_preserved', re.search(r'^AUDIO_SESSION_REJECTED operation=CPU idle proof errno=0$', initial, re.M))
require('initial_rejection_did_not_START', 'PCM_STAGE name=START' not in initial)
for filename, marker in [
    ('audio-v3-pm-diagnostic-on-20261006-v1.raw.txt', 'AUDIO_V3_DIAGNOSTIC_PM_ON_USAGE_ONE'),
    ('audio-v3-pm-diagnostic-auto-20261006-v1.raw.txt', 'AUDIO_V3_DIAGNOSTIC_PM_SUSPENDED_USAGE_ZERO'),
]:
    require(marker, re.search('^' + marker + '$', read(filename), re.M))
notes = read('audio-v3-live-image-identity-20261006-v2.raw.txt')
require('fresh_live_image_build_notes_sha', re.search(r'^31152f433f71e10fa685762108333ecaa5c4b6eb69613c65ffef7d8765c9682b  /sys/kernel/notes$', notes, re.M))
require('notes_exact_60_byte_hex', '040000001400000003000000474e550066eae96027cd89c53d2857bc971d23cccb2983600600000001000000000100004c696e757800000000000000' in notes)
fdt_dir = HERE / 'build/root-live-fdt-v3-audit'
fdt = (fdt_dir / 'live.dtb').read_bytes()
require('fresh_full_live_fdt_sha', len(fdt) == 168064 and hashlib.sha256(fdt).hexdigest() == 'c1cf7fd3ea52dc33171d6631f46d587d68fa180737c16c8d22fd0a69a0a3120a')
review = json.loads((fdt_dir / 'semantic-review.json').read_text())
require('full_fdt_semantics_review_record', review['nodes'] == 962 and review['phandles'] == 762 and len(review['full_property_changes']) == 31)
for path in [fdt_dir / 'live.dtb', fdt_dir / 'extraction.json', fdt_dir / 'semantic-review.json', HERE / 'build/live-image-v2-id/identity.json', HERE / 'build/board-audio-v3/input-manifest.json', HERE / 'build/integration-v2/manifest.json', HERE / 'build/integrated-codec-v2/manifest.json']:
    data = path.read_bytes()
    files[path.relative_to(ROOT).as_posix()] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
for path in PRIVATE.glob('audio-v3-*-20261006-*.raw.txt'):
    read(path.name)

result = {
    'finite_trial_completed': True, 'full_audio_adaptation_completed': False, 'initial_idle_verified_without_diagnostic': False, 'CPU_v11_close_regression_passed': True,
    'mode': 'RAM_ONLY_NOT_FLASH_READY', 'board_now': 'original_Android_verified_at_receipt_timestamp',
    'checks': checks, 'evidence': files, 'snapshots': snapshots, 'streams': streams,
    'known_blocker': 'initial set_fmt asynchronous PM idle raced with configuring; strict first guard rejected. One normal on-to-auto diagnostic idle request enabled this finite close regression. CPU v12 correction/new Image/initial-idle comparison pending',
    'scope': 'Single-thread native3/manual exclusive domain; S16_LE 48k 2ch 256x4; each direction 24576 frames; Playback/MIC/Resume OFF; capture statistics only',
    'not_verified': ['Acoustic playback/microphone quality',
                     'Product services and concurrent clients', 'poweroff/physical rails/MCU ACK',
                     'Formal flash and USB recovery', 'New battery calibration and charging'],
    'restart_window': window,
}
(OUT / 'result.json').write_bytes((json.dumps(result, indent=2, ensure_ascii=False) + '\n').encode('utf-8'))
print(json.dumps({'checks_passed': len(checks), 'evidence_files': len(files),
                  'finite_trial_completed': True, 'full_audio_adaptation_completed': False}))
