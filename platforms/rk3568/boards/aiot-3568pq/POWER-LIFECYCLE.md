# 原厂关机证据与 Linux 电源生命周期适配

当前仅确认原 Android 执行到内核 power-down 路径，未测量电源轨，也未验证新 Linux 的 MCU 协作。
原始命令为 `su 0 setprop sys.powerctl shutdown`。
[已提交的关机输出摘录](../../../../outputs/rk3568-boot-preparation-20260928/shutdown-evidence.txt)
保留原厂日志中的函数名和时间顺序；完整串口流仅在本地采集目录保存。

## 已观察到什么

|原厂日志|证据支持的结论|不能据此确认|
|---|---|---|
|`mcuinterface_shutdown`，reason=3|原厂关机进入 MCU 接口驱动的 shutdown 路径|3 对应的协议值、总线地址或消息帧|
|`WriteWatchdogOffFlagToMCU`|驱动打印了关闭 MCU 看门狗的写入动作|实际发送字节、MCU ACK、看门狗确实停止|
|`WritePowerOffFlagToMCU`|驱动打印了 MCU 断电标志写入动作，出现在看门狗步骤之后|标志是否立即断电、延迟生效或仅记录关机原因|
|`reboot: Power down`|内核已进入最后的关机路径|随后整板是否掉电、待机电源是否保留、MCU 是否仍运行|

日志另有 xHCI halt 超时和 invalid GPIO 提示；不能把本次操作描述为无警告关机。
日志里的 `drivers/smdt/mcuinf.c` 是原厂编译路径线索，不代表本项目已经取得这份源码。
该 MCU 与项目 GD32 协议实现的对应关系、是否经 UART0 通信均未证实，不能直接套用已有 codec。

补充设备树与绑定证据：原树 I²C5 `mcuinf@62` 声明 `smdtmcu,STM8S00K3`，
采集的 `5-0062` 已绑定 `McuCom`；板控 MCU 已有明确 I²C 接口线索。
尚待核对的是这个驱动与关机函数的源码对应、寄存器/消息语义及 ACK，不是完全没有 MCU 设备信息。
见[设备树框图](DEVICE-TREE-DIAGRAM.md)，该节点不可直接与 UART0 的 GD32 混同。

## 对首次启动的影响

当前候选禁用 UART0，没有实现上述 MCU 生命周期协议。禁用 UART 节点不会关闭 MCU 内已经运行的看门狗。
从 Android 切换内核、重启、异常复位或断电上电时，MCU 可能保留不同状态；具体行为尚未知。
因此“系统能进入 shell”与“能持续运行、正常重启和物理断电”必须分别验收。
现有 initramfs 不自动调用 reboot/poweroff；这不是硬件看门狗保护机制，也不能阻止 MCU 自主复位。

## 恢复供电后需要取得的证据

1. 在原 Android 上只读核对 MCU 设备节点、驱动绑定、DT 属性、启动参数和可取得的源码/模块线索，确认实际传输接口。
2. 有源码时追踪上述函数的寄存器/消息定义、返回值和错误处理；没有源码时，结合原系统受控操作进行被动总线抓取。
   不以函数名、reason=3 或现有 GD32 协议猜测并试发断电/看门狗命令。
3. 记录看门狗何时启用、谁负责喂狗、超时及复位对象；区分冷启动、Android 正常关机、重启和内核交接的状态。
4. 在恢复入口可用后，测量关机时主电源/待机电源状态，并关联 MCU 应答与串口时间线。
   LED 熄灭或串口静默本身不足以证明所有电源轨关闭。

## 实现与验收边界

先确认接口、命令语义和响应，再决定适配放在内核驱动还是用户态服务，不预先选择猜测的 UART/GPIO。
正常关机需协调业务退出、存储同步/卸载、看门狗状态和最终断电请求；具体次序取决于命令是否立即切电及其超时。
发送失败、MCU 无响应和重复请求必须有有界处理，不能无限等待或盲目重试电源动作。

验收分别记录：冷启动后的看门狗状态、稳定运行、正常关机、正常重启及通信失败时的行为。
每项保留系统日志、总线响应和适用的电源测量；尚未完成这些验证前，不宣称 MCU 电源管理已移植。

## 2026-10-03 原驱动静态接口补充

后续已将现场选定符号与备份 Image 对应，确认这些函数属于 I²C5 McuCom 驱动。
现场运行 FDT 的 `skip-mcu` 为真：原驱动跳过身份/版本初始化、看门狗启用及工作线程；
读写 helper 返回255且不执行总线操作，上层的部分成功判断仍可能接受这个值。
因此此前关机日志中的“成功”不能证明有真实 MCU 写入，更不能据此证明自主看门狗关闭。

非 skip 代码里，关闭看门狗对应寄存器0x32写0，断电标志对应0x51写0x55；
仅取得静态代码意图，未执行这些写入、测得ACK或电源轨。正常 probe/worker 的错误与重试还有边界，
不可原样复制成未经验证的生命周期实现。
完整事实、Image 指纹及复核位置见[MCU-INTERFACE.md](MCU-INTERFACE.md)。

新独立 C 程序只读0xc0内核缓存，Android/独立原4.19 Linux均返回六字节全零。
它没有查询物理MCU，不代替上述生命周期验收。本轮普通reboot返回Android成功，
与完整关机及看门狗交接验收分开记录，见
[源码对照记录](../../../../outputs/rk3568-mcu-baseline-20261003/README.md)。

## 2026-10-04 源码内核 RAM 首启与即时复位

源码5.10.160-rt89、重建DTB和最小initramfs已实机进入串口shell，短时空闲观察至uptime199.19秒。
PMIC/TCS、IO域、温度驱动已绑定；其probe会操作硬件寄存器，不能把RAM启动描述为没有硬件状态变化。
UART0与I²C5/MCU未启用，没有加载原McuCom驱动或调用缓存/电源ioctl。

确认挂载仅rootfs/devtmpfs/proc/sysfs/tmpfs后，请求SysRq即时复位，返回原Android11/4.19.232，
boot_completed=1且五个启动分区SHA仍一致。这只证明本次RAM启动后的即时复位返回，
未调用源码内核的普通device_shutdown流程，不代表正常重启、关机、MCU ACK或物理断电通过。
启动前电量59%，结束摘要58%，Android仍报告AC/USB powered=false；不能当持续外部供电测量。

本轮对MCU遗留状态没有新的协议/总线证明，199秒无自主关机不证明看门狗完全关闭。
原loader/DDR/trust保留，源码内核仍有SCMI/RGA/MFD等警告；证据和后续处理见
[源码首启记录](../../../../outputs/rk3568-source-kernel-20261004/README.md)。

## 2026-10-04 新源码用户空间往返与 SysRq RCU 警告

新编译5.10内核中已完成普通ext4文件rootfs的只读noload验证、RW chroot源码测试及标记写入。
cache/rootfs/devpts与loop完整清理后，独立RAM-only guard通过，SysRq即时复位返回Android，
两份标记SHA回读一致、五个启动分区SHA未变。结束电量52%，AC/USB powered仍为false。

此次复位日志出现rcu_note_context_switch警告。调用栈为
`__handle_sysrq → emergency_restart → kmsg_dump → pr_flush → msleep`：
SysRq外层RCU读锁包住重启回调，日志等待分支未排除RCU读侧，主动睡眠触发告警。
它发生在硬件reset hook之前，不能归因于PMIC/MCU，也不能用成功返回Android掩盖警告。
相关SysRq/reboot/printk/RCU源码本轮没有新增修改，具体证据见
[新用户空间记录](../../../../outputs/rk3568-source-userspace-20261004/README.md)与
[复位调用栈](../../../../outputs/rk3568-source-userspace-20261004/reset-warning.txt)。

后续先处理并板测SysRq日志刷新上下文，再独立验证普通reboot/device_shutdown及关机。
普通reboot没有这处SysRq外层读锁，但其硬件回调仍未验收；实际MCU应答、看门狗交接及电源轨测量仍缺。

## 2026-10-04 RCU 最小修正后的复位对照

后续新增printk补丁，may_sleep排除rcu_preempt_depth，使用既有非睡眠等待，不改电源/MCU处理。
源码函数回归复现原缺陷并验证修正，新完整Image、相同配置/DTB/initramfs已实机启动。
仅ro,noload挂cache运行源码测试；卸载与独立RAM/loop guard通过后沿用SysRq b，
这次完整Linux复位捕获无RCU警告/Call trace，成功返回Android且五个启动分区SHA未变。
结束电量45%、AC/USB powered=false；仍不能当外部持续供电或物理轨测量。

本次一次同路径复位支持该修正，不等同普通device_shutdown、正常重启/关机、MCU ACK或看门狗接管。
日志无进展等待预算为1000ms，有进展会重置，不能称复位日志等待具有全局一秒硬截止。
证据：[RCU修正与板测](../../../../outputs/rk3568-rcu-reset-20261004/README.md)。

## 2026-10-05 源码显示内核的正常重启

0008 panel-simple错误传播配独立720×720/亮度0 DT，屏幕排线断开，RAM接口74项通过。
释放cache/debugfs、核仅RAM mounts、无loop/module/物理设备FD后，MIT静态helper请求reboot(RESTART)。
这次真正经过kernel_restart_prepare/device_shutdown/syscore_shutdown，DRM日志确认VP1关闭，
454.881364秒Restarting system后返回Android11/4.19.232/root/boot_completed1；未用SysRq。
本次正常关闭请求至首DDR未捕获WARNING/BUG/Call trace；启动既有BSP和显示诊断仍在。
五启动分区和两份旧rootfs七完整SHA一致，结束电量78%、AC/USB powered=false。
PMIC/TCS和WLAN power回调确实改变运行期状态；MCU未启用，没有MCU指令或ACK。
这补足一次源码5.10正常重启往返，不等同poweroff、看门狗交接、电源轨或长时稳定性。
证据：[正常重启](../../../../outputs/rk3568-normal-reboot-20261005/README.md)、
[显示接口与完整输入](../../../../outputs/rk3568-display-20261005/README.md)。

## 2026-10-05 原生 Linux PID1 的普通重启往返

原生 PID1 v3 实机挂普通 loop rootfs 为只读根，运行协议/PTY纯软件自检并回收自有子进程；
返回时先 pivot 到 RAM，卸载旧根、detach loop、卸载cache，独立guard确认仅七个RAM挂载。
这次返回岛的52个BusyBox链接由PID1原生创建，没有手工修复或临时放宽guard。
真实reboot(RESTART)在165.596432秒Restarting system后返回原Android11/4.19.232/root/boot_completed1，
五启动分区和两份保留rootfs七完整SHA前后一致，电量67→67%。请求至首DDR窗口没有
WARNING/BUG/Call trace/Kernel panic；范围不扩大到其他启动诊断或关机电气状态。
v2历史试验需要手工补链接和父TTY guard后才普通重启，单列为协助收尾，不与v3合并计数。
PID1交接/回RAM/正常重启已具本次现场证据；生产服务退出、音频DMA、poweroff、MCU ACK和看门狗仍待验。
完整输入、原始流和48项只读汇总见[PID1实测](../../../../outputs/rk3568-pid1-20261005/BOARD-RESULTS.md)。

## 2026-10-05 Linux RAM bootm 包的普通重启收尾

同一Linux v2包第二次试验（trial-v3）最终overlay/full-tree通过后，原生PID1运行软件自检并回收子进程，
自行回RAM、卸载旧根/cache、detach loop，独立七挂载guard通过。普通reboot请求在1656.913338秒
达到Restarting system，随后DDR与原Android11/4.19.232/root/boot_completed1；没有SysRq或手工返回岛修复。
七保护输入完整SHA相同，电量62→60%；请求至首DDR窗口无WARNING/BUG/Call trace/Kernel panic。
此时间是内核时间戳，并非重启耗时。该证据限当前没有音频流和外接屏幕/电机的RAM包试验；
不扩大到DMA运行后的关闭、poweroff、MCU ACK、轨测量或正式flash恢复。
见[71项完整现场结果](../../../../outputs/rk3568-bootm-ram-20261005/linux-candidate-result-v3.json)。

## 2026-10-06 声音传输后的正常重启

新CPU v12声音镜像第四轮RAM启动后，自然初始休眠和顺序播放/采集有限传输通过。
正常解绑声卡、卸载codec、解绑CPU后，16项时钟引用全零、DMA通道和隔离缓冲为零。
原生PID1完成软件自检、卸载文件系统、回RAM及独立guard后请求普通restart；
747.877323秒的Restarting system至首DDR窗口无严重trace，返回原Android11/4.19.232。
七保护对象和三项native缓存完整SHA与试验前相同。这是单方向声音运行后的正常重启证据，
不扩大到全双工、poweroff、MCU ACK、电源轨或正式刷机恢复。
详见[第四轮汇总](../../../../outputs/rk3568-audio-runtime-20261005/build/board-results-20261006-v4/result.json)。
