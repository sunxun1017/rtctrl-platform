# 下一轮外设适配的源码证据

本文件保留当轮只读调查。后续结果：[加速度计](../rk3568-accelerometer-20261004/README.md)、
[CAP1188身份诊断](../rk3568-cap1188-20261004/README.md)、
[RK809声卡接口](../rk3568-audio-20261005/README.md)。前两项身份尚未通过，RK809仅接口通过。

本轮仅完成 UART0 驱动枚举和 USB 麦克风格式对照。以下来自锁定原运行树、
5.10 源码及已实测 Image 配置的只读审查，没有启用、探测或校准这些外设。

## 优先处理 MXC6655 加速度计

原节点在 I²C5 `fe5e0000`，地址 `0x15`，compatible 为 `gs_mxc6655xa`。
I²C5 M0 使用 GPIO3_B3/B4、mux4、无内部上下拉且启用施密特输入；
IRQ 为 GPIO3_C1。原配置 `irq_enable=0`、30ms、`layout=1`。
这些引脚与本轮 UART0 GPIO0_C0/C1 不冲突。当前证据仅确认加速度计，不能称为六轴 IMU。

已有 GPL 实现是 `drivers/input/sensors/accel/mxc6655xa.c`。
当前 Image 的 `CONFIG_SENSOR_DEVICE=n`，没有对应驱动对象；只启用 DTS 不会得到可用驱动。
实际构建链为 `sensor_dev.o` 加 `accel/mxc6655xa.o`，需选择 `SENSOR_DEVICE`、
`GSENSOR_DEVICE` 和 `GS_MXC6655XA`，并重新核对与 Image 匹配的产物。

最小设备树变化是启用 I²C5，仅加入该 `@15` 子节点及其 pinctrl。
保持电源 MCU `@62`、EEPROM 及其他未知设备缺席；不通过总线扫描寻找地址。
原节点没有明确的 regulator/reset/power 属性，这不能证明器件电压或独立供电控制。
保留现有 IO-domain 与供电映射。

首轮初始化会写 CONTROL=`0x01` 并设置 `SENSOR_OFF`；轮询初始 `stop_work=1`，
没有自动排队。它使用 input/evdev 接口。首次只验身份及默认关闭，不启动采样或写校准。
`sensor-dev.c:221` 的校准入口调用 `rk_vendor_write`，涉及持久存储，不能混入身份检查。

必须先处理源码中两个错误传播问题：

- `sensor-dev.c:2004` 丢弃 `sensor_probe()` 返回值，随后恒返0。探测或初始化失败也可能留下
  driver 绑定，因此 symlink 不是芯片验收。测试须覆盖正确/错误 ID、I²C失败和初始化失败。
- `sensor-i2c.c:86` 部分传输返回正数，调用者通常只检查负数；`sensor_read_reg():147`
  忽略读取错误。需验证负错误和短传输，并让 MXC 初始化/active 路径传播失败。

验收应同时包含 ID=`0x05`、成功初始化、准确绑定及默认 OFF；不能只读“initialized ok”日志。
源码行号适用于内核 commit `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`。
本轮没有生成新的传感器 Image、模块或 DTB，也没有验证这些修正。

## CAP1188 需要单独的 SPI 实现

原连接 SPI3 M1、CS0，100kHz、mode3。总线使用 GPIO4_C2/C5/C3，CS GPIO4_C6，
reset GPIO0_B6，原 flags=0，没有 IRQ 描述。
当前 SPI3 默认 M0；当前 `KEYBOARD_CAP11XX=n`，已有 `cap11xx.c` 仅支持 I²C且要求 IRQ。
不能把它绑定到原 SPI 节点。后续应按芯片资料验证 SPI 协议、reset、电源及轮询/IRQ方式，
再实现传输和事件；设备树本身不足以恢复原阈值与滤波策略。

## 板载 RK809 音频仍未恢复

PMIC I²C0/@20 codec 接 I²S1 `fe410000`；MCLK GPIO1_A2、12.288MHz；
SCLK/LRCK/SDI/SDO 为 GPIO1_A3/A5/B3/A7；功放 GPIO4_C4，低有效。
当前 simple-card/I²S TDM 已编入，`SND_SOC_RK817=n`，板级 codec/sound 节点缺席。
probe 会申请功放输出 GPIO、启用 MCLK并写寄存器。须先约定静音/功放默认关闭、
验证路由和供电，再单独验播放；本轮 USB 麦克风枚举不能代表这张板载声卡通过。
