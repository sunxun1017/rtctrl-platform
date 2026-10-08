# DMA 异步故障候选交接

最终待 root 整合的是 **source-v5**，四文件补丁
[dma-fault-private-v5.patch](dma-fault-private-v5.patch)，输入身份见
[source-manifest-v5.json](source-manifest-v5.json)。最小 CPU-only 新字段单列为
[soc-dai-async-hook.patch](soc-dai-async-hook.patch)，基于已固定的 params source-v4 header；
由 root 合并。CPU 实现由 TRCM 作者负责。

新 controller 首错 tasklet 将同 epoch 的所有 descriptor callback_result/param
先借用，再在 channel/controller 锁外通知；producer/refcount 计入 synchronize drain。
CPU fault sink先撤销 admission/ticket，再做异步 channel XRUN。普通 NOERROR period 路径保持。
PREPARED 没有 descriptor，使用真实 prepare/START/quiesce 的 cached accessor 通知 sink。
同步 trigger/pointer 不递归 snd_pcm_stop_xrun；pointer返回 XRUN sentinel。

DMA_ERROR分支重新读取精确 cached errno，避免 tx_status自己新发布故障后先记成 EIO。
同步排空期间新出现的错误同样通知 CPU sink，再按真实 quarantine 规则分别隔离两 allocation。
正常 channel退出仍使用已有本 thread STOPPED 与 FSM/FSC规则，peer运行不要求全局 stop_proven。

最后实际证据：

- [旧实现 red-v7](runs-red-v7/receipt.json)：三个环境 compile0/execute1，37有序边界观察中9通过、28红。
- [同步窗口旧候选 red-v1](runs-sync-red-v1/receipt.json)：source-v4同37观察，36通过，遗漏同步期间新错误的CPU通知；三个环境实际红。
- [最终候选 green-v7](runs-green-v7/receipt.json)：host、ASan+UBSan、AArch64 QEMU均 compile0/execute0，37观察全部通过，stderr空，三完整stdout逐字相同。
- [最终有限回读](review-ready-v2.json)：上述实际命令/有序观察/完整输出、四源码和七个 actual SDK输入前后全SHA保持；仅在本目录四文件副本实际 check/apply，结果逐字等于source-v5。v7只补fixture销毁所有已初始化mutex，避免下一scenario重新初始化旧mutex；source-v5与旧v6实际输出保持。

37项是有序边界观察，不能称37个独立业务用例。真实函数体包括PL330通知/同步、PCM
prepare_and_submit/trigger/pointer/quiesce、quarantine，以及generic open和CPU sink绑定。
已有完整结构ABI未在该模型中重建；类型shape、调度、PM/MMIO、ALSA state action、CPU
fault hook与generic core open/close/约束是明确API夹具。PL330 terminate_channel为显式cutoff
边界，完整真实sync/drain体执行；不得称完整PL330硬件调用链已执行。

两buffer由真实quarantine元数据路径各自转移，模型最后的释放明确代表随后power-cycle；
不是驱动出错后恢复、真实DMA停止或板端缓存一致性的证明。

旧v1–v4源码/输出保持。初次red-v1的sign-compare编译失败、真实dotask首次queue-red-v1
遗漏__iomem模型注释的编译失败均原样保留。source-v1的status首次0→新fault errno race，
source-v2的fanout期间新queued标记覆盖，分别在后续版本修正；queue-red-v2实际35观察只有
该queued窗口一项红，source-v3实际35全绿。source-v4仅改明确LF/noBOM字节输出。
make-source最初一次在任何四文件输出前因非唯一epoch锚点拒绝，工具返回有记录，未单独保存
完整shell stderr；不能称该初次准备失败已完整封存。

仍需 root 独立审查、合并CPU hook、真实Kbuild/Image与新联合模型。没有修改actual SDK、DT、
公共补丁或旧Image，没有板操作、第二START、TUN操作或全迁移完成结论。
