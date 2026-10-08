# RK3568 加速度计源码驱动与两套系统对照

2026-10-04。本轮完成错误传播修正和一次 RAM Linux 往返，**没有完成加速度计功能验收**。
原 Android 与源码 Linux 在 I²C5、地址 `0x15` 读取 `WHO_AM_I` 时均报告 `ENXIO`。
没有测得预期 ID `0x05`，不能据此确定器件未安装，或认定某根线、供电有故障。
板子已返回 Android 11 / 4.19.232，root 与 `boot_completed=1` 再次确认；最后读取电量 41%。

机器结果见 [result.json](result.json)。原始串口、Android 状态、反汇编和失败尝试在忽略的
`private/`；构建产物也不纳入公开源码。公开记录只保存有界结论和摘要，不含网络凭据与设备身份。

## 实际做了什么

| 层次 | 本轮结果 | 尚未证明 |
|---|---|---|
| 原 Android 基线 | `5-0015` 有驱动 symlink，但没有 gsensor 输入或 `/dev/gsensor`；原启动日志有 ID 读取失败 | 驱动绑定不证明芯片可用 |
| GPL 驱动 | 修正短 I²C 传输、读错误、ID/init/probe 返回及 class 创建失败清理；实际 Kbuild 构建两模块 | 成功采样、卸载与并发校准生命周期 |
| 设备树 | 仅启用 I²C5、加入 MXC 节点及 IRQ pinctrl；保留原总线引脚、30ms、layout1、irq_enable0 | 原节点无明确电源属性，不能还原供电实物 |
| Linux 板测 | 两模块实际加载，probe 返回 `-6`，不再留下假绑定；固定 WHO 读也是 errno6 | ID、初始化、硬件默认 OFF、采样/方向 |
| Android 对照 | 按本机原 Image 的 24-byte I²C 消息布局单次读 WHO，返回 ENXIO | 不推广到其他厂商 Image 或其他控制器 |
| 收尾 | cache/debugfs 释放，只剩 RAM 文件系统；保留模块，SysRq 返回原 Android | 正常 poweroff/reboot、模块 remove、裸机恢复 |

没有打开电机物理 TTY、发送 MCU 帧、扫描 I²C 总线或写校准。用户确认电机未连接。
UART0 的 GPIO0_C0/C1 归属保留，本次收尾 TX/RX 均为 0。
没有加入 MCU `@62`、EEPROM 或其他未知 I²C 子设备。

## 补丁和真实构建关系

源码锁定 commit `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`。
公开修正在 [0005-sensor-error-propagation.patch](../../platforms/rk3568/boards/aiot-3568pq/patches/0005-sensor-error-propagation.patch)，
只涉及 `sensor-i2c.c`、`sensor-dev.c` 和 `accel/mxc6655xa.c`，SHA256 为
`cff9f21c036173bc4465cf51ee414e77fc2456e8e0c15d84f0e74d414a64d184`。

短传输转成 `-EIO`，负 errno 保留；读失败不再作为寄存器值使用。
每次 ID 重试都重新设置读地址，只有读成功才更新 ID；错误 ID 返回 `-ENODEV`。
初始化和 probe 的 errno 向上传递，失败清空 ops/clientdata。
class 创建/属性注册失败按已取得资源清理，不把 ERR_PTR 当作有效 class。
MXC 的 active/init 路径在读失败后停止后续写，写成功才更新缓存。

采用外部 `obj-m` 构建 `sensor_dev.ko` 与 `mxc6655xa.ko`，使用已实测 Image 对应的
headers、完整 `.config`、`Module.symvers`。原 `.config` 仍为 `CONFIG_SENSOR_DEVICE=n`，
没有重新编译 Image，也没有修改第三方源码树或原 ABI 构建目录。
vermagic、GPL 许可证、AArch64 ELF 和导入符号闭合均核对；同名 kernel release 单独不够。

原 sensor 框架的 remove/open-FD/校准并发问题仍在：本轮不调用 rmmod、不打开输入设备、
不请求采样或校准。加载后的两个模块一直保留到 RAM 系统复位。
本次 probe 在 ID 阶段失败，没有走到 CONTROL/MASK 初始化写；这不等于已测得器件关闭。
I²C 读取包含寄存器地址写入，不能称为电气上零副作用操作。

## 设备树与启动输入

[独立加速度计 DTS](../../platforms/rk3568/boards/aiot-3568pq/bsp/rk3568-aiot-3568pq-accelerometer.dts)
叠加此前 UART/RNG/Wi-Fi 候选。I²C5 M0 为 GPIO3_B3/B4、mux4、无内部上下拉、施密特输入；
IRQ 为 GPIO3_C1，`irq_enable=0`。这些与 UART0 引脚不冲突。

编译时保留此前 760 个 phandle 的数值，以便对实际 DTB 做逐属性对照。
只有 15 项属性变化；其他旧属性值、旧节点顺序和 memreserve 保留，不能称整个新 DTB 字节不变。
151 项检查、13 个真实编译错误候选拒绝、零新增 DTC warning。
实机看到 I²C5 GPIO3_B3/B4 归 `fe5e0000.i2c`，加入的 `5-0015` 在模块加载前未绑定。

| RAM 输入 | 字节数 | U-Boot CRC32 | SHA256 |
|---|---:|---|---|
| 已测源码 Image | 34755072 | c91762d1 | e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457 |
| 加速度计 DTB v3 | 162863 | 85f45284 | e76139f3c9b978cbceb786ae26eb31c9618e32529f0dc9a8e4bbf1b778c77e12 |
| 此前新版 RAM initramfs | 4308268 | 74fea1e6 | f0965ceed549acab8d5bd87df8bb831bb06a95d08b5b7bf3c5582045933323ee |

Image 配置 SHA256 为 `1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912`。
实际使用 v1 两模块：sensor_dev SHA `4dee08efa9a0214a089f0e615f8cc5f40035e3d330905d5ec05ab6de1a96d8a1`；
MXC SHA `f6b67fb459375e93b916b0df1a9b9e1996f90ede410b364bed63518c390099f9`。
v2 是另一次 host 重建，没有上板；去掉 debug/build-id 并只归一化 MXC 的一处源码路径后代码一致，
不声称两次完整 ELF 字节一致。

加载到已核实的 RAM 范围，三输入长度/CRC 在 U-Boot 读回。
仅修改内存 FDT/环境，删除原 Android 两项旧 initrd memreserve；未执行 saveenv 或刷写启动分区。
PID1 的 exe=`/bin/busybox`、argv=`/bin/sh\0/init\0`、ELF SHA 均实测匹配。
`/proc/1/comm` 实际为 `init`，不能用预想的 `sh` 名字替代身份核验。

## Android 的私有 I²C 布局

最初用标准 Linux 工具读取原 Android 得到 `EFAULT`，这不是芯片身份结论。
对已备份原 Image 的 kallsyms/实际反汇编核查，发现其 `i2c_msg` stride 为 24，
标准 ARM64 布局为 16；外层 `i2c_rdwr_ioctl_data` 为 16。
地址/flags/len/buffer 偏移分别为 0/2/4/8，尾部 8 字节字段名字未知。
不能仅凭版本 4.19 或上游头文件推定厂家的 UAPI。

[离线摘要](android-abi-audit.json)限定原 Image SHA
`54e75d6dbb03ab96ea938eb940fe64cab91f3f81a3e43a9e98d763980dd7779d`。
审查的 RK3x 消息路径没有使用这 8 字节尾部，故本机专用工具将其清零。
这只适用于该精确 Image 与控制器路径；没有运行时证明初次 EFAULT 的具体失败指令。

[android-identity.c](android-identity.c) 必须显式选择 `--android-legacy24`，不自动探测/回退。
固定 `/dev/i2c-5`、char89:5、地址15，只用一次 ioctl 组合写 WHO 索引0f/读一个身份字节。
不 force、不扫描、不写控制寄存器值。成功标记在关闭设备成功之后输出。
实际运行前校验原 boot 分区 SHA、原 kernel/Android、RK3x 绑定和工具 SHA。
返回 `I2C_RDWR: No such device or address`、rc2，未出现身份成功标记。
Linux 独立工具读相同 WHO 返回 errno6/rc1。两套系统一致失败，具体硬件原因仍需实物资料与测量。

## 测试与实际失败记录

最终 [verify-host.py](verify-host.py) 独立复跑驱动函数、DTB、两 helper、reset guard 和运行依赖，全部通过。
14 项模块审计另由 test-driver-modules.py 完成，记录在忽略的 driver-module-tests-v2/result.json。
设备调用在 host/QEMU 测试中用 mock，与上述真实板测分开记载：

- 原驱动函数 C harness 72 项，覆盖真实 probe/irq 初始化函数、默认不排队、错误传播和资源清理；
  修正前保留了有失败的红测。
- 真实 ELF/导入/构建输出边界 14 项；新 DTB 151 检查和 13 编译故障候选。
- 标准 I²C helper 13 项；legacy24 helper host18 与静态 AArch64 QEMU18，含调用顺序/短传输/close失败。
- 实际 reset guard 脚本 16 fixture 用例；精确 RAM BusyBox 52 applet、声明的18依赖与4脚本语法通过。
  依赖检查不是完整 shell 静态分析器。

另修复发布后的 prepare 入口：已有公开补丁只有逐字节匹配生成结果才复用，匹配时 inode/mtime/mode/内容不变；
篡改、符号链接、已有/越界输出拒绝。真实 main 红测3失败，修正后10项通过；实际 source-v2
重新生成的三份候选源码 SHA 与 v1 一致，未额外上板。

保留了本轮脚本问题及修正，避免把失败尝试写成验收：

1. 最初 PID1 comm 检查期待 sh，但实际为 init；失败发生在 cache 挂载前，改为 exe/argv/SHA。
2. RAM BusyBox 没有 base64；上传后 hash 门槛拒绝空脚本。改用 shell printf 的八进制传输。
3. RAM BusyBox 也没有 id；枚举/探测都在模块加载前停止。改用 `/proc/self/status` 四 UID 字段。
4. 最终 `linux-runtime-v4-upload.raw.txt` 七输入 SHA 通过后才执行枚举与 probe。
   transport 的最终成功 marker 仍名为 V3；v4 文件名和七项 SHA 确定实际版本。

`runtime-manifest-v4.json`、各 build manifest 的 `board_tested=false` 是构建时快照；
实际板测结果单列于 result.json，不将准备记录改写成历史上已上板。
标准 helper 的完成文字早于 close，但板测脚本要求进程 rc0；本次 rc1 不会被接受为成功。

## 复现入口

以下在 WSL 仓库根目录执行。需要锁定第三方源码、AArch64 GCC11/binutils、DTC、
先前同 Image 的完整 ABI 构建目录与 UART/RAM 输入；前序来源和构建见
[RCU Image](../rk3568-rcu-reset-20261004/README.md)、
[UART/RAM 用户空间](../rk3568-motor-alignment-20261004/README.md)。
目前不是一条脱离前序输入的整板发行构建命令，firmware/loader/DDR/trust 仍须单列。

新检出目录首次生成候选与函数测试，再构建外部模块；已有匹配公开补丁应复用，不能改写：

```sh
python3 outputs/rk3568-accelerometer-20261004/driver-prepare.py --version v1

python3 outputs/rk3568-accelerometer-20261004/test-driver-functions.py \
    --source-dir outputs/rk3568-accelerometer-20261004/driver-source-v1/drivers/input/sensors \
    --label green-v2

python3 outputs/rk3568-accelerometer-20261004/build-modules.py --version v1
python3 outputs/rk3568-accelerometer-20261004/build-dtb.py --revision v3
python3 outputs/rk3568-accelerometer-20261004/build-inspect.py
```

Android 专用工具另需要本机原 Image 备份及对应离线 ABI 审查，不能把它当作通用 Linux 工具。
在全新测试输出目录先生成三份规定的记录；下面红测预计非零，并应有11项失败，随后两绿测各18项零失败。
该负对照只在 host mock 上运行，不访问硬件：

```sh
python3 outputs/rk3568-accelerometer-20261004/test-android-identity.py \
    --label red-v2 --wrong-baseline

python3 outputs/rk3568-accelerometer-20261004/test-android-identity.py --label green-v1

python3 outputs/rk3568-accelerometer-20261004/test-android-identity.py \
    --label green-v2 --aarch64-qemu

python3 outputs/rk3568-accelerometer-20261004/build-android-identity.py --version v1
```

各生成器拒绝覆盖已存在的输出目录。本轮现有产物再核验用未使用的 revision：

```sh
python3 outputs/rk3568-accelerometer-20261004/verify-host.py --revision v2
python3 outputs/rk3568-accelerometer-20261004/record-result.py
```

verify-host 的 v1 已在本机完成；v2/v3 会生成独立新测试目录，不能重复使用同一 revision。
record-result 核验本轮最终 v1 测试记录和私有原始日志；额外复跑不自动替代该历史证据。
它不能在新机器凭空生成板测成功。
串口操作顺序以 load-ram.json、boot-ram.json、linux-stage.sh、runtime v4、
linux-enumeration.sh、linux-probe.sh、linux-return-guard.sh、return-android.json 为证据入口；
旧失败 session 不能直接重新执行。上板前重新核实端口、供电、机械状态和所有指纹。

## 返回结果与下一步

538.169568 秒 SysRq 后进入原 DDR/U-Boot/Android 流程。
已捕获源码 Linux 日志至首 DDR 未见 WARNING/BUG/Call trace。
五个启动分区完整 SHA 前后相同；旧 source rootfs 前后相同；旧64MiB network rootfs 的本次读回
与此前锁定基线相同。本轮初始 raw 没包含 network rootfs，不能称两份本轮日志都测了它。
这些不是完整 eMMC 差分，也不代表已经实测恢复备份。普通 cache/data 中的新诊断文件保留。

加速度计后续先确认本板实装芯片及该传感器的供电/连线，再取得正确身份，随后才验初始化、
默认关闭、方向和采样。若缺少实物测量条件，可独立推进已在 Android 正常出现的 CAP1188
SPI 输入或板载音频适配，保留此缺口。电机真实返回帧、停止/使能/watchdog仍未确认，
不能把源码 codec/PTY 成功当作实物运动对齐。
