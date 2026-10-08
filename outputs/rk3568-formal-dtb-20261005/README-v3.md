# eMMC v3 的 pre-overlay 衔接候选

v3 从声音 v3 包实际未叠加组件派生，闭合 v2 只保存 overlay 后树的版本衔接。当前 audio 包及 v1/v2 完整保留，没有生成 Image、boot/recovery 包或上板许可。

| 角色 | 字节数 | SHA-256 |
|---|---:|---|
| 实际声音 v3 `components/dtb` 输入 | 163204 | `c36b140c0ad18b79c3976f64239ef02251fc6986893afad7c474126725eb1e8b` |
| 新 pre-overlay 候选 `build/emmc-v3/audio-emmc-compatible.dtb` | 163224 | `08ddd2ad4040ae298dae55ecb928c86672090d9d9bd1f889875ffd1b1daab700` |
| 实际 overlay 后原基线 | 163285 | `4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f` |
| 新 post-overlay 核查产物 `build/emmc-v3/applied-emmc-audit-only.dtb`，逐字节等于 v2 候选 | 163305 | `5c09084fe0d456953d228cdd811b53ddca8fc74f0963a2fe00820e70265f8b72` |

新未叠加候选只在 `/sdhci@fe310000:compatible` 末尾追加 `snps,dwcmshc-sdhci`，保持 `rockchip,rk3568-dwcmshc` 第一项和原 `rockchip,dwcmshc-sdhci`。完整 962 节点、4885 属性、762 phandle 核对：其它 USB、电源、音频、chosen、phandle、reservation/版本/启动 CPU 字段均不变，未混入 USB-device 或电量计候选。chosen symbol 与 phandle 0x2fa 已由实际输入提供，不另分配；原 codec 0x2f9 保持。

已有严格 boot parser 实际重读声音 v3 `boot-padded.img` 41943040B/SHA `5d9e5de346a307edff9dc034f2b396e949b85d83564c1b6cfe9b62467a6ff8ab`，证明 header-v2 单 DT 位于 offset40318976，且 RSCE 九份 DT 逐字节都等于 c36b 输入、各存储 hash 有效。声音 v3 manifest/receipt/实际组件全 SHA 对应；不是从说明文字推定包内内容。

原 DTBO 完整分区 4194304B/SHA `59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d`，严格提取 entry0 offset64/559B/SHA `acf746c91caa230f7958ba2df4e6daf325881e7bce855657aa3b535f440dfec3`。锁定 real libfdt 三对实际应用证明：原 pre→4fb，新 pre→5c09；后者完整语义、所有 phandle/reservation 和字节都等于 v2。overlay 只增加 chosen bootargs_ext、改变 mode-bootloader/fastboot 两值，normal5242c300保持；pre compatible 修改与这三项互不干扰。**将来整合包必须使用 pre-overlay 候选；post-overlay 文件只作核查，不能直接打包。**本任务未制作或修改任何包。

- 原 pre 基线的红例明确拒绝缺部署 U-Boot 匹配串。pre 和 post 各 21 个实际坏 DTB 全拒绝，保持原串顺序/缺失/NUL/重复、其它属性/USB/供电/chosen/phandle/reserve/格式边界。
- 另有 12 个 pre/overlay 边界拒绝，包含把 post 树误作 pre 输入、原 DTBO count/offset/size/尾部异常及五个 real libfdt 失败。缺 chosen symbol/phandle、symbol 指向不存在节点、phandle 溢出、第二 fragment fixup 缺失都不返回 applied tree；完整缓冲恢复仍保留失败码。成功对照得到同一5c09产物。
- 新 pre 的四次 DTC 解码/重编码 exit0；完整往返语义相等。保留 stdout/stderr 原 SHA，路径归一化后 decode 与 encode diagnostics 逐字相同，零新增；不是零警告或完整 binding 验证声明。
- 新 pre 输入与候选上的真实 `of_prop_next_string`、`__of_device_is_compatible`、`__of_match_node` 及 `sdhci_dwcmshc_dt_ids`，host 与 ASan/UBSan 各7/7，确实选择 RK3568 数据；generic 第一项的负对照会选择 generic 数据。模型仅提供 node/property 读取，未运行驱动 probe、MMIO 或 eMMC I/O。

部署事实分两种证据：锁定 `../rk3568-boot-package-20261005/FORMAL-EARLY-REVIEW.md` 的原部署 U-Boot SHA4758…/二进制审查，记录 board_init0xa04480→0xa05030 读取 RSCE、0xa050f8 替换 gd DT/重建 DM；late component4 的0xa28b54比较 env fdt_addr_r/gd，不同则0xa28b5c→0xa0379c重读 RSCE。它还确认部署 eMMC driver0xb210d0/oftable0xae93f8/probe0xa4f198识别 snps 串。`PLAN-v2.md` 记录原部署 overlay 吞错误边界，本任务未重新反汇编或执行该失败路径，锁定 kernel libfdt 也不冒充部署二进制。

另一份实际成功记录是主控的 `../rk3568-pid1-20261005/private/audio-v3-boot-20261006-v1.raw.txt`，完整 SHA `d1c4403c4f6201e895794b3eb721ce637c1562c59e27e3a1f98724cc38b39872`。仅提取其单 bootm、selected `rk3568_smdt_3568a_v20.dtb`、`ANDROID: fdt overlay OK`、Hash OK、Linux fdt 入口五精确行；保存于 `build/deployed-evidence-v3/result.json`。这是旧早期 DM 保持情况下的声音 v3 RAM 成功 overlay，不能证明当前新 eMMC bridge 早期初始化。

上电前使用新 RSCE 的实际 DM 重建与 clock/reset/regulator/provider 闭包、eMMC probe/读写、正式 boot_android/AVB/分区加载和 USB 恢复仍未验证；串匹配只证明 table 准入。后续需要主控确定可恢复且不持久写入的 early-DM 试验路径，再采集新输入/所选资源/完整早期 DT、驱动绑定及实际 eMMC 初始化和只读加载结果。现有 CLI 后 RAM bootm 不覆盖该时序。DMO 身份和 VBUS/ID 边界保持，USB/电量计没有启用。

所有执行使用已有工具和新目录；41份版本输入快照、完整大包与 raw 只以 SHA 引用，在封存时重新逐字节读取核验。旧 sealed-v1 的84文件及 sealed-v2 的80文件的 snapshot/live SHA 全核。封存 `sealed-v3/receipt.json` 仍明确 accepted_for_board=false、early_dm_tested=false、formal_flash_ready=false。无板子/串口/ADB/网络/TUN操作，未修改 audio 包、kernel/config、公共补丁或项目记忆。
