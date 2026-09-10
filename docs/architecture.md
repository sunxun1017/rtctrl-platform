# 平台架构（v0.7）

本文件描述已经落地的架构。产品规划见 `develop camera/roadmap.md`；规划中的
RKNN 推理、事件算法、远程设备管理不代表已有可部署实现。

## 设计选择

采用模块化单仓库、端口与适配器、显式依赖注入、产品组合根。
实时域采用固定容量消息与单硬件所有者；控制算法是可替换策略；生命周期采用
显式状态与故障锁存；采集采用句柄资源所有权和借用帧。
不使用服务定位器、动态插件系统、全局事件总线或厂商类型贯穿的统一 HAL。

产品入口依赖模块和适配器；模块依赖语义接口。板卡选择与产品选择正交。
同一个 RV1126B 可以构建视觉节点，也可以构建控制与视觉组合。

## 产品与构建

| RTCTRL_PRODUCT / preset | 实际产物与用途 |
| --- | --- |
| development / release | 控制库、适配器、模拟 demo、协议 demo、benchmark；兼容原默认构建 |
| control-sim | 模拟控制与纯协议能力；不编译 mailbox、SocketCAN、原生串口和 POSIX 共享内存映射 |
| vision-node | 通用 C 采集核心、synthetic 后端、可选 V4L2 后端及工具；没有控制库依赖 |
| vision-node / vision-synthetic | 关闭 V4L2 的无硬件视觉构建，运行相同帧消费者 |
| robot-vision | 控制和采集能力集合，另含语义事件到模拟控制的回放组合入口 |

```sh
cmake --preset robot-vision
cmake --build --preset robot-vision -j8
ctest --preset robot-vision
./build/robot-vision/rtctrl_vision_control_replay tests/fixtures/vision-events.txt --arm
```

交叉编译通过现有 toolchain/profile 注入，产品通过 `-DRTCTRL_PRODUCT=vision-node`
等选择。产品 preset 不绑定 SoC。`control-sim` 显式关闭原生硬件适配器，保留无设备 I/O 的协议实现。
适配器开关和 v0.7 接口迁移见 `adr/0006-injectable-capture-and-adapter-capabilities.md`。

## 编译依赖

```text
apps（组合根）
  ├─ runtime → contracts + timer + safety + Threads
  ├─ control → contracts
  ├─ bridge → contracts
  ├─ selected HAL / transport / POSIX adapter
  └─ capture adapter → capture → capture_contracts（独立 C 契约，无控制依赖）
```

`rtctrl_contracts` 提供 C++ 数据和接口的构建契约，`rtctrl_options` 保留共同的
编译选项与关节 profile。`rtctrl_timer` 只通过平台接口等待周期；具体 POSIX
实现属于 `rtctrl_platform_posix`。

通用协议组合 HAL `rtctrl_hal_protocol` 只依赖接口；Dynamixel 和半双工链路分别由
`rtctrl_actuator_dynamixel`、`rtctrl_actuator_serial_link` 实现。HAL 还包括
`rtctrl_hal_sim`、`rtctrl_hal_shm`、
`rtctrl_hal_mailbox`；字节流和 CAN 实现、语义命令源分别有独立 target。
`rtctrl`、`rtctrl_hal`、`rtctrl_transport`、`rtctrl_platform`、`rtctrl_ipc`
保留为聚合 target。新应用应显式链接所需细粒度 target。
上游 ControlLink 与下游 Dynamixel 编解码已拆为 `rtctrl_protocol_target` 和
`rtctrl_protocol_dynamixel`，不再让上游来源绑定电机协议库。

`cmake/Architecture.cmake` 在每次 configure 时递归检查核心 target 的依赖闭包；
`scripts/check-architecture.py` 检查核心及其递归头文件依赖，禁止厂商和具体适配器
进入实时核心、通用 HAL、采集核心和帧消费者。测试还安装 package 并编译独立下游消费者，防止导出不完整。

## 实时域与管理入口

```text
非实时应用循环
  └─ ICommandSource[最多 4 个] → TargetArbiter → ITargetIngress
                                                    ↓ SPSC
                                              control 200 Hz
                                                    ↓ SPSC command
                                              I/O 1 kHz → HAL
                                                    │
                        control ← SPSC state ───────┤
                IStateSnapshot ← SPSC snapshot ─────┘
```

引擎只拥有两个实时线程；命令源不再由引擎持有或启动。
`apps/rtctrl_demo.cpp` 在普通主循环每 20 ms 调用仲裁器。实际网络适配器必须及时
返回；阻塞 SDK/网络工作应放在独立 worker，再通过自己的有界队列交给普通循环。

`ICommandSource` 属于 bridge 语义入口；旧 transport 命名保留为 alias。
`TargetArbiter` 由一个非实时线程独占，启动前绑定来源。数值越大的 priority
越优先，同优先级取较小 slot。每来源独立防重放，输出重新分配单调序列号，
但保留原始创建时间，并将有效期限制在来源期限与本地租约的较小值。
重复缓存不会被重新发布时间戳；队列满时保留候选并有界重试。
来源会话重置需要重建仲裁器，不能将序号回退静默解释成新会话。

实时入口只有一个生产者；状态快照接口只有一个读取者。多来源必须先仲裁，
多订阅者由非实时层分发。快照慢读时会丢弃新发布，返回值必须自行检查
`sample_time_ns`；读完队列后后续发布可继续进入，不能将快照视为同步读硬件。
实时线程不等待快照消费者。队列 drain 以入口时的可用数量为上限，不受持续生产拖延。

## 生命周期和安全所有权

```text
Created → Starting → Ready → Armed
                    ↑         │
                    └─ terminal disarm
Starting / Ready / Armed → FaultLatched
各运行状态 → Stopping → Stopped
```

`start()` 和 `join()` 由一个应用生命周期所有者调用；跨线程只调用 request 方法和
`state()`。重复 start 被拒绝，且不更改正在运行的实例。实例 single-shot。

启动默认未武装。即使传入 `--arm`，也要等两线程调度门控成功、反馈可用、
控制器收到新鲜目标并生成通过安全校验的命令，I/O 所有者才调用 HAL arm。
启动授权不等于立即使能。请求/响应式 HAL 的首次反馈会先发布给控制器；武装后回到下一周期的 read 路径，避免武装事务与控制事务争抢半双工链路。HAL 的打开、读写、arm、紧急停止和关闭只由 I/O 线程执行。

`request_disarm()` 是本实例不可撤销的请求：关闭目标入口，I/O 线程在下次周期
处理并执行紧急停止。恰好与当前周期并发的请求可能在下一周期生效；这是软件
周期行为，不是硬实时延迟保证。解除武装后状态返回 Ready，但不允许本实例重新 arm。
恢复必须停止、重新创建并显式授权。`request_stop()` 最终进入停止与关闭路径。
没有提供会绕过检查的动态 request_arm 接口。

HAL I/O 故障、非法数值、越界仍锁存故障。目标或命令过期走原安全退化路径。
`state()` 支持运行中读取；完整 `report()` 只在 join 后有效。
硬件/MCU watchdog 保持独立；用户态策略不替代硬件安全层。

## 视觉域

`include/rtctrl/vision/capture.h` 是独立 C 契约，`src/vision/capture.c` 实现公共
句柄与所有权管理。`capture_backend.h` 是后端端口；组合根通过
`rtctrl_camera_create(backend, config, &camera)` 注入具体实现。

`rtctrl_vision_v4l2` 实现 Linux 多平面 MMAP，`rtctrl_capture_synthetic` 实现无硬件
确定性 GRAY8 图像源。消费者只使用通用句柄，无后端选择分支；独立配置、设备路径、
原生结构及资源生命周期留在适配器。公共层复制回调表并验证元数据与借用 token。

颜色空间、传递函数、YCbCr 矩阵、量化范围和像素格式采用 `image_format.h`
的平台枚举。原生默认值仅在上下文足够时解析，否则为 UNKNOWN。
`native_format` 仅供诊断，消费者不能用其数值推断可移植的图像处理语义。

每个句柄一个所有者、最多一个借用帧：

```text
open（配置、映射、排队、开流） → acquire → 使用只读帧 → release → acquire
                                      └──────── close ──────────┘
```

帧携带各平面的数据、有效长度、stride、颜色元数据、序号和时间戳来源。
生成后端未节流，时间戳为 0（不可用），不宣称是真实采集时钟。
release 后指针失效；异步推理必须先获得独立所有权或复制到自己的有界池，不能把
借用指针排进异步队列后立即 QBUF。当前未实现 DMA-BUF；以后应新增适配器/所有权
实现，保持这些语义。

初始化失败逐项释放已映射资源；close 即使 STREAMOFF 失败也继续清理。
公共层将独立递增的借用 token 映射回后端 token，防止底层复用 buffer ID
时旧借用被再次接受。借用 token 防止错误归还和重复归还。非法驱动长度、失败的归还会使句柄失效，
需要关闭并重新创建。重连策略属于非实时产品层。

V4L2 采集入口默认保留设备格式，采集 70 帧；可选保存第一张非损坏帧与 schema_version=2 的 `.json`
元数据。两种入口共用 `apps/camera_capture/capture_cli.c` 的帧处理代码。保存发生在诊断工具的同步流程，不能作为异步生产推理流水线使用。
SIGINT/SIGTERM 通过正常路径清理。相机/ISP 拓扑与格式由板级部署准备，库不会
猜测 `/dev/videoN`，也不会管理 3A 服务。

采集、ISP、预处理、推理、跟踪事件和管理分别是独立职责。当前已实现采集、
语义契约与控制互锁；RKAIQ 生命周期仍使用现有工具，RKNN worker、算法及恢复服务
尚未实现。不能把模块名称或接口当作已运行的视觉算法。

## 视觉与控制连接

`vision::Observation` 是进程内语义契约，包含 schema、session、sequence、采集时间、
有效期和 Clear/Active/Unknown/Fault。它不是直接 memcpy 的网络或共享内存 ABI；
未来跨进程适配器须显式编解码并转换为本地 monotonic 时间。

`bridge::VisionInterlock` 是可选产品策略：只有新鲜 Clear 才保持原授权；Active、
Unknown、Fault、会话不符、乱序、非法数据或超时均请求终止武装。
它不能生成电机命令、授予运动权限、清除故障。调用方须在启动前提供首条观测，
并持续在非实时管理循环检查；产品重启默认不自动武装。

`rtctrl_vision_control_replay` 是已经接通的组合根：加载有界文本事件（最多 4096 条、
60 秒时间轴），通过互锁连接模拟控制。正常、危险和恢复观测的回放证明恢复观测
不会重新武装。它不访问真实电机、不运行 NPU、不代表真机视觉闭环验收。

## 平台、厂商输入与部署

`platforms/` 负责 SoC、板卡、BSP 和 SDK 选择；`patches/` 负责版本化第三方修补；
`kernel/` 及 `include/uapi/` 保持原 mailbox V2 边界。本轮未修改 ioctl magic、
结构布局、设备树 binding、ControlLink ABI 或 6/23 关节 profile。

RKAIQ 构建每次在 `build/rkaiq/run-*/` 创建新源码副本，应用 `patches/rkaiq/series`，
记录原始副本与补丁后副本 hash、补丁 hash、实际编译器与产物 hash、构建命令及状态。
SDK Git commit 只作为辅助信息，不再冒充实际工作副本。失败也生成 manifest。
当前脚本仍只构建 librkaiq，server 补丁被准备但需要独立 server 构建/回归路径。
它不替换板端系统库，也不声称外部 sysroot 已完全封闭锁定。

`deploy/README.md` 定义产品部署边界。现有 `config/*.toml` 仍是运行意图说明，
不是已接通的配置解析器。端侧控制通过明确 CLI/RuntimeConfig 装配，新增配置解析
只能发生在启动前，不能进入实时循环。

## 扩展规则

- 新控制算法：实现 IController，在产品入口选择，不修改 runtime。
- 新执行器：实现协议或链路，按 capabilities 装配；HAL 不进入视觉域。
- 新命令源：实现 bridge::ICommandSource，经仲裁进入唯一实时入口。
- 新相机/推理后端：留在视觉适配器，厂商句柄不进入 Observation 或控制数据模型。
- 新板卡：增加 platform profile/BSP，不加板卡分支到 control/runtime。
- 新产品：增加组合入口与产品 preset，声明故障处理和部署所有权，并添加端到端回放。

v0.6 核心接口迁移见 ADR-0005；v0.7 后端接口迁移和构建能力见 ADR-0006。
线程运行环境、安全门控和固定容量 SPSC 仍是有意保留的核心约束，不为每个稳定实现
增加虚接口；本轮没有把 POSIX 运行时改造成 RTOS 执行器。
