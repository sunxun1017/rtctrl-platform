# rtctrl-platform

面向机器人端侧的可移植 Linux 实时控制平台。RK3588 是首个目标而非架构前提；第一阶段不依赖 ROS，提供 1 kHz I/O、200 Hz 控制、固定容量数据通路、故障注入和时延基准。ControlLink V1 已打通固定帧编解码、UART 短包重组、CRC32C、会话重放防护与接收端租约。

## 设计目标

- 实时域仅执行定长 POD 数据处理；循环内不分配内存、不写日志、不做阻塞 I/O。
- `IRealtimePlatform`、HAL、control、transport、protocol 与 bridge 边界彼此解耦。
- I/O 线程为 1 kHz，控制线程为 200 Hz，命令通过有效期租约防止陈旧指令下发。
- `SCHED_FIFO`、CPU 亲和性和 `mlockall` 不可用时，默认安全回退到普通调度并报告能力；`--strict-rt` 可改为失败即停止。
- WSL 运行 POSIX + 模拟 HAL；Linux/RK3588、UART/SPI/NearLink 与 ROS 2 都通过叶子适配器接入。仓库已提供 POSIX 串口适配器，SPI 和 ROS 2 保持可选。
- 启动默认保持未武装状态；演示也必须显式传入 `--arm` 才允许普通控制指令进入 HAL。

## 快速开始（WSL）

```bash
cd /home/sx/projects/rk3588-rt-control
cmake --preset release
cmake --build --preset release -j8
ctest --preset release
./build/release/rtctrl_frame_demo
./build/release/rtctrl_demo --duration 5 --arm --no-mlock
./build/release/rtctrl_bench 5 1000
```

或执行：

```bash
./scripts/check.sh
./scripts/verify-install-and-signal.sh
```

普通用户通常没有 `SCHED_FIFO` 权限，因此输出中出现 `scheduler=fallback` 是预期行为。不要把 WSL 时延结果作为 RK3588 的硬实时验收结论。

板端验收可给 benchmark 设置门禁，任一条件失败都会返回非 0：

```bash
RTCTRL_MAX_JITTER_US=200 RTCTRL_MAX_SKIPPED_PERIODS=0 \
RTCTRL_REQUIRE_FIFO=1 RTCTRL_REQUIRE_MLOCK=1 \
./build/release/rtctrl_bench 60 1000 2 80
```

内核只读审计：

```bash
./kernel/scripts/check-kernel.sh
./kernel/scripts/check-kernel.sh --strict  # CI/板端验收模式
```

生产与诊断 Kconfig、systemd 模板和目标板使用边界见 [`kernel/README.md`](kernel/README.md)。脚本不会修改运行内核、WSL 全局配置、IRQ 或 sysctl。

## 故障注入

下面命令在 1 秒后模拟 HAL I/O 故障，验证安全指令和故障统计：

```bash
./build/release/rtctrl_demo --duration 3 --arm --fault-after-ms 1000 --no-mlock
```

## 目录

```text
apps/                 演示程序和独立周期基准
include/rtctrl/       稳定接口、数据模型与实时容器
src/platform/         平台无关周期器与 POSIX 适配器
src/hal/              模拟或真实执行器后端
src/control/          可替换控制算法
src/protocol/         固定长度 ControlLink V1 与 CRC32C
src/transport/        loopback、POSIX UART、分帧命令源
src/safety/           命令租约、边界与故障策略
src/runtime/          双速率线程和数据流编排
tests/                零第三方依赖的单元测试
docs/                 架构与部署说明
kernel/               Kconfig、只读检查器与 systemd 模板
config/               portable / strict 运行意图配置
cmake/toolchains/      不绑定板卡的交叉编译入口
```

协议字节布局、跨时钟域租约与 MQTT/NearLink 边界见 [`docs/control-link-v1.md`](docs/control-link-v1.md)。安装后会导出 `rtctrlTargets.cmake`，下游项目可通过 CMake package 集成，而不必复制源码。
本轮可复现构建、sanitizer、信号停机与 WSL 功能基线见 [`docs/verification-v0.3.0.md`](docs/verification-v0.3.0.md)。

## 交叉构建

安装 `riscv64-linux-gnu-g++` 后可验证 RV64 编译：

```bash
cmake --preset riscv64
cmake --build --preset riscv64 -j8
```

RK3588 使用相同工具链入口，将 `RTCTRL_TARGET_TRIPLE` 设为 `aarch64-linux-gnu`，有板厂 sysroot 时再传入 `RTCTRL_SYSROOT`。交叉产物只证明 ABI/编译可移植性，实时性仍必须在目标板测量。

## 开源参考

- [Linux PREEMPT_RT](https://www.kernel.org/doc/html/latest/core-api/real-time/index.html)（GPL-2.0）：完全可抢占与线程化 IRQ 的目标运行环境。
- [rt-tests/cyclictest](https://git.kernel.org/pub/scm/utils/rt-tests/rt-tests.git/)（GPL-2.0-only）：外部唤醒延迟基准。
- [Rigtorp SPSCQueue](https://github.com/rigtorp/SPSCQueue)（MIT）与 [Boost.Lockfree](https://github.com/boostorg/lockfree)（BSL-1.0）：固定容量 SPSC 与缓存行隔离思路；本仓库实现为独立的最小 C++17 版本。
- [Orocos RTT](https://github.com/orocos-toolchain/rtt)（GPL + runtime exception）：借鉴 Component/Port/Activity 的边界设计，但不引入其运行时依赖。

本项目采用 MIT License。Linux、rt-tests 与其他参考项目仍遵循各自许可证；仓库不复制它们的源码。
