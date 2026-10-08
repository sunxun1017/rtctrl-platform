#!/usr/bin/env python3
"""Preserve the previous design evidence and record its authorized source-based correction."""
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
DESIGN = HERE.parent / 'full-duplex-configuration-design-v1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    previous = DESIGN / 'correction-v1/before'
    previous.mkdir(parents=True, exist_ok=False)
    pinned = {'DESIGN.md': 'ad82e047bd9fe34c7f9940ee0b64e72ee8c0ff0992c25f48ad0334062601c83d',
        'input-manifest.json': 'd00a4bf2c174958ff9271f03f9928095922c4e818bc79d37139081f1b45b7167',
        'design-readback.json': '166e394a3df648234605bc750e7e6f86651321c82fa03ba100413a49076c762f'}
    for name, digest in pinned.items():
        path = DESIGN / name
        if sha(path) != digest:
            raise ValueError('Previous design identity changed')
        shutil.copy2(path, previous / name)
        if sha(previous / name) != digest:
            raise ValueError('Previous evidence copy differs')
    path = DESIGN / 'DESIGN.md'
    text = path.read_text()
    old = '''CPU 的 started/configuring 检查较晚。
仅新增 CPU 的格式门，或仅把 codec 比较放在其 hw_params 开头，都不能保证 machine 早期
CCF/set_sysclk 不改 peer。card pcm_mutex 也不串行另一个方向的 trigger/IRQ/异步 PM。'''
    new = '''需纠正首次设计的顺序推论：CPU set_sysclk 在 machine 末尾已有 started 门。健康
peer 48k 运行、B 同 rate 请求时，machine 先有两个 clk_get_rate 和 codec 缓存 setter，
随后 CPU set_sysclk 返回 EBUSY；后续 codec hw_params/PLL 不执行。不能称这条健康链已
重启 PLL，CCF getter 也不能被称作已证明物理寄存器读取。

更有价值的待模型串接是 component 晚失败把 CPU.rate 清0后，合法单向 START peer，再
请求不同 rate：symmetry 可因 cache=0 跳过，machine 的 child CCF/cache 改动早于 CPU
set_sysclk 拒绝。此处必须用真实 error/START 产生状态，不手写清 rate 或 started。
不同 rate 的健康已配置 peer 本来由 symmetry 提前挡住，这个正确行为也应保留。
card pcm_mutex 仍不串行另一个方向的 trigger/IRQ/异步 PM；显式整链预约用于这些空窗
及失败归属，不能以错误的健康链 PLL 推论论证。纠正及原字节见 correction-v1。'''
    if text.count(old) != 1:
        raise ValueError('Expected design paragraph missing')
    path.write_text(text.replace(old, new))
    old_manifest = json.loads((previous / 'input-manifest.json').read_text())
    correction = {'previous_files_sha256': pinned, 'corrected_design_sha256': sha(path),
        'source_manifest_v1_sha256': sha(DESIGN / 'input-manifest.json'),
        'reason': 'Actual machine CPU set_sysclk started gate precedes codec hw_params; healthy and post-error paths must differ',
        'source_functions': ['asoc_simple_hw_params', 'rockchip_i2s_tdm_set_sysclk', 'soc_pcm_params_symmetry', 'soc_pcm_hw_params'],
        'source_body_identities_unchanged': True, 'model_executed': False, 'production_modified': False}
    (DESIGN / 'correction-v1/record.json').write_text(json.dumps(correction, indent=2) + '\n')
    old_manifest['design_correction'] = correction
    (DESIGN / 'input-manifest-v2.json').write_text(json.dumps(old_manifest, indent=2) + '\n')
    (DESIGN / 'design-readback-v2.json').write_text(json.dumps({
        'status': 'AUTHORIZED_DESIGN_INFERENCE_CORRECTION_NOT_MODEL_RESULT',
        'design_sha256': sha(path), 'input_manifest_v2_sha256': sha(DESIGN / 'input-manifest-v2.json'),
        'correction_record_sha256': sha(DESIGN / 'correction-v1/record.json'), 'previous_files_preserved': pinned,
        'model_executed': False, 'build_executed': False, 'board_tested': False,
        'duplex_START_authorized': False}, indent=2) + '\n')
    print(json.dumps({'design_sha256': sha(path), 'manifest_v2_sha256': sha(DESIGN / 'input-manifest-v2.json'),
        'readback_v2_sha256': sha(DESIGN / 'design-readback-v2.json')}))


if __name__ == '__main__':
    main()
