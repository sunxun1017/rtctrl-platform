#!/usr/bin/env python3
"""Check and record an already captured RAM trial; never operate the board."""
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIVATE = ROOT / 'outputs/rk3568-pid1-20261005/private'
OUT = HERE / 'build/board-results-20261006-v4'
files = {}
checks = []


def evidence(path):
    data = path.read_bytes()
    files[path.relative_to(ROOT).as_posix()] = {
        'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return data


def read(name):
    return evidence(PRIVATE / name).decode('ascii').replace('\r', '')


def require(name, passed):
    checks.append({'name': name, 'passed': bool(passed)})
    if not passed:
        raise ValueError(name)


def marker(name, text):
    require(name, re.search('^' + re.escape(name) + '$', text, re.M))


if OUT.exists():
    raise ValueError('Fresh result directory required')

marker('AUDIO_PACKAGE_V4_RAM_AUX_VERIFIED_NO_MODULE_OR_START',
       read('audio-v4-copy-aux-20261006-v1.raw.txt'))
codec = read('audio-v4-codec-observation-20261006-v1.raw.txt')
require('natural_initial_runtime_suspended', re.search(r'^suspended$', codec, re.M))
require('initial_CPU_has_no_owned_MCLK_or_live_IRQ',
        re.search(r'^version=1 ready=1 error=0 owners=0 open=0 stop_proven=1 stop_reads=2 irq_live=0 irq_drained=1 mclk_leases=0 hclk_lease=1 configuring=0 power_transition=0 shutting_down=0$', codec, re.M))

snapshots = {}
for label, filename, stage, allocated in [
    ('pre_playback', 'pre-playback', 'bound', 2),
    ('post_playback', 'post-playback', 'bound', 2),
    ('pre_capture', 'pre-capture', 'bound', 2),
    ('post_capture', 'post-capture', 'bound', 2),
    ('card_unbound', 'card-unbound-guard', 'card-unbound', 2),
    ('cpu_unbound', 'cpu-unbound-guard', 'cpu-unbound', 0),
]:
    text = read(f'audio-v4-{filename}-20261006-v1.raw.txt')
    marker(f'AUDIO_SESSION_IDLE_VERIFIED stage={stage} allocated={allocated} board_start_permission=0 reboot_permission=0', text)
    marker('AUDIO_QUARANTINE 0', text)
    marker(label.upper() + '_V4_EXIT_0', text)
    cpu = re.search(r'^AUDIO_CPU (.*)$', text, re.M).group(1)
    dma = re.search(r'^AUDIO_DMA (.*)$', text, re.M).group(1)
    require(label + '_zero_DMA_software_PM_and_leases', all(
        (' ' + key + '=0') in (' ' + dma)
        for key in ['error', 'pm_usage', 'leases', 'software', 'queued', 'descriptors']))
    require(label + '_STOP_cached_proven', ' stop_proven=1 ' in (' ' + dma + ' '))
    clocks = re.search(r'AUDIO_CLOCKS_BEGIN\n(.*?)AUDIO_CLOCKS_END', text, re.S).group(1)
    rows = re.findall(r'^([^ ]+) enable=(\d+) prepare=(\d+) protect=(\d+)$', clocks, re.M)
    require(label + '_sixteen_unique_clock_rows', len(rows) == 16 and len({row[0] for row in rows}) == 16)
    if stage == 'cpu-unbound':
        require('CPU_unbound_all_clock_refs_zero', all(row[1:] == ('0', '0', '0') for row in rows))
    snapshots[label] = {'CPU': cpu, 'DMA': dma, 'clocks': clocks}

streams = {}
for stream in ['playback', 'capture']:
    text = read(f'audio-v4-{stream}-20261006-v1.raw.txt')
    marker(stream.upper() + '_BOUNDED_V4_EXIT_0', text)
    for operation in ['START', 'DROP', 'HW_FREE', 'CLOSE_PCM']:
        require(stream + '_' + operation + '_one_success', len(re.findall(
            '^PCM_STAGE name=' + operation + r' rc=0 errno=0$', text, re.M)) == 1)
    require(stream + '_no_helper_first_error', not re.search(r'^PCM_FIRST_ERROR', text, re.M))
    result = re.search('^PCM_TRANSFER card=1 stream=' + stream + r' frames=24576 (.*)$', text, re.M)
    require(stream + '_finite_transfer_summary', result)
    streams[stream] = result.group(0)
    if stream == 'capture':
        require('capture_OFF_stats_only', 'samples=49152 zeros=49152 zero_ppm=1000000' in result.group(1))
    require(stream + '_old_close_error_absent', 'ASoC: error at snd_soc_dai_set_sysclk on fe410000.i2s: -22' not in text)

for filename, expected in [
    ('unbind-card', 'AUDIO_NORMAL_CARD_UNBOUND'),
    ('unload-codec', 'AUDIO_NORMAL_CODEC_UNLOADED'),
    ('unbind-cpu', 'AUDIO_NORMAL_CPU_UNBOUND'),
    ('unmount-audio-debug', 'AUDIO_DEBUGFS_NORMAL_UNMOUNTED'),
    ('pre-native-return', 'AUDIO_PRE_NATIVE_RETURN_ZERO_QUARANTINE'),
    ('native-return-check', 'PID1_INDEPENDENT_RAM_ONLY_RETURN_READY'),
]:
    marker(expected, read(f'audio-v4-{filename}-20261006-v1.raw.txt'))

tests = read('audio-v4-native-tests-20261006-v1.raw.txt')
for test in ['codec', 'pty']:
    marker(f'SOFTWARE_TEST_PASSED path=/usr/bin/{test}-test exit=0', tests)
marker('PID1_STATUS phase=4 loop=0 owned=1 forward=63 backward=63 pivot=1 old_unmounted=1 loop_detached=1 cache_unmounted=1',
       read('audio-v4-native-return-20261006-v1.raw.txt'))

restart = read('audio-v4-native-reboot-20261006-v1.raw.txt')
start = restart.index('\nNORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN\n')
end = restart.index('\nDDR ', start)
window = restart[start:end]
require('normal_restart_not_sysrq', 'reboot: Restarting system' in window and 'sysrq' not in window.lower())
require('restart_to_first_DDR_no_serious_trace', not re.search(r'WARNING:|BUG:|Call trace:|Kernel panic', window))
return_check = read('audio-v4-native-return-check-20261006-v1.raw.txt')
require('no_old_close_diagnostic_through_return', 'ASoC: error at snd_soc_dai_set_sysclk on fe410000.i2s: -22' not in return_check)

manifest = json.loads(evidence(HERE / 'build/board-audio-v4/input-manifest.json'))
receipt = json.loads(evidence(HERE / 'build/audio-return-v4.json'))
require('fresh_original_Android_receipt_complete', receipt['completed'] is True)
require('no_partition_write_no_network_configuration_change', all(
    receipt[key] is False for key in ['partition_write', 'flash', 'saveenv', 'network_configuration_changed']))
commands = receipt['commands']
require('fresh_original_Android_identity', commands[0]['output'] == '0\n4.19.232\n11\n1' and commands[0]['exit_code'] == 0)
require('fresh_seven_protected_full_SHA_equal', commands[1]['output'] == '\n'.join(manifest['protected_sha256']) and commands[1]['exit_code'] == 0)
require('fresh_native_cached_full_SHA_equal', commands[2]['output'] == '\n'.join(manifest['native_cached_sha256']) and commands[2]['exit_code'] == 0)

notes = read('audio-v4-live-image-identity-20261006-v1.raw.txt')
marker('59373c55bac7c0b89c2da52f489c32f90d4dac2b0a85f55aafb87163f1d370af  /sys/kernel/notes', notes)
require('notes_exact_60_byte_hex', '040000001400000003000000474e5500121dee3f6b55985315d213be760d486507815b9f0600000001000000000100004c696e757800000000000000' in notes)
fdt_dir = HERE / 'build/root-live-fdt-v4-audit'
fdt = evidence(fdt_dir / 'live.dtb')
require('fresh_complete_live_FDT_identity', len(fdt) == 168064 and hashlib.sha256(fdt).hexdigest() == '93dfe8b5bb3dc943b2734a07aaca245c2a0ad503890c5256bc6da22f1879c2a0')
review = json.loads(evidence(fdt_dir / 'root-semantic-analysis.json'))
independent = json.loads(evidence(fdt_dir / 'independent-review.json'))
require('complete_FDT_root_and_independent_review',
        review['nodes'] == independent['nodes'] == 962 and
        review['phandles'] == independent['phandles'] == 762 and
        len(review['full_property_changes_from_baseline']) == 31 and
        independent['header_nodes_properties_phandles_reservations_equal_to_v3'] is True)

for path in sorted(PRIVATE.glob('audio-v4-*-20261006-*.raw.txt')):
    text = read(path.name)
    require('no_PM_diagnostic_in_' + path.name, 'power/control' not in text)

for path in [
    fdt_dir / 'extraction.json', HERE / 'build/live-image-v3-id/identity.json',
    HERE / 'build/integration-v3/manifest.json', HERE / 'build/integrated-codec-v3/manifest.json',
    HERE / 'build/review-gate-v4.json', HERE / 'verify-audio-return-v4.ps1',
    ROOT / 'outputs/rk3568-audio-package-20261005/build/sealed-production-v4-r2/receipt.json',
    ROOT / 'outputs/rk3568-audio-package-20261005/build/audit-root-v4/receipt.json',
    Path(__file__).resolve(),
]:
    evidence(path)

result = {
    'finite_trial_completed': True,
    'full_audio_adaptation_completed': False,
    'initial_idle_verified_without_diagnostic': True,
    'CPU_v11_close_regression_passed': True,
    'CPU_v12_initial_idle_regression_passed': True,
    'mode': 'RAM_ONLY_NOT_FLASH_READY',
    'board_now': 'original_Android_verified_at_receipt_timestamp',
    'checks': checks, 'evidence': files, 'snapshots': snapshots, 'streams': streams,
    'scope': 'Native3 manual exclusive single-thread session; sequential directions; S16_LE 48k 2ch 256x4; each direction 24576 frames; Playback/MIC/Resume OFF; capture statistics only',
    'measurement_limits': [
        'STOP reports prior driver MMIO readback, not fresh guard MMIO',
        'Playback raw contains one merged partial line; only 94 WRITE lines are completely identifiable, so per-operation I/O trace is incomplete',
        'Playback transfer summary counts submitted frames; DROP was used, not full acoustic drain',
        'Initial Android serial IPv4 line interleaved; failed raw kept and independent ADB identity/SHA used',
        'Actual kernel notes identify this build; no full live RAM Image SHA was measured',
        'Single-thread FD scan and two observations are not an atomic all-thread claim',
    ],
    'not_verified': [
        'Simultaneous full-duplex and product concurrent clients',
        'Acoustic playback and microphone quality',
        'Display hardware', 'poweroff physical rails and MCU ACK',
        'Formal early boot/flash and USB recovery', 'New battery calibration and charging',
    ],
    'restart_window': window,
}
OUT.mkdir()
(OUT / 'result.json').write_bytes((json.dumps(result, indent=2, ensure_ascii=False) + '\n').encode('utf-8'))
print(json.dumps({'checks_passed': len(checks), 'evidence_files': len(files),
                  'finite_trial_completed': True, 'initial_idle_verified_without_diagnostic': True,
                  'full_audio_adaptation_completed': False}))
