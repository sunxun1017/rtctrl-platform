#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Reuse existing actual user ABI helpers after their missing-transfer red run."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--verify', action='store_true')
args = parser.parse_args()
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'outputs/rk3568-i2s-lifecycle-20261005'))
sys.dont_write_bytecode = True
from source_utils import function
original = ROOT / 'outputs/rk3568-audio-runtime-20261005/pcm-config.c'
s = original.read_text()
prefix = s[:s.index('static const char pcm_identity')]
prefix = prefix.replace('/* RK809 PCM parameters only: never prepare/start, transfer frames, or change controls. */', '/* RK809 bounded one-direction PCM I/O; root guard retains reboot authority. */')
prefix = prefix.replace('#include <errno.h>', '#include <errno.h>\n#include <inttypes.h>\n#include <poll.h>\n#include <stdbool.h>\n#include <stdarg.h>\n#include <stdlib.h>\n#include <sys/time.h>\n#include <time.h>')
prefix += '_Static_assert(sizeof(struct snd_pcm_sw_params) == 136, "SW_PARAMS ABI");\n'
prefix += '_Static_assert(offsetof(struct snd_pcm_sw_params, start_threshold) == 32, "SW start offset");\n'
prefix += '_Static_assert(SNDRV_PCM_IOCTL_SW_PARAMS == 0xc0884113UL, "SW_PARAMS ioctl");\n'
prefix += '_Static_assert(SNDRV_PCM_IOCTL_PREPARE == 0x4140UL && SNDRV_PCM_IOCTL_START == 0x4142UL && SNDRV_PCM_IOCTL_DROP == 0x4143UL, "state ioctl ABI");\n'
declarations = s[s.index('static const char pcm_identity'):s.index('static int text_valid')]
names = ['text_valid', 'pcm_info_valid', 'params_any', 'params_exact', 'interval_contains', 'caps_valid', 'caps_allow_exact', 'exact_valid']
body = '\n\n'.join(function(s, n) for n in names)
target = HERE / 'pcm-transfer.c'
generated = prefix + '\n' + declarations + '\n' + body + '\n' + (HERE / 'pcm-transfer-body.c').read_text()
if args.verify:
    if target.read_text() != generated: raise ValueError('final source differs from reproduction')
else:
    if target.exists(): raise ValueError('source already exists')
    target.write_text(generated)
provenance = HERE / ('source-provenance-final.json' if args.verify else 'source-provenance.json')
if provenance.exists(): raise ValueError('provenance already exists')
provenance.write_text(json.dumps({'existing_source_sha256':hashlib.sha256(original.read_bytes()).hexdigest(), 'copied_functions_sha256':{n:hashlib.sha256(function(s,n).encode()).hexdigest() for n in names}, 'source_sha256':hashlib.sha256(target.read_bytes()).hexdigest(), 'raw_kernel_uapi_sha256':hashlib.sha256((ROOT / 'third_party/linux-rk3588/include/uapi/sound/asound.h').read_bytes()).hexdigest(), 'final_source_reproduction_verified': args.verify}, indent=2) + '\n')
print(target)
