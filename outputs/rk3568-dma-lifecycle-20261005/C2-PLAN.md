# C2 PCM allocation 所有权

C1 输入固定 `driver-source-v15` / `C1-review-v2/receipt.json`，不覆写冻结文件。
B 输入仍为 `rk3568-asoc-errors-20261005/driver-source-v2`。本阶段保持板端 START 禁止。

真实 `snd_pcm_hw_params` 在释放 stream spinlock 后调用同步和 managed malloc；
`stop_operating=false` 的失败 START 跳过现有 `snd_pcm_sync_stop`，但 resize 能在
component.hw_params 之前释放旧 dynamic buffer。仅增加 component prepare/hw_free/
close/sync_stop 不能保护该路径。给 checked provider 的 DMA PCM runtime 安装
内部 process `dma_quiesce` guard，真实 pcm_memory malloc_pages 在任何 resize 前
调用；free_pages 调用后继续清理不曾 exposed 的新 buffer并保留 guard 首 errno。
普通 provider guard=NULL，保持原同步 API 契约。quiesce 不调用 allocator，避免
guard→quiesce→allocator 的递归；锁序为 runtime process mutex→provider sync mutex，
不能持 PCM stream spinlock。close 清 guard/private_data 后才释放 prtd。

open 先分配 opaque permanent quarantine token。START 前查实际 runtime dma_buffer_p
为 SNDRV_DMA_TYPE_DEV coherent、private_data=NULL、匹配 provider device、无 IOMMU，
实际 area/addr/bytes 与 runtime 一致。DEV_IRAM 请求实际 fallback=DEV 用真实 allocator
函数验证，不以请求枚举判断。未知 allocator 在任何 prep/submit/GO 之前拒绝。
submit 检查真实 dma_submit_error；成功 cookie 后标记 allocation exposed，issue 后
provider DMA_ERROR 作为原 void GO 的失败观察，process checked 再取得 provider errno。

process quiesce 无条件覆盖 stop_operating=false，负返回已由 C1 保证旧软件全部排空。
保存首次负 errno。若 exposed，将当前 allocation 元数据与 START 保存的 owner 核对；
发生未经保护的替换时 fail-stop，不释放未知 owner。嵌入 buffer 复制到 token并清完整
旧 embedded owner；动态 snd_dma_buffer 指针本体交给 token，不 kfree。清 runtime
aliases，持 device ref，card total bytes 转移到 core 独立 quarantine bytes/list。
token 不持 runtime/card/substream 指针，任何后续 close、managed/card free不能看到
已退役 allocation；token consumed 后永久留存，不在故障时新分配。

已有 first error 后继续 checked 清理，但不能把表面成功当已恢复；返回 first errno。
未 exposed 的新 buffer 可正常错误清理。两 generic component 表均接入 sync_stop、
prepare、hw_free；close 同 guard。DMA channel free/driver remove 未能转移调用者所有权
时沿 C1 fail-stop，不因 quarantine 成功就提供活跃 card/provider unbind 恢复。

TDD 真函数链包括 open/START/submit/trigger、core malloc/free、set_runtime_buffer、
真实 snd_pcm_hw_params 的 failed START→resize 路径、dynamic/embedded/card free与
generic hooks。记录原始红、host/ASan+UBSan/static QEMU 绿和 SHA。只 fake kernel API、
allocator/MMIO 边界。生产 ABI 完整构建、C3 trigger rollback、只读 poison/quarantine/
lease/STOPPED 并列证明尚待闭合；内核 panic_timeout=0 不保证外部 watchdog 不 reset。
