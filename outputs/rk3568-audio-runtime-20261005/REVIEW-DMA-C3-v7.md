# C3 v7 拒绝原因与保留证据

独立只读 reviewer 沿实际 AMBA/provider 和 generic-held-channel PCM 调用链发现两项确定缺口，
作者随后增加真实函数夹具复现。v7 manifest 为
`c2f709c52e08af28ab9357c5b377e1c7c1c52a7e10b209fd9aa397e4aa1eea02`。

1. 首次全 controller STOP 成功没有写入缓存证明，AMBA wrapper 返回、PM usage=0 后
   第一次 readonly show 为 ready=0/stop_proven=0/stop_reads=0。
   ready2 三环境各13/14，唯一失败为首次 ready；部分 manager STOP 失败拒绝路径成立。
2. 永久 STOP 超时、quarantine 和 close 后，generic 仍持有的同一 channel 可重新 open 返回0。
   后续 prepare/START 仍拒绝，但 open 没有在 prtd/token 分配前返回原 sticky errno。
   held-open 三环境各19/21；还需明确 checked provider 缺 callback 的拒绝契约。

这两项使 v7 不进入最终 Image 整合。旧测试、源码和日志保留在 DMA 任务目录，
新冻结包 `C3-review-v2/receipt.json` 的 red-evidence 与 prior-source 清单绑定其完整 SHA。
只读审查本身没有执行测试；上述执行结果属于新增夹具的作者实测。

支持的 PCM 调用链以 prtd.operations 包住 prep/submit 及拒绝 giveback，process quiesce 等待
operations=0 后才 close/unregister/release。裸 DMA 客户在 tx_submit 仍执行时交还最后通道引用
不属于本轮承诺，不据此扩张补丁范围。相同源与结果的完整身份在 v8 冻结包中保存。
