# RK3568 音频运行期与 DMA 的后续修正

2026-10-05 独立只读源码审查，尚未 PREPARE/START 或传 PCM 帧。
锁定 kernel commit `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`；下列内核路径均相对
`third_party/linux-rk3588/`。codec 路径相对本目录 `driver-source-v1/sound/soc/codecs/rk817_codec.c`，
C SHA `797d9d74c81dba2ed6f306c011446882eaed1bdf7b8d1ffc7321de73676e86b6`。
已测参数与独立 closed-state 的范围见 [result.json](result.json)。
后续 Playback 测试的全零样本帧也是实际 frame I/O；0个帧 START 会返回 EPIPE。
Capture 与声学验证待实物连接；本文件不作为立即 START 的依据。

## Codec mute 的独立最小修正

真实入口 DAC `:1048`、ADC `:1117`、方向分派 `:1131`；ops `:1176–1182`。
DAC mute `:1055–1064` 关闭功放/耳机 GPIO，再 DACMT/restart/禁 I2SRX，但丢弃寄存器 errno。
unmute `:1066–1070` 在判断路径前已启 I2SRX/清 DACMT，OFF 落入 default，仍解除数字静音。
ADC 不检查 MIC OFF；任意非 Playback direction 都按 Capture 执行。

在 I/O 前拒绝非法方向；OFF/MIC OFF 的 unmute 走受检查静音操作。
所有 write/update_bits/restart 的负 errno 原样传播，0/1 成功统一0；错误后不能继续解除静音或使能输出。
必要独立关闭尽力继续，保留首 errno，清理失败另记录。GPIO helper `:98–121` 用无 errno 的
gpiod_set_value，不能证明电气成功。路径控件 `:534/:730` 在 clk_lock 前更新路径且寄存器编程前已解锁；
此小补丁不支持并发路径切换，首轮必须保持 OFF/MIC OFF。

regmap `drivers/base/regmap/regmap.c:1909–1933` 先更新缓存再 bus write；`:3015–3044`
update_bits 可依据缓存略过写。RK817 在 `drivers/mfd/rk808.c:158–159` 用 RBTREE 缓存。
实例 I/O 错误后不得自动解除静音或假定重试恢复；不能改共享 PMIC cache_bypass/cache_only 掩盖问题。

## PREPARE 的错误链与重入状态

pcm_native `:1963`→snd_pcm_do_prepare `:1931`→soc_pcm_prepare `sound/soc/soc-pcm.c:808`。
ASoC `:841` 丢弃数字 mute errno，而 soc-dai `:304–319` 已能传播它。
只对实际支持且适用当前方向的 mute 回调检查失败；无回调的 CPU DAI 返回 ENOTSUPP，不能一概判失败。
失败保留首 errno，重新静音已处理及可能部分执行的 DAI，并立即配对 DAPM STREAM_STOP。
不能持 card->pcm_mutex 递归调用 soc_pcm_hw_free。已分配 buffer/OPEN 的 PM 由后续 HW_FREE/close 处理。

pcm_native `:1916–1928` 允许 PREPARED 重新 PREPARE；失败 `:1936–1938` 无 undo，旧 PREPARED 仍可 START。
只让 ASoC 返回 errno 不能封住重入失败后的 START。最小通用候选是失败时用 snd_pcm_set_state
退回 SETUP（该 helper `:576–582` 自带锁并保留 DISCONNECTED），或在 DMA component START 之前的入口设可靠闩。
放到 codec/CPU DAI trigger 太晚，ASoC START `:1041–1049` 先执行 DMA component。

soc_pcm_hw_free `:993–1030` 丢弃 mute errno，固定返回0。可累计首负 errno，继续全部清理后返回。
显式 HW_FREE 在 pcm_native `:849–858/:886–891` 可观察错误，但 buffer 仍释放、状态仍 OPEN。
close `:2687–2691/:2855–2873` 忽略释放错误，不能替代显式 HW_FREE。
本板没有额外 hw_free 回调；通用 void helpers（soc-dai `:342–348`、soc-component `:795–812`、
soc-link `:125–131`）不在本板最小修正范围，不能宣称所有 callback errno 已传播。

## DMA buffer 同步与提交错误

generic DMA 两 component `sound/soc/soc-generic-dmaengine-pcm.c:333–354` 均无 sync_stop；
ASoC `soc-pcm.c:2853–2854` 仅有 component 回调时才安装 PCM sync_stop。
pcm_native `:853–857` 在释放 buffer 前调用 snd_pcm_sync_stop；只修 close 的 synchronize 太晚。
两 component 都需 process-context sync_stop 调正确 channel 的 dmaengine_synchronize。
normal DROP→HW_FREE、DROP→PREPARE 和 START 部分失败回滚须覆盖；后者 snd_pcm_undo_start
`:1413–1417` 调 STOP 却没设置普通 STOP 的 stop_operating，不能只依赖此标记。
dmaengine API `include/linux/dmaengine.h:1110–1188` 要求 terminate_async 后同步才能释放 callback 内存；
同步不可来自 atomic trigger 或自身 callback。

pcm_dmaengine `:181` 不检查 submit cookie，`:213–223` 丢弃 pause/terminate errno。
rockchip_i2s_tdm trigger `:1758–1780` 的 void helpers 丢弃部分 regmap/reset/FIFO clear 错误
（`:464–512/:571–600/:876–1011`）。DMA 板测前需处理或证明本轮不涉及。

## PL330 不能只补 tasklet_kill

锁定 `drivers/dma/pl330.c`：

- tasklet `:2289–2294` 在 channel 锁外执行 callback，旧遍历仍保存下一 descriptor `_dt`。
- terminate `:2521–2523` 立即归还跨 channel 公共 desc_pool，其他 channel 可在旧 callback/遍历结束前复用。
- IRQ pl330_update `:1923–1926` 解 controller 锁后迟到 rqcb；rqcb `:1764–1776` 访问 owner 并调度 channel。
- controller fault tasklet `:1818–1820` 也是锁外 producer，synchronize_irq 不覆盖它。
- issue_pending `:2699` 直接调用 tasklet 函数，不受 tasklet RUN/SCHED 等待保护。

当前 `:3316–3325` 没 device_synchronize；card 生命周期不在每次 PCM close 释放 channel，
free_chan_resources `:2566` 的 tasklet_kill 不能保护每次 close。
_stop `:991–1014` KILL 未确认 STOPPED，DBGINSN `:913–916` halted 仅打印，UNTIL `:253` 无截止忙等。
用户态 alarm 不能证明硬件停止/回调清理有界。

可信候选需同时实现 terminated descriptor 隔离、旧 runner 回调后中止遍历、
等待 IRQ/fault 已入 producer、覆盖直接 runner，并在旧 owner 全部结束后才回收 descriptor。
安装非原子 synchronize 时不能持 callback 所需的锁；共享 DMAC 其他 channel 的影响必须审查。
若统一成纯 tasklet 调度，重验 DMA 先就绪/CPU 后启动及 FIFO underrun。

## 分阶段验证

先独立 codec mute 真实函数 tests；再 PREPARE/HW_FREE 回滚、CPU无回调、重入失败state、清理错误。
DMA 设计先审查锁序、硬件失败策略和所有权，再实现。
并发测试用真实函数及明确屏障固定 callback暂停时terminate、IRQ持desc后terminate、fault迟到、
directrunner终止、跨channel池复用、START回滚、HW_FREE/close后无旧runtime/buffer访问。
适用的 KASAN/lockdep 为补充，不能以 fixture 通过代替实际内核测试。

以上门槛通过后才规划 OFF/MIC OFF 的全零样本 Playback，核 DMA进展、停止/同步、closed、FD、
GPIO/runtime/clock counts。dmaengine/summary `drivers/dma/dmaengine.c:83–119` 仅绑定/client_count；
PL330 debugfs `:3102–3131` 仅物理 thread 映射，均不证明队列为空或无 callback。
失败保留证据，不自动 START 重试/改旧时钟，不以 closed/summary 掩盖失败。
