# 0010 已发布候选与证据

公开补丁：`platforms/rk3568/boards/aiot-3568pq/patches/0010-asoc-prepare-free-errors.patch`。
SHA256 `c3bd1bd7e8fd581e21a962993519f934ceb78a7efe61d77da846972e93b73f2b`。
最终候选 `driver-source-v2/`，与首轮 `driver-source-v1/` 的生产文件/补丁字节一致。

| 生产文件 | 原源码 SHA256 | 候选 SHA256 |
| --- | --- | --- |
| sound/soc/soc-pcm.c | 1b64190aa7421d2195f174f2c5a6607cc72d868a56c5431591abbdb8619b3bfc | 0da4f2816f293dc782fa83260f9d59735553064836fc333edc8c70556361d1b0 |
| sound/core/pcm_native.c | dc1e6ac01a8532afce0155eaaf2cda1d65aa95c5414210fb54bb03c2577bd608 | bc34db0aabe8b523172403a4095afeac5544434e15a05884ca99f6b77d48c47d |

`asoc-tests-red-v3/result.json`：真实锁定原函数，host / ASan+UBSan / static
AArch64+QEMU 各 198 项，42 通过、156 行为失败。red-v1 是抽取器编译失败的历史，
red-v2 是抽取器拒绝错误声明的历史；它们不能作为行为红证据。

`asoc-tests-green-v2/result.json`：公开候选对应的三环境各 198/198。
`asoc-tests-green-v1` 绑定相同生产字节且首次转绿；最终引用 v2。
逐字抽取的真实函数/helper/action/宏、源快照、harness、编译/运行输出与 ELF
都绑定 SHA256，目录内 include 只引用封存的输入。

`prepare-tests-v1/result.json`：36/36，包括公开 0001–0010 顺序重放、全部目标
文件字节绑定、冻结 codec/panel SHA、源/9 个依赖补丁篡改拒绝、冲突公开补丁
拒绝、版本/已有输出拒绝和原内核 tree clean。测试只在私有 fixture 改动。

修改仅处理实际适用静音回调错误、尝试前缀重新静音/DAPM STOP、HW_FREE 清理
与首错返回，以及 do_prepare 失败后经现有 helper 退 SETUP。无 callback 的 CPU
DAI、no_capture_mute 和正值回调不误失败；适用 callback 的 ENOTSUPP 是真失败。
锁定 ABI 不含 legacy digital_mute 字段。原 void hw_free helper 未改变。

本目录 .gitignore 忽略生成源/结果、封存的 harness 和根目录测试 C/header。
生成生产源只保留原 license/copyright，没有注入 harness。完整生产对象/Image
构建和硬件验证仍由主任务执行；DMA/PL330、链接 PCM 事务、reset 后资源撤销、
前置 buffer/pre_action 拒绝失效不在本补丁范围。仍禁止上板 START。
