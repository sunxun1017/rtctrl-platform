# RK3568 checked 全双工契约候选

本目录只制作设计与冻结 v12 的基线红例，等待主控审查后另立生产候选。驱动、公共补丁、guard、旧冻结和板状态均不在本任务修改范围。软件模型不授予硬件 START。

## 选择与状态所有权

仅支持同 rate、同 sample format/有效位宽、共同 LRCK/BCLK/MCLK/TRCM 的双方向；第一轮有限 profile 为 S16_LE、48000 Hz、各 2ch、MCLK 12288000 Hz、TRCM TXONLY=1。不是跨采样率或跨格式混音。必须在第二方向写入任何共享 codec PLL/位宽/CPU clock 前检查一致性；不一致返回 -EINVAL，不触碰 peer 或有效 clock 请求。symmetrical_rates 单独不足以保护 codec 的双 RX/TX 位宽。

CPU 维护 open_mask、configured_mask、prepared_mask、started_mask、starting_mask，以及一个共享 config tuple。它们不是可相互替代的引用计数。substreams[] 仍为 IRQ 捕获指针所有者；closed 意味着本方向指针撤销并同步排空，不意味整个设备 STOP。现有 ready、sticky、shutting_down、configuring、power_transition 和 IRQ/STOP 证据继续保留。组件准入不能只读门后放行 DMA：必须为同一 substream/方向分配一个 bounded START admission，并在 DAI commit 或 rollback STOP 中消费/撤销，不能使另一方向的故障在 DMA GO 窗口绕过。

正常 STOP 只撤销本方向 DMA 请求/IRQ 和 started 位；peer 存活时保持共享 TX/RX XFER、clock tuple、peer FIFO/descriptor，不做共享 CLR 或 TRCM 停启。最后方向 STOP 才执行双方 DMA/IRQ关闭、共同 XFER STOP、双方 CLR、直接 MMIO readback；成功才有 global stop_proven。per-direction quiesced 与 global stop_proven 分开，正常 peer 运行时后者为 false 不是本方向关闭失败。

CPU lock 负责瞬时状态与寄存器提交；不能在其内等待 IRQ、DMA callback、PM worker 或 ALSA stream 锁。关闭/PM 的过程同步排空按已有 context 顺序在 lock 外完成；START/DROP/close/config/PM 的状态票据使延迟回调、旧 substream 指针、旧 descriptor 不能重新发布。PM 仅最后 open/配置/运行所有者退出且 global STOP、IRQ排空均证明时释放共享 clock；format_pm_release 不是全双工所有者替身。

## 请求清零与配置

simple-card shutdown 调用 codec sysclk(0) 后 CPU sysclk(0)，两者回调都没有 substream 参数。因此不能靠 clk_id 推断关闭方向，也不能只删 CPU gate。peer open/configured/started 时，合法 teardown 清零必须成功无诊断并保留整个共享有效请求；最后所有者离开才清请求缓存。codec cache 与 CPU cache 必须采用同一个真实 peer-liveness 规则，不能一个清零另一个保持。此操作是请求缓存管理，不直接 clk_set_rate(0) 或 clock disable。

首个窄修正选择是在 simple-card 的真实 shutdown 中，只有 CPU 和 codec 的 snd_soc_dai_active 均为0才发两次 sysclk(0)，并保持已有 child clock 引用的每次 enable/disable；peer open（含idle）或 failed-open rollback仍保留双方请求。最后关闭继续调用 v11/v12 合法清零，当前 checked CPU zero 门不放松。soc_pcm_clean 先执行 snd_soc_runtime_deactivate，再 DAI shutdown、link shutdown；真实 snd_soc_runtime_action 调用各 DAI action，使方向 stream_active 与对应 component active变化。不能把模型伪计数写进生产。第一段仅 machine shutdown，不加入 START准入；共享正请求/config tuple/codec/DAPM另段审查。还须覆盖多个DAI/shared DAI引用、startup早失败mark与unwind，不能独自用 codec cache=0 当 harmless 通过。

该 machine 段的前置条件现在已有真实红例：soc_pcm_open 的失败路径先 unlock，再 soc_pcm_clean 重新lock，未activate的B已占 startup标记与child clock。A最后close在此窗口可清掉B的rtd/DAI单指针mark，使B后续rollback漏clock和CPU指针。因此应先拆私有 clean_locked/post_unlock，失败startup仍在原 card pcm_mutex 内清理；正常close顺序保持，PM与pinctrl锁外。不能以 active=0 证明无在途启动owner。

PM get在锁前、put在锁后，mark_pm又是单指针，startup事务修正仍不能单独保护PM。真实 get 对每member先取得usage引用，-EACCES按既有约定是成功，非EACCES失败仅put_noidle当前失败member；此前成功prefix旧代码依赖外部clean。改动方案要求get自己按本调用local prefix依原序put_autosuspend归还，失败memberput_noidle一次，返回原errno；PCM和compressed get失败分支同时跳过clean/fullput避免double-put。全部get成功后的startup失败/正常close按本次取得的完整引用各还一次，不读写共享mark_pm，不改helper签名或struct/header ABI。相同device经不同component出现仍是每次独立usage引用。

实际源调用点仅 soc-pcm.c 的open/clean与soc-compress.c的open错误/free（共6处）；本次只执行PCM与PM helper，不执行compressed caller。RK817注册hifi与voice两DAI共用component cache，当前单link仅hifi；CPU0/codec0 active门不覆盖voice或所有component兄弟DAI。pinctrl默认/睡眠在锁外，也有active0但在途PMowner窗口；当前板default-only，不能据此扩为所有板sleep切换并发安全。

第二方向 idle hw_params 可以写本方向独立 FIFO 配置；相同共享 PLL/clock/format应复用，不重复 reset PLL 或改变 peer 可见寄存器。运行 peer 时允许第二方向 open 与相同配置/prepare，需要区分 per-direction dirty 与 shared dirty，不能调用当前 force-global-STOP 的 prepare。RK817 codec hw_params 会同时写 TX/RX widths，ADC/DAC DAPM restart 均触碰共享 PLL；最小方案至少改 codec 的相同配置复用及 active-peer 共享写拒绝，并核第一次开启另一 DAPM path 的 PLL 更新是否必要。仅 machine 层缓存相同 tuple 不证明 DAPM 无干扰。

## 实际调用链与回滚

实际 open：component PM get → component open → simple-card startup → CPU/codec DAI startup → runtime activate。实际 close：runtime deactivate → CPU/codec DAI shutdown → simple-card shutdown → component close → PM put。实际 START：link → components（CPU、codec、platform）→ DAIs（CPU、codec）。实际 STOP：DAIs → 所有 components → link，即使前一组失败仍继续独立清理。C3 失败 START 仅回滚已尝试的本 substream prefix。

不得改变该错误传播顺序来掩盖第二 START，或跳过 generic DMA cleanup。第二方向成功 START 应仅使本方向 DMA/IRQ使能并添加 started 位，既有共享 XFER 不再重写/CLR。错误 START rollback 只撤销失败方向的票据、DMA和指针；共同故障例外，见下节。竞争双方 component 准入至 DMA GO 至 DAI commit 的每个边界必须有确定性夹具；仅各自 CPU gate 单元成功不足以证明完整链。

## 共享故障与隔离

CPU shared regmap/XFER/STOP/PLL 故障或 PL330 controller sticky 都关闭两个方向 admission，并通知两个活跃 substream。CPU 要有独立 joint-stop 路径，不以“peer 位仍在”拒绝故障 STOP，不通过顺序调用当前 stop_locked 两次假装联合停止。保留首个 errno；双方 DMA/IRQ/CLR 独立清理尽量执行，无法证明停止时 retain clocks/device，禁止重新START/解绑。

ASoC 本方向 trigger rollback 不负责联合停止另一个 substream；异步联合故障须在正确上下文发双方 XRUN/cleanup，避免在 I2S/DMA lock 内取 stream lock；排空先前捕获的 IRQ 指针。PL330 C3 已有 controller sticky、各 channel 同步排空和 PCM allocation quarantine；正常单 channel close 可在健康 peer 运行时结束。但还需要真实两 channel 的故障 fanout、两 callbacks/descriptors/allocations 的独立归还/隔离证明。不能把一个 allocation quarantine 当两个方向安全，不能为返回0吞掉 STOP 失败。

## 分段实现与审查门

1. 本任务：原 v12 真函数、真实 ASoC dispatcher 与 simple-card/codec sysclk链复现双 open/单 close、顺序第二 START、竞争 START 与 prefix rollback；标出所有 API model 边界。只期望红例，不作生产修改。
2. 首个生产段（主控另立目录授权）：ASoC failed-open事务 + PM本次local-prefix/get失败caller分支 + machine同DAI shutdown门。CPU v12不变，second START与joint STOP仍拒绝。详见主控2026-10-06-rk3568-asoc-open-rollback-design.md和对应计划。
3. request/config 段：另立 machine/CPU/codec 候选，补共享 tuple、方向 owner；相同格式可复用、不同格式/频率在共享写之前拒绝。保留全旧单向回归，先独立审查。
4. START/STOP 段：另立 CPU 双方向位图与 admission/rollback票据、per-direction STOP 与 last/joint STOP，prepare不force peer STOP；真实整链并发 START/DROP/close/PM 确定性交错与 IRQ captured-pointer 排空。
5. 联合故障段：CPU/PL330通知与双方XRUN，不改 C3 正常 per-channel ABI，除非双 channel 真函数红例证明具体缺口。generic DMA 现有 rollback/close 先复用；必要修改单独审查并保留allocation quarantine/failstop。codec DAPM shared PLL 与 PM 必须独立闭合，不能只删secondSTART gate。
6. 全部软件门：host、ASan+UBSan、AArch64 QEMU真函数红绿、真实相关 Kbuild/完整Image、独立review；随后才可改有限全双工collector/guard矩阵并由主控决定板测。此次无guard/硬件START许可。

## 本次模型的精确边界

使用 byte-exact v12 CPU 生命周期函数、冻结 C3 ASoC trigger/open/clean及DAI/link dispatch、原 simple-card startup/shutdown/clock请求和codec sysclk setter。spinlock/mutex、regmap/CCF/PM核心、ALSA约束API、component open/close、codec trigger和generic平台DMA副作用是显式API模型；不等于内核 ABI、完整soc_pcm_hw_params、RK817 DAPM或PL330执行器/硬件。竞争 fixture 用真实 pthread barrier 固定“两方 component 通过并DMA GO后才DAI”的允许软件交错，不声称板上实际发生。人为双started=3 fixture仅演示未来只移除START gate后的STOP反例，当前原驱动不会合法生成此状态，不能当原驱动已双向运行。

最终 model-v5 精确抽取57函数，runtime activate/deactivate/action、DAI active/action、PM get/put、symmetry helper均真实；PM核心usage副作用和constraint errno注入仍为API模型。旧model-v3的54函数版本未抽取真实PM helper，它的PM平衡只是声明范围内的模型观察，不能用其62绿覆盖PM单指针缺口。module/open component helper未执行真实生产体，生产候选需再补这些前缀。C3 trigger用局部i/j和本substream prefix回滚，不用shared startup/PM mark，已经避开同类标记覆盖机制，但不证明所有并发device commit安全。
