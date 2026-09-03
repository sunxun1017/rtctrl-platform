# Dynamixel Protocol 2.0 执行器接入

项目提供不依赖具体 Dynamixel 型号的 Protocol 2.0 热路径实现。它没有引入 Dynamixel
SDK 运行时，也没有把型号、串口设备或 Orange Pi 写进实时核心。

## 分层

```text
DynamixelJointProfile
  ID、Control Table 地址、raw/SI 换算、方向和零点
             |
DynamixelProtocol2 : IActuatorProtocol
  Protocol 2.0、CRC16、Byte Stuffing、Sync Write、Bulk Read
             |
HalfDuplexSerialLink : IActuatorLink
  固定发送队列、短写续传、收发阶段切换
             |
PosixSerialTransport : IByteTransport
  /dev/tty*、波特率、可选 Linux RS-485 自动方向
```

同一个 `DynamixelProtocol2` 可使用 U2D2、带自动方向的 TTL 转换器或原生 UART +
RS-485 收发器。型号 profile 不包含设备路径和波特率；串口层不包含电机寄存器。

## 已实现范围

- Protocol 2.0 Instruction/Status packet、官方 CRC16 和 Byte Stuffing。
- 对垃圾前缀、短包、粘包、CRC 错误进行固定容量流式恢复。
- 多 ID Bulk Read；位置命令和 Torque Enable/Disable 使用 Sync Write。
- 每个逻辑关节独立 ID、方向、零点、Control Table 和 raw/SI 比例。
- Present Position 必选，Present Velocity/Effort 可选。
- 串口支持 9,600 至 4,000,000 的 Linux 标准波特率档位，包括精确 1 Mbps。
- `TIOCSRS485` 内核自动方向可选；U2D2/硬件自动方向模式不启用该选项。
- 周期路径无动态分配、异常、日志和阻塞等待。

当前只输出 Position 模式，不把 `kp/kd` 或 effort 猜测映射到型号寄存器。Protocol 1.0、
4.5/6 Mbps 自定义波特率、GPIO 软件方向、间接地址自动配置和 Fast Bulk Read 尚未实现。

## Profile 示例

下面只展示常见 X 系列 Control Table 布局。比例、零点、电流到力矩的换算和地址必须以
所用型号 e-Manual 为准：

```cpp
std::array<rtctrl::hal::DynamixelJointProfile,
           rtctrl::model::kJointCount> joints{};
for (std::size_t i = 0; i < joints.size(); ++i) {
  joints[i].id = static_cast<std::uint8_t>(i + 1);
  joints[i].torque_enable = {64, 1};
  joints[i].goal_position = {116, 4};
  joints[i].present_effort = {126, 2};
  joints[i].present_velocity = {128, 4};
  joints[i].present_position = {132, 4};
  joints[i].position_zero_raw = 2048;
  joints[i].position_rad_per_unit = /* model value */;
  joints[i].velocity_rad_s_per_unit = /* model value */;
  joints[i].effort_nm_per_unit = /* measured/model value */;
  joints[i].direction = 1;
}

rtctrl::hal::DynamixelProtocol2 protocol({joints.data(), joints.size()});
rtctrl::transport::PosixSerialTransport serial({
    .device = "/dev/ttyUSB0",
    .baud_rate = 57600,
    .linux_rs485 = false,  // U2D2 handles direction itself
});
rtctrl::hal::HalfDuplexSerialLink link(serial);
rtctrl::hal::ProtocolActuatorHal actuator(link, protocol);
```

所有关节的 Torque Enable 和 Goal Position 地址/宽度必须一致，保证命令使用广播
Sync Write，不产生逐电机应答碰撞。反馈寄存器布局可以逐 ID 不同，Bulk Read 会携带
各自地址和长度。重复 ID、无效比例、过大反馈窗口和不一致写布局都在打开串口前拒绝。

## 接线选择

### U2D2

最适合首次联调。设备通常表现为 `/dev/ttyUSB*`，`linux_rs485=false`。U2D2 不给电机
供电，必须使用独立电源/Power Hub。USB latency 要设为 1 ms 并实际测量抖动；它不应被
视作硬实时接口。

### Orange Pi 原生 UART

Dynamixel TTL 是单线半双工，不能把 RK3588 的 TX/RX 直接并接。必须使用匹配 3.3V
逻辑的自动方向/电平转换电路。当前实现不在周期线程里翻 GPIO。

RS-485 型号应使用隔离或合适电平的半双工收发器。如果目标 UART 驱动支持 Linux
RS-485 mode，可设置 `linux_rs485=true`，由内核在发送期间控制 RTS/DE。板端必须确认
UART pinmux、驱动的 `TIOCSRS485` 支持和终端电阻。

## 周期和带宽

一次有效周期为：接收上一轮各 ID Status packet → 解码完整反馈 → Sync Write 本轮目标
→ Bulk Read 请求下一轮反馈。启动时先发 Bulk Read，收到全部 ID 后才允许 arm。

runtime 启动期会在 `startup_feedback_timeout` 内按固定间隔等待首个完整反馈；运行期跨
多个 tick 的 `NotReady` 不立即锁存故障，但超过 `state_validity` 仍会进入安全停机。
这两个期限必须根据波特率、ID 数量和最坏 Status packet 时长配置，而不是无限等待。

1 Mbps、8N1 的理论线速约为每毫秒 100 字节，多电机不能仅凭 1 kHz 线程频率就获得
1 kHz 全量反馈。应根据 ID 数、Status packet 长度和误码压力结果选择 57600/1M/2M/4M、
降低反馈频率、拆分多条总线或使用实时现场总线。命令失效、丢 ID 或电机错误最终仍由
runtime lease、安全策略和电机侧 watchdog/Shutdown 共同处理。

官方参考：[Protocol 2.0](https://emanual.robotis.com/docs/en/dxl/protocol2/)、
[Dynamixel SDK](https://emanual.robotis.com/docs/en/software/dynamixel/dynamixel_sdk/overview/)、
[U2D2](https://emanual.robotis.com/docs/en/parts/interface/u2d2/)。
