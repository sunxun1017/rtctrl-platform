# Checked shared-params TRCM CPU 段

仅修改新目录内的 CPU 私有副本；基线是已审 params source-v4 CPU SHA
399a672728c41a5ed3900b6186021babaf9a1d3aac4dafbfcd4f72277d5fafe0。
legacy、无 shared-params opt-in checked 实例、C3 core/DMA 生产源码保持基线。
固定 single-link hifi 48k/S16_LE/2ch/master/TRCM_TXONLY profile 未激活 DT。

CPU component START 先于真实 platform DMA GO。锁内核 open==params owner、prepared、
sticky/ready/PM/config/pending，发布每方向 ss/epoch ticket 和 starting 借用位。DAI START
用真实 substream 核当前 ticket，再提交本向 DMAC/IRQ。第一次提交双 XFER START；
第二次只开本方向请求，不重写 XFER/CLR/reset。ticket 在成功提交后转 started owner。
同 ss 的真实 ALSA stream 锁序列化 trigger；没有 current/task 身份许可。

故障撤销 ticket validity/epoch，保留 starting 借用位，不能以撤 epoch 称 GO 已排空。
真实 C3 component 失败 reverse prefix 的 CPU STOP 在已调用的 DMA STOP 后执行；
DAI 失败意味着 GO 已返回，随后真实 C3 component STOP 完成本调用清理。CPU STOP
在此契约下归还 starting 借用。任意脱离 ALSA/C3、同 ss 并发触发不能凭 CPU-only
接口认证，需另 completion 接口；不以 synthetic 注入模拟成该泛型安全证明。

正常 DAI STOP 只停止自己的 owner：peer 已 started 或 starting 时，关闭并 ACK 本向
IRQ、关闭本向 DMAC、direct MMIO 核本方向 bits，保留 shared XFER/peer 配置与 FIFO。
无 started/starting 时才双 IRQ/DMAC/XFER STOP、150us、双 CLR、三寄存器 direct proof。
quiet proof 只证请求/IRQ关闭，未证明 FIFO 内容或重启样本质量。prepare 按本 owner
准入，peer 活动时只本向 quiet，无全局清 FIFO/停时钟。

CPU 共享硬件错误先 latch 首 errno、关闭新准入和撤票，然后独立尝试联合各 STOP
阶段；不能顺序调用旧 peer-EBUSY stop 两次代替联合停止。IRQ 锁内捕获 started|starting
两方向当前 ss，联合 STOP 后锁外 XRUN。PREPARED 期间 XRUN 返回0并不证明 DMA 停，
尚未提交方向仍由 sticky/epoch 阻断 DAI，再由 C3 回收本向 DMA。close 在锁内撤 pointer，
锁外 synchronize_irq 排空已捕获借用；无新 worker，不能把 IRQ drain 扩成 work drain。

starting 位进入 params begin/free、prepare、format/PM、quiesce/close 条件。共享参数
fault callback 本身仍只 latch/no shared MMIO；它不声称联合停止既有 peer。实际 CPU
传输写失败及 IRQ 故障走 joint helper。PL330 controller sticky/异步 fanout 和精确 PCM
桥由独立候选处理，本段不授予硬件双 START 或全链故障闭合。

复用已执行 model-v6 的真实 PCM/C3/params body；新旧模型使用相同有限 API边界。
先保存旧 CPU 的双 START/peer STOP/joint fault 红例，再用新 CPU body 三环境红绿。
不做 Kbuild、Image、模块、SDK 修改、DT 激活、硬件或大规模封存。
