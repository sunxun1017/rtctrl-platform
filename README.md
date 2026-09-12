# rtctrl-platform

面向机器人端侧的可移植 Linux 实时控制平台。RK3588 是首个目标而非架构前提；第一阶段不依赖 ROS，提供 1 kHz I/O、200 Hz 控制、固定容量数据通路、故障注入和时延基准。ControlLink V2 已打通固定 profile 帧编解码、UART 短包重组、CRC32C、会话重放防护与接收端租约。

## 当前能力与限制

| 入口 | 当前用途 | 验证边界 |
| --- | --- | --- |
| `release` / `control-sim` | 模拟控制、协议与时延基准 | 主机结果不等于板端硬实时保证 |
| `vision-synthetic` | 无摄像头采集演示与测试 | 不编译 V4L2 |
| `robot-vision` | 视觉语义事件到模拟控制的回放 | 不代表生产视觉服务已完成 |
| [独立视频预览](apps/video_preview/README.md) | RV1126B DMA-BUF 采集、RGA 缩放、MPP JPEG、浏览器预览 | 已做板端短测；不加载模型，不参与控制闭环 |

1 kHz I/O、200 Hz 控制是运行配置与设计目标，实际调度、抖动和设备响应需在目标板验收。
RV1126B 与无 B 后缀的 RV1126 使用不同平台配置，不能混用部署说明。

## 环境依赖

默认主机开发在 Linux / WSL 中进行，需要 Git、CMake 3.21 或更新版本、Ninja、
支持 C++17 的 GCC/Clang，以及 Python 3（项目检查脚本）。预设文件使用 schema v3，
不能仅依据 `CMakeLists.txt` 的 3.16 最低版本判断 `--preset` 是否可用。

Ubuntu 22.04 可安装基础依赖：

```bash
sudo apt update
sudo apt install build-essential cmake ninja-build git python3
```

格式检查另外需要 clang-format 14 或更新版本，见 [贡献指南](CONTRIBUTING.md)。
默认主机构建无需下载内核和厂商 SDK 子模块；板级构建按
[平台说明](platforms/README.md)与[第三方清单](third_party/README.md)初始化对应依赖。
板端独立预览使用 Python 3、GStreamer、V4L2 和 Rockchip MPP/RGA 插件，
不需要在板端编译本项目 C++ 目标，具体检查命令见应用文档。

## 快速开始（WSL）

```bash
git clone <repository-url> rtctrl-platform
cd rtctrl-platform
cmake --preset release
cmake --build --preset release -j8
ctest --preset release
./build/release/rtctrl_frame_demo
./build/release/rtctrl_demo --duration 5 --arm --no-mlock
./build/release/rtctrl_bench 5 1000
```

完成环境准备后，也可依次运行以下脚本；第二个脚本依赖第一个生成的 release 产物：

```bash
./scripts/check.sh
./scripts/verify-install-and-signal.sh
```

23 关节 profile：

```bash
cmake --preset humanoid23
cmake --build --preset humanoid23 -j8
ctest --preset humanoid23 --output-on-failure
./build/humanoid23/rtctrl_frame_demo
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
./kernel/scripts/build-module.sh /absolute/path/to/linux-build
```

生产与诊断 Kconfig、systemd 模板和目标板使用边界见 [`kernel/README.md`](kernel/README.md)。脚本不会修改运行内核、WSL 全局配置、IRQ 或 sysctl。
编程语言选择和内核/用户态职责见 [`docs/language-and-kernel-boundary.md`](docs/language-and-kernel-boundary.md)。

## 应用入口

- [RV1126B 独立视频预览](apps/video_preview/README.md)：首次部署、浏览器访问、停止服务及软件/硬件对比。
- [RV1126B 板级配置](docs/rv1126b.md)：BSP、用户态交叉构建与板端验收。
- [产品部署边界](deploy/README.md)：控制与视觉运行域的部署约束。

视频预览直接运行 `apps/video_preview/preview.py`，不会由 `cmake --build` 自动部署。

## 架构与构建入口

项目采用端口与适配器、显式产品装配、控制/视觉运行域隔离。实时核心通过抽象
连接控制器和执行器；通用协议 HAL、具体电机协议与链路分别构建。
采集核心使用可注入 C 后端端口，V4L2 与无硬件 synthetic 后端共用同一个消费者。
颜色和像素格式使用平台契约，原生 SDK 类型与数值在适配器内部转换。

- [模块职责与端口归属](modules/README.md)
- [机器人产品配置](products/README.md)
- [公开头文件边界调整](docs/adr/0008-public-header-ownership.md)
- [v0.8 目录与接口迁移](docs/adr/0007-module-owned-ports.md)
- [当前架构与实现边界](docs/architecture.md)
- [v0.7 后端接口迁移与构建能力](docs/adr/0006-injectable-capture-and-adapter-capabilities.md)
- [v0.7 验证结果与限制](docs/verification-v0.7.0.md)
- [v0.6 实时入口迁移](docs/adr/0005-product-composition-and-domain-isolation.md)
- [产品部署边界](deploy/README.md)

```bash
cmake --preset vision-synthetic
cmake --build --preset vision-synthetic -j8
ctest --preset vision-synthetic
./build/vision-synthetic/rtctrl_camera_synthetic /tmp/frame.gray
```

`vision-synthetic` 完全不编译 V4L2；`control-sim` 不编译 mailbox、SocketCAN、原生
串口和 POSIX 共享内存映射。`release` 保留默认控制开发能力；`robot-vision` 提供
语义事件到模拟控制的回放闭环。生产视觉与控制的集成、恢复策略仍需单独验收；
独立摄像头预览已有板端实现，见上方应用入口。

## IDE / clangd

首次打开工程或修改 CMake 配置后，运行 `cmake --preset robot-vision`。
仓库的 `.clangd` 使用 `build/robot-vision/compile_commands.json`，覆盖控制和视觉
源码；默认 `release` 产品不包含视觉源码，不能为相机文件提供准确的编译参数。
人脸应用另由 .clangd 匹配到 build/face-video，需要先运行 cmake --preset face-video，其依赖见 [人脸应用说明](apps/face_recognition/README.md)。
无需把编译数据库复制到仓库根目录。若编辑器仍显示旧诊断，执行
`clangd: Restart language server`。内核源码继续使用 `.clangd` 中独立的内核配置。

如果 C++ 文件仍提示找不到 `cstdint` 等标准头文件，可在编辑器的 clangd 参数中
设置 `--query-driver=/usr/bin/c++,/usr/bin/cc`，允许 clangd 查询实际编译器的系统
头文件路径；编译器位于其他位置时替换为编译数据库中对应的可信路径。
不要把本机 GCC 版本目录硬编码进模块 CMake 或 `.clangd`。

## 设计目标

- 实时域仅执行定长 POD 数据处理；循环内不分配内存、不写日志、不做阻塞 I/O。
- `IRealtimePlatform`、HAL、control、transport、protocol 与 bridge 边界彼此解耦。
- 电机协议与通信链路分别注入；同一 codec 可部署在串口、CAN-FD 或 IgH EtherCAT link 上，runtime 不感知电机型号和总线类型。
- 串口执行器提供固定容量 Dynamixel Protocol 2.0、Sync Write/Bulk Read、半双工短写续传和可注入 Control Table profile。
- I/O 线程为 1 kHz，控制线程为 200 Hz，命令通过有效期租约防止陈旧指令下发。
- `SCHED_FIFO`、CPU 亲和性和 `mlockall` 不可用时，默认安全回退到普通调度并报告能力；`--strict-rt` 可改为失败即停止。
- WSL 运行 POSIX + 模拟 HAL；Linux/RK3588、UART/SPI/NearLink 与 ROS 2 都通过叶子适配器接入。仓库已提供 POSIX 串口和 Linux SocketCAN CAN-FD 帧级适配器，SPI 和 ROS 2 保持可选。
- 启动默认保持未武装状态；显式传入 `--arm` 后，还须等待调度门控、反馈和首条有效控制命令，才由 I/O 线程武装 HAL。
- 逻辑关节数是编译期 profile：默认 6 关节；`humanoid23` 使用从 `sx_text` 提炼的 23 关节/三 EtherCAT master 拓扑，不修改核心源码。
- L0 硬件进程与控制进程可通过版本化 POSIX 共享内存解耦；EtherCAT 可选用 IgH 1.6 `ecrt` 适配器；具备伴随控制器/FPGA mailbox 时，也可选择 Linux C 内核驱动的 kernel-staged ioctl + coherent-DMA + IRQ + hrtimer watchdog 路径。硬件 ABI V2 要求精确关节数、DMA_QUIESCED/RESET 握手和独立硬复位线；ROS 2、设备 PDO codec 和 ONNX Runtime 都留在叶子适配器。

## 故障注入

下面命令在 1 秒后模拟 HAL I/O 故障，验证安全指令和故障统计：

```bash
./build/release/rtctrl_demo --duration 3 --arm --fault-after-ms 1000 --no-mlock
```

## 目录

```text
modules/              按能力组织的库；每个模块有自己的 include、src、CMakeLists
adapters/             端口的具体实现；系统 I/O、硬件、厂商 SDK 和模拟后端
apps/                 产品入口，选择并注入模块和适配器
platforms/            SoC、板卡、BSP、SDK 与工具链配置
include/uapi/         用户态与内核共享 ABI
kernel/               内核驱动、DT binding、Kconfig 与部署模板
tests/                跨模块集成、产品回放和安装验证；专属测试随模块/适配器存放
deploy/               产品部署边界
docs/                 架构、迁移、板端与验证记录
config/               portable / strict 运行意图配置
cmake/                构建规则、依赖检查、安装与交叉工具链
third_party/          锁定版本的外部源码
```

协议字节布局、跨时钟域租约与 MQTT/NearLink 边界见 [`docs/control-link-v1.md`](docs/control-link-v1.md)。从本人 `sx_text` 分支提炼和改造的内容见 [`docs/sx-text-integration.md`](docs/sx-text-integration.md)。安装后导出各模块的 CMake target；下游通过 target 获得对应头文件路径。具体适配器只供源码树内的应用装配，不在公共 package 中导出。
当前 C UAPI、C++17 内核 mailbox HAL、6/23 关节构建与已知环境限制见 [`docs/verification-v0.5.0.md`](docs/verification-v0.5.0.md)；旧版记录仍保留在 [`docs/verification-v0.4.0.md`](docs/verification-v0.4.0.md)。
Linux CAN/CAN-FD 接口配置、`vcan` 环回、API 示例及与具体电机协议的职责边界见 [`docs/can-fd.md`](docs/can-fd.md)。
IgH master/domain/PDO/DC 生命周期、构建方法和真机边界见 [`docs/igh-ethercat.md`](docs/igh-ethercat.md)。
专用 Intel I210 PCIe 网卡、IgH native `ec_igb` 构建、通信依赖注入和实时部署边界见 [`docs/dedicated-ethercat-igb.md`](docs/dedicated-ethercat-igb.md)。
电机协议/链路正交、逻辑 endpoint 路由和组合式 HAL 决策见 [`docs/adr/0004-actuator-protocol-link-separation.md`](docs/adr/0004-actuator-protocol-link-separation.md)。
Dynamixel Protocol 2.0、U2D2/原生 UART 接线边界、型号 profile 和总线带宽见 [`docs/dynamixel.md`](docs/dynamixel.md)。
跨机器开发时的子模块初始化、版本锁定和内核 ABI 边界见 [`third_party/README.md`](third_party/README.md)；可运行 `./scripts/check-third-party.sh` 校验源码提交。默认构建不需要 IgH，也不依赖 Dynamixel SDK。

## 交叉构建

ARM64（包括 RK3588 用户态）与 RV64 使用同一个不绑定板卡的工具链入口：

```bash
cmake --preset aarch64
cmake --build --preset aarch64 -j8
cmake --preset riscv64
cmake --build --preset riscv64 -j8
```

有板厂 sysroot 时通过 `-DRTCTRL_SYSROOT=/absolute/sysroot` 注入。交叉产物只证明源码与 ABI 的编译可移植性，实时性仍必须在目标板测量。

正点原子 ATK-DLRV1126B 复用同一 ARM64/POSIX 核心，并提供独立的板级用户态部署 profile：

```bash
./scripts/cross-build-linux-userspace.sh \
    --platform atk-dlrv1126b \
    --sdk-root /absolute/path/to/atk_dlrv1126b_linux6.1_sdk \
    --plan
./scripts/cross-build-linux-userspace.sh \
    --platform atk-dlrv1126b \
    --sdk-root /absolute/path/to/atk_dlrv1126b_linux6.1_sdk
```

摄像头、RKISP/RKNN、板级设备树和 BSP 保持叶子集成，不进入 1 kHz/200 Hz
实时线程。支持边界、单 SoC 视觉数据流和板端验收步骤见
[`docs/rv1126b.md`](docs/rv1126b.md)。

RV1126B 内核使用 Rockchip GitHub 官方 Linux 6.1 submodule，并在独立构建
副本上叠加正点原子板级配置；不会修改或污染公共内核工作树：

```bash
./scripts/prepare-linux-kernel-source.sh \
    --platform atk-dlrv1126b \
    --build-dtb
```

完整 RK3588 构建采用“公共 SoC 配置 + 板卡 profile”。首次换开发机后：

```bash
git clone --recurse-submodules <repository-url>
cd rtctrl-platform
./scripts/bootstrap-aarch64.sh --install
./scripts/cross-build-rk3588.sh --board orangepi-5-max --plan
./scripts/cross-build-rk3588.sh --board orangepi-5-max
```

最后一条命令依次构建匹配 profile 的内核/DTB、mailbox 模块、IgH
`ec_master`/`ec_igb` 和 rtctrl ARM64 用户态。若只需要不含板卡内核依赖的用户态：

```bash
./scripts/cross-build-rk3588.sh --board orangepi-5-max --userspace-only
```

生成物和构建清单位于被 Git 忽略的 `.deps/`、`build/aarch64-*`。当前已验证板卡
profile 及新增其他 RK3588 载板的方法见 [`platforms/README.md`](platforms/README.md)。
内核子模块固定构建输入，但不能让生成的 `.ko` 跨内核 ABI 通用。

## 开源参考

- [Linux PREEMPT_RT](https://www.kernel.org/doc/html/latest/core-api/real-time/index.html)（GPL-2.0）：完全可抢占与线程化 IRQ 的目标运行环境。
- [rt-tests/cyclictest](https://git.kernel.org/pub/scm/utils/rt-tests/rt-tests.git/)（GPL-2.0-only）：外部唤醒延迟基准。
- [Rigtorp SPSCQueue](https://github.com/rigtorp/SPSCQueue)（MIT）与 [Boost.Lockfree](https://github.com/boostorg/lockfree)（BSL-1.0）：固定容量 SPSC 与缓存行隔离思路；本仓库实现为独立的最小 C++17 版本。
- [Orocos RTT](https://github.com/orocos-toolchain/rtt)（GPL + runtime exception）：借鉴 Component/Port/Activity 的边界设计，但不引入其运行时依赖。

本项目自有代码采用 MIT License。通过固定提交的 Git 子模块引入的第三方源码，
以及文中引用的外部项目，遵循各自许可证；详见 [第三方清单](third_party/README.md)。
