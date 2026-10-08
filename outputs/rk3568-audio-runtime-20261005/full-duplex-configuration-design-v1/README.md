# 共享配置设计入口

[DESIGN.md](DESIGN.md) 定义有限 48k/S16_LE/2ch 双 idle owner、运行期参数拒绝、整链预约、
cache/引用回滚、最后 owner 和 sibling 范围；[MODEL-PLAN.md](MODEL-PLAN.md) 定义下一步
真实函数 caller-chain 的基线红例、故障注入与确定性竞争。接口仍待主控审查选择。

只读依据是最新已接受四源、CPU v12、codec 72e59 和实际 integration-v4 SOURCE；
`input-manifest.json` 的 14 个普通副本与实际 Image 源库存的有限项逐项匹配，登记43个
生产函数身份和11个普通参考文件。没有扫描/再验整个SDK，不借此宣称新ABI已构建。

本轮只执行了普通文件身份、副本与函数 body SHA 核对；没有模型、编译、新 Image/包、
板或 START 操作。旧源码、冻结、模型、guard、公共补丁、记忆和板流程保持。
主控已生成的 board-v5/live-v5 属于主控本轮事实，本设计不把早先准备时刻的“未生成”
记录当当前状态，也不重新生成或修改它们。

关键新增证据是 machine 共享设置早于 codec/CPU 的准入，以及 params 失败前缀清 rate
会覆盖 peer 的 DAI cache。下一步应先在新目录注册真实 hw_params callbacks 复现红例，
再评审事务接口成本；不以本设计关闭剩余四项双START/jointSTOP红例。
