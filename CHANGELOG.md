# Changelog

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
