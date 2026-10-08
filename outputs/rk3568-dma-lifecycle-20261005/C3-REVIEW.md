# C1/C2/C3 冻结审查入口

**v5 已否决**：独立审查复现 probe 中 IRQ 发布早于 pl330_add 初始化 controller
lock/req_done/threads；AMBA probe 入口已 powered，pending IRQ 进入 update 后
访问零初始化链表导致 SIGSEGV/ASan SEGV。下述 165 项已有通过证据未覆盖这条
路径，不能放行此候选。独立失败 stderr/fixture 在冻结 `red-evidence/independent-probe-irq`
保留；需另立新版本修正 publication 与失败逆序清理，不覆盖本 v5 或 production-v6。

候选 `driver-source-c3-v5` 保持原文件许可证，只修改生产函数与内部字段/API。
PL330 SHA256 为 `6ad96f3e3920375bbcc0f2df508d371db1a2c0d6caa3b78d93a63717ca4d7f45`，
私有 0011 增量 SHA256 为 `7258cc28f4da806c9d9cc5d138e7a4ec5a0b8981647190210794620e2f7568ef`。
公开 0001–0010 保持精确锁定；0011 从该公开串之后重放。原核提交为
`9f9e9d18574d0914c0d192a90c3babfe1fd63c95`，生成/编译前后检查其工作树干净。
CPU 由另一作者负责，本组合绑定已审查的 v10：
`outputs/rk3568-i2s-lifecycle-20261005/driver-source-v10/sound/soc/rockchip/rockchip_i2s_tdm.c`，
SHA256 `cbd19c1a8b128d442f6321ebb9ce1d51524633536282862b6c06fa76b4f77b59`，
独立 CPU 补丁 SHA256 `ec857605a70abccce88ac71c1e5070b866fb245717ad90ae0db2af26fc9aa495`。
两份补丁单独保存。没有创建公开 0011，也没有构建 Image 或操作硬件。

冻结源的 manifest 保留生成时的未验证状态；本次验证结果以冻结 receipt 和下表中的
最终 result.json 为准。历史候选、红绿结果和生产编译失败都保留；旧 CPU v9 合测及
未执行真实 PRE_START 的 v7/v8 合成结果不能替代最终证据。

| 最终结果目录 | 每环境通过数 | 真实路径与边界 |
|---|---:|---|
| pl330-c3-tests-green-v2 | 67 | 实际队列、IRQ/fault、prep/epoch、直接启动、回收、checked、PM、free/remove；fake kernel 原语与状态接口 |
| pl330-c3-hw-tests-green-v1 | 17 | 实际 DBG/state/start/stop/deadline；寄存器与单调时钟模型 |
| pl330-debugfs-tests-green-v4 | 2 | checked profile 不发布旧 raw-owner debugfs 文件 |
| dma-admission-tests-green-v4 | 9 | 实际 core 注册/get/引用/关闭入口同 mutex；该 core 与最终源逐字一致 |
| trigger-cpu-tests-green-v5 | 47 | native、真实 ASoC group/helper、PCM/allocator；CPU v10 实际 precheck/ownership helper，provider API 边界注入 |
| dma-pcm-tests-green-v9 | 17 | 同一 TU 连通真实 native PRE_START/START、ASoC、DMA API/PL330硬件函数、PCM分配/隔离、core channel put；MMIO及CPU I/O故障边界注入 |
| core-lifecycle-tests-green-v2 | 6 | 实际 device/sysfs/kernfs active/remove/drain、module get/stop；单 attribute leaf、等待/timer 原语 |

合计每环境 165/165，环境为 host、ASan+UBSan、静态 AArch64/QEMU。每份结果都保存
完整输入源码、逐字函数摘录、真实 ABI/常量、独立可编译 TU、harness、编译与执行
参数、二进制/stdout/stderr 哈希。编译器和所有参数以 result.json 为准。极小 FIFO
codegen 叶与内核原语由 fixture 提供；没有声称真实 AXI 写入已排空。

`production-v6` 对精确 0001–0010 + 私有 0011 + CPU v10 私有 0012 串完整重放，
逐字核对 13 个 C3 生产文件和 CPU 源，使用板级实际配置及 AArch64 GCC 11.4
完成 12/12 Kbuild 对象：PL330/DMA core、PCM core/memory/engine/native/memalloc、
ASoC pcm/component/dai/generic 与完整 CPU I2S 对象。冻结保留 `.config`、实际
`.o.cmd` 编译参数、对象和构建日志。它证明当前生产 ABI 编译，尚未证明最终
Image 链接或外部 codec 模块 ABI；这两项由主控进行。

C1 使用 pch→controller 锁顺序，池/PM/回调/等待在相应锁外；refs 与不可变 owner/epoch
隔离旧 callback，首错/负 PM 门闩挡住真正提交/GO/IRQ推进。terminate 的 pre-PM
operation ticket、direct/queued runner ticket、IRQ/fault/prep/GC lease 纳入有界 drain。
软件排空失败不能返回并让 close 销毁 runtime，进入 panic_timeout=0 failstop。
硬件 STOPPED 失败但软件已排空时，descriptor/thread/mcode/PM 保留，错误 sticky。
无已证明 reset；不使用 NULL reset 伪成功。free_chan、void synchronize、remove 的失败
通过 failstop 阻止后续析构；不依赖 errno 阻止 devres_release。remove 的 client gate
与 core get 线性化，无 client 后仍要求 manager/channel 与所有软件用户排空。
普通 AMBA shutdown 未新增 remove/double-free 路径。

C2 仅在安装 checked callback 的 PL330 PCM 上启用 coherent DEV/no-IOMMU 元数据
校验。open 预分配 token；buffer 只有真正暴露给硬件才成为危险 owner。HW_PARAMS
resize/free、prepare/hw_free/close 都经过 process guard；失败 START 且
stop_operating=false 也不能绕开。硬件停稳失败时把实际动态 snd_dma_buffer 或嵌入
buffer 元数据转入永久 core owner，清 runtime/嵌入旧 owner，持 device 引用并调整
card/global 字节计账；token 无 runtime/card/prtd/callback 指针。旧错误即使随后
checked 成功仍保留，未知 allocation 在 START 前拒绝。其他 DMA provider 沿其旧
void synchronize API 契约，本补丁没有重新验证其硬件安全性。

C3 START 组失败回滚已尝试前缀，包括失败成员，保留未尝试成员/另一已运行 stream；
外层回滚此前已完成的 group/link。STOP 继续全部成员与 component，保存 CPU 第一
错误并仍清理 DMA。顺序保持 direct DMA-before-CPU。合成用例断言真正 PRE_START
及 GO/暴露发生后再注入 CPU 故障；checked 隔离或正常排空由真实 provider 完成。
CPU 第二方向 START -EBUSY 与未 owned STOP 不改变旧方向；本轮仍限定单向。

常规 card/codec 退出证据：真实 native release + managed/preallocate free 后，真实
generic unregister→dma_release_channel→dma_chan_put→PL330 void checked sync/free_chan，
最终无私有 descriptor/PM owner/poison；在真实 IRQ period_elapsed barrier 内 close
等待旧软件回调返回后才释放 prtd。故障用例实际 void sync failstop，component/thread/PM
未销毁。ASoC unregister 边界观察旧 runtime/area 已清；没有模拟整个
ALSA device_disconnect 与新 open 的并发组合，主控须先关闭真实 FD，再注销 card。
零 quarantine/无 FD 不能单独替代 CPU+DMA 的停稳证明。

只读状态、真实 kernfs drain 的 500ms owner 存活 timer、del_timer_sync 锁关系以及
永久 quarantine 为什么 pin snd-pcm 模块，见 `READONLY-SCOPE.md`。普通读取不启
timer、不访问 MMIO或PM；读快照不会恢复 sticky 或授权新 admission。当前板级
SND_PCM/SND_DMAENGINE_PCM/PL330 为 built-in；强制卸载不在本契约内。
panic_timeout=0 保证内核不会主动自动 warm reboot，不能保证外部 MCU/watchdog 不 reset。

复验在本责任目录运行，各脚本要求新 label/revision，保留旧结果。源码与 CPU 使用
上述精确路径；命令如下（`vN` 需选未使用版本）：

```sh
python3 test-pl330-c3.py --source-dir driver-source-c3-v5 --label green-vN
python3 test-pl330-c3-hardware.py --source-dir driver-source-c3-v5 --label green-vN
python3 test-pl330-debugfs.py --source-dir driver-source-c3-v5 --label green-vN
python3 test-dma-admission.py --source-dir driver-source-c3-v5 --label green-vN
python3 test-asoc-cpu.py --source-dir driver-source-c3-v5 --cpu-source ../rk3568-i2s-lifecycle-20261005/driver-source-v10/sound/soc/rockchip/rockchip_i2s_tdm.c --label green-vN
python3 test-dma-pcm.py --source-dir driver-source-c3-v5 --label green-vN
python3 test-core-lifecycle.py --source-dir driver-source-c3-v5 --label green-vN
python3 build-production.py --source-dir driver-source-c3-v5 --cpu-dir ../rk3568-i2s-lifecycle-20261005/driver-source-v10 --revision vN
```

冻结目录内的 TU 与所有 local includes 自含，可直接按保存的编译参数更换 TU/输出
路径复编。generator 快照记录工作区产生过程，不声称移动 generator 后其相对
工作区输入路径自动改变。`original-inputs`、`patch-inputs`、`full-replay` 和严格重放
receipt 提供独立的补丁评估入口；SHA drift、上下文篡改、偏移重放均拒绝。

未完成：整组独立审查、主控完整 Image/外部 codec 模块 ABI、板端单向硬件验证。
未授权发布或板端 START；不提供 full-duplex、活跃解绑恢复、强制卸载、未知
allocator/IOMMU、poison 后普通 warm reboot 或外部 watchdog 保证。
