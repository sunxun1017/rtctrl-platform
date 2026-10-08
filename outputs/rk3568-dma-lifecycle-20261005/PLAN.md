# DMA / PL330 生命周期 C 阶段实现计划

输入为 Linux `9f9e9d18574d0914c0d192a90c3babfe1fd63c95` 和冻结 B 阶段
`outputs/rk3568-asoc-errors-20261005/driver-source-v2`。按已核查的
`outputs/rk3568-audio-runtime-20261005/PLAN-C.md` 实现，原内核、0006–0010、
硬件和主任务文件均只读。本阶段仍禁止板端 START。

**C1：先真实函数屏障红证据，再修 PL330。** 保留 direct issue_pending。
channel 锁先于 controller 锁；pool 锁不嵌套；PM、callback、等待均在锁外。
descriptor 的 owner/epoch 在本次 checkout 至最后引用退出前不可改写。队列 owner
引用与 IRQ/fault/runner 借用引用分开；terminate 只关门闩、推进 epoch、摘发布
入口和转 retired，不归池。IRQ/fault 在 controller 锁内捕获完整 request 快照
并借引用后，才解锁 rqcb；不在解锁后重新读 request。rqcb 判门闩/epoch再拒绝
迟到发布。direct/tasklet 只有一个 runner；callback 后从当前队列重新取对象。
未提交准备链的引用由 submit/prepare 拒绝路径负责归还，不混入 terminate 队列。

checked synchronize 在 process context 持 sync mutex，截止等待 producer、runner
和已排队 tasklet 全退，然后读真实 STOPPED；只在两项证明都成功后归池/放 PM。
DBG 5ms、STOPPED 20ms、软件排空 500ms 是初始可审查截止，没有板测性能结论。
所有原 UNTIL 去掉无限忙等，DBG 返回 errno。硬停失败 sticky 封锁整个 DMAC 的
alloc/prep/submit/GO，保留 thread/event/mcode/descriptor/PM。无 DT reset 不能以
`reset_control_assert(NULL)==0` 假称复位。free_chan/remove/void synchronize 不能
把调用者所有权转走，失败进入 fail-stop；suspend 故障拒绝，活跃未停止通道拒绝。

**C2：ALSA allocation 真正永久退役。** 新增 optional checked provider API，
原 void API 保留。只有安装 checked callback 的 PL330 路径启用本次受保护
allocator/quarantine 限制；其他 provider 调原 void synchronize 并沿用原 API
契约，不声称其新验证。生成与构建审计必须核查 PL330 checked 接线。open 预分配
独立 quarantine token，START 检查实际 buffer 是 DEV coherent、无 allocator
private_data、无 IOMMU，device 匹配；DEV_IRAM 请求在无 iram 时真实 allocator
回退为 DEV，不按请求枚举猜测。未知实际 allocator 在 START 前拒绝。

checked 负值只允许在软件全部排空之后返回。硬件停止未知时，pcm_memory helper
将嵌入 buffer 的完整元数据复制到 token 并清旧 owner；动态 snd_dma_buffer 连同
指针转交而不 kfree。清 runtime buffer，持 device ref，card bytes 转到 core
独立 quarantine_bytes 和永久 list，后续 managed/card free 不再看到 allocation。
不依赖 prtd/runtime/card 活着，也不在故障时临时分配。sticky 最多退役一份旧
allocation；后续新 HW_PARAMS 的无 DMA allocation 可正常错误清理，不能增长隔离。

软件排空超时不得返回让 close 释放 runtime；fail-stop helper 自身先设
`panic_timeout=0` 再 panic，内核不主动 warm-reboot。本轮另要求 bootargs panic=0。
外部硬件/MCU watchdog 未核，不能保证外部不会 reset；不能自动暖重启或复用旧 RAM。

两 generic component 装 sync_stop，同时 prepare/hw_free/close 走同一 checked
process helper，覆盖 stop_operating=false 的 START 失败。关闭前先排空/退役再
释放 prtd。检查 submit cookie；GO 错误由 provider sticky 状态/tx_status 暴露并
阻止启动。成功路径保持 DMA 先就绪、CPU DAI 后启动的顺序。

**C3：冻结 B 增量的 trigger 回滚。** START 任何后续阶段失败都停止已处理和
可能部分执行的 DMA component；不依赖 native group action 对失败成员的 undo。
STOP 的 CPU/link/component 首 errno 保存，但仍执行所有独立停止。Rockchip CPU
I2S 的 void helper 吞错须明确审查；不以 DMA 生命周期通过声称它已经修好。

每阶段先加真实生产函数故障测试，原字节红证据后才修改；host / ASan+UBSan /
static AArch64 QEMU 的 pthread 明确屏障覆盖 callback、IRQ、fault、direct runner、
跨通道复用、pool归还、超时、ownership transfer、重复关闭与实际 START 回滚。
测试只假内核 API/I/O/锁与调度边界，不能证明真实 AXI 停止、KASAN/lockdep或电气。
生产代码只保留原许可证，不注入测试。候选分批可审查；完整 C 未完成不公开
可部署的 0011，不以半补丁开放 START。完整 Image 由主任务构建并独立复核。

C1 2026-10-05 冻结评审输入为 `driver-source-v15`，公开 0011 仍未写入。
队列/真实 cookie/callback/prepare/submit/IRQ/fault/PM/checked/free/remove/GC 共 63 项，
真实 DBG/state/control 的寄存器模型 15 项，真实 DMA core registry/get/quiesce 9 项；
host、ASan+UBSan、static AArch64 QEMU 每环境 87 项通过。SHA 收据位于
`C1-review-v2/receipt.json`，生成脚本副本冻结于其 `generators/`。中间失败和已否决
证据保留；尤其旧 v14 的未拥有 ES 通过普通 host 却触发 ASan 越界，不能引旧绿冒充
v15。核原 Git 树保持锁定且 clean；三文件精确补丁仅内存重放，拒绝上下文/哈希篡改。

本 C1 系统 sleep 保守要求全部 DMA 通道已释放，保留 allocated idle 通道也返回
EBUSY。真实 core mutex 内对 client_count 的检查与 terminal admission 位发布配对；
有客户端的 remove 进入 fail-stop，未提供活跃 unbind 恢复。普通 AMBA shutdown 的
真实 helper 未调用未注册的 shutdown callback，也不调用 remove；这不授权暖重启，
外部 MCU/watchdog/reset 后 RAM 是否仍被总线写入未证明。所有 fail-stop 设置
panic_timeout=0，仅保证此内核不主动自动 warm-reboot。

GC 只在实际成功 PM lease、pch→controller 两锁下证明旧软件 users/queue/双 req
为空、无故障、真实 STOPPED、所有 retired refs=1 后 detach；锁外 unmap/归池。
此线性化之后的 submit/issue 可以直接 GO 新请求，保留 DMA-before-CPU 时序；
GC 本身和排队状态计入同步等待，free/checked/remove 的真实屏障覆盖其退出。
条件不满足只保留 retired，20ms GC 观察截止不把忙状态伪称 fault 或 STOPPED。

C2/C3 当前仅完成计划及实际源码链审查，尚无实现/绿证据；production 内建配置未
编译。接下来的只读板端观察方案还须能区分 poison、隔离 allocation bytes、PM lease
和实际 STOPPED 证明；单 DROP/close 结果不作为停稳依据。上述缺口闭合和独立复核
完成前仍 published=false、deployable=false、禁止 PCM START。
