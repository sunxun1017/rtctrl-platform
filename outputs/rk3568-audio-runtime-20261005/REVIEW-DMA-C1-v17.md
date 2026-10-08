# DMA C1 v17 独立审查

receipt SHA `486c294feacafb737853d01230e0ae1feb9668be2a4f63f6f151458831b89702`，
PL330源SHA `9985d8f7f02ba12d4acf79f0cdc1c2105058946e7d6a82e662079758a8aef128`。
独立审查核159个冻结文件、三文件完整patch replay、原内核HEAD与clean状态；真实提取67个
软件链、12个低层硬件链、6个DMA core函数与实体源一致。现有host/ASan+UBSan/ARM64 QEMU
各91/91复跑的stdout/stderr SHA与冻结证据一致。

v15缺少checked profile debugfs删除门槛：probe注册raw-controller文件、删除时未撤销读取，
资源释放后仍可读。v16起checked profile不发布这一legacy入口，v17真实注册顺序已独立确认。
public terminate取PM前在pch lock下取得operations ticket并关闭epoch；checked私有helper
等待公共入口完整PM退出，避免以前未计数的入口区间。两项修正成立。

checked负返回发生在软件生产者、IRQ、tasklet/direct runner、callback引用完全排空之后；
软件超时进入明确不复用资源的内核停止路径。硬件STOPPED未证明时，retired descriptor、
thread/event/mcode及已有PM引用保持。该证据不证明PCM allocation已经独立退役；那属于C2。

发现一项C3/START放行前阻断：真实_start对WFE或INVALID返回false而未latch首错，
pl330_run及IRQ pl330_update忽略bool；tx_status前置仅看sticky，未完成cookie仍可IN_PROGRESS。
既有15项低层测试没覆盖这两个拒绝分支。主控用相同冻结ASan ELF重现WFE=4和INVALID=10：
guarded返回-5，lifecycle_error0、GO计数0、req_running-1，精确argv/exit/stdout/stderr/SHA存于
[独立寄存器模型复现](build/dma-v17-independent-register-review/receipt.json)。
真实caller忽略返回值由实体源码确认；guarded将bool转errno不能代替production sticky接线。
没有板端触发证据。

作者在独立v18/C1-review-v5目录修正此拒绝的首错记录并补真实_start→runner/IRQ→tx_status测试，
旧v17冻结不变。v18、C2/C3全部接线、只读DMA状态及完整生产Image仍需最终独立审查与整合；
本报告不放行板端START、正常重启或正式迁移。
