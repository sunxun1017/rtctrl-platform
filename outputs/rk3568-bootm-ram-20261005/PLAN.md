# 原启动包 RAM bootm 实测计划

先测与原 boot 分区逐字节一致的 40 MiB 包。它只在 cache 保存普通文件，U-Boot ext4load 到 RAM，再执行单地址 bootm；不写启动分区或保存环境。

1. 只读核主机原备份、官方 roundtrip、冻结 manifest 的完整 SHA/大小/CRC/逐字节一致及源清单。Android root/11/4.19.232/boot_completed、电量和七完整 SHA已在PID1 v3返回后重新采集。
2. 新 cache 路径仅普通文件；预检空间、主机和两次板端SHA；已有文件/符号链接拒绝覆盖，暂存脚本证据保留。
3. 原 Android 正常 reboot 后中断进入 CLI。重新核 bdinfo 的RAM banks/relocation、默认环境目的地、缓存 GPT索引、保留区；PACKAGE_ADDR暂定0x20000000，40MiB跨度[0x20000000,0x22800000)，只有现场范围不重叠才用。
4. ext4load 原包并核filesize与全40MiB CRC6e48ba06。只执行 `bootm 20000000`；不用boot_android，不把单地址包冒作Image/ramdisk/fdt三地址。
5. 记录真实kernel/ramdisk/DT选择/复制地址和Android启动，重新核七SHA。明确成功仅证明CLI已经可达条件下的RAM原包启动；不证明改变boot后仍可进入CLI或USB/MaskROM恢复。

原包26/26已完成。Linux v2包第二次实测（trial-v3）71/71已完成：仅临时FDT地址匹配fresh gd A100000，
最终overlay/full-tree完整SHA审查、native PID1自检/原生RAM返回、普通重启和Android七完整SHA闭环。
第一次trial-v2最终overlay丢失的65/71保留拒绝，不与trial-v3混用。
原early RSCE/PMIC/显示初始化仍来自eMMC原boot；正式分离early/late DT和OTG恢复未证实，本测试不放行flash。
后续继续声音C1/C2/C3整合与正式早期启动路径调查，各自新产物另行冻结、地址核对与板测。
