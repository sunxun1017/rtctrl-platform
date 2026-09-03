# 专用 EtherCAT 网卡：Intel I210 + IgH `ec_igb`

本项目固定推荐 Intel I210 PCIe 网卡作为单口 EtherCAT 主站接口；I211、I350
也在同一 IgH native `igb` 驱动支持范围内。该端口物理专用于 EtherCAT，不承载
管理网络、IP、SSH 或普通以太网流量。RK3588 载板必须提供可用的 PCIe 链路；不建议
用 USB 网卡替代实时现场总线接口。

IgH 的 `ec_igb` 是基于 Linux `igb` 的原生 EtherCAT 驱动，不走 generic/raw-socket
数据路径。IgH 1.6.12 自带 Linux 5.10、6.1、6.8、6.12 的驱动快照，并包含 I210、
I211、I350 的 PCI ID。独立 PCIe 功能还便于给 MSI-X IRQ、CPU affinity 和电源策略
做单独控制。

## 获取与编译

仓库通过 Git 子模块锁定官方 IgH 1.6.12 tag 和其 peeled commit；第三方源码保持
独立历史，不复制进本项目的 MIT 源码提交：

```bash
git submodule update --init --recursive
./scripts/check-third-party.sh
./kernel/ethercat/build-igh-igb.sh \
  third_party/igh-ethercat \
  /absolute/path/to/prepared-linux-build \
  .deps/rtctrl-igh-igb-build
```

`fetch-igh.sh` 保留为脱离主仓库使用构建工具时的备用入口。`build/` 与 `.deps/`
均被 Git 忽略，禁止提交目标内核生成的 `.ko`、sysroot 或本机安装前缀。

构建脚本只启用 native `igb`，关闭 generic driver、EoE 和实时循环 syslog，启用
hrtimer，并以 `W=1` 编译内核模块。它检查目标内核版本是否有对应的 IgH 快照，最后
验证 `ec_master.ko` 与 `ec_igb.ko` 的 vermagic 一致。脚本不会安装或加载模块。

ARM64 交叉编译示例：

```bash
ARCH=arm64 \
CROSS_COMPILE=aarch64-linux-gnu- \
RTCTRL_IGH_HOST=aarch64-linux-gnu \
./kernel/ethercat/build-igh-igb.sh \
  third_party/igh-ethercat \
  /absolute/path/to/rk3588-linux-build \
  .deps/rtctrl-igh-igb-arm64
```

必须使用目标板最终运行的、已经配置并 prepare/modules_prepare 的 BSP/PREEMPT_RT
内核构建树。为桌面机内核编出的模块不能复制到 RK3588 使用。

## 绑定前检查

安装或加载模块前，先用接口名验证 PCI ID、当前驱动和路由隔离：

```bash
./kernel/ethercat/check-intel-igb-nic.sh enp2s0
```

检查通过后，把脚本打印的永久 MAC 地址填入
[`config/ethercat-igb.conf.example`](../config/ethercat-igb.conf.example)，再作为目标机
`/etc/ethercat.conf` 的部署输入。不要用 `ff:ff:ff:ff:ff:ff` 通配符，避免主站抢占
错误网卡。由 `ec_igb` 接管后，该端口不再是普通 Linux IP 接口；管理网络必须使用
另一块网卡。

## 通信链路与电机协议独立注入

`ActuatorLinkBackend` 和 `inject_actuator_dependencies()` 位于
[`actuator_composition.hpp`](../include/rtctrl/hal/actuator_composition.hpp)。composition
root 在创建实时线程前分别注入通信链路和电机协议：

```cpp
rtctrl::hal::ActuatorLinkProviders links{
    .serial = serial_link,
    .can_fd = can_link,
    .igh_ethercat = ethercat_link,
};
auto dependencies = rtctrl::hal::inject_actuator_dependencies(
    rtctrl::hal::ActuatorLinkBackend::IghEthercat, links, motor_protocol);
rtctrl::hal::ProtocolActuatorHal actuator(
    *dependencies.link, *dependencies.protocol);
```

同一个 `motor_protocol` 可与串口、CAN-FD 或 EtherCAT link 组合；电机 codec 不包含
MAC、CAN ID、串口路径或 PDO offset。只允许选中的 link 执行 `open()`；不要在周期线程
内探测、切换或同时服务多个物理总线。三份 `linux-rt-*.toml` 表达互斥部署意图；当前
项目尚未提供 TOML 解析器，部署层应将选择映射到 composition root。

## 实时部署边界

- 使用 PREEMPT_RT、高分辨率定时器，并把 EtherCAT 周期线程固定到隔离 CPU。
- 从 `/proc/interrupts` 确认 I210 MSI-X IRQ，再基于压力测试设置 affinity；不要预先
  写死 RK3588 CPU 或 IRQ 编号。
- 在进入周期循环前完成 master/domain/PDO/SDO/DC 配置、内存预触页和 `mlockall`。
- 禁止周期内日志、动态分配、设备探测与配置解析；周期内只做
  receive/process、process-data 读写、queue/send。
- 关闭该 PCIe 功能的 runtime power management；ASPM、CPU governor 和频率策略需
  以板端抖动数据决定。
- 武装前必须同时满足 link up、从站 online/OP、Working Counter 达标、DC 收敛和命令
  租约新鲜。任一条件失效立即走安全停机。

真机验收至少覆盖：长时间 cyclictest/周期抖动、总线压力下 WKC 零丢失、DC 偏差、
拔线/从站掉电、主站进程退出、watchdog 和重新上电后的默认未武装状态。
