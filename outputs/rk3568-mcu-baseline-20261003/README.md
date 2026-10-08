# RK3568：独立源码程序的 Android / Linux 对照

2026-10-03，复用原 4.19.232 内核和原 FDT，在 Android 11 与独立 RAM Linux 中运行了
同一份三个静态 AArch64 程序。协议 codec、POSIX PTY 收发和新增 MCU 缓存诊断均通过。
程序不依赖厂家 Jar、Binder、JNI 或运行时 `.so`；内核仍是原厂二进制过渡基线。
这一步完成用户态接口替代的基础验证，没有完成电机控制或板控 MCU 驱动移植。

机器摘要：[result.json](result.json)。接口事实与下一阶段约束：
[MCU-INTERFACE.md](../../platforms/rk3568/boards/aiot-3568pq/MCU-INTERFACE.md)。

## 三项实际结果

| 程序 | 原 Android | 独立 Linux | 验证范围 |
| --- | --- | --- | --- |
| `rtctrl_patchx_codec_test` | 通过，exit 0 | 通过 | 向量、分片、损坏输入、容量边界、字节 transport；没有打开硬件 UART |
| `rtctrl_patchx_pty_test` | 通过，exit 0 | 通过 | PTY 空闲/精确发送/分片接收/损坏输入/重开/断线；没有打开 ttySMT0/4 |
| `read-cached-mcu-info` | exit 0，六字节全零 | 同样输出 | 只读原内核缓存，未查询物理 MCU |

Android 的 PTY syscall 记录仅打开 `/dev/ptmx` 和当次 `/dev/pts/0`。
缓存程序记录为 O_RDONLY 打开 `/dev/McuCom`、一次 `ioctl(0xc0)`、关闭、exit 0。
独立 Linux 的 PID1 为 `/bin/sh /init`；使用 devtmpfs/proc/sysfs/tmpfs，临时 devpts 用于 PTY。
测试完成后 devpts/cache 均卸载，loop 列表为空。普通 `reboot -f` 返回 Android 后，
通过串口再次运行三个程序，输出一致。

脱敏输出：[runtime-check.txt](runtime-check.txt)。这些测试不证明真实 UART 收发、电机 ACK、
停止/限位行为、物理断电或 MCU 看门狗接管；没有下发执行器、未知查询或升级命令。

三个实测程序均为静态 ELF64 AArch64，无 PT_INTERP/DT_NEEDED，使用 GCC 11.4 构建：

| 程序 | 字节数 | SHA-256 |
| --- | ---: | --- |
| codec-test | 2136440 | `18fd4744d881e46661d16ad60112f395262b6a6e97ce83f246a4334f6448234c` |
| pty-test | 2134160 | `5eb5fd9aba8133933dce602d5e0dbd3acf5f1829f700615dc77a67b5f1d0cbda` |
| read-cached-mcu-info | 646680 | `97fca95e70d8634e19942f3c13ba02cf590fac401e1d553f855ed875ce532dc2` |

## 原 Android 的被动基线

- ttySMT0 对应 `fdd50000.serial`，ttySMT4 对应 `fe680000.serial`。
  两个被动窗口前后 UART0/4 的 tx/rx 均为零。
- ttySMT1 对应 `fe650000.serial`，当时 eGTouchD 持有该设备；不能凭串口编号当作电机接口。
- I²C5 `5-0062` 已绑定 McuCom，节点 `/dev/McuCom` 为字符设备 10:61。
  运行设备树 `i2c@fe5e0000/mcuinf@62` 含零长度 `skip-mcu` 和 `powerkey-controller`。
- 创建独立 ftrace instance，过滤 I²C5/地址 0x62 的 read/write/reply 和 I²C5 的 result。
  成功窗口分别为 30.31 秒和 30.27 秒，均无这些事件；第二次含 10 条自身 shell 的
  sched_switch 正对照，所有 CPU overrun/dropped 为零，instance 清理成功。
  缓存程序调用位于第二次观测窗口内。这是 tracepoint 窗口证据，不是逻辑分析仪抓包。
- 描述符所有者清单只作尽力枚举：进程可能退出、部分 `/proc` 访问可能失败，不能据空清单证明无人使用。
  未打开真实 UART 做探测，也没有执行原 `mcu_tool`。

[observe-android.sh](observe-android.sh) 保留 root/wifi tracer，逐项清理自己创建的 instance。
第一次按每个 FD 启动 readlink 的慢枚举在 tracing 开始前被终止；它不是成功观测窗口。

## 如何独立实现缓存诊断

先对已经备份的原 `boot.img` 提取 Image，再将原机选定符号与反汇编对应。
不是按 `mcu_tool` 名字猜接口：该工具只有 `notify_power_on` 路径，会调用有写入效果的
0xaa，且忽略 ioctl 错误；它不能用于只读诊断。

静态分析确认原驱动 open/release 无硬件操作，0xc0 使用完整 65 字节用户缓冲，
把六个内核缓存字节复制到偏移 32–37，返回 0；该路径没有 I²C、GPIO 或看门狗操作。
由此独立编写 [read-cached-mcu-info.c](read-cached-mcu-info.c)，不用原厂用户态库。

调用输出为：

```text
MCU_CACHE_BYTES=000000000000
SOURCE=kernel-cache; physical MCU status not queried
```

这里的全零可能与 `skip-mcu` 跳过缓存初始化有关，不能当作 MCU 的真实版本、电量或健康状态。
程序没有自动核验驱动 Image 指纹。**只允许用于本记录对应的原驱动**；同名设备、相同
`uname -r` 或 ioctl 返回 0 都不足以建立另一个驱动的兼容性。
它是一次性诊断程序，不是已经开放源码的 MCU 内核驱动或实时控制接口。

## 构建与复现顺序

主机需要 CMake/Ninja、aarch64-linux-gnu GCC/G++ 和 binutils。
在仓库根目录运行以下分开的命令；构建脚本拒绝覆盖已有产物目录：

```sh
sh outputs/rk3568-mcu-baseline-20261003/build-source-tests.sh
sh outputs/rk3568-mcu-baseline-20261003/build-cached-mcu-info.sh
```

codec 与 PTY 的源码分别在
[协议适配器](../../adapters/actuator/patchx/README.md)、
[测试](../../adapters/actuator/patchx/tests/test_patchx_pty.cpp)和
[POSIX transport](../../adapters/transport/serial/src/posix_serial_transport.cpp)。
通过真实 CMake 目标编译，未用未参与构建的文件或其它板测替代。
上表 SHA 标识本次跨系统运行的同一份产物，不承诺任意编译选项得到相同二进制。
新增构建脚本本地重建的诊断程序通过静态 ELF 检查；本地重建产物未另行上板，
不能把这个构建检查追加成第四项硬件验收。

重新上板前核验当前串口/地址、原 Image 指纹、McuCom 绑定、cache 的 PARTNAME/容量、
已验证备份和 RAM 启动入口；不要照抄历史端口或块设备号。
先在 Android 运行同一份三个程序、检查哈希，再存入新建的普通实验目录。
[stage-linux-tests.sh](stage-linux-tests.sh) 只复制普通文件，保留原 printk 值，不改启动分区。

随后沿用已经验证的
[原内核 RAM 启动方法](../rk3568-backup-linux-20261003/README.md)，
执行 [run-linux-source-tests.sh](run-linux-source-tests.sh)。该脚本限定原 4.19.232、
cache 的 PARTNAME 和 786432 个扇区，检查 SHA，运行测试并清理挂载。
[linux-source-tests.json](linux-source-tests.json) 为串口操作步骤；
[linux-clean-check.json](linux-clean-check.json) 用短命令独立确认清理。
未知挂载/loop 存在或清理失败时，先解决再重启。

当前公开脚本已把 cache 的只读挂载改为 `ro,noload`，防止 ext4 日志回放；
**本次真实运行的是修改前的 `ro` 版本，未重新上板验证 `noload` 版本**。
`ro` 仍可能回放日志，不能宣称本次没有任何块设备写入。
本次板端 runner SHA 为 `12090ced0f8bfa424c115719f2f38a8c14116a75c71a9aa58f29c1acf4d4109c`，
不要把后来修改的脚本哈希当作当时实测版本。暂存脚本随后移除了 printk 写入；
本次曾临时降低日志级别，返回 Android 后已重新核验为 7/4/1/7。

## 静态分析的证据标识

- 原 `mcu_tool`：11424 字节，SHA `17e779014b75383a04fb0e32aca76fcbba342c4970840154fccdb5ca464058b9`。
- 原 Image：33046536 字节，SHA `54e75d6dbb03ab96ea938eb940fe64cab91f3f81a3e43a9e98d763980dd7779d`。
- FDT SHA `f81341ac00389e88a91864dfc251ae0e10217135539a38b4bf434e1ae9ddef52`。
- RAM bootstrap：621289 字节，SHA `157acfd6f5d3ffbdcebe6ea492fe3b9e01a48207323c14fdb9bf25425437dc65`。

[extract-original-image.py](extract-original-image.py) 校验提取边界、长度及 magic，拒绝覆盖。
[collect-kernel-symbols.sh](collect-kernel-symbols.sh) 暂时调整 kptr_restrict 以读取选定符号，
两次均通过 trap 恢复为 2；末尾再次核实为 2。没有持久修改安全策略。
原二进制、地址符号、反汇编及未脱敏日志留在被忽略的 `private/`，不随公开源码分发。

## 收尾状态与下一阶段

独立 Linux 清理完成后正常重启返回 Android 11，串口确认 `sys.boot_completed=1`、root 和
4.19.232。原 boot/uboot/trust/dtbo/vbmeta 五项 SHA 与已验证备份一致；未 saveenv 或刷写启动分区。
root tracer 为 0/nop，只有原 wifi instance。printk 为 7/4/1/7，kptr_restrict 为 2，串口已释放。

网络 ADB 未恢复：wlan0 为 UP/LOWER_UP 且有 IPv4，adbd running，但主机连接 5555 超时，
板端 ping 路由器 2 包均丢失。未把它误报为正常网络，也未因此反复重启。
下次先重新核验供电、串口及网络；地址/信号状态不是跨任务常量。

下一阶段有两个独立工作面：

1. 公开可重建内核：现有 5.10 候选只有构建证据，先核对原板电源/I²C5/UART 配置，
   用 RAM 启动验收基础 shell，再适配已分析的板控契约。不能把本次原 4.19 板测当成 5.10 成功。
2. 真实运动控制：参考 Java 没有已证实的只读遥测命令；先取得 MCU 文档或被动监听已知动作，
   明确 ACK、单位、限位、停止和失联行为，再把独立 codec 接入硬件。命令 14 不能按猜测充当停止。

原驱动 `skip-mcu` 的静态行为和正常路径寄存器事实见接口说明。
还没有 MCU 固件源码、真实反馈或超时测量；完整开源发行物仍需列出内核、模型、固件与 loader 的源码/许可缺口。

本地收尾检查通过：三项实测产物 SHA/静态 ELF、五个实机启动分区 SHA、shell/Python/JSON 语法、
文档本地链接及 `git diff --check`。独立只读审查没有发现新的阻断问题。
最后一次串口检查仍为 Android `boot_completed=1`，完成后关闭串口。
