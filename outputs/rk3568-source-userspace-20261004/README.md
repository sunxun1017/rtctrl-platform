# RK3568 源码内核与持久化用户空间对照

后续补充：本轮发现的SysRq RCU睡眠缺陷已最小修正并用新Image实机对照，一次同路径复位未再捕获警告。
见[RCU修正记录](../rk3568-rcu-reset-20261004/README.md)；本文件保留原始板测及警告事实。

2026-10-04：新编译的 Linux 5.10.160-rt89 已实机运行，同一份独立源码 codec/PTY 程序在
原 Android 4.19.232 与新 Linux 中均通过。Android 写入标记、Linux 回读并写入新标记、
返回 Android 后两份标记与 SHA-256 均一致。五个启动分区的全分区 SHA-256 前后未变。

板子已返回原 Android 11，boot_completed=1、root 已通过串口再次确认，串口已释放。
ADB 在准备和返回回读阶段可用，随后再次 offline/TCP 超时；最终串口确认 adbd 仍运行且
wlan0 有 IPv4。不能把本次成功传输当作网络已经稳定。结束时电量52%，AC/USB powered=false。

**SysRq 即时复位出现 RCU 睡眠警告，正常重启、关机及 MCU 生命周期仍未验收。**
这是可重复检查的阶段性板测，不是可部署整机镜像；PID1 仍在 RAM，持久化 rootfs 只供短命子进程 chroot。

## 新内核改了什么

源码锁定 commit `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`，构建工具为 GCC 11.4，
release 为 `5.10.160-rt89-g9f9e9d18574d-dirty`。release 与上一轮相同，必须用 Image SHA 区分产物。

- [firstboot.cfg](../../platforms/rk3568/boards/aiot-3568pq/firstboot.cfg) 关闭未使用的
  RK817 charger、multi-RGA、SCMI power-domain/reset 客户端。最终完整配置已检查；
  SCMI clocks、CRU reset、PMIC、IO 域、温度、eMMC、loop/ext4 与 PTY 保留。
- 沿用 [cache/KASAN include 补丁](../../platforms/rk3568/boards/aiot-3568pq/patches/0001-arm64-cache-kasan-include.patch)，
  新增 [RK817 诊断补丁](../../platforms/rk3568/boards/aiot-3568pq/patches/0002-rk817-feedback-diagnostic.patch)。
  后者只修正缺少反馈属性时打印未初始化变量的问题；原属性读取、寄存器写入分支、值和次序不变。
  不猜填 DDR 电压或反馈属性，不把日志中的 selector 值当作物理测量。
- DTB 仍使用板级源码，保留高地址 no-map、loader logo/LUT 与原内存范围。
  编译后53项审计及12项故障注入通过；本轮 DTB 与上一轮最终 DTB 字节相同。

启动输出未再出现 SCMI protocol 17/22 与 RGA iommu 警告，新 PMIC 日志明确打印
`external (fb-inner-reg-idxs unavailable: -22)`。MFD 的 battery/charger/codec 缺 of_node 警告仍存在，
另有 FIQ 可选 IRQ/NMI、regulatory.db 提示。短时启动未匹配 panic/Oops/BUG/Call trace，
复位阶段的 Call trace 单独保留；没有长时稳定性或实时延迟结论。

## 实际板测顺序

1. 重新确认 Android/root/网络/串口。在新实验目录创建64 MiB普通 ext4 文件，
   只格式化这个新文件；不覆盖上一轮 rootfs，不格式化任何分区。
2. Android 私有 mount namespace 中挂载该文件，绑定 /dev、单独绑定 /dev/pts、挂 proc/sys，
   chroot 运行源码 codec 与 POSIX PTY 测试，写入 Android 标记，完整卸载并释放 loop。
3. U-Boot 现场复核 mmc0/cache 0:c 与内存范围，加载 Image/DTB/initramfs 并逐项核对 CRC。
   RAM 中设置 kernel_addr_r=0x00400000，与 booti 地址一致；未 saveenv。
   删除旧 Android initrd 的两项 memreserve，只改内存 FDT。新内核进入 RAM /init shell。
4. Linux 首先用只读 loop 与 `ro,noload` 挂载 cache/rootfs，核对原文件 SHA 与 Android 标记后完整清理。
   再分别重新以可写方式挂载 cache/rootfs，chroot 运行相同两个程序，写入 Linux 标记并同步。
   **这个阶段确实写入了 cache 和普通 rootfs 文件；只有清理完成后才恢复为 RAM-only。**
5. 卸载 chroot 内 /dev/pts、sys/proc、/dev、rootfs、cache，释放本轮 loop 与 RAM devpts。
   独立检查挂载只剩 rootfs/devtmpfs/proc/sysfs/tmpfs、loop 列表为空后才请求 SysRq 复位。
6. 返回 Android，用只读 loop 与 `ro,noload` 回读两份标记及 SHA，完整清理。
   boot/uboot/trust/dtbo/vbmeta 全分区 SHA 前后相同。最终另用串口确认 Android/root/电量及服务状态。

Linux 实测 rk808、fan53555-regulator、rockchip-iodomain、rockchip-thermal 已绑定；
温度样本41.875/41.250℃，测试后 uptime104.60秒。新根文件系统没有厂商用户库、原4.19模块或固件。
两个程序只测试独立 codec 和伪终端，不打开物理 UART，不验证实际电机、MCU ACK 或安全停止。

## 输入与复现入口

| 输入 | 字节数 | SHA-256 |
| --- | ---: | --- |
| Image | 34755072 | b230838582b655f7786564ff21670ab1cd29172488df9c367a77d7005708c260 |
| firstboot.dtb | 161378 | 20c8f026b71fe4e8a8752a9407087eb05b4e4819b3fa7e2f4845be17727d8c15 |
| initramfs.cpio.gz | 621515 | 7e5c405148ee46e44d845d0c123d469c4d848fbe928f6ed3e448cfed98d57e5c |
| rootfs.tar.gz | 2114047 | 81c751c33fb79be0d1e94be770dce155dfd3f380f0cacfe4afaa5778d8be7243 |

Image 头部 text_offset=0，含 BSS 的内存跨度35389440字节，运行加载范围
`[0x00400000, 0x025c0000)`，不能用文件长度代替内存跨度。
DTB 载入0x03000000，initramfs载入0x04000000、结束0x04097bcb。
配置、补丁 SHA 和 CRC 见 [kernel-artifacts.json](kernel-artifacts.json) 与 [boot-inputs.sha256](boot-inputs.sha256)。

[build-kernel.sh](build-kernel.sh) 是本轮实际构建入口：先生成配置，再临时应用两个补丁，
编译 Image 后只反向撤销自身补丁并检查源码干净。输出必须是新目录；现有同名产物会拒绝覆盖。
第一版使用 prepare-headers 时触发 RT 头文件 include-cycle，失败日志保留在 private；
最终流程在应用 cache 补丁后由完整 Image 构建生成所需头文件，已成功完成。

[build-userspace.py](build-userspace.py) 打包源构建 BusyBox 1.36.1 与上一阶段已经核对的两个静态
AArch64 CMake 产物，检查 ELF/哈希，不在本轮重新编译两个程序。
BusyBox 来源和构建见[原用户空间记录](../rk3568-persistent-linux-20261003/README.md)，
程序构建见[源码测试入口](../rk3568-mcu-baseline-20261003/build-source-tests.sh)。
当前打包入口依赖本地已有的这些经验证输入和同版本 DTC，尚不是全新 clone 后的一键构建流程。
静态 BusyBox 按 GPLv2 记录源码/许可证，独立程序使用本仓库源码；二进制与 raw 采集未纳入公开文件。

[prepare-android.sh](prepare-android.sh) 与 [readback-android.sh](readback-android.sh) 负责原系统
基线和回读；[ram-init.sh](ram-init.sh)、[test-userspace.sh](test-userspace.sh)、[check-base.sh](check-base.sh)
定义 RAM PID1 与 chroot 测试。[load-ram.json](load-ram.json)、[boot-ram.json](boot-ram.json)、
[linux-check.json](linux-check.json)、[return-android.json](return-android.json) 记录板端串口步骤。
复现前必须重新核对设备、分区和内存地址，不能套用旧串口号/IP或未经核验的挂载设备。

## 复位警告与下一步

[复位调用栈](reset-warning.txt) 是 `__handle_sysrq → emergency_restart → kmsg_dump → pr_flush → msleep`
触发 `rcu_note_context_switch`。锁定源码中 `drivers/tty/sysrq.c` 的外层 RCU 读锁包住重启回调；
`kernel/reboot.c` 在硬件复位前 dump 日志；`kernel/printk/printk.c` 的等待日志分支未排除该 RCU 读侧。
调用栈在进入 PMIC/MCU 复位处理前报警。这几处源码本轮没有新增修改，不能归因于 rootfs 或诊断补丁。
日志无积压时 flush 可以直接返回，旧轮未观察到警告不能证明路径安全。

后续先修正并独立验证 SysRq/printk 的 RCU 上下文约束，再做正常重启、电源生命周期与网络对照。
普通 reboot 不持有这处 SysRq 外层读锁，但硬件 shutdown/reset hook 仍须另行验证。
正式 rootfs 介质、switch_root/自动启动、Wi-Fi 关联与传输、NPU/音视频和真实 MCU 运动依次验收。
原 DDR/loader/trust、Wi-Fi/MCU 固件缺口仍单列，不能宣称整机完全开源。

## 证据

[result.json](result.json) 是本轮运行结果，里面的 kernel/userspace_inputs 保留构建输入清单，
嵌套清单的 board_tested=false 仅表示生成清单时尚未板测；本轮实测字段位于顶层。
[linux-runtime-check.txt](linux-runtime-check.txt)、[boot-excerpt.txt](boot-excerpt.txt)、
[reset-warning.txt](reset-warning.txt) 为脱敏运行证据；[verification.txt](verification.txt) 记录主机复核。
原始记录及其 SHA 单列在 result.json，raw、原厂二进制、CPU/eMMC标识和网络地址只留在忽略的 private 目录。
本轮生成的Image/DTB/归档由.gitignore排除，不纳入公开文件。
没有提交、推送、saveenv、刷写启动分区或下发电机命令。
