# v0.3.0 验证记录

日期：2026-09-01  
源码基线：`dea6917`（验证后追加本记录）  
环境：Ubuntu 22.04 WSL2，G++ 11.4.0，CMake 3.22.1，Ninja 1.10.1  
工作目录：WSL ext4 `/home/sx/projects/rk3588-rt-control-v0.3.0`

## 自动验证

```bash
./scripts/check.sh
cmake --preset asan
cmake --build --preset asan -j8
ASAN_OPTIONS=halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 \
  ctest --preset asan --output-on-failure
./scripts/verify-install-and-signal.sh
```

结果：

- Release：26/26 targets 构建成功，CTest 1/1 通过。
- ASan + UBSan：26/26 targets 构建成功，CTest 1/1 通过，无 sanitizer 报告。
- 协议集成：64 字节目标帧以每次最多 7 字节短读完成重组，序号 42、50 ms 本地租约和 6 个关节目标一致，0 framing error。
- 安装导出：头文件、静态库、可执行程序与 `rtctrlConfig/rtctrlTargets` 安装到临时前缀成功。
- 生命周期：向已使能的 10 秒演示发送 SIGTERM，进程提前正常退出并报告 `fault_latched=false`；I/O 线程退出路径调用幂等 `emergency_stop()` 后关闭 HAL。

单元/集成测试包含 SPSC、绝对周期器跳周期、安全策略、控制器与 HAL、协议 round-trip、64 个单 bit 损坏、UART 短读、垃圾前缀恢复、重复序号、跨会话拒绝、接收端租约截断，以及 runtime 目标过期降级。

## WSL 功能基线

一次 ext4 Release 运行结果：

| 环路 | 样本 | p50 jitter | p99 jitter | max jitter | max exec | skipped |
|---|---:|---:|---:|---:|---:|---:|
| I/O 1 kHz | 3016 | 80 us | 240 us | 540.1 us | 51.5 us | 0 |
| Control 200 Hz | 603 | 90 us | 190 us | 415.1 us | 26.4 us | 0 |

独立 1 kHz benchmark 的同轮结果：2998 样本，p50 80 us，p99 210 us，max 2181.9 us，skipped 2。`SCHED_FIFO` 申请以 errno 1 回退，内存锁定成功。

这些数字只证明 WSL2 下的功能、内存安全和软实时趋势。当前 WSL 内核为 `PREEMPT_DYNAMIC + HZ=250`，不是 PREEMPT_RT；它们不能替代 RK3588/RV64 目标板在隔离 CPU、IRQ/负载矩阵与真实 EtherCAT/NearLink 链路下的验收。

## 待目标板补证据

1. AArch64/RV64 工具链与实际 sysroot 的交叉构建产物、ELF 架构及 SHA256。
2. PREEMPT_RT 最终 `.config`、内核命令行、CPU/IRQ 亲和性、rtprio/memlock 能力。
3. 真实 HAL 的状态采样、命令到执行器端到端时延、watchdog 和断链安全停机时间。
4. idle、CPU/内存/网络压力下不少于 30 分钟的重复轮次，并使用 benchmark 环境变量设置非 0 门禁。
