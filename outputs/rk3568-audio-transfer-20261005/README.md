# 有限单向 PCM 工具（离线冻结，待主控验收）

`build/static-v1/pcm-transfer` 是 MIT 静态 ARM64 ELF64，小端，659736字节，无动态解释器/依赖。二进制SHA256 `2a6c765bd9c3c25b3456e60d68670231e81dcaf7781b827559cd701beed09e2e`；源码SHA256 `044b43f79ecf538301b1e128fc00ee6882901a84e75be18d5ea9637e91f547b2`。真实锁定内核ALSA UAPI `138cb9e8de8df6cdf2abb05806d7f61078fb7ea44063e5914bea277ef55a0447`；工具版本、ABI、ELF、编译输入与证据哈希在 `build/static-v1/manifest.json`。

当前 `board_tested=false`、`actual_bounded_transfer=false`、`audio_start_allowed=false`。工具已离线验证，不表示允许上板运行。主控须先闭合 CPU/DMA/C3、完整Image、实际设备身份、路由、电源与exclusive FD的session guard；这里不改native PID1生命周期，也不读取DMA停止字段或授权普通reboot。

集成时仅复制该静态二进制进下一版只读rootfs（建议 `/usr/bin/pcm-transfer`），保持主控现有进出根和救援流程。全部门槛通过后，分别单向运行，例如：

```text
/usr/bin/pcm-transfer --card-id rockchiprk809co --stream playback --frames 24576 --timeout-ms 5000
/usr/bin/pcm-transfer --card-id rockchiprk809co --stream capture --frames 24576 --timeout-ms 5000
```

这两行是两个独立会话；前一向必须由root确认CPU/DMA实际停止且无owner/quarantine/poison/lease后，才安排下一向。工具不支持全双工、设备任意选择、恢复XRUN、自动重启、卸载驱动或MCU重置。所有参数必填，无默认48000帧。帧数1024..48000且为256整数倍（最大可用47872）；时限100..10000ms。24576帧对应0.512秒样本数量，实际开始/退出/日志输出时长受软时限和系统调度影响。

卡号动态扫描controlC0..31，要求唯一固定ID `rockchiprk809co`，并核 `driver=rockchip_rk809-`、`name/longname=rockchip,rk809-codec`，以及PCM D0/subdevice0完整 `fe410000.i2s-rk817-hifi rk817-hifi-0` identity/protocol。值来自已有Linux `/proc/asound/cards`证据及实际soc_setup_card_name；设备node须字符设备major116，兼容实际CONFIG_SND_DYNAMIC_MINORS。多个匹配/异常身份明确拒绝，不猜card0/card1。

参数保持S16_LE/RW_INTERLEAVED/48k/2ch、period256×4、buffer1024帧。HW_PARAMS后设置SW_PARAMS start_threshold=LONG_MAX，禁止默认阈值1带来的隐式START。playback只预填全零1024帧，再显式START一次，之后只写零样本；capture先显式START，再只读当前一向。短read/write的正返回按实际PCM fops的**字节数**累积，除以4统计帧，帧不对齐/零进展/异常大返回均拒绝。EINTR/EAGAIN仅poll/read/write按同一截止时间继续；状态ioctl和close各尝试一次。

操作轨迹固定262144字节内存，保留4096字节给清理；正常STOP/free/close尝试完后输出，防止串口逐周期写日志拖慢5.33ms period。容量将耗尽时返回ENOBUFS并清理。`PCM_STAGE`保存全部已尝试的OPEN、identity、参数、PREPARE、START、poll、read/write、STATUS、DROP、HW_FREE、close返回；`PCM_FIRST_ERROR stage=... errno=...`保持首错误，即使后续清理也失败。capture输出frames/samples/zeros/zero_ppm，内存块复用后清零，不保存或输出声学样本。返回0及 `PCM_BOUNDED_IO_COMPLETE_GUARD_STILL_REQUIRED`只表示该用户态有界I/O和正常清理调用通过；返回2表示参数/过程/清理/软截止错误。

playback统计为已排入用户态/PCM的帧数，最后直接DROP，**不DRAIN、不能声称全部帧已播放完**。STATUS观察hw_ptr至少推进256帧并分别报告observed_hw_ptr，但不证明电气/声音质量或DMA实际停稳。DROP、HW_FREE、close rc0或无FD同样不能作为重启许可，root仍必须读取CPU sticky/uncertain/ownership/IRQ/clock及DMA poison/quarantine/lease/STOPPED证据。

SIGALRM/INT/TERM只置取消标志、打断可中断调用并进入正常DROP/HW_FREE/close；继承的SIG_IGN和屏蔽状态被显式覆盖/解除。没有kill、force close、自动reset/reboot。软timer覆盖轨迹输出；用户态无法强迫不可中断驱动调用或堵塞输出立即返回，实际调度/救援边界仍由root负责。Linux close报告EINTR也不重试，避免误关被重用FD；失败仍留首错误和外部停止核验要求。

验证结果：完整生产C未改名或重写算法，以链接syscall wrappers验证真实边界；host、ASan/UBSan（含glibc fortify别名）、ARM64/QEMU各 **143/143**。覆盖最小/最大/示例帧数、严格CLI拒绝、动态唯一身份、参数/状态、短I/O、EINTR/EAGAIN、XRUN、poll截止/挂断、START/DROP/HW_FREE/close错误、首错保持、日志容量及输出阶段截止。真实100ms SIGALRM用例从继承ignore/block恢复后正常清理退出；没有终止进程代替清理。既有pcm-config真实源码缺失START/data/DROP为红；实时输出日志与过早取消输出阶段timer也各有真实编译红对照。vendor/cross ARM64 HW/SW/status结构和ioctl ABI一致，完整静态实际程序无参数时QEMU返回2且未访问声卡。

`build/static-v1/manifest.json`和`sealed-v1/manifest.json`登记冻结证据。未执行板上I/O、未接触生产Image/串口/ADB/公共补丁/CPU封存/DMA/PID1，没有提交或发布。实际PCM传输、声学/电气和完整C3退出仍待主控安排。
