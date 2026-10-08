# CPU lifecycle v11：合法 shutdown 的 0Hz 请求清理

本版只在新目录中形成候选和离线证据；不改变原 kernel、已经实测的专用音频树、旧 v10、公共
0012、启动包、native3、项目记忆或硬件状态。v11 尚未形成完整 Image，也没有板测。

根线程实测旧候选 playback/capture 都完成有界 START、DROP、HW_FREE、close，并通过独立
post bound gate，但 close 时出现 `snd_soc_dai_set_sysclk ... -22`。原因是 checked CPU callback
在任何锁、状态检查或缓存更新之前拒绝 `freq=0`。真实 simple-card 的 machine shutdown
在 `mclk_fs` 有效时正常调用 codec/CPU `set_sysclk(..., 0, ...)`；这个关闭请求是清理请求缓存，
无需将硬件时钟率设为零。ASoC 的 machine shutdown 是 void，close 返回 0 会伴随这个诊断，
不能把 helper 的成功返回写成无诊断验收。

真实调用顺序来自冻结 `soc-pcm.c`：`soc_pcm_clean` 先对 DAIs 调用 shutdown，再调用 link
shutdown/simple-card，之后关闭 components、最后 PM put。checked CPU DAI shutdown 已清理
当前 substream 指针，完成 STOP，并在锁外 `synchronize_irq` 后发布 IRQ drained；随后才收到
simple-card 的 0Hz。此时 CPU own MCLK/IRQ live 可仍保留，PM put 尚未发生，不能错误要求
它们已释放。codec component probe 所持的独立基础 MCLK 引用也不由这个缓存请求清理释放。

候选仅修改两个函数：

- `rockchip_i2s_tdm_set_sysclk`：继续验证 clock ID，并在原 spinlock 下先执行原 checked gate；
  sticky、shutting_down、configuring、power_transition、started 都按原错误拒绝。仅对 zero
  额外要求 STOP proven、IRQ drained、两个 substream 指针均为空；成功同时清零共享 TRCM 的
  TX/RX 请求缓存。不发 clk/PM/regmap/MMIO 操作，不清 sticky，不修改 STOP/IRQ/引用计数。
- `i2s_checked_hw_params`：原 checked gate 成功后，在置 configuring 和任何 clock 操作前
  拒绝任一请求缓存为零，返回 `-EINVAL` 且不 poison。避免 shutdown 清零后不经正确 sysclk
  setup 的直接 hw_params 进入 `clk_set_rate(0)`。下一次真实 simple-card hw_params 先以
  rate×mclk_fs（本板 48000×256）通过 codec/CPU setter 重建正频率，再进入 CPU hw_params。

非零 checked sysclk 的原准入保持；它仍可在 startup 后、STOP/IRQ 初始未证明时设置请求缓存，
由后续 prepare/STOP 建立运行证明。zero 额外限制不套到这个合法 preconfiguration 阶段。
旧 unchecked sysclk/TRCM/独立方向和 unchecked hw_params 分支逐字节不变。

`shutdown-red-v10` 使用冻结旧实际 CPU、真实 `snd_soc_dai_set_sysclk` dispatch、真实 simple
shutdown 和 codec cache setter，每环境 4 项中的合法共享缓存清理那一项失败，三环境一致。
`shutdown-green-v11` 每环境 48/48，覆盖 zero cache reset、两方向、重复 zero、活动/配置/转换/
sticky/shutdown/open/STOP/IRQ 拒绝、非法 clock ID、legacy 保持、清零后直接 hw_params 拒绝、
下一次真实 simple-card 正请求重建与实际 CPU hw_params。
`params-regression-v11` 原参数模型每环境 140/140。环境是 host、ASan+UBSan、AArch64 QEMU。

这些执行的是逐字节生产函数与真实 caller body，设备/CCF/regmap/PM/ASoC 周边为明确模型；
post-CPU-shutdown 的 STOP/IRQ/open 字段也是模型。没有模拟完整 kernel close、真实 IRQ/DMA
排空或实物电气行为。codec setter本身仅缓存更新、simple child clk 在本 DT 中未配置；模型证明
这一组合未发 clock release，不能声称测到了 per-consumer CCF 引用。

`kbuild-object-v1` 将完整生产 C 编译为 AArch64 ET_REL，使用原已集成 Image 的 config 和
Module.symvers、独立复制的 ABI 输出目录；所有写入在本目录，原源树和 ABI 前后 SHA 相同。
此检查为实际 Kbuild object，不是重新构建 Image 或装入 kernel。

`source/delta-v10-v11.patch` 是窄增量，`source/i2s-lifecycle-v11.patch` 是从原未修改 CPU 源码
开始的完整候选补丁。两种 patch 在独立目录实际 replay 后必须得到同一完整候选 SHA。
`receipt.json`、`frozen-output-manifest.json` 和 `SHA256SUMS` 登记模型、编译、源码/补丁和输入。
主控仍需独立审查、重新形成 Image/codec ABI/包身份，再以新的 pre/post guard 和全诊断做实机
对照；本候选不替代 START、硬件 STOP、返回 Android 或正式恢复验证。
