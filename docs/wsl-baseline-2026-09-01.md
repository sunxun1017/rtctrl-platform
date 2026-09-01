# WSL 功能与软实时基线（2026-09-01）

## 环境

- Ubuntu 22.04.5 LTS / WSL2
- Kernel `6.18.33.2-microsoft-standard-WSL2`, `PREEMPT_DYNAMIC`
- x86_64, 32 vCPU, 7.6 GiB RAM
- GCC 11.4.0, CMake 3.22.1, Ninja 1.10.1, cyclictest 2.20

这些数据只证明平台的调度路径、统计链路和故障机制可运行，不代表 RK3588 + PREEMPT_RT 的验收结果。

## 验证结果

### 构建与测试

- Release 构建：通过，`-Wall -Wextra -Wpedantic -Wconversion -Wshadow` 无警告。
- 单元/集成测试：通过；包含 SPSC、NaN/过期命令、PD/HAL、target lease 失联降级。
- ASan + UBSan：通过。

### 普通用户、显式武装、2 秒

```text
io_1khz: p50=90 us, p99=270 us, max=2012.7 us, skipped=2, queue_drops=0
control_200hz: p50=110 us, p99=280 us, max=1174.2 us, skipped=0, queue_drops=0
scheduler=fallback, fault_latched=false
```

### root 严格模式、固定 CPU、2 秒

```text
scheduler: io=SCHED_FIFO, control=SCHED_FIFO, mlock=active
io_1khz: p50=30 us, p99=180 us, max=547.8 us, skipped=0, queue_drops=0
control_200hz: p50=40 us, p99=120 us, max=517.2 us, skipped=0, queue_drops=0
fault_latched=false
```

### 故障注入

HAL 在 500 ms 后持续返回 I/O error。最终结果：`fault_latched=true`，故障不会因后续普通命令自动恢复。

### cyclictest 交叉检查

root、FIFO 80、CPU 2、1 ms 周期、3 秒：`Min 5 us / Avg 36 us / Max 2400 us`。WSL 虚拟化会产生毫秒级尖峰，因此最终目标板必须重新测量。

## RK3588 下一阶段

1. 接入 AArch64 sysroot 和交叉编译工具链。
2. 在目标 PREEMPT_RT 内核上确定 IRQ/CPU 亲和性。
3. 实现有界非阻塞 UART/SPI/NearLink transport 与真实执行器 HAL。
4. 使用 cyclictest 和应用内指标完成压力负载、故障注入及长稳测试。
5. 将测得的 p99/max、执行时间和安全停止时间更新到项目文档及简历。

