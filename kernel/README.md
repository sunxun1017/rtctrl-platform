# Linux 内核与部署层

这里维护“可审查的部署输入”，不修改正在运行的系统。

- `config/rt-periodic-production.cfg`：周期 I/O 控制负载的生产起始片段。
- `config/rt-diagnostics.cfg`：仅在定位尖峰时叠加；其测量不能作为最终验收数据。
- `scripts/check-kernel.sh`：只读检查当前内核；默认报告，`--strict` 在缺少硬要求时返回失败。
- `scripts/merge-config.sh`：调用目标 Linux 源码树自带的 `merge_config.sh`，输出到显式路径。
- `systemd/rtctrl.service.in`：参数化权限与隔离模板，不直接安装。
- `driver/`：Linux 6.1+ 平台/misc 驱动，管理 coherent DMA、IRQ、武装门控与内核 watchdog。
- `bindings/misc/`：对应硬件邮箱的设备树 schema，不写死 RK3588 地址。
- `config/rtctrl-mailbox.cfg`：驱动集成到目标内核树后可合并的模块配置。
- `scripts/build-module.sh`：针对显式内核构建树编译外部模块，不安装或加载。

配置片段不是最终配置。必须在目标板 BSP 上合并、运行 `olddefconfig`，再审计生成的 `.config`；依赖不满足或无 prompt 的 Kconfig 符号可能忽略片段赋值。`HZ=1000` 是工程起点，而高分辨率定时来自 `HIGH_RES_TIMERS`。

```bash
./kernel/scripts/check-kernel.sh
./kernel/scripts/check-kernel.sh --strict
./kernel/scripts/merge-config.sh /path/to/linux /tmp/rtctrl.config production
./kernel/scripts/build-module.sh /absolute/path/to/linux-build
```

## 板端原则

- 生产配置采用 `PREEMPT_RT + HIGH_RES_TIMERS + HZ_PERIODIC`，默认不启用 `NO_HZ_FULL`。
- systemd/cgroup v2 设备默认关闭 `RT_GROUP_SCHED`，避免非 root cgroup 无 RT 带宽。
- CPU 与 IRQ 归属根据板端拓扑、`/proc/interrupts` 和压力数据决定，不在源码中写死 CPU 号。
- systemd 的 `LimitRTPRIO`、`LimitMEMLOCK`、`LimitRTTIME` 都要按应用峰值和故障注入结果给有限值。
- WSL 只做编译、单测、仿真和趋势观察，不自动替换内核、不写 `.wslconfig`、IRQ affinity、sysctl 或启动参数。

参考：[Linux 实时内核配置](https://docs.kernel.org/core-api/real-time/kernel-configuration.html)、[CPU 隔离](https://docs.kernel.org/admin-guide/cpu-isolation.html)、[IRQ affinity](https://docs.kernel.org/core-api/irq/irq-affinity.html)、[cgroup v2 CPU controller](https://docs.kernel.org/admin-guide/cgroup-v2.html#cpu)。
