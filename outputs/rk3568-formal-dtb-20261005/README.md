# 有限共享设备树兼容候选

已完成 eMMC 兼容串的离线候选和 USB 依赖核查。候选只在已验证 audio DT 的 `/sdhci@fe310000:compatible` 末尾追加 `snps,dwcmshc-sdhci`，保留 `rockchip,rk3568-dwcmshc` 首项和原 Rockchip fallback。

| 项目 | 实际结果 |
|---|---|
| 输入 audio DT | 163161B；SHA `9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478` |
| 候选 `build/emmc-v1/audio-emmc-compatible.dtb` | 163181B；SHA `cb3028a4dab33596532557ef59ea8fc99d1517c2474f2816900238ce53cdd279` |
| 真实 libfdt 生成 | 三次字节/SHA 相同；使用锁定 libfdt `.so` |
| 完整树比较 | 962 节点、4883 属性、761 phandle；仅 compatible 一项变化，所有其余节点/属性/phandle/reserve/metadata 相同 |
| DTC | baseline/candidate 解码和重新编码均 exit0；往返完整语义相同，实际上重新编码字节也相同；路径归一化后解码和编码 diagnostics 均相同，没有新增警告 |
| 红例 | 原 audio tree 被明确拒绝：缺部署 U-Boot eMMC 匹配串 |
| 坏 DTB | 21/21 拒绝；包含 generic 放首项、漏 RK3568、无 NUL、重复/额外串、status/clock/reset/phandle/USB/供电/chosen/reserve 改动及截断/坏头/尾部 |
| USB 图 | 原 42 节点、候选 41 节点；按 provider 参数、PIPE domain15/PM QoS、供电关系归一化，当前图引用可解析 |

部署 U-Boot 的 eMMC 匹配对象依据主控已确认的 `../rk3568-boot-package-20261005/FORMAL-EARLY-REVIEW.md`：driver `0xb210d0`、oftable `0xae93f8`、probe `0xa4f198` 使用 `snps,dwcmshc-sdhci`。本任务没有重新审整个二进制。

Linux `sdhci-of-dwcmshc.c:536` 的真实表中 RK3568 指向 `rk3568_drvdata`，generic 指向 `dwcmshc_drvdata`；`drivers/of/base.c:484` 与1082的实际评分/择优按 compatible 的位置给早项更高分。`check-linux-match.py` 提取真实 `of_prop_next_string`、`__of_device_is_compatible`、`__of_match_node` 和实际 eMMC 表，在宿主及 ASan/UBSan 各7/7向量执行通过。候选和旧audio基线确实都选择 RK3568 数据；通用项放首位的负对照改选 generic 数据，只有原 Rockchip 泛串则不匹配。模型只提供 node/property读取，未执行 eMMC probe/MMIO/I/O；实际argv、日志、生成C、ELF与输入SHA见 `build/linux-match-v1/`。

一度从 UNC 工作目录启动 WSL 返回 `Wsl/Service/0x8007274c`，未进入编译；失败启动记录保留在 `build/wsl-launch-failure-v1.json`。后按主控已验证的方式把 Windows 启动工作目录设为 `C:\`，同时显式指定 Linux 工作目录，立即完成上述真实 matcher 编译与测试。WSL/TUN/网络未由本任务修改。USB 图及源码快照使用已有 Windows Python 完成。

本候选保持所有 USB状态、供电、GPIO、MCU/执行器配置，且没有增加 chosen overlay 前提。正式共享包若采用原 DTBO overlay，仍需按新树实际空闲 phandle 单独追加并重审 chosen symbol/phandle，与主控 audio RAM shim 的2fa用途协调。本目录没有 Image、boot/recovery 刷写包、板端传输、启动或分区写操作。

USB 的最小明确后续范围与未验证条件见 [USB-DEPENDENCIES.md](USB-DEPENDENCIES.md)。仍需确认真实 OTG 数据脚/VBUS/ID、部署恢复路径、共享 DT 的早期 DM/eMMC/USB闭包，解决内建 Linux USB链激活方式，之后才能做默认地址 RAM 试验和可恢复的正式入口验证。板上电前 DM重建、AVB分区加载、USB恢复、电气/声学/显示、MCU安全契约仍未因此完成。

复现均使用新输出目录：

```sh
python3 outputs/rk3568-formal-dtb-20261005/build-emmc-bridge.py \
    --out outputs/rk3568-formal-dtb-20261005/build/emmc-next

python3 outputs/rk3568-formal-dtb-20261005/test-emmc-bridge.py \
    --candidate outputs/rk3568-formal-dtb-20261005/build/emmc-next/audio-emmc-compatible.dtb \
    --out outputs/rk3568-formal-dtb-20261005/build/audit-next \
    --boundaries

python3 outputs/rk3568-formal-dtb-20261005/audit-usb-closure.py \
    --candidate outputs/rk3568-formal-dtb-20261005/build/emmc-next/audio-emmc-compatible.dtb \
    --out outputs/rk3568-formal-dtb-20261005/build/usb-closure-next

python3 outputs/rk3568-formal-dtb-20261005/verify-dtc-warnings.py \
    --build outputs/rk3568-formal-dtb-20261005/build/emmc-next \
    --out outputs/rk3568-formal-dtb-20261005/build/dtc-warning-next
```

本轮结果：`build/emmc-v1/manifest.json`、`build/baseline-red-v1/result.json`、`build/audit-green-v1/result.json`、`build/dtc-warning-audit-v1/result.json`、`build/linux-match-v1/result.json`、`build/usb-closure-v3/result.json`、`build/usb-source-v1/result.json`。原节点解析诊断、旧不完整图和失败启动记录均保留，不混入已通过计数。
