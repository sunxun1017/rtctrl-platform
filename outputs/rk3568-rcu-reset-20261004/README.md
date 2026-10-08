# RK3568 SysRq 日志刷新 RCU 修正

2026-10-04：已修正已观察到的 RCU 睡眠判断缺陷，重新编译源码 Linux 5.10.160-rt89 并实机启动。
源码 codec/PTY 再次通过，完整卸载后沿用原 SysRq 即时复位路径返回 Android；
**本次完整 Linux 复位捕获没有再出现 RCU 调度警告或 Call trace。**
五个启动分区完整 SHA 前后一致。收尾串口确认 Android11/4.19.232、boot_completed=1/root；
网络 ADB root 查询也通过，printk恢复7/4/1/7，串口已释放。电量45%，AC/USB powered=false。

## 修正依据与范围

上一轮实测栈为 SysRq 持有外层 RCU 读锁，`emergency_restart → kmsg_dump → pr_flush → msleep`，
见[原警告记录](../rk3568-source-userspace-20261004/reset-warning.txt)。
`pr_flush()` 仅用 preemptible、softirq、系统启动状态判断能否睡眠；抢占式 RCU 读侧允许被抢占，
但不能主动睡眠，因此原判断会漏掉实际调用者持有的 RCU 读锁。

[0003-printk-rcu-flush-context.patch](../../platforms/rk3568/boards/aiot-3568pq/patches/0003-printk-rcu-flush-context.patch)
在 may_sleep 中增加 `!rcu_preempt_depth()`，RCU 读侧改走原有非睡眠等待分支。
普通进程仍可 msleep；保留日志目标、返回值与超时策略，没有删日志、解除 SysRq 读锁或修改电源/MCU处理。
锁定树的 PREEMPT_RCU API 直接读当前嵌套深度，不依赖 PROVE_RCU/lockdep；非 PREEMPT_RCU 构建
由原 preemptible 判断覆盖读侧禁止睡眠条件。没有采用 DEBUG_LOCK_ALLOC 关闭时恒为真的 rcu_read_lock_held，
也没有采用 RT 中恒为0的 sched_rcu_preempt_depth。

当前四处实际调用都是 pr_flush(1000,true)：无进展时等待预算递减，有进展时可重置。
**1000表示无进展预算，不是总墙钟时间最多一秒。** API 的无限等待能力未改动。

## 源码与构建验证

[test-pr-flush.py](test-pr-flush.py) 提取并编译实际 pr_flush/pr_msleep 函数，控制外部上下文和 console 进展。
原函数实测失败于 RCU 内主动睡眠；真实补丁应用后通过以下行为：

- 有积压的一层/嵌套 RCU 不睡眠，无进展时预算耗尽，取得进展后成功返回。
- 普通进程保留睡眠等待，普通无进展超时仍准确退出。
- 原子上下文、softirq、早期启动、零超时、已追平和禁用 console 不走错误等待路径。

外部 console、RCU 状态及延时调用是测试夹具，真实调度器/RCU 机制没有在主机中仿真；
它验证真实函数的分支、返回和等待行为。实机另验证完整内核与 SysRq 返回，未插入板端分支计数器。
这次一次复位没有警告，不推广为全部上下文、长时稳定性或正常关机已通过。

[build-kernel.sh](build-kernel.sh) 从锁定 commit
`9f9e9d18574d0914c0d192a90c3babfe1fd63c95` 完整构建，使用 GCC11.4 和原两补丁加本次第三补丁。
配置逐字节等于上一轮；DTB/initramfs逐字节复用已验证输入；没有重新生成板级电源配置。
构建后只撤销自身三补丁并检查第三方源码干净。
独立审查还修正了构建入口的失败清理：单项反向补丁失败后仍尝试其他项，成功项立即清标志；
[test-build-restore.py](test-build-restore.py) 用真实源文件和补丁临时树验证失败、重试和恢复。
这项脚本修正不改变已经成功构建的 Image，无需重复构建。

| 输入 | 字节数 | SHA-256 |
| --- | ---: | --- |
| 新 Image | 34755072 | e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457 |
| 复用 DTB | 161378 | 20c8f026b71fe4e8a8752a9407087eb05b4e4819b3fa7e2f4845be17727d8c15 |
| 复用 initramfs | 621515 | 7e5c405148ee46e44d845d0c123d469c4d848fbe928f6ed3e448cfed98d57e5c |

release仍为5.10.160-rt89-g9f9e9d18574d-dirty，必须用Image SHA区分各轮。
Image含BSS的内存跨度35389440字节，加载范围[0x00400000,0x025c0000)；
DTB载入0x03000000，initramfs载入0x04000000、结束0x04097bcb。
配置与三项补丁 SHA/CRC 见[kernel-artifacts.json](kernel-artifacts.json)。清单生成时的板测标志保留历史，
本轮运行结果见[result.json](result.json)。

## 现场顺序与网络结果

开始时串口/root/原Android正常，ADB offline。只读确认adbd监听5555，但到网关邻居FAILED、
两次ping全丢，Wi-Fi关联COMPLETED也不能代替通信可达证据。
关闭再开启已保存Wi-Fi，稍后重新关联成功，重新连接该ADB transport后root查询和传输通过。
新Image约1.7秒上传；返回Android后ADB root再次通过。没有改认证、密码、路由器、代理/TUN、
全局ADB服务器或持久化网络配置；不能由这次恢复推定弱信号或掉线根因已经完全解决。

Android [prepare-boot.sh](prepare-boot.sh) 将新文件放到独立实验目录，逐项SHA核对，不覆盖旧rootfs/产物。
U-Boot现场重查内存银行、mmc0/cache0:c，三输入加载CRC通过，内存FDT/环境修正后booti。
Linux PID1仍在RAM；cache仅挂ro,noload，运行经SHA核对的同一静态codec/PTY程序，
测试自有devpts清理，cache卸载后再独立RAM/loop guard，最后请求SysRq b。
本轮没有chroot或写入持久化rootfs；上一轮Android→Linux→Android的文件标记实验保留原结论。
温度样本43.125/43.125℃，测试后uptime68.76秒，复位请求83.932秒。

脚本入口：[describe-inputs.py](describe-inputs.py)、[load-ram.json](load-ram.json)、[boot-ram.json](boot-ram.json)、
[linux-check.json](linux-check.json)、[test-source-programs.sh](test-source-programs.sh)、[return-android.json](return-android.json)。
串口步骤匹配失败会停止：如果已经挂cache，需要人工核查/卸载，再通过独立guard；
不能把脚本提前停止当作清理成功。测试脚本只清理自己挂载的devpts。

## 当前边界与接续

SysRq即时复位本次通过；普通reboot/device_shutdown、真正关机、看门狗和电源轨仍待独立验证。
MFD缺of_node、FIQ可选IRQ/NMI、regulatory.db等启动提示仍在，不称整轮日志无警告。
codec/PTY不打开物理UART，不验证实际MCU、运动或安全停止；NPU/音视频/源码Wi-Fi板测仍待推进。
原DDR/loader/trust与Wi-Fi/MCU固件缺口单列；没有saveenv、刷写启动分区、发送电机命令、提交或推送。

下一阶段按依赖补充源码Wi-Fi的Android基线/设备树/固件请求对照，再选择正式rootfs与启动入口。
网络端口、地址、串口、供电和运行状态下次必须重新核实。

证据：[Linux运行读回](linux-runtime-check.txt)、[复位摘录](reset-excerpt.txt)、
[机器结果](result.json)、[主机复核](verification.txt)。原始证据SHA记录于机器结果；
raw、机器标识/网络地址及私有串口/ADB辅助脚本只保留在忽略的private目录；
生成二进制由本目录.gitignore排除，不纳入公开文件。
