# DMA C3 v5：独立复现后拒绝

2026-10-05，冻结候选 manifest SHA
`0cc48150995c765d81a2004aaf23373cab0ae76c156ae62517324deb32ad67ea`。
完整独立审查未完成；已经复现的 probe 中断问题足以拒绝该版本。未生成生产 Image，未板上 START。

实际 AMBA wrapper 在 provider probe 前置设备 active 并持 runtime PM usage=1。
v5 `pl330_probe` 在 `pl330_add` 初始化 controller lock、req_done 队列和 physical threads 前
调用 devm_request_irq。此时 pending IRQ 可以进入 handler：removing/system_suspended 均为0，
runtime PM 门槛通过。即使 FSM/FSC/ES 都为0，零初始化的 req_done.next 仍不是合法空链表，
真实 `pl330_update` 进入 list_del，访问空指针。

独立夹具保留实际生产函数和作者的底层 MMIO/codegen 模型，新增 probe 时序场景。
host 与 ARM64/QEMU probe-irq 返回 -11；ASan/UBSan 返回1，栈为
list_del → list_del_init → pl330_update → pl330_irq_handler。其余 pm-latch、
operation-drain、private-desc、manager-snapshot 四个场景在三种环境返回0。
这不是实际 IRQ/AXI 执行，不能用四个绿色场景宣称生命周期全通过。

独立重编译十二个实际 Kbuild 对象均为 ARM64 ET_REL，编译返回0，源码重放及配置 ABI
有原始 argv/hash；对象构建通过不消除上述初始化错误，也没有构建 Image。
未完成审查的114个原始文件已逐项SHA复制至
[独立证据](build/c3-v5-independent-review/inventory.json)，包括模型、编译器输出、
完整源码提取结果及失败日志。作者拒绝封存另见
[C3-review-v1](../rk3568-dma-lifecycle-20261005/C3-review-v1/receipt.json)。

下一版本须先初始化内部数据及 STOP/mask/clear，再安装 IRQ；所有安装/发布失败需关闭入场、
排空软件用户和中断，按依赖顺序清理。descriptor 连续分配块必须记录块基址后整块释放，
不能逐个释放 interior pointer。新版本以真实 probe/error/remove 和独立重跑验收。
