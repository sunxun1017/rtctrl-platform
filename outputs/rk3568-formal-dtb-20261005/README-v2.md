# 今日实际音频 DT 的有限 eMMC 兼容串候选 v2

v2 唯一输入是今天实际使用的 overlay 后 Linux树 `outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/applied-audit-only.dtb`，163285B/SHA `4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f`。旧v1的9cf基线、工具、sealed-v1及结果保留。

只在 `/sdhci@fe310000:compatible` 末尾追加 `snps,dwcmshc-sdhci`，保持 `rockchip,rk3568-dwcmshc` 第一项和原 `rockchip,dwcmshc-sdhci` fallback。候选 `build/emmc-v2/audio-emmc-compatible.dtb` 为163305B/SHA `5c09084fe0d456953d228cdd811b53ddca8fc74f0963a2fe00820e70265f8b72`。

旧工具仅另立BASE路径/SHA/长度与新版输出；OF matcher 的tested-baseline向量改为实际读取今天基线DT的compatible属性。既有算法、真实Linux函数/表、21坏树和验证边界保持，没有扩大审计框架。

- 真实锁定libfdt三次结果相同，完整962节点/4886属性/762phandle，仅compatible一项变化；其余USB、电源、音频、chosen、phandle、reservation/启动CPU/版本字段完全保持。没有混入USB-device-v2或电池候选。
- 新基线实际被部署U-Boot匹配串要求拒绝；首次红例WSL launcher超时未进入脚本，原工具输出存于 `build/wsl-launch-failure-v2.json`，重试的真正红结果在 `build/baseline-red-v2-retry`。
- `build/audit-green-v2` 的21个真实坏DTB全部拒绝，保留旧框架的串顺序/缺失/NUL/重复、其它属性/USB/供电/chosen/phandle/reserve/格式异常用例。
- 四次实际DTC exit0，完整往返语义相同；`build/dtc-warning-audit-v2` 重新核原流SHA，路径归一化后解码和编码diagnostics均逐字相同，零新增。不是零警告声明。
- `build/linux-match-v2` 抽取真实 `of_prop_next_string`、`__of_device_is_compatible`、`__of_match_node` 及实际eMMC表，host与ASan/UBSan各7/7。实际新基线与候选都选择rk3568_drvdata；generic放首项会选择generic数据的负对照也执行。模型只提供node/property读取，没有执行probe/MMIO/eMMC I/O。

19份版本输入与实际工具/源码绑定；新版封存逐SHA复核旧sealed-v1的84文件及原工具/结果未改变。本任务未重启WSL服务或修改TUN、网络、板子、kernel/config、公共patch、音频包或项目记忆。

仍只是offline共享DT兼容候选，formal_flash_ready=false、early_dm_tested=false、emmc_probe_io_tested=false、usb_recovery_tested=false。这里采用overlay后树不代表pre-overlay包准备完整、部署U-Boot DM重建可行、AVB/分区加载或恢复已验证；没有Image或正式包，也不改变当前音频下一版使用的已测DT。

复跑仍使用新的输出目录：新版工具为 `build-emmc-bridge-v2.py`、`test-emmc-bridge-v2.py`、`verify-dtc-warnings-v2.py`、`check-linux-match-v2.py`，参数接口沿用旧README。最后由主控独立复核并决定后续整合。
