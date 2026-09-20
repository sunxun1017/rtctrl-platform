# AIoT-3568PQ Linux 适配候选

本轮目标：以 Linux 为产品路线，先完成可离线验证的 BSP 配置和证据采集工具。
用户要求业务、核心模块和通用工具不依赖具体硬件；设备差异放在可替换适配器及配置数据中。
目前只有《帕奇硬件框图.pdf》三页，尚无原机设备树、原厂 BSP 或板端访问。
因此这里是 `kernel-candidate.json`，尚不是部署用 `profile.env`。

## 平台边界

| 层 | 职责 | 换硬件时的变化 |
| --- | --- | --- |
| `modules/` | 控制、状态、安全、采集/推理及传输契约 | 保持通用，不读取板名、GPIO 或厂商 SDK |
| `adapters/` | POSIX 串口、V4L2、ALSA、推理后端及设备协议实现 | 按能力替换叶子实现；芯片型号不进入业务 |
| `apps/`、`products/` | 产品组合、配置及生命周期 | 选择适配器，处理能力缺失 |
| Linux 芯片驱动 | 芯片寄存器、总线事务、电源生命周期 | CAP1188 SPI、SH3001 等实现应可跨板复用 |
| `platforms/<soc>/boards/<board>/` | 内核版本、驱动选项、设备树及固件映射 | 放置实际接线、板级数据与证据 |
| `scripts/prepare-linux-config.py` | 读取显式候选数据，生成并审计配置 | 没有板名、SoC、架构和 RT 策略特判 |

现有 Linux 标准接口可作为适配边界：输入事件用 evdev，音频用 ALSA，摄像头用
V4L2，显示用 DRM/KMS；未来 IMU 驱动优先输出 IIO。这里只给出接入方向，
不把尚未实现的 IMU、触摸或显示用户态适配器写成现有功能。
无需为未知芯片先新增一套空的核心接口，也不通过 `#ifdef RK3568` 改业务逻辑。

## 框图与驱动对应

依据：PDF 第 1 页系统框图、第 2 页电源、第 3 页电滑环和接口。
文件 SHA256：`094f83b44b7cf90357664a4a0b34149084ec09937ea895cc2d2a4909d01ded0d`。
下表的连接来自框图，不是实物测量。源码路径相对候选内核树。

| 框图器件 / 路径 | 已核实的 Linux 代码或候选入口 | 仍需确认 |
| --- | --- | --- |
| RK3568 / AIoT-3568PQ | `CPU_RK3568`、RK3568 DTSI 及控制器驱动 | 板版本、RAM/eMMC、DDR loader、启动链 |
| RK809-5，I²C0 | RK808 系列 MFD、regulator、RTC、clock；RK817 codec 匹配 RK809 | 电源树、电压/休眠值、IRQ、声卡路由；电池测量能力还须核原理图 |
| TCS4525，I²C0 | `drivers/regulator/fan53555.c` 含匹配 | 地址、供电和 OPP 电压 |
| BQ25703 / SC8886，I²C0 | `CHARGER_BQ25700` 的 `bq25700_charger.c` 显式匹配两者 | 实装型号、2S 充电参数、采样电阻、CHG_INT/OTG_EN |
| FUSB302，I²C0 | TCPM + `TYPEC_FUSB302` | IRQ、CC/USB角色、VBUS控制和电源策略 |
| TXW400012B0 / NV3051F，DSI 4 lane | Rockchip DRM + 厂商 `panel-simple` 的 DT 初始化序列 | 720×720 的完整 porch/clock/命令序列、DSI实例、reset、电源和背光PWM |
| OV5695 兼容 CSI 2 lane 接口，I²C2 | CIF + ISP V21 + CSI2 DPHY + `VIDEO_OV5695` 候选 | 实装传感器、MCLK、reset/pwdn、电源、IQ文件；兼容接口不证明装的是OV5695 |
| AP6256，SDMMC1 / UART1 | `AP6XXX` vendor DHD；HCI UART/serdev/BCM | 固件、NVRAM、供电/唤醒GPIO、BT附加参数 |
| I²S1 → RK809 → HT366/EUA2310 | Rockchip I2S TDM + RK817 codec + multicodecs声卡 | MCLK、路由、功放使能、左右通道、实际功放型号 |
| BH6080，USB2_HOST3 | USB host + `SND_USB_AUDIO` 候选 | USB描述符是否UAC、采样率、主机实际可见通道及厂商控制协议 |
| ES7243 回声参考 | 位于音频硬件路径，尚未证明由RK3568直接控制 | 主控归属、接口/时钟；不能以ES7243E驱动替代或套用RV1126B的软件AEC延迟 |
| AT24C16B，I²C3 | `EEPROM_AT24` | 基地址及多地址占用、已有内容、写保护策略 |
| SH3001，I²C3 | 当前树未找到匹配驱动 | 官方寄存器资料、ID/地址、中断和方向；后续独立IIO驱动 |
| CAP1188，SPI3，8路触摸 | 现有 `KEYBOARD_CAP11XX` 仅I²C，不能绑定SPI3 | SPI模式/速率、CS/IRQ/reset、键值映射；需可跨板复用的SPI实现 |
| 灯、底部键、Recovery、光感 | GPIO LED / GPIO keys等可选通用驱动 | GPIO或ADC、有效电平、光感实际器件；屏TP预留不当作已装触摸 |
| RK3568 UART0 ↔ GD32 USART1 | 通用串口transport可复用 | 原固件协议、波特率、帧/校验、单位、反馈、停机和watchdog |

GD32 管理 3×TB6612 的六路 PWM/方向、A/B 反馈和限位。TB6612 不是直接挂在
RK3568 I²C/SPI 下的设备，不给 Linux 虚构六路 PWM 引脚。MCU Flash 属于 GD32，
也不新增主控 SPI Flash 节点。UART0 不能直接等同 `/dev/ttyS0`。

图中屏背光规格 40mA 与原图约80mA、逻辑电源二极管后的电压均已标有疑点；
配置文件不补猜测数值。充电/PD、GPIO 和 regulator 的运行状态须由原板资料确认。

## 可复现配置

候选复用仓库锁定的 Orange Pi/Rockchip Linux **5.10.160**，commit
`9f9e9d18574d0914c0d192a90c3babfe1fd63c95`。目录名 `linux-rk3588` 是历史名称，
这棵树实际也含 RK3568 驱动。它是厂商 BSP；用户的 Linux 产品路线不等于已选择上游 mainline。
原板 BSP 到手后重新评估该候选，不复用 Orange Pi 的板级 DTB。

从仓库根目录，在 Linux/WSL 执行（输出须为新目录或空目录）：

```sh
python3 scripts/prepare-linux-config.py \
  --candidate platforms/rk3568/boards/aiot-3568pq/kernel-candidate.json \
  --output .deps/kernel/aiot-3568pq-candidate --prepare-headers

python3 scripts/prepare-linux-config.py \
  --candidate platforms/rk3568/boards/aiot-3568pq/kernel-candidate.json \
  --check-config .deps/kernel/aiot-3568pq-candidate/.config
```

构建顺序为 source/commit校验 → 基础defconfig → 按JSON顺序合并fragment →
olddefconfig → 逐项审计 → 可选prepare/modules_prepare。板级fragment可覆盖SoC默认值。
`arch`、编译器前缀、defconfig及源码pin全由JSON提供；另一平台仅提供另一份候选数据。
工具依赖Python3、make、GCC交叉工具链、flex、bison及目标BSP的构建依赖，
会发现仓库已有 `.deps/host-tools/bin`，不安装系统包。

配置生成失败返回非零。输出非空时拒绝覆盖；修正输入后选择新的输出目录。
最终 `kernel-config-manifest.json` 记录输入/配置SHA256及编译器，明确
`deployable=false`、`dtb=null`。不生成 Image、整包模块、DTB 或刷机文件；
`modules_prepare` 也不提供完整内核链接产生的 Module.symvers。
`--check-config` 只检查片段要求是否满足，不证明该配置的来源、启动或硬件功能。

## 后续补原机信息

通用采集器 `scripts/collect-linux-hardware.sh` 可在Linux或具备相应toybox命令的
Android shell执行，实际Android/SELinux权限尚未验收：

```sh
# 在原机执行；父目录必须已存在，输出目录必须为空或不存在。
sh collect-linux-hardware.sh /data/local/tmp/hardware-snapshot

# 在主机读取已挂载/导出的目标文件树，不把主机uname冒充目标信息。
sh scripts/collect-linux-hardware.sh --root /path/to/exported-root /tmp/hardware-snapshot
```

它保存可读取的fdt、展开设备树、内核配置以及白名单USB/I²C/SPI绑定、ALSA和input信息。
逐项状态在 `status.tsv`，错误在 `errors.log`；返回0为采集完整，1为部分资料缺失/跳过/失败，
2为参数或输出目录被拒绝。仅有DTB时不要求另外提供完整采集目录。
原始DT可能含序列号/MAC，工具只本地保存；USB白名单不含serial。
不会打开串口、麦克风或I²C设备，也不扫描总线、写sysfs、加载模块或发电机命令。

取得设备树后按阶段推进：

1. 核对板型号及电源/时钟/存储，建立真实板级DTS和启动链，先串口启动Linux。
2. 按实际节点启用屏幕、USB音频、网络、摄像头；每项完成枚举、失败恢复和板端验收。
3. 为尚缺的芯片补独立驱动；CAP1188输出input事件、SH3001输出IIO数据，业务只消费通用能力。
4. 结合原MCU协议增加独立codec与执行器适配器，再接产品；先离线协议回放、再禁能握手。
   原有Dynamixel协议不能替代GD32，`open_safe`、队列内急停和MCU watchdog须各有验证。

## 本轮验证

- ARM64 GCC 11.4.0：93项最终配置逐项匹配，prepare/modules_prepare通过。
- 下列7个目标交叉编译通过：`fan53555.o`、`bq25700_charger.o`、`at24.o`、
  `fusb302.o`、`rk817_codec.o`、`ov5695.o`、`8250_dw.o`。
- 输出位于 `.deps/kernel/aiot-3568pq-candidate/`，是离线产物。
  对象文件成功不代表完整Image/模块链接或原板启动；没有真机驱动验收。
- 通用工具的测试及最终仓库验证见 [验证记录](../../../../docs/verification-linux-platform-20260921.md)。

官方接口参考：[Linux CAP11xx binding](https://www.kernel.org/doc/Documentation/devicetree/bindings/input/cap11xx.txt)、
[Microchip CAP1188](https://www.microchip.com/en-us/product/cap1188)。
选项和compatible以本地锁定BSP源码为准，不能只按网上新版本名称配置旧内核。
