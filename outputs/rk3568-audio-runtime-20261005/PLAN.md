# RK809 PCM 参数与退出阶段

接续已验证的 RK809 声卡接口。用户更换电池并要求继续 Linux 适配；本次新鲜
Android 电量 87%、root、4.19.232 和 boot_completed=1 已确认。保留 TUN 设置。

先运行真实 codec 函数的错误注入测试，修正 hw_params 和四个数字时钟重启函数的
errno 传播。在任何寄存器操作前验证 stream、rate 和 format；能力声明移除当前
没有实现的 S20_3LE。保留原先成功路径的寄存器顺序、延时、PMIC regmap 所有权。
公开补丁基于 0006，原内核源码、Image、配置与 ABI 保持不变；独立外部 Kbuild。

板测仅 open、INFO、HW_REFINE、HW_PARAMS、STATUS、HW_FREE 和 close。
使用 S16_LE、48kHz、双通道，Playback/Capture 保持 OFF/MIC OFF；分别验证播放
和采集参数，不 PREPARE、START、读写 PCM 帧或改音频路径。不录音、不输出音频。
原因：本版 ASoC 的 PREPARE 会调用 unmute 并忽略 errno，codec 在 OFF 路径仍清除
DAC 静音；必须先另行处理该调用链。DMA slave_config 不证明 submit 或实际传输。

沿用已测 audio DTB、RAM initramfs；新模块/helper 和脚本写普通新 cache 目录。
加载前后 SHA 检查，RAM 复制后释放 ro,noload cache。收尾检查描述符、挂载和模块
引用；保留 codec 到复位，再返回 Android 比对五启动分区与两份旧 rootfs SHA。

随后推进独立显示 DT、完整用户空间启动和 Linux 正常电源生命周期。电机/MCU
需要真实连接及已确认停止、使能和反馈契约；读取失败的传感器另列硬件缺口。
