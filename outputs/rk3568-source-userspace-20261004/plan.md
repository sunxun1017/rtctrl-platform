# 源码内核上的持久化用户空间验证

用户授权继续已有迁移路线。本阶段沿用原Android基线与U-Boot RAM启动，不刷写启动分区。

1. 重新核验ADB/root/供电/串口；保留2026-10-04首启产物与历史记录。
2. 在现有firstboot片段关闭未使用的RGA、SCMI power-domain/reset及RK817 charger子驱动，
   核对最终Kconfig；保留SCMI clocks/CRU reset/PMIC/IO域/温度/eMMC。
3. 生成新的源码Image与包含完整静态BusyBox的RAM bootstrap，保留明确补丁/配置/摘要；
   PMIC诊断缺陷只在能证明硬件配置分支不变的情况下单独修正。
4. 新建独立64MiB普通ext4文件；Android写标记并运行源码codec/PTY基线。
   不复制原4.19内核模块、厂商用户库或MCU缓存程序。
5. U-Boot加载CRC核对，PID1仍RAM；源码5.10中运行同一codec/PTY，
   子进程chroot验证文件读写，完整卸载/释放本轮loop。
6. RAM-only guard后即时SysRq返回Android；只读noload回读标记，核对启动分区SHA与网络/串口收尾。

成功依据：实际源码内核release/输入摘要；减少的警告；三系统阶段标记与测试一致；挂载清理；Android返回。
未覆盖：正式rootfs介质/自动启动、运动/真实MCU ACK、正常关机、长时/实时性及所有外设。
