# 私有 DMA 异步故障候选

仅修改本目录的源码副本，不操作板子、TUN 或实际 SDK。

PL330 控制器首次 sticky error 通过已初始化的 controller tasklet 排队通知。
通知先在每个 channel 与 controller 的既有锁序下借用本 epoch 的 descriptor、
callback_result 和 callback_param。必须先捕获全部 channel，再在两个锁之外调用；
第一个 PCM sink 可以联合 STOP，不能使第二个 channel 的通知丢失。
借用纳入已有 producers/refcount，因此 close cutoff 后同步等待旧通知，
不再从 descriptor 重新读取 callback 或下一 epoch。

PCM checked 实例使用 descriptor.callback_result；NOERROR 保留原 period 路径，
错误结果读取 dmaengine_check_open 的精确 cached errno，先记录首错并通知 CPU sink，
再只在异步 callback 上调用 snd_pcm_stop_xrun。prepare/START/pointer 常在 PCM stream
锁内，禁止在这些调用中递归 snd_pcm_stop_xrun；pointer 返回 XRUN sentinel。
PREPARED 无 descriptor 时，prepare/START 的 cached check 同步通知 sink 并返回首错。

generic ASoC 在实际 rtd 的单 CPU、可选 pcm_async_fault hook 上绑定 sink。
该 CPU-only hook 必须 atomic、不睡眠、撤销 START 票据并联合 STOP；不调用 codec。
NULL hook 与非 checked legacy PCM 保持原路径。

既有 pl330_sync_channel 已仅要求本 thread STOPPED 与全局 FSM/FSC 无 fault；
全局 stop_proven=false 不拒绝健康单 channel reclaim，因此这段无需源码修补。
sticky synchronize 仍先排空 software borrowers，再返回负值；两个 PCM runtime
分别拥有 quarantine，不能让一个 buffer 的隔离代替另一个。

模型执行真实窄函数体；调度、MMIO/PM、ALSA state action、CPU sink 是明确 API 边界。
不证明实际 AXI 停止、Kbuild/ABI、硬件双 START 或完整迁移完成。
