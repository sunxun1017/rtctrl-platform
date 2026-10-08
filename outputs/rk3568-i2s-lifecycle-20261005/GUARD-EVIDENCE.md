# CPU 停稳证据与重启候选门槛

本文件只描述待审查的 v8 软件接口与后续守卫输入。没有部署或运行上板守卫，没有实机 MMIO/FIFO/IRQ/clock 验收；当前仍禁止音频 START。

## 只读接口

候选在 checked profile 完成 component/PCM 注册后，通过 devm_device_add_group 注册 0444 的 `rk3568_lifecycle_state`。按已确认 fe410000 设备发现实际 sysfs 名称，预期路径为 `/sys/bus/platform/devices/fe410000.i2s/rk3568_lifecycle_state`，不能凭设备名猜测成功。旧内核、非本次 profile、注册失败或接口缺失都必须拒绝许可。

读取在 I2S 锁内快照状态，随后格式化文本；不触发 MMIO、PM 获取、钟操作，不披露子流指针。`ready` 以 READ_ONCE 配对发布。示例为候选的测试夹具结果，非实机输出：

```text
version=1 ready=1 error=0 owners=0 open=0 stop_proven=1 stop_reads=2 irq_live=0 irq_drained=1 mclk_leases=0 hclk_lease=1 configuring=0 power_transition=0 shutting_down=0
```

| 字段 | 含义与普通重启候选值 |
| --- | --- |
| version / ready | 格式版本 1，当前注册完整，必须 1/1。 |
| error | 实例首个硬件/PM errno，永不由 STOP/close/retry 清除；必须 0。 |
| owners / open | playback bit0、capture bit1；START owner 与已发布子流分别记录，必须均 0。 |
| stop_proven | STOP 的真实 force-write、FIFO clear 和直接 MMIO readback 均成功的历史证据；必须 1。0 表示不确定；START 前先撤销。 |
| stop_reads | 完成前序 STOP 清理后进行直接 readl 的累计次数；必须大于 0，仅计数不能代替 stop_proven/error。 |
| irq_live / irq_drained | ISR 软件入口 gate 与最近 process synchronize_irq 完成证据；必须 0/1。 |
| mclk_leases | 本驱动拥有 TX/RX 一对 enable/prepare 引用的布尔值，不是全局 CCF 计数；必须 0。 |
| hclk_lease | 本驱动所持 HCLK 引用，绑定而 idle 时应为 1；它负责后续受控退出释放。 |
| configuring / power_transition / shutting_down | 必须全 0；事务或破坏过程中的中间状态拒绝许可。 |

force STOP 同时关闭 TX/RX IRQ 与 DMA request、XFER 两方向，延时后有限次 FIFO clear；双 timeout 返回 -ETIMEDOUT，不把本板没有实现的同步 reset 当成功。随后以直接 readl 读取 XFER/DMACR/INTCR，对应 START/request/IRQ-enable 位均为 0 才给 stop_proven，规避 FLAT cache 同值跳过硬件写。readl 只证明驱动观察到寄存器值；真实硬件有效性、FIFO 延时与 DMA 退出需要后续实机验收。

## 根守卫仍要合并的条件

1. 在受控救援会话中关闭使用者并阻止新的 PCM 打开，核实两方向无 FD/进程 owner；只读快照本身不阻止另一个调用者随后 START。无独占控制条件时不能把它当无竞态的重启许可。
2. 等待真实 runtime suspend 后读取以上所有 CPU 条件；缺字段、解析失败、sticky、不确定、未排 IRQ、有钟引用或事务位任一不符即拒绝。正常 close 返回 0 或进程退出只是触发清理，不能跳过本检查。
3. 独立检查 0011 对当前 DMA 子流的 checked STOPPED、无 descriptor/callback/stream lease、无 quarantine、无 poison/未排空状态。CPU STOP 不能终止 PL330，也不能证明另一个 DMA allocation 可释放；目前 C3 尚未合测，缺此证据必须拒绝。
4. 保存真实 clock-summary 中对应 TX/RX 的 prepare/enable 引用证据并与本驱动 lease 对照。全局 CCF 可能有其它 owner，名称和引用不能用本字段冒充或猜测。只读接口禁止为采样临时重新获取 PM/MCLK。

正常退出失败时留在救援，不自动重试 START，不 unbind、不 warm reboot、不触发板复位来掩盖缺失证明。候选 remove/platform shutdown 在已有 open/START owner、无法 PM 获取、STOP/FIFO/readback 失败时使用 panic_timeout=0，阻止继续 devres 释放；它是最后的软件 fail-stop，不能作为正常守卫测试方法。外部 MCU/watchdog 或电源管理可能仍能复位硬件，尚未测量或建立阻止契约，不能宣称 panic_timeout=0 提供物理断电/不复位保证。

## 验证边界

state/profile 初始配置测试摘录了真实 C 与 byte-exact probe 注册前的四个配置操作（TDL/RDL/TRCM/GRF）；它没有模拟整个 devres/ALSA 注册过程。IRQ 测试以可控 barrier 覆盖已捕获旧子流的 ISR 与 shutdown 的排空顺序；PM API 为边界模型，尚未完整合测真实 inactive runtime-PM→resume→remove 嵌套回调、全内核 lockdep 或 callback 关停。最终 Kbuild 对象证明完整实际 C 对真实头文件/config 可编译，不证明内建 Image 链接或上板行为。
