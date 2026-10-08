# 原生 PID1 实机往返结果

2026-10-05，AIoT-3568PQ / RK3568，COM8 / 1500000，屏幕排线拔下，无外接耳机、喇叭、电机。本板无 SD 卡座。TUN 设置保持；电脑通过绑定 WLAN 源地址的临时用户态转发连接板端 ADB，没有修改路由或适配器。

## production-v3 完整通过

构建时封存的 manifest 保持未板测，现场结果单独绑定同一产物：production manifest SHA256 `53f8807d3e2ab63fbe7d4b35cab33a391b28e00bf317179fedeac1a6f7306484`；board session-v4 manifest SHA256 `6b71dc13c70b869864d316245adcc436ec85ff8c7c63cadfba883a98dca253dd`。

| 产物 | SHA256 | 字节 |
|---|---|---:|
| PID1 | 249cc1cfd87cbddc8618e81e6b8fd742526de78fd964d4a4b3b59b8a7d76368b | 767112 |
| 只读根文件系统 | 3a87bd54f44b1e5d20701514c26669d086123e8b2ee8ed9087cc118c12fc679d | 16777216 |
| initrd | 54db3bb6fa94dd1570a306aa90e3caa6ae5ed7bb6b93d96afcae0c5f8881afef | 972203 |

仍使用旧 RCU Image `e7a95d9f…8fa457` 和 UART/RNG DT `7be4f96f…9491d1`；三个 U-Boot 实际载入大小及 RAM CRC 全部一致。原生 PID1 在 loop0 上以 root 身份运行，`/proc/1/maps` 为 07:00/inode45，exe SHA 与生产一致。根和 cache 都是只读 ext4/norecovery，PID1 仅 console 0/1/2。

协议编码和 POSIX PTY 纯软件自检分别 exit0，自有子进程正常回收；root shell exit0 回到监督器。原生 return 完成全部 backward=63、pivot=1、old_unmounted=1、loop_detached=1、cache_unmounted=1。独立 guard 使用生产版本的 52 个 applet 链接直接通过，确认仅七个 RAM 虚拟挂载、无持久 mount/loop/module/未知用户进程或额外 FD。没有手工创建链接或替换 guard。

guard 在重启前再次通过，然后 normal-reboot helper 发普通 reboot syscall，`165.596432` 秒记录 `Restarting system`，随后 DDR 和原 Android 启动。只对请求标记至首条 DDR 的窗口检查，未捕获 WARNING/BUG/Call trace/Kernel panic；不把启动 BSP 的所有诊断都称无错。

返回后新鲜 Android11 / 4.19.232 / root / boot_completed1，电量前后均67%。五个启动分区 boot/uboot/trust/dtbo/vbmeta 和两份旧 rootfs 的完整 SHA256 前后相同。独立现场证据汇总 [48/48结果](build/board-native-v3-result-v1/result.json) 记录每个原始证据 SHA；由 [只读汇总程序](audit-board-native-v3.py) 生成。上板前离线真实调用测试 host/QEMU 各855/855，session 检查83/83，详情见 [独立审查](REVIEW.md)。

Android 串口 probe 的末尾标记被内核 audit 日志穿插，执行器严格匹配失败，原始流保留在 `private/pid1-android-probe-native-v3.raw.txt`。它没有触发设备修改；随后 ADB 新鲜完整采集确认原系统和七 SHA，未放宽失败标记。

## production-v2 是人工协助收尾

v2 曾真正 ROOT_READY，软件自检和原生卸载/loop/cache 退出完成；但返回岛仅两个 ELF，缺52 applet symlink，独立检查报 sha256sum not found。主控手工在 RAM 里补52链接后，旧 guard 又拒绝真实 job-control 父 BusyBox 的 FD10 `/dev/tty`（字符5:0）。保留原失败流，独立 fixture 验证并收紧只允许匹配父 PID/PPid1/session/pgrp/精确BB SHA/FD10类型的规则，随后仅在 RAM 更新 guard。

修正后的独立 guard 通过，普通 reboot 在 `640.596799` 秒返回 Android，七 SHA 相同。v2因此不能记成未经干预的完整往返通过；production-v3 原生建52链接并使用已审查新 guard，才完成上面的完整测试。v2原始失败、手工动作与返回记录均保存在 private 的 v2/manual 文件，不覆盖。

## 仍未完成的范围

这一轮证明只读文件根上的真正 PID1、纯软件自检、原生卸载、纯RAM退出和普通重启。没有生产服务自动启动、网络/音频/显示在此PID1下的集成、PCM START、poweroff、MCU断电契约、长期重复测试、正式boot包部署或USB裸机恢复。七SHA对比不是全eMMC差分。用户报告OTG接口“dmo直接接地”，引脚和测量条件仍未知，恢复入口未确认。未写启动分区、saveenv、提交或推送。
