# 有限单向 PCM 用户态工具计划

授权边界：仅此新目录离线实现/测试/静态ARM64构建；不改CPU/DMA封存、PID1、公共patch，不执行串口/ADB/硬件/START/发布/提交。

运行接口固定为 `pcm-transfer --card-id rockchiprk809co --stream playback|capture --frames N --timeout-ms M`。动态扫描 controlC0..31 并核字符设备major116和CARD_INFO；要求唯一匹配卡identity，不猜CARD号。PCM D0/subdevice0、完整既有 CPU-codec id/name/protocol身份继续核验；external root guard负责所有设备使用者/exclusive FD和CPU/DMA只读停止证明。

硬件参数：RW_INTERLEAVED/S16_LE/48k/2ch，samplebits16/framebits32，period256帧/1024字节，periods4，buffer1024帧/4096字节。N为1024..48000且256整倍数；M为100..10000ms，均必须显式输入。

实际 `pcm_native.c` 默认start_threshold=1，因此须SW_PARAMS设置start_threshold=LONG_MAX防止隐式启动。playback先写零样本预填1024帧并验证PREPARED，再显式START一次；capture先START再读。只读/写当前一向；read/write字节数必须帧对齐，短I/O累加，不重复已成功数据。EINTR/EAGAIN仅poll/read/write按同一全局monotonic deadline重新等待；XRUN(EPIPE)、挂断、异常返回、无进展和截止明确失败，不自动recover/reprepare/restart。

SIGALRM/INT/TERM只置取消标志，阻止新业务操作并进入正常DROP/HW_FREE/close。改变状态的ioctl和close不重试，避免部分执行/FD复用歧义；任何后续清理错误不得覆盖首错。尝试HW_PARAMS后保守尝试DROP/HW_FREE；同一PCM FD最终close恰一次。timer不会杀进程/force close。内核不可中断睡眠不能由用户态严格限定实际退出时刻，必须保留救援，不自动重启。

记录每个OPEN/identity/HW_PARAMS/SW_PARAMS/PREPARE/START/有界poll/read/write/STATUS/DROP/HW_FREE/close及首错误；播放不接受文件内容，只固定全零；capture只输出frame/sample数和零率，不存声学数据。统计queued/read和observed hw_ptr分别命名，不能把用户态写成功当实际硬件全部消费，更不能以DROP/close rc0许可reboot。

先对既有真正pcm-config源码做缺失START/数据路径的红对照，再对完整生产helper编译syscall边界wrapper，host/ASan/ARM64QEMU涵盖短读写、EINTR/EAGAIN、XRUN/poll超时、身份/参数/状态拒绝、START/DROP/HW_FREE/close故障与首错清理。静态ARM64 ELF、真实锁定UAPI/ABI/编译器SHA及tests冻结，manifest `board_tested=false`、`actual_bounded_transfer=false`。交root集成，只给运行接口，不改PID1 lifecycle。
