# Linux CAN-FD 接入

`SocketCanFdTransport` 是基于 Linux 官方 SocketCAN RAW API 的非阻塞帧级适配器。它同时收发 Classical CAN 和 CAN-FD，不绑定电机厂商、CAN ID 分配、量纲或控制模式。

## 职责边界

适配器负责：

- 标准帧与扩展帧；
- CAN-FD 64 字节 payload、BRS 和 ESI；
- Classical CAN RTR；
- 最多 32 个内核接收过滤器；
- SocketCAN 错误帧；
- `SO_TIMESTAMPNS` 内核接收时间戳；
- 非阻塞、无动态分配的单帧收发。

适配器不负责配置控制器 bitrate，也不猜测电机协议。bitrate、data bitrate、采样点和自动重启属于网络接口部署配置；电机 CAN ID、帧布局、单位换算、使能状态机和 watchdog 应由独立的设备 codec/HAL 实现。

## 配置物理接口

下面仅为常见示例，bitrate 必须按控制器、收发器和总线上的设备手册确定：

```bash
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 1000000 dbitrate 5000000 fd on restart-ms 100
sudo ip link set can0 up
ip -details -statistics link show can0
```

RK3588 BSP 还必须正确提供 CAN 控制器 pinmux、时钟和收发器 enable/standby GPIO。SocketCAN 适配器不会绕过或替代内核控制器驱动。

## 无硬件环回

内核启用 `vcan` 后可以验证软件收发：

```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set vcan0 up
RTCTRL_VCAN_INTERFACE=vcan0 ctest --test-dir build/release \
  -R rtctrl_socketcan_vcan_test --output-on-failure
```

`vcan` 只能验证 SocketCAN 路径和上层协议，不能验证 CAN-FD bit timing、收发器、电气终端、电磁兼容性或真实总线负载。

## C++ 使用示例

```cpp
#include <rtctrl/transport/socketcan_fd_transport.hpp>

rtctrl::transport::SocketCanFdTransport can("can0");
const rtctrl::transport::CanFilter filters[]{{0x180, 0x7f0, false}};
if (!can.set_filters(filters, 1) ||
    can.open() != rtctrl::transport::TransportStatus::Ok) {
  // can.last_error() is an errno value.
}

rtctrl::transport::CanFrame command{};
command.id = 0x101;
command.fd = true;
command.bit_rate_switch = true;
command.size = 16;
const auto tx = can.try_send(command);

rtctrl::transport::CanFrame feedback{};
const auto rx = can.try_receive(feedback);
```

`try_receive()` 在没有帧时返回 `WouldBlock`。接口掉线对应 `Closed` 或 `Error`，上层必须立即停止续租并走安全停机路径。收到的 `timestamp_ns` 来自 Linux `SO_TIMESTAMPNS`（系统实时时钟），不能直接与项目的 `CLOCK_MONOTONIC` 租约时间相减；控制新鲜度应在接收线程用本地 monotonic 时间记录。

## 接入电机 HAL

一个具体电机族仍需实现以下叶子层：

```text
IActuatorHal
  -> 电机状态机、watchdog、单位换算、CAN ID 路由
  -> 厂商帧 codec
  -> ICanTransport / SocketCanFdTransport
  -> Linux SocketCAN
```

只有拿到电机协议文档后才能正确实现 codec 和安全状态机。不要用“通用猜测帧”直接使能执行器。
