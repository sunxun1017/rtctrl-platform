# 共享 DT 的有限离线兼容候选

主控委派范围：仅此目录；只读已有输入，不操作板卡，不生成启动包或刷写文件。

1. 以已验证的 audio DT 作为唯一基线，锁定完整大小、SHA 和真实 libfdt/DTC。
2. 先验证旧 eMMC compatible 无法命中部署 U-Boot 的已确认匹配串。
3. 仅追加原 Android 的 `snps,dwcmshc-sdhci`，保留 Linux `rockchip,rk3568-dwcmshc` 首项。
4. 真实 libfdt 生成 DTB，完整节点、属性、phandle、reserve 比较；DTC 解码、重新编码再比较语义。
5. 用真实坏 DTB 验证拒绝其它改动和不完整格式，不把格式通过视作早期上电证明。
6. 按 phandle 解析原 Android 和候选的 USB 控制器、PHY、时钟、reset、GRF、供电依赖，核源码和当前内建配置。
7. 保存输入、脚本、输出与真实测试 SHA。USB status 保持原候选状态；仅列后续所需的明确变化和未验证条件。

候选只证明 eMMC 匹配串的离线兼容。上电前的 DM 重建、真实 eMMC 读写、USB 电气状态、恢复入口以及正式 AVB/分区加载仍由主控单列验证。
