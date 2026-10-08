#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Freeze additive v2 tools, actual production inputs and observed results."""
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    spec = importlib.util.spec_from_file_location('audio_v2_seal', HERE / 'audio-package-v2.py')
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    gate = 'outputs/rk3568-audio-runtime-20261005/build/review-gate-v2.json'
    image_inputs = core.production_inputs(gate)
    package = HERE / 'build/ram-audio-v2'
    package_report = core.audit_directory(package, image_inputs)
    package_manifest = core.unique_json(core.read_ordinary(package / 'manifest.json'))
    audit = HERE / 'build/audit-production-v2'
    audit_report = core.unique_json(core.read_ordinary(audit / 'audit.json'))
    core.require(audit_report == package_report, 'Observed production audit must match fresh audit')
    audit_receipt = core.unique_json(core.read_ordinary(audit / 'receipt.json'))
    core.require(audit_receipt['audit'] == core.metadata(core.read_ordinary(audit / 'audit.json')) and
                 audit_receipt['auditor_sha256'] == core.metadata(core.read_ordinary(HERE / 'audio-package-v2.py'))['sha256'] and
                 audit_receipt['wrapper_sha256'] == core.metadata(core.read_ordinary(HERE / 'audit-audio-package-v2.py'))['sha256'],
                 'Observed audit receipt binding')

    old = core.unique_json(core.read_ordinary(HERE / 'build/prepared-v1/receipt.json'))
    old_preserved = {}
    for name, info in old['sources'].items():
        data = core.read_ordinary(core.relative_path(name))
        core.require(core.metadata(data) == info, 'Frozen prepared-v1 source changed: ' + name)
        snapshot = HERE / 'build/prepared-v1/source-inputs' / name
        core.require(core.read_ordinary(snapshot) == data, 'Old frozen source snapshot changed: ' + name)
        old_preserved[name] = info
    for name, info in old['evidence'].items():
        core.require(core.metadata(core.read_ordinary(HERE / name)) == info, 'Old fixture evidence changed: ' + name)
        core.require(core.metadata(core.read_ordinary(HERE / 'build/prepared-v1/evidence' / name)) == info,
                     'Old frozen evidence snapshot changed: ' + name)

    rejected_old = {}
    for name in ('build/tests-v1/fixture-candidate', 'build/tests-v2/fixture-candidate',
                 'build/tests-v3/fixture-candidate'):
        try:
            core.audit_directory(HERE / name, image_inputs)
        except ValueError as error:
            core.require('Candidate receipt mode/boundary' in str(error), 'Unexpected old result rejection')
            rejected_old[name] = {'reason': str(error), 'receipt': core.metadata(core.read_ordinary(HERE / name / 'receipt.json'))}
        else:
            raise ValueError('Old fixture accepted as production: ' + name)

    tests = core.unique_json(core.read_ordinary(HERE / 'build/tests-v4/result.json'))
    regression = core.unique_json(core.read_ordinary(HERE / 'build/production-bug-green-v2/result.json'))
    red = core.unique_json(core.read_ordinary(HERE / 'build/production-bug-red-v1/result.json'))
    cli = core.unique_json(core.read_ordinary(HERE / 'build/production-cli-v2/result.json'))
    core.require(tests['passed'] == tests['total'] == 62 and tests['mode'] == 'FIXTURE_ONLY_NOT_DEPLOYABLE',
                 'Observed fixture results')
    core.require(tests['core_source'] == core.metadata(core.read_ordinary(HERE / 'audio-package-v2.py')) and
                 tests['test_source'] == core.metadata(core.read_ordinary(HERE / 'test-audio-package-v2.py')),
                 'Observed fixture source binding')
    core.require(regression['passed'] == regression['total'] == 14 and
                 regression['core'] == {'path': str((HERE / 'audio-package-v2.py').relative_to(ROOT)),
                                        **core.metadata(core.read_ordinary(HERE / 'audio-package-v2.py'))},
                 'Observed real production regressions')
    core.require(red['passed'] == 6 and red['total'] == 14 and
                 all(command['exit_code'] == 0 for command in cli['commands']), 'Observed red and production CLI')

    output = core.fresh_directory(HERE / 'build/sealed-production-v2')
    notes = '''# 音频 RAM 包 v2 实际结果

两项生产输入错误已另立 v2 修复。旧工具与 prepared-v1 保持：35 个来源文件、7 个旧证据及其
冻结副本逐字节/完整 SHA 核对通过。没有改 Image、review gate、driver 或公共补丁。

- `build/production-bug-red-v1/result.json` 保存原工具 6/14、两项根因及相关格式失败；
  原生产 CLI exit 1，拒绝 `Bounded ordinary file required`，没有创建候选目录。
  真实 Linux Image 被原 release 判断拒绝；原工具把同一真实 Image 的虚假 Android release 接受。
- `build/production-bug-green-v2/result.json` 实际 14/14、exit 0：完整 910 文件 gate、合法空日志、
  真实新 Image、错误 release、空 JSON/Image/ARM64 输入、普通文件/路径/大小边界。
- `build/tests-v4/result.json` 实际 62/62、exit 0，为 `FIXTURE_ONLY_NOT_DEPLOYABLE`；
  旧 RCU Image release 从冻结 kernel-artifacts.json 和 Image banner 独立确认。
- `build/production-cli-v2/result.json` 保存实际 builder/auditor argv、stdout/stderr 和 exit 0。
  新生产包为 `build/ram-audio-v2`，新审计为 `build/audit-production-v2`。

根因一是底层普通文件读取混入了非空格式要求，导致合法零字节编译日志不能被完整 SHA 核对。
v2 仅把大小下界改为 0，大小上界、普通文件类型、路径和前后 identity 保持；格式解析仍拒绝空数据。
根因二是把原 Android `4.19.232` 错作 Linux Image release；v2 固定本次真实构建的
`5.10.160-rt89-g9f9e9d18574d-dirty`。

真实新 Image 为 34755072B，SHA `e48c4295b871623f3c4d0e18470d451b5c344b7e71d021c77f9b0cc297d89955`，
CRC `fb920db9`；manifest SHA `5caa5a64816af8627baf880d46cae55876e5a6ed0985afc21fd623765c1860f5`；
review-gate-v2 SHA `cbad7ecff36098d4dbc0d49db3191f966bcf4107595e733671be0330e20781af`。
实际 raw 包 40482816B，padded 包 41943040B，完整 SHA
`58e2a96f9da2c2ad1d60e0b42c92efa2d4c30efbfe76202738393f2e06974b8b`，CRC `fe7bd3a1`。

v2 production audit 实际拒绝旧 tests-v1/v2/v3 fixture candidate 的 mode；旧 prepared-v1
仍为生产待完成证据，旧 62/62 不能证明这轮真实生产输入可用。
封存入口 `build/sealed-production-v2/receipt.json` 含新工具、实际输入、所有本轮结果的完整 SHA。

范围保持 `RAM_ONLY_NOT_FLASH_READY`。没有操作板、ADB、串口、网络、TUN、分区、保存环境、
公共补丁、提交或推送。没有声学/电气、PCM START/STOP 或实际新内核板测结论；主控仍需独立复核
和 fresh RAM 地址/CRC/整树/身份/普通返回验证。
'''
    core.write_new(HERE / 'RESULTS-v2.md', notes.encode())
    tool_names = ('audio-package-v2.py', 'build-audio-package-v2.py', 'audit-audio-package-v2.py',
                  'test-audio-package-v2.py', 'test-production-inputs-v2.py', 'create-v2-tools.py',
                  'run-production-v2.py', 'seal-production-v2.py', 'README-v2.md', 'PLAN-v2.md', 'RESULTS-v2.md')
    snapshots = {str((HERE / name).relative_to(ROOT)): core.read_ordinary(HERE / name) for name in tool_names}
    for name in (gate, core.PRODUCTION + 'manifest.json', core.PRODUCTION + 'kernel.config',
                 core.PRODUCTION + 'Module.symvers', core.PRODUCTION + 'vmlinux.symvers',
                 'outputs/rk3568-rcu-reset-20261004/kernel-artifacts.json'):
        snapshots[name] = core.read_ordinary(core.relative_path(name))
    for name, data in snapshots.items():
        target = output / 'source-inputs' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        core.write_new(target, data)

    result_dirs = ('production-bug-red-v1', 'production-bug-green-v2', 'tests-v4',
                   'production-cli-v2', 'ram-audio-v2', 'audit-production-v2')
    evidence = {}
    for name in result_dirs:
        for path in sorted((HERE / 'build' / name).rglob('*')):
            if path.is_file() and not path.is_symlink():
                evidence[str(path.relative_to(ROOT))] = core.metadata(core.read_ordinary(path))
    production_files = (core.PRODUCTION + 'Image', core.PRODUCTION + 'manifest.json',
                        core.PRODUCTION + 'kernel.config', core.PRODUCTION + 'Module.symvers',
                        core.PRODUCTION + 'vmlinux.symvers', gate)
    receipt = {'schema': 2, 'status': 'RAM_ONLY_NOT_FLASH_READY',
               'sources': {name: core.metadata(data) for name, data in snapshots.items()},
               'production_inputs': {name: core.metadata(core.read_ordinary(core.relative_path(name)))
                                     for name in production_files},
               'production_image_release': '5.10.160-rt89-g9f9e9d18574d-dirty',
               'reviewed_files_sha256': image_inputs['provenance']['reviewed_files_sha256'],
               'results': evidence, 'package': package_report['package'],
               'production_regressions': {'passed': 14, 'total': 14},
               'fixture_checks': {'passed': 62, 'total': 62, 'mode': 'FIXTURE_ONLY_NOT_DEPLOYABLE'},
               'old_preserved_sources': old_preserved,
               'old_preserved_evidence': old['evidence'],
               'old_prepared_receipt': core.metadata(core.read_ordinary(HERE / 'build/prepared-v1/receipt.json')),
               'old_fixture_production_rejections': rejected_old,
               'superseded_old_production_input_validation': {'read_ordinary_zero_bytes': 'REJECTED_VALID_LOGS',
                                                            'kernel_release': 'ANDROID_RELEASE_ACCEPTED_LINUX_REJECTED'},
               'board_tested': False, 'deployed': False, 'formal_flash_ready': False,
               'freeze_scope': 'NEW_TOOLS_REAL_INPUTS_AND_ALL_OBSERVED_NEW_RESULTS'}
    core.write_new(output / 'receipt.json', core.json_bytes(receipt))
    print(core.json_bytes({'status': receipt['status'], 'new_sources': len(snapshots),
                          'results': len(evidence), 'old_preserved_sources': len(old_preserved),
                          'old_preserved_evidence': len(old['evidence']),
                          'old_fixture_production_rejections': len(rejected_old),
                          'package': receipt['package'],
                          'receipt': core.metadata(core.read_ordinary(output / 'receipt.json'))}).decode())


if __name__ == '__main__':
    main()
