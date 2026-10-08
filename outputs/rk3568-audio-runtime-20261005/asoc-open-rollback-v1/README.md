# ASoC 打开失败与同DAI请求候选

私有四源码的关闭、打开失败清理和PM引用归还合同已完成首轮离线红绿及实际Kbuild对象检查。
主控fresh复跑和独立证据审查已完成，已批准仅此离线范围封存；尚未正式整合或上板，全双工未通过。
输入来源、完整原/新源码SHA与精确patch见 `inputs-v1`、`source-manifest-v1.json`；
此前 `full-duplex-contract-v1` 冻结基线保持。

## 实际生产改动

`source-v1/sound/soc/soc-pcm.c` 将清理拆为私有locked/post-unlock段。
正常close仍按deactivate→DAI shutdown→link shutdown→component close→DAPM stop执行，
随后解锁并归还PM、处理pinctrl；startup失败则在原pcm_mutex连续持锁区内清理，
不额外deactivate，保留原open errno，不递归加锁。C3副作用调用与CPU v12生产函数均保持。

`soc-component.c` 的PM get失败先put_noidle失败成员一次，随后按原顺序归还本调用成功prefix。
返回1与-EACCES保留原成功语义；同device的不同component按每次取得分别归还。
全量get成功后的put不再依赖可被peer覆盖的mark_pm单指针。
PCM及 `soc-compress.c` 的get失败分支都不再clean/fullput，防止get自清理后双释放；
full-get成功后startup失败及正常close/free仍fullput一次。
helper签名、struct/header ABI及导出符号保持；COMPRESS未在板配置启用。

`generic/simple-card-utils.c` 只有当前CPU和codec DAI的真实active都为0才发原两次sysclk0，
每次child clock disable仍执行。同DAI peer open（含idle）时缓存保留；
最后owner关闭仍受CPU原sticky、STOP、IRQdrain、两substream均NULL门约束。

## 实际模型结果

同一fixture运行冻结旧源及私有候选，固定25合同、110边界观察（74个唯一标签；
方向及idle/running矩阵有重复标签，110不是110个独立测试）。
`model-red-v2` 抽取68个实际生产函数，`model-green-v2` 抽取70个（新增两段clean）；
逐函数SHA、完整source输入及版本内准备器、fixture、input-manifest均保存。
两个版本的首次运行分别在 `runs-redv1/receipt.json`、`runs-greenv1/receipt.json`。

| 环境 | 旧源合同 | 候选合同 | 旧源/候选边界 | 编译/执行退出 |
| --- | --- | --- | --- | --- |
| host | 0/25 | 21/25 | 各110/110 | 各0/1 |
| ASan+UBSan | 0/25 | 21/25 | 各110/110 | 各0/1 |
| 静态AArch64/QEMU | 0/25 | 21/25 | 各110/110 | 各0/1 |

三环境stderr均空。执行exit1表示明确保留的业务红例；不存在将exit1称完整通过。
runner SHA `e7436d6884d8a91201343ecd8b3f9955a27765b5926b4f8c00b1f083434fda20`。
它固定合同/边界总数及通过数，逐行计数必须等于最后JSON，检查关键边界名单及精确剩余红例。
边界名称沿用旧基线，其中“leaks”等名称描述旧缺陷，候选分支断言相应资源已归还。

21项转绿涵盖真实两open/一close、startup失败连续清理、first errno和PM归属；
110观察包含11个startup前缀、PCM/compressed首/中/末get失败、压缩startup/free、
返回1/-EACCES、重复device及失败成员与prefix同device、peer open/close交错、
共享DAI跨runtime真实active计数和原sticky/IRQ拒绝。PM current noidle/prefix autosuspend
各一次，usage-underflow另行记录；GCC instrumentation观察真实clean/fullput函数入口，
确保get失败调用者不再误fullput，而不是以理想化caller替代错误分支。

四项剩余红例名称在每次stdout和receipt中精确列出：

- `sequential_first_0_second_normal_START`
- `sequential_first_1_second_normal_START`
- `concurrent_two_normal_START_commit_both`
- `hypothetical_dual_joint_STOP_reaches_global_proof`

START并发fixture能让两component准入到达模型DMA GO，实际CPU gate仍拒绝第二方向，
实际ASoC local prefix rollback只清失败方；假设mask3的joint STOP仍拒绝。
mask3不是v12真实START可达到的合法状态，不能把该假设红例当作板运行事实。
CPU gates没有放宽；双START授权为false。

内核PM、模块、CCF、regmap、IRQ、DMA、调度和回调副作用是显式API模型；
真实ASoC dispatcher、runtime/DAI activity、生产single-pointer startup/open/module标记，
PCM/compressed caller错误分支、simple与CPU函数逐字抽取。
模型不替代完整内核运行、PL330 descriptor/drain、codec PLL/DAPM或实物测试。
此前57函数/25红/76观察冻结基线是不同fixture版本；本轮68/70及110不能回写旧收据。

## 真实Kbuild与有限配置边界

`kbuild-v2/receipt.json` SHA
`4f1403bd8aec74ee0ea1e24ff65ffca1ffe9c7b82399d7732f629417446b54dd`。
消费既有audio-v3生成ABI的私有影子和只读kernel include/scripts，原目录前后SHA一致。
原 `.config` 为 `1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912`。
真实Makefile `obj-y`、Kbuild `.cmd`、nm与ar证明四个AArch64 ET_REL对象进入对应built-in.a，
没有-DMODULE，未生成/加载ko；两个build及6个nm/ar步骤均exit0，build stderr为空。

| 生产文件 | 对象SHA256 |
| --- | --- |
| soc-pcm.c | `7776b4d8942372f651b794f1d7e000f17f04d19b16b7fbc75fd0d7458ad32814` |
| soc-component.c | `bfde9be11e2049259f7495c03a462b013b218e432f8511bada00afb162b4fce3` |
| generic/simple-card-utils.c | `fa8b140d06cc19d39d65225f71011cd69456efa411f64c5362536b2ae40dd90b` |
| soc-compress.c | `c397d7b5113ba305dfb397fda4076e386547b371f7afab205eb9a2f648438fcc` |

前三项按原配置编译。原配置没有SND_SOC_COMPRESS/SND_COMPRESS_OFFLOAD；
压缩项仅离线预处理分支检查：独立影子 `.config`、auto.conf、autoconf.h 各追加这两个标记，
完整diff、原/新SHA及真实Kconfig bool/select/tristate依据均记录。
这些标记未由Kconfig生成，不是compressed配置闭合、ABI验收或板镜像启用。
该检查只能证明真实完整compressed翻译单元能在所声明分支中通过Kbuild。
新产品Image将由主控用独立完整源/正配置生成，不消费本影子。

## 保留证据与未完成事项

`prepare-v1-failure.json` 与partial model-v1保留首次头函数抽取失败；
`kbuild-v1/failure.json` 保留首次只读inventory因源码内合法symlink拒绝、尚未开始编译的事实。
后续v2锁定源内链接文本/目标/SHA，禁止链接逃出输入树。旧失败不删、不记为业务红例。

RK817 hifi/voice共用component缓存，本门只保护当前hifi单CPU/单codec同DAI owners；
不能外推兄弟DAI或任意多DAI图。pinctrl active0仍可能存在在途PMowner，当前板default-only，
通用sleep-state并发安全未闭合。PM usage平衡不是callback drain、device kref或remove许可。
shared TRCM的双START、单方向STOP保留运行peer、joint fault/quarantine和双allocation隔离
仍需独立设计/模型/完整内核及必要硬件证据。

本目录未生成Image、正式音频包或公共patch，未操作板、串口、ADB、网络服务、TUN、flash、充电或MCU。
四源码候选仅按此离线范围封存，后续Image/实机有独立整合门。

主控fresh的六次实际重编译/运行和只读最终审查已完成：
`review-evidence-v1/input-manifest.json` 锁定96个只读快照文件，
包含root成功v2的两个model、编译/执行日志、六binary/result与真实runner，
以及root首次v1头函数parser失败、未compile的保留记录。原root目录前后SHA一致。
root结果SHA `42fba37ab7c5d1ae17be9960189d0a325fa8b60359bd22c96011bdb325bdecff`，
runner SHA `8d9ed526b6c85e01c1d3cb87cf23f2c6e04590977c2db1a70b1822d358a4335c`；
红68/绿70逐函数与unit重建、六次stdout逐SHA等于本轮记录。
只读审查另外核对四对象、obj-y thin archive和8395项有限保护输入哈希，无剩余具体阻断；
主控正式接受文档的只读快照为 `review-evidence-v1/ROOT-FINAL-REVIEW.md`，
SHA `2cc2ead8e92ed9c2119e30bc518c9f384080627f916f0e8d493b1439ac52f38c`。
`review-acceptance-v1.json` 记录仅此离线范围的封存许可，不将只读审核当作Image/硬件验证。

`freeze.py` 复核模型、日志、binary、Kbuild对象/命令/完整thin archive成员、原/新来源及外部输入，
在新 `freeze-preflight-v1` 执行真实patch的零fuzz重放，再生成 `sealed-v1/receipt.json`、
`file-manifest.json` 与 `SHA256SUMS` 并逐项readback。
owned清单均为普通文件；外部普通输入与SDK内明确链接分别列在preflight inventory，不混计。
thin archive连同其四个成员对象及命令一并保留，不能只复制archive便声称可恢复。
