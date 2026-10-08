# C3 v8 离线整合复核

独立 rtctrl_reviewer 完成 C1/C2/C3、CPU v10 接线及 v7→v8 差异的只读功能审查，
指定范围内未发现新的确定错误，允许进入离线 Image 整合。该角色未写文件、编译、重放补丁或操作板卡。
主控另外实际重新编译、执行两项原失败触发契约及 CPU/PCM 组回滚链；三环境各82/82通过。
主控运行结果见 `build/c3-v8-root-reexecution-v1/result.json`，不是仅重新读取作者结果。

完整冻结 receipt SHA 为
`97011370d4a66b385ab3855fa9cf2f2cf4c857728a1f969902f5e8dd9b10e975`，
manifest `db9856217de3577bbfc797e0fdb38d887efd9d7072ede79a041787ec880c8e2d`，
补丁 `c2f973b6f96620b1ac307e5fa5e0632f5430a12a7accbb54cc95088c772b519c`。
独立 reviewer 和主控均核回883/883冻结文件；主控同时核250份CPU独立证据。

首次 STOP 检查先撤销旧缓存，全物理线程与 manager 成功才在 controller lock 内 capture；
部分 STOP 失败没有发布成功 proof。新 ready2 夹具从真实 amba_probe 调用 pl330_probe，
首次 ready 不人工设置缓存。模型仍替代内核 API 叶函数和真实寄存器。

新 device_check_open 只读 sticky/closing/removing/suspended，在约束、prtd 和 quarantine token
分配前拒绝。checked 缺回调返回 EOPNOTSUPP，unchecked 旧 provider 保持 open=0。
真实 generic-held-channel poisoned reopen 被原 sticky errno 拒绝，没有 PM/MMIO/GO/KILL。
该回调与 helper 不受 CONFIG_NO_GKI 包围；只验证当前 CONFIG_NO_GKI=y，不承诺外部 GKI ABI。

IRQ 前初始化、reader 排空、DMA/OF 发布撤销、连续 descriptor 块按基址释放、客户 cutoff、
quarantine 与模块引用、ASoC START 已尝试前缀回滚和 STOP 全员首错传播的生产接线保持一致。
主控支持范围为 FD 关闭后注销的 PCM 生命周期；不承诺裸 DMA 客户违反引用存活条件的并发释放。

生产完整十二补丁严格重放23文件、13个C3源码及CPU源身份匹配；十二实际ELF64 AArch64对象、
十二实际.cmd及四步配置/构建返回0。作者八套三环境各183/183；独立 reviewer核查身份，未独立执行。
主控新增实跑三套：ready2 14、held-open 21、CPU/PCM组47，host/ASan+UBSan/static AArch64 QEMU均通过，
ASan leak检查开启。新鲜编译和实际argv/stdio/binary SHA全部保存在主控结果中。

本结论尚不代表完整 Image 链接、精确 codec ABI、真实 PM/MMIO/AXI/STOPPED、软件排空或板端 START
通过。当前仅放行离线整合；硬件步骤仍按 INTEGRATION-PLAN 分阶段验证。
