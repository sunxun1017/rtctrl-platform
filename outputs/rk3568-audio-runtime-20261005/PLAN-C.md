# DMA 生命周期 C 阶段设计交接

2026-10-05 独立只读架构审查结论。设计候选，尚未实现、构建或板测。
实现责任为 `outputs/rk3568-dma-lifecycle-20261005/` 和公开 `0011` 补丁；在冻结
`outputs/rk3568-asoc-errors-20261005/driver-source-v2` 上增量，不覆盖 0006–0010。
先真实函数红证据与屏障测试，再候选实现/独立审查/完整 Image，仍禁止上板 START。

## 源码和硬件边界

内核 commit `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`。
`drivers/dma/pl330.c` SHA256
`8fa1c9f54d7ef9bdd6ce2fedf356144db31f5e1d1f1005e3a0365b1f8b0e5627`。
PL330 两个控制器在锁定 rk3568.dtsi 与真实显示 DTB
`650228482eaed6f95d9892fce217f436072d851cc47398696d52b85e08200f70`
中均没有 iram、iommus、resets、reset-names。`reset_control_assert(NULL)` 返回0
不是实际复位证据。不得补未经确认的 SRST 或搬用现有 remove 的 optional reset 当 failsafe。

正常 STOPPED 后才回收；硬停超时则隔离 PCM allocation、对应 thread/microcode/event/PM 引用，
sticky 禁止该控制器再分配/准备/提交/GO，保留至冷启动。软件回调未排空不能只保留 buffer 后继续 close。

## PL330 字段、锁和所有权

- channel：epoch、QUIESCING/POISONED、retired_list、runner_active/rerun、已排队 tasklet 标记、
  producer 计数、waitqueue、仅 process context 用的 sync_mutex、独立 pm_ref_held。
- descriptor：不可变 owner_pch/owner_epoch、refcount_t refs。准备/队列有一份 owner 引用；
  IRQ、fault、runner 锁外使用前各借一份。get_desc 得到准备事务引用；tx_submit 成功才转交
  submitted 队列。未提交链不被 terminate 当作已提交链回收，失败 submit/prepare 自己归还。
- thread：controller 锁保护 callback 接受门闩和 owner epoch；硬件停止证明单独记录。
  req_running=-1 不能代替 STOPPED。
- controller：sticky 故障；硬停失败保留仍被硬件持有的 thread/event/mcode 和 PM 引用。

锁序 `pch->lock -> dmac->lock`。IRQ/fault 不反向取 channel 锁，在 controller 锁内借 desc 引用，
解锁后交 rqcb。公共池统一 release helper 拿 pool_lock，不嵌套 channel/controller 锁。
callback、等待、PM put 全部在这些 spinlock 外。

## terminate 和同步

1. 原子 terminate 先关 channel/thread 门闩、推进 epoch、屏蔽事件，摘除 request 和 req_done
   发布入口；submitted/work/completed 转 retired，不归公共池，不释放 microcode，不丢 PM 引用。
2. pl330_update 在解 controller 锁前为捕获 desc 借引用；pl330_dotask 一次捕获两个 request 并借引用。
   解锁后不能再取可能被新 epoch 改写的 thrd->req[].desc。迟到 rqcb 在 channel 锁下判门闩/epoch，
   拒绝并放借用引用。producer 排空必须覆盖 IRQ 和 controller fault tasklet。
3. direct issue_pending 和 tasklet 共用 runner 入口，channel 锁内取得唯一执行权；已有 runner 只置 rerun。
   callback 前保留 desc 引用，callback 后重新判 epoch/门闩，从当前队列重新取对象，不能继续旧 _dt。
4. process 同步持 sync_mutex，不持 spinlock/PCM stream lock；等待 producer、direct/tasklet runner
   和已排队 tasklet 退出。tasklet_kill 只作最终资源销毁补充，不能单独证明所有路径排空。
5. _execute_DBGINSN 返回 errno，所有 UNTIL 改有截止处理。KILL 是停止请求，进程阶段仍要读真实
   channel STOPPED。可审查的初始截止候选：DBG 5ms、STOPPED 20ms、软件排空500ms，均未硬件测量。
6. STOPPED 与软件排空均成立才放 retired owner 引用/归池/PM put。STOPPED 超时保留全部并 POISONED。

## ALSA buffer 必须真正退役

真实路径：component sync_stop 为 int，但 pcm_native 的 snd_pcm_sync_stop 为 void，先清
stop_operating 后丢弃回调 errno；do_hw_free 即使 hw_free 失败也 free managed buffer；
soc-component hw_free 汇总为 void；close 忽略释放错误，仍 free prtd/runtime。
因此仅返回 terminate/hw_free errno 无法保存硬件可能写入的 allocation。

正常 managed-buffer 路径保持。snd_dmaengine_pcm_open 在 START 前预分配 quarantine_token，
失败拒绝 open。token 独立于 prtd/component/card。pcm_memory 增受限所有权转移 helper，
前提软件 callback 全排空且 buffer 操作串行化/独占 close。

- runtime->dma_buffer_p 指向嵌入 substream->dma_buffer 时，整份 allocation 元数据复制进 token，
  清原 area/addr/bytes/private_data，保留 dev 配置。
- 动态 snd_dma_buffer 直接转交指针，不能 kfree。
- snd_pcm_set_runtime_buffer(substream, NULL)，token 进入 ALSA core 永久 quarantine list，持 DMA
  device 引用，card total_pcm_alloc_bytes 转入独立 quarantine_bytes 账本，不依赖已销毁 card。
- 不调用 snd_dma_free_pages。native managed free 和 card preallocate free 只能看到空旧 owner。

本轮限已核实的本板 SNDRV_DMA_TYPE_DEV coherent allocation。未知 allocator 在 START 前拒绝，
不能停止失败后才猜如何保留。每故障 channel 最多保留一份，sticky 门闩防增长，不自动恢复/释放。

## checked API 和调用接线

新增 BSP 内部 optional device_synchronize_checked，保留既有 void API：

- 0：硬件 STOPPED 与软件排空都成立。
- 负值：软件完全排空，但硬停未证明，调用方必须退役 allocation。
- 软件排空超时：不能正常返回让 close free runtime，必须明确内核 fail-stop，禁止自动 warm reboot
  或旧 RAM 复用。buffer quarantine 不能代替 callback 排空。测试和本轮启动参数必须符合此边界。

PL330 void wrapper 调同一实现，失败不能假成功返回；受保护 PCM 直接 checked API。
两套 generic component 都装 sync_stop，同时 prepare/hw_free/close 同一 process helper，覆盖
stop_operating=false 的 START 失败回滚。close 先排空/退役再 free prtd；sticky 错误拒绝后续
open/HW_PARAMS/PREPARE/START。void 链不保证显式 HW_FREE errno，不能据其0称恢复。
START 检查 submit cookie；GO 失败由 provider 错误状态返回并异步停止。
soc_pcm_trigger 的 START 部分失败须独立停止已启 DMA（含 native 不做失败成员 undo 的路径），
STOP 保留首错仍继续 component 清理，避免 CPU DAI STOP 错误跳过 DMA。

free_chan_resources/remove/suspend 同样遵守隔离，POISONED suspend 拒绝；销毁故障控制器不能进
pl330_del 后继续 free devm/mcode。真实 DMAC/OCP reset 与 AXI 清空/共享 owner 属后续独立验证。

## 实际构建与必测边界

修改面：pl330.c、dmaengine.h、pcm_dmaengine.c、dmaengine_pcm.h、pcm_memory.c、pcm.h、
soc-generic-dmaengine-pcm.c、冻结 B 后的 soc-pcm.c。当前相关 config 都 y，实际连入 pl330.o、
snd-pcm-dmaengine.o、snd-soc-core，必须完整 Image，不能外部 module 冒充生效。
Rockchip CPU I2S trigger 的错误传播仍须明确解决或证明本轮路径不涉及，见 NEXT-DMA.md。

至少用真实函数和明确屏障覆盖：cyclic callback 暂停/terminate/跨 channel get_desc；
IRQ借ref迟到rqcb；fault捕获两个request迟到；directrunner与tasklet竞争终止；noncyclic归池
前所有ref释放；submit/GO后CPU START失败（含linked失败成员）；STOP CPU失败仍DMA清理；
DBG timeout/长期KILLING/STOPPED timeout对动态和嵌入buffer的永久退役、managed/cardfree不释放；
DROP->PREPARE/重复HW_FREE/close无重复转移/计账/PMput；softwaredrain截止及remove/suspend不UAF。

## 锁定官方依据

本次核查截至2026-10-05，链接均固定 commit；上游“仍无完整修复”只限所列快照。

- [Linux v5.10，2c85ebc57b3e1817b6ce1a6b703928e113a90442](https://github.com/torvalds/linux/commit/2c85ebc57b3e1817b6ce1a6b703928e113a90442)，2020-12-13。
  vendor DBGINSN/_stop/rqcb/dotask/terminate/issue对应函数逐字相同。
- [descriptor复用清callback_result，4728e3fe2ff1b02b84ddab876d8af5eeb74eee18](https://github.com/torvalds/linux/commit/4728e3fe2ff1b02b84ddab876d8af5eeb74eee18)，2024-01-22。
- [等待WFP补丁22a9d9585812440211b0b34a6bc02ade62314be4](https://github.com/torvalds/linux/commit/22a9d9585812440211b0b34a6bc02ade62314be4)，2023-12-22；
  [因回归撤销afc89870ea677bd5a44516eb981f7a259b74280c](https://github.com/torvalds/linux/commit/afc89870ea677bd5a44516eb981f7a259b74280c)，2024-03-28。不能盲回移无限等待。
- [PL330固定0d3e3376b289cdaff5b3b6c1581999926ff1000f](https://raw.githubusercontent.com/torvalds/linux/0d3e3376b289cdaff5b3b6c1581999926ff1000f/drivers/dma/pl330.c)，2026-07-02，SHA
  `7241bf8e4258b5653480ac6366b6e5b6460e5b323a3ca459e5b428db1719f69b`，无device_synchronize/vchan完整接线。
- [v5.10 virt-dma.h](https://raw.githubusercontent.com/torvalds/linux/2c85ebc57b3e1817b6ce1a6b703928e113a90442/drivers/dma/virt-dma.h)，与锁定vendor逐字同，terminated+同步后释放原则，调用者须先阻止新callback。
  vendor cyclic改为per-desc cyclic/work_list，不能直接换上游channel-wide实现。
- [ARM DDI0424D](https://documentation-service.arm.com/static/5e8e25befd977155116a5ad9)，文档ID072812、PDF SHA
  `ab5a380b1866a24e297027670a8824cc2c9dd418e69b4a86415dc1647d3e29e5`。
  §4.3.6 DMAKILL须等channel ID AXI事务完成/清队列后进入Stopped，支持用真实STOPPED作为回收条件。
