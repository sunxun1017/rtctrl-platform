# RK3568 CPU I2S v8 离线候选

最终冻结 driver-source-v8，仅交独立审查。未发布 0012、未部署、未构建生产 Image、未触碰硬件，当前仍禁止音频 START。C3 与 generic DMA/PL330 的退出合测、完整 Image/匹配 ABI、上板验收均未完成；不能据此将安卓迁移或音频适配标完成。

## 最终产物

- [完整真实 C](driver-source-v8/sound/soc/rockchip/rockchip_i2s_tdm.c)、[私有审查 patch](driver-source-v8/i2s-lifecycle-review.patch)、[原始源/ABI 快照](source-input-v1/manifest.json)。
- [分块计划](PLAN.md)、[只读状态与根守卫边界](GUARD-EVIDENCE.md)、[最终冻结清单](sealed-v1/manifest.json)。冻结清单覆盖候选、测试输入、机器结果、Kbuild 对象与 patch replay；生成时的早期 candidate manifest 不覆盖最终测试状态。
- 源 SHA256：`33bd1208d379be53be8232cab11fe908f2d3096b94e66fc59d76a143c86cb3d0`。
- 私有 patch SHA256：`8e669846259434b5253c3055e3628b0a3541fe699b42950f47011a6ca3037990`。

## 修改与边界

checked profile 精确限制 fe410000/0x1000、RK3568、TRCM1、BCLK64、普通 master I2S，无 always-on/HDMI/calibration/multiplex/multi-lanes/digital-loopback/no-dmaengine/route。set_fmt 拒绝不同协议/主从模式，TDM slot 不支持。其它 profile 保留 legacy 路径，不进入本次安全性声明。

真实参数链检查 channels/dirty/read/write 与 clock/PM errno，配置 ticket 跨睡眠 clock 操作但不持 spinlock，纯输入/冲突错误不 poison。实例硬件首错 sticky；prepare、startup、hw_params、CPU component START 预检和真实 DAI START 都拒绝已知故障。component 只预检，不启动 CPU，实际 DAI 在同一锁事务再次检查并取得方向 owner。

本轮为主控批准的单向闭环：播放、采集可分别运行；已有任一方向 START 后第二方向 START 或参数修改返回 -EBUSY，纯冲突不 poison。重复本方向 START/STOP 不增加 owner；没有全双工承诺。START 失败保首 errno 并尽力停止，STOP 尽力遍历 IRQ/DMA request/XFER/FIFO 清理；cache 写失败后必须真正 force 写，不接受空 RK3568 reset 的假成功。软件 IRQ publish/revoke 使用 READ_ONCE/WRITE_ONCE，ISR 离开 I2S 锁后才进入 ALSA；process shutdown/PM 才 synchronize_irq，trigger/ISR/stream-lock 内没有 IRQ 等待。

STOP 成功需直接 MMIO XFER/DMACR/INTCR readback；只读 sysfs 显示 sticky、方向 owner/open、不确定、IRQ gate/drain、钟 lease、事务位。runtime suspend 对 sticky/未停稳拒绝关钟，cache-sync 失败恢复 cache-only，钟引用按实际取得的 prefix 释放一次。checked remove/platform shutdown 无法保存 devres 时在破坏前 panic_timeout=0；正常重启须事先守卫证据，不能以试 shutdown/panic 替代。probe unwind 阻止晚到 PM 回调，MCLK 已开但 STOP 不确定时拒绝释放，PCM 注册失败进入 PM 退出路径。

## 最终验证

下表五套都从同一 v8 真实 C 摘录函数与实际 DAI/DMA-data/UAPI 声明；每套 host、ASan/UBSan、ARM64 静态交叉编译/QEMU 均通过。API、PCM substream/device、IRQ 与 MMIO 行为由显式边界模型提供，不宣称完整内核 ABI 运行或硬件成功。

| 范围 | 每种运行结果 | 机器收据 |
| --- | --- | --- |
| 参数、clock/read/write/PM 首错 | 140/140 | [params](params-tests-green-v6/result.json) |
| START/STOP、cache 失败、FIFO、MMIO 回读、并发方向 START | 81/81 | [lifecycle](lifecycle-tests-green-v4/result.json) |
| 指针撤销/已捕获 ISR、无锁反转、prepare/component 预检 | 27/27 | [IRQ](irq-tests-green-v4/result.json) |
| PM/clock、未知停止、remove/shutdown/probe unwind | 25/25 | [PM](pm-tests-green-v6/result.json) |
| 真实 probe 初始 block、SoC GRF、profile、只读 state | 31/31 | [config/profile](config-tests-green-v3/result.json) |

共每种运行 304 个断言。 [实际 DT 驱动真实 profile/config 函数](actual-dt-profile-v2/result.json) 另过 31/31，保存锁定 DT `9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478`、fe410000 reg/TRCM/IRQ/default pinctrl、CPU phandle、I2S/mclk-fs256 card 路由；不只凭硬编码夹具接受 profile。

[真实 Kbuild 对象](kbuild-object-v3/result.json) 使用原 `.config` `1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912`、复制的原 ABI metadata、实际内核头文件与已锁定 cache-header 修复。完整 C 编译为 ELF64 LE AArch64 ET_REL，0 编译退出且 build.stderr 为空。对象 SHA256 `fb4210aa735b0f4eccd4e043b77397cd2ad8bbeedbbcf078c58427f3daba2afe`。原 kernel HEAD `9f9e9d18574d0914c0d192a90c3babfe1fd63c95` 保持 clean，原 ABI 全文件 inventory 前后相同。这里外部 obj-m 仅选择对象并有 MODULE 初始化语义；生产配置为 built-in=y，仍需真实 Image 链接及上板，不能加载此对象或推断 module import 闭合。

红例与失败日志全部保留。有效行为红例包括原参数 31/121→候选最初137/137、原 lifecycle12/77→77/77、原 IRQ14/26→26/26、原 PM4/14→20/20；后续回归增加参数3例、STOP proof/MMIO未清2例、未知proof component1例、PM初始proof/退出3例，以及 probe/profile/readonly31例。当前 PM unwind 原v6 为23/25→v7/v8 25/25，初始config/profile 原v5 为3/13→v7/v8 31/31（新增 profile/state 的完整分支仅候选存在）。compile-failure 目录只作开发日志，不记作行为红例：缺失 __user/__iomem/ARRAY_SIZE/EPROBE_DEFER、旧源 O2 uninitialized 警告、shim 声明顺序/unused、readonly括号警告等均单独修正。kbuild-object-v1 缺 dtc PATH 在编译前退出；v2/v3 用实际 ABI scripts/dtc/dtc 完成，不覆盖原失败目录。

## 交给独立审查与 C3 的未完成项

1. CPU precheck 相对 generic DMA component 的实际执行顺序，START 后续 CPU 错误的 C3 rollback，STOP 保 CPU/link 首错仍 terminate 当前所有 DMA component，以及 PCM allocation checked/quarantine 和 callback 屏障，均必须合测。当前 CPU 测试不运行 generic DMA/PL330，CPU停稳不能证明 descriptor 安全释放。
2. 全内核/真实 PREEMPT_RT lockdep、实际 inactive runtime-PM 回调嵌套与完整 probe devres/ALSA 注册并发未运行；本轮真实 probe 测的是 byte-exact 初始配置 block 和 SoC/profile/state，未称完整 probe 故障模拟。probe 注册尾部 PM cleanup 改动还需完整内核或专门 devres 生命周期合测。
3. 此 driver 的旧控制/其它 profile 未包含在 checked 路径 acceptance；必须逐个核查实际 card controls 是否会绕过配置 gate，本轮未将通用 mixer/control 写声明为闭合。
4. full-duplex 跨方向 DMA ownership 契约后续单独实现；当前第二方向 active 冲突属于公开限制。硬件 FIFO deadline、MMIO有效性、实际 IRQ号及 clock-summary、声音/外部端点、MCU/watchdog/复位行为仍是上板阶段。

所有普通退出失败均应留救援，无自动 reset；只读观测没有永久撤销后续 opens 的接口，需要受控、独占测试会话与 DMA 端证明。父任务完成独立审查与 C3 后再分派下一轮，当前按要求释放本子任务槽位。
