# 音频 RAM 包 v2 离线修复

1. 原工具对真实零字节 reviewed 日志和真实 Linux Image metadata 的红例保持在新目录。
2. 另立四个 v2 工具，普通文件读取允许 0 字节，具体格式维持严格校验；纠正真实 Linux release。
3. 独立真实生产输入回归验证有效空日志、完整 gate、新 Image、非法空格式及错误 release。
4. 旧 RCU Image fixture 的 62 项机械契约另立复跑，release 来自冻结构建记录与 Image banner。
5. 以实际 integration-v1 Image 和 review-gate-v2 构建 ram-audio-v2，审计 audit-production-v2，
   冻结新工具、真实输入和结果完整 SHA，并保留旧结果的拒绝范围。

范围为 RAM_ONLY_NOT_FLASH_READY。仅写本目录新文件，不修改旧工具、prepared-v1、Image、gate、
driver、公共补丁，不操作设备、网络、ADB、串口、TUN、分区或提交。
