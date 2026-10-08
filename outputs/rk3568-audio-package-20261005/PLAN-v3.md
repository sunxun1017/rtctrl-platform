# 音频 RAM 包 v3 离线适配

1. 先以原 v2 的真实已执行工具确认它仍指向 integration-v1/v10、没有本次 runtime sidecar 闭合，保存红例与旧文件完整 SHA。
2. 新增 v3 工具，保留原 ARM64 地址、header/RSCE/DT、普通文件与独立审计规则。精确绑定 integration-v2 的 13 补丁、CPU v11 源码及冻结 inventory、review-gate-v3。
3. 新 runtime sidecar 目录只复制新 Image ABI 的 codec、原 PCM transfer/inspector、guard v4；manifest/audit 校验来源、完整字节及全部 SHA。native3 ramdisk/rootfs、audio DT 保持冻结字节。
4. 镜像未就绪时只执行真实旧工具红例和有价值的合成地址/身份拒绝模型；模型明确标注 fixture，不能生成或冒充生产 Image。
5. 新 Image 与 codec 完成后才执行真实生产 CLI、审计、闭合输入拒绝测试和封存。保留 v1/v2 全部原件，无硬件、ADB、串口、网络或 TUN 操作。

生产结果范围为 RAM_ONLY_NOT_FLASH_READY；不证明物理声音、正式 flash、当前板端地址或新 Image 的实机运行。
