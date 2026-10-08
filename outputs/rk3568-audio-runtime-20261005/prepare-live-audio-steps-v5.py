#!/usr/bin/env python3
"""Prepare separate reviewed console steps or validate exported peer logs offline."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
from types import ModuleType

BASE = Path(__file__).resolve().parent
OUT = BASE / 'build/live-audio-v5'
GUARD = '/tmp/audio/audio-session-guard-v4'
GUARD_SHA = '8740384398313be87a13245e854d6fc5a17a10f3794bdd83966e933c894c6f69'
TRANSFER = '/tmp/audio/pcm-transfer'
TRANSFER_SHA = '2a6c765bd9c3c25b3456e60d68670231e81dcaf7781b827559cd701beed09e2e'
PEER = '/tmp/audio/pcm-peer-idle'
PEER_SHA = '7693a052b6318ec3e965451fcb94609e97cb48e693715b847b62032cc684e661'
PEER_SOURCE_SHA = '4edc171fd8bb57c10d844bbfdfa72f83dd090de3f96f143bab8459fd7e22c8d2'
CPU = '/sys/bus/platform/devices/fe410000.i2s'
DMA = '/sys/bus/amba/devices/fe550000.dmac'
CLK = '/tmp/audio-debug/clk'
CARD = 1
POLICY_SHA = '23431a6b7647531ddd54474c6723a2bb6a77b7d105f2ef2dd6fc9d4f0448775c'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_policy(path=None):
    path = Path(path) if path is not None else BASE / 'prepare-audio-board-trial-v5.py'
    root = BASE.parents[1]
    require(path.is_relative_to(root) and '..' not in path.parts and stat.S_ISREG(path.lstat().st_mode),
            'Ordinary fixed board policy required')
    ancestor = path.parent
    while True:
        require(stat.S_ISDIR(ancestor.lstat().st_mode), 'Nonordinary policy ancestor')
        if ancestor == root:
            break
        ancestor = ancestor.parent
    payload = path.read_bytes()
    require(hashlib.sha256(payload).hexdigest() == POLICY_SHA, 'Reviewed primary policy full SHA changed before execution')
    module = ModuleType('reviewed_board_v5_policy')
    module.__file__ = str(path)
    exec(compile(payload, str(path), 'exec'), module.__dict__)
    return module


def expected_operation_names(open_first, close_first):
    require(open_first in ['playback', 'capture'] and close_first in ['playback', 'capture'], 'Explicit known direction required')
    opened = 'p' if open_first == 'playback' else 'c'
    closed = 'p' if close_first == 'playback' else 'c'
    peer = 'c' if closed == 'p' else 'p'
    result = ['empty-action', 'action', 'empty-unblock', 'add', 'unblock', 'alarm5',
              'ctl-open', 'ctl-stat', 'card-info', 'ctl-close']
    for stream in [opened, 'c' if opened == 'p' else 'p']:
        result += [stream + '-' + suffix for suffix in ['open', 'stat', 'version', 'info', 'full', 'exact', 'params', 'setup']]
    result += [closed + '-free', closed + '-open-state', closed + '-close', peer + '-peer-setup',
               peer + '-free', peer + '-open-state', peer + '-close', 'alarm0']
    return result


def validate_peer_output(stdout, stderr, exit_bytes, open_first, close_first):
    require(isinstance(stdout, bytes) and len(stdout) <= 16384, 'Bounded original stdout bytes required')
    require(stderr == b'' and exit_bytes == b'0\n', 'Original empty stderr and exact independent process exit0 required')
    try:
        lines = stdout.decode('ascii').splitlines()
    except UnicodeError as error:
        raise ValueError('Peer output is not ASCII') from error
    require(len(lines) == 35 and lines[-1] == 'PCM_PEER_IDLE_VERIFIED_NO_START', 'Complete 34 rows and real helper success marker required')
    pattern = re.compile(r'PCM_PEER_OP seq=(\d+) name=([a-z0-9-]+) rc=(-?\d+) errno=(\d+) state=(-?\d+) appl_ptr=(\d+) hw_ptr=(\d+)')
    names = expected_operation_names(open_first, close_first)
    records = []
    for index, (line, wanted) in enumerate(zip(lines[:-1], names), 1):
        match = pattern.fullmatch(line)
        require(match is not None, 'Partial or unknown peer operation row')
        seq, name, rc, error, state, appl, hw = match.groups()
        seq, rc, error, state, appl, hw = map(int, [seq, rc, error, state, appl, hw])
        require(seq == index and name == wanted, 'Peer operation sequence/name changed')
        require(error == 0 and appl == hw == 0, 'Peer error or stricter zero-pointer observation not satisfied')
        require(-(1 << 63) <= rc < (1 << 63), 'Peer rc exceeded actual long long representation')
        if name.endswith('-open') or name in ['alarm5', 'alarm0']:
            require(rc >= 0, 'Open FD/alarm remaining-seconds must be nonnegative')
        else:
            require(rc == 0, 'Unexpected nonzero successful ioctl/stat/close/signal return')
        wanted_state = 1 if name.endswith('setup') else 0 if name.endswith('open-state') else -1
        require(state == wanted_state, 'Peer state differs from actual configure/free sequence')
        records.append({'seq': seq, 'name': name, 'rc': rc, 'errno': error, 'state': state, 'appl_ptr': appl, 'hw_ptr': hw})
    return {'complete_operations': 34, 'process_exit': 0, 'first_error': None,
            'real_helper_success_marker_present': True, 'records': records,
            'open_first': open_first, 'close_first': close_first,
            'OPEN_zero_pointer_is_stricter_observation_than_helper_state_only_contract': True,
            'scope': 'Exported userspace records only; root must also accept kernel diagnostics and strict pre/post guard'}


def result_command(label, program, identity, arguments, peer=False):
    prefix = '/tmp/audio/' + label
    marker = label.upper().replace('-', '_') + '_EXIT_0'
    command = (
        f'if test ! -e {prefix}.stdout && test ! -L {prefix}.stdout && '
        f'test ! -e {prefix}.stderr && test ! -L {prefix}.stderr && '
        f'test ! -e {prefix}.exit && test ! -L {prefix}.exit && '
        f'test "$(sha256sum {program})" = \'{identity}  {program}\'; then '
        f'{program} {arguments} > {prefix}.stdout 2> {prefix}.stderr; '
        f'audio_rc=$?; printf "%s\\n" "$audio_rc" > {prefix}.exit; '
        f'cat {prefix}.stdout; cat {prefix}.stderr; ')
    success = 'test "$audio_rc" = 0'
    if peer:
        success += (f' && test ! -s {prefix}.stderr && '
            f'test "$(grep -c \'^PCM_PEER_OP \' {prefix}.stdout)" = 34 && '
            f'test "$(wc -l < {prefix}.stdout)" = 35 && '
            f'test "$(grep -cx PCM_PEER_IDLE_VERIFIED_NO_START {prefix}.stdout)" = 1')
    command += success + f' && echo {marker}; else echo AUDIO_FRESH_FILE_OR_IDENTITY_REFUSED; fi'
    return {'command': command, 'wait': 8 if program == TRANSFER else 6 if peer else 5,
            'expect': '(?m)^' + marker + r'\r?$'}


def guard_step(label, stage='bound'):
    args = f'{stage} {CARD} {CPU} {DMA}'
    if stage == 'bound':
        args += ' 2 /tmp/audio/alsa-inspect'
    elif stage == 'card-unbound':
        args += ' 2'
    args += ' ' + CLK
    return result_command(label, GUARD, GUARD_SHA, args)


def build_steps():
    files = {}
    for label, stage in [('pre-playback-v5', 'bound'), ('post-playback-v5', 'bound'),
                         ('pre-capture-v5', 'bound'), ('post-capture-v5', 'bound'),
                         ('card-unbound-v5', 'card-unbound'), ('cpu-unbound-v5', 'cpu-unbound')]:
        files[label] = [guard_step(label, stage)]
    for stream in ['playback', 'capture']:
        label = stream + '-bounded-v5'
        args = f'--card-id rockchiprk809co --stream {stream} --frames 24576 --timeout-ms 5000'
        files[label] = [result_command(label, TRANSFER, TRANSFER_SHA, args)]
    for first in ['playback', 'capture']:
        for close in ['playback', 'capture']:
            label = 'peer-idle-open-' + first + '-close-' + close + '-v5'
            files['pre-' + label] = [guard_step('pre-' + label)]
            files[label] = [result_command(label, PEER, PEER_SHA,
                f'--card {CARD} --open-first {first} --close-first {close}', peer=True)]
            files['post-' + label] = [guard_step('post-' + label)]
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board-input-manifest-sha256')
    parser.add_argument('--verify-peer-stdout', type=Path)
    parser.add_argument('--peer-stderr', type=Path)
    parser.add_argument('--peer-exit', type=Path)
    parser.add_argument('--open-first', choices=['playback', 'capture'])
    parser.add_argument('--close-first', choices=['playback', 'capture'])
    args = parser.parse_args()
    if args.verify_peer_stdout:
        require(all([args.peer_stderr, args.peer_exit, args.open_first, args.close_first]) and
                args.board_input_manifest_sha256 is None, 'Only explicit complete offline peer log verification arguments required')
        for p in [args.verify_peer_stdout, args.peer_stderr, args.peer_exit]:
            require(p.is_file() and not p.is_symlink(), 'Ordinary exported original peer files required')
        result = validate_peer_output(args.verify_peer_stdout.read_bytes(), args.peer_stderr.read_bytes(), args.peer_exit.read_bytes(),
                                      args.open_first, args.close_first)
        print(json.dumps(result))
        return
    require(args.board_input_manifest_sha256 is not None and not any([args.peer_stderr, args.peer_exit, args.open_first, args.close_first]),
            'Explicit actual board preparation SHA required for generation')
    policy = load_policy()
    board = policy.read_json(BASE / 'build/board-audio-v5/input-manifest.json', policy.digest(args.board_input_manifest_sha256))
    policy.validate_false_flags(board, ['board_tested', 'start_allowed', 'battery_algorithm_enabled', 'usb_peripheral_enabled', 'early_emmc_candidate_included'])
    require(board['guard_binary_sha256'] == GUARD_SHA and board['peer_binary_sha256'] == PEER_SHA and
            board['image_sha256'] == policy.IMAGE_SHA and board['codec_manifest_sha256'] == policy.CODEC_MANIFEST_SHA,
            'Actual new board/runtime identity changed')
    peer_source = policy.ordinary(BASE / 'pcm-peer-idle-v1/pcm-peer-idle.c')
    require(sha(peer_source) == PEER_SOURCE_SHA, 'Actual operation-name source changed')
    require(not OUT.exists() and not OUT.is_symlink(), 'Fresh live-audio-v5 output required')
    files = build_steps()
    for steps in files.values():
        for item in steps:
            policy.step(item['command'], item.get('expect'), item['wait'])
    OUT.mkdir()
    for name, steps in files.items():
        with (OUT / (name + '.json')).open('xb') as stream:
            stream.write((json.dumps(steps, indent=2) + '\n').encode('ascii'))
    cases = []
    for first in ['playback', 'capture']:
        for close in ['playback', 'capture']:
            label = 'peer-idle-open-' + first + '-close-' + close + '-v5'
            cases.append({'open_first': first, 'close_first': close,
                'ordered_files': ['pre-' + label + '.json', label + '.json', 'post-' + label + '.json'],
                'expected_operations': expected_operation_names(first, close), 'expected_original_stdout_lines': 35,
                'stdout': '/tmp/audio/' + label + '.stdout', 'stderr': '/tmp/audio/' + label + '.stderr',
                'exit': '/tmp/audio/' + label + '.exit'})
    proof = {'prepared_only': True, 'board_tested': False, 'start_allowed': False, 'helper_command_files': len(files),
        'board_input_manifest_sha256': args.board_input_manifest_sha256, 'tool_sha256': sha(Path(__file__)),
        'board_input_policy_sha256': sha(BASE / 'prepare-audio-board-trial-v5.py'),
        'peer_source_sha256': PEER_SOURCE_SHA, 'peer_binary_sha256': PEER_SHA, 'guard_version': 4, 'card': CARD,
        'cases': cases, 'files_sha256': {name + '.json': sha(OUT / (name + '.json')) for name in files},
        'each_file_is_independent_root_must_accept_diagnostics_before_next': True,
        'peer_has_no_PREPARE_START_or_audio_IO': True,
        'single_direction_transfers_only_after_all_four_peer_cases_and_root_gate': True,
        'SIGALRM_not_bound_for_D_state_or_stdout_after_alarm0': True,
        'OPEN_zero_pointer_is_stricter_observation_not_automatic_helper_violation': True,
        'remaining_dual_START_and_joint_STOP_reds_not_closed': True}
    with (OUT / 'preparation.json').open('xb') as stream:
        stream.write((json.dumps(proof, indent=2) + '\n').encode())
    print(json.dumps({'command_files': len(files), 'preparation_sha256': sha(OUT / 'preparation.json'),
                      'board_tested': False, 'start_allowed': False}))


if __name__ == '__main__':
    main()
