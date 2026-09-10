# ADR-0007：模块自包含、端口归属与显式适配器

状态：Accepted，2026-09-10，v0.8。

## 原因

原先公共 include 与 src 的目录形状不能表达完整的模块所有权，POSIX、串口、
SocketCAN 等具体实现又与通用能力混放。全局 include 路径和聚合目标掩盖了依赖。
运行时依赖 bridge/runtime_ports.hpp，端口的归属也与实际提供能力的模块相反。

借鉴 Boost 的模块内 include/src/test 组织和 OpenCV 按 core/videoio/dnn 等能力划分
模块的方式，保留 src 作为实现目录，在其外层明确能力归属。
参考：[Boost 目录规范](https://www.boost.org/doc/libs/1_34_0/more/lib_guide.htm)、
[OpenCV 模块组织](https://docs.opencv.org/4.0.0/index.html)。这里借鉴组织原则，
不引入这些框架的运行依赖，也不复制它们的全部层级。

## 决策

- modules/<能力> 自己拥有接口、实现、构建和专属测试。跨模块测试保留在根 tests。
- 端口归需要或提供该能力的模块，不建立全局 port 层。C++ 虚接口与 C 回调表并存。
- 适配器归 adapters/<类别>/<实现>，公开的创建入口只对显式依赖它的装配代码可见。
- 平台 profile 是板级数据，继续放在 platforms；运行时端口归 runtime，POSIX 归适配器。
- 模块只能依赖模块。runtime 不依赖 bridge，bridge 通过 runtime 端口接入引擎。
- 安装仅导出模块库与模块头文件，具体适配器静态链接到应用。需要外部厂商后端的
  用户可以实现已安装的端口，或在源码树构建中显式使用适配器 target。
- 稳定的算法、容器和编解码器保留直接实现，不为每个类增加虚接口。

## 迁移清单

| 原位置 | 新位置 |
| --- | --- |
| src/control、safety、runtime、bridge、protocol、transport | modules/<同名模块>/src |
| src/hal 的通用组合 HAL、半双工链路 | modules/actuator/src |
| src/platform/realtime_platform.cpp | modules/runtime/src/periodic_timer.cpp |
| src/platform/posix_realtime.cpp | adapters/realtime/posix/src |
| src/ipc/posix_shared_memory.cpp | adapters/ipc/posix_shm/src |
| mailbox HAL 与 codec | adapters/actuator/mailbox/src |
| 串口、SocketCAN、loopback | adapters/transport/<实现>/src |
| IgH 实现 | adapters/ethercat/igh/src |
| 模拟 HAL、共享内存 HAL、Dynamixel HAL 协议 | adapters/actuator/<实现>/src |
| src/vision/capture.c | modules/capture/src/capture.c |
| synthetic_capture.c | adapters/capture/synthetic/src/synthetic_capture.c |
| include/rtctrl/<通用能力> | modules/<所属模块>/include/rtctrl/<原公共前缀> |

头文件调用方需要更新：

| 原 include | 新 include |
| --- | --- |
| rtctrl/platform/realtime_platform.hpp | rtctrl/runtime/realtime_platform.hpp |
| 通过平台头文件间接使用 PeriodicTimer | 显式包含 rtctrl/runtime/periodic_timer.hpp |
| rtctrl/bridge/runtime_ports.hpp | rtctrl/runtime/runtime_ports.hpp |
| rtctrl/transport/command_source.hpp | rtctrl/bridge/command_source.hpp |
| rtctrl/vision/capture.h、capture_backend.h、image_format.h | rtctrl/capture/ 下的同名头文件 |
| rtctrl/vision/synthetic_capture.h | rtctrl/adapters/synthetic/capture.h |
| rtctrl/platform/posix_realtime.hpp | rtctrl/adapters/posix/posix_realtime.hpp |
| 其他具体适配器头文件 | rtctrl/adapters/<实现>/<原文件名> |

ITargetIngress、IStateSnapshot、ILifecycleControl、RuntimeState 的命名空间从
rtctrl::bridge 移至 rtctrl::runtime。ICommandSource 只使用 rtctrl::bridge，
删除 transport 兼容 alias。其他既有类名、命名空间和函数行为保留。

删除 rtctrl、rtctrl_contracts、rtctrl_hal、rtctrl_transport、rtctrl_platform、
rtctrl_ipc、rtctrl_protocol 聚合目标。以应用 CMakeLists 的细粒度依赖作为示例，
不要用一个新的全局聚合目标替换它们。rtctrl_options 只提供编译选项。
旧 rtctrl_capture_contracts 改为 rtctrl_capture_api。

删除 ActuatorLinkBackend、ActuatorLinkProviders 和固定后端 switch；
inject_actuator_dependencies 直接接收 IActuatorLink* 与 IActuatorProtocol*。
保留空指针、协议需求与链路容量校验。增加新链路不再修改模块中的后端枚举，
由应用选择并传入实际对象。

包版本升为 0.8，find_package 应请求 rtctrl 0.8。模块头文件安装到独立目录，
路径由 imported target 传递；不再假设只加安装根 include 就能编译所有模块。
适配器库与头文件不再安装。应用仍按原名称安装并可运行。

新安装应使用干净的 staging 目录：CMake install 不会清除旧版本遗留的头文件和库。
仓库安装测试每次使用干净目录，并验证端口可用、适配器不可见。

## 删除与保留

删除已跟踪的三个 Python .pyc 生成文件并忽略后续字节码；源脚本保留。
移除旧源码目录、旧构建清单和转发接口，不建立空壳模块。
模拟实现、板级配置、共享 ABI、协议分层、历史验证文档都有实际用途，保留。

本次不修改控制参数、线程行为、协议数值、UAPI 布局、板级文件或第三方 SDK。
运行时仍有 C++ 线程和 Linux/POSIX 适配器约束，不等于完成跨操作系统移植。
目录结构为后续 inference 提供边界，不代表已经接入 RKNN。
