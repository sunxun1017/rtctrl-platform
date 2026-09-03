# Changelog

## Unreleased

- Pin the official Orange Pi RK3588 Linux source as a shallow Git submodule and
  add board-profile-driven, isolated ARM64 kernel/DTB/module/IgH/user-space builds.
- Add Debian/Ubuntu AArch64 bootstrap checks, RT kernel configuration contracts,
  generated build manifests, and an extensible path for non-Orange-Pi RK3588 boards.

- 增加不绑定电机型号的 Linux SocketCAN 帧级适配器，同时支持 Classical CAN、CAN-FD、标准/扩展帧、BRS/ESI、RTR、错误帧、内核过滤器和接收时间戳。
- 增加 CAN/CAN-FD 帧合法性检查、固定容量配置和部署/`vcan` 验证文档。
- 增加可选的 IgH EtherCAT 1.6 `ecrt` 适配器，覆盖 master/domain/slave、SyncManager/PDO、Working Counter、从站状态和 Distributed Clocks 周期生命周期。
- IgH 公共配置保持电机无关且不暴露 `ecrt.h`；PDO、identity、DC 参数和 process-data offset 由部署叶子提供。
- 增加锁定 IgH 1.6.12 的 Intel I210/I211/I350 native `ec_igb` 获取、构建和网卡隔离检查工具；构建默认关闭 generic、EoE 与实时循环 syslog。
- 增加 Serial/CAN-FD/IgH EtherCAT 三选一链路与独立电机协议 codec 两个注入维度、固定容量逻辑数据包、组合式 `ProtocolActuatorHal` 和互斥部署意图；实时循环不做总线探测或切换。
- 增加 Dynamixel Protocol 2.0 CRC/Byte Stuffing/流式解析、可注入 Control Table profile、批量 Sync Write/Bulk Read 和固定容量半双工串口 link；POSIX 串口新增 1–4 Mbps 档位与可选 Linux RS-485 自动方向。

## 0.4.0 - 2026-09-01

- 从本人 `sx_text` 分支提炼 23 关节/三 EtherCAT master 拓扑，并增加编译期完整性与协议匹配校验。
- 增加版本化 POSIX 共享内存 ABI、L0 双向一致快照和 `SharedMemoryHal`，保持实时核心无 ROS/vendor 依赖。
- runtime 使能前必须先获得新鲜反馈；共享内存急停拥有独立 enable 直达路径。
- 命令模型升级为 position/velocity/effort/kp/kd 混合阻抗契约，安全策略校验增益边界。
- 增加固定容量 `PolicyActionMapper`，支持 action clip/scale、逻辑关节重映射、关节限位及 delta-action 残差。
- 关节数改为 1–64 的编译期 profile；ControlLink V2 显式携带 joint count，默认 6 关节 64 字节、humanoid23 为 132 字节。

## 0.3.0 - 2026-09-01

- 增加 64 字节 ControlLink V1：显式小端、CRC32C、会话号、严格序号和相对租约。
- 增加 POSIX 非阻塞串口、短包/粘包重组、垃圾前缀恢复、重放与会话切换防护。
- runtime 采用接收端时钟计算的端到端目标截止时间，并统计 source 队列丢包。
- systemd 默认不使能且不自动重启；demo 响应 SIGINT/SIGTERM 并走安全停机路径。
- 增加协议集成演示、故障测试、benchmark 可选门禁、RV64 preset 与 CMake 安装导出。

## 0.2.0 - 2026-09-01

- 将 POSIX 实时能力隐藏在 `IRealtimePlatform` 后，核心 runtime 不再依赖 Linux 类型。
- HAL 生命周期拆分为 `open_safe`、显式 `arm`、幂等 `emergency_stop` 与 `close`。
- 增加 transport、protocol、bridge 端口，固定 ROS 2、NearLink 与板卡均为外部适配器。
- 增加 PREEMPT_RT 生产/诊断配置片段、只读内核检查器、systemd 模板和通用交叉编译入口。
- 用 ADR 固化依赖方向、内核/用户态边界与实时热路径规则。

## 0.1.1 - 2026-09-01

- 建立 1 kHz I/O、200 Hz 控制、固定容量 SPSC、租约与故障锁存基线。
