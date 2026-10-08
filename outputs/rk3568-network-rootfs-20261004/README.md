# RK3568 源码网络工具与持久化 rootfs（2026-10-04）

本阶段把此前分别验证的源码工具合并到一个新 64 MiB ext4 普通文件。
PID1 仍为已验证 initramfs 内的 `/bin/sh /init`，新文件只用于短时 chroot，尚未 switch_root 或自动启动。
板端路径是独立 `/cache/rtctrl-network-rootfs-20261004/rootfs.img`；旧镜像保留，启动分区未作为写入目标。

实际 Android 4.19 →源码 Linux 5.10 →Android 4.19 的完整标记往返已通过，
两份测试后镜像已回传并核对压缩包与解压完整 image 的 SHA。
五个启动分区完整 SHA 前后一致。实机结果见 [result.json](result.json)、
[Linux rootfs 检查](linux-rootfs-check.txt)、[收尾运行读回](linux-runtime-check.txt)。
host manifest 保留构建时 `board_tested=false`，当前板测结果单独记录在 result.json。

## 产物与构建

输入由 [rootfs-manifest.json](rootfs-manifest.json) 逐项固定，镜像初始 SHA：
`fb998ec342e19d28df0dc7ba1f24171c4f9cb651b4a1150045ed5d3c3c6ba757`。

包含源码 BusyBox、codec/PTY 诊断、wpa_supplicant/wpa_cli 2.11、独立网络 helper，
以及与 Image 严格匹配的 BCMDHD 5.10 模块。模块链接不意味着 Android 上可以加载该模块。
所有常规文件、目录、链接及 ext4 保留 inode 都核对 uid/gid 0。
无原厂 Android Jar/Binder/JNI `.so`、SSID/密码或 MCU 操作程序。
`/tmp` 必须绑定到 RAM；运行目录、日志及 DNS 文件经内部链接落到 RAM `/tmp`。

```sh
python3 outputs/rk3568-network-rootfs-20261004/build-rootfs.py \
    --output-dir outputs/rk3568-network-rootfs-20261004/build/new-revision
python3 outputs/rk3568-network-rootfs-20261004/verify-rootfs.py
python3 outputs/rk3568-network-rootfs-20261004/test-rootfs.py
python3 outputs/rk3568-network-rootfs-20261004/test-runtime-cleanup.py
```

构建拒绝覆盖已有入口。重建须选择未使用的目录并按脚本接口核验相应产物；
上述 verify/test 的默认目标为当前主入口，不能把它的结果移用于另一份新镜像。
首次两次审计解析失败产物仍保留在忽略目录，最终成功产物来自 `build/v3`。
固定输入支持追踪和重建功能，尚无跨环境逐字节可复现结论。

宿主只读 e2fsck、104 路径及完整 payload 审计、实际镜像提取的 AArch64 静态 ELF/QEMU 检查通过，
实际占用 22,982,656 字节。21 项边界测试包含覆盖/链接/动态 ELF/模块版本/实际 ext4 篡改/持久凭据拒绝。
7 个实际 shell 清理测试执行原函数片段，验证部分卸载失败后按剩余 flag 重试和 loop 所有权拒绝；
设备命令由 mock 拦截，不能当作板端真实失败注入。

## 实机验证顺序

1. Android 重新确认 root、内核、固件、原五个启动分区与网络状态；原 15 项启动备份重新校验。
2. 相同源码 helper 在 Android 进行 64 KiB TCP 双向传输，发送、板端及回传 SHA 一致。
3. 上传新普通文件并逐项 SHA 核对。Android 私有 mount namespace 中按 RO loop + `ro,noload` 检查，
   绑定 RAM `/tmp`，运行 codec/PTY 与 WPA/CLI 版本检查；临时写入前后完整 image SHA 不变。
4. 独立 RW 挂载只写一个 Android 标记，再独立 RO 回读；卸载每个子挂载、根挂载及所拥有的 loop。
5. 测试后的 image 在 Android 压缩后回传，同时校验压缩包及解压完整 image 的 SHA，保留为新快照。
6. U-Boot 新鲜检查 eMMC/cache/内存布局，沿用原已板测 Image/DTB/v5 initramfs，逐项加载 CRC。
   只修改 RAM 环境/FDT，启动源码 Linux。外置检查脚本也单独验 SHA，image SHA 不覆盖这些脚本。
7. Linux 先 RO/noload cache + rootfs，回读 Android 标记并运行同套源码测试；完整 SHA 不变。
   卸载后独立 RW cache/rootfs 只写一个 Linux 标记，再 RO 回读，逐项释放挂载/loop/devpts。
8. 独立 RAM/loop guard 后 SysRq 即时复位返回 Android，核对五个启动分区、Linux 标记并回传新快照。

检查脚本为 [rootfs-check.sh](rootfs-check.sh)、[linux-rootfs-check.sh](linux-rootfs-check.sh)，
实际发送的命令保存在 JSON 文件；[runtime-scripts.json](runtime-scripts.json) 固定本轮外置脚本 SHA。
检查拒绝覆盖既有 marker，失败产物保留用于调查；清理失败时留在当前系统，不强行复位。

## 网络与开源边界

本轮 Android TCP 对照通过只说明当时链路可通信。此前源码 Linux 的对端 ARP/TCP 未通过，
本轮 rootfs 检查没有开启 Wi-Fi，不得据 rootfs 中存在 WPA/模块或版本检查通过，声称 Linux 联网恢复。
新鲜 Android 关联 5 GHz、此前 Linux 曾漫游至另一 AP，是现场差异，尚非根因。
源码调查确认驱动有 `PM=0` 支持，但本轮没有修改该参数或过滤/漫游机制。

两份原机 firmware/NVRAM 是私有实测依赖，SHA 与此前备份一致；其再发布许可仍未验证。
镜像、固件、原始网络日志、运行地址及串口控制脚本位于忽略目录，不随源码公开。
原 DDR/loader/trust、芯片固件及 MCU 固件的二进制缺口继续单列，不能把本阶段称为整机完全开源。
未验证正常 reboot/poweroff、MCU/watchdog、运动、屏幕音频、蓝牙、休眠、长期网络或实时性能。

备份覆盖原 15 项启动输入及本轮 rootfs 快照，不是完整 eMMC，也没有裸机恢复验收；
recovery/super/userdata/oempriv 的整分区内容仍未完整备份。
本轮没有 saveenv、刷写启动分区、发送运动命令、提交或推送。

## 新发现：认证前的随机数就绪条件

Linux uptime 约 53 秒执行 WPA/CLI `-v` 时，两者出现
`uninitialized urandom read (4096 bytes read)`。本轮没有进行认证，不能推断已经用弱随机认证。
实际完整内核配置已启用 HW_RANDOM/HW_RANDOM_ROCKCHIP，构建列表也包含 `rockchip-rng.o`；
本次沿用的 Wi-Fi DTB 中 `/rng@fe388000/status` 为 disabled。
锁定驱动匹配 `rockchip,cryptov2-rng`，成功绑定后可通过 hwrng 内核线程供熵，尚未实机确认该路径。

后续使用独立新 DTB 验证 TRNG，旧实测产物保留；驱动、接口及节点依据为：
`third_party/linux-rk3588/drivers/char/hw_random/rockchip-rng.c`、
`drivers/char/hw_random/core.c`、`drivers/char/random.c` 和 `arch/arm64/boot/dts/rockchip/rk3568.dtsi`。
本锁定 random.c 中 getrandom 无 NONBLOCK 时等待 CRNG，NONBLOCK 在未就绪时返回 EAGAIN；
不能推广为任意内核版本的行为。

下一次在源码 Linux 读取 rng_available/rng_current、entropy_avail 与初始化日志，
并通过 getrandom 或一次不输出内容的 `/dev/random` 读取直接确认就绪后再认证。
`dd if=/dev/random of=/dev/null bs=1 count=1` 在本内核会等到就绪，
因此需要有界等待或人工中止，不能用固定睡眠几秒作为替代证据。
这是认证前必须补充的条件，尚未定位此前 Linux ARP/TCP 失败根因。

独立 `wifi-rng` 候选已离线构建，SHA 为
`ab0893cea485cb9972d93dfb3eaa61ec955cbf4314a3f0f39c43b418249e8035`，162,418 字节。
104 项审计（原 Wi-Fi 90 项加 RNG 14 项）与 11 项实际 DTB 故障拒绝通过，
新增 DTC 警告为零；相对固定 SHA 的旧 Wi-Fi DTB，解析属性只改 rng/status，保留区完全相同。
Image、模块、旧 DTS/DTB 及本轮实测清单保留原字节。
候选尚未上板，没有 RNG 驱动绑定、熵初始化或无线修复结论。
[rng-candidate.json](rng-candidate.json) 保留离线构建清单，实际二进制仍在忽略的 build 目录。

```sh
python3 outputs/rk3568-network-rootfs-20261004/build-rng.py \
    --output outputs/rk3568-network-rootfs-20261004/build/rng-new-revision
```

构建器拒绝已有/越界/符号链接输出，固定旧 DTB、Image、配置和干净源码 commit。
原 `build-firstboot.py` 入口未改动，新候选不自动替代任何已板测文件。
本轮实测电量到 3% 后已提醒换电池，清理完成、串口释放，两份快照已备份；
此后只做电脑上的候选构建与记录，电量提醒已暂停以避免重复。下一轮先重新核实新电池与连接。
