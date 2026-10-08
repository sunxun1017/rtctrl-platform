#!/usr/bin/env python3
"""Preserve v2 inference evidence, then record the parent's finite errno/caller decision."""
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
DESIGN = HERE.parent / 'full-duplex-configuration-design-v1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def change(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Expected unique design correction')
    return text.replace(old, new)


def main():
    pins = {'DESIGN.md': '44fcd22b971318c04bb2bf1322ab612137ed148f13196a57cbbd89fba2993981',
        'MODEL-PLAN.md': 'c8a0e6d8f1d08273bdc234f8f70e238887d0fdfb007e79d431180e9a9bedcd04',
        'input-manifest-v2.json': '25776089ba1474de586f155b4cb851bf186f69d7cfcd843bcf125aa289e2c777',
        'design-readback-v2.json': 'e1db3e40894d2335b3a46a42a0b5c6361c2b205d6a6623cd18d57fe7b63f1038'}
    for name, digest in pins.items():
        if sha(DESIGN / name) != digest:
            raise ValueError('Previous design identity changed: ' + name)
    previous = DESIGN / 'correction-v2/before'
    previous.mkdir(parents=True, exist_ok=False)
    for name in pins:
        shutil.copy2(DESIGN / name, previous / name)
        if sha(previous / name) != pins[name]:
            raise ValueError('Previous evidence copy differs')
    path = DESIGN / 'DESIGN.md'
    text = change(path.read_text(),
        '| 任一方向已 START，另一向或同向请求 params（包括相同 tuple） | 在整链入口拒绝 -EBUSY；不做 PLL/rate/width 写入，不把幂等 setter 当活动期重配许可 |',
        '| 任一方向已 START，另一向或同向请求 params | 先保留 symmetry/有限 profile 的 -EINVAL；通过两门的合法同 profile 请求在首共享写前拒绝 -EBUSY；不做 PLL/rate/width 写入 |')
    text += '''
## 纠正 v2：errno 优先级与 START 前缀

主控已选择保留原 symmetry，有限 profile validation 同样返回 EINVAL；只有通过两门的
running 同 profile 请求才要求 EBUSY。健康已配置 peer 的不同 rate 本来就由 symmetry
EINVAL 拒绝，必须登记为正确观察，不能将它列为业务红例。component 晚失败清 rate 后的
44100 请求超出本轮 profile，候选应在首共享写前 EINVAL；旧链预计在 child CCF/cache
修改后 EBUSY，两种差别均需保留真实记录。这里没有实现新的 validation/reservation。

START 状态只由真实 soc_pcm_trigger 产生：link → components（含 CPU component 早门、
DMA API 边界）→ DAIs，并保留 C3 的本调用 prefix 失败 rollback。不能只调用 CPU trigger
再称整个 START 无副作用。reservation 先胜时，component/DMA 前缀是否已执行必须通过
真实 caller 观察；CPU DAI 末段门不能替代整条事务的证明。旧 source/body 身份不变。
纠正前字节与新记录见 correction-v2；本段是已选择的设计契约，不是模型/板验证结果。
'''
    path.write_text(text)
    plan = DESIGN / 'MODEL-PLAN.md'
    text = change(plan.read_text(),
        '| 合法单方向 START 后，第二向相同/不同 params | 实际旧链红例：codec-before-CPU 或 machine 已动，然后 CPU EBUSY；候选必须首 I/O 前 EBUSY |',
        '| 合法单方向 START 后，第二向 params | 健康同 rate 在 machine CPU sysclk 处 EBUSY且无 codec PLL，健康不同 rate symmetry EINVAL均为正确观察；晚 component 失败清 rate 后的 44100 旧链 CCF/cache先变再EBUSY，候选 profile EINVAL且首共享写0 |')
    text = change(text,
        '| DAI | snd_soc_dai_hw_params/hw_free/set_sysclk、真实 stream_valid 与 iterate 宏；fixup 的真实参数拷贝行为 |',
        '| DAI | snd_soc_dai_hw_params/hw_free/set_sysclk、实际 iterate 宏与 fixup 参数拷贝；本次 stream_valid 有限 API shim 须明确边界，后续能力验证才抽取真实体 |')
    text += '''
基线另保留真实 soc_pcm_trigger 的 component/DMA→DAI 顺序与 C3 rollback；未抽取的
DMA GO/STOP 为 API 模型，不能称 PL330 实机。健康不同 rate 的合法 EINVAL不计业务失败；
44100 的候选首写前 EINVAL 与旧晚 EBUSY按不同合同观察，不统一成同一 errno。
'''
    plan.write_text(text)
    correction = {'previous_files_sha256': pins,
        'corrected_design_sha256': sha(path), 'corrected_model_plan_sha256': sha(plan),
        'errno_precedence': ['existing_symmetry_EINVAL', 'finite_profile_EINVAL', 'otherwise_valid_running_EBUSY_before_shared_write'],
        'START_chain': 'actual soc_pcm_trigger components/DMA then DAIs, actual C3 local-prefix rollback; API model is not PL330',
        'source_body_identities_unchanged': True, 'model_executed': False, 'production_modified': False}
    record = DESIGN / 'correction-v2/record.json'
    record.write_text(json.dumps(correction, indent=2) + '\n')
    manifest = json.loads((DESIGN / 'input-manifest-v2.json').read_text())
    manifest['errno_and_START_correction'] = correction
    output = DESIGN / 'input-manifest-v3.json'
    output.write_text(json.dumps(manifest, indent=2) + '\n')
    readback = DESIGN / 'design-readback-v3.json'
    readback.write_text(json.dumps({'status': 'PARENT_SELECTED_CONTRACT_NOT_MODEL_RESULT',
        'design_sha256': sha(path), 'model_plan_sha256': sha(plan), 'manifest_v3_sha256': sha(output),
        'correction_record_sha256': sha(record), 'previous_files_preserved': pins,
        'model_executed': False, 'Kbuild_executed': False, 'board_tested': False,
        'duplex_START_authorized': False}, indent=2) + '\n')
    print(json.dumps({'design_sha256': sha(path), 'model_plan_sha256': sha(plan),
        'manifest_v3_sha256': sha(output), 'readback_v3_sha256': sha(readback)}))


if __name__ == '__main__':
    main()
