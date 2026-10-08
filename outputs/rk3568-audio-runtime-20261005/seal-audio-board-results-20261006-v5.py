#!/usr/bin/env python3
"""Validate an explicit captured trial offline; never interact with any device."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
from types import ModuleType

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREP = HERE / 'build/board-results-v5-tool-preparation'
BOARD_SHA = '0f46ce3496f96c4e28346c6a36cb84f4289be9f16d5909735b3d14cafe6a9517'
LIVE_SHA = '5e94f6f1b29441f848aa44fe8f6d9733245376ef35e7ef3cfcd3b48c0c6b6cda'
PARSER_SHA = '80baf3482cb90e7fd5d78b9ef3ff064c50e6cdede7991e63a3d328de06bba85b'
IMAGE_SHA = '48b9958d36e2b4821235520360530faac38c9f2dae072c2a2602dbda7e048595'
NOTES_SHA = 'a2008d938402984c29c007a3e2bb229d862776d35ed1bfc3f0246a34650b6436'
NOTES_HEX = '040000001400000003000000474e550051e22386ae723cd9247a05f17f2b8a668c0de9070600000001000000000100004c696e757800000000000000'
CODEC_SHA = 'aa594a46d660c929cdae71f81024659cf9f4beca032baf9a193ad6ded3476171'
PACKAGE_SEAL_SHA = '0178b39488d658e9c1be116c950978cba8feb96cc56ddd501b8c70df7b69ea18'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def ordinary(path, limit=64 * 1024 * 1024):
    path = Path(path)
    require(path.is_relative_to(ROOT), 'Workspace ordinary path required')
    current = ROOT
    require(stat.S_ISDIR(current.lstat().st_mode), 'Ordinary workspace root')
    for component in path.relative_to(ROOT).parts[:-1]:
        require(component not in ['', '.', '..'], 'Canonical path')
        current /= component
        require(stat.S_ISDIR(current.lstat().st_mode), 'Ordinary ancestor')
    require(stat.S_ISREG(path.lstat().st_mode) and path.stat().st_size <= limit, 'Bounded ordinary file')
    return path.read_bytes()


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def load_peer_parser():
    source = HERE / 'prepare-live-audio-steps-v5.py'
    payload = ordinary(source)
    require(sha(payload) == PARSER_SHA, 'Actual peer parser identity before execution')
    module = ModuleType('locked_actual_v5_peer_parser')
    module.__file__ = str(source)
    exec(compile(payload, str(source), 'exec'), module.__dict__)
    return module


def decode_hex_chunks(board, length, transfer_raws):
    require(isinstance(transfer_raws, list) and all(isinstance(raw, bytes) for raw in transfer_raws),
            'Independent transfer raw files required')
    expected = {offset: min(1024, length - offset) for offset in range(0, length, 1024)}
    accepted = {}
    complete_copies = 0
    partial_attempts = []
    begin_prefix = 'AUDIO_EXPORT_CHUNK path=' + board + ' '
    end_prefix = 'AUDIO_EXPORT_CHUNK_END path=' + board + ' '
    header = re.compile(re.escape(begin_prefix) + r'offset=(\d+) bytes=(\d+) encoding=hex')
    for raw_index, raw in enumerate(transfer_raws):
        # Each attempt is independently framed in one raw; never concatenate fragments.
        rows = raw.decode('ascii').replace('\r', '').splitlines()
        index = 0
        while index < len(rows):
            if not rows[index].startswith(begin_prefix):
                index += 1
                continue
            match = header.fullmatch(rows[index])
            require(match is not None, 'Exact captured hex header required')
            offset, size = map(int, match.groups())
            require(offset in expected and size == expected[offset], 'Exact finite 1024-byte chunk offset/size')
            start = index
            index += 1
            payload = []
            while index < len(rows) and not rows[index].startswith((begin_prefix, end_prefix)):
                payload.append(rows[index])
                index += 1
            complete_end = index < len(rows) and rows[index] == end_prefix + 'offset=' + str(offset)
            valid = complete_end and len(payload) == (size + 15) // 16
            encoded = []
            if valid:
                for row_index, row in enumerate(payload):
                    width = min(16, size - row_index * 16) * 2
                    # BusyBox/host hexdump pads only the final short row to 32 columns.
                    if not re.fullmatch('[0-9a-f]{' + str(width) + '}(?:' +
                                        (' {' + str(32 - width) + '}' if width < 32 else '(?!)') + ')?', row):
                        valid = False
                        break
                    encoded.append(row[:width])
            if valid:
                data = bytes.fromhex(''.join(encoded))
                require(offset not in accepted or accepted[offset] == data, 'Conflicting complete original-file retransmission')
                accepted[offset] = data
                complete_copies += 1
            else:
                partial_attempts.append({'raw_index': raw_index, 'line': start + 1, 'offset': offset,
                                         'complete_matching_end': complete_end,
                                         'reason': 'Incomplete or malformed attempt; requires independent complete retransmission'})
            if index < len(rows) and rows[index].startswith(end_prefix):
                index += 1
    require(set(accepted) == set(expected), 'Complete independent chunk coverage required; re-export missing original-file blocks')
    return b''.join(accepted[offset] for offset in sorted(expected)), {
        'encoding': 'hex', 'chunk_bytes': 1024, 'unique_complete_chunks': len(accepted),
        'complete_copies': complete_copies, 'partial_attempts': partial_attempts,
        'empty_file_requires_no_payload': length == 0, 'cross_raw_fragments_combined': False}


def check_export_bytes(descriptor, host, metadata, transfer_raws):
    board = descriptor['board_path']
    require(isinstance(board, str) and re.fullmatch(r'/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+', board) and
            not set(board.split('/')) & {'.', '..'}, 'Canonical explicit board file path')
    require(type(descriptor['bytes']) is int and 0 <= descriptor['bytes'] <= 64 * 1024 * 1024 and
            re.fullmatch('[0-9a-f]{64}', descriptor['sha256']), 'Bounded explicit full original file identity')
    require(len(host) == descriptor['bytes'] and sha(host) == descriptor['sha256'], 'Host original bytes equal board identity')
    text = metadata.decode('ascii').replace('\r', '')
    sizes = re.findall(r'^AUDIO_BOARD_FILE bytes=(\d+) path=' + re.escape(board) + '$', text, re.M)
    hashes = re.findall(r'^([0-9a-f]{64})  ' + re.escape(board) + '$', text, re.M)
    require(sizes and set(sizes) == {str(len(host))} and hashes and set(hashes) == {sha(host)},
            'Independent captured board stat/full SHA match original host bytes')
    actual, transport = decode_hex_chunks(board, len(host), transfer_raws)
    require(actual == host, 'Complete independent transferred bytes equal host original')
    return {'bytes': len(host), 'sha256': sha(host), 'board_path': board,
            'board_stat_and_full_SHA_matched': True, 'independent_transfer_bytes_matched': True,
            'partial_bytes_reconstructed': False, 'transport': transport}


def check_dmesg(before, after):
    require(before and before.endswith(b'\n') and after.endswith(b'\n') and after.startswith(before),
            'Complete same-boot dmesg baseline retained without ring truncation')
    new = after[len(before):].decode('ascii')
    require(not re.search(r'WARNING:|BUG:|Call trace:|Kernel panic|ASoC: error|audio_runtime_error|pl330[^\n]*error', new),
            'No new serious or audio lifecycle kernel diagnostic')
    return {'before_bytes': len(before), 'after_bytes': len(after), 'new_lines': len(new.splitlines()),
            'complete_baseline_prefix_preserved': True, 'new_window': new,
            'scope': 'Exact exported kernel log files; not the serial command echoes'}


CLOCK_NAMES = {
    'i2s1_mclkout_rx', 'clk_i2s1_8ch_rx_src', 'clk_i2s1_8ch_rx', 'mclk_i2s1_8ch_rx', 'clk_i2s1_8ch_rx_frac',
    'clk_i2s1_8ch_tx_src', 'clk_i2s1_8ch_tx_frac', 'clk_i2s1_8ch_tx', 'mclk_i2s1_8ch_tx', 'i2s1_mclkout_tx',
    'i2s1_mclk_tx_ioe', 'i2s1_mclkout', 'hclk_i2s1_8ch', 'i2s1_mclkin_tx', 'i2s1_mclkin_rx', 'i2s1_mclk_rx_ioe'}
CODEC_PARENTS = {'clk_i2s1_8ch_tx_src': 'gpll', 'clk_i2s1_8ch_tx_frac': 'clk_i2s1_8ch_tx_src',
                 'clk_i2s1_8ch_tx': 'clk_i2s1_8ch_tx_frac', 'mclk_i2s1_8ch_tx': 'clk_i2s1_8ch_tx',
                 'i2s1_mclkout_tx': 'mclk_i2s1_8ch_tx', 'i2s1_mclkout': 'i2s1_mclkout_tx'}


def only_line(text, prefix):
    rows = re.findall('^' + re.escape(prefix) + '(.*)$', text, re.M)
    require(len(rows) == 1, 'Exactly one complete line: ' + prefix)
    return rows[0]


def block(text, name):
    require(len(re.findall('^' + name + '_BEGIN$', text, re.M)) == 1 and
            len(re.findall('^' + name + '_END$', text, re.M)) == 1, 'Complete unique report block: ' + name)
    match = re.search('^' + name + '_BEGIN\n(.*?)^' + name + '_END$', text, re.M | re.S)
    require(match is not None, 'Ordered complete report block: ' + name)
    return match.group(1)


def numeric_fields(row, expected):
    tokens = row.split()
    require(all(re.fullmatch(r'[a-z_]+=-?\d+', item) for item in tokens), 'Complete cached-state numeric fields')
    fields = dict((key, int(value)) for key, value in (item.split('=') for item in tokens))
    require(len(fields) == len(tokens) and set(fields) == set(expected), 'Exact unique cached-state keys')
    for key, value in expected.items():
        require(fields[key] == value, 'Cached state ' + key)
    return fields


def parse_guard(blob, stage):
    require(stage in ['bound', 'card-unbound', 'cpu-unbound'], 'Exact guard stage')
    text = blob.decode('ascii').replace('\r', '')
    allocated = 0 if stage == 'cpu-unbound' else 2
    cpu_row = only_line(text, 'AUDIO_CPU ')
    if stage == 'cpu-unbound':
        require(cpu_row == 'CPU_COMPONENT_UNBOUND', 'CPU component is normally unbound')
        cpu = {'component_unbound': True}
    else:
        expected = {'version': 1, 'ready': 1, 'error': 0, 'owners': 0, 'open': 0, 'stop_proven': 1,
                    'irq_live': 0, 'irq_drained': 1, 'mclk_leases': 0, 'hclk_lease': 1,
                    'configuring': 0, 'power_transition': 0, 'shutting_down': 0}
        reads = re.search(r'(?:^| )stop_reads=(\d+)(?: |$)', cpu_row)
        require(reads is not None and int(reads.group(1)) >= 2, 'CPU prior STOP readbacks complete')
        cpu = numeric_fields(cpu_row, {**expected, 'stop_reads': int(reads.group(1))})
    dma_row = only_line(text, 'AUDIO_DMA ')
    reads = re.search(r'(?:^| )stop_reads=(\d+)(?: |$)', dma_row)
    require(reads is not None and int(reads.group(1)) >= 2, 'DMA prior STOP readbacks complete')
    dma = numeric_fields(dma_row, {'version': 1, 'ready': 1, 'error': 0, 'stop_proven': 1,
                                  'stop_reads': int(reads.group(1)), 'pm_usage': 0, 'leases': 0,
                                  'software': 0, 'queued': 0, 'descriptors': 0, 'allocated': allocated})
    require(only_line(text, 'AUDIO_QUARANTINE ') == '0', 'Zero quarantine')
    processes = block(text, 'AUDIO_PROCESSES').splitlines()
    require(processes and all(re.fullmatch(r'\d+:\d+', row) for row in processes) and len(processes) == len(set(processes)),
            'Complete unique guard process snapshot')
    registrations = block(text, 'AUDIO_CHARACTER_REGISTRATIONS')
    require(registrations and only_line(text, 'AUDIO_UIO_REGISTRATION ').startswith('present='), 'Complete registration report')
    rows = block(text, 'AUDIO_CLOCKS').splitlines()
    clocks = {}
    for row in rows:
        match = re.fullmatch(r'([a-z0-9_]+) enable=(\d+) prepare=(\d+) protect=(\d+)', row)
        require(match is not None and match[1] not in clocks, 'Complete unique clock count row')
        clocks[match[1]] = tuple(map(int, match.groups()[1:]))
    require(set(clocks) == CLOCK_NAMES, 'Exact sixteen cached clock rows')
    for name, count in clocks.items():
        wanted = int((stage == 'bound' and name in CODEC_PARENTS) or (stage != 'cpu-unbound' and name == 'hclk_i2s1_8ch'))
        require(count == (wanted, wanted, 0), 'Exact stage clock profile: ' + name)
    parents = {}
    for row in block(text, 'AUDIO_CODEC_CLOCK_PARENTS').splitlines():
        match = re.fullmatch(r'([a-z0-9_]+) parent=([a-z0-9_]+)', row)
        require(match is not None and match[1] not in parents, 'Complete unique codec cached-parent row')
        parents[match[1]] = match[2]
    require(parents == CODEC_PARENTS, 'Exact frozen six-node codec baseline cached parent chain')
    if stage == 'bound':
        require(only_line(text, 'ALSA_CARD ') == 'card=1 id=rockchiprk809co controls=3', 'Exact ALSA card and controls')
        for numid, tail in [(1, 'name=Playback Path items=11 value=0 label=OFF'),
                            (2, 'name=Capture MIC Path items=4 value=0 label=MIC OFF'),
                            (3, 'name=Resume Path items=2 value=0 label=OFF')]:
            require(only_line(text, f'ALSA_CONTROL numid={numid} ') == tail, 'Complete codec three OFF cached observations')
        require(only_line(text, 'ALSA_CODEC_INTERFACE_VERIFIED') == '', 'Complete codec inspector success')
    require(only_line(text, 'AUDIO_SESSION_IDLE_VERIFIED ') ==
            f'stage={stage} allocated={allocated} board_start_permission=0 reboot_permission=0', 'Strict collector-only guard success')
    return {'stage': stage, 'CPU': cpu, 'DMA': dma, 'clock_counts': clocks, 'codec_cached_parents': parents,
            'guard_reports_prior_MMIO_not_fresh_MMIO': True,
            'process_snapshot_not_an_atomic_all_thread_claim': True, 'START_authorized_by_guard': False}


def parse_stream(stdout, trace, exit_code, stream):
    require(stream in ['playback', 'capture'] and exit_code == b'0\n', 'Exact direction and independent process exit0')
    require(stdout.endswith(b'\n') and trace.endswith(b'\n') and len(stdout) <= 4096 and len(trace) <= 65536,
            'Complete bounded original stream stdout and stderr')
    output = stdout.decode('ascii').splitlines()
    require(len(output) == 2 and output[1] == 'PCM_BOUNDED_IO_COMPLETE_GUARD_STILL_REQUIRED', 'Exact finite summary and guard-required marker')
    match = re.fullmatch(r'PCM_TRANSFER card=1 stream=' + stream +
                        r' frames=24576 samples=(\d+) zeros=(\d+) zero_ppm=(\d+) observed_hw_ptr=(\d+)', output[0])
    require(match is not None, 'Complete fixed stream summary')
    samples, zeros, ppm, observed_hw = map(int, match.groups())
    require((samples, zeros, ppm) == ((49152, 49152, 1000000) if stream == 'capture' else (0, 0, 0)) and observed_hw >= 256,
            'OFF-path statistics and bounded hardware-progress observation')
    rows = trace.decode('ascii').splitlines()
    index = 0
    states = {}
    io_calls = 0
    retry_calls = 0

    def take(pattern, message):
        nonlocal index
        require(index < len(rows), 'Complete trace prefix: ' + message)
        result = re.fullmatch(pattern, rows[index])
        require(result is not None, 'Exact stream operation order: ' + message)
        index += 1
        return result

    def stage(name):
        take('PCM_STAGE name=' + name + ' rc=0 errno=0', name)

    def state(name, number, pointers=None):
        stage(name)
        result = take('PCM_STATE stage=' + name + ' state=' + str(number) + r' appl_ptr=(\d+) hw_ptr=(\d+)', name + ' state')
        value = tuple(map(int, result.groups()))
        require(pointers is None or value == pointers, 'Expected stream pointers: ' + name)
        states[name] = {'state': number, 'appl_ptr': value[0], 'hw_ptr': value[1]}
        return value

    selected_control_seen = False
    for card in range(32):
        result = take('PCM_STAGE name=OPEN_CONTROL card=' + str(card) + r' rc=(-?\d+) errno=(\d+)', 'discovery card ' + str(card))
        ret, error = map(int, result.groups())
        if ret < 0:
            require(ret == -1 and error in [2, 19], 'Only absent control ENOENT/ENODEV may be skipped')
        else:
            require(error == 0, 'Successful control open errno0')
            for name in ['CONTROL_NODE', 'CARD_INFO', 'CLOSE_CONTROL']:
                stage(name)
            selected_control_seen |= card == 1
    require(selected_control_seen, 'Selected card1 was actually opened during complete discovery')
    result = take(r'PCM_STAGE name=OPEN_PCM rc=(\d+) errno=0', 'OPEN_PCM')
    for name in ['PCM_NODE', 'PVERSION', 'PCM_INFO']:
        stage(name)
    take('PCM_INFO card=1 device=0 subdevice=0 stream=' + stream +
         r' id=fe410000\.i2s-rk817-hifi rk817-hifi-0', 'PCM identity')
    for name in ['HW_REFINE_CAPS', 'HW_REFINE_EXACT', 'HW_PARAMS']:
        stage(name)
    state('STATUS_SETUP', 1, (0, 0))
    stage('SW_PARAMS')
    stage('PREPARE')
    state('STATUS_PREPARED', 2, (0, 0))
    direction = 'READ' if stream == 'capture' else 'WRITE'

    def transfer_until(next_stage, required_bytes):
        nonlocal index, io_calls, retry_calls
        transferred = 0
        while index < len(rows) and not rows[index].startswith('PCM_STAGE name=' + next_stage + ' '):
            poll = re.fullmatch(r'PCM_STAGE name=POLL rc=(-?\d+) errno=(\d+) timeout_ms=(\d+)', rows[index])
            io = re.fullmatch('PCM_STAGE name=' + direction + r' rc=(-?\d+) errno=(\d+) requested_bytes=(\d+)', rows[index])
            require(poll is not None or io is not None, 'Complete finite I/O/poll trace only')
            ret, error, requested = map(int, (poll or io).groups())
            if poll:
                require(0 < requested <= 10000 and ((ret in [0, 1] and error == 0) or (ret == -1 and error == 4)),
                        'Poll result0/1 or retry EINTR within timeout')
            else:
                require(0 < requested <= 1024 and requested % 4 == 0, 'Aligned bounded S16_LE stereo I/O request')
                require((0 < ret <= requested and ret % 4 == 0 and error == 0) or (ret == -1 and error in [4, 11]),
                        'Aligned successful I/O or retry EINTR/EAGAIN')
                if ret > 0:
                    transferred += ret
                    io_calls += 1
                else:
                    retry_calls += 1
            index += 1
        require(transferred == required_bytes, 'Complete per-operation byte sum equals bounded frame count')

    if stream == 'playback':
        transfer_until('STATUS_PREFILLED', 1024 * 4)
        state('STATUS_PREFILLED', 2, (1024, 0))
    stage('START')
    state('STATUS_STARTED', 3)
    transfer_until('STATUS_TRANSFERRED', (24576 - (1024 if stream == 'playback' else 0)) * 4)
    state('STATUS_TRANSFERRED', 3, (24576, observed_hw))
    stage('DROP')
    state('STATUS_DROPPED', 1)
    stage('HW_FREE')
    state('STATUS_FREED', 0, (0, 0))
    stage('CLOSE_PCM')
    require(index == len(rows), 'No extra, incomplete, repeated or first-error trace after normal close')
    return {'stream': stream, 'frames': 24576, 'transferred_bytes': 24576 * 4, 'successful_IO_calls': io_calls,
            'IO_retry_calls': retry_calls, 'summary': output[0], 'states': states,
            'START_count': 1, 'DROP_count': 1, 'HW_FREE_count': 1, 'CLOSE_count': 1,
            'capture_MIC_OFF_statistics_not_microphone_acceptance': stream == 'capture',
            'submitted_frames_not_acoustic_drain': True, 'stderr_is_complete_operation_trace': True}


def parse_initial_idle(blob):
    text = blob.decode('ascii').replace('\r', '')
    row = only_line(text, 'version=1 ready=1 error=0 owners=0 open=0 stop_proven=1 stop_reads=')
    require(row == '2 irq_live=0 irq_drained=1 mclk_leases=0 hclk_lease=1 configuring=0 power_transition=0 shutting_down=0',
            'Natural initial CPU STOP2/drained/no-owned-MCLK/idle state')
    require(re.search(r'^suspended$', text, re.M), 'Natural initial runtime-suspended observation')
    for marker in ['AUDIO_V5_IMAGE_AND_GUARD_ID_VERIFIED', 'AUDIO_CODEC_MODULE_INSERTED', 'AUDIO_V5_CARD1_BOTH_PCM_PRESENT']:
        require(only_line(text, marker) == '', 'Initial codec/card identity marker')
    require('power/control' not in text, 'No PM diagnostic toggle in initial observation')
    return {'natural_initial_runtime_suspended': True, 'STOP_reads': 2, 'owned_MCLK_leases': 0,
            'live_IRQ': False, 'IRQ_drained': True, 'observed_before_PCM_programs': True,
            'limited_to_explicit_captured_operator_workflow': True}


def parse_android_return(receipt, board):
    require(receipt.get('completed') is True and all(receipt.get(key) is False for key in
            ['partition_write', 'flash', 'saveenv', 'network_configuration_changed']), 'Fresh protected Android return receipt')
    commands = receipt.get('commands')
    require(isinstance(commands, list) and len(commands) >= 3, 'Independent original Android commands required')
    require(commands[0]['output'] == '0\n4.19.232\n11\n1' and commands[0]['exit_code'] == 0, 'Fresh root/original Android/kernel/boot count')
    for index, key, count in [(1, 'protected_sha256', 7), (2, 'native_cached_sha256', 3)]:
        require(len(board[key]) == count and commands[index]['output'] == '\n'.join(board[key]) and
                commands[index]['exit_code'] == 0, 'Original Android full protected SHA set: ' + key)
    return {'completed': True, 'protected_files': 7, 'native_cached_files': 3,
            'partition_write': False, 'flash': False, 'saveenv': False, 'network_configuration_changed': False,
            'original_Android_verified_at_receipt_timestamp_only': True}


class CapturedEvidence:
    def __init__(self):
        self.files = {}
        self.payloads = {}

    def read(self, relative, expected=None):
        require(isinstance(relative, str) and '\\' not in relative and not relative.startswith('/') and
                all(part not in ['', '.', '..'] for part in relative.split('/')), 'Repository-relative canonical evidence path')
        data = ordinary(ROOT / relative)
        require(expected is None or re.fullmatch('[0-9a-f]{64}', expected) and sha(data) == expected, 'Explicit evidence full SHA: ' + relative)
        require(relative not in self.payloads or self.payloads[relative] == data, 'Evidence unchanged between reads')
        self.payloads[relative] = data
        self.files[relative] = {'bytes': len(data), 'sha256': sha(data)}
        return data

    def reference(self, ref):
        require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'Exact explicit path/SHA reference')
        return self.read(ref['path'], ref['sha256'])

    def export(self, entry, expected_board=None):
        require(isinstance(entry, dict) and set(entry) == {'board_path', 'host_path', 'bytes', 'sha256',
                'metadata_raw_path', 'transfer_raw_paths'}, 'Exact original-board-file export descriptor')
        require(expected_board is None or entry['board_path'] == expected_board, 'Original board path matches prepared command')
        require(entry['host_path'].startswith('outputs/rk3568-audio-runtime-20261005/build/board-exports-v5/'),
                'Actual own original-export host location required')
        host = self.read(entry['host_path'], entry['sha256'])
        metadata_paths = entry['metadata_raw_path']
        if isinstance(metadata_paths, str):
            metadata_paths = [metadata_paths]
        require(isinstance(metadata_paths, list) and metadata_paths, 'Independent metadata raw paths required')
        metadata = b''.join(self.read(relative) for relative in metadata_paths)
        require(isinstance(entry['transfer_raw_paths'], list), 'Independent transfer raw path list required')
        transfers = [self.read(relative) for relative in entry['transfer_raw_paths']]
        proof = check_export_bytes(entry, host, metadata, transfers)
        return host, proof

    def final_readback(self):
        for relative, payload in self.payloads.items():
            require(ordinary(ROOT / relative) == payload, 'Every input unchanged at final readback: ' + relative)


def collect_trial(inputs, evidence):
    require(isinstance(inputs, dict) and set(inputs) == {'schema', 'exports', 'raw_files', 'fdt_root_review',
            'fdt_independent_review', 'android_return_receipt', 'additional_evidence'}, 'Exact explicit captured-trial input schema')
    require(inputs['schema'] == 'RK3568_AUDIO_BOARD_V5_CAPTURE_INPUTS', 'Captured v5 trial schema')
    board = json.loads(evidence.read('outputs/rk3568-audio-runtime-20261005/build/board-audio-v5/input-manifest.json', BOARD_SHA))
    live = json.loads(evidence.read('outputs/rk3568-audio-runtime-20261005/build/live-audio-v5/preparation.json', LIVE_SHA))
    require(board['image_sha256'] == IMAGE_SHA and board['notes_sha256'] == NOTES_SHA and
            board['sealed_package_receipt_sha256'] == PACKAGE_SEAL_SHA and board['host_verified'] is True and
            board['mode'] == 'RAM_ONLY_NOT_FLASH_READY', 'Pinned actual prepared package/Image/notes identity')
    require(all(board.get(key) is False for key in ['board_tested', 'start_allowed', 'battery_algorithm_enabled',
                'usb_peripheral_enabled', 'early_emmc_candidate_included']), 'Prepared inputs do not authorize START or unsupported hardware')
    require(live['board_input_manifest_sha256'] == BOARD_SHA and live['tool_sha256'] == PARSER_SHA and
            live['peer_binary_sha256'] == board['peer_binary_sha256'] and len(live['cases']) == 4, 'Pinned four-case live preparation')
    for item in board['files']:
        data = evidence.read(item['source'], item['sha256'])
        require(len(data) == item['bytes'], 'Actual staged source length: ' + item['name'])
    evidence.read('outputs/rk3568-audio-package-20261005/build/sealed-production-v5/receipt.json', PACKAGE_SEAL_SHA)
    for relative, expected in [
        ('outputs/rk3568-audio-runtime-20261005/build/integration-v4/manifest.json', board['image_manifest_sha256']),
        ('outputs/rk3568-audio-runtime-20261005/codec-image-v4-v1/build-v2/manifest.json', board['codec_manifest_sha256']),
        ('outputs/rk3568-audio-runtime-20261005/build/live-image-v4-id/identity.json', board['notes_identity_sha256']),
        ('outputs/rk3568-audio-runtime-20261005/prepare-live-audio-steps-v5.py', PARSER_SHA),
    ]:
        evidence.read(relative, expected)
    peer_parser = load_peer_parser()
    peers = {}
    guard_stages = {}
    for case in live['cases']:
        first, close = case['open_first'], case['close_first']
        label = 'peer-idle-open-' + first + '-close-' + close + '-v5'
        require(case['expected_operations'] == peer_parser.expected_operation_names(first, close) and
                case['ordered_files'] == [name + '.json' for name in ['pre-' + label, label, 'post-' + label]],
                'Prepared four peer orders and actual operation set')
        peers[label] = case
        guard_stages['pre-' + label] = guard_stages['post-' + label] = 'bound'
    for name in ['pre-playback-v5', 'post-playback-v5', 'pre-capture-v5', 'post-capture-v5']:
        guard_stages[name] = 'bound'
    guard_stages['card-unbound-v5'] = 'card-unbound'
    guard_stages['cpu-unbound-v5'] = 'cpu-unbound'
    programs = set(peers) | set(guard_stages) | {'playback-bounded-v5', 'capture-bounded-v5'}
    expected_exports = {label + '.' + ext for label in programs for ext in ['stdout', 'stderr', 'exit']} | {'dmesg-before', 'dmesg-after', 'live.dtb'}
    require(isinstance(inputs['exports'], dict) and set(inputs['exports']) == {'files'} and
            set(inputs['exports']['files']) == expected_exports, 'Exact twenty programs and dmesg/FDT original exported-file set')
    exports = {}
    proofs = {}
    for key, entry in inputs['exports']['files'].items():
        board_path = '/tmp/audio/' + key if key not in ['dmesg-before', 'dmesg-after', 'live.dtb'] else None
        if key == 'live.dtb':
            board_path = '/sys/firmware/fdt'
        if key in ['dmesg-before', 'dmesg-after']:
            require(entry['board_path'].startswith('/tmp/audio/'), 'Original captured same-boot dmesg file')
        exports[key], proofs[key] = evidence.export(entry, board_path)
    snapshots = {}
    for label, stage in guard_stages.items():
        require(exports[label + '.stderr'] == b'' and exports[label + '.exit'] == b'0\n', 'Strict guard empty stderr/independent exit0: ' + label)
        snapshots[label] = parse_guard(exports[label + '.stdout'], stage)
    peer_results = {}
    for label, case in peers.items():
        peer_results[label] = peer_parser.validate_peer_output(exports[label + '.stdout'], exports[label + '.stderr'],
                exports[label + '.exit'], case['open_first'], case['close_first'])
    stream_results = {stream: parse_stream(exports[stream + '-bounded-v5.stdout'], exports[stream + '-bounded-v5.stderr'],
                    exports[stream + '-bounded-v5.exit'], stream) for stream in ['playback', 'capture']}
    dmesg = check_dmesg(exports['dmesg-before'], exports['dmesg-after'])
    raw_required = {'copy-aux', 'codec-observation', 'live-image-identity', 'unbind-card', 'unload-codec', 'unbind-cpu',
                    'unmount-audio-debug', 'pre-native-return', 'native-return-check', 'native-tests', 'native-return',
                    'native-reboot', 'first-peer-wrapper-failed', 'first-peer-post-recovery'}
    require(raw_required <= set(inputs['raw_files']), 'Explicit identity, ordinary teardown/return and preserved wrapper-failure raw evidence')
    raw = {label: evidence.reference(ref).decode('ascii').replace('\r', '') for label, ref in inputs['raw_files'].items()}
    markers = {'copy-aux': 'AUDIO_PACKAGE_V5_RAM_AUX_VERIFIED_NO_MODULE_OR_START',
        'unbind-card': 'AUDIO_NORMAL_CARD_UNBOUND', 'unload-codec': 'AUDIO_NORMAL_CODEC_UNLOADED',
        'unbind-cpu': 'AUDIO_NORMAL_CPU_UNBOUND', 'unmount-audio-debug': 'AUDIO_DEBUGFS_NORMAL_UNMOUNTED',
        'pre-native-return': 'AUDIO_PRE_NATIVE_RETURN_ZERO_QUARANTINE', 'native-return-check': 'PID1_INDEPENDENT_RAM_ONLY_RETURN_READY'}
    for label, marker in markers.items():
        require(only_line(raw[label], marker) == '', 'Normal workflow marker: ' + marker)
    initial = parse_initial_idle(raw['codec-observation'].encode())
    notes = raw['live-image-identity']
    require(only_line(notes, NOTES_SHA + '  /sys/kernel/notes') == '' and NOTES_HEX in notes,
            'Actual full 60-byte kernel notes build identity, not live RAM Image SHA')
    require('sh: wc: not found' in raw['first-peer-wrapper-failed'] and
            re.search(r'^PCM_PEER_IDLE_VERIFIED_NO_START$', raw['first-peer-wrapper-failed'], re.M) and
            not re.search(r'^PEER_IDLE_OPEN_PLAYBACK_CLOSE_PLAYBACK_V5_EXIT_0$', raw['first-peer-wrapper-failed'], re.M),
            'Preserved first program success followed by missing-wc console-wrapper failure')
    require(re.search(r'^POST_PEER_IDLE_OPEN_PLAYBACK_CLOSE_PLAYBACK_V5_EXIT_0$', raw['first-peer-post-recovery'], re.M) and
            not re.search(r'^PCM_PEER_OP ', raw['first-peer-post-recovery'], re.M), 'Recovery only postguard/metadata; peer not replayed in recovery')
    for test in ['codec', 'pty']:
        require(only_line(raw['native-tests'], f'SOFTWARE_TEST_PASSED path=/usr/bin/{test}-test exit=0') == '', 'Fresh native software test')
    require(only_line(raw['native-return'], 'PID1_STATUS phase=4 loop=0 owned=1 forward=63 backward=63 pivot=1 old_unmounted=1 loop_detached=1 cache_unmounted=1') == '',
            'Normal native RAM return/cache loop detached')
    restart = raw['native-reboot']
    begin = restart.index('\nNORMAL_REBOOT_REQUESTED_DEVICE_SHUTDOWN\n')
    end = restart.index('\nDDR ', begin)
    window = restart[begin:end]
    require('reboot: Restarting system' in window and 'sysrq' not in window.lower() and
            not re.search(r'WARNING:|BUG:|Call trace:|Kernel panic', window), 'Normal device-shutdown restart without serious trace')
    for label, text in raw.items():
        require('power/control' not in text, 'No captured PM diagnostic toggle: ' + label)
        require('ASoC: error at snd_soc_dai_set_sysclk on fe410000.i2s: -22' not in text, 'Prior close diagnostic absent: ' + label)
    fdt_root = json.loads(evidence.reference(inputs['fdt_root_review']))
    fdt_independent = json.loads(evidence.reference(inputs['fdt_independent_review']))
    fdt_sha = sha(exports['live.dtb'])
    require(len(exports['live.dtb']) == 168064 and fdt_root['live_sha256'] == fdt_independent['live_sha256'] == fdt_sha and
            fdt_root['nodes'] == fdt_independent['nodes'] == 962 and fdt_root['phandles'] == fdt_independent['unique_phandles'] == 762 and
            len(fdt_root['full_property_changes_from_baseline']) == fdt_independent['baseline_fixups'] == 31 and
            fdt_root['full_live_semantics_equal_previous'] is True and
            fdt_independent['full_header_property_node_phandle_reservation_equal_previous_v4'] is True and
            fdt_independent['independent_readonly_review_completed'] is True and fdt_independent['board_START_authorized'] is False,
            'Current complete live FDT and independent semantic review')
    for relative, expected in fdt_independent['inputs'].items():
        evidence.read(relative, expected)
    android = parse_android_return(json.loads(evidence.reference(inputs['android_return_receipt'])), board)
    require(isinstance(inputs['additional_evidence'], list), 'Explicit preserved attempts and preparation receipts')
    for ref in inputs['additional_evidence']:
        evidence.reference(ref)
    return {'finite_trial_completed': True, 'full_audio_adaptation_completed': False,
        'mode': 'RAM_ONLY_NOT_FLASH_READY', 'board_now': 'original_Android_verified_at_receipt_timestamp',
        'scope': 'Four no-START two-open/two-HW_PARAMS peer idle orders and sequential original single-direction regressions; three codec controls OFF',
        'initial_idle': initial, 'strict_guards': snapshots, 'strict_guard_count': len(snapshots),
        'peer_no_START_cases': peer_results, 'peer_case_count': len(peer_results), 'streams': stream_results,
        'dmesg': dmesg, 'export_proofs': proofs, 'Android_return': android,
        'first_wrapper_failure': {'reason': 'Board wc applet absent after program returned0',
            'original_failure_preserved': True, 'program_original_stdout_stderr_exit_verified': True,
            'post_guard_observed_in_separate_recovery': True, 'console_wrapper_success_claimed': False},
        'live_fdt_sha256': fdt_sha, 'notes_sha256': NOTES_SHA, 'restart_window': window,
        'measurement_limits': ['STOP is prior driver readback; guard does not issue fresh MMIO',
            'FD/process snapshots are not atomic across all threads', 'Kernel notes identify the build; no full live RAM Image SHA measured',
            'Single-direction frames are submitted/captured bytes; DROP is not complete acoustic drain',
            'Peer SIGALRM bounds interruptible waits; D-state and stdout after alarm cancellation remain outside the timer',
            'No-PM-diagnostic conclusion is limited to explicitly captured operator workflow'],
        'not_verified': ['Simultaneous full-duplex or product concurrent clients', 'Physical sound or microphone quality',
            'Display hardware', 'Formal flash/early boot/USB recovery', 'New battery calibration/charging', 'Complete Android-to-Linux migration']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial-inputs', required=True)
    parser.add_argument('--trial-inputs-sha256', required=True)
    parser.add_argument('--out', default='board-results-20261006-v5')
    args = parser.parse_args()
    require(re.fullmatch('[a-z0-9-]{1,90}', args.out), 'Fresh owned result directory name')
    output = HERE / 'build' / args.out
    require(not output.exists() and not output.is_symlink(), 'Fresh formal result directory')
    evidence = CapturedEvidence()
    evidence.read(Path(__file__).relative_to(ROOT).as_posix())
    input_blob = evidence.read(args.trial_inputs, args.trial_inputs_sha256)
    result = collect_trial(json.loads(input_blob), evidence)
    evidence.final_readback()
    result['evidence'] = evidence.files
    result['evidence_files'] = len(evidence.files)
    result['trial_inputs_sha256'] = sha(input_blob)
    result['collector_sha256'] = sha(ordinary(Path(__file__)))
    result['freeze_scope'] = 'Collector/result bytes and explicit external SHA references; original exported files/raws stay at their unchanged paths'
    encoded = (json.dumps(result, indent=2, ensure_ascii=False) + '\n').encode()
    output.mkdir(exist_ok=False)
    (output / 'collector.py').write_bytes(ordinary(Path(__file__)))
    (output / 'trial-inputs.json').write_bytes(input_blob)
    (output / 'result.json').write_bytes(encoded)
    files = {name: sha(ordinary(output / name)) for name in ['collector.py', 'trial-inputs.json', 'result.json']}
    (output / 'SHA256SUMS').write_text(''.join(value + '  ' + name + '\n' for name, value in sorted(files.items())))
    print(json.dumps({'finite_trial_completed': True, 'full_audio_adaptation_completed': False,
        'strict_guards': result['strict_guard_count'], 'peer_no_START_cases': result['peer_case_count'],
        'evidence_files': len(evidence.files), 'result_sha256': files['result.json'], 'scope': result['scope']}))


if __name__ == '__main__':
    main()
