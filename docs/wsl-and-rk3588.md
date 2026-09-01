# WSL 与 RK3588 部署边界

## WSL 阶段

- 仅使用 `SimulatedHal` 和 `LoopbackSource`，不访问真实设备。
- 本机 WSL2 当前检测为 `PREEMPT_DYNAMIC`；其他 WSL 安装必须运行时检测，不能据此推断。
- 可以验证架构、编译、队列、双速率循环、故障注入和统计链路。
- WSL 的 p99/max jitter 只能作为功能基线，不能写成 RK3588 硬实时指标。

## RK3588 阶段

1. 合并 `kernel/config/rt-periodic-production.cfg`，运行 `olddefconfig` 并审计最终配置。
2. 交叉编译时用 `cmake/toolchains/linux-cross.cmake` 提供 target triple 与 sysroot，不在源码里写死 AArch64。
3. 根据实际 IRQ 分布选择 housekeeping CPU 和控制 CPU；不要机械启用所有 isolation 参数。
4. 用 cyclictest 在空载、CPU、内存、存储和通信压力下建立基线。
5. 接入真实 HAL 后运行 1 kHz/200 Hz 长稳测试，记录 p50/p99/max、skipped period、queue drop 与安全介入。
6. 用实测 `VmLck` 与故障注入设置有限的 systemd RT 权限；应用尚无 `sd_notify`，模板不伪装 systemd watchdog 支持。

WSL 中不得自动替换内核、写 `.wslconfig`、修改全局 RT sysctl、IRQ affinity、governor 或启动参数。

建议实机验收目标：压力负载下 1 kHz I/O 循环 p99 抖动不超过 100 us、最大值不超过 250 us、控制计算 p99 小于 1 ms；实际指标必须以目标板测量结果为准。
