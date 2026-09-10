# 模块与端口

从需要的能力找模块，再进入该模块的 include、src 或 tests。这里的 src 是该模块
需要编译的实现；include 是可复用契约与公开 API。纯头文件模块没有空的 src 目录。
每个模块拥有 CMakeLists.txt；跨模块集成测试仍在根 tests 中。

| 模块 | 职责 | 主要构建目标 |
| --- | --- | --- |
| model | 固定容量控制目标、传感与命令数据 | rtctrl_model_api |
| runtime | 双速率执行、生命周期、状态快照、周期定时 | rtctrl_runtime、rtctrl_timer |
| control | 控制器接口、关节 PD、策略动作映射 | rtctrl_control |
| safety | 限幅、租约与故障策略 | rtctrl_safety |
| actuator | 执行器端口、拓扑、通用协议组合 HAL、半双工链路 | rtctrl_hal_protocol、rtctrl_actuator_serial_link |
| transport | 字节/CAN 传输端口 | rtctrl_transport_api |
| protocol | ControlLink 与 Dynamixel 纯编解码 | rtctrl_protocol_target、rtctrl_protocol_dynamixel |
| ipc | SPSC 容器、共享控制数据 ABI；不创建系统资源 | rtctrl_ipc_api |
| bridge | 非实时来源仲裁、分帧命令源、视觉互锁策略 | rtctrl_bridge、rtctrl_source_framed |
| capture | 通用 C 采集、帧借用和后端回调契约 | rtctrl_capture |
| inference | 通用张量描述、大小计算和同步后端接口 | rtctrl_inference、rtctrl_inference_api |
| vision | 视觉观测的语义数据契约，不依赖相机或 NPU | rtctrl_vision_api |

推理契约与张量大小计算归 inference 模块，RKNN 归 adapters/inference。当前支持输入
准备和同步执行接口；输出读取和完整生产推理服务尚未实现。通用模块不依赖 RKNN SDK。

## 端口归属

| 端口 | 所属模块 | 实现或调用方 |
| --- | --- | --- |
| IRealtimePlatform | runtime | POSIX 适配器、测试替身 |
| ITargetIngress / IStateSnapshot / ILifecycleControl | runtime | 引擎实现；桥接和应用调用 |
| IController | control | JointPd 等控制策略 |
| IActuatorHal / IActuatorProtocol / IActuatorLink | actuator | 模拟、Dynamixel、mailbox、通用组合 HAL 等 |
| IByteTransport / ICanTransport | transport | 串口、SocketCAN、loopback |
| ICommandSource | bridge | 分帧命令源、loopback 来源 |
| rtctrl::inference::Backend | inference | RKNN 适配器、测试替身及外部实现 |
| rtctrl_capture_backend | capture | V4L2、synthetic、外部自定义后端 |

端口与业务接口可以不同。采集核心通过 backend 回调取得帧，再统一验证所有权，
向消费者暴露 capture.h；不要让消费者直接操作 V4L2 队列。
端口可以是 C++ 虚接口，也可以是 C 回调表。固定算法和数据容器不为目录对称增加接口。

## 依赖和使用

模块不能包含或链接 adapters，也不访问厂商/系统头文件。应用显式选择适配器，
构造后注入端口。`*_api` 目标提供模块头文件与契约依赖，调用非内联实现时必须
链接表中的库目标。runtime 的端口头文件可以单独提供给 bridge，无需链接线程引擎。
runtime 为此使用独立的公开头文件根目录：

| target | 源码头文件根目录 | 可见内容 |
| --- | --- | --- |
| rtctrl_runtime_api | runtime/ports/include | 生命周期、时钟/等待端口、统计数据 |
| rtctrl_timer | runtime/timer/include | PeriodicTimer，以及其依赖的端口和数据 |
| rtctrl_runtime | runtime/include | RealtimeEngine，以及其依赖 |

各根目录下仍保留 rtctrl/runtime 前缀，现有 runtime include 拼写不变。
仅链接端口 target 时，引擎和定时器头文件不可见。
其他模块的 *_api 提供该模块所有公开声明及其头文件依赖，非内联实现由库 target 提供。
FramedCommandSource 属于 rtctrl::bridge，消费注入的 ITargetCodec；
使用 FixedTargetCodec 的应用需显式链接 rtctrl_protocol_target。

构建与安装都通过 target 获得头文件根目录，不使用全仓全局 -I。安装路径是
`include/rtctrl-modules/<module>/`；runtime 的 ports、timer、engine 各有独立子目录。
代码中的 include 仍是 `rtctrl/...`。
适配器创建接口不导出到模块 package。

```cmake
find_package(rtctrl 0.8 REQUIRED CONFIG)
target_link_libraries(my_control PRIVATE rtctrl::rtctrl_runtime rtctrl::rtctrl_control)
```

目录迁移保留了多数既有命名空间，例如 actuator 模块的 `rtctrl::hal` 和定时器的
`rtctrl::platform`。它们不是板级配置目录；新的实际文件位置与 API 迁移见
[ADR-0007](../docs/adr/0007-module-owned-ports.md)。

具体机器人拓扑和标定属于 [products](../products/README.md)，不作为 actuator API 安装。
启用 RTCTRL_BUILD_TESTS 时，每个公开模块头文件单独编译，只使用所属 target 的依赖；
C 头文件同时以 C 和 C++ 编译。安装包消费者会对 imported targets 重复这些检查，
并验证 runtime 端口、transport 和 actuator 不会暴露引擎、上层命令源或产品配置。
