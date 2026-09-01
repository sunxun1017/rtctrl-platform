# ADR-0002：内核与用户态边界

状态：Accepted，2026-09-01。

## 决策

内核层提供可抢占调度、高分辨率时钟、IRQ/CPU 调度基础和资源权限；用户态 runtime 负责绝对周期、跳周期、防陈旧租约、安全状态机和观测指标。

仓库只提交 Kconfig 片段、只读能力检查器与部署模板，不自动写内核、boot 参数、IRQ affinity、sysctl 或 systemd 系统目录。最终配置必须在目标 BSP 运行 `olddefconfig` 后审计，最终时延必须在目标硬件压力环境测量。
