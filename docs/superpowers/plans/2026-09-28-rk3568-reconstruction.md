# RK3568 无原厂 BSP 重建实施记录

> 按 rtctrl-dev 执行；主 agent 实现并验证，独立硬件 agent 核对电源和驱动证据。

**Goal:** 在项目内形成可重现编译的首轮 Linux 5.10.160 板级 DTS 候选，不生成未经验证的刷机配置。

**Architecture:** 使用已锁定公开内核的 RK3568 SoC DTSI，重新表达原机供电、IO 电压、存储和 USB 接线。
板级数据位于 `platforms/rk3568/boards/aiot-3568pq/bsp/`；核心、业务与原有用户修改保持独立。

**Tech Stack:** Linux 5.10.160 commit `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`，DTS/CPP/DTC，已有 prepare-linux-config.py。

**依据:** `outputs/android-board-20260928/README.md`、经 SHA-256 验证的原机 FDT；用户已授权写入项目。

## 本轮范围

- [x] 建立重建说明和驱动可复用/缺口表，修正板卡说明中过时的“没有原机资料”。
- [x] 重建首轮 DTS 和电源片段：原机供电/pinctrl/IO-domain，原机内存范围和保留项，FIQ 调试串口，低速 eMMC，USB2 host。
- [x] 新建独立 firstboot 配置输入，不覆盖之前按框图制作的全功能候选；CPU/DDR DVFS、充电、PD、MCU串口、传感器、摄像头和显示首轮不启用。
- [x] 用真实 CPP/DTC 编译，检查 phandle、供电电压、内存保留、启动参数和禁用项；输出命令/日志/哈希和 non-deployable 清单。
- [x] 配置生成/审计；编译相关板级驱动对象，独立审查，更新项目记忆。

实际编译补充：该BSP的eMMC驱动将runtime PM函数置于CONFIG_PM_SLEEP条件中，因此保留CONFIG_SUSPEND=y以满足编译；
仅DTS的rockchip-suspend保持disabled，系统休眠功能不能宣称被全局移除，首轮禁止触发休眠。

## 重点检查

IO-domain vccio4/vccio6必须引用1.8V；RK809 LDO4为3.1V；PMIC sleep引脚pull配置以原机为准。
不复制4.19的SoC时钟编号和控制器compatible覆盖5.10定义；不导入原机serial/MAC/Android bootargs。
eMMC首轮降至52MHz，保留5.10控制器reset定义；UART0不打开，USB不虚构5V使能GPIO。
首轮仅允许initramfs根，不写死Android分区root；loader、DDR、BL31、boot镜像格式/AVB、恢复路径尚未验证。
原机memreserve及内存布局是本次启动快照，必须在未来启动前核对loader fixup与加载地址，不能声称已完成启动链。

## 验证界限

编译与配置/节点审计是本轮验收。没有原厂源码不再是阻止离线重建的条件。
不承诺DDR训练、闭源固件、CAP1188厂商阈值或GD32安全协议可由设备树推断。
本轮不向板端部署，不重启，不刷机；第一轮真正启动前仍须建立恢复路径和可用的启动链输入。
