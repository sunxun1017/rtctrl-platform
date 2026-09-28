# RK3568 无原厂 BSP 重建：离线验证记录

用户明确无法取得原厂BSP，并授权将重建内容写入项目。本轮产物为可维护的板级DTS候选、独立配置、
可复现编译/审计入口和驱动缺口说明；没有连接板卡或部署镜像。

源码入口：[重建说明](../../platforms/rk3568/boards/aiot-3568pq/RECONSTRUCTION.md)。
原机依据：[串口采集记录](../android-board-20260928/README.md)。

## 最终结果

|检查|结果|证据|
|---|---|---|
|内核源码|锁定5.10.160，commit 9f9e9d18574d0914c0d192a90c3babfe1fd63c95，未改third_party|manifest.json|
|配置生成/prepare/modules_prepare|90项配置要求通过|configure-final.log、config-audit-final.log、kernel-config-manifest.json|
|CPP/DTC/反编译|通过；20条既有SoC警告，新增板级警告0|dtc.log、baseline-dtc.log、firstboot.compiled.dts|
|编译后DTB审计|49项通过|audit.json|
|供电原始证据对照|198项属性/符号引用与原FDT一致|power-comparison.json、compare-power-evidence.py|
|审计故障注入|8项通过：含IO电压、eMMC高速、CSI2、MCU串口、分区root、内存保留等错误拒绝|fault-tests-final.log|
|拒绝覆盖旧输出|返回2，现有产物哈希均未改变|nonempty-output-refused.log、final-checks.json|
|驱动对象交叉编译|10个对象成功，检查全部为ELF64 AArch64|driver-objects-final.log、object-manifest.json|
|独立只读审查|发现默认CSI2启用，已修复并复核；最终未报告新增具体问题|见下方审查处理|

可下载/检查的[DTB](rk3568-aiot-3568pq-firstboot.dtb)、[可读编译结果](firstboot.compiled.dts)和
[配置](firstboot.config)仅用于审查。`manifest.json`明确`deployable=false`、`image_built=false`、`board_boot_tested=false`。
没有生成完整Image、initramfs、模块包或刷机镜像。配置工具的清单仍记录它自身不生成DTB，独立DTB产物以本目录manifest为准。

## 最终执行命令

以下从仓库根目录在WSL执行，输出目录非空时应改用新名字，不删旧证据：

```sh
python3 scripts/prepare-linux-config.py \
  --candidate platforms/rk3568/boards/aiot-3568pq/firstboot-candidate.json \
  --output .deps/kernel/aiot-3568pq-firstboot-final-config --prepare-headers

python3 platforms/rk3568/boards/aiot-3568pq/build-firstboot.py \
  --kernel third_party/linux-rk3588 \
  --dtc .deps/kernel/aiot-3568pq-final/scripts/dtc/dtc \
  --output .deps/kernel/aiot-3568pq-firstboot-final-dtb-v2

PATH="$PWD/.deps/host-tools/bin:$PATH" make -C third_party/linux-rk3588 \
  O="$PWD/.deps/kernel/aiot-3568pq-firstboot-final-config" \
  ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j8 \
  drivers/mfd/rk808.o drivers/regulator/fan53555.o \
  drivers/regulator/rk808-regulator.o drivers/soc/rockchip/io-domain.o \
  drivers/mmc/host/sdhci-of-dwcmshc.o drivers/usb/host/ehci-platform.o \
  drivers/usb/host/ohci-platform.o drivers/phy/rockchip/phy-rockchip-inno-usb2.o \
  drivers/soc/rockchip/fiq_debugger/rk_fiq_debugger.o drivers/thermal/rockchip_thermal.o

python3 outputs/rk3568-reconstruction-20260928/compare-power-evidence.py \
  .deps/kernel/aiot-3568pq-firstboot-final-dtb-v2/rk3568-aiot-3568pq-firstboot.dtb
python3 outputs/rk3568-reconstruction-20260928/finalize-evidence.py
```

CPP/DTC准确argv和输出重定向保存在[commands.json](commands.json)、[commands.sh](commands.sh)；
最终测试/配置审计/拒绝覆盖命令见[final-check-commands.json](final-check-commands.json)。
最终主机结果为[final-checks.json](final-checks.json)，关键文件哈希为[SHA256SUMS](SHA256SUMS)。
这些脚本不操作串口、网络、分区或板端硬件。

## 调整、失败与审查处理

1. 第一次SUSPEND=n配置生成成功，但真实eMMC对象编译失败；错误是runtime PM函数位于CONFIG_PM_SLEEP条件块内。
   原日志保留在driver-objects.log；保留SUSPEND=y后v2和final对象编译通过，日志分别保留。
   原BSP源码未修改。DT rockchip-suspend仍disabled，但不宣称系统休眠能力完全不存在。
2. 裸rk3568.dtsi基线单独编译时缺少板级vdd_logic标签。基线专用DTS加入无属性的标签占位以检查SoC警告，
   实际候选使用完整原板电源描述；基线占位从未进入候选DTB。
3. 初期尝试DTC的`-O fs`发现该工具只支持fs输入，不支持fs输出；改为直接解析编译后的DTB，保留完整memreserve校验。
   该尝试日志位于`.deps/kernel/aiot-3568pq-dtb-firstboot/export.log`。
4. 审查发现SoC默认启用mipi_csi2_hw，而CIF配置会让它probe，超出首轮范围；显式关闭并加入审计/故障注入。
   同时关闭display-subsystem避免无VOP时的无效probe，关闭板载codec配置，保留USB音频。
5. 供电对照排除的是未引用的SoC原有pmic-pins组；四个实际重建的PMIC pin组均逐值/符号比较，没有忽略它们。

## 尚未验证

loader/DDR/BL31、原boot镜像格式和AVB行为、可恢复分区备份、RAM/外部介质启动路径、实际内存fixup均未核实。
没有执行板端上电、eMMC读写、USB录音或外设功能验收。
`regulator-init-microvolt`不能作为目标驱动实际设压证据；电源/IO域必须在未来首启时读回。
CAP1188 SPI驱动、显示片段、Wi-Fi固件选择、传感器读数、摄像头失败原因和GD32安全协议仍是后续工作。
本次没有运行无关C++全仓测试；验证对象是新板级DTS、配置及实际相关内核驱动构建目标。
# Git 留存范围

Git 保存源码关联报告、文本日志、配置、审计清单与摘要。生成 DTB/DTS 仅保留本地；原 FDT 等上游证据也不随 Git 分发。
新克隆需按命令重建产物，并取得原采集包才能重做供电对照；文内本地证据链接不表示所有原始文件已入 Git。
