# 音频 RAM 包 v2 实际结果

两项生产输入错误已另立 v2 修复。旧工具与 prepared-v1 保持：35 个来源文件、7 个旧证据及其
冻结副本逐字节/完整 SHA 核对通过。没有改 Image、review gate、driver 或公共补丁。

- `build/production-bug-red-v1/result.json` 保存原工具 6/14、两项根因及相关格式失败；
  原生产 CLI exit 1，拒绝 `Bounded ordinary file required`，没有创建候选目录。
  真实 Linux Image 被原 release 判断拒绝；原工具把同一真实 Image 的虚假 Android release 接受。
- `build/production-bug-green-v2/result.json` 实际 14/14、exit 0：完整 910 文件 gate、合法空日志、
  真实新 Image、错误 release、空 JSON/Image/ARM64 输入、普通文件/路径/大小边界。
- `build/tests-v4/result.json` 实际 62/62、exit 0，为 `FIXTURE_ONLY_NOT_DEPLOYABLE`；
  旧 RCU Image release 从冻结 kernel-artifacts.json 和 Image banner 独立确认。
- `build/production-cli-v2/result.json` 保存实际 builder/auditor argv、stdout/stderr 和 exit 0。
  新生产包为 `build/ram-audio-v2`，新审计为 `build/audit-production-v2`。

根因一是底层普通文件读取混入了非空格式要求，导致合法零字节编译日志不能被完整 SHA 核对。
v2 仅把大小下界改为 0，大小上界、普通文件类型、路径和前后 identity 保持；格式解析仍拒绝空数据。
根因二是把原 Android `4.19.232` 错作 Linux Image release；v2 固定本次真实构建的
`5.10.160-rt89-g9f9e9d18574d-dirty`。

真实新 Image 为 34755072B，SHA `e48c4295b871623f3c4d0e18470d451b5c344b7e71d021c77f9b0cc297d89955`，
CRC `fb920db9`；manifest SHA `5caa5a64816af8627baf880d46cae55876e5a6ed0985afc21fd623765c1860f5`；
review-gate-v2 SHA `cbad7ecff36098d4dbc0d49db3191f966bcf4107595e733671be0330e20781af`。
实际 raw 包 40482816B，padded 包 41943040B，完整 SHA
`58e2a96f9da2c2ad1d60e0b42c92efa2d4c30efbfe76202738393f2e06974b8b`，CRC `fe7bd3a1`。

v2 production audit 实际拒绝旧 tests-v1/v2/v3 fixture candidate 的 mode；旧 prepared-v1
仍为生产待完成证据，旧 62/62 不能证明这轮真实生产输入可用。
封存入口 `build/sealed-production-v2/receipt.json` 含新工具、实际输入、所有本轮结果的完整 SHA。

范围保持 `RAM_ONLY_NOT_FLASH_READY`。没有操作板、ADB、串口、网络、TUN、分区、保存环境、
公共补丁、提交或推送。没有声学/电气、PCM START/STOP 或实际新内核板测结论；主控仍需独立复核
和 fresh RAM 地址/CRC/整树/身份/普通返回验证。
