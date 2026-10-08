# RK3568 独立 Linux PID1，离线 v1

本目录独占新产物；旧 rootfs、启动分区、环境变量与硬件保持原样。实现为 MIT 静态 AArch64 ELF 的 `bootstrap`、`root`、`return` 三种模式。`/init` 是此 ELF，getpid 必须为 1；子 chroot 不算成功。构建、测试、审计目录一律拒绝覆盖。

## 固定输入与身份

- Image SHA256 `e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457`；内核 release `5.10.160-rt89-g9f9e9d18574d-dirty`。运行时核查 cache 中固定 `rtctrl-rcu-reset-20261004/Image` 的完整 SHA（旧 prepare-boot.sh 与 load-ram.json 的确切路径）；这证明文件，实际加载 Image 仍需主控在 U-Boot 校验本次地址/大小/CRC。uname 不能证明正在执行的 Image 完整 SHA。复用已存在的此文件，不另占 34 MiB。
- BusyBox 固定模块参数修正版 SHA `514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1`，52 applets，无 stock init/switch_root。生成镜像复用此 ELF，不重新编译或修改依赖。
- `/dev/mmcblk0p12` 只允许 block major 179，fstat dev 必须与 `/sys/class/block/mmcblk0p12/dev` 一致；uevent 必须 PARTNAME=cache，size 必须 786432 个 512-byte 扇区（384 MiB）。不从 Android 的 mmcblk2 名称推断 Linux 身份。
- cache mount `MS_RDONLY|MS_NOSUID|MS_NODEV|MS_NOEXEC`，ext4 数据 `noload`；rootfs 固定普通 root-owned 文件 `/cache/rtctrl-pid1-20261005/rootfs-pid1.ext4` 限制 16 MiB，SHA 从 initramfs 固定 manifest 获取。文件不带 symlink，nlink=1。文件系统 needs_recovery、未清洁状态直接拒绝。
- 独占 loop-control 分配的本轮 loopN，block major 7/minor N；必须初始 LOOP_GET_STATUS64 返回 ENXIO，再 SET_FD、SET_STATUS64 READ_ONLY，无 AUTOCLEAR。GET_STATUS64 必须核 dev/inode/offset/sizelimit/flags。完整 backing fd 在核查后关闭。
- PID1/BusyBox/codec/pty ELF SHA 均由 builder 固定 manifest；生产 ELF 不嵌入自身 SHA。引导可信 manifest 放 initramfs；runtime 状态复制至独立 tmpfs 岛，并不接受用户指定设备或哈希。

## 转入 ext4 真 PID1

bootstrap 明确建立 private mount namespace 属性；mount devtmpfs、proc、sysfs、tmpfs /tmp、tmpfs /run、devpts，console stdio 恰为 char 5:1。在 cache RO,noload、rootfs 完整校验、readonly loop、root ext4 RO,noload 验证之后：

1. 在 `/newroot/.ram-return` 独立挂 tmpfs，复制同 SHA PID1 和 BusyBox，建立独立目录及状态；不可依赖旧 initramfs 或 ext4 的 executable 映射返回。
2. 将 cache 移入 `/newroot/.backing-cache`，再按记录的步骤把 dev（含 devpts）、proc、sys、tmp、run 移入新根。
3. PID1 自己 chdir(newroot)、MS_MOVE(newroot,/)、chroot(.)、chdir(/)，exec 同 SHA `/bin/pid1 root`。保留隐藏初始 RAM root 内容；不用 BusyBox 删除旧 root 的实现。
4. 新 PID1 验证 `/proc/1/exe` 内容、root st_dev、mountinfo `/` 的 ext4/source/ro 身份、return 岛和 runtime 状态，然后输出 `LINUX_PID1_ROOT_READY`。

## 会话、FD 和信号

监督器在 console 上提供 status、shell、codec、pty、stop、return、resume 命令；无网络、音频、MCU、模块自动启动。shell/软件测试是监督器直接 fork 的单独 setsid/TIOCSCTTY 会话；两个 CLOEXEC 管道传递 ready/permit，父进程核实 PID/starttime/parent/group/session 后才许可子进程 exec。父验证失败时关闭 permit，子进程退出而不先启动 shell 争抢控制台。waitpid 回收自身会话及已收养子进程；SIGCHLD 仅置标记，正常上下文回收。所有文件 FD CLOEXEC；进入 exec 前检查 PID1 仅持 console 0/1/2，且三个 stdio 都是 5:1、不带 FD_CLOEXEC。子进程 exec 失败可以 _exit，PID1 任何错误都进入 console rescue 循环，永不 exit。禁止全局 kill(-1)、force/lazy umount、隐式 reset。codec/pty 只有正常 exit=0 且回收检查无错才输出独立 `SOFTWARE_TEST_PASSED`，非零及信号终止进入救援。

本轮 `return` 只在没有控制台子会话和其他用户进程、没有额外挂载、没有 fd>=3 时继续；kernel threads 根据 PF_KTHREAD 判断。若用户把 shell 后台进程遗留，保留 PID/starttime 可见状态，用户可在 rescue shell 清理后重启同一检查。主流程不擅自杀未知 PID。受控子会话只在 leader PID/starttime/session 一致时可以对其进程组发信号。

## 从 ext4 返回 RAM

1. root 模式核 loop 和 mountinfo 身份、所有用户进程/FD；将阶段写入岛状态，然后先 exec 岛内同 SHA `/bin/pid1 return`，解除旧 root executable 映射。
2. return 模式重复身份核查，从旧根把 cache、dev、proc、sys、tmp、run 移到岛的相应目录。逐步记录进度；失败保留已完成步骤，不重复假设路径。救援状态显示实际路径。
3. chdir(岛)，pivot_root(.,old-root)，chroot(.)、chdir(/)。不得以 rootfs 初始根执行 pivot_root。
4. 正常 umount(`/old-root`) 成功后才 LO_CLR_FD 本轮 loop；再次 GET_STATUS64 必须 ENXIO，然后正常 umount(`/backing-cache`)。清理不成功则不输出 ready、不 reset，不 force/lazy。
5. 输出 `LINUX_PID1_RAM_READY_NO_RESET` 后继续 console 监督器。返回岛 BusyBox 和 PID1 为 RAM 映射。v1 没有 reset/flash/saveenv 命令；主控必须另行核查剩余 RAM mounts 才能执行用户已授权的复位。

## 故障与救援

阶段记录包括 boot/root/return 状态、owned loop inode/dev、迁移 mask 和 pivot 状态。任何失败保留首个失败步骤/errno，进入永久 rescue；可用 status 和独立 RAM BusyBox shell。root 切换前后 exec 失败均保留独立岛或原 RAM BusyBox 的可用路径；已 MS_MOVE、未 chroot 时使用 cwd 下 `./.ram-return` 与实际迁移后的相对虚拟挂载路径。root 切换尾部失败可人工 `resume`，重试尚未完成的 chdir/MS_MOVE/chroot，重复文件系统/ELF/进程/FD 核查后 exec root 模式。返回阶段 `resume` 只重试尚未完成清理；pivot 成功但 chroot/cwd 失败须先重试该步骤。loop CLR_FD 成功即记录已 detach，后续 close 失败不会误判设备仍 bound。bootstrap 前部失败不自动重试分配 loop。不可通过错误路径绕过身份核查。

## 构建与验证

先 RED 测试真实 main 的缺失行为，再以链接 `--wrap` 替换真实 syscall 边界；生产不携带 wrapper、测试分支、环境注入。测试检查调用次序、flags/设备、身份错误、全部关键 syscall 单点失败、部分迁移和 pivot/umount/loop 清理失败；host 和 QEMU 静态 AArch64 执行。真实 mount/pivot_root 需板测，wrapper 不证明内核允许它们。

离线 builder 固定 gcc 11.4 static 版本及源码/UAPI/ELF SHA，生成 16 MiB 普通 ext4 文件和 deterministic newc initramfs。mke2fs 只针对本目录新普通文件。逐 inode（包括 reserved allocated inodes）uid/gid=0 审计；导出每个白名单 ELF 再核 SHA，e2fsck -fn、superblock clean/no needs_recovery、大小和 applet 清单审计。交付 ext4 的全部 allocated inode 以及 CPIO 所有成员 uid/gid=0；host stage 临时文件沿用工作用户所有权，由 debugfs 仅在新镜像上修正并审计。cache 文件部署由主控以 root 创建，不能沿用 sx uid=1000。

尚未板测。缺失前提包括实际 cache free space、Linux 控制台可用性、loop/mount/pivot_root 内核实测、PID1 signal/孤儿回收与 exec 映射释放、U-Boot 本轮 Image/DTB/initramfs 地址及 CRC，以及完整恢复路径的板端证据。

## 独立审查后的 native v2 修复

build/review-rejected-v1/ 封存原 C、harness、生成器、审计器、计划及 v1 manifest
的实际字节；v1 生产三产物与测试报告不修改。定向红证据使用真实 v1 main，
model 保留稳定 mount ID/parent，并让旧 ext4 ELF 映射导致正常 old-root umount
返回 EBUSY；不能由无条件成功的 umount wrapper 隐藏这个失败。

内部 state 升为 v2，保存 initial RAM root、ext4 root、return island、cache、
dev、devpts、proc、sys、tmp、run 共十个 mount 的原始 ID、parent、filesystem
type 与 device。首次建立完整岛后记录它们；每一次 MS_MOVE 后、每次 resume、
pivot 后、old-root/cache 正常卸载后和最终 READY 前重新核完整可见表。每个预期
target 恰有一个 mount，ID/type/device/root 保持一致，parent 按 forward/backward
mask 和 pivot 状态计算。devpts 必须仍以原 dev mount 为父；同名 overmount 也
拒绝。old-root/cache 仅在本轮相应正常卸载已成功后可以缺席。

chroot 后初始 RAM root 不在当前 /proc/1/mountinfo 的可见子树中，其记录作为
已知外部 parent 锚保留；不要求 namespace 所有挂载都位于新根内。锁定
fs/namespace.c 的 pivot_root 将新岛挂在原 root parent 下、将旧根挂在岛的
old-root 下，因此这些父变化有明确源码依据。

finish_return 每次进入都要求已通过完整 state contract，且当前 PID1 exe
确为已记录岛 tmpfs 上同 SHA ELF。ROOT 中岛 exec 失败后的 resume 先重新核
ext4 root exe、完整挂载表、岛文件、loop/cache、进程和 FD，再次 exec 岛；
不能直接开始返回迁移。RETURN 初始检查失败也不能经 rescue 的 resume 跳过
state、exe 或挂载身份。缓存已卸载后若最终验证失败，RAM rescue 的 resume
仍重做完整剩余 RAM 表和 exe/进程/FD 检查，不重挂缓存、不重新 detach loop。

ROOT 到 RETURN 的 state_save 本身失败时，resume 的重 exec 路径先重新保存
当前完整 RETURN 状态，避免新 main 读取旧 ROOT 状态或截断文件。该边界实际
main 红证据为 open/fstat/write 三种失败不能恢复；修复后这些场景连同
fsync/close 单点失败均必须经真实重新 exec 和完整清理达到 RAM_READY。

## 板测反馈后的 native v3 返回岛命令修复

主控已板测 v2 的 ROOT_READY、codec/PTY 成功及原生回 RAM 的 mount/pivot/normal
umount/loop detach/cache umount。返回后 ash 报 sha256sum not found：原岛仅复制
两个 ELF，锁定 BusyBox 的 FEATURE_SH_STANDALONE 未启用，必须存在 PATH 中的
applet 链接。build/board-rejected-v2/ 保存修前所有 native 源和 v2 manifest；
现场原始日志由主控保存，不改 v2 三产物及旧证据。

v3 在岛中两个同 SHA ELF 成功复制后、任何向 ext4 root 的 mount move 之前，
按已锁定 --list 的 52 项顺序创建 bin/<applet> -> busybox 相对链接。任一
symlink 失败立即进入原有 rescue，不能输出 ROOT_READY 或继续 root exec。
不重编 BusyBox，不改 state v2 ABI，也不新增服务、自动 reset 或 mount 类型。

外部 syscall harness 对新 symlink 的目标、前缀、名称边界作严格检查，并在
fixture 的真实文件系统中创建链接。测试核 52 项恰齐、全部 target busybox，
用实际 AArch64 BusyBox ash 在仅该 bin 的 PATH 中逐项 command -v，再经
sha256sum 链接执行实际 applet。每一个真实新 symlink 调用单点注入失败，
必须保持 PID1 存活且禁止 root exec。[[ 在本锁定 ash 中通过外部 applet
查找；不假设它是 shell builtin。

production-v3 生成器只接受含完整 applet 清单、实际 main 调用序列与真实
BusyBox shell 查找的 host/QEMU evidence；冻结返回岛 8 个目录、两个 ELF 与
52 个相对链接的运行时白名单。rootfs/initramfs 原有 52 applet 白名单仍逐项
审计。新源码、新 ELF 与新镜像需重新独立审查及板测。

v3 使用全新普通 cache 目录 /cache/rtctrl-pid1-20261005-v3/；native 内部固定
ROOT_FILE 为 /backing-cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4，生成器
manifest 对齐该部署路径。wrapper 拒绝任何其他 rootfs 文件路径，真实 main
成功场景也检查实际 open 路径。旧已上板 v2 cache 输入与 frozen 三产物保留。
