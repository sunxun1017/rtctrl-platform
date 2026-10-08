#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Redirect mature v11 models and Kbuild to fresh v12 paths, keeping inputs."""
from pathlib import Path
import difflib
import json
from source_utils import replace, sha

HERE = Path(__file__).resolve().parent
PRIOR = HERE / 'inputs/outputs/rk3568-audio-runtime-20261005/cpu-lifecycle-v11'


def main():
    before = (PRIOR / 'test-sysclk-shutdown.py').read_text()
    runner = replace(before,
        "KERNEL_COPY = HERE / 'inputs/.deps/kernel-source/aiot-3568pq-audio-v1'",
        "FIXTURE = HERE / 'inputs/outputs/rk3568-audio-runtime-20261005/cpu-lifecycle-v11/inputs'\n"
        "KERNEL_COPY = FIXTURE / '.deps/kernel-source/aiot-3568pq-audio-v1'")
    runner = runner.replace("HERE / 'inputs/outputs/rk3568-i2s-lifecycle-20261005", "FIXTURE / 'outputs/rk3568-i2s-lifecycle-20261005")
    runner = runner.replace("'params-regression-v11'", "'params-regression-v12'").replace("'shutdown-green-v11'", "'shutdown-green-v12'")
    runner = replace(runner, "    output.mkdir(exist_ok=False)\n",
        "    output.mkdir(exist_ok=False)\n    (output / 'runner-snapshot.py').write_bytes(Path(__file__).read_bytes())\n")
    (HERE / 'test-v11-regression.py').write_text(runner)
    for name in ['test-sysclk-main.c', 'simple-model-glue.h']:
        (HERE / name).write_bytes((PRIOR / name).read_bytes())
    before_build = (PRIOR / 'build-object.py').read_text()
    build = before_build.replace('aiot-3568pq-audio-v1', 'aiot-3568pq-audio-v2').replace("'kbuild-object-v1'", "'kbuild-object-v2'")
    (HERE / 'build-object.py').write_text(build)
    output = HERE / 'verification-tools'
    output.mkdir(exist_ok=False)
    for name, prior, current in [('v11-model-paths.patch', before, runner), ('v11-kbuild-paths.patch', before_build, build)]:
        (output / name).write_text(''.join(difflib.unified_diff(prior.splitlines(keepends=True), current.splitlines(keepends=True),
                                                             fromfile='prior', tofile='v12')))
    (output / 'receipt.json').write_text(json.dumps({
        'model_runner_sha256': sha((HERE / 'test-v11-regression.py').read_bytes()),
        'build_object_sha256': sha((HERE / 'build-object.py').read_bytes()),
        'model_glue_and_checks_byte_exact_v11': True,
        'changes': 'Only fixture/output paths and executed runner snapshot; production Kbuild paths now actual integrated v2.',
        'board_accessed': False
    }, indent=2) + '\n')
    print('Prepared fresh v12 regression and private object tools')


if __name__ == '__main__':
    main()
