# rtctrl-mailbox 内核驱动

该模块面向“伴随实时端点”，不是 RK3588 自带外设或星闪模组驱动。只有 FPGA、MCU 或 RISC-V 固件实现本页寄存器/DMA 契约，且设备树提供真实 MMIO、IRQ 资源后，才能在目标板加载。UART 型星闪模组应走标准 UART/serdev，再由普通域网关接入控制协议。

## 版本与访问边界

- endpoint hardware ABI：V2，对应 `compatible = "sx,rtctrl-mailbox-v2"`、DMA layout 和寄存器 `ABI_VERSION=2`。
- userspace UAPI：V2，提供 `GET_INFO`、`SUBMIT_COMMAND`、`READ_FEEDBACK`、`ARM`、`DISARM`、`GET_STATS`。
- coherent DMA 只在内核和端点之间共享。用户态不能 mmap，也不能直接写环索引；驱动在每个 fd 的 staging 中收帧，验证后才复制到 DMA。
- 设备树必须给出 `sx,joint-count`；layout、command、feedback 与用户态 profile 必须精确一致，不能用“最大 64”掩盖缺失关节。
- 设备树必须提供名为 `mailbox` 的独占硬复位线。remove/suspend/shutdown 在 DMA 静止握手失败时用它强制停止 bus master；若 remove 时两者都失败，驱动故意不归还 coherent 缓冲，避免故障设备写入已复用内存。
- 仅允许一个 opener。fd 用 kref 保持 host 对象生命周期；remove 后已有 fd 返回 `ENODEV`，不会触碰已释放的 MMIO/DMA。

`sx` 是实验性 vendor prefix；向主线提交前需在 Linux `vendor-prefixes.yaml` 注册。实现遵循 Linux 官方的 [misc device](https://docs.kernel.org/driver-api/misc_devices.html)、[DMA API](https://docs.kernel.org/core-api/dma-api-howto.html) 和 [DT schema](https://docs.kernel.org/devicetree/bindings/writing-schema.html) 边界。

## 寄存器契约

所有寄存器为 32 位 little-endian MMIO：

| Offset | 名称 | 方向 | 语义 |
|---:|---|---|---|
| `0x00` | CONTROL | Host→HW | bit0 输出使能；bit1 RESET（端点完成后自清零）；写 0 立即禁能并请求停止全部 DMA |
| `0x04` | STATUS | HW→Host | bit0 READY，bit1 FAULT，bit2 DMA_QUIESCED |
| `0x08` | IRQ_STATUS | HW→Host | bit0 RX_READY，bit1 FAULT |
| `0x0c` | IRQ_ACK | Host→HW | write-one-to-clear |
| `0x10` | TX_DOORBELL | Host→HW | 已发布的 command producer |
| `0x14` | TX_CONSUMER | HW→Host | 设备已消费的 command consumer |
| `0x18/1c` | DMA_ADDR | Host→HW | coherent DMA 总线地址低/高 32 位 |
| `0x20` | DMA_BYTES | Host→HW | DMA 区总字节数 |
| `0x24` | ABI_VERSION | Host→HW | endpoint hardware ABI，当前为 2 |

命令和反馈环都使用 32 位单调 producer/consumer。驱动维护可信 command producer shadow，读取硬件 `TX_CONSUMER` 判断背压；写完整 slot 后执行 `dma_wmb()`，再发布 producer 与 doorbell。端点写完整 feedback slot 后发布 producer，再触发 IRQ；驱动观察 producer 后执行 `dma_rmb()` 才读取 payload。任一方向的 pending 大于深度 8 都视为协议破坏并锁存故障。

## 安全状态机

1. probe、open、resume 都保持 DISARMED；close、DISARM、suspend、shutdown、remove 先清 CONTROL，再同步普通 ioctl、hrtimer 与 DMA_QUIESCED。
2. 用户页 copy 不持有 `transition_lock`，因此 userfault/缺页不能卡住硬件优先的关断路径。
3. `ARM` 需要 `CAP_SYS_RAWIO`、READY=1、FAULT=0，并要求本会话先提交仍有至少 1 ms 租约的 SafeStop。
4. SafeStop 必须满足每关节 velocity=0、effort=0、kp=0、有限 position，以及有限非负 `kd<=1000`。端点仍必须把 SAFE_STOP 当作高优先级模式，忽略任何普通驱动力输出。
5. command 和 feedback 的 64 位传输序号在会话内必须严格递增；重复/倒序帧不能刷新租约。
6. 已武装状态只有通过完整验证且仍有至少 1 ms 剩余租约的 command submission 才刷新 watchdog。独立 heartbeat 不存在。
7. watchdog 取“命令租约截止”和“最后一次已接受提交 + timeout”的较早值；fault IRQ、非法帧和超时都会关断并进入 FAULTED。
8. CONTROL=0 后端点必须停止所有 DMA 并置 DMA_QUIESCED；驱动确认后才进入 DISARMED、清空或释放 coherent 区。RESET 自清零并复位端点环计数器，独立 reset controller 是生命周期兜底。
9. suspend 进入 SUSPENDED；resume 完成 QUIESCED/RESET 握手，再初始化 DMA 地址、环、硬件 ABI、IRQ ACK 和 session epoch，最后回到 DISARMED，不自动 ARM。

结构性 SafeStop 校验不能替代设备相关的关节位置/速度/力矩限制。本机端点还必须有独立 watchdog；整机仍需 STO、限位、制动和急停回路。

## 构建

要求配置好的 Linux 6.1+ 内核构建树：

```sh
./kernel/scripts/build-module.sh /absolute/path/to/linux-build
```

脚本只生成 `.ko` 等构建产物，不执行 `sudo`、`insmod`、设备树覆盖或系统配置变更。
