# ControlLink V1

ControlLink 是实时控制核心与 NearLink/UART 等字节链路之间的稳定边界。V1 只定义机器人端接收的位置目标帧；协议编解码无系统调用、无动态分配，不直接依赖 Linux、ROS 2、MQTT 或具体板卡。

## 64 字节目标帧

所有多字节整数采用 little-endian；浮点数为 IEEE-754 binary32。实现逐字段读写字节，不序列化 packed C/C++ struct，因此 x86-64、AArch64 与 RV64 不受结构体填充和对齐差异影响。

| 偏移 | 长度 | 字段 | 约束 |
|---:|---:|---|---|
| 0 | 4 | magic | `RTCL` |
| 4 | 1 | version | `1` |
| 5 | 1 | type | `1`（position target） |
| 6 | 2 | flags | V1 必须为 0 |
| 8 | 4 | session_id | 非 0；链路重连后由发送端重新生成 |
| 12 | 2 | payload_size | `24` |
| 14 | 2 | reserved | 必须为 0 |
| 16 | 8 | sequence | 会话内严格递增、非 0 |
| 24 | 8 | sender_time_ns | 发送端单调时间，仅用于检测会话内时间回退 |
| 32 | 4 | lease_us | 相对有效期、非 0 |
| 36 | 24 | position[6] | 6 个有限的 float32 关节目标 |
| 60 | 4 | crc32c | 覆盖字节 `[0, 60)` |

`sender_time_ns` 不能与接收端时钟直接相减：两块设备的 monotonic clock 不属于同一时钟域。接收成功时，适配器记录本机 `created_time_ns=now`，并计算：

```text
valid_until_ns = now + min(lease_us, policy.max_lease_us) * 1000
```

runtime 同时检查本地最大目标年龄和这个端到端截止时间。发送停止、链路卡死或中间件重复投递都不能无限刷新旧控制目标。

## 会话与恢复

- 同一打开周期只接受一个 `session_id`，序号必须严格递增。
- 发送端重启必须建立新会话；接收端只在显式关闭/重新打开链路时接受新会话。
- CRC、版本、形状或有限数检查失败时，解析器有界丢弃并搜索下一个 magic；每次 poll 的帧数和扫描步数都有上限。
- 热路径不重连、不打印日志。链路恢复、告警和状态机属于非实时 supervisor。

## NearLink 与 MQTT 边界

NearLink 模组若暴露 UART/USB 串口，可直接使用 `PosixSerialTransport + FixedTargetCodec + FramedCommandSource`；若暴露 SPI，只替换 `IByteTransport` 叶子实现。

MQTT 不进入 1 kHz/200 Hz 实时线程。推荐由独立 gateway 订阅控制主题，完成认证、QoS 1 去重和语义校验后写入本协议或共享内存。控制主题不得 retain；最终安全判断仍以机器人本机租约和硬件 watchdog 为准。

## V1 范围

V1 的 6 关节负载用于验证 ABI 与平台边界，不代表机器人最终自由度。扩展 23 自由度时应新增版本或分片类型，不能静默改变 V1 的 64 字节布局。
