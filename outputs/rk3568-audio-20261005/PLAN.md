# RK809 声卡接口

用户当前只接板子，没有耳机或喇叭。本阶段验证源码 codec 的声卡注册、控件及
播放/采集端点元数据，不打开 PCM、不更改控件、不播放或录音。

保留已测 Image、ABI、initrd，独立构建 GPL codec 模块。先修 DT/probe/reset
错误传播与资源所有权，再检查模块导入闭包；运行时只加载此模块并保持到重启。
probe 会配置 GPIO、MCLK 和寄存器；控件 OFF 是软件路径值，不证明电气断电。

新增音频 DTB 从 UART/RNG/Wi-Fi 基线派生，只新增 PMIC codec、simple-card，
启用 I2S1 并限定原板五条音频信号。原 Android DAPM routes 对本驱动不适用。
I2C5、SPI3 与 MCU 保持原基线。通过完整属性差分和真正编译的坏 DTB 检查边界。

MIT 静态 helper 仅打开指定 control 节点，检查卡身份、动态控件 ID、枚举标签和
默认 OFF/MIC OFF；错误均关闭描述符。host/QEMU 故障测试限制系统调用白名单。
helper 自行设置默认 SIGALRM 的5秒限时；实际 RAM BusyBox 没有 timeout applet。

上板前复查电量、Android/root、启动分区及两份 rootfs 的完整 SHA。仅普通 cache
暂存，U-Boot RAM 加载。RAM 复制后释放只读 cache，收集身份/控件/PCM 元数据，
确认无 PCM/control 描述符、无持久挂载，再回 Android 比对七项 SHA。
3% 时按用户要求提醒换电池。无刷写、saveenv、MCU、电机或正常关机验收。

本阶段不验收音质、实际播放采集、音频路径切换、suspend/resume 或整板电源生命周期。
runtime callbacks 的进一步错误传播属于后续完整音频适配。
