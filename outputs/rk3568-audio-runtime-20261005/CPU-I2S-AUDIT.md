# CPU I2S 生命周期只读审查（2026-10-05）

由独立 agent i2s_runtime_audit 核查锁定源码/DT/config，主控保存。没有新编译、故障 harness 或板测。以下缺口仍阻断首次 PCM START，需与 DMA C3 一起闭合。

## 锁定输入与实际分支

- kernel HEAD `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`。
- `sound/soc/rockchip/rockchip_i2s_tdm.c` SHA256 `53de554206b13f13e480280b8f46366778c2837cdcba2cdb1417e0127be7ffda`。
- config SHA256 `1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912`；I2S_TDM/generic DMA PCM/PCM DMAengine/PL330/PM/PM_SLEEP=y，multi-lanes=n，NO_GKI=y。
- 已测 audio DTB SHA256 `9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478`。
- `rk3568.dtsi:2922–2935` 与 `rk3568-aiot-3568pq-audio.dts:6–45`：fe410000、RK3568、TX/RX 两 reset、dmac1 request2/3；TRCM1（TX共享时钟）、master、普通 I2S、mclk-fs256。48kHz/S16/2ch：MCLK12.288MHz，BCLK3.072MHz，div_bclk4，div_lrck64，maxburst8。
- 无 always-on、HDMI、mclk-calibrate、io-multiplex、TDM slots、digital-loopback、no-dmaengine、clk/idle pinctrl state。不要扩大本轮通用分支的验证声明。

## 已定位缺口

| 入口/锁定原源码行 | 实际缺口 |
|---|---|
| hw_params1681–1755 | 两次set_mclk rate及NO_GKI parent已检查；channels/dirty reads、TRCM三写吞错，params_trcm返回值未接线。 |
| channels1637、dirty1491–1505 | read失败使用未初始化或旧值，dirty shortcut可能假成功。 |
| params_trcm1514–1547 | 三次配置固定返回0；另一方向active时pause/resume的DMA/XFER错误也丢。 |
| START/STOP549–600、876–1011、trigger1758–1780 | IRQ mask、DMA request、XFER、clear经过void helper，trigger恒成功。 |
| clear464–526 | 首写不检查；poll失败后再次写/poll，最终失败返回0。 |
| sync_reset305–438、probe2766–2781 | HAVE_SYNC_RESET开启，但仅PX30/RK1808/RK3308映射CRU，RK3568 cru_base=NULL，fallback直接返回，不是硬停证明。 |
| ownership934–951 | START先增atomic refcount再硬件动作；STOP无方向ownership/零保护。重复STOP或失败rollback可下溢，重复START可漏引用。 |
| prepare2118–2126 | 没有CPU prepare门槛。 |
| startup2093、shutdown2110–2115 | 子流指针发布/撤销无统一同步；shutdown只NULL，没有IRQ排空/停止兜底。 |
| ISR2573–2604 | INTSR read吞错且val未初始化，INTCR清/屏蔽吞错，裸取substream后XRUN，存在独立于DMA的迟到IRQ/UAF边界。 |
| runtime PM198–264 | resume已检查clock-enable/cache-sync；sync失败未恢复cache-only；本DT pinctrl为no-op；suspend没有停止证明。 |
| system PM2983–3003 | suspend仅mark dirty，resume负pm_runtime_get_sync未配put_noidle。 |
| remove/shutdown2957–2979 | 不排IRQ/硬件；runtime_suspend后又重复disable两MCLK，already suspended也无条件disable。clk.c830/971零计数disable/unprepare会WARN。shutdown吞PM/STOP错，可能下溢。 |

DMACR/XFER为FLAT regcache且非volatile（2178–2226）。`_regmap_write:1918–1933`先更新cache后硬件写，`_regmap_update_bits:3037`可能因为cache相同跳过写。故障后STOP用普通update_bits返回0不证明硬件曾写；可使用现有regmap_write_bits强制写。需要读回时须明确读的是硬件，MMIO成功也不是电气测量。

## 最小实施分块

1. errno与结果分离的channels/dirty，实际TRCM配置与hw_params接线。纯格式/方向/channels输入错误不poison；硬件配置之后I/O/clock失败记录实例首个sticky errno。set_fmt实际四次CKR/TXCR/RXCR写、PM get也检查。
2. helper链改int，I2S锁覆盖DMA request/XFER/ownership。方向bitmask或严格一致ownership替代单refcount。START全成功才记started；失败保首错且尽力关闭。STOP即使sticky仍独立尝试IRQ disable、DMA disable、XFER STOP、clear，保首错。逻辑mask清零不作硬停证明。
3. startup/hw_params/DAI prepare/START-like拒绝sticky，不从重试/STOP/HW_FREE/close自动清除。I2S component.trigger仅预检，真正DAI再查；预检不提前启动硬件。首次fault/竞态由C3回滚。
4. 保存实际IRQ，shutdown撤销方向指针、释放I2S锁后process synchronize_irq。ISR检查INTSR read、记sticky、READ_ONCE快照，失败不使用val报XRUN。关钟前禁止入口并排IRQ，未停稳/sticky拒绝普通suspend；clock引用只释放一次。void remove/shutdown不能靠errno保devres，要具体保留/failstop策略。

## 锁与等待位置

- 本板PCM atomic。START ioctl `pcm_native.c1353–1362`持stream lock；linked action1193–1209还持其他stream locks。锁序ALSA stream/group lock→I2S lock。
- `snd_pcm_stop_xrun1544–1552`自行持stream lock；`pcm_lib.c143–155`→snd_pcm_stop→ASoC/CPU STOP。因此ISR拿过I2S锁必须释放后再XRUN，不反向拿锁。
- startup：native open2816/2725持open_mutex；`soc-pcm.c712/723–727`持card pcm_mutex，无stream spinlock。
- shutdown：native close2866–2867持open_mutex；`soc_pcm_clean654/659–660`持card pcm_mutex，无stream spinlock。实际IRQ→XRUN→STOP不获取card pcm_mutex，本板可撤销指针、解I2S锁后synchronize_irq。
- 不在trigger、ISR、I2S spinlock或ALSA stream-lock临界区等待IRQ。屏障必须覆盖ISR已捕获旧指针但还未XRUN的窗口；仅NULL不够，PL330 synchronize不覆盖CPU ISR。

## 与 DMA C3 的接线和返回值边界

冻结B `soc-pcm.c1064–1097`：START link→component→DAI，STOP DAI→component→link。generic DMA START `pcm_dmaengine.c204–207`提交/issue早于CPU XFER。
`soc-core.c1016–1044`依CPU component→codec→platform添加，本板I2S component预检早于generic DMA，但不能启动硬件。

C3必须在CPU首次START失败后停已启动DMA，覆盖失败成员未undo；CPU STOP首错仍执行DMA/component/link清理。process PREPARE/HW_FREE/close无条件checked排空，含stop_operating=false START回滚。CPU sticky与DMA poison/quarantine各自保持职责，CPU STOP成功不证明PL330 STOPPED。

`pcm_native.c1475–1483`忽略ops trigger STOP errno，2687–2691/2855–2873 close忽略释放错误返回0，CPU shutdown void。`drivers/base/dd.c1176–1183`忽略remove errno后仍devres_release_all。DROP/close/unbind rc0均不作停稳证明。

## 真实函数测试要求

- 实际clock/read/write逐点负errno，首错/后续不执行/sticky；dirty全命中read fault不能shortcut。
- clear写失败、read失败、首次timeout次次成功、双timeout；RK3568空sync_reset负对照，失败不变0。
- DMA enable后INTCR/XFER失败，rollback后STOP、重复STOP、STOP-before-START、重复START、PAUSE/RESUME；ownership不下溢，各独立关闭尽力执行。
- STOP多错首错稳定；cache先更新但硬写失败后STOP仍真正发写。
- 双向ownership/另一方向active时dirty hw_params pause/config/resume故障。暂未闭合另一DMA共享故障则只单向验收，不能宣称full-duplex。
- 用barrier停ISR于取旧指针之后，close需等ISR完成再释放runtime；IRQ→XRUN→STOP不反锁。
- suspend/close/remove IRQ屏障、clock计数、cache-sync失败恢复cache-only、无双disable。
- C3合测CPU START fail已提交DMA、CPU STOP errno仍terminate、两个独立IRQ/DMA callback屏障与实际allocation quarantine。
- 摘录参数/helper/trigger/startup/shutdown/ISR/PM/remove真实C与实际ABI，不只测试wrapper；目标内建y，最终完整Image+匹配ABI才使更改生效。
