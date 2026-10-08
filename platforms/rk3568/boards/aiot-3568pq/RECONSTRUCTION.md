# 无原厂 BSP 的 Linux 重建

可以基于公开 RK3568 内核与原机资料重建板级支持，不再以取得整套原厂 BSP 为前提。
本目录的板级 DTS 与源码构建的 Linux 5.10.160-rt89 已于 2026-10-04 实机启动，
进入独立 RAM shell 并返回原 Android；随后新编译内核与持久化文件rootfs中的独立源码程序对照通过，
尚未形成可部署的整机刷机包。
当前已修正SysRq日志等待的RCU判断并重新板测；随后同源码Wi-Fi模块与联网工具
已完成认证、DHCP和网关通信；后续启用TRNG并以PM=0/仅5GHz配置完成64KiB电脑TCP双向传输，
三端SHA一致。默认与仅PM0两组的电脑ARP/TCP仍失败，根因和长时重连尚未确认。最新网络结果见
[RNG与5GHz传输](../../../../outputs/rk3568-rng-network-20261004/README.md)，首轮部分结果保留于
[源码Wi-Fi对照](../../../../outputs/rk3568-source-wifi-20261004/README.md)，基础结果以
[RCU修正板测](../../../../outputs/rk3568-rcu-reset-20261004/README.md)及
[源码用户空间板测](../../../../outputs/rk3568-source-userspace-20261004/README.md)为准，
下面保留首轮设计和历史构建边界。

后续新 64 MiB 源码工具 rootfs 已完成 Android 4.19 /源码 Linux 5.10 的 chroot、
RAM 临时目录、持久标记往返与两份回传快照校验；PID1 仍在 RAM，未 switch_root/自动启动。
五个启动分区完整 SHA 不变，新鲜 Android 64 KiB TCP 对照通过。
这一rootfs阶段的WPA版本检查曾出现CRNG未就绪提示，旧Wi-Fi DTB的rng节点disabled；
后续独立wifi-rng DTB已板测：rockchip-rng绑定、0.749178秒crng init done、认证前getrandom就绪均通过，
不能把此前未就绪提示认作ARP失败原因。
独立 wifi-rng 候选已离线编译，104 项审计与 11 项实际 DTB 故障拒绝通过，
解析差分只有 rng/status；保留旧实测文件，新候选已在上述独立网络轮上板。
最新 rootfs 实机结果见 [源码工具 rootfs](../../../../outputs/rk3568-network-rootfs-20261004/README.md)。
原BusyBox关闭FEATURE_CMDLINE_MODULE_OPTIONS，实际insmod吞命令行参数；新版独立构建只启用该选项，
真实对象syscall mock红绿与QEMU通过，尚未上板或替换已验证rootfs。

## 已实现的第一阶段

`bsp/rk3568-aiot-3568pq-firstboot.dts` 使用锁定 Linux 5.10.160 的 `rk3568.dtsi`，
**不包含任何 EVB/Orange Pi 板级 DTSI**。SoC控制器、时钟和reset定义由目标内核提供，
原机4.19的寄存器编号不直接复制到5.10。

`bsp/rk3568-aiot-3568pq-power.dtsi` 从原机运行树重建固定电源、TCS452x、RK809 regulator约束和PMIC引脚。
每个供电引用由原树数字phandle恢复成可维护的符号，包含以下关键差异：

- vccio4/vccio6接1.8V，不能采用EVB的3.3V。
- LDO4/vccio_acodec为3.1V；DCDC1/2/4下限825mV。
- GPIO0_A2的PMIC sleep使用pull-up，GPIO模式使用output-low+pull-down。
- USB 5V regulator没有原机GPIO属性，不添加EVB的GPIO0_A5/A6。
- DDR regulator没有已知电压约束，保持原机always-on，不猜电压。

首轮启用FIQ调试串口（UART2、1500000 baud）、eMMC、两个USB2 host控制器和温度保护。
eMMC先限制52MHz；本版本dwcmshc驱动对该频率会清除HS200/HS400/DDR能力。
原机内存的三个有效范围及两项memreserve保留，不将内存简化成连续4GB。

首轮UART0/MCU、SD卡、SDIO Wi-Fi、GPU/NPU、显示、CSI2和DDR调频不启用。
配置关闭CPU调频、BQ25700/RK817电池驱动、FUSB302驱动及板载RK817声卡，USB声卡保留。
2026-10-04第一次首启完整配置仍继承CHARGER_RK817=y并观察到相关警告；后续本目录配置片段
已关闭该子驱动、multi-RGA、SCMI power-domain/reset客户端，并重新编译和实机验证。
RK808 MFD仍创建部分缺少DT子节点的设备，警告尚在；SCMI clocks和CRU reset保留。
通用SoC片段仍编译一些尚未启用的能力；“设备树未启用”不等于内核完全没有这些驱动代码。

## 配置与可复现编译

当前完整Image构建使用[已验证构建脚本](../../../../outputs/rk3568-rcu-reset-20261004/build-kernel.sh)，
其中记录三项补丁、构建顺序及恢复源码，含pr_flush的RCU读侧禁止睡眠修正。
未应用cache补丁时，下面历史命令的prepare-headers
可能触发RT头文件include-cycle；不把这段独立配置/DTB流程当作当前完整Image入口。
从仓库根目录在Linux/WSL执行，所有输出目录必须为新目录或空目录：

```sh
python3 scripts/prepare-linux-config.py \
  --candidate platforms/rk3568/boards/aiot-3568pq/firstboot-candidate.json \
  --output .deps/kernel/aiot-3568pq-firstboot-config --prepare-headers

python3 platforms/rk3568/boards/aiot-3568pq/build-firstboot.py \
  --kernel third_party/linux-rk3588 \
  --dtc .deps/kernel/aiot-3568pq-firstboot-config/scripts/dtc/dtc \
  --output .deps/kernel/aiot-3568pq-firstboot-dtb
```

若prepare未生成DTC，可用已安装的`dtc`或已构建的同版本内核DTC，通过`--dtc`明确传入。
本次实测复用了 `.deps/kernel/aiot-3568pq-final/scripts/dtc/dtc`。
`--cpp`默认gcc，只进行预处理，未用主机编译器生成ARM内核机器码。

构建器检查源码commit=`9f9e9d18574d0914c0d192a90c3babfe1fd63c95`和干净状态，
不往third_party源码中复制文件，不覆盖旧输出。实际经过CPP→DTC→反编译→节点审计。
输出包含DTB、展开/反编译DTS、命令argv与可读命令、全部诊断、`audit.json`和`manifest.json`。
清单始终标记`deployable=false`、`board_boot_tested=false`，没有接入自动部署profile。

审计从**编译后的DTB**解析供电引用，检查电压、PMIC引脚、存储、UART和禁用节点，
还检查原机标识/Android root参数没有被带入。故障注入回归：

```sh
python3 platforms/rk3568/boards/aiot-3568pq/test-firstboot-audit.py \
  .deps/kernel/aiot-3568pq-firstboot-dtb/rk3568-aiot-3568pq-firstboot.dtb -v
```

验证记录：[本次命令、日志与边界](../../../../outputs/rk3568-reconstruction-20260928/README.md)。
这些是独立内核/DTC构建入口，不修改C++应用的CMake目标，也不以无关CTest通过替代板级验证。

## 需要特别保留的边界

`regulator-init-microvolt`是原树证据，目标FAN53555/RK808驱动不消费此属性；不能宣称它强制启动电压。
固定regulator描述的是软件供电关系，不代表已经测量输入实际电压。首次启动已读回驱动绑定与供电属性；
`microvolts` 是软件/寄存器selector换算，尤其外部反馈DDR的500000读数不是物理电压测量。

这版BSP的eMMC驱动把runtime PM函数包在`CONFIG_PM_SLEEP`内，关闭SUSPEND会实际编译失败。
因此配置保留`CONFIG_SUSPEND=y`，仅DT的`rockchip-suspend`节点disabled；没有声称系统休眠被彻底移除。
首轮设计不调用suspend/reboot/poweroff；2026-10-04完成的是RAM-only guard后的SysRq即时复位，
PMIC和TCS的普通关机路径也可能改变电源状态，仍需独立验收。
原厂关机已观察到 MCU 看门狗与断电标志日志；写入是否被 MCU 接收及物理断电尚未验证。
首次启动前还须核对 MCU 遗留看门狗状态，详见[电源生命周期适配](POWER-LIFECYCLE.md)。

原内存范围、memreserve来自一次Android启动，不能当作独立确认的loader/DDR/BL31契约。
没有把原initrd地址、序列号、MAC、Android分区root或运行时DTB加载地址写入新板级文件。
后续必须检查bootloader如何修正`/memory`和chosen，以及Image/initramfs/DTB加载范围是否重叠。
首轮命令行选择`rdinit=/init`，后续已生成最小initramfs；`ro`本身也不能保证任意用户态不写块设备。

## 后续外设按证据恢复

|部分|可复用代码/已取得输入|仍需做的工作|
|---|---|---|
|720×720屏幕|独立DT、panel错误传播和真实DSI host测试；排线断开/亮度0时74项接口、180命令完成与正常重启已板测|实际画面/面板ACK、电气背光、显示应用与suspend/resume待验；软件connected不证明实物|
|RK809音频|GPL codec外部模块、独立DTB/MIT ALSA工具已RAM板测；14控件和双向48k/S16/2ch参数配置/释放/关闭通过，路径OFF/MIC OFF|PREPARE、帧/DMA、声学/功放电平、退出/休眠待验；0009 mute错误与sticky修正仅离线，ASoC/PCM/DMA错误链继续处理|
|USB麦克风|snd-usb-audio；Android和源码Linux实测8声道16kHz S16_LE枚举一致|本轮未录音；各通道意义、音质和应用链待验|
|Wi-Fi/BT|独立Wi-Fi/RNG DTS、源码BCMDHD/WPA已板测；实际请求AP6256/BCM43456c5固件，DT原字符串ap6398s保留|PM0+仅5GHz条件下64KiB电脑TCP三端SHA通过；默认/仅PM0失败，重连未验收；BT未恢复，firmware仍为二进制|
|MXC6655|GPL驱动错误传播已修；外部模块与I2C5/@15新DTB已板测，当前Image的SENSOR_DEVICE仍n|Android与Linux WHO均ENXIO，Linux不再留假绑定；芯片实装/供电待查，ID05、默认OFF、采样/方向与卸载未验；不是已证六轴IMU|
|CAP1188 SPI|原Android八路接口已采集；开源SPI身份工具和独立M1/HS DTB已RAM板测|FD/FE均00，尚未验芯片身份；无reset/init/input事件，硬件供电/连线待测；cap11xx仍只有I2C|
|OV5695|驱动和IQ文件名、2-lane通路已有|原Android未绑定，先排查实装/供电/ID；IQ与ISP用户态版本需匹配|
|GD32参考接口|Android ttySMT0与源码Linux ttyS0均fdd50000 UART0；驱动/pinmux已板测，codec/PTY通过|未开物理TTY/接电机；真实GD32连接、返回帧、使能/停止/watchdog仍待验证|

2026-10-04新增UART0候选只改已板测RNG DT的UART0/status；同Image配新版RAM initramfs已返回Android，
启动分区/旧rootfs完整SHA不变。新BusyBox的模块参数真实生效；USB麦克风仅枚举元数据通过。
完整参考168项源码及升级输入来源已审查，仍无可信停止/使能/反馈契约。
原始日志、构建故障检查和明确边界见[电机接口与RAM新版实测](../../../../outputs/rk3568-motor-alignment-20261004/README.md)，
剩余外设具体依赖见[下一轮源码证据](../../../../outputs/rk3568-motor-alignment-20261004/NEXT-PERIPHERALS.md)。

同日加速度计独立RAM对照完成：0005修正I2C/ID/init/probe/class失败传播，72真实函数检查通过，
同Image ABI构建的两个外部模块实际加载；新DTB151检查/13故障拒绝，只15属性变化。
原Android的驱动绑定并未带来gsensor输入；按精确原Image的24byte I2C消息布局读WHO也ENXIO。
Linux probe -6且无假绑定，未进入初始化，未验默认OFF/采样/方向；保留模块直到SysRq返回Android。
五启动分区/source rootfs前后SHA一致，network rootfs与此前基线一致，未刷写或操作电机。
身份读取失败与实物根因单列于[加速度计源码与两系统记录](../../../../outputs/rk3568-accelerometer-20261004/README.md)。

同日CAP1188独立RAM诊断完成：151项DT审计/15坏DTB拒绝，只10属性变化、保留760旧phandle，
SPI3 normal/HS均为M1且只CS0，I2C5继续禁用。同Image/ABI不变，MIT工具以mode3/100k执行三帧FD/FE/FF。
产品/厂商均00，SPI messages0→3且控制器errors/timeouts0；零错误不是芯片应答，身份未验收。
事务后实机为spi3-hs/M1，reset GPIO0B6及CS1未占用；无reset、初始化或CAP input注册，UART0 TX/RX0。
stage18项/return guard25项实际脚本fixture和精确52app BusyBox通过，释放cache/debugfs后349.427961秒SysRq返回Android。
五启动分区和两份旧rootfs本轮前后完整SHA一致，最后电量30%；未提交/推送或正常poweroff验收。
身份不符和原厂驱动有界静态问题见[CAP1188源码与实机记录](../../../../outputs/rk3568-cap1188-20261004/README.md)。

2026-10-05板载音频接口独立RAM测试通过：同Image/ABI，0006补齐所覆盖probe/reset错误传播，
借用PMIC原regmap且不释放；73真实函数host/QEMU检查、模块32项导入闭合，原内核树保持干净。
最小audio DTB177审计/23坏DTB拒绝，29属性变化；14控件和三目标ENUM快照通过，未打开PCM或改控件。
实际I2S1五条pinmux、MCLK12.288MHz、gpio148 out hi ACTIVE LOW均是软件诊断，不代替电气测量。
codec DMA mask提示来自OF配置，未阻断接口注册；PCM DMA仍未验。模块引用1保留到SysRq，
释放持久挂载/FD后147.271085秒回Android；七项完整SHA不变，返回后电量7%仅为历史快照。
证据与后续音频边界见[RK809源码接口实测](../../../../outputs/rk3568-audio-20261005/README.md)。

## 没有原厂 BSP 时的启动路线

推荐以保留现有loader/DDR/信任固件为第一选择，先备份与解析原boot、dtbo、uboot/trust等启动输入，
检查是否支持保留启动分区的RAM加载或外部介质。后续15项启动备份已回传并校验，
原4.19和源码5.10均已通过U-Boot RAM启动再返回Android；未执行解锁、AVB修改或loader替换。
无法拿到原厂可恢复镜像时，读取本机启动分区仍有价值，但备份可读不等于已经验证恢复过程。

公开U-Boot已经支持RK3568，Rockchip提供rkbin中的DDR/BL31等二进制，
说明不必从零编写SoC启动固件；仍需按本板内存/启动链选择，不能直接刷通用EVB loader：
[U-Boot官方RK3568支持](https://docs.u-boot.org/en/latest/board/rockchip/rockchip.html)、
[Rockchip rkbin](https://github.com/rockchip-linux/rkbin)。

另一条可单独评估的路线是复用原4.19内核配Linux initramfs/rootfs，减少第一次切换变量。
现有配置有initramfs支持，但这不证明Android启动参数、安全策略与用户态依赖已兼容，不能直接宣称换rootfs就能启动。

最终目标仍是可维护的Linux板级支持；首轮离线重建已推进到源码内核基础启动，外设业务与完整生命周期仍需验收。
# 2026-09-28 后续：Image 与 initramfs 已生成

首次完整 Image 构建已经通过，ARM64 initramfs shell 已经用户态 QEMU 验证。
本轮实际需要 PREEMPT_RT 配置和 `patches/0001-arm64-cache-kasan-include.patch`，
用于解决锁定厂商源码的非 RT 热插拔缺失函数及 RT 头文件循环。
完整配置、失败日志、成功日志和产物摘要见
[启动准备记录](../../../../outputs/rk3568-boot-preparation-20260928/README.md)。
这里的旧验证结果保留为首轮历史；新 Image 不能冒称使用未修改的厂商原树。
此段记录2026-09-28当时尚未上板的历史；最新源码5.10实机结果见上述2026-10-04记录。
USB裸机恢复入口仍未实测，本次没有刷写启动分区。

## 2026-10-05 原生根交接与 Android RAM 启动包

原生PID1 v3已在源码5.10内核完成只读loop根、自有纯软件测试子进程回收、原生回RAM/卸载/detach，
独立guard通过后普通reboot返回原Android，七保护输入完整SHA前后相同。原生创建52个BusyBox链接，
v2的人工协助记录保留为历史；详见[PID1实测](../../../../outputs/rk3568-pid1-20261005/BOARD-RESULTS.md)。

锁定官方AOSP源码重建原40MiB boot包逐字节一致；实际单地址RAM bootm触发本机Android hook，
从RAM RSCE选择3568a_v20、hash/overlay通过，回到原Android。26项现场汇总通过，
详见[原包RAM启动](../../../../outputs/rk3568-bootm-ram-20261005/README.md)。
这只验证CLI可达时原包的内存启动；正式flash和USB恢复入口仍未验收。
Linux候选v1只载入/CRC、未启动；v2补chosen symbol及phandle后，第一次RAM bootm进入Linux却丢最终overlay。
部署版二进制确认另设FDT地址触发第二次资源DT读取；第二次相同v2包恢复临时FDT A100000，
完整最终树958节点/4891属性及overlay保留通过独立审查，native PID1自检/原生RAM返回和普通重启完成。
[最新71/71汇总](../../../../outputs/rk3568-bootm-ram-20261005/linux-candidate-result-v3.json)绑定全包、最终树、
实际原始流及Android七保护输入完整SHA，电量62→60%。第一次65/71失败保持。
早期RSCE/PMIC/显示仍来自原eMMC启动输入，正式包/USB恢复和全部外设/生产服务尚未验收。
内存booti通过不能自动覆盖Android bootm的处理分支，也不能作为正式迁移完成的依据。
