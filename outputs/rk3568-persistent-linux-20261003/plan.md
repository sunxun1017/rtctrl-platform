# 原内核持久化用户空间与迁移基线

用户授权继续最小Linux后的持久化rootfs工作，并明确要求传输慢时先在Android验证驱动和库，再在Linux验证。
本轮使用原4.19.232内核和配套FDT；保持已验证旧RAM产物，新增独立BusyBox、initramfs和普通64MiB ext4文件。
不更换原boot、保存U-Boot环境或盲目运行厂商库构造函数。既有应用源码改动保持原样。

- [x] Android现场：重新核实身份、loop/ext4能力，采集驱动绑定、模块元数据、Wi-Fi实际固件路径和库的ELF依赖/进程映射。
- [x] 本机构建：新静态BusyBox补齐挂载/chroot/清理/reboot/校验工具，配置与原15项applet版本分开保存。
- [x] Android先验：创建普通64MiB ext4镜像，私有mount namespace中组装rootfs，进入同一rootfs验证工具和标记读写；卸载后重挂确认。
- [x] Linux对照：原内核RAM启动，先核对cache GPT PARTNAME/大小；挂镜像供子进程chroot使用，核对驱动绑定，验证Android标记并写入Linux标记。
- [x] 返回与持久性：退出子进程，按dev/proc/sys→rootfs→仅本轮loop→cache清理，所有步骤成功后正常内核reboot；Android重挂rootfs读回Linux标记。
- [x] 交付：根文件系统、启动和清理脚本、Android/Linux迁移矩阵、已验证结果与缺口；更新项目记忆。

PID1本轮仍留在initramfs，持久化rootfs用于子进程用户空间；不将此阶段称为switch_root或整机生产部署。
Android/Bionic/HAL/JNI库先做实际依赖与使用证据检查，不能直接当作glibc/musl库。驱动绑定、功能测试和ABI兼容性分别记录。
不主动采音/采帧、发送执行器指令或改变看门狗设置。Wi-Fi重新连接、GPU/NPU计算与其他功能验证按已核实依赖逐步安排。
如果挂载/loop清理失败，保留RAM诊断shell并停止重启，不能照搬上一轮SysRq方法。
