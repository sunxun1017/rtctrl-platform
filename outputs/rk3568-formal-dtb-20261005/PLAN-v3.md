# eMMC v3：从声音 v3 的实际 pre-overlay 组件派生

仅创建本目录新 v3 工具/输入/输出；v1/v2、当前 audio 包、内核、公共补丁、项目记忆保持。无板子、串口、ADB、网络或 TUN 操作。

输入以 `rk3568-audio-package-20261005/build/ram-audio-v3` 实际 `components/dtb` 为准，163204B/SHA c36b140c0ad18b79c3976f64239ef02251fc6986893afad7c474126725eb1e8b。先用已有真实 boot parser 重读完整包，证明 header-v2 单 DT 组件及 RSCE 九份 DT 都等于该 pre-overlay 输入，而不是使用 applied-audit-only 树。

只在 `/sdhci@fe310000:compatible` 末尾追加 `snps,dwcmshc-sdhci`；保持 RK3568 首项和原 Rockchip fallback，整棵树其它节点/属性/phandle/reserve/metadata 不变。保留 chosen symbol/phandle 0x2fa；不加入 USB 或电量计候选。

用原完整 DTBO 分区的严格 entry0 提取器和锁定 real libfdt，先证明 actual pre-overlay base 应用后等于原 4fb 核查树，再实际应用到新候选三次，并完整比较 v2 的 5c09084fe0d456953d228cdd811b53ddca8fc74f0963a2fe00820e70265f8b72。分别记录 pre-overlay 包候选与 post-overlay audit-only 产物。

复用 v2 builder/DTC/21 坏树/真实 OF matcher，只窄改 baseline 路径、长度和 SHA；执行原 baseline 红例、新 pre-overlay 21 坏树、新 post-overlay 21 坏树、overlay 前提/格式负例；DTC 四次及完整往返/diagnostics 核对。真实 Linux OF matcher host 与 ASan/UBSan 针对新输入执行。最后另封 v3 并逐 SHA 检查旧 v1/v2 snapshot 与 live 文件未改变。

本候选只闭合 pre/post-overlay 离线衔接。部署 U-Boot 的真实早期 RSCE 读取、gd 替换/DM 重建、late 资源加载、overlay 错误处理依据已有部署二进制审查及实际日志单列；kernel libfdt 不冒充部署 libfdt。同一 compatible 字符串不能证明 clock/reset/regulator、eMMC probe/MMIO/I/O 或早期 DM 成功。没有生成 Image/正式包/刷写许可，board/early-DM/USB recovery 均 false。
