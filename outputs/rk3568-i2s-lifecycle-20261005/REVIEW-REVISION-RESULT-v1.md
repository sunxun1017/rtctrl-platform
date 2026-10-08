# CPU I2S v9：独立审查阻断修订

v9 已修复 v8 的 devres clock-handle UAF 和 checked profile 注册 controls 绕过门槛，并完成新的整段真实 probe/退出/PM 嵌套回归。仍为离线候选，未发布、未部署、未构建生产 Image、未上板，START 仍禁止。C3 与 DMA 的合测继续留后续。

## 最终交付

- [v9 完整真实 C](driver-source-v9/sound/soc/rockchip/rockchip_i2s_tdm.c)、[私有 patch](driver-source-v9/i2s-lifecycle-review.patch)、[新冻结清单](sealed-v2/manifest.json)。
- 源 SHA256：`5a04c4697c4db7f90f961767b1a454388e99fc170047571af5b4d818950cd357`。
- patch SHA256：`ffc6af4a0cd0dd605d2147e95c46cfd573ba5099d0ac7372b763682e4eb1e313`。
- Kbuild 对象 SHA256：`b35df89d1c7d33ed3473869fa5b4252c0cb6ac71a7322cbfe6670e34bd42d4cc`。
- 原 v8/sealed-v1、原证据输入及已哈希文档/工具全部保持字节一致，校验存入新清单。旧报告按历史保留，不修改旧绿色结果。

## 实际改动

checked probe 先完成 HCLK/TX/RX 三个 devm_clk_get，再注册 clock-release action，然后才 enable HCLK。真实 devres 反序因此先执行 action，后 clk_put 三个 consumer handles；partial getter、action 注册失败与 enable 失败均有回归。legacy profile 的原获取/enable 顺序保留。action 撤销 ready/IRQ、拒绝 owner/configuring、通过 PM disable 排运行中的 PM callback，再按停止证明释放本驱动所持钟引用；不依赖已失效 handle。

checked component 使用独立的实际 descriptor，整组 legacy PATH、loopback、wait-time controls 均不注册；实际原 descriptor/table 原样保留给其它 profile。实际 locked DT 不启用校准，DAI probe 也不会额外注册 calibration control。只读 lifecycle sysfs 保留，格式/正常重启候选字段条件沿用 [GUARD-EVIDENCE](GUARD-EVIDENCE.md)。

ready 发布前，startup、prepare、component START 和真实 DAI START 返回 -EAGAIN，不能建立子流/START owner；sticky 和 shutting_down 的既有首错误仍优先。外部参数/START admission 同锁检查 PM transition，纯 -EBUSY/-EAGAIN 不 poison。set_fmt 在注册/bind 阶段需要工作，故其内部配置 ticket 可跨真实 runtime resume；内部 forced STOP 和 teardown 的 resume 不调用外部门槛，避免对自己的 configuring/shutting_down 自拒绝。

component/PCM/sysfs 注册 late failure 在返回原注册错误前执行 process quiesce：同锁撤销 ready/IRQ、排 IRQ、实际 PM 获取/必要 resume、forced STOP+FIFO+MMIO readback、排 PM/IRQ并一致释放时钟，完成后才允许 devres。停止不确定则 panic_timeout=0，保留资源；测试会明确区分该 fail-stop 与成功退出。runtimeResume 结束时按锁内当前 shutting_down 发布 IRQ gate，防止已开始的 PM callback 把并发 teardown 撤销的 IRQ gate重新打开。

## 新增真实红→绿

[完整 probe/descriptor/PM/退出测试](probe-review-tests-green-v3/result.json) 摘录整段 production probe、DAI prepare、实际 controls/descriptor、真实 set_fmt/runtime PM/remove/shutdown/startup/ISR/helper C；API 边界模拟 OF、注册、CCF handles、devres、PM 核心序列化/异步 put。没有另写一份替代 probe。consumer handles 使用真实 malloc/free，按生产注册事件反序释放；已捕获 IRQ 与运行中的 PM callback 各有明确 barrier。

| 场景 | 每种运行绿色结果 |
| --- | --- |
| 16 处获取/注册/enable failure 与四个真实初始 register fault、反序退出 | 193/193 |
| bind callback 硬件错误后完整 late failure | 13/13 |
| component/PCM/sysfs 注册前 ready 门槛、DAI 二次检查、撤销后拒绝 | 30/30 |
| checked 注册零 legacy controls，其它 profile 保留原表 | 13/13 |
| inactive set_fmt ticket→resume，PM transition 两次 START检查，inactive remove→resume→STOP | 18/18 |
| 两个 clock enable、cache sync、PM get 故障及停止不确定阻止 devres | 59/59 |
| late failure 等已捕获 IRQ，再释放时钟/资源 | 13/13 |
| pending PM resume 与 remove 并发，PM serialization/ready撤销/IRQ不复活 | 15/15 |

合计每种 **354 个断言**，host、ASan/UBSan、ARM64/QEMU 全通过。[相同 harness 的 v8 红例](probe-review-tests-red-v4/result.json) 全部成功编译，所有场景均失败；[ASan 完整 probe UAF](probe-review-tests-red-v4/host-sanitized-late-fault.stderr) 明确在实际 action 的 clk_disable 后访问已释放的 TX/RX consumer。non-sanitized 的 UAF 数值受 freed memory 影响，不把这些值当精确硬件事实。独立审查原始证据完整保存于 [review-input-v1](review-input-v1/input-manifest.json)。red-v1/red-v3 与 green-v2 仅是缺失 shim 原型/旧 source pointer-sign 的 compile-failure 日志，不作行为红绿。

## 原回归、实际 DT 与 Kbuild

[review-regression-v1](review-regression-v1/runner-provenance.json) 保留原五套测试输入。正常场景夹具新增 ready=true 表示已完成 probe，新增套独立验证未 ready 的拒绝；不通过把所有场景默认 ready 来跳过新门槛。五套 host/ASan/ARM64 各继续通过 140/81/27/25/31，共 **304 个断言**。新旧共每种 658 个断言。

[真实 audio DT](actual-dt-review-profile-v1/result.json) 驱动 v9 真实 profile/config/state 再过 31/31；原 config/DT 锁未变。[Kbuild 完整实际 C](kbuild-review-object-v1/result.json) 编译退出 0、stderr 空，ELF64 LE AArch64 ET_REL；原 kernel HEAD9f9e… clean、原 ABI inventory 前后不变。外部 obj-m 只做对象/真实头文件/config 验证，仍需 built-in Image 链接和生产包/硬件验证。

## 保留的实际边界

完整 probe 的 **控制流**、配置/注册失败/反序退出均来自真实 C；OF/CCF/ALSA/IRQ/devres/PM 核心仍为明确模型，DAI/controls 的 API layout 部分为局部模型，最终 Kbuild 才验证完整真实 ABI。当前 DT 不走 route/multi-lanes/always-on/calibration，相关 helper 的 API 返回按 absent DT 边界提供，不能扩大到其它 profile。

PM put 模型保留异步 idle 语义，手动推进的 idle 与 queued-resume callback 使用模型核心锁；验证的是此驱动允许自身 ticket/teardown resume、屏障与引用一致性，不声称整个 Linux runtime-PM 核心或 PREEMPT_RT lockdep 运行通过。fail-stop 测试断言资源未释放后有单独的 test-only 内存收集，不能当成驱动退出成功。

CPU STOP/ready/IRQ/clock证据不证明 PL330 descriptor/callback/allocation 退出。C3 START rollback、STOP 保首错且全部 DMA cleanup、provider checked/quarantine/lease 独立只读门槛仍未合测；真实 FIFO/MMIO/IRQ/CCF、声音和外部 MCU/watchdog/复位行为仍未测。普通重启仍须先满足 CPU 与 DMA 两端证明，失败留救援，不靠尝试 shutdown 后 panic 判断，也不自动 reset。
