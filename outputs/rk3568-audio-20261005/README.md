# RK809 板载声卡接口：源码 Linux 实测

2026-10-05，在只接板子、没有耳机或喇叭的条件下，源码 Linux 的 RK809 声卡注册和
ALSA 控件接口通过。实际播放和采集端点都出现；本轮没有打开 PCM、修改控件、播放或录音。
随后经 RAM 收尾门槛和 SysRq 返回 Android 11/4.19.232，五个启动分区与两份旧 rootfs
的完整 SHA256 均与测试前相同。返回后电量实测 7%，整理记录后收尾为5%，均仅是各自时间快照。

机器结果：[result.json](result.json)。源码和构建器可公开，原始串口/ADB 记录含设备身份，留在忽略的
`private/`；生成产物在忽略目录中。已有构建 manifest 的 `board_tested=false` 是构建时记录，
本次上板结果单独写入 result，不修改历史证据。没有提交或推送。

## 实际验证了什么

| 项目 | 本轮结果 |
| --- | --- |
| 声卡身份 | `rockchiprk809co`，本次 card1；卡号由 ID 查找，不能固定假设 |
| PCM 元数据 | I2S1 `fe410000` ↔ `rk817-hifi`，playback 1 / capture 1 |
| 节点 | `controlC1`、`pcmC1D0p`、`pcmC1D0c`，字符设备 major116 |
| 控件 | 共14项；三个目标 ENUM 的身份、标签、当前值检查通过；其余只 LIST |
| 当前路径 | Playback Path=`OFF`，Capture MIC Path=`MIC OFF`，Resume Path=`OFF` |
| 引脚归属 | MCLK GPIO1_A2；BCLK A3；LRCK A5；SDO A7；SDI B3，均实际归 I2S1 |
| 时钟软件状态 | codec MCLK 12.288MHz，引用为1；没有测量引脚波形 |
| 功放 GPIO | debugfs 为 gpio148 / spk-ctl / out hi / ACTIVE LOW；不是电气关闭验收 |
| UART0 | `FDD50000` TX/RX 均0；没有打开物理 UART 或发送 MCU/电机帧 |
| 收尾 | 只有五种 RAM/伪文件系统，无持久挂载、loop、网络或音频 FD 残留；codec 保留到复位 |
| 返回 | 147.271085秒 SysRq → DDR → Android，root 和 boot_completed=1 |

刚 insmod 后第一次 `/proc/asound/cards` 仅列 USB 卡，随后 PCM、sysfs 和 helper 显示 RK809
card1，属于注册时序窗口，不能据最早读数判定声卡缺失。

原 Android 本次仍只有两个 path ENUM，Playback 为 `HP_NO_MIC`。同一 helper 在 Android 返回
通用元数据/路径拒绝 rc2，没有改原路径；这个输出不足以单独认定具体失败分支。
本轮接口验证不需要原厂定制 `.so`，也没有复现原厂 HAL 的全部音频处理行为。

## 源码、设备树与精确产物

内核仍用锁定 commit `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`，
release `5.10.160-rt89-g9f9e9d18574d-dirty`。原内核树、Image、完整配置和 ABI 元数据未改。
外部 Kbuild 只构建 codec；当前原配置的 `CONFIG_SND_SOC_RK817=n` 保留。

| 本轮使用的产物 | SHA256 |
| --- | --- |
| 既有 `../rk3568-rcu-reset-20261004/Image` | `e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457` |
| 既有 `../rk3568-motor-alignment-20261004/initramfs.cpio.gz` | `f0965ceed549acab8d5bd87df8bb831bb06a95d08b5b7bf3c5582045933323ee` |
| `build/dtb-v3/audio.dtb`，163161 bytes | `9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478` |
| `driver-modules-v4/modules/snd-soc-rk817.ko`，515240 bytes | `52bf198a33ce42e11f52fdf5cd6bd9be6648dc58f04d3e48810bb4e15ac579f7` |
| `build/inspect-v4/alsa-inspect`，650408 bytes | `118cf99482cdd65acdfae8c5e85530a76bf60c90b0b0498e8f285223f862a945` |

公开板级输入为 [audio.dts](../../platforms/rk3568/boards/aiot-3568pq/bsp/rk3568-aiot-3568pq-audio.dts)。
它从已测 UART/RNG 树派生，只加 PMIC codec、simple-card、启用 I2S1，并恢复原板五条信号的
pinmux/bias 与 12.288MHz 初始 MCLK。29项属性变化，760个旧 phandle、其余旧属性顺序与保留区保持，
177项审计、23个实际编译的错误 DTB 拒绝，零新增 DTC 警告。I2C5/SPI3/MCU 未启用。
原 Android routes 引用的 DAPM widgets 在这版 codec 中不存在，本次不携带不匹配 routes。

[0006补丁](../../platforms/rk3568/boards/aiot-3568pq/patches/0006-rk817-codec-error-propagation.patch)
SHA=`f501e5642d363b0c10431de053c19d8c1ae16060ddb35838d520de0f0d84bd81`：
传播 GPIO errno/defer、芯片读取、reset 写、时钟准备、控件注册与 DAI format 错误，
补齐所覆盖 probe 失败的资源释放，保持成功 reset 序列。
最终方案借用原 PMIC regmap，codec 不分配或释放该 map；component 只解除自身指针。
弃用的 child-managed map 候选不会用于上板，其查找 devres 生命周期问题有独立负对照。
芯片名/版本可能来自父 regmap RBTREE 缓存，日志 `0x80/0x95` 不作新鲜 I2C 身份证明。

最终候选 `driver-source-v5` 的 C SHA=`210104c9c6014a50d3486398d081e760e08f3e7fb84fe19cde2119993131bed7`。
公开补丁重放与独立 v6 重建逐字节相同。真实函数抽取后 mock kernel API 的 host/QEMU 各73项通过；
生成器9项、真实模块 ELF/导入故障15项通过。模块32项导入都由精确 Image 的 vmlinux 导出满足。
这些失败路径是主机测试，不是板端硬件故障注入。

## 控件检查工具

[alsa-inspect.c](alsa-inspect.c) 为 MIT 静态 AArch64 工具，严格接受
`--inspect --card N`（N=0..7）。仅打开指定 `controlCN`，校验设备类型、卡 ID、动态 numid、
两次列表一致性和目标 ENUM 信息，再读当前缓存路径。只允许 CARD_INFO/LIST/INFO/READ ioctl，
没有 ELEM_WRITE、锁、PCM open 或重试，完成 close 后才输出成功标记。
它自行设置默认 SIGALRM 的5秒限时；本 RAM BusyBox 没有 timeout applet。

生产对象无测试 wrapper；锁定内核和交叉编译器的 ALSA UAPI 经编译断言与 QEMU 布局对照一致。
真实 C main 包装设备调用的 host/QEMU 各114项通过，包括真实 SIGALRM 终止。
路径 OFF 是驱动缓存值，不能代替功放电压、寄存器新鲜读取或静音验收。

## 复现顺序

先重建[已验证内核和 ABI](../rk3568-rcu-reset-20261004/README.md)，需要相同锁定源码、GCC11.4.0
交叉工具链、DTC、Python3和 QEMU。原始 Android 镜像不是公开构建输入。
以下从仓库根目录运行，所选输出目录必须不存在；本机已保存同名产物，不会覆盖。

```sh
python3 outputs/rk3568-audio-20261005/driver-prepare.py --version v5
python3 outputs/rk3568-audio-20261005/driver-prepare.py --version v6

python3 outputs/rk3568-audio-20261005/test-driver-functions.py \
  --source-dir outputs/rk3568-audio-20261005/driver-source-v5 --label green-v5
python3 outputs/rk3568-audio-20261005/test-driver-functions.py \
  --source-dir outputs/rk3568-audio-20261005/driver-source-v6 --label green-v6 --qemu

python3 outputs/rk3568-audio-20261005/build-codec.py --version v4
python3 outputs/rk3568-audio-20261005/build-dtb.py --revision v3
```

helper 的完整生产编译参数在 `build/inspect-v4/manifest.json`。
在尚无历史红绿产物的公开检出中，可直接从 MIT 源码编译到独立新目录；运行测试使用新的 label：

```sh
audioOutput=outputs/rk3568-audio-20261005/build/reproduce-inspect
mkdir "$audioOutput"
audioKernelHeader="$PWD/third_party/linux-rk3588/include/uapi/sound/asound.h"
aarch64-linux-gnu-gcc -std=c11 -O2 -Wall -Wextra -Werror \
  -fno-builtin -fno-ident -D__user= -D__force= \
  -DALSA_LOCKED_UAPI="\"$audioKernelHeader\"" \
  -c outputs/rk3568-audio-20261005/alsa-inspect.c -o "$audioOutput/alsa-inspect.o"
aarch64-linux-gnu-gcc -static -Wl,--build-id=none \
  "$audioOutput/alsa-inspect.o" -o "$audioOutput/alsa-inspect"

python3 outputs/rk3568-audio-20261005/test-alsa-inspect.py --label green-v20
python3 outputs/rk3568-audio-20261005/test-alsa-inspect.py --label green-v21 --aarch64-qemu
```

本轮 `build-inspect.py` 还绑定了保留的历史红绿证据；不能在没有这些证据的检出中冒称已重跑原轮。
跨机器生成物有构建路径/工具链边界，不承诺不同环境字节相同；新生成物必须重新核验并绑定本次测试。

上板顺序记录在 [load-ram.json](load-ram.json)、[boot-ram.json](boot-ram.json)、
[linux-stage.sh](linux-stage.sh)、[linux-interface.sh](linux-interface.sh)、[linux-return-guard.sh](linux-return-guard.sh)。
它们是该板本轮受审输入记录，不是通用自动刷机入口。普通 cache 新目录暂存，
U-Boot 按长度/CRC 校验后 RAM booti；不 saveenv、不写启动分区。
RAM 中对五个输入各做两次 SHA 校验，cache 用 ro,noload，复制后 cd / 并释放。
stage18项真实 shell fixture（含旧 cwd 清理失败负对照）、guard31项检查通过。
收尾仍是 RAM PID1，未 switch_root；ASoC card 引用模块为1，保留到 SysRq，不做 rmmod。

当前输入复查工具：[verify-host.py](verify-host.py)；输出新 `build/host-checks-v1/`，拒绝覆盖。
本地结果生成：[record-result.py](record-result.py)，只读取已有私有证据，不通信、不加载硬件模块。

## 日志与未完成项

本次源码 Linux 返回日志至首 DDR 未捕获 `WARNING:`、`BUG:` 或 `Call trace:`。
外部模块 O taint 正常记录；codec 的 `DMA mask not set` 是 OF 平台配置 dev_warn：
`drivers/base/platform.c` 调用 `drivers/of/device.c`，缺失指针时补成自身 coherent mask 后继续。
codec 不调用 DMA API，I2S PCM 缓冲区使用 DMA 通道控制器设备。这条日志未阻止接口验收，
也不证明后续 PCM DMA 可用，不为消除它猜填设备树 DMA 属性。

下一音频阶段先审查 runtime path/mute/hw_params 的错误传播，再以播放/采集都关闭的条件
验证 PCM 能力、实际 I2S/DMAC 通道、时钟及退出；之后接明确的音频设备验波形、音质和通路。
reset 部分失败没有硬件回滚保证，suspend/resume、完整移除并发和普通 Linux reboot/poweroff
仍未验收。SysRq 返回不能替代这些生命周期检查。
触摸/加速度计身份缺口及真实电机反馈、停止/使能/watchdog仍单列。
七项 SHA 相等不等于完整 eMMC 差分或裸机恢复演练；当前还没有整机部署包。
