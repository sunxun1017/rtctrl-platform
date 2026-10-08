# RK3568 电机串口、USB 麦克风与新版 RAM 用户空间

本轮已在源码 5.10 Linux 实机确认 UART0 驱动及引脚归属，USB 麦克风格式与 Android 一致，
协议/PTY 测试通过，新 BusyBox 的模块参数实际生效。用户明确目前只连接板子、未接电机；
没有发送电机指令，也没有验证运动、停止或位置反馈。收尾已回到 Android 11/root，
五个启动分区完整 SHA 与旧 rootfs SHA 不变，最后实测电量53%，串口已释放。

当前结果见 [result.json](result.json)。构建 manifest 保留构建时的 `board_tested=false`，
本轮板测单独绑定相同产物 SHA，不把离线 manifest 改写成过去已经板测。

## 本轮实测

| 层次 | 结果 | 验证范围 |
| --- | --- | --- |
| UART0 | `fdd50000.serial` → `dw-apb-uart` → `/dev/ttyS0`，字符号4:64 | 与 Android 的 `ttySMT0` 对应同一控制器；尚未证明外部 GD32 的物理连接 |
| pinmux | GPIO0_C0/C1 的实际所有者为 UART0 | pin16/17、uart0-xfer；不是测得的电气电压 |
| 控制台隔离 | `ttyS0/console=N`，控制台仍为 ttyFIQ0 | 未打开物理 TTY；FD 快照为空仅是当时尽力枚举 |
| UART计数 | 10秒窗口及收尾 tx=0/rx=0 | 不证明电气层永久无TX；probe/寄存器诊断仍可能改变硬件状态 |
| USB麦克风 | snd-usb-audio，8通道、16kHz、S16_LE，Capture Stop | 与 Android 元数据一致；没有录音、验证音质或通道意义 |
| 独立协议与串口传输 | codec/真实 POSIX PTY 两套源码测试通过 | idle、精确TX、分片RX、损坏帧、重开、断开；PTY不是电机实物 |
| 新 RAM BusyBox | 新 SHA 已实机读回，三项 insmod 参数生效 | FW/NVRAM sysfs准确，独特 config 文件本次日志打开12bytes、PM0/band1解析 |
| RNG | rockchip-rng绑定、单次 getrandom NONBLOCK 就绪 | 没有认证；不称随机统计质量或本轮网络传输验收 |
| 旧工具 rootfs | RO cache/RO loop/ro,noload，payload与同套测试通过 | RAM/tmp probe后整文件SHA不变；旧rootfs里的BusyBox没有替换 |

所有物理 TTY 的 `cat`、`stty`、`tcgetattr`工具均未执行。即使只读打开也会走串口 startup，
默认 N_TTY 回显可能发数据。本轮额外构建的 [serial-inspect.c](serial-inspect.c) 仅在主机真实
PTY/QEMU 上验过12项，其字节在板端核对过，未用于物理 UART；不能当作无硬件副作用的诊断入口。

## 产物与复现

沿用实测 Image，未重编内核或模块：
`e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457`。
新 [UART wrapper](../../platforms/rk3568/boards/aiot-3568pq/bsp/rk3568-aiot-3568pq-uart.dts)
只把已板测 RNG DTB 的 `/serial@fdd50000/status` 从 disabled 改为 okay；
127项编译后审计、12项真实损坏DTB拒绝、无新增DTC警告，保留区不变。
DTB 162414bytes，SHA `7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1`，CRC `407e3caa`。

新版单 gzip/newc initramfs 4308268bytes，SHA
`f0965ceed549acab8d5bd87df8bb831bb06a95d08b5b7bf3c5582045933323ee`，CRC `74fea1e6`。
将 v5 两流的最终74个成员合并为76个，仅替换 bin/busybox，新增 entropy-check/serial-inspect。
最终 network-helper 叠加层完整保留。新旧实际 applet 集合均为52，纠正此前51的计数描述；没有新增 stty。
独立 cpio、6个静态 AArch64 ELF、QEMU、14个归档错误拒绝及6个构建边界检查通过。
没有厂家定制 `.so`、凭据或自动联网。无线固件仍为本机二进制，未验证重分发许可；归档不公开发布。

本轮在已准备锁定输入的工作区实际执行：

```sh
python3 outputs/rk3568-motor-alignment-20261004/build-uart.py
python3 outputs/rk3568-motor-alignment-20261004/build-userspace.py --revision v2
```

构建器拒绝已有目录、越界及符号链接；直接再次执行会因现有证据而拒绝。
复现需在独立干净工作区准备相同SHA输入，不删除或覆盖本轮记录。
另可只执行 `record-result.py`，重新核对本轮已保存的实测和产物。
当前 host 结果在 [userspace-manifest.json](userspace-manifest.json)；RAM加载前板端核对完整SHA，
U-Boot再核对三输入长度/CRC。无 saveenv/启动分区刷写。

## 清理中的真实问题与最终修正

v1复位门槛曾把 losetup/grep 读取失败的空输出当作“没有残留”；v1未执行复位，原片段红证据保留。
现在 [linux-return-guard.sh](linux-return-guard.sh) 先确认每项读取成功，仅允许五种 RAM 文件系统，
再核 loop、模块、进程、测试目录及精确 firmware_class.path 字节。18项真实脚本 mock 检查通过，
包括读取失败、非RAM挂载、模块/loop/进程残留、错误换行；失败不会输出放行标记。

v2清理另误把“换行字符串”当作恢复后的空参数：原 sysfs getter为 `0a`，恢复后实测 `0a0a`，
命令替换删除尾换行造成假通过。锁定 kernel/params.c 的 copystring setter直接复制输入，getter再追加换行。
已在模块全卸载后，仅对这个已确认的参数用单个 NUL 恢复空串，逐字节读回 `0a`。
最终 v3不修改 firmware_class.path，沿用内核默认/lib/firmware搜索；三项模块参数仍实际生效。
v3清理聚合错误并继续独立资源，实机卸载、配置删除、精确参数检查通过。
这项经验只适用于已检查的 string 参数，不能推广为所有 sysfs 文件的写入方式。

根fs/cache/debugfs/devpts、loop、无线模块与实验配置全部释放。PID1仍 `/bin/sh /init`，
704.977365秒 SysRq即时复位并返回 Android；捕获的源码内核日志（包含复位至首个DDR交接）
未见 WARNING/BUG/Call trace。普通 reboot/poweroff、裸机恢复与持续Linux启动仍未验收。
printk=7/4/1/7、kptr_restrict=2。原始日志包含设备和网络标识，仅保存在忽略的 private/。

## 电机协议的覆盖与缺口

[reference-audit.json](reference-audit.json) 记录原作者锁定 commit 的168/168 Java/AIDL文件、
163个去重对象完整检查。缺失114对象通过只读 SSH Git协议在内存读取，pack、commit/tree及每个blob哈希核对；
没有复制或重新授权私有源码，没有改变旧 partial clone。

业务调用能确认通用cmd、欢迎5/告别10、音乐26、唤醒1/25、随机12–15/21–24及FA原始角度。
这些只是应用触发关系。命令14同时出现在随机集合，不能当急停；6/8秒是发送节流而非动作完成。
返回回调只有长度日志，升级ACK仅弱命令回显，没有停止/去使能/关节反馈契约。
唯一AIDL为 provisioning，厂家 UART Binder/JNI实现及 MCU固件不在这个源码范围。
现有 codec仅链接测试，未实现生产 `IActuatorProtocol`，不会因本轮串口绑定成功而接入自动运动。

[固件来源调查](firmware-source-audit.json) 已查1027项完整树及736项assets；仅有5个语音命名bin，
没有可识别电机固件。未读取这些二进制，大小未知。业务升级通过消息URL下载到应用外部files/downloads，
板端两种路径当前均ENOENT；没有执行下载或升级，也不能据此证明MCU内部或板上别处没有固件。

下一步并行分成两条实际工作：补电机MCU协议/固件与安全停止证据；恢复已有源码的传感器与其他外设。
[NEXT-PERIPHERALS.md](NEXT-PERIPHERALS.md) 已给出加速度计、触摸和板载音频的具体连接、配置及驱动缺陷。
MXC6655探测错误会被吞掉，必须先修正并做短传输/错误ID测试，不能把绑定成功直接写成外设对齐。
