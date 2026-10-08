#!/usr/bin/env python3
"""Fresh root compilation/execution of frozen, byte-bound production models."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FROZEN = HERE / 'cpu-lifecycle-v11'
OUT = HERE / 'build/cpu-v11-root-reexecution-v1'
OUT.mkdir(exist_ok=False)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(FROZEN / 'frozen-output-manifest.json') == '7d36c8f14369b6b88ffbbc700a9b35c3d30a23d98eadd9cee88affa658a20a88'
inventory = json.loads((FROZEN / 'frozen-output-manifest.json').read_text())['files_sha256']
for name, expected in inventory.items():
    path = FROZEN / name
    assert path.resolve().is_relative_to(FROZEN) and sha(path) == expected, name
assert len(inventory) == 2249
sys.path.insert(0, str(FROZEN))
from source_utils import function
new_source = (FROZEN / 'source/sound/soc/rockchip/rockchip_i2s_tdm.c').read_text()
old_source = (ROOT / '.deps/kernel-source/aiot-3568pq-audio-v1/sound/soc/rockchip/rockchip_i2s_tdm.c').read_text()
assert sha(FROZEN / 'source/sound/soc/rockchip/rockchip_i2s_tdm.c') == '87779ff23367aaaac07e8c980ee98dbdf59a93318e3a2782c52bdb011eb4417c'
result = {'passed': False, 'board_tested': False, 'fresh_compilation': True,
          'inventory_files_checked': len(inventory), 'runs': {}, 'evidence_sha256': {}}

for model, total, red in [('shutdown-red-v10', 4, True), ('shutdown-green-v11', 48, False), ('params-regression-v11', 140, False)]:
    model_dir = FROZEN / model
    authored = json.loads((model_dir / 'result.json').read_text())
    source = old_source if red else new_source
    extracted = (model_dir / 'actual-cpu-functions.c').read_text()
    for name, expected in authored['cpu_functions_sha256'].items():
        body = function(source, name)
        assert hashlib.sha256(body.encode()).hexdigest() == expected and body in extracted, name
    if not model.startswith('params'):
        callers = (model_dir / 'actual-caller-functions.c').read_text()
        for name, relative in [
            ('rk817_set_dai_sysclk', 'sound/soc/codecs/rk817_codec.c'),
            ('snd_soc_dai_set_sysclk', 'sound/soc/soc-dai.c'),
            *[(n, 'sound/soc/generic/simple-card-utils.c') for n in ['asoc_simple_clk_disable', 'asoc_simple_shutdown', 'asoc_simple_set_clk_rate', 'asoc_simple_hw_params']],
        ]:
            body = function((ROOT / '.deps/kernel-source/aiot-3568pq-audio-v1' / relative).read_text(), name)
            assert hashlib.sha256(body.encode()).hexdigest() == authored['caller_functions_sha256'][name] and body in callers, name
    run_dir = OUT / model
    run_dir.mkdir()
    result['runs'][model] = {}
    for mode, compiler, flags, prefix in [
        ('host', 'gcc', [], []),
        ('asan-ubsan', 'gcc', ['-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie'], []),
        ('aarch64-qemu', 'aarch64-linux-gnu-gcc', ['-static'], [str(ROOT / '.deps/qemu-user/root/usr/bin/qemu-aarch64-static')]),
    ]:
        binary = run_dir / ('model-' + mode)
        argv = [compiler, '-std=gnu11', '-O0', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-unused-function', '-pthread', *flags, str(model_dir / 'unit.c'), '-o', str(binary)]
        compiled = subprocess.run(argv, capture_output=True, timeout=60)
        for channel in ['stdout', 'stderr']:
            (run_dir / (mode + '-compile.' + channel)).write_bytes(getattr(compiled, channel))
        assert compiled.returncode == 0, compiled.stderr.decode(errors='replace')
        executed = subprocess.run(prefix + [str(binary)] + (['red-v10'] if red else []), capture_output=True, timeout=60)
        for channel in ['stdout', 'stderr']:
            (run_dir / (mode + '.' + channel)).write_bytes(getattr(executed, channel))
        tests = json.loads(executed.stdout.splitlines()[-1])
        assert tests == {'total': total, 'passed': total - int(red)}, (model, mode, tests)
        assert executed.returncode == int(red) and not executed.stderr, (model, mode)
        assert executed.stdout == (model_dir / (mode + '.stdout')).read_bytes()
        result['runs'][model][mode] = {'compile_argv': argv, 'exit_code': executed.returncode, 'tests': tests, 'expected_red': red}
    print(model + ': actual production bodies and three fresh compile/runtime environments verified', flush=True)
result['passed'] = True
for path in OUT.rglob('*'):
    if path.is_file():
        result['evidence_sha256'][path.relative_to(OUT).as_posix()] = sha(path)
(OUT / 'result.json').write_bytes((json.dumps(result, indent=2) + '\n').encode())
print('CPU_V11_ROOT_FRESH_RECOMPILE_VERIFIED', flush=True)
