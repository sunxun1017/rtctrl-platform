# v0.5.0 验证记录

验证日期：2026-09-01

## 新增范围

- Linux C platform/misc 驱动：设备树资源、coherent DMA、IRQ、固定大小 staged ioctl、硬件优先关断、命令租约和 hrtimer watchdog。
- userspace UAPI V2 与 endpoint hardware ABI V2 使用独立常量；固定 64 关节上限、8 深度双向 DMA 环、session epoch、能力/状态/统计接口。
- C++17 `KernelMailboxHal`：反馈新鲜度、独立传输序号、ARM 前 SafeStop、RAII 关闭；用户态不映射设备 DMA。
- DT binding、Kconfig/Kbuild、只构建不加载的模块脚本，以及 Ubuntu 24.04 CI 模块编译任务。
- 通用 AArch64 与 RV64 交叉编译 preset；目标 triple/sysroot 会传递到 CMake 内部 `try_compile`。

## 已通过

用户态环境：Ubuntu-22.04 WSL，GCC 11.4.0，CMake 3.22.1，Ninja。

| 配置 | 结果 |
|---|---|
| Release，默认 6 关节 | 全部目标构建成功；2/2 CTest 通过 |
| Release，Yidong 23 关节 | 全部目标构建成功；2/2 CTest 通过 |
| ASan + UBSan，默认 6 关节 | 全部目标构建成功；2/2 CTest 通过 |
| C UAPI 独立编译 | UAPI/HW 版本、布局、对齐、3 个 ioctl size 静态断言通过 |
| 安装导出与 SIGTERM | 下游 CMake package 链接及进程安全停止路径通过 |
| AArch64 交叉构建 | `rtctrl_demo` 为 ARM aarch64 ELF，构建成功 |
| RV64 交叉构建 | `rtctrl_demo` 为 RISC-V LP64D ELF，构建成功 |
| DT YAML 基础语法 | PyYAML 解析通过 |
| module build Shell | `sh -n` 通过 |
| Linux 外部模块（兼容性） | Ubuntu `5.15.0-190-generic` 头文件成功生成 GPL `.ko` |
| Linux 外部模块（目标版本） | Ubuntu HWE `6.8.0-138-generic`、GCC 12、`W=1` 成功生成 GPL `.ko`，无驱动源码警告 |

内核模块构建命令：

```sh
./kernel/scripts/build-module.sh /usr/src/linux-headers-5.15.0-190-generic
CC=gcc-12 ./kernel/scripts/build-module.sh /usr/src/linux-headers-6.8.0-138-generic
```

6.8 模块的 `modinfo`：license 为 GPL，description 为 `Robot kernel-staged coherent-DMA mailbox with watchdog`，vermagic 为 `6.8.0-138-generic SMP preempt mod_unload modversions`。提交前已清理 `.o/.ko/Module.symvers` 等构建产物。

## 重点安全复审

- 用户命令先复制到 per-file staging，再取得状态转换锁；反馈在锁内形成内核快照，解锁后才复制给用户。因此 userfault/缺页不会阻塞 DISARM/remove/suspend 的 CONTROL 清零。
- SafeStop 不能仅靠 flag 伪装：内核要求 velocity/effort/kp 为 IEEE 零、position 有限、kd 有限非负且不超过 1000。
- 设备树、DMA layout、内核命令/反馈校验与 C++ profile 的实际关节数必须精确一致，避免部分关节 SafeStop 被误认为整机安全。
- command 与 feedback 传输序号严格递增；重复或倒序帧锁存协议错误，不能续租。
- 发布 doorbell 和 ARM 前重新采样单调时钟，剩余租约不足 1 ms 就拒绝，避免把已过期或即将过期的帧交给端点。
- hrtimer 在 CONTROL enable/doorbell 前按绝对截止时间启动；STOPPING/DEAD/SUSPENDED 不会被 IRQ 覆盖。
- remove 后 fd 由 kref 保活但只能得到 `ENODEV`；resume 重新写 DMA 地址、大小、hardware ABI、IRQ ACK，清环并递增 session，不沿用掉电前状态。
- DISARM/close 必须确认 DMA_QUIESCED 才进入 DISARMED；remove/suspend/shutdown 还用独占 reset controller 兜底，双重失败时不回收 coherent 内存。

## 未伪报的限制

- 当前 WSL 内核是 `6.18.33.2-microsoft-standard-WSL2`，没有对应构建头文件；模块未加载到 WSL。5.15/6.8 结果是 API 与编译兼容证据，不是真机功能证据。
- WSL 的 Windows 挂载目录产生小于 0.1 秒的 clock-skew 提示；缺少匹配 `vmlinux` 时 BTF 被跳过。两者不属于驱动源码警告。
- TSan 在当前 WSL 地址空间初始化阶段失败，故不声明本地 TSan 通过；仓库保留原生 Ubuntu CI 的 TSan 任务。
- 未加载模块、未写设备树 overlay、未修改 WSL 内核/sysctl/IRQ affinity，也未连接真实 RK3588、EtherCAT、星闪或 RISC-V/FPGA 端点。
- hardware ABI V2 仍需端点实现 RESET/DMA_QUIESCED 握手并接入可靠的硬复位线；host 的 1 ms 剩余租约门禁和 hrtimer 不替代端点 watchdog、STO 与机械制动。

## 真机下一步

1. 在目标 RK3588 BSP 的配置树重新运行模块构建和 `dt_binding_check`。
2. 用禁能执行器的 FPGA/伴随控制器验证 producer/consumer wrap、重复序号、NaN、短租约、fault IRQ、suspend/resume 和 overlay remove。
3. 接入 EtherCAT 后以 `perf`、`cyclictest` 和 ftrace 测量 IRQ→反馈、submit→doorbell、1 kHz 周期抖动及最坏执行时间；据数据配置 PREEMPT_RT、CPU/IRQ 亲和性。
4. 接入 STO 后测量“停止提交→CONTROL 清零→端点停机→机械制动”四段时延，并把阈值变成板端门禁。
