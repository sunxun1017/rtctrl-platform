# ADR-0001：平台边界与依赖方向

状态：Accepted，2026-09-01。

## 决策

核心 runtime 仅依赖 `IRealtimePlatform`、`IActuatorHal`、`IController`、安全策略与语义命令源。POSIX、板卡、通信协议和 ROS 2 都是组合根选择的叶子适配器。

Transport 仅收发有界字节；protocol 仅做纯编解码；HAL 将二者组合成执行器语义；controller 不知道设备与消息来源。RK3588 宏、设备路径、CPU 编号和 ROS 类型不得进入 model/control/runtime。

v0.2 使用静态链接和显式装配，不引入动态插件 ABI。需要新平台、UART、NearLink、共享内存或 ROS 2 时新增适配器，不修改实时核心。
