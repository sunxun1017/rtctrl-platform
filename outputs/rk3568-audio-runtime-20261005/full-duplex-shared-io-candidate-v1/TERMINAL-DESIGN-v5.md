# checked codec 终端生命周期候选 v5

可整合源：[source-v5](source-v5/)。它保留 source-v3 的外围 I/O/PM 改动，追加
codec terminal/probe 与 ASoC 显式关机 helper；CPU 仅修正 runtime_suspend 的
sticky errno 优先顺序。七源身份见 [source-manifest-v5.json](source-manifest-v5.json)，
对 source-v3 的四文件增量见 [terminal-private-v5.patch](terminal-private-v5.patch)。
新增 soc.h 的基线是已接受 SDK 文件，不包含其它 header 修改。

## 生命周期与锁

`snd_soc_component_shutdown_card(dev, exact_driver, timeout_ms)` 只由 checked
codec platform.shutdown 显式调用，process-only。默认 codec/card 不调用它。
helper 采用真实 `snd_soc_unregister_card()` 的锁序：client_mutex 稳定组件和卡，
调用内部 `snd_soc_unbind_card(card, false)`。不重入持同一锁的 public unregister，
不在锁外读取 component->card。等待既有文件释放时不持 card->mutex 或私有
params_lock：真实 DPCM close 需要 card->mutex，后者也会阻碍正常 codec close。

helper 验证组件 driver 指针后调用 `snd_card_disconnect()` 关闭 ALSA file 准入，
再在 files_lock 下用真实 wait_event_lock_irq_timeout 等 files_list 为空。
timeout 参数限 1..5000ms；codec 使用 5000ms。disconnect 是正常 ALSA API，包含
设备/fops/IRQ 等副作用；这里没有声称它是纯谓词或失败前无平台副作用。
超时或 disconnect 错误不进入 card cleanup，保持仍被借用的卡/组件资源。
void platform.shutdown 沿现有 CPU failstop 政策设置 panic_timeout=0 后 panic，
不返回给 device_shutdown，也不冒称恢复。

drain 成功后走原内部 unbind → flush work → cleanup。原 cleanup 再次
disconnect_sync（文件已空），继而 DAPM、link DAI/component remove、rtd/aux/card
free。component.remove 执行 codec quiesce 和 detach。只文件等待有上限；现有
flush work 与 snd_card_free 保持原框架阻塞边界，整个关机回调不保证 5 秒上限。

普通 platform.remove 先检查本 codec 已知 FAULT/retained，然后走原
snd_soc_unregister_component。真实 DAI unregister 仅删除列表节点；devm 对象
在回调返回后释放。原 card cleanup 的 disconnect_sync 等完整 ALSA file release
结束，之后才到 component.remove。该普通移除等待仍是原框架的无界等待。
仅 shared_open/params 为空不能证明整个 PCM close 已退出：DAI shutdown 之后
还有 link shutdown、components close/DMA drain、post-unlock PM，再到 file_remove。

`shutdown_started` 是独立永久关机 latch，在进入 helper 前于 params_lock 内设置。
它只阻新 startup 和 component probe，不阻在途 HW_FREE/mute/DAI shutdown。
`terminal_started` 在 drain 后的 component.remove 中设置，用 params_lock 排空
本 codec 的 checked body，然后禁止所有新的本端借用。锁序为
params_lock → clk_lock。unbind(false) 按原框架将卡放到 unbind_card_list；关机 latch
保证意外 re-probe 在首 I/O/首 lease 前 ESHUTDOWN，未声称取消全局 rebind。
以后 machine unregister 对该未 instantiated 卡执行原 list_del；模型检查一次
删除且不重复 cleanup。普通健康移除后可开始新 probe 生命周期；关机后不重开。

## I/O、clock 与首错误

健康 terminal 需要无 pending/params owner/open、无 params_error/mute_error、
无 retained_clock，path 计数合法且 probe lease 已实际获得。checked power_down ALL
的每一笔 I/O 全部成功后，才归还实际 playback/capture path refs 和 probe ref，
发布 OFF/计数零/terminal_done，再由 component.remove 清空 regmap/component borrow。
重复 shutdown/remove 没有重复 I/O 或 ref return。

FAULT、retained lease、或任一 terminal I/O 不确定时保留首 errno、映射、路径计数、
实际 clock refs，执行不返回的硬失败。普通 remove 的 void component callback
不能通过 EBUSY 阻止后续解绑；这里也没有使用这种返回约定。局部前置检查只涉及
codec 的已知错误，其它组件的联合 FAULT/quiesce 仍由主控整合边界负责。

checked probe 在首需要 clk_lock 前初始化它。两次只读或 clock 获取失败、且还未
执行 reset 写入时，可正常 detach 返回原 errno；未得到 clock 时不伪造 probe ref。
reset 任一写入错误硬失败，保留实际 probe ref。reset 成功后 controls 注册失败，
仅完整 checked power_down ALL 成功才能归还 ref/detach 返回原注册 errno；cleanup
另一个错误不覆盖注册的首错误，也不作为恢复证明。已有 FAULT 不允许 reinit 掩盖。

## 本次实际验证

同一固定 1471 项 schedule：

- [旧 source-v3 / model](model-terminal-framework-old-v2/manifest.json) 与
  [旧运行](runs-terminal-framework-old-v1/receipt.json)：三个环境各 1260 过、211 红，
  compile exit0、program exit1。新增 terminal/cleanup 故障 sweep 使用固定 20 笔
  ALL power_down、12 笔 reset，不因旧实现缺 cleanup 而跳过失败项。
- [新 source-v5 / model](model-terminal-framework-new-v2/manifest.json) 与
  [新运行](runs-terminal-framework-new-v2/receipt.json)：host、ASan+UBSan、AArch64
  static QEMU 各 1471/1471，compile/run exit0，stderr 空，各边三份完整 stdout
  字节相同。另无 CONFIG_PM_SLEEP 的有限源切片实际 compile/run exit0。
- 模型提取 53 个真实函数；包含实际 soc_remove_component、card cleanup/unbind、
  新 helper 和原 SDK snd_card_disconnect_sync。原 SDK init.c SHA 固定在 manifest，
  每轮执行前后校验。list/文件、disconnect、wait 时序、DMA close、card_free、CCF/
  I2C/GPIO 仍是明确的 primitive fixture；不是完整内核布局或实际板硬件执行。
- 检查 active file 在 DAI close 前，以及 shared_open 已清空但 component close/
  file release 未结束的两个窗口；drain 前仍可执行真实 HW_FREE/mute/shutdown，
  不提前失去 component/clock borrow；超时没有 cleanup、codec I/O 或 ref return。
  同时覆盖 driver identity、默认路径、unbind list 后续删除、重复调用、关机 rebind
  gate、每笔 terminal/reset/controls cleanup 故障、CPU sticky+owner+format_release。
- [第一次 framework new-v1](runs-terminal-framework-new-v1/receipt.json) 编译因有限
  安全迭代 fixture 没消费 n，触发 -Werror=unused-but-set-variable。修 fixture 后新建
  v2 模型重跑，未压低警告，未改 source-v5，失败记录保留。

此前 source-v3 的 1111 检查与 source-v4 的局部 terminal 草案及全部运行原样保留；
局部草案不能证明完整 PCM caller drain，由 v5 的实际 core 顺序模型补上这条边界。

本 agent 未执行 Kbuild/Image/DT/板操作。主控单独报告已实际对象 Kbuild，证据在
build/root-audio-integration-v5/trcm-terminal-objects-v1/receipt.json；该验证由主控
整合源负责。本结果不证明所有设备的 Linux 关机、联合故障物理恢复、DMA/CCF
实际电气状态、模块最终装载或新 Image 验收，也不授权全双工 START。四个旧
dual START/共同 STOP 红例仍由整链模型保留。
