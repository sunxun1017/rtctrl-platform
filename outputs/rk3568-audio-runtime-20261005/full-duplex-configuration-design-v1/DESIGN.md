# 双 owner 共享配置：下一有限契约

本设计仅准备下一步软件实施。已接受的 open/rollback、PM local-prefix 和 simple shutdown
修正作为输入；CPU v12、C3、codec 72e59 和所有 START 门保持。这里没有新模型执行、
Kbuild、Image、板操作或剩余四项全双工红例的通过结论。

输入锁见 `input-manifest.json`：14 项普通源码/header 副本逐字/尺寸/POSIX mode 核回，
对应实际 integration-v4 SOURCE 的有限成员逐项等于 Image 源库存；43 个函数仅登记生产
body SHA/行号。未重复泛读 TRCM/DMA；其既有调查沿用 `build/full-duplex-review-v1`。

## 选择的有限行为

只支持当前单 link、单 CPU、rk817-hifi 的正常 PCM，48kHz、S16_LE、2ch，
MCLK=48000×256=12288000Hz；TRCM=1、bclk-fs=64、lrck-ratio=1 的已锁定 profile。
format 比较使用完整 enum，不能用 physical width 代替 S24_LE/S32_LE 的区别。

| 状态/请求 | 预期结果 |
| --- | --- |
| A/B 均已打开、均未 START，A 首次 params | 预约整条事务；成功后发布 A 的配置 owner 和共享 tuple |
| B 同 tuple idle params | 复用共享 MCLK/PLL/rate/codec 两向位宽；仅必要的 B 独立 CPU 宽度/DMA 参数可配置 |
| A/B idle，同一向重复同 tuple params | 引用/owner 幂等；不重复共享 PLL power-cycle 或 clk_set_rate/reparent |
| 第二向不同 rate/format/channels、非法方向或超出本轮 profile | 在 machine、codec、CPU、DMA 任何共享 I/O 前拒绝 -EINVAL，保持 peer/cache/引用，无新 sticky |
| 任一方向已 START，另一向或同向请求 params | 先保留 symmetry/有限 profile 的 -EINVAL；通过两门的合法同 profile 请求在首共享写前拒绝 -EBUSY；不做 PLL/rate/width 写入 |
| params 与 peer START 竞争 | 事务预约先胜则 START 保留现有 configuring 拒绝；START 先胜则 params 在首个 I/O 前拒绝 |
| 第一次或第二次 params 失败 | 保留最早 errno，只撤销本次 provisional/committed owner；恢复旧软件请求和 peer DAI cache，硬件状态不确定则 dirty/fault/禁 START |
| HW_FREE/close 一个 owner | 不清 peer 的共享请求，不停 peer 的共享时钟；该向资源按真实调用顺序归还 |
| 最后所有者退出 | 配置 owner 清空；最后 open 退出且 CPU STOP/IRQ 排空条件满足后才清 sysclk 请求并释放各自 child-clock 引用 |

这轮不允许活动 peer 时首次加入参数、PREPARE/双 START、分向 STOP 或联合故障运行。
要求拒绝在合法单向运行状态中产生；测试不得靠手写 dual-start mask 创建“已支持”的状态。

## 为什么必须覆盖整个 params 链

最新 `soc_pcm_hw_params:909` 在 card pcm_mutex 内按以下顺序执行：

1. `soc_pcm_params_symmetry:362`。
2. link `asoc_simple_hw_params:250`：codec child rate → CPU child rate → codec sysclk → CPU sysclk。
3. codec DAI `rk817_hw_params:942`；成功后覆盖该 DAI 的 rate/channels/sample_bits 并调用 DAPM update。
4. CPU DAI `i2s_checked_hw_params:2270`；成功后覆盖同类 DAI cache。
5. component hw_params，最终到 `dmaengine_pcm_hw_params:76` 的 slave_config。

CPU 只配置 symmetric_rates。现有 symmetry 可挡不同 rate，却不能挡不同完整 format/channel。
codec 对合法 S16/S24/S32 的共享比较尚不存在：每次写 CFG0/4、CFG3、DAC rate、方向数字
clock 与共享 PLL 的 down/up，再同时写 RXCR2/TXCR2。需纠正首次设计的顺序推论：CPU set_sysclk 在 machine 末尾已有 started 门。健康
peer 48k 运行、B 同 rate 请求时，machine 先有两个 clk_get_rate 和 codec 缓存 setter，
随后 CPU set_sysclk 返回 EBUSY；后续 codec hw_params/PLL 不执行。不能称这条健康链已
重启 PLL，CCF getter 也不能被称作已证明物理寄存器读取。

更有价值的待模型串接是 component 晚失败把 CPU.rate 清0后，合法单向 START peer，再
请求不同 rate：symmetry 可因 cache=0 跳过，machine 的 child CCF/cache 改动早于 CPU
set_sysclk 拒绝。此处必须用真实 error/START 产生状态，不手写清 rate 或 started。
不同 rate 的健康已配置 peer 本来由 symmetry 提前挡住，这个正确行为也应保留。
card pcm_mutex 仍不串行另一个方向的 trigger/IRQ/异步 PM；显式整链预约用于这些空窗
及失败归属，不能以错误的健康链 PLL 推论论证。纠正及原字节见 correction-v1。

最新 simple shutdown 已在真实 deactivate 后，仅 CPU0+codec0 的 DAI active 都为 0 时调用
两次 sysclk0，且每次 child clock disable 仍平衡。此修正必须保留；它不是配置完成计数，
也不是 codec component 所有 sibling DAI 的 owner 证明。

还有独立的 core cache 回滚问题：`soc_pcm_hw_params` 的 interface/component 错误路径将
已成功 prefix 的 DAI `rate=0`，即使同一 DAI 的 peer 已配置。真实 rollback 宏先 `--i`，
不包括失败的 DAI；component hw_free 也排除失败 member。CPU/RK817 当前都没有 hw_free
DAI callback，simple_ops 也没有 hw_free。失败 callback 必须自清本次部分状态，不能依赖
core 将失败 member 再调用一次。

## 推荐实现边界与接口成本

推荐先建立一个可审查的 params 事务入口/结束，而不是先局部放宽 gate。最小完整链需要：

- `soc-pcm.c`：在 symmetry 后、link callback 前对选中 DAI 做**无 I/O 的预约**；在所有
  codec/CPU/component 参数成功后完成；任一失败走本调用局部 prefix 终止。保存并恢复
  真实共享 DAI 的 rate/channels/sample_bits，不能在 peer 存活时无条件清 rate。
- `simple-card-utils.c`/`simple-card.c`：有限 profile 的 machine 入口必须在已预约事务内；
  请求相同共享 tuple 时跳过 CCF/parent 和缓存重写。补 machine hw_free/失败自清接线，
  只释放本次请求，不通过已有零 sysclk API 伪造 abort。保留最新 shutdown 与 child ref。
- `rockchip_i2s_tdm.c`：预约状态有明确 substream+generation，START/PM/format 继续受
  configuring 门约束；本次 CPU hw_params 只允许消费自己的票据，不能广泛允许 configuring。
  第二个相同 idle owner 只写必要的本方向字段，跳过共享 div/rate/reparent；补本向 hw_free
  配置 owner 释放。直接 set_sysclk 的不同正请求/零请求不可绕过 reservation。
- `rk817_codec.c`：component 级有限 owner 表与共享 tuple/pending/dirty；参数共享部分只在
  首 owner 初始化，同 tuple 第二 owner复用。加入失败自清与 hw_free；sysclk setter 分离
  pending 请求与已提交 stereo_sysclk，不推断 clk_id=0 是 playback。

**待主控选择的接口**：最清楚的方案是在 `snd_soc_dai_ops` 增加可选的 params transaction
begin/end（或等价三阶段）callbacks，由 PCM dispatcher 调度；begin 含 substream/params，
end/abort 含同一个 owner token/结果。这些是拟议名称，不是已存在 API。它能避免 machine
直接认识 CPU/codec 私有 struct，且不用再造 exported helper 的模块加载依赖，但会改变
kernel 内部 ops/header ABI，必须整套 Image/codec 用同一新 header 重建并独立审查。
当前 compressed/DPCM/multi-DAI 不接入此有限契约；通用 callback 的默认空路径要保留原行为。

另一选择是 board 专用 machine 与 CPU/codec 的显式私有 reservation API；可不改通用 ops
layout，但必须解决动态 codec 模块依赖、真实 params 最后一段成功/失败通知、owner token
以及全部 bypass caller。只在 machine 加 tuple 缓存或先调用 CPU set_sysclk，既没有 owner
参数，也没有跨睡眠操作的 reservation，不能作为完整方案。推荐先审前一种显式 core 链方案。

本任务不先写任一接口。后续应先用真实 caller-chain 红例证明成本，再由主控批准签名与范围。
C3 DMA/PL330、guard、compress 生产体本阶段无需修改；真实 DMA slave_config 的拒绝/错误仍
进入事务回滚，不能给它总成功 stub 后宣称晚段清理完成。

## 状态、提交与失败归属

分清 open-owner、params-owner 和 running-owner。open 与 PM/child-clock 归属继续用已修
真实 core；params-owner 必须按 substream 记录，不能拿 DAI active、rate 非零、共享 mark
或 pop_wait 充当计数。shared tuple 至少含 rate、完整 format、channels、MCLK、DAI format、
TRCM/divider profile；buffer/period/channel slave_config 是本向参数。

预约保持到整条调用完成。CPU spinlock 下只做 bounded 状态与 MMIO，不能持它调用 CCF、
I2C、PM、codec mutex 或 stream lock；card mutex 的现有外层顺序保持。codec I/O mutex
只串行单个寄存器操作，不是整个 params/controls/PM 事务。锁定顺序及 release 最后由 CPU
reservation 打开 START 门的次序，必须在新模型中覆盖。

begin 只读软件 profile/owner 状态并记录本次 token、旧请求与 cache；所有 begin 成功前
禁止共享 I/O。begin 自己失败立即返还自己局部状态；dispatcher 只 abort 已成功 begin 的
prefix。实际第一次参数 I/O 有部分完成后报错时，只承诺本次引用/cache 请求回滚：旧物理
寄存器/CCF 不一定恢复。若尝试物理恢复，需真实旧 rate/parent/寄存器写后读回证据；恢复
失败保留第一 errno、latch dirty/fault、禁 START，并保留必要硬件 lease，不能返回 clean。

成功发布必须经过最后 component；codec/CPU endpoint 的临时准备成功不能称整个 PCM
成功。finish 不重新编程 PLL；若 IRQ/PM 令 ticket 失效，撤销本次 owner 并保留故障，不把
旧 cookie 写回新 generation。若 endpoint 提前软件发布后最后校验失败，abort 必须仍可
精确撤销本次发布，且 CPU reservation 在全部端点完成前不能被清掉。

第一失败时旧 request=0，也不能调用 set_sysclk(0) 来还原：两个 substream 仍可能存在，
CPU v12 正确拒绝这个公共零请求。应由 owned transaction abort 恢复自己的 pending/旧
cache，保持公共 zero gate。CCF 的真实旧 rate 与请求 cache=0 是不同状态，禁止
clk_set_rate(0)。hw_params 原本不取得 simple startup 的引用，不能多 disable 一次。

正常 HW_FREE 只释放该向 params owner，且不能把仍 open 的两个方向误当最后 clock owner。
最后 params-owner 退出时应清配置 tuple 与 DAI rate/channels/sample_bits，effective MCLK
request 仍由 open lease 维持。旧 core 仅在 DAI active==1 时清三 cache；两个方向先都
HW_FREE、再逐个 close 的合法顺序会始终 active==2 地 free，真实 deactivate/action 又只
减计数、不清 cache。因此新 CPU/codec hw_free 的 owner-aware 更新（或等价 core 查询）
必须覆盖这条顺序，不能把 active count 代替 params-owner。error rollback 的 core 写零也
不得覆盖这些端点刚保留的 peer cache。
最后 close 才按最新 machine gate 和 CPU STOP/IRQ 条件清请求。RK817 probe 还持有一份
MCLK 到 remove；child lease 归零不等于物理所有 MCLK 已关闭。

## 共享写入的旁路与 sibling 范围

RK817 hifi/voice 都绑定同一 `rk817_dai_ops`，共用 stereo_sysclk/PLL。有限 owner 表不能
只用两个 hifi bit 然后宣称全 component 无 owner：本轮 voice 使用应显式拒绝或在 component
表中登记 sibling；voice 不提供兼容放行。codec zero request 也要检查全部实际 component
owner，不能只相信 machine 的 CPU0/codec0 active 门。

`rk817_codec_power_up/down`、playback/capture path controls、set_fmt 与 suspend/resume
都能写共享寄存器，部分原路径吞 I/O errno。实际手动 path-control/power helpers 的共享写
不能泛称为 DAPM widget callback；ASoC 另有 DAPM update/event。只处理 hw_params 不闭合
这些入口。建议这轮有限 checked profile 对有任何 pending/configured/running owner 的
非 PCM 共享重配请求 fail-closed；需要另向 path 准备时另立只做该向独立位的设计。PM 默认
回调也不能在 reservation 内 power_down ALL。CPU PPM/control 重写同样必须拒绝或明确排除
并保留未闭合项，不能由“板步骤不调用”推导驱动不存在旁路。

这项仲裁的真实函数覆盖是软件整合门；声学路由、活动期 prepare/controls、系统 suspend、
voice 泛化、双 START/STOP 和共同故障仍有后续独立契约。任何当前 source/model/板结果都
不能被本设计改写为剩余四项红例已通过。

## 纠正 v2：errno 优先级与 START 前缀

主控已选择保留原 symmetry，有限 profile validation 同样返回 EINVAL；只有通过两门的
running 同 profile 请求才要求 EBUSY。健康已配置 peer 的不同 rate 本来就由 symmetry
EINVAL 拒绝，必须登记为正确观察，不能将它列为业务红例。component 晚失败清 rate 后的
44100 请求超出本轮 profile，候选应在首共享写前 EINVAL；旧链预计在 child CCF/cache
修改后 EBUSY，两种差别均需保留真实记录。这里没有实现新的 validation/reservation。

START 状态只由真实 soc_pcm_trigger 产生：link → components（含 CPU component 早门、
DMA API 边界）→ DAIs，并保留 C3 的本调用 prefix 失败 rollback。不能只调用 CPU trigger
再称整个 START 无副作用。reservation 先胜时，component/DMA 前缀是否已执行必须通过
真实 caller 观察；CPU DAI 末段门不能替代整条事务的证明。旧 source/body 身份不变。
纠正前字节与新记录见 correction-v2；本段是已选择的设计契约，不是模型/板验证结果。
