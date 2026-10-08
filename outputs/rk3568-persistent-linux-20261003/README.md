# RK3568 原内核持久化 Linux 用户空间板测

2026-10-03：复用原 4.19.232 Image 和运行设备树，独立 Linux 成功使用 64 MiB ext4 文件中的用户空间。
Android → Linux → Android 标记读写和 SHA-256 一致；原 Wi-Fi 模块、固件在 Linux 加载成功。
结束时已回到 Android 11，boot_completed=1，五个原启动分区 SHA 与备份一致，串口已释放。

PID1 仍为 RAM 中的 `/bin/sh /init`，持久文件系统供子进程 chroot 使用。
没有 switch_root、自动启动 Linux 或完整发行版验收。原启动备份见[上一阶段](../rk3568-backup-linux-20261003/README.md)。

用户后续要求可公开重建、优先去掉厂家定制黑盒，见[源码与替代接口审计](../rk3568-open-source-audit-20261003/README.md)。
本页的原 4.19 二进制用于过渡验证，尚未取得完整对应源码；[源码构建的 5.10 候选](../rk3568-boot-preparation-20260928/README.md)尚未上板。

## 已验证结果

| 对象 | 实际结果 | 边界 |
| --- | --- | --- |
| Android 基线 | 模块/驱动绑定、实际固件请求、六个 `.so` 的 ELF 依赖和现有进程映射 | 没有任意 dlopen；库映射不等于功能正确 |
| 用户空间 | 静态 AArch64 BusyBox 1.36.1，无 PT_INTERP，51 个 applet；QEMU 用户态、Android chroot 和独立 Linux 均通过 | QEMU 不代表板级内核测试 |
| 存储 | 普通文件 `/cache/rtctrl-linux-20261003/rootfs.ext4`，67108864 字节；Linux 读 Android 标记、写 Linux 标记，Android 回读一致 | 只格式化新普通文件；cache 会被清理，尚未选择正式 rootfs 介质 |
| Wi-Fi | 原 bcmdhd.ko 载入；固件 611103 字节、NVRAM 2874 字节打开成功；Firmware 7.45.96.150；wlan0 UP/LOWER_UP | 独立 Linux 尚未关联路由器、DHCP 或网络传输 |
| 其他驱动 | renderD129→RKNPU，driver v0.7.2；ISP/video、两张声卡、McuCom/gsensor/cap1188 枚举与 Android 对照 | 未推理、采帧、采音或发执行器命令 |
| 返回 Android | 模块、rootfs/cache 挂载和本轮 loop 均释放；仅剩 RAM/虚拟挂载后普通内核 reboot 返回 Android | 不证明 MCU ACK、看门狗接管或整板掉电策略 |

证据：[result.json](result.json)、[脱敏板测摘要](linux-runtime-check.txt)、[Android 回读](android-readback.txt)、
[原启动分区复核](android-final-check.txt)。后续驱动、库和功能测试顺序见 [MIGRATION.md](MIGRATION.md)。

## 产物与实际执行顺序

新 BusyBox/initramfs 与旧 15-applet 产物分开保存；没有替换旧候选。
[artifacts.json](artifacts.json) 保存长度、SHA-256、CRC 和 applet 清单。

| 新对象 | 字节数 | SHA-256 |
| --- | ---: | --- |
| BusyBox | 1202816 | `5c2f1c653fdfe92d21c5baa68a64a460dd9aff3b8947d526048314700e1d5844` |
| rootfs 压缩包 | 627792 | `6bf3cba924359765b9848dc0638ba9a73fdea98994b89fb64ad39edb3bbc914d` |
| RAM bootstrap | 621289 | `157acfd6f5d3ffbdcebe6ea492fe3b9e01a48207323c14fdb9bf25425437dc65` |

1. [inventory-android.sh](inventory-android.sh)、[collect-elf.py](collect-elf.py) 收集小型 Android 基线，
   [elf-metadata.json](elf-metadata.json) 记录六个库的动态依赖及原模块 vermagic。
2. [build-busybox.sh](build-busybox.sh)、[build-rootfs.py](build-rootfs.py) 构建用户空间；
   [prepare-rootfs-android.sh](prepare-rootfs-android.sh) 在 Android 组装普通 ext4 文件、chroot 检查、卸载重挂。
   原 ko 和两份固件直接在板内复制，没有回传整份 vendor/super。
3. [inspect-uboot.ps1](inspect-uboot.ps1) 重新检查运行 U-Boot 的 DRAM、GPT 和文件。
   本次 eMMC=mmc0、cache=0:c；[load-ram.json](load-ram.json) 将 Image/FDT/initrd 分别读到
   0x00280000/0x03000000/0x04000000，CRC=28e3a67c/60dbf153/898d6391。
4. [boot-ram.json](boot-ram.json) 只修改内存 FDT/环境，保留板级 reserved-memory，清除原 Android initrd/chosen 引用，
   使用 initrd 长度 0x97ae9 执行 booti；没有 saveenv 或启动分区刷写。
5. [linux-baseline.json](linux-baseline.json) 检查 PID1、驱动及 cache 的 PARTNAME/786432 扇区；
   [open-rootfs.sh](open-rootfs.sh) 挂载镜像供 chroot 使用；核对原模块/固件 SHA、读取和写入标记。
6. Wi-Fi 固件测试后，[linux-cleanup.json](linux-cleanup.json) 停接口、卸模块、退出 chroot 清理；
   [linux-loop-check.json](linux-loop-check.json) 复核只剩虚拟挂载、loop 未绑定，才执行 [linux-reboot.json](linux-reboot.json)。
7. [readback-android.sh](readback-android.sh) 在私有 namespace 只读重挂回读，清理后复核启动分区，恢复 printk 7/4/1/7。

本轮串口为 CH340/COM8、1500000/8N1；Android/Linux 用 LF，U-Boot 用 CR。
下次必须重查端口、地址、分区编号和产物校验，不能直接套用旧现场。
板端保留的 `rootfs-preflight-1.ext4` 是第一次 PATH 检查失败的诊断文件，本次未使用。
两份 ext4 文件及本轮普通启动文件最终为 0600。cache 中的文件不能作为正式恢复副本的替代。

## Wi-Fi 路径排错

初始 firmware_class.path 为 RAM 视角的 `/mnt/root/vendor/etc/firmware`，chroot 内启用接口时得到固件 `-2`。
后续用 echo 修改字符串参数又存入了 LF，hexdump 末尾为两个 0a；改用不带换行的 printf 后末尾一个 0a，
接口开启、固件读取均通过。getter 自身补一个 LF，正常读回的一份 LF 不等于写入的字符。

成功方案将两份固件同时放在 chroot 与 RAM 根的 `/vendor/etc/firmware`；只做板内复制：

```sh
# 在本轮 chroot 中，原模块和两份固件已校验并且 ko 已载入后执行。
cp /vendor/etc/firmware/fw_bcm43456c5_ag.bin \
    /proc/1/root/vendor/etc/firmware/fw_bcm43456c5_ag.bin
cp /vendor/etc/firmware/nvram_ap6256.txt \
    /proc/1/root/vendor/etc/firmware/nvram_ap6256.txt
printf '%s' '/vendor/etc/firmware' \
    > /sys/module/firmware_class/parameters/path
ip link set wlan0 up
```

实测成功日志为 `linux-wifi-path-bytes.raw.txt`；初次失败及路径探索 JSON 保留为排错记录，不是推荐重放步骤。
外部 config.txt/CLM 文件缺失仍有 -2；没有伪造原机未找到的文件。
原 [v4.19.232 固件加载器](https://github.com/gregkh/linux/blob/v4.19.232/drivers/base/firmware_loader/main.c)
使用 kernel_read_file_from_path；[字符串参数 setter](https://github.com/gregkh/linux/blob/v4.19.232/kernel/params.c)
不裁掉写入的 LF。执行请求的根目录受调用语境影响，不能套用较新 _initns 实现。
本次没有锁定 DHD 请求线程，也未做“仅 chroot 副本且无 LF”的独立对照；结论限定为当前两侧可见方案通过。

## 清理修复与验证说明

- Android 首次内联 chroot 命令继承原 PATH，找不到新工具；显式设 /bin PATH 和 set -e 后重新组装通过。
- 清理脚本补 HUP/INT/TERM→exit trap；源码/归档一致性审查、shell 语法通过，没有在已挂存储时故意注入中断。
- Android 传播隔离用原机 BusyBox 1.31.0 的 `busybox mount --make-rprivate /`。
  默认 Toybox mount 不支持该调用；修正后 Android 回读实测通过。创建脚本已同步修正，没有重格式化现有镜像。
- 清理工具的最后一次正则匹配被串口回显交错打断；真实输出为 ROOTFS_CLEANUP_OK。
  后续独立短命令确认 loop 未绑定、losetup -a 为空、无 ext4 挂载，再执行普通内核 reboot。

[summarize-results.py](summarize-results.py) 已核对保存的 CRC、启动、标记、固件、清理、重启及五个启动分区 SHA，
输出 BOARD_EVIDENCE_VERIFIED。二进制、完整 inventory 和原始串口流已被 .gitignore 排除，只在本地保留。
未保存配网口令，没有修改已有应用源码，没有提交或推送。
