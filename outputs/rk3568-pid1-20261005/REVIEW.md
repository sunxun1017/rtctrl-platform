# PID1 production-v2 独立复核

2026-10-05，`display_next_steps` 只读复核通过。此结论允许分阶段板测，不代替真实 mount、loop、console 或返回流程验证。

`pid1.c` SHA256 为 `064ed3e89795cb658b64525900aaf9e6f0538a7a099390f44995f17936606a32`。RETURN 恢复在原 ext4 上执行时，重新核 root、进程、文件描述符、挂载与 tmpfs 身份，先成功保存状态再执行 RAM PID1。五种状态文件故障与 exec 故障的恢复证据确实经过真实 execve，启动全新测试进程并重新读取状态。

最终 `verified-host-v2` 与 `verified-aarch64-v2` 各 802/802。曾为 797 项的历史 `final-*-v2` 不纳入此次通过。最终收据绑定的 46 份文件长度、SHA256、CRC32 和九份生产源码快照全部匹配。

生产为静态 AArch64 ELF；ext4 中 `/bin/pid1` 和 initrd 中 `/init` 均匹配 `8f509bc09988ee419a74b57936bd0c80a0ccf9d214141ebd7b859668a10bc75e`。原始 ext4 bitmap 的 86 个已分配 inode 全部 uid/gid 0；CPIO 内启动清单与外部清单相同。三份产物的长度、SHA256 与 CRC32 全部一致。

生产清单 SHA256：`8f7f15481a0c76db2bcb4d5f3e3a707873fd760c2c0408238854b71ca6d344ca`。最终证据收据 SHA256：`2a29198a0e7f070f023c9dd7921d5cdf20833567044237adf898f983d820e0ae`。

主控的 `board-manifest-v2.json` 已绑定新 ELF 与返回检查脚本；实际 52 applet BusyBox 执行的挂载、进程、文件描述符失败用例和串口命令绑定检查合计 73/73。早期 v1 输入及失败证据保留。

## production-v3 与 session-v4

v2 板测发现返回岛缺少 BusyBox applet 链接，实际切根、软件测试和正常卸载返回已成功，但该版本的完整收尾需要人工补齐。v3 在切根前建立全部 52 个相对链接，并使用独立 `rtctrl-pid1-20261005-v3` 缓存目录。

2026-10-05，独立复核 v3 通过：host/QEMU 各 855/855，全部 52 个 symlink 的失败注入阻止继续 exec/READY；真实 BusyBox 在仅有返回岛的 PATH 中找到完整命令，`sha256sum` 通过实际链接执行。审查从 ELF 的 PT_LOAD 独立还原 52 项指针数组，核顺序、唯一性与锁定 BusyBox 清单一致。61 项最终证据绑定、九份源码快照与实际输入全部匹配；rootfs、initrd 内 ELF 均与生产 PID1 逐字节相同，v2 产物和快照保留。

生产 PID1 SHA256 为 `249cc1cfd87cbddc8618e81e6b8fd742526de78fd964d4a4b3b59b8a7d76368b`。生产清单 SHA256 为 `53f8807d3e2ab63fbe7d4b35cab33a391b28e00bf317179fedeac1a6f7306484`。session-v4 已薄核绑定此版本及更新后的返回检查脚本。

实机 BusyBox 交互父 shell 的 FD10 是控制终端 `/dev/tty`，实际为字符设备 5:0。返回检查仅对身份、父进程、进程组和会话均匹配的父 shell 接受这个 FD10，PID1 和检查进程自己的该连接仍被拒绝。九个新用例先红 79/82，再绿 82/82；加生产清单绑定检查后 session-v4 共 83/83。实际板测结果另见收据，不从离线通过推断完成。
