#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Add public wrappers around the exact reviewed v11/v12 delta bytes."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNTIME = ROOT / 'outputs/rk3568-audio-runtime-20261005'
PUBLIC = ROOT / 'platforms/rk3568/boards/aiot-3568pq/patches'
CPU = 'sound/soc/rockchip/rockchip_i2s_tdm.c'

SPECS = [
    ('0013-i2s-sysclk-shutdown-reset.patch', 'cpu-lifecycle-v11/source/delta-v10-v11.patch',
     'dd31e7208c71bdc7dac8b41c8d82f9e2702f77c743a80214044d8b28e5422437',
     '''Subject: [PATCH 13/14] ASoC: rockchip: handle simple-card shutdown sysclk reset

The simple-card shutdown callback calls set_sysclk with a zero frequency
after the CPU DAI has closed. The checked lifecycle rejected this legal
cache reset with -EINVAL, causing an ASoC diagnostic after otherwise
successful DROP, HW_FREE and close.

Keep the existing admission gate and require STOP proof, drained IRQs and
no substreams for a zero request. Only reset the shared TRCM cached TX/RX
request under the lock; do not touch clock hardware, PM or codec leases.
Require a new positive request before subsequent checked hw_params.

Base: SDK 9f9e9d18574d0914c0d192a90c3babfe1fd63c95 plus public 0001-0012.
Reviewed delta: cpu-lifecycle-v11/source/delta-v10-v11.patch.
Evidence: outputs/rk3568-audio-runtime-20261005/public-integration-v1/.

'''),
    ('0014-i2s-format-runtime-pm.patch', 'cpu-lifecycle-v12/source/delta-v11-v12.patch',
     '64957ca517417c02dbb7c2a52306bb3020f5b2b730cdf636a0f60fbd950a078c',
     '''Subject: [PATCH 14/14] ASoC: rockchip: hand completed format setup to runtime PM

pm_runtime_put queues asynchronous idle work. A worker running before
set_fmt clears configuring sees -EBUSY from checked runtime suspend;
the PM core does not retry this case. Probe can then remain active with
usage zero and retain its MCLK/IRQ ownership after format setup ends.

Keep configuring asserted for the entire in-flight function. After all
format MMIO ends, latch the first error and publish a private terminal
handoff only on success, before the PM put. Permit checked suspend to
consume that handoff while retaining sticky-error, START and STOP gates.
Every format exit clears it under the same lock. Other commands and
destruction still reject configuring; suspend's hardware body is unchanged.

Base: SDK 9f9e9d18574d0914c0d192a90c3babfe1fd63c95 plus public 0001-0013.
Reviewed delta: cpu-lifecycle-v12/source/delta-v11-v12.patch.
Evidence: outputs/rk3568-audio-runtime-20261005/public-integration-v1/.

'''),
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def expected_patches():
    result = {}
    for name, relative, digest, header in SPECS:
        path = RUNTIME / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError('Need ordinary frozen delta: ' + relative)
        delta = path.read_bytes()
        if sha(delta) != digest or not delta.startswith(('--- a/' + CPU + '\n').encode()):
            raise ValueError('Frozen delta mismatch: ' + relative)
        result[name] = header.encode() + ('diff --git a/' + CPU + ' b/' + CPU + '\n').encode() + delta
    return result


def main():
    manifest = json.loads((RUNTIME / 'build/integration-v3/manifest.json').read_text())
    old = sorted(PUBLIC.glob('*.patch'))
    prior = [path for path in old if int(path.name[:4]) <= 12]
    chain = list(manifest['patches_sha256'].items())
    if len(prior) != 12 or len(chain) != 14:
        raise ValueError('Expected prior 12/public and actual 14/private chain')
    for path, (private_name, digest) in zip(prior, chain[:12]):
        if path.read_bytes() != (ROOT / private_name).read_bytes() or sha(path.read_bytes()) != digest:
            raise ValueError('Prior public/private patch mismatch: ' + path.name)
    result = {}
    for name, data in expected_patches().items():
        path = PUBLIC / name
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                raise ValueError('Never replace existing public file: ' + name)
        else:
            with path.open('xb') as handle:
                handle.write(data)
        result[name] = {'bytes': len(data), 'sha256': sha(data)}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
