# RK3568 源码 Linux 正常重启

本阶段在 RAM 显示接口检查和收尾守卫通过后，单独测试正常 reboot syscall。
已测 SysRq b 直接进入 emergency_restart；本测试进入 kernel_restart_prepare 的
reboot notifiers 和 device_shutdown，再到 syscore_shutdown、machine_restart。
锁定源码为 9f9e9d18574d0914c0d192a90c3babfe1fd63c95；目标 release 固定，实际 Image
身份仍由本轮 U-Boot 长度/CRC 与部署前完整 SHA 绑定，不能用 uname 代替。

本目录的 MIT 静态 helper 只接受 --request，只发 LINUX_REBOOT_CMD_RESTART，
要求 root、非 PID1、精确 kernel release、/tmp/normal-reboot 的 RAM executable。
外部先核无持久挂载、loop、模块和物理设备 FD。helper 不调用 sync、SysRq、poweroff、
flash 或网络；失败不会自动回退到另一种复位。syscall 进入关机链后可能阻塞，
用户态超时不能证明内核 device_shutdown 已完成。串口完整捕获并单列各 warning。

本轮屏幕排线、耳机、喇叭和电机均未连接，MCU/I2C5 无驱动，音频/WLAN模块未加载。
源码 PMIC syscore 会配置 RTC interrupt；仅 POWER_OFF 分支请求 PMIC 断电。
DRM shutdown 会停 display，panel shutdown 会走新补丁的 disable/unprepare。
返回 Android 后重读五启动分区和两份旧 rootfs 的 SHA、boot_completed 和电量。
成功只证明本次正常重启往返，不验收真实 poweroff、MCU ACK、看门狗或电源轨。

先验证实际生产 main 的 syscall 边界，再构建静态 AArch64，host/QEMU 同样测试。
生产 ELF 没有 wrapper 或测试入口。构建拒绝覆盖，包含源码/编译器/ELF/测试 SHA。
截至此计划创建时尚未板测。
