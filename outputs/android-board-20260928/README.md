# Android RK3568 板卡只读采集记录

本次已通过串口读取并校验设备树、内核配置和外设枚举资料，供后续 Linux BSP 移植使用。
没有刷机、重启、改变SELinux、改变内核日志等级、发送MCU指令、主动采音或打开摄像头。
板端仅新增临时采集目录 `/data/local/tmp/rtctrl-hw-20260928`，含采集脚本、资料副本及压缩包，保留以便复核。

## 文档入口

- [命令与原始输出索引](commands-and-outputs.md)：每条串口命令、输出文本、原始字节，包含失败与重试。
- [设备树逐项分析](device-tree-review.md)：显示、摄像头、音频、Wi-Fi/BT、传感器及串口的节点和引脚。
- [原始FDT](fdt.dtb) / [可读DTS](android-running.dts)：**后续分析优先保留原始FDT**。
- [完整运行时树](live-tree/) / [运行时树DTS](android-live-tree.dts)。
- [内核配置](kernel.config)、[板端资料包](hardware-bundle.tar.gz)、[解包后的外设资料](bundle/extra/)。
- [完整性验证](verification.json)、[传输逐块校验](transfer-verification.tsv)、[主机处理日志](host-verification.log)。

## 已核实的板卡身份

|项目|本次结果|
|---|---|
|串口|COM6，CH340，1500000 baud，8N1，无流控，DTR/RTS=false|
|型号/SoC|3568A；compatible为rockchip,rk3568-evb1-ddr4-v10、rockchip,rk3568|
|系统|Android 11 / API 30；ShimetaOS/rk3568，userdebug|
|内核|4.19.232 #49 SMP PREEMPT，构建时间Thu Mar 12 15:55:49 CST 2026，aarch64|
|内存|MemTotal=3802460 kB；这是内核可见总量，不是芯片容量测量|
|权限|初始shell uid2000；`su 0`可执行root只读采集；SELinux原本Permissive|
|内核配置|6197行，CONFIG_PREEMPT=y，CONFIG_HZ_300=y|

此前仓库的Linux 5.10.160是离线候选，**本次原机运行的是4.19.232**。不能把候选构建结果当成本机兼容性证明。
Windows采集日志记录2026-09-28下午；WSL工具记录2026-09-29凌晨，两侧时钟存在约8小时差异；Android文件日期还显示2017。
保留各端原始时间，没有修改任何时钟。目录日期沿用任务日期，排序优先使用步骤编号和板端内核uptime。

## 描述与实际绑定对照

|部分|本次运行时结果|证据与边界|
|---|---|---|
|显示|card0-DSI-1 connected，模式720x720；背光127/255|extra/display.txt；只读枚举，没有目视/触屏功能测试|
|CAP1188|spi3.0绑定cap1188；cap1188_input注册event0|extra/buses.txt、input.txt；证明绑定/输入设备存在，未读触摸事件验证每通道|
|屏触摸|goodix gt9xx I2C1@14存在，但无driver链接，input清单无Goodix|不能把设备树okay当作触屏可用|
|IMU|I2C5@15绑定gsensor_mxc6655；I2C3@68 rjgt102无driver链接|未证明SH3001实装；绑定不等于传感器读数通过|
|摄像头|OV5695 I2C2@36无driver链接；vm149c已绑定；存在ISP视频节点|未发现OV5695 sensor子设备，不能声称摄像头正常；未主动采帧|
|USB音频|Bothlent UAC Dongle，VID:PID=1d6b:a4a6，绑定snd-usb-audio；card0 capture|18补采显示S16_LE、8声道、16000Hz，当前Stop；未采音。USB名称不能单独证明内部芯片型号|
|板载音频|card1 rockchip,rk809-codec，有播放与录音PCM|extra/audio.txt；未播放测试音|
|Wi-Fi|SDIO 02d0:a9bf，function1/2绑定bcmsdh_sdmmc；bcmdhd模块已加载|DT声明ap6398s，与旧框图AP6256不同；实际模组料号还需硬件/固件对应证据；未连接网络|
|UART0|/dev/ttySMT0→fdd50000.serial|extra/serial.txt；该厂商使用ttySMT命名，不能沿用/dev/ttyS0；没有验证GD32连接或协议|
|蓝牙串口|/dev/ttyS1是/dev/ttySMT1链接|已保存映射，未启动/配对测试|
|供电|rk809→rk808；bq25703→bq25700-charger；tcs452x→fan53555-regulator|extra/buses.txt；保存实际绑定名以匹配BSP驱动|
|分区|eMMC mmcblk2，boot/dtbo/recovery/super等名称及起点/大小已保存|extra/partitions.txt；**只读布局，未备份完整分区镜像**|

## 完整性与例外

原始FDT为151680字节，SHA-256：

```text
a028987f730f3c8e4be9cb6e771b91a5665932712c51e1e540b96654de4dd28b
```

资料包为362916字节，SHA-256：

```text
61293bdd27721122e9b5a2b1a21d794ffb1f899534330288f89249a60cbb1c47
```

以上均与板端一致。资料包按8192字节分块，每块独立核对SHA-256，重组后再次核对整包。
采集脚本上传也与主机SHA-256一致。gzip校验、tar解包与DTC解析成功。
完整live-tree归档包含6276个条目，tar错误文件为空。

FDT与运行时树经过DTC排序后，节点/属性文本一致；唯一差异是运行时sysfs树不带FDT头部的两个`/memreserve/`项：
`0xa100000/0x25000`、`0xa200000/0xc8c20`。见[live-tree-diff.txt](live-tree-diff.txt)。
因此`sorted_fdt_equals_live_tree=false`不代表采集损坏，也不能仅用sysfs树代替完整原始FDT。

DTC反编译有26条警告，原样保留在[dtc-warnings.txt](dtc-warnings.txt)，没有修改设备树来隐藏警告。
反编译不恢复原厂源文件、include、宏与注释；得到的DTS还不能直接作为新内核可启动板级文件。

已有逐文件采集器在该Android上速度较慢，约1960行status后主动Ctrl-C停止，`bundle/snapshot/devicetree`明确为不完整副本。
后续改用tar保存完整运行时树，完整结果是`live-tree/`；snapshot中的原始FDT和config.gz已验证可用。
`bundle/extra/status.tsv`的modules/firmware-list返回1，原因包括查询了不存在的候选目录，已有模块/文件列表保留；不能据此称所有目录完整取得。
当前dmesg环形缓冲区最早约uptime405秒，未包含完整上电启动日志；没有为补日志重启设备。
固件/IQ目录仅列清单，没有备份整个固件、IQ或Android用户分区。

## 接下来移植所需资料

优先获得本机对应4.19.232厂商内核源码/补丁，特别是CAP1188 SPI、MXC6655、面板初始化、音频路由及ttySMT修改；再逐项对照目标Linux BSP绑定。
保留本次显示参数、供电/pinctrl、USB声卡格式及UART0映射作为已核实输入。
摄像头与RJGT102/Goodix未绑定的原因、真实模组料号、GD32安全协议及完整可恢复固件仍未确认。
本次没有生成或部署Linux镜像，没有完成移植启动或外设功能验收。
# Git 留存范围

Git 保存本目录报告、采集/核验脚本与摘要。原始 FDT、运行树、设备标识、串口流、工具二进制和归档仅保留本地，未删除。
下文及命令索引中的原始证据链接依赖本地采集目录；新克隆需取得对应原始包才能重新核验，Git 并不包含完整原机备份。
