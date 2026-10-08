# RK817 mute errno 与 OFF 状态 Implementation Plan

> 执行方式：本 worker 按已授权范围直接实现；root 整合并独立审查。使用 rtctrl-dev 与 TDD，未经额外授权不委派、不操作硬件或 Git。

**Goal:** 修正三个 codec mute 回调的方向检查、OFF/MIC_OFF 行为、逐 I/O 错误传播及实例故障后禁止解除静音。

**Architecture:** 在 0006+0007 候选副本上生成 0009，不修改原内核、共享 PMIC regcache 策略或任意路径切换。实例保存首次负 I/O errno；受控 unmute 失败进行本方向一次有界 checked mute 清理，原错误优先。静音路径先关输出 GPIO，尽力执行独立的数字关闭，保持首错；fault 后即使静音清理表面成功也返回保存的首次负 errno。

**Tech Stack:** 锁定 Linux 5.10 C、GCC 11.4、ASan/UBSan、静态 AArch64 与 QEMU user。

**Spec:** 本任务指令；输入 `../rk3568-audio-runtime-20261005/driver-source-v1/sound/soc/codecs/rk817_codec.c`，SHA `797d9d74c81dba2ed6f306c011446882eaed1bdf7b8d1ffc7321de73676e86b6`。

## Global Constraints

- 核锁定 commit `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`；保留原 GPL-2.0-or-later 通知和全部已有改动。
- 只修改本输出目录的新文件及公开 `0009-rk817-mute-errors.patch`。
- GPIO helper 使用无 errno 的 `gpiod_set_value`，只能记录关闭请求，不能证明电气动作成功。
- 任何已覆盖 I/O 错误保持实例 fault；后续真正 unmute 返回保存的首次 errno，不再发寄存器或使能 GPIO。
- Playback OFF 的 unmute 执行 checked DAC mute；MIC_OFF 的 unmute 执行 checked I2STX disable。
- 已知更新成功返回 0/1，均归一成功 0；所有负错误原样传播。

## Review Focus

- regcache 可能在总线报错前更新，不能用下次 update_bits 的 0 返回推断硬件恢复。
- DAC restart 含开启时钟步骤；先设置 DAC mute 成功才进入 restart，restart 首错后仍尝试关闭独立 I2SRX。
- unmute 失败后清理再失败不能覆盖主 errno，也不能清除 sticky fault。
- 已有播放情况下采集方向错误的处理仅局限本方向；不自动变更同时播放路径。
- direct DAC/ADC 回调与总 dispatcher 都要在任何 GPIO/寄存器之前拒绝错误方向。

## Task 1: 真实函数与测试

文件：`test-mute-functions.py` 抽取实际私有结构、GPIO helper、DAC restart 和三个 mute 回调；`test-mute-shim.h` 只替代内核 I/O 边界；`test-mute-main.c` 提供有界故障与缓存先更新 fixture。

- [x] 写覆盖各合法路由、OFF/MIC_OFF、非法 stream、每个 I/O 失败、正 0/1、输出关闭、清理失败和 fault 后禁止 unmute 的测试。
- [x] 对原 0006+0007 候选运行 red，确认行为失败而不是编译失败。
- [x] 在 `driver-prepare.py` 只变更 mute 回调和实例错误字段，生成独立 source 副本与公开 patch。
- [x] host、ASan/UBSan、静态 AArch64/QEMU 全部通过；生成器输出与完整 0006+0007+0009 补丁重放字节一致。
- [x] 保留 hash 绑定的红绿结果、工具版本和自含 harness，交 root 独立审查。

## 当前已验证结果

- 最终 `driver-source-v2` C SHA：`72e59ced7af3bc570bafb516459c55a073f80613fb0a9ff1b6192cfa3f7cbc64`。
- 公开 0009 SHA：`4d7cb506387fea2d336cbb75fe81679ad72cb3121016ea2af949e176fbdfeb5c`；与 source-v1 候选字节相同。
- `mute-tests-red-v3/result.json`：三个环境各 226 项，69 通过、157 行为失败。
- `mute-tests-green-v4/result.json`：host、ASan/UBSan、静态 AArch64/QEMU 各 226/226。
- `prepare-tests-v1/result.json`：22/22，含独立完整补丁重放、改动输入/坏依赖/冲突发布拒绝及原树仍 clean。
- 来源 C/H、函数摘录、测试代码、输出和 ELF 的 SHA 均保存在自含结果目录。没有 production module 新构建或硬件验证；root 独立审查仍待完成。

## 未完成的下一层问题

ASoC `snd_soc_dai_digital_mute` 的调用者仍可能忽略返回值，本补丁不保证 ALSA prepare/start 会失败退出。PCM PREPARE 重入 state、DMA 启停同步和 frame progress/退出生命周期尚未修复。本阶段不允许 START 或上板运行 DMA，不能仅因 codec C 测试通过便越过此门槛。任意运行时 Playback/Capture Path 切换、resume/shutdown/并发与卸载不在本任务范围。

完整 production module 新构建由 root 后续执行；本 worker 不修改旧 ABI 输出或部署硬件。
