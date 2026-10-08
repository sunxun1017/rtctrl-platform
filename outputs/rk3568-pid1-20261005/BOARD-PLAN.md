# 真正 PID1 首轮板测方案

2026-10-05 主控准备，尚未执行。本板屏幕排线已拔下，无外接电机、耳机和喇叭，无 SD 卡座。
当前保持 Android/TUN 配置。只接管 COM8 串口；原启动分区与两个旧 rootfs 保留。

原生 v1 的603/603只是离线模型结果。独立审查的 exec 失败恢复和未知挂载漏洞正在修正，
当前不部署 v1；其 `board-manifest-v1.json` 和会话为历史准备记录，不作放行依据。
新生产候选需独立复核通过，主控再以明确 manifest SHA 生成新的 board-vN。

## 暂存与启动

1. 新鲜核 Android11/4.19.232/root/boot_completed1、电池，以及 boot/uboot/trust/dtbo/vbmeta
   和旧 source/network rootfs 的7个完整SHA；记录仅代表本次，不是全eMMC差分。
2. 经ADB上传到新的 `/data/local/tmp/rtctrl-pid1-20261005`。校验清单和准备脚本由电脑核SHA，
   板端再次核完整清单后运行prepare，创建仅本轮 `/cache/rtctrl-pid1-20261005` 普通目录。
   rootfs固定16MiB，initrd约1MiB、UART DT约162KiB；缓存可用至少21MiB。
   复用已有 `/cache/rtctrl-rcu-reset-20261004/Image`，不再复制34MiB内核。
3. 经Android正常重启、串口中断进U-Boot；重新读版本、内存图、分区和环境。
   使用cache=mmc0:c，Image/DT/initrd的实际长度与CRC均应和本次清单一致。
4. RAM地址为Image0x00400000、DT0x03000000、initrd0x04000000。Image extent到0x025c0000，
   DT resize后仍早于initrd，initrd限制8MiB以内。RAM原有效范围、保留区和U-Boot重定位范围另核。
   仅本次FDT删除匹配的旧AndroidFDT/initrd reserve，并设置volatile环境；无saveenv。
   启动参数panic=0，不自动重试故障启动。

## 主系统进程与退出

1. 只有原生PID1切入本轮只读ext4根并核自身exe设备及SHA，才接受 `LINUX_PID1_ROOT_READY`。
   异常留救援控制台，先看首错和实际mount/FD/进程，不直接复位有持久挂载的系统。
2. 单独执行codec/PTY纯软件测试。各自必须正常exit0且已回收，由原生程序输出明确通过标记。
   不打开物理UART、SPI、PCM、DRM、framebuffer；不采音、不发电机帧、不开Wi-Fi。
3. 进入自有shell只读采 `/proc/1/mountinfo/maps/exe/root/fd` 和loop，核本次PID1 ELF。
   在RAM `/tmp` 建立校验绑定的独立return guard；从只读cache复制既有正常重启helper到RAM、核SHA。
4. 退出shell并确认owned session被回收，再输入return。原生PID1必须先exec内存岛ELF，
   移动虚拟挂载、pivot、正常umount旧根、detach自有loop并确认ENXIO、正常umount cache，
   每阶段复核精确mount身份/集合，才接受RAM_READY和phase4状态。
5. 再进入自有RAM shell，核新PID1 SHA/argv、7个虚拟挂载目标/类型各唯一、无模块/loop，
   仅已识别父系用户进程、PID1只有console0/1/2，未知FD阻断。不能用旧BusyBox PID1 guard替代。
6. 独立guard再次通过，才调用RAM正常重启helper。helper自身再核root、固定内核release、
   exe路径/内存fs和SHA绑定。返回Android后重查7SHA、root/系统和电量，保存结果。

## 当前 guard 故障证据

`build/board-review-v1/results.json`：独立实际BB52 shell检查49/52，3例false-ready为
PID1额外socket、额外普通文件FD、同target重复devpts。原证据保留。
修正后增加未知RAM mount、各target重复/缺失/错误fs、父系、读取失败、stdio和额外FD测试。
`board-review-v3` 为67/68：所有行为和新故障例通过，唯一失败是修正后的guard不再匹配旧v1清单。
这项绑定失败是预期的阻断，必须生成并复核新清单后才能放行，不把67/68写成完整通过。

真实mount/pivot_root、console/TIOCSCTTY、孤儿回收时序、内核exec映射和完整返回仍待板测。
本方案不等于正式开机自启、恢复包、掉电、MCU/watchdog或整机功能验收。
