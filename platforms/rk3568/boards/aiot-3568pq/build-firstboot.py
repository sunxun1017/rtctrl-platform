#!/usr/bin/env python3
"""Compile/audit this board's offline DTB candidate without modifying the kernel."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--dtc', required=True)
    parser.add_argument('--cpp', default='gcc')
    args = parser.parse_args()
    board = Path(__file__).resolve().parent
    source = args.kernel.resolve(strict=True)
    output = args.output.resolve()
    candidate = json.loads((board/'firstboot-candidate.json').read_text())
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != candidate['source_commit']:
        parser.error('Kernel commit differs from firstboot-candidate.json')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        parser.error('Kernel source must be clean, including untracked files')
    if output == source or output.is_relative_to(source):
        parser.error('Output must be outside the kernel source tree')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error('Output must be new or empty; previous evidence is never overwritten')
    dtc = shutil.which(args.dtc)
    cpp = shutil.which(args.cpp)
    if not dtc or not cpp:
        parser.error('DTC and C preprocessor must already be available')
    output.mkdir(parents=True, exist_ok=True)
    commands = []
    command_lines = []

    def run(argv, stdout_name, stderr_name):
        commands.append(argv)
        command_lines.append(shlex.join(argv) + ' > ' + shlex.quote(str(output/stdout_name))
                             + ' 2> ' + shlex.quote(str(output/stderr_name)))
        with (output/stdout_name).open('wb') as out, (output/stderr_name).open('wb') as err:
            result = subprocess.run(argv, stdout=out, stderr=err)
        (output/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        (output/'commands.sh').write_text('\n'.join(command_lines)+'\n')
        if result.returncode:
            raise RuntimeError(f'Command failed ({result.returncode}); see {output/stderr_name}')

    include = source/'arch/arm64/boot/dts/rockchip'
    preprocess = [cpp, '-E', '-P', '-nostdinc', '-undef', '-D__DTS__', '-x', 'assembler-with-cpp',
                  '-I', str(include), '-I', str(source/'include')]
    dts = board/'bsp/rk3568-aiot-3568pq-firstboot.dts'
    dtb = output/'rk3568-aiot-3568pq-firstboot.dtb'
    run(preprocess + [str(dts)], 'firstboot.pp.dts', 'preprocess.log')
    run([dtc, '-@', '-I', 'dts', '-O', 'dtb', '-o', str(dtb), str(output/'firstboot.pp.dts')],
        'compile.stdout', 'dtc.log')
    run([dtc, '-I', 'dtb', '-O', 'dts', str(dtb)], 'firstboot.compiled.dts', 'decompile.log')
    run([sys.executable, str(board/'verify-firstboot.py'), str(dtb)], 'audit.json', 'audit.log')

    # SoC include references the board-owned vdd_logic label even while the
    # video decoder is disabled. Supply a label-only stub for this warning
    # baseline, never for the actual candidate.
    (output/'soc-baseline.dts').write_text('/dts-v1/;\n#include "rk3568.dtsi"\n'
                                         '/ { vdd_logic: baseline-only-supply {}; };\n')
    run(preprocess + [str(output/'soc-baseline.dts')], 'soc-baseline.pp.dts', 'baseline-preprocess.log')
    run([dtc, '-@', '-I', 'dts', '-O', 'dtb', '-o', str(output/'soc-baseline.dtb'),
         str(output/'soc-baseline.pp.dts')], 'baseline.stdout', 'baseline-dtc.log')

    def warnings(path):
        return {line.split('Warning ', 1)[1] for line in path.read_text().splitlines() if 'Warning ' in line}

    new_warnings = sorted(warnings(output/'dtc.log') - warnings(output/'baseline-dtc.log'))
    if new_warnings:
        raise RuntimeError('New board DTC warnings require review: ' + repr(new_warnings))

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = {'schema': 1, 'kernel_commit': commit, 'deployable': False, 'board_boot_tested': False,
                'image_built': False, 'modules_built': False, 'dtb': dtb.name,
                'dtb_sha256': digest(dtb), 'new_board_warnings': new_warnings,
                'dtc_version': subprocess.check_output([dtc, '--version'], text=True).strip(),
                'sources': {p.name: digest(p) for p in [dts, board/'bsp/rk3568-aiot-3568pq-power.dtsi',
                                                       board/'firstboot.cfg', board/'firstboot-candidate.json',
                                                       board/'verify-firstboot.py', Path(__file__)]}}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'DTB compiled and audited; non-deployable manifest: {output / "manifest.json"}')


if __name__ == '__main__':
    main()
