# PatchX MCU 字节协议

`rtctrl_patchx_codec` 是独立 C++17 叶子适配器，负责帧编码和流重组。
不包含 Android、Rockchip、GD32、POSIX 串口或设备路径依赖；不打开设备，不发送动作。
源码依据、候选命令和待验证项见 [协议审计](../../../docs/verification-patchx-protocol-20260921.md)。

## 使用边界

本层只知道 `uint8_t command` 和原始载荷字节。`encode_frame()` 不表示命令可以安全发送，
`StreamParser::pop()` 成功只表示一帧符合已知发送格式，不表示真实 MCU 的应答、运动完成或状态有效。
尚无可信接收抓包来确认 MCU 返回帧采用相同格式。

现有 `IActuatorProtocol` 需要 SI 单位、可信反馈及 `open_safe/arm/safe-stop` 契约。
Android 源码不足以满足这些条件，因此本适配器没有实现该接口，不修改现有 runtime 或 HAL。
实际业务应依赖领域接口，由产品装配处选择具体协议；不要向通用控制模块引入 PatchX 命令号。

## 格式与容量

```text
FF FF | BE16(1 + payload_size) | command | payload |
BE16(CRC16/Modbus over length + command + payload) | 55 AA
```

CRC 初值 `FFFF`，反射多项式 `A001`，无末异或。CRC 在线上高字节先，不能使用通常的
Modbus RTU 低字节先顺序。载荷不转义，允许出现帧头和帧尾。

本实现载荷上限为 260 字节，能容纳原发送器的 4 字节升级元数据和 256 字节块；这是本地容量，
不是 MCU 已确认的最大载荷。每帧最大 269 字节，解析缓存 538 字节。所有存储为固定数组，
没有动态分配、文件日志、锁、线程或物理 I/O。解析有界但未测最坏运行时间，放在非实时接收线程。

## 集成方式

包含 `rtctrl/adapters/patchx/patchx_codec.hpp`，链接 `rtctrl_patchx_codec`。
编码成功时 `WireFrame.size` 给出有效字节数，失败时为零；载荷过大或非空载荷指针为空均拒绝。

接收线程通过注入的 `IByteTransport::try_receive()` 获得字节，再调用 `push()` 和 `pop()`：

1. 每次接收块不大于一帧容量；前一次输入后先循环 `pop()`，直到没有完整帧。
2. `push()` 溢出时整体拒绝，不覆盖旧数据；调用者保留尚未接受的输入，先排空、分块再重试。
3. `pop()` 失败不改输出对象。坏 CRC、帧尾或无效长度会跳过并重新寻找帧头。
4. 看起来有效但尚未收齐的长度必须继续等待，不能把载荷内的帧头误当新帧；调用者维护
   字节间超时，超时或重连时 `reset()` 清除残片。解析器自身不读取时钟。
5. 将完整帧交给独立的命令/反馈语义层验证。传输成功、格式有效、设备确认和运动完成是不同状态。

测试通过现有 loopback 的 `IByteTransport` 逐字节输入，证明串口碎片处理不依赖具体平台。
未提供发包 CLI、串口默认地址、动作重试、固件升级流程或硬件使能入口。

## 离线验证

```sh
cmake -S . -B build/patchx-release -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/patchx-release --target rtctrl_patchx_codec_test
ctest --test-dir build/patchx-release -R rtctrl_patchx_codec_test --output-on-failure
```

`RTCTRL_BUILD_CONTROL=ON` 时构建适配器；`RTCTRL_BUILD_TESTS=ON` 时在自身子目录注册测试。
无需开启串口能力。测试覆盖独立字节向量、全部两片拆分位置、逐字节读取、连续帧、CRC/数据/尾部损坏、
长度边界、嵌入分隔符、溢出保留、超时/重连重置。完整验证结果见上述审计记录。

开启 `RTCTRL_ENABLE_SERIAL` 后另有 `rtctrl_patchx_pty_test`，通过内核创建的 PTY 验证实际
Linux 串口适配器与 codec 的双向收发、空闲和挂断；不会打开任何实物串口。
PC/ARM64 QEMU 用户态的复现命令、已发现缺陷与验证边界见
[PC 验证记录](../../../docs/verification-pc-qemu-20260921.md)。
