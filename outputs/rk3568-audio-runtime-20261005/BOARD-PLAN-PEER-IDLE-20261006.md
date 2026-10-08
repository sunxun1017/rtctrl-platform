# 无START双打开与逐个关闭的有限板验

沿用已接受的 [检查器设计](../../docs/superpowers/specs/2026-10-06-rk3568-pcm-peer-idle-design.md)
和 [四源离线边界](REVIEW-ASOC-OPEN-ROLLBACK-20261006.md)。主控独占板操作。
当前仅有电脑上的源码、模型和ELF结果；本文件不表示硬件操作已发生。

先完成新integration-v4完整Image/modules、对应codec真实ABI、v5内存包及主控fresh包审。
绑定最终seal、工具、辅助程序、CPU v12、四源和实际Image文件，重核原Android身份及保护对象。
以既有一次RAM bootm流程启动，核本轮kernel notes和全量live FDT，再加载codec。
电池算法、USB peripheral、early eMMC候选不加入；TUN设置保持。

自然初始空闲通过严格bound guard后，依次验证四种明确顺序：

| 先打开 | 先关闭 | 仍打开的peer |
| --- | --- | --- |
| playback | playback | capture |
| playback | capture | playback |
| capture | playback | capture |
| capture | capture | playback |

每次使用不同的stdout、stderr和exit文件，不覆盖已有证据。
每次前后都在两个方向已经关闭时执行严格bound guard。检查器内部确认两方向参数、
先关方向HW_FREE后的OPEN、剩余peer的SETUP/零指针，以及剩余方向HW_FREE/close成功。
完整34条操作记录、顺序、返回值、无first error和实际进程exit0必须同时成立；
串口缺字时保留失败原流，只重新导出板上原文件，核长度和全SHA，不补猜字节。
这段不发PREPARE、START、声音读写或控制路径切换，不证明DMA传输或真实声学效果。

每次检查fresh内核诊断与PM/时钟/IRQ状态；任何未知诊断、peer状态异常或guard拒绝都停止后续组合，
保留原始日志并调查。SIGALRM不能保证D态等待或解除alarm后的stdout截止，不能把超时当资源已释放。

四组合结束后保留两方向分别有限单START传输回归，仍使用此前的单方向运行门和前后严格检查。
正常card解绑、codec引用归零后卸载、CPU解绑，核全时钟引用/DMA工作及隔离缓冲，
执行原生codec/PTY自检与正常RAM返回，独立挂载/进程/FD guard后普通reboot回Android。
当轮重核七项保护及三项native缓存全SHA；写入独立板结果，不改离线manifest的未板验标记。

成功只关闭“双打开/逐个关闭”和本轮单方向回归边界。四项双START/共同STOP红例、共享TRCM故障、
RK817 voice缓存、泛型pinctrl在途窗口、真实声音与正式恢复仍有各自验收要求。
