# PCM peer-idle 离线封存状态

2026-10-06。主控 fresh 执行与独立只读审查已接受同一版生产源码、syscall 模型、原始日志和静态 AArch64 ELF。`README.md`、`ready-for-review-v1.json` 与 `production-v2/manifest.json` 保留生成当时的待审状态，不回写历史记录；最终审查和封存状态以本文件、复制的 root acceptance note 及 `sealed-evidence-v1/receipt.json` 为准。

主源码 SHA `4edc171fd8bb57c10d844bbfdfa72f83dd090de3f96f143bab8459fd7e22c8d2`，参数 header SHA `26ae04bc98a5e466bc24a18ab76b5841c9c52a0e265d5610cdedc2d4011536f9`。实际静态 AArch64 程序为 `production-v2/pcm-peer-idle`，655136 B、SHA `7693a052b6318ec3e965451fcb94609e97cb48e693715b847b62032cc684e661`、CRC `e5c2ba24`。生产 manifest SHA `30e074fd01cbe94bc8e28a20de19698c5492525af469615afc7daaac92331779`。

作者与主控分别实际编译并执行 host、ASan+UBSan、AArch64 QEMU，每个环境各 1032/1032。主控实际源码/header/wrapper 与作者逐字相同，复制的 runner 只改变 ROOT/RUNTIME 目录深度。主控结果 SHA `f300fd76c0e98311e970a71dd6debcee9929a87e993d357411d5be12bcb9115a`，独立审查及主控接受 note SHA `569f6ed7e09e58c82eb9a9388fddb8f928d8b9df855d86fdf20e4b10ef02b69d`。完整 root fresh 执行树已只读复制到 `review-inputs-root-v1`，其 snapshot receipt SHA `af60d6e8d2fa9a615142fd0c897e18bee5597dd6dc6cff5e9ac823f249047302`。主控原目录不改。

`sealed-evidence-v1` 归档所有本目录当时的普通输入、源/工具、作者 red/green 执行、历史失败输出、目标 ELF 与审查副本；inventory 记录逐文件大小和 SHA，checksum 清单另覆盖 inventory 与 final receipt。八个原输入和初始 9436 文件 candidate inventory 均再次核验；初次模型编译失败和 FORTIFY 白名单导致的初次 audit 拒绝均保留并明确区分于有效红例和最终生产产物。

这是无 PREPARE/START/I/O 的离线用户态检查器，未做板上验证。模型和 STATUS 不直接测量真实内核 PM、DMA 或共享 sysclk 缓存；不产生 START 许可、不证明全双工、物理声音或整机迁移完成。严格 guard 只用于全部 PCM 关闭的前后。后续实机四顺序矩阵由主控在新 Image/codec/包身份闭合和审查后执行。

三个环境约五秒 SIGALRM/-14 的实际测试验证可中断 pause，不能保证结束内核不可中断等待。信号终止不经过用户态清理日志；内核 fd 释放仍由内核处理。资源归还后解除 alarm 再输出，stdout 阻塞不在五秒期限保证内。
