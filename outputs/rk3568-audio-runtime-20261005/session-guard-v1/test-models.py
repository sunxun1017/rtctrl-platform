#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Actual C parsers in synthetic fixtures; no device access, not board evidence."""
from pathlib import Path
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
QEMU = ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    out = HERE / 'models'
    out.mkdir(exist_ok=False)
    fixtures = out / 'fixtures'
    fixtures.mkdir()
    cpu = 'version=1 ready=1 error=0 owners=0 open=0 stop_proven=1 stop_reads=3 irq_live=0 irq_drained=1 mclk_leases=0 hclk_lease=1 configuring=0 power_transition=0 shutting_down=0\n'
    dma = 'version=1 ready=1 error=0 stop_proven=1 stop_reads=8 pm_usage=0 leases=0 software=0 queued=0 descriptors=0 allocated=2\n'
    names = ['i2s1_mclkout_rx', 'clk_i2s1_8ch_rx_src', 'clk_i2s1_8ch_rx',
             'mclk_i2s1_8ch_rx', 'clk_i2s1_8ch_rx_frac', 'clk_i2s1_8ch_tx_src',
             'clk_i2s1_8ch_tx_frac', 'clk_i2s1_8ch_tx', 'mclk_i2s1_8ch_tx',
             'i2s1_mclkout_tx', 'i2s1_mclk_tx_ioe', 'i2s1_mclkout', 'hclk_i2s1_8ch',
             'i2s1_mclkin_tx', 'i2s1_mclkin_rx', 'i2s1_mclk_rx_ioe']
    clocks = ''.join(f'{name} enable={int(name.startswith("hclk_"))} prepare={int(name.startswith("hclk_"))} protect=0\n' for name in names)
    inspect = ('ALSA_CARD card=1 id=rockchiprk809co controls=3\n'
               'ALSA_LIST numid=1 iface=2 device=0 subdevice=0 index=0 name=Playback Path\n'
               'ALSA_LIST numid=2 iface=2 device=0 subdevice=0 index=0 name=Capture MIC Path\n'
               'ALSA_LIST numid=3 iface=2 device=0 subdevice=0 index=0 name=Resume Path\n'
               'ALSA_CONTROL numid=1 name=Playback Path items=11 value=0 label=OFF\n'
               'ALSA_CONTROL numid=2 name=Capture MIC Path items=4 value=0 label=MIC OFF\n'
               'ALSA_CONTROL numid=3 name=Resume Path items=2 value=0 label=OFF\n'
               'ALSA_CODEC_INTERFACE_VERIFIED\n')
    cases = []

    def add(name, kind, content, expected=False, argument=1, second=None):
        first = fixtures / (name + '.txt')
        first.write_bytes(content.encode())
        last = '-'
        if second is not None:
            other = fixtures / (name + '-second.txt')
            other.write_bytes(second.encode())
            last = str(other)
        cases.append({'name': name, 'kind': kind, 'argument': argument,
                      'file': str(first), 'extra': last, 'expected': expected})

    for kind, good, argument in [('cpu', cpu, 1), ('dma', dma, 2)]:
        add(kind + '-valid', kind, good, True, argument)
        words = good.strip().split(' ')
        for index, word in enumerate(words):
            key, value = word.split('=')
            mutations = {'missing': words[:index] + words[index + 1:],
                         'duplicate': words[:index] + [word] + words[index:],
                         'unknown': words[:index] + ['unknown=' + value] + words[index + 1:]}
            for label, mutated in mutations.items():
                add(f'{kind}-{key}-{label}', kind, ' '.join(mutated) + '\n', argument=argument)
            for bad in ['-5', '-0', '+0', '00', '18446744073709551616', '1x', '', 'errno=-5']:
                changed = list(words)
                changed[index] = key + '=' + bad
                add(f'{kind}-{key}-syntax-{len(cases)}', kind, ' '.join(changed) + '\n', argument=argument)
            if key != 'stop_reads':
                changed = list(words)
                changed[index] = key + '=' + str(int(value) + 1)
                add(f'{kind}-{key}-unsafe', kind, ' '.join(changed) + '\n', argument=argument)
        for label, bad in [('no-lf', good.rstrip()), ('double-lf', good + '\n'),
                           ('extra', good.rstrip() + ' injected=1\n'), ('crlf', good.replace('\n', '\r\n')),
                           ('leading', ' ' + good), ('double-space', good.replace(' ', '  ', 1)),
                           ('diagnostic', 'errno=-11\n' + good)]:
            add(kind + '-' + label, kind, bad, argument=argument)
        add(kind + '-stop-reads-zero', kind, good.replace('stop_reads=3', 'stop_reads=0').replace('stop_reads=8', 'stop_reads=0'), argument=argument)
    add('cpu-bound-hclk-required', 'cpu', cpu.replace('hclk_lease=1', 'hclk_lease=0'))
    add('dma-held-channels-allowed', 'dma', dma, True, 2)
    add('dma-no-guessed-allocated', 'dma', dma, False, 0)
    add('dma-zero-after-unregister', 'dma', dma.replace('allocated=2', 'allocated=0'), True, 0)
    for content in ['1\n', '0', '00\n', '0\n0\n', 'errno=-5\n', '-1\n', '0 \n']:
        add('quarantine-bad-' + str(len(cases)), 'quarantine', content)
    add('quarantine-zero', 'quarantine', '0\n', True)
    add('stable-good', 'stable', cpu, True, second=cpu)
    add('stable-stop-count-changed', 'stable', cpu, second=cpu.replace('stop_reads=3', 'stop_reads=4'))
    add('stable-allocated-changed', 'stable', dma, second=dma.replace('allocated=2', 'allocated=1'))
    add('stable-process-changed', 'stable', '1:3\n10:99\n', second='1:3\n11:100\n')
    add('inspect-valid', 'inspect', inspect, True)
    for label, bad in [('resume-on', inspect.replace('value=0 label=OFF\nALSA_CODEC', 'value=1 label=ON\nALSA_CODEC')),
                       ('playback-on', inspect.replace('label=OFF', 'label=Speaker', 1)),
                       ('mic-on', inspect.replace('label=MIC OFF', 'label=Main Mic')),
                       ('missing-resume', inspect.replace('ALSA_CONTROL numid=3 name=Resume Path items=2 value=0 label=OFF\n', '')),
                       ('duplicate', inspect.replace('ALSA_CODEC', 'ALSA_CONTROL numid=3 name=Resume Path items=2 value=0 label=OFF\nALSA_CODEC')),
                       ('wrong-card', inspect.replace('card=1', 'card=2')),
                       ('wrong-id', inspect.replace('rockchiprk809co', 'unknown')),
                       ('unknown-line', inspect + 'extra\n'), ('errno', inspect + 'errno=-5\n'),
                       ('enum-out-of-range', inspect.replace('items=2 value=0', 'items=2 value=2')),
                       ('negative-zero', inspect.replace('device=0', 'device=-0', 1)),
                       ('missing-lf', inspect.rstrip()), ('crlf', inspect.replace('\n', '\r\n')),
                       ('duplicate-list-id', inspect.replace('numid=2 iface', 'numid=1 iface')),
                       ('wrong-target-iface', inspect.replace('iface=2', 'iface=3', 1)),
                       ('list-device-nonzero', inspect.replace('device=0', 'device=1', 1))]:
        add('inspect-' + label, 'inspect', bad)
    add('clocks-bound-good', 'clocks', clocks, True)
    add('clocks-unbound-good', 'clocks', clocks.replace('enable=1 prepare=1', 'enable=0 prepare=0'), True, 0)
    for name in names:
        rows = clocks.splitlines(keepends=True)
        row = next(x for x in rows if x.startswith(name + ' '))
        for label, bad in [('missing', clocks.replace(row, '')), ('duplicate', clocks + row),
                           ('unknown', clocks.replace(name + ' ', 'unknown ')),
                           ('protect', clocks.replace(row, row.replace('protect=0', 'protect=1'))),
                           ('bad-lease', clocks.replace(row, row.replace('enable=0', 'enable=1') if 'enable=0' in row else row.replace('enable=1', 'enable=0')))]:
            add('clocks-' + name + '-' + label, 'clocks', bad)
    for label, content, expected in [
            ('sound-alias', '1 116 30 /run/hardlink\n', False),
            ('oss', '1 14 3 /dev/dsp\n', False),
            ('sound-deleted', '1 116 31 /dev/snd/deleted\n', False),
            ('mem', '1 1 1 /run/memory-alias\n', False),
            ('kmem', '1 1 2 /dev/kmem\n', False),
            ('uio', '1 247 0 /dev/uio0\n', False),
            ('null', '1 1 3 /dev/null\n', True),
            ('tty', '1 4 64 /dev/ttyS0\n', True),
            ('ram-log', '0 0 0 /run/audio/log\n', True)]:
        add('fd-' + label, 'fd', content, expected)

    listing = out / 'cases.txt'
    listing.write_text(''.join(f'{c["name"]} {c["kind"]} {c["argument"]} {c["file"]} {c["extra"]}\n' for c in cases))
    evidence = []
    for target, compiler, flags, prefix in [
            ('host', 'gcc', ['-O2'], []),
            ('asan-ubsan', 'gcc', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer'], []),
            ('aarch64-qemu', 'aarch64-linux-gnu-gcc', ['-O2', '-static'], [str(QEMU)])]:
        binary = out / ('model-' + target)
        argv = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-fno-ident',
                *flags, str(HERE / 'model-driver.c'), '-o', str(binary)]
        built = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        (out / (target + '-compile.stdout')).write_text(built.stdout)
        (out / (target + '-compile.stderr')).write_text(built.stderr)
        if built.returncode:
            raise RuntimeError(built.stderr)
        result = subprocess.run(prefix + [str(binary), str(listing)], capture_output=True, text=True, timeout=60)
        (out / (target + '.stdout')).write_text(result.stdout)
        (out / (target + '.stderr')).write_text(result.stderr)
        actual = dict(line.split(' ') for line in result.stdout.splitlines())
        failures = [c['name'] for c in cases if actual.get(c['name']) != str(int(c['expected']))]
        evidence.append({'target': target, 'cases': len(cases), 'passed': len(cases) - len(failures),
                         'failures': failures, 'exit': result.returncode, 'compile_argv': argv,
                         'binary_sha256': sha(binary)})
        if result.returncode or failures:
            (out / 'result.json').write_text(json.dumps({'model_only': True, 'board_tested': False,
                                                        'targets': evidence}, indent=2) + '\n')
            raise RuntimeError(f'{target}: {failures}; stderr={result.stderr}')
    (out / 'result.json').write_text(json.dumps({'model_only': True, 'board_tested': False,
                                                'parser_sha256': sha(HERE / 'guard-parser.h'),
                                                'source_sha256': sha(HERE / 'model-driver.c'),
                                                'test_sha256': sha(Path(__file__)),
                                                'targets': evidence}, indent=2) + '\n')
    print(json.dumps({'model_only': True, 'board_tested': False, 'cases_per_target': len(cases),
                      'targets': [{k: e[k] for k in ('target', 'passed', 'cases')} for e in evidence]}))


if __name__ == '__main__':
    main()
