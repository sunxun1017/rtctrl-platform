# RK3568 首次启动准备与留痕（2026-09-28）

本轮在原 Android 保持运行的情况下读取启动资料，并在电脑构建 Linux。
用户确认目前仅连接串口，没有 USB OTG 数据线。没有重启、刷写原分区、进入 Loader/MaskROM 或启动新 Linux。

## 新 Linux 产物

- `Image`：5.10.160 ARM64，34,888,192 字节；头部声明内存跨度 35,520,512 字节（含 BSS，不等于文件长度）。
- `rk3568-aiot-3568pq-firstboot.dtb`：沿用上一轮经原 FDT 对照的最小板级树。
- `initramfs.cpio.gz`：静态 ARM64 BusyBox 1.36.1；仅自动挂载 devtmpfs/proc/sysfs/tmpfs，输出诊断后提供串口 root shell。
  不自动挂载 eMMC 文件系统、启动网络、采音、采帧、休眠或重启。交互 root shell 本身不是防误写沙箱。
- `artifacts.json`、`SHA256SUMS`：文件摘要与实际验证结果；`deployable=false`、`board_boot_tested=false`。
- `kernel.config`、`busybox.config`：本轮实际配置，不覆盖上一轮的历史验证清单。

完整 Image 编译成功；`vmlinux` 经 file 检查为 ELF64 AArch64。BusyBox shell 通过用户态 QEMU 执行，
cpio 列表已检查，两次归档逐字节一致；manifest 单独存在时拒绝覆盖。这些检查不能替代真实 ARM64 内核启动。

## 内核构建中实际解决的问题

源版本仍为 `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`，但 Image 使用了明确保存的补丁，不能称为未修改原树构建。

1. `kernel-image-build.log`：非 RT + HOTPLUG_CPU 调用不存在的 `migrate_tasks()`。
   PM_SLEEP_SMP 强制选择 HOTPLUG_CPU；先前 dwcmshc 又需要 PM_SLEEP。
   firstboot.cfg 改为 PREEMPT_RT，保留 SUSPEND。此选择不证明任何实时延迟指标。
2. `kernel-image-rt-build.log`：RT spinlock 经 cache.h 无条件包含 kasan-enabled.h，造成 WARN 定义前引用。
   KASAN 已关闭，不能继续靠关配置解决。
3. `0001-arm64-cache-kasan-include.patch`：将 kasan-enabled.h 移到唯一需要它的 KASAN_HW_TAGS 分支。
   最终 `kernel-image-rt-patched-build.log` 完整成功。构建结束反向移除了本次补丁，third_party 源树恢复干净；
   可维护补丁也存放于 `platforms/rk3568/boards/aiot-3568pq/patches/`。

复现应先在干净锁定源上完成配置/DTB步骤，再应用该补丁构建 Image，结束后反向移除。
现有 build-firstboot.py 仍要求干净原树；不要在打补丁后调用它或绕过其检查。

## 原机证据与范围

- `01-current-state.*`：重新核验 Android 4.19.232、root、orange、flash.locked=0、分区映射。
  这些属性不证明 bootloader 接受任意镜像。
- `02-transfer-options.*`：仅 loopback IPv4，板端有 nc/busybox；没有改变网络设置。
- `03/04-*`：boot 前 4096 字节及独立 SHA-256 校验。
- `06/07-*`：其余四分区前 512 字节及独立 SHA-256 校验。
  `05-*` 是错误转义的失败尝试，保留原始输出。
- `boot-header.json`：Android header v2，page_size=2048，kernel=33046536、ramdisk=822304、second=4491776、dtb=1650869 字节。
  头部地址仅是镜像声明值，未经当前 loader 的实际加载/fixup 验证，不可直接作为新镜像启动地址。
- `component-headers.json`：uboot 前缀 FDT magic，dtbo 为 DT table，vbmeta 为 AVB0；trust 头部零值不能证明整个分区为空。
- `08-backup-components.*`：只读原分区，写入板端普通临时文件 `/data/local/tmp/rtctrl-boot-20260928/`。
  boot 40 MiB、uboot/trust/dtbo 各 4 MiB、vbmeta 1 MiB，未读取 userdata/oempriv。
- 串口配置 COM6、1500000、8N1、无流控、DTR/RTS=false；每条板端命令有 `.command.sh`、`.output.txt`、`.raw.bin` 和 session.log。

大块回传最初被异步 rk817-bat 日志打断，失败尝试 `17/18-*` 保留。
`transfer-components-filtered.ps1` 只剥离带内核时间戳的日志后解码，并要求每块字节数和 SHA-256 同时一致；
最后还要求整包摘要一致，解码过滤本身不能证明数据正确。

**本轮大文件回传未完成。** 板端压缩包为 18,384,591 字节，SHA-256
`8e653d52d144a5a4cf8e18ca2a19211c76a3113509f958e53b259bedb4288380`，目前仅在板端临时目录完整保存，
不是脱离原机的可靠恢复备份。主机保留的是已校验头部、少量分块及全部失败原始串口流。
`artifacts.json` 只描述新 Linux 构建产物，不描述原分区备份完成。

进一步处理及结果：

- 发现旧解码正则漏掉形如 `qQ==` 的短尾行，已在 filtered/final 脚本改为允许短行；仍保留逐块 SHA 校验。
- `09-*` 读取原 printk 值为 `7 4 1 7`；`10/12-*` 暂设 console_loglevel=1，减少串口日志。
  两次传输都以 finally 恢复，`11/13-*` 输出确认恢复 `7 4 1 7`。这属于临时诊断设置修改，不能称全过程零写入。
- `20/21-*` 安静串口仍出现传输字节缺失；最终在第 1 块耗尽重试，未生成完整主机压缩包。
  没有用绕过校验的方法接受损坏数据。不同试验的 chunk-NNN.bin 为中间缓存，可能重复使用名称；
  追溯以各试验独立的原始 `.raw.bin`/`.output.txt` 和对应 tsv 为准。
- `transfer-components-final.ps1` 为最后一次实际尝试，不是已证明可靠的大文件传输方案。
  待 USB OTG/ADB 连接后应换用可靠传输，并验证板端整包摘要和包内各镜像摘要。

## 命令、依赖与验证入口

- `commands.sh`：主机构建与核验命令；每次失败和最终编译分别保存日志。
- `analyze-evidence.py`：解析头部并检查独立采集的板端摘要。
- `verify-artifacts.py` / `verification-output.txt`：Image头、配置、ARM64 shell、归档重现、防覆盖验证。
- `initramfs-list.txt`：cpio 内容和权限；`busybox-applets.h`：实际15个 applet。
- BusyBox 官方来源：https://busybox.net/downloads/busybox-1.36.1.tar.bz2 ，同站 `.sha256` 校验通过。
  下载源码和校验文件保留 `.deps/busybox-firstboot/`；许可证见 `busybox-LICENSE`。
  BusyBox 不支持 olddefconfig 的失败也保存在 busybox-config.log，随后使用 oldconfig 成功。
  allnoconfig 未开启 `--list` 功能，所以首次 --list 检查失败，随后以生成 applet 表及实际 ash 执行核验。
- verify-artifacts 首版误将内存 image_size 限制到文件长度，触发断言；已修正为检查包含 BSS 的内存跨度，并重新通过。

## 上板前仍需要的证据

完整启动分区备份也不包括 GPT/前置 loader/eMMC boot0、boot1/RPMB/熔丝；不能称为整板恢复包。
还需完整镜像拆包、AVB/DTB/resource 关系核实，以及正确 OTG 接口、恢复按键/短接位置和匹配 DDR 的 loader。
只有确认进入恢复和临时启动的实际方法、加载区域不重叠后，才安排首次启动。

参考格式定义：[AOSP boot header](https://source.android.com/docs/core/architecture/bootloader/boot-image-header)、
[DTBO](https://source.android.com/docs/core/architecture/dto/partitions)、
[AVB](https://android.googlesource.com/platform/external/avb/+/refs/heads/main/README.md)、
[Rockchip rkdeveloptool](https://github.com/rockchip-linux/rkdeveloptool)。
其中 `rkdeveloptool db` 是下载 usbplug，不是通用 Linux RAM 启动命令。
# 关机与 Git 留存（本轮后续）

用户明确要求关机，重新核验原 Android 与 root 后，执行 `su 0 setprop sys.powerctl shutdown`。
串口确认进入 Android shutdown，最终输出 `reboot: Power down`，没有重启进入新系统。
完整原始字节和输出保留本地 `23-orderly-shutdown.*`；提交的摘录见 `shutdown-evidence.txt`。
观察到原厂 `mcuinterface_shutdown` 调用关闭 MCU 看门狗并发送 MCU power-off 标志；
这是原厂正常关机路径产生的动作，不是另行猜测发送 MCU 命令。新 Linux 的物理断电路径仍需单独适配。
日志还有 xHCI halt 超时和 invalid GPIO 提示，不能称全程无警告；未独立测量板上电源轨。

Git 保存报告、脚本、文本构建日志、配置与核验清单。Image、DTB、cpio、分区副本、原始串口流和传输块仅保留本地，未删除。
文内指向这些原始证据的链接依赖本地目录；新克隆需要重新构建或取得原采集包，不是完整恢复备份。
