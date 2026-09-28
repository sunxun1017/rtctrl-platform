# 无原厂 BSP 的 Linux 重建

可以基于公开 RK3568 内核与原机资料重建板级支持，不再以取得整套原厂 BSP 为前提。
本目录已经有首轮可编译的板级 DTS 候选。它不是刷机包，也尚未经过板端启动。

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
配置关闭CPU调频、充电驱动、FUSB302驱动及板载RK817声卡，USB声卡保留。
通用SoC片段仍编译一些尚未启用的能力；“设备树未启用”不等于内核完全没有这些驱动代码。

## 配置与可复现编译

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
固定regulator描述的是软件供电关系，不代表已经测量输入实际电压。首次启动仍需读回电源与IO域状态。

这版BSP的eMMC驱动把runtime PM函数包在`CONFIG_PM_SLEEP`内，关闭SUSPEND会实际编译失败。
因此配置保留`CONFIG_SUSPEND=y`，仅DT的`rockchip-suspend`节点disabled；没有声称系统休眠被彻底移除。
首轮不调用suspend/reboot/poweroff；PMIC和TCS的关机路径也可能改变电源状态，需独立验收。

原内存范围、memreserve来自一次Android启动，不能当作独立确认的loader/DDR/BL31契约。
没有把原initrd地址、序列号、MAC、Android分区root或运行时DTB加载地址写入新板级文件。
后续必须检查bootloader如何修正`/memory`和chosen，以及Image/initramfs/DTB加载范围是否重叠。
首轮命令行只选择`rdinit=/init`，目前尚未制作initramfs；`ro`本身也不能保证任意用户态不写块设备。

## 后续外设按证据恢复

|部分|可复用代码/已取得输入|仍需做的工作|
|---|---|---|
|720×720屏幕|厂商panel-simple已解析panel-init-sequence；已取得完整时序和命令|重建独立显示片段，核对reset/enable顺序、DRM端点和背光；板测|
|RK809音频|rk817_codec + simple-audio-card；原路由、功放GPIO已导出|恢复板载声卡片段，先静音验证时钟，再测播放/录音|
|USB麦克风|snd-usb-audio；Android确认8声道16kHz S16_LE|Linux枚举和格式验证；各通道意义不能凭数量猜测|
|Wi-Fi/BT|BCMDHD、SDIO路径及唤醒GPIO；DT声明ap6398s|确认实际固件/NVRAM和模组，恢复SDIO/BT片段及用户态加载|
|MXC6655|已有drivers/input/sensors/accel/mxc6655xa.c|选择厂商input接口或以后独立IIO适配；先验证读数/方向；不冒称SH3001|
|CAP1188 SPI|已确认SPI3.0、mode3、100kHz、reset、input注册|当前cap11xx.c只有I2C；需按芯片资料补SPI传输、初始化与事件，原厂阈值/滤波不能由DT还原|
|OV5695|驱动和IQ文件名、2-lane通路已有|原Android未绑定，先排查实装/供电/ID；IQ与ISP用户态版本需匹配|
|GD32|UART0实际/dev/ttySMT0，已有独立协议codec|新Linux设备名重新确认；返回帧、使能/停止/watchdog独立验证，不能推断急停语义|

## 没有原厂 BSP 时的启动路线

推荐以保留现有loader/DDR/信任固件为第一选择，先备份与解析原boot、dtbo、uboot/trust等启动输入，
检查是否支持不改eMMC的RAM加载或外部介质。这里尚未执行分区备份、解锁、AVB修改或loader替换。
无法拿到原厂可恢复镜像时，读取本机启动分区仍有价值，但备份可读不等于已经验证恢复过程。

公开U-Boot已经支持RK3568，Rockchip提供rkbin中的DDR/BL31等二进制，
说明不必从零编写SoC启动固件；仍需按本板内存/启动链选择，不能直接刷通用EVB loader：
[U-Boot官方RK3568支持](https://docs.u-boot.org/en/latest/board/rockchip/rockchip.html)、
[Rockchip rkbin](https://github.com/rockchip-linux/rkbin)。

另一条可单独评估的路线是复用原4.19内核配Linux initramfs/rootfs，减少第一次切换变量。
现有配置有initramfs支持，但这不证明Android启动参数、安全策略与用户态依赖已兼容，不能直接宣称换rootfs就能启动。

最终目标仍是可维护的Linux板级支持；本次完成的是离线重建第一阶段，没有声称整机已移植完成。
# 2026-09-28 后续：Image 与 initramfs 已生成

首次完整 Image 构建已经通过，ARM64 initramfs shell 已经用户态 QEMU 验证。
本轮实际需要 PREEMPT_RT 配置和 `patches/0001-arm64-cache-kasan-include.patch`，
用于解决锁定厂商源码的非 RT 热插拔缺失函数及 RT 头文件循环。
完整配置、失败日志、成功日志和产物摘要见
[启动准备记录](../../../../outputs/rk3568-boot-preparation-20260928/README.md)。
这里的旧验证结果保留为首轮历史；新 Image 不能冒称使用未修改的厂商原树。
当前仍未上板启动，不能刷写。用户确认只有串口，USB 恢复入口待实测。
