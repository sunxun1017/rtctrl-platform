# 架构说明

## 依赖方向

```text
app/composition root
  |-- runtime --> platform-api --> POSIX / future RTOS adapter
  |          |--> HAL-api ------> simulated / framed actuator HAL
  |          |--> control-api --> PD / future policy controller
  |          `--> safety + fixed-capacity IPC
  |-- HAL adapter --> byte-transport + protocol codec
  `-- bridge ------> CLI / shared-memory / future ROS 2
```

依赖只指向抽象。HAL 不依赖控制器；protocol 不依赖 Linux 或具体总线；controller 不知道板卡、设备协议和目标来源；bridge 回调不得直接进入实时线程。RK3588、NearLink 和 ROS 2 分别只是 deployment、transport 和 bridge 的实现。

## 线程与数据流

```text
CLI/ROS/network bridge or semantic source (normal, 50 Hz)
                  | bounded SPSC target
                  v
Control thread (200 Hz) -> bounded SPSC command -> I/O thread (1 kHz) -> HAL
                  ^                                  |
                  `-------- bounded SPSC state ------'
```

三个队列都是单生产者/单消费者、固定容量并在启动前构造。控制线程每周期排空状态队列，只处理最新状态；I/O 线程排空命令队列，只采用最新且仍在有效期内的命令。

目标与状态分别有独立 freshness lease。命令源停止后，控制线程不会用旧目标生成带新时间戳的命令；设备状态过期或序号不前进时也不会刷新控制命令。

字节链路采用 `IByteTransport -> ITargetCodec -> FramedCommandSource` 三层组合：设备文件和短读写只存在于 transport，帧 ABI 与 CRC 只存在于 protocol，会话、重放和跨时钟域租约只存在于 source。替换 RK3588、RISC-V、NearLink 或 SPI 不会改变控制器与实时引擎。V1 细节见 `docs/control-link-v1.md`。

## 实时规则

进入周期循环后禁止：动态内存、异常传播、标准输出、文件写入、无界队列、互斥锁和设备重连。周期等待使用 `CLOCK_MONOTONIC + TIMER_ABSTIME`，超期时直接跳到下一个未来周期，避免补跑风暴。

## 安全路径

每条控制命令携带 `created_time_ns` 与 `valid_until_ns`。I/O 线程在唯一的执行器出口检查：

1. HAL 故障位和读写结果；
2. 命令是否过期；
3. NaN/Inf；
4. 位置、速度和力矩边界。

任何检查失败都生成 `SafeStop` 指令并累计可观测指标。真实机器人部署时仍需驱动器或 MCU 侧独立 watchdog，Linux 用户态不能成为唯一安全层。

启动默认未武装。`open_safe()` 只允许初始化并保持硬件安全，显式 `arm()` 后才可输出；只有 `--arm`、调度门控成功、状态与目标均新鲜时才会下发普通控制指令。`emergency_stop()` 是幂等且唯一的紧急 HAL 出口。硬件读写错误、NaN 和越界会锁存故障，本次运行不自动恢复；当前引擎为 single-shot，必须停止并重新创建实例才能复位。

systemd 模板不携带 `--arm` 且不自动重启。SIGINT/SIGTERM 只通知主线程退出，主线程随后请求 runtime 停止，I/O 线程在关闭 HAL 前执行幂等 `emergency_stop()`。真实硬件还必须有驱动器或 MCU watchdog；用户态退出路径不是唯一安全层。

架构决策见 `docs/adr/`。核心不采用动态插件或 service locator；新增平台/协议/中间件通过显式工厂与独立 CMake target 装配。
