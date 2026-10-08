# 0010 独立只读审查

2026-10-05，由未实施本补丁的 PID1 作者审查。公开补丁 SHA256：
`c3bd1bd7e8fd581e21a962993519f934ceb78a7efe61d77da846972e93b73f2b`。
最终输入为 `driver-source-v2/manifest.json`，SHA256
`af187eb8da2b890742244582410febf85cc5bec0e2c2e310849f63f11393957e`。

未发现本次限定范围的阻断问题。真实 `snd_soc_dai_digital_mute` 选择条件与新增 predicate
一致；无 callback 和 capture `no_capture_mute` 跳过，适用 callback 的 ENOTSUPP 作为真失败。
PREPARE 的第一次 unmute 错误停止后续 unmute，重新 checked 静音已尝试前缀、配对 DAPM STOP，
保留首 errno，没有递归获取 PCM mutex。HW_FREE 保留首个 mute 错误并继续原清理。
进入 do_prepare 后，prepare/reset 失败退 SETUP，保留 DISCONNECTED，真实 START 门槛拒绝。

本次只读核对 105 个文件 SHA 一致，红/绿逐字抽取 41/42 项全部一致；读取保存的 host、
ASan/UBSan、AArch64/QEMU 报告，原源码各 42/198，修正各 198/198；生成器 36/36、审计 224/224。
没有重跑这些测试、构建生产 Image 或操作板子。

前置 buffer/pre_action 拒绝尚未调用驱动，仍可能保留 PREPARED；reset 失败仅使 PCM 状态失效，
不撤销已成功 DAPM START。HW_FREE 不负责完整 DAPM STOP；close 仍可能忽略错误。
managed buffer 的释放、链接 PCM 的跨流事务、实际电气状态和 DMA/PL330 同步不由 0010 解决。
继续禁止上板 START，须完成 DMA 所有权修复和生产构建后再独立验收。
