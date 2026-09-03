# ADR-0004：电机协议与通信链路正交

状态：Accepted，2026-09-02。

## 背景

同一种执行器语义可能经串口、CAN-FD 或 EtherCAT 交付；同一种通信链路也可能服务
不同电机协议。把 `MotorXCanDriver`、`MotorXEthercatDriver` 作为核心抽象会重复安全状态机、
单位换算和反馈校验，并迫使控制器知道部署总线。

三种链路的原生模型并不相同：串口是可短读写的字节流，CAN-FD 是带 ID 的报文，
EtherCAT 是周期过程映像。为了表面统一而让它们共同实现字节流接口，会丢失边界和实时
属性。

## 决策

控制器和 runtime 只依赖 `IActuatorHal`。真实执行器 HAL 由两个正交依赖组成：

```text
motor/device protocol codec       communication link adapter
command words, units, scaling     serial / CAN-FD / IgH EtherCAT
feedback validation               endpoint routing and physical I/O
                 \               /
                  ProtocolActuatorHal
                           |
                     IActuatorHal
```

`IActuatorProtocol` 只在 SI 单位的 `CommandFrame`/`SensorFrame` 与固定容量
`ActuatorPacketBatch` 之间转换。包只携带逻辑 endpoint 和固定上限 payload，不携带
设备路径、波特率、CAN ID、PDO offset 或 vendor SDK 类型。

`IActuatorLink` 根据部署路由表把逻辑 endpoint 映射到串口地址/帧、CAN ID 或 EtherCAT
PDO。它不解释控制字、寄存器、单位或电机型号。

composition root 分别选择一个协议实例和一个链路实例，再构造
`ProtocolActuatorHal`。启动后不自动探测、不回退、不切换链路，也不同时打开未选中的
物理总线。兼容性由部署配置和启动期校验决定，不在实时周期内协商。

## 实时与安全约束

- packet/batch 固定容量，启动后无动态分配。
- 串口重组、CAN 过滤与 PDO offset 路由由链路适配器在启动前配置。
- arm、普通命令与 safe-stop 都由同一个协议 codec 编码，经同一个已选链路发送。
- `ProtocolActuatorHal` 保持 `open_safe -> first read -> arm -> write` 生命周期；safe-stop
  后重新禁止普通写入。
- 请求—应答链路允许反馈跨有限个周期返回；runtime 只在 startup/state lease 内接受
  `NotReady`，超过期限按通信故障安全停机。
- 不声称任意协议天然兼容任意链路；若 payload、周期或路由能力不满足，composition
root 必须拒绝启动，而不是把电机类型和总线类型重新耦合成一个类。
- link capability 与 protocol requirement 在 composition root 比较；例如 CAN-FD link
  可声明单包 64 字节，而串口/EtherCAT link 可声明更大上限。核心上限不采用 CAN 常量。
