# Linux PID1 离线交付 v1（仍未板测）

主控独立审查更新：v1 暂缓部署和 RAM 启动。已确认岛内 exec 失败后的 resume 未重试
exec，以及未知挂载检查未拒绝同名 `/dev/pts` overmount、pivot 后新增 mount。
原作者正在补实际 main 红绿测试和新生产版本；下列 v1 清单、603/603 和镜像报告保留为
历史离线结果，不作为当前上板放行依据。板子仍在原 Android。

生产包在 `build/production-v1/`。本目录的新工具没有部署、连接板卡、刷启动分区、修改 U-Boot 环境变量或更新旧 rootfs。源码为 MIT；BusyBox 是精确的模块参数修正版 GPL ELF，实际 52 applets 已由 QEMU 核对，出处与对应源码/config SHA 见生产 manifest。

| 文件 | 字节 | SHA256 | CRC32 |
|---|---:|---|---|
| pid1 | 758576 | f24b86829560b963782b676d9f9a7c41cedab447587c2b6522489cedfb6f124c | 59afee7b |
| rootfs-pid1.ext4 | 16777216 | 604f49edd55b8e0a35835eedb86e41f6edc2a133ef86ee57af0c69da6400d921 | 99c7ace1 |
| initramfs-pid1.cpio.gz | 969242 | 6c91172e125a15b05438d4a183b693f66e4af4f3409e0d64de7295dd9249e280 | e7aa81b6 |

生产 manifest SHA256 为 `9f4035c5722956bcbead03f18e05308fc110ae0b66031705b8096863d8153bed`；源码 `pid1.c` SHA256 为 `3afe441c6fcfd0ada8c17d2e34943747d51857d49c2c06a14625656044d5c928`。完整编译参数、gcc 11.4.0 版本、实际使用的锁定 loop UAPI 副本和 SHA、各 ELF 输入、rootfs path 白名单及测试报告 SHA 均在 manifest 内。生产 ELF 无 wrapper/测试代码。

本轮固定复用旧 Image `/cache/rtctrl-rcu-reset-20261004/Image`，SHA `e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457`。新 rootfs 的固定板端文件路径是 `/cache/rtctrl-pid1-20261005/rootfs-pid1.ext4`；必须由主控以 root 创建，普通文件 nlink=1、uid/gid=0。initrd 的文件部署与 U-Boot 加载由主控另行准备。本包没有自动部署脚本，也不复制旧 34 MiB Image。增加的两个镜像约 16.93 MiB。

内核本轮必须由主控在 U-Boot 核本次 Image/DTB/initrd 的实际大小、RAM 地址跨度和 CRC。helper 的 Image SHA 只证明固定 cache 文件的内容；uname 不证明正在运行的内核完整字节。本轮继续使用此前已测 UART/RNG DT，不依赖新显示 Image。

## 实际执行契约

`/init` 是静态原生 PID1 ELF，只有真实 getpid=1、uid=0 可工作。bootstrap 挂 devtmpfs/proc/sysfs/devpts/tmpfs，核 cache PARTNAME=cache、786432 sectors、block major179 及 sysfs/fstat dev 完全一致，cache ext4 只读 noload；核完整 rootfs SHA、clean/no needs_recovery，再绑定仅本轮 loop（READ_ONLY、无 AUTOCLEAR），把根 ext4 只读 noload 挂上。

它建立独立 tmpfs 返回岛并复制同 SHA PID1/BusyBox，然后自己 MS_MOVE/chroot/exec，root 模式核 `/proc/1/exe` SHA 和 st_dev 必须来自本轮 loop。只有此路径输出 `LINUX_PID1_ROOT_READY`。子 chroot 无法取得此标记。

控制台提供 `status`、`shell`、`codec`、`pty`、`stop`、`return`、`resume`。第一轮不自动运行软件测试，不启动 Wi-Fi、音频、MCU 或其他服务。`codec`/`pty` 仅执行旧的纯软件 AArch64 测试；只有正常 exit=0 且回收无错才输出 `SOFTWARE_TEST_PASSED`。shell 是经过两管道握手和 PID/starttime/parent/group/session 验证的独立会话；退出 shell 后回到原生监督器。未知后台用户进程或额外 mount/FD 会阻止返回，不做全局 kill。

输入 `return` 时，先核无其他用户进程、仅 console 0/1/2、根/loop/cache 身份，再 exec 返回岛同 SHA ELF。return 模式核 exe st_dev 为独立 tmpfs，逐步移走 cache 与所有虚拟挂载，pivot_root 到岛。必须依次正常 umount old-root、CLR_FD 自有 loop 并 GET_STATUS64=ENXIO、正常 umount cache，才输出 `LINUX_PID1_RAM_READY_NO_RESET`。

任何错误进入永久救援控制台，保留首错步骤/errno和当前挂载路径。部分返回迁移、pivot 尾部、umount 或 loop 关闭失败可以人工 `resume`，只继续未完成步骤；root 切换尾部/exec 失败的 `resume` 会重复身份核验再执行同 SHA 新根 ELF。`stop` 只对仍匹配已记录 PID/starttime/session 的自有会话进程组操作。没有 force/lazy umount，也没有 reset/reboot/SysRq/flash/saveenv 命令。

## 已运行的离线验证

- `build/red-v1/results.json`：缺失 PID1 实现的基线 0/5；`build/red-lifecycle-v1/results.json`：缺失完整生命周期基线 0/30。后续会话握手、软件测试退出码、FD_CLOEXEC、身份与 resume 的真实失败证据均按版本保留。
- `build/final-host-v1/results.json`：603/603；`build/final-aarch64-v1/results.json`：静态 AArch64/QEMU 603/603。实际 main 通过外部链接 wrap 做 syscall 故障注入，检查所有观察到的关键操作单点失败、错误身份、未知进程/FD/mount、部分迁移/返回清理及人工 resume。
- `build/production-v1/inode-audit.json`：全部 86 个 allocated inode（包括 reserved/journal）uid/gid=0；`e2fsck.log`：只读全检查通过。所有 ext4 ELF 导出再核 SHA，clean/no needs_recovery，16 MiB 大小；newc 69 成员全部 root。
- `build/artifact-red-v1/results.json`：缺失审计基线仅干净包通过，1/12；`build/artifact-green-v4/results.json`：12/12，真实篡改 reserved UID、普通 inode GID、dirty/recovery、ELF 架构、symlink 镜像、CPIO owner/白名单/console/BusyBox 均拒绝。
- `build/audit-production-v1/audit.json`：独立只读复核全部 86 inode 的原始 bitmap 与 debugfs stat、77 rootfs 路径及全部 payload/link；实际导出的 codec/pty 在 QEMU exit=0，BusyBox applet 列表一致。
- `build/repository-suite-v1/ctest.log`：项目全部现有 41/41 CTest 通过。为遵守只写新目录约束，复制只读 CTest 元数据到该新目录运行，测试仍引用现有绝对路径 executable，所有 CTest 运行日志留在新目录。

## 尚未覆盖

QEMU user 和 wrapper 不执行真实 mount/pivot_root/loop/console TIOCSCTTY，不证明板端内核允许这些操作。实际 PID1 信号、真实孤儿回收时序、console 会话、内核 exec 映射释放、正常卸载/loop detach、MMC/驱动阻塞、旧根隐藏 mount 行为及完整返回岛路径均需上板核查。RAM_READY 只表示 helper 的正常清理检查完成，后续复位仍由主控独立核资源和状态。没有正式 eMMC boot 包或写启动分区。

详细状态机和故障边界见 `PLAN.md`。新版本构建/测试/审计一律必须指定新的输出目录；已存在目录立即拒绝覆盖。
