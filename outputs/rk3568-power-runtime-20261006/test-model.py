#!/usr/bin/env python3
"""Compile byte-identical production functions inside dependency wrappers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
ENV = dict(os.environ)
ENV['PATH'] = str(HERE.parents[1] / '.deps/host-tools/bin') + ':' + ENV['PATH']

def block(source, signature):
    found = re.search(signature, source, re.MULTILINE)
    if not found:
        raise ValueError('missing production unit: ' + signature)
    start = found.start()
    opening = source.index('{', found.end())
    level = 1
    i = opening + 1
    while level:
        level += (source[i] == '{') - (source[i] == '}')
        i += 1
    end = source.index(';', i) + 1 if signature.startswith('struct ') else i
    return source[start:end]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--candidate', action='store_true')
    args = ap.parse_args()
    source_path = HERE / args.source
    text = source_path.read_text()
    output = HERE / args.output
    output.mkdir(parents=True, exist_ok=False)
    structure = [block(text, r'struct battery_platform_data\s*'), block(text, r'struct rk817_battery_device\s*')]
    funcs = ['rk817_bat_parse_dt', 'rk817_bat_field_read', 'rk817_bat_field_write', 'rk817_bat_get_coffset', 'rk817_bat_set_coffset', 'rk817_bat_get_ioffset', 'rk817_bat_current_calibration', 'rk817_bat_get_vaclib0', 'rk817_bat_get_vaclib1', 'rk817_bat_init_voltage_kb', 'rk817_bat_init_caltimer', 'rk817_bat_init_fg', 'rk817_get_rtc_sec', 'rk817_bat_rtc_sleep_sec',
             'rk817_battery_work', 'rk817_bat_caltimer_isr', 'rk809_plug_in_isr', 'rk809_plug_out_isr', 'rk809_charge_init_irqs',
             'rk817_battery_probe', 'rk817_battery_shutdown', 'rk817_bat_pm_suspend', 'rk817_bat_resume_work', 'rk817_bat_pm_resume', 'rk809_chg_get_property']
    if args.candidate:
        funcs = ['rk817_bat_running', 'rk817_bat_queue_monitor', 'rk817_bat_stop', 'rk817_bat_pause', 'rk817_bat_validate_pdata'] + funcs
        if 'static int rk809_bat_refresh_plug_state(' in text:
            funcs.insert(0,'rk809_bat_refresh_plug_state')
        funcs += ['rk817_battery_remove']
    units = []
    for name in funcs:
        units.append(block(text, r'^static[^\n;{}]*\b' + name + r'\s*\([^;{}]*?\)\s*(?=\{)'))
    prototypes = [unit[:unit.index('{')].strip() + ';' for unit in units]
    generated = ('#define CANDIDATE 1\n' if args.candidate else '')
    generated += '#include "model-support.h"\n' + '\n'.join(structure) + '\n' + '\n'.join(prototypes)
    generated += '\n#include "model-body.h"\n' + '\n\n'.join(units) + '\n#include "model-tests.h"\n'
    wrapper = output / 'wrapper.c'
    wrapper.write_text(generated)
    results = []
    for name, compiler, flags, runner in [
        ('host', 'gcc', ['-O2'], []),
        ('sanitizers', 'gcc', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'], []),
        ('aarch64', 'aarch64-linux-gnu-gcc', ['-O2', '-static'], [str(HERE.parents[1] / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static')]),
    ]:
        binary = output / name
        argv = [compiler, '-std=gnu11', '-Wall', '-Wno-unused-function', '-Wno-unused-parameter', '-Wno-unused-variable', '-I', str(HERE), *flags, str(wrapper), '-o', str(binary)]
        compile_run = subprocess.run(argv, capture_output=True, text=True, env=ENV)
        (output / (name + '-compile.txt')).write_text(compile_run.stdout + compile_run.stderr)
        if compile_run.returncode:
            raise ValueError('model compile failed: ' + name)
        run_argv = runner + [str(binary)]
        result = subprocess.run(run_argv, capture_output=True, text=True, env=ENV)
        (output / (name + '-stdout.txt')).write_text(result.stdout)
        (output / (name + '-stderr.txt')).write_text(result.stderr)
        results.append({'environment': name, 'compile_argv': argv, 'run_argv': run_argv, 'returncode': result.returncode,
                        'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                        'passed': result.stdout.count('PASS '), 'failed': result.stdout.count('FAIL ')})
    (output / 'result.json').write_text(json.dumps({'source_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
        'wrapper_sha256': hashlib.sha256(wrapper.read_bytes()).hexdigest(), 'candidate': args.candidate,
        'units_sha256': {name: hashlib.sha256(unit.encode()).hexdigest() for name,unit in zip(funcs,units)},
        'results': results, 'board_tested': False, 'dependency_model': True}, indent=2) + '\n')
    print(json.dumps(results))

if __name__ == '__main__':
    main()
