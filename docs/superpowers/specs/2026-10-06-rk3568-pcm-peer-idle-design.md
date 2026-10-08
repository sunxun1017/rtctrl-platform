# RK3568 双 open、逐个关闭的无 START 检查

继续已授权的 Android→Linux 迁移。此程序只用于下一版 ASoC 候选的有限检查，
不发 PREPARE/START/WRITE/READ/DROP，不改声音控件、驱动绑定或 PM 配置。

独立目录为 `outputs/rk3568-audio-runtime-20261005/pcm-peer-idle-v1/`。
复用已验证的 pcm-config 设备身份、固定 48kHz/S16_LE/2ch/256×4 参数和锁定 UAPI，
保留旧 helper 的源码、二进制和测试结果。

程序需显式选择卡号、open 的第一方向和 close 的第一方向，覆盖四种组合。
先核 control/card 身份，再依次打开、核实并配置两个 PCM。每次 ioctl 只尝试一次，
硬件参数返回必须严格匹配，状态必须 SETUP 且两个指针为零。
两向配置完毕后，按选择顺序 HW_FREE/核 OPEN/close 第一方向；
核另一方向仍为 SETUP、指针零，随后 HW_FREE/核 OPEN/close。
默认动态 minor，只接受原 rk817-hifi PCM 完整 id/name 与 116 主设备号。

记录每个操作的结果及唯一操作序号，采用有界缓冲或有界输出，保留第一个错误。
失败后只归还已取得的资源，每个 HW_FREE/close 至多一次，继续另一方向清理。
先建立正常 SIGALRM 行为和解除继承屏蔽，再设置五秒期限；内核不可中断等待仍不受此期限保证。
参数错误必须在任何设备调用前拒绝；不按猜测识别 USB 音频为目标卡。

验证真实程序 main，通过外部 syscall 边界包裹覆盖四种顺序、第二 open/config 失败、
非法身份/返回参数、状态错误、HW_FREE/close 失败、首错误和多资源清理；
包裹器应拒绝任何未列入白名单的 ioctl、重试或资源重复释放。
实际运行 host、ASan+UBSan、AArch64/QEMU；另交叉编译真正静态可部署程序。
所有输入、argv、二进制和日志 SHA 存档，独立审查后才封存。

用户态 syscall 模型不证明内核 PM/时钟/DMA 清理，程序状态检查也不直接测量共享 sysclk 缓存。
现有严格 guard 只在全部 PCM 关闭的前后使用；本程序不产生硬件 START 许可。
板上实际矩阵需等待新候选源码、完整 Image、codec ABI和包的审查绑定完成。
