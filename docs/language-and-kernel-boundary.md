# 编程语言与内核边界决策

## 结论

| 层 | 语言 | 选择原因 |
|---|---|---|
| Linux platform/misc 驱动、UAPI | C | 直接使用 platform、DMA、IRQ、hrtimer、ioctl 与设备电源管理 API，便于传统 RK3588/RISC-V BSP 审核和移植 |
| 实时 runtime、控制、安全、HAL | C++17 | 固定容量容器、RAII、强类型接口和可替换叶子适配器；不依赖 GC |
| 设备树 binding | YAML | 用 schema 描述真实 MMIO、IRQ、DMA 和 watchdog 参数，不在源码写死板卡资源 |
| 构建与板端检查 | POSIX Shell + CMake | WSL、ARM64 与 RV64 共用入口；脚本不进入实时路径 |
| 离线训练/分析 | Python | 服务 PyTorch、仿真和数据处理，只输出模型或参数，不进入 1 kHz 环 |

Linux 内核不提供标准 C++ 运行时，异常、RTTI 和标准库对象生命周期也不适合这个小型驱动边界。Rust-for-Linux 有内存安全优势，但各家 BSP 的内核、Rust 支持和工具链差异仍大；本版选 C 以覆盖传统 BSP，同时保持 UAPI 独立，未来可替换内核实现。

## 内核承担什么

- 从设备树取得 MMIO、IRQ、实际关节数和 watchdog 参数，分配仅供内核与端点访问的 coherent DMA 环。
- 通过 UAPI v2 固定大小 ioctl 接收/返回帧；用户态不 mmap DMA，也不能修改 producer/consumer。
- 用户页复制使用每个 fd 独立的预分配 staging，并在安全状态锁之外完成，缺页不会阻塞 DISARM/remove/suspend 清除 CONTROL。
- 校验关节数、有限浮点、租约、会话内严格递增序号、环容量与 SafeStop 约束，再发布 DMA slot 和 doorbell。
- SafeStop 强制 velocity/effort/kp 为零，kd 为 `[0, 1000]` 的有限非负值；只允许它作为 ARM 前置命令。
- 在发布和 ARM 前重新读取 `CLOCK_MONOTONIC`，要求至少剩余 1 ms 租约；以租约截止和 watchdog 截止的较早者驱动绝对 hrtimer。
- fault IRQ、超时、close、DISARM、suspend、shutdown 和 remove 均先清硬件使能；进入 DISARMED 或释放 DMA 前确认 DMA_QUIESCED，生命周期路径另有独占硬复位线兜底。热移除后的 fd 由 kref 保活，只返回 `ENODEV`，不再访问 devres。
- resume 保持禁能，并重写 DMA 地址、大小、硬件 ABI、IRQ ACK，清空环且递增 session epoch，绝不自动重新武装。

## 用户态承担什么

- C++ HAL 将逻辑关节模型转换成 C UAPI 帧，用独立传输序号防重放，并执行“先反馈、后 SafeStop、再 ARM”。
- runtime 负责控制算法、边界约束、QoS/线程调度、ROS 2 或其他中间件适配。
- MQTT、日志、配置解析和策略网络推理留在非实时线程或进程；EtherCAT、UART/星闪和 ROS 2 都是可替换叶子模块。

UAPI 版本与端点硬件版本被刻意拆开：用户态 ioctl 当前是 `RTCTRL_MB_UAPI_ABI_VERSION=2`；端点为 `RTCTRL_MB_HW_ABI_VERSION=2`，相较原始草案增加 DMA_QUIESCED 与 RESET 握手。两者本次恰好同为 2，但以后可以独立演进。

## 诚实边界

仓库实现的是 host 驱动、HAL 与协议契约，需要 FPGA、MCU 或 RISC-V 固件实现对应寄存器/DMA 端点后才能上真机；它不是 RK3588 原生 mailbox、星闪射频驱动或 EtherCAT master。1 ms 发布裕量是 host 侧拒绝窗口，不替代端点独立 watchdog、驱动器 STO、限位、制动和真机时延测量。
