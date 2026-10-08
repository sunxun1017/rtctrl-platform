# RK3568 CPU I2S 生命周期候选计划

2026-10-05。只在本目录生成离线源码、摘录测试和候选 diff；不改原内核、不发布 0012、不重建生产 Image、不接触硬件。主控负责与 0011 整合和独立审查。

锁定输入为内核 `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`、I2S C `53de554206b13f13e480280b8f46366778c2837cdcba2cdb1417e0127be7ffda`、已测 config `1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912`、audio DTB `9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478`。依据见 [CPU 审查](../rk3568-audio-runtime-20261005/CPU-I2S-AUDIT.md)。本轮实际对象是 fe410000 I2S1、TRCM1、master、普通 I2S、无 quirks/calibration/multiplex/multi-lanes。

## 分块与验收

1. 参数：保留真实函数和 ABI 的原始字节快照；先执行原驱动的 clock/read/write 逐点红例，再补 channels/dirty 的 errno 与结果分离、TRCM 三写及 hw_params 接线、set_fmt PM 获取/四写、输入校验。I/O 或实际硬件配置后的 clock 失败锁存实例首错；纯无效参数不 poison。
2. START/STOP：当前路径方向 ownership 采用独立 bit；START 全成功才发布，失败保首错并尽力停止。STOP-before-START、重复 START/STOP 幂等；即使 sticky 仍尝试 IRQ/DMA/XFER/FIFO 清除，STOP 用 force-write 防 cache 假成功，clear 双 timeout 不接受无实际 RK3568 reset 的成功。
3. 调用入口：startup、hw_params、DAI prepare、START-like 拒绝 sticky；CPU component.trigger 仅预检，不做硬件 START，实际 DAI 二次检查。保留其它 SoC、slave/multi-lanes/HDMI 分支，不声明这些路径完成。
4. CPU IRQ 生命周期：锁内 READ_ONCE/WRITE_ONCE 指针发布/撤销；ISR 已取指针后必须离开 I2S 锁再调用 XRUN。process shutdown 在撤销、尽力停止和解锁后 synchronize_irq，禁止在 trigger/ISR/spinlock/ALSA stream-lock 等 IRQ。
5. PM/退出：cache-sync 失败恢复 cache-only；保存 IRQ 和 MCLK 引用状态；关钟前撤销入口并排 IRQ；未停稳拒绝 suspend。remove/shutdown 的 errno 不能保护 devres，须先确定停止证明，无法证明则 panic_timeout=0 fail-stop，不 warm reboot/继续释放。
6. 独立审查与 C3 合测：检查 current substream CPU START 失败是否真正终止已提交 DMA、STOP 首错仍清理所有 component，以及两个独立 IRQ/PL330 callback 屏障。本阶段只编译完整候选 C 的真实 Kbuild AArch64 对象；最终 built-in Image 链接、生产包和上板属于主控整合阶段。

## 双向未闭合边界

主控已裁决：0011 C3 只闭合当前 substream，首版 CPU 候选在同一锁事务拒绝另一方向已 START 时的第二 START，任何 active 下改参数返回 -EBUSY，纯冲突不 poison；两方向可分别单向运行。CPU 请求关闭不能证明 PL330 通道 STOPPED。全双工需要单独的跨方向 stop/owner 契约，不能用全实例 sticky 代替硬停。

## 本轮冻结状态

最终候选为 driver-source-v8。真实参数、START/STOP、IRQ、PM、probe 初始配置/profile/只读状态五套测试在 host、ASan/UBSan、ARM64/QEMU 各通过 140/81/27/25/31 项；实际 DT 单独读取后驱动真实 profile 函数再次通过 31 项。完整 C 已通过原 config/ABI 的 Kbuild AArch64 对象编译。首错、并发方向 START、FLAT cache 写失败、MMIO 返回成功但实际 XFER 尚 START、双 FIFO timeout、捕获旧 IRQ 指针后的 shutdown 屏障均有负例。

只读状态接口保存 sticky、方向 owner/open、stop_proven/stop_reads、IRQ gate/drain、clock lease 与事务位，读取不触发 MMIO 或 PM。普通重启候选条件见 GUARD-EVIDENCE.md，仍需要 0011 的 DMA STOPPED/poison/quarantine/lease 证据；当前未实现合测守卫，不允许 START、不允许把无 FD 或 DROP/close rc0 当停稳。

本轮按主控要求提交离线冻结物并释放审查槽位。独立审查、C3 合测、完整 Image/上板仍未完成；保留所有失败目录，不能发布或部署此候选。

## 证据纪律

所有结果使用未存在的 vN 目录，保存 source、真实摘录、头文件、harness、编译命令/版本/输出/SHA 和机器结果。host、ASan/UBSan、ARM64/QEMU 三运行以相同真实摘录测试；失败结果保留。MMIO/regcache/clock/IRQ 模型只验证软件边界，不能证明真实 FIFO、电气、DMA 或物理声音。未闭合事项单列，绿色测试不标记 deployable。
