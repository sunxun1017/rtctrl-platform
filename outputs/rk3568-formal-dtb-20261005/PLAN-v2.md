# eMMC 有限桥接更新到今日实际 Linux DT

父任务范围仅本目录全新v2工具/输出；旧工具、sealed-v1、源码和结果不改，不操作硬件/网络，不触碰kernel、音频包或记忆。

当前输入为 `outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/applied-audit-only.dtb`，163285B/SHA `4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f`。旧桥接的9cf基线不再作为v2输入。只在 `/sdhci@fe310000:compatible` 保持 RK3568首项和原fallback，并末尾追加 `snps,dwcmshc-sdhci`。

复用旧真实libfdt、完整树语义、DTC往返及21坏树、Linux真实OF matcher工具，只另立准确BASE锁/读取实际输入兼容串/输出路径。不扩大审计框架；其它USB、电源、音频、所有phandle/reserve/chosen完全保持。USB-device-v2和电池候选不混入。

步骤：锁定旧sealed-v1与新BASE/旧工具/实际OF源码；新BASE先被旧部署匹配串要求实际拒绝；三次真实libfdt与完整树检查；四次DTC与诊断逐字相同；21实际坏树拒绝；实际Linux OF函数/表在新BASE与候选的兼容串上重新执行host与ASan/UBSan；绑定完整输入输出SHA另封v2。

仍仅offline共享DT候选。overlay后的树不是pre-overlay正式包输入许可；early DM重建、真实eMMC读写、USB恢复/电气状态、AVB/分区加载、正式包整合/刷写都未验证。没有Image/正式包，也不改变当前音频下一版所用已测DT。
