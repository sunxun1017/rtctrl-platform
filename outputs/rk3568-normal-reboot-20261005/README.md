# RK3568 正常重启已完成一次板测

源码显示内核在RAM运行、零亮度接口与收尾守卫通过后，调用正常reboot(RESTART)。
454.881364秒记录 Restarting system，完整串口显示DRM VP1关闭及DDR/loader→Android启动；
新鲜Android11/4.19.232/root/boot_completed1，五启动分区和两份旧rootfs七SHA未变，电量78%。
返回过程中未使用SysRq、flash、saveenv或MCU命令。请求至首DDR未捕获WARNING/BUG/Call trace。

MIT静态helper只接受--request，要求root/nonPID1、固定release与/tmp/normal-reboot的RAM executable。
外部请求先验证冻结的显示RAM守卫及helper完整SHA。真实main host/QEMU共32项边界测试，
生产ELF无测试syscall wrappers；glibc自身__wrap_main是正常启动实现，不作测试入口判断。
生产SHA `6c90fe3dca1f0ae6ffab50eddbfdccca27cc2f8ccf0821814456ae3980fe09f5`，646720B。

[PLAN.md](PLAN.md)、构建器与测试描述真实调用链及失败门槛；[result.json](result.json) 为本次板测结果。
[显示实测](../rk3568-display-20261005/README.md) 包含输入、全部原证据SHA和回读结果。
这是一次正常device_shutdown重启往返；普通poweroff、MCU应答/看门狗和物理电源轨仍未验收。
REQUESTED输出只表示发起请求前的记录；任何后续测试也需新鲜返回证据，不能只匹配该标记认作通过。
