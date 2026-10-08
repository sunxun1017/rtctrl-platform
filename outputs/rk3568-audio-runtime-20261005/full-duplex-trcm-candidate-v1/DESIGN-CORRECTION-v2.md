# 正常 XRUN 与 shared IO 错误的区分

source-v1 草案将健康 TX underflow/RX overflow 也视为共享故障，主控审查纠正。
source-v2 对正常本向 IRQ 只 disable/ACK 并通知本向，保留 peer 与 transport；实际
status read 或 IRQ disable/ACK/共享 IO 失败才 latch 首 errno、撤 admission/ticket
validity、joint STOP 并捕获两个方向通知。此文覆盖 DESIGN.md 的原单 IRQ联合说法。

实际 pcm_native.c 的 action_lock_irq 持 stream 锁，贯穿 action 的单/组 do_action
与 post_action，最后才 unlock；START ioctl 经过此入口。snd_pcm_start 要求调用者
持同锁。故 CPU DAI commit 成功后、native RUNNING 发布前的 ISR 可在 CPU 锁外
等待 stream 锁；它随后观察已发布状态，不以 PREPARED 时 stop_xrun 返回0证明停机。
模型将执行真实有限 native action/do_start/post_start 切片并用明确 unlinked/atomic
API 锁边界复现此等待。没有执行完整 ioctl、linked group 或 nonatomic mutex路径，
也不把锁 wrapper 或 XRUN wrapper 称为完整内核实现。

params HW_FREE/close 可释放不在 starting 的 idle 本方向，peer starting owner 仍保留
共同 cache；禁止释放自己的在途 GO owner。begin/format/prepare/PM 拒任何 starting。
同方向合法 close 由 ALSA stream 锁排除 GO 并发；若违约仍有 GO 借用，VOID shutdown
不能安全返回让 core 释放 ss，采用已有 checked failstop，不把日志当拒绝传播。
