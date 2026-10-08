# RK3568 启动备份与原内核 Linux 首次板测

2026-10-03：15 项启动相关文件已在电脑端逐一验证 SHA-256；原 4.19.232 内核配合原运行设备树和静态 BusyBox initramfs，已通过 U-Boot 独立启动。随后重启回原 Android 11，`sys.boot_completed=1`；boot、uboot、trust、dtbo、vbmeta 五个分区的 SHA-256 均与测试前一致。最终网络 ADB root shell 可用，串口已关闭释放，printk 恢复为 7/4/1/7，wlan0 MTU 为 1500。

此次运行的是内存中的最小 Linux。没有刷写 boot、保存 U-Boot 环境或发送电机命令；没有验证完整桌面系统、全部外设或生产使用的关机流程。

## 备份范围

两个归档都保存在本目录本地，二进制与原始日志由 `.gitignore` 排除。

| 归档 | 字节数 | SHA-256 |
| --- | ---: | --- |
| original.tar.gz | 18384591 | 8e653d52d144a5a4cf8e18ca2a19211c76a3113509f958e53b259bedb4288380 |
| extra-startup.tar.gz | 903453 | e3a0222546e6a04ca4c996c0830af30bc306874ec11b46db14d0f5760d820af8 |

`original/` 包含 boot（40MiB）、uboot、trust、dtbo（各4MiB）、vbmeta（1MiB）。
`extra/` 包含 security、misc、smdt、baseparameter、eMMC boot0/boot1、前4MiB引导区、末尾33扇区GPT、运行FDT、内核配置。
全部15项原始文件共80945572字节；[manifest.json](manifest.json) 记录每项的长度和摘要。

这是启动相关备份，未备份整个 eMMC、recovery、super、userdata 或 oempriv。没有验证裸机恢复或 OTG 刷机；保留原系统且不改启动分区，是此次试启动的恢复方式。

大文件网络传输多次停滞。用户关闭 TUN 后，电脑到板子的路由已核实为 WLAN 直连，但网络 ADB 一度离线；最终通过串口每8192字节传输并逐块验证 SHA-256，整包再验证 SHA-256。不能把所有传输失败都归因于代理。部分失败下载文件以 `.partial` 或私有临时文件保留，不属于有效备份。

在 WSL 仓库目录重新验证本地文件：

```sh
python3 outputs/rk3568-backup-linux-20261003/verify-backup.py
```

## 首次启动方法

首先在原 Android 内核下通过私有 mount namespace 和 chroot 验证静态 ARM64 用户空间。证据为 [userspace-test.txt](userspace-test.txt)；这一步本身不证明独立启动。

随后在 `/cache/rtctrl-linux-20261003` 创建三个普通文件：从 boot v2 的2048字节页后提取原 Image、复制原运行FDT、复制已验证的 initramfs。没有创建自动启动配置。文件准备脚本为 [prepare-ramboot-files.sh](prepare-ramboot-files.sh)，长度/SHA 见 [ramboot-files.txt](ramboot-files.txt)。

本次串口为 CH340/COM8、1500000/8N1、无流控，DTR/RTS关闭。Android 命令使用 LF；U-Boot 使用 CR。通过原系统重启，并在重启过程中反复发送两个 Ctrl-C 字节，进入 `=>`。`bootdelay=0`，实际中断成功；串口号及板端运行状态下次必须重新核实。

实机只读核查确认：U-Boot 2017.09（2026-03-12），eMMC 为 `mmc 0`，cache 为第12分区 `0:c`；该路径三个文件均可读取。`bdinfo` 表明 U-Boot 已重定位到高地址，低地址可用于此次加载。先执行 U-Boot `reset` 并返回 Android 11，才进行 Linux RAM 启动。

以下加载地址结合本机内存图确定，不能直接套到其他板卡：

| 文件 | 地址 | 文件长度 | CRC32 |
| --- | --- | ---: | --- |
| Image | 0x00280000 | 33046536 | 28e3a67c |
| android-running.dtb | 0x03000000 | 151680 | 60dbf153 |
| initramfs.cpio.gz | 0x04000000 | 533234 | b9718d95 |

Image 头的 `text_offset=0x80000`、`image_size=0x207d000`、`flags=0xa`。完整内核空间为 `[0x00280000,0x022fd000)`；原 U-Boot 二进制的 bit3 分支确认此输入不会搬至低2MiB，见 [uboot-image-review.txt](uboot-image-review.txt)。三次 `ext4load` 与 CRC 均在实机通过。

仅在内存中的 FDT 删除两条旧 Android FDT/initrd 的 memreserve 和 `/chosen` 中旧 initrd 地址、bootargs_ext；保留 `/reserved-memory`。`fdt resize 10000` 为新FDT增加空间并生成新FDT reserve。设置此次有效启动参数及两项禁止搬移的高地址环境变量，均未 `saveenv`。

实际启动命令：

```text
booti 280000 4000000:822f2 3000000
```

此前设置的启动参数为：

```text
console=ttyFIQ0 earlycon=uart8250,mmio32,0xfe660000 rdinit=/init loglevel=7
```

厂商 U-Boot 会在交接时追加板级参数；实际 `/proc/cmdline` 仍保留上述 `rdinit=/init`。文件中原机标识已脱敏。完整逐步命令分别保存在 [load-ram.json](load-ram.json) 和 [boot-ram.json](boot-ram.json)；这些是本次板测记录，重新执行前须再次核查内存与FDT reserve。

## 独立 Linux 的证据与返回

[linux-runtime-check.txt](linux-runtime-check.txt) 为脱敏实机输出：

```text
uname -r
4.19.232
cat /proc/uptime
60.23 228.70
ls /
dev   root  bin   proc  sys   tmp   init
hexdump -C /proc/1/cmdline
00000000  2f 62 69 6e 2f 73 68 00  2f 69 6e 69 74 00        |/bin/sh./init.|
```

`/proc/mounts` 只有 rootfs、devtmpfs、proc、sysfs 和 tmpfs，未挂载任何持久化块文件系统。新内核启动日志、PID1 和根目录共同证明此次已独立运行最小 Linux，区别于前面的 chroot 测试。

确认上述挂载状态后，用 `echo b > /proc/sysrq-trigger` 立即重启返回原 Android。随后重新查询 Android11、`sys.boot_completed=1`、4.19.232，以及五个启动分区完整SHA。返回成功并不等于正常 Linux reboot/shutdown、MCU看门狗或电源断电生命周期已适配；该即时重启方法只用于此次没有持久化挂载的 RAM 测试。

[boot-result.json](boot-result.json) 记录已验证结果和原始日志SHA；[record-results.py](record-results.py) 校验保留的启动/挂载/恢复证据后生成此记录。原始 `.raw.txt` 留本地，包含原机标识，不纳入版本库。

下一阶段可以在同一原内核上构建可持久化的 Linux 根文件系统，补齐启动服务、Wi-Fi固件和网络工具；MCU/看门狗/正常关机须单独适配。当前结果不证明 Android 的 `.so` 能直接用于常规 Linux，也未验证电机、摄像头或其他外设功能。原内核和配套设备树已证明可用于最小 Linux 首次启动，无需继续逐项反编译设备树来完成这一阶段。
