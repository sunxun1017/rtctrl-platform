# 新 RK3568 开发板迁移检查

2026-10-07。用户换用带屏幕、电机等外设的开发板，本轮通过网络 ADB 连接成功。
原 Android 和板级配置与旧 AIoT-3568PQ 基线一致，独立静态用户态验证通过。
完整 Linux 迁移仍需调试串口进入 U-Boot、验证返回路径，再启动现有 RAM 候选。
用户确认现场只有网络 ADB，本轮保持 Android。

## 板型与配置

型号 `3568A`，RK3568，约 4GB 内存、64GB eMMC；Android 11/API30、内核 `4.19.232 #49`。
fingerprint、`MemTotal=3802460kB` 与旧板相同。新板完整内核配置 36,644B，
SHA256 `709d54fd7827fae674a8f03746529150038dff7fc493f558cb1e2fc51cc75fff` 与旧板一致，
`CONFIG_KEXEC` 未开启。

[完整设备树比对](fdt-comparison.json)核对两份 151,680B 原运行树：760 个节点、4,756 项属性，
无节点新增/删除，保留内存相同。8 项属性差异仅涉及序列号、CPU/eMMC 标识、MAC、启动计数；
其中 bootargs 只变 `androidboot.serialno`、`cid`、`cpuid`。其余供电、内存、引脚、屏幕初始化、
音频、UART、SPI/I²C、MCU 属性字节相同。这支持复用现有板级配置，实际外设功能需在新板验收。

| 原 Android 枚举 | 本轮状态 |
| --- | --- |
| DSI 屏与背光 | `connected`、720×720，背光 127/255；只读状态 |
| 板载声音 | RK809，I2S `fe410000`，当前声卡1 |
| USB 音频 | Bothlent UAC Dongle，当前声卡0，仅采集端点 |
| CAP1188 | SPI3.0 的 `cap1188_input` 已注册 |
| MCU 与串口 | `/dev/McuCom`、`ttySMT0` 和 `ttySMT4` 等节点存在；真实电机身份、ACK、停止和 watchdog 尚待验收 |

声卡序号取决于当前 USB 枚举，后续产品配置使用稳定设备身份，不能照搬旧序号。
软件枚举不等于画面、声音或电机动作验收。本轮没有打开物理 UART 或发送动作命令。

## 本轮备份与用户态验证

本机保存了 `boot/recovery/dtbo/uboot/trust/vbmeta/baseparameter/misc` 八个完整分区，
合计 161,480,704B。每份均核对板端读取前 SHA、电脑完整文件 SHA、板端读取后 SHA。
七份可直接与旧 manifest 对比的分区全尺寸/SHA 一致；recovery 为本次新板自己的完整备份。
备份范围不包含完整 eMMC、用户数据，也尚未验证裸机恢复。

现有源码构建的三个静态 AArch64 程序已上传到独立目录
`/data/local/tmp/rtctrl-newboard-20261007`，逐份核对 SHA 后执行：

| 程序 | 板端结果 |
| --- | --- |
| BusyBox `uname` | `aarch64`、`4.19.232`，exit0 |
| PatchX codec 自检 | 向量、分片、损坏、容量与字节传输通过，exit0 |
| POSIX PTY 自检 | 空闲、发送、碎片接收、损坏、重开与挂断通过，exit0 |

PTY 只使用伪终端，结果证明独立 Linux 用户态在原 Android 内核上的软件兼容性，
不能替代电机实物串口或独立 Linux 内核验收。全部八个备份分区在验证后 SHA 保持，
boot_id 保持，原 Android `boot_completed=1`。诊断程序已结束，目录保留以便继续核查。

原始 ADB 输出、设备标识、启动备份和运行收据留在忽略目录
`baseline-v1/`、`backups-v1/`、`runtime-v1/`。公开比对仅保存属性路径和摘要，
不公开原厂二进制、设备标识值、完整日志或网络凭据。

## 接调试串口后继续

现有 [audio-v5 离线 RAM 候选](../rk3568-audio-runtime-20261005/offline-next-delivery-v1/README.md)
完整启动包 SHA `90e663bc…59dc0b1`、CRC32 `4427a536` 与记录一致，匹配声音模块
SHA `c43e470c…e13d85`。本轮仅重新核对这两个完整文件；原离线封装审查范围保持。
候选尚未上传或在新板启动，5.10 模块不能加载到当前 Android 4.19。

先连接开发板调试 UART，确认实际接线和电平。旧方案使用 UART2/FIQ、1500000 baud、8N1；
COM 编号需重新识别。通过串口验证原系统 U-Boot CLI、内存布局、当前分区和原 Android 返回，
再按 [接线后验收入口](../rk3568-audio-runtime-20261005/NEXT-HARDWARE-VALIDATION.md)
安排有限 RAM 启动与逐项外设测试。电池参数和物理电源链、USB 恢复及正式 eMMC 启动仍需闭合。
实际电机测试先建立身份、反馈与可靠停止契约。

## 本轮工具

[采集与备份](collect-baseline.py)保存白名单 ADB 查询、完整 FDT 和有限启动分区；
[用户态部署](deploy-userland.py)将固定 SHA 的现成诊断部署到新建测试目录；
[离线比对](compare-baseline.py)核设备树、备份、配置、运行收据与两份候选文件。
工具均只服务本轮有限验证，未修改 C++ 应用、内核、设备树或 CMake 接线。
运行和备份输出目录拒绝覆盖；离线比对更新本轮摘要。

独立复核发现检查工具对备份缺项的失败拒绝不足。原八份实际数据均完整，
随后仅补上尺寸/读取失败退出、部署前八份唯一备份的全尺寸/SHA检查和摘要的八份全核回。
内存模拟复现旧失败路径并核对修复，原板端19步骤和收据保持，未再次部署或运行板程序。
最终独立只读复核另外核对八份实际备份、完整FDT、静态ELF/来源、原19步骤和修复后的缺项拒绝；
未发现未解决问题。本轮仍只完成兼容性与原Android上的用户态验证。

## 原厂控制程序停止

随后用户报告板子持续控制电机，要求关闭对应进程。原厂主应用 `com.patchx_main`
最初PID1967，第一次 `am force-stop --user 0 com.patchx_main` 后短时消失，随后重新出现为PID4422。
因此执行 `pm disable-user --user 0 com.patchx_main` 再次force-stop。
观察至少20秒后PID查询为空、exit1，包状态 `stopped=true`、`enabled=3`（disabled-user）。
包和数据保留，原Android正常；`com.patchx_sys` 保留，未向电机或物理UART发送命令。

[实际停止结果](motor-process-stop.json)只证明主程序已停止并禁止启动；电机实物是否停止尚待用户反馈。
恢复应用的命令为 `pm enable --user 0 com.patchx_main`，本轮没有执行恢复。
地址与PID属于当时记录，下次继续操作前重新确认。

用户随后明确反馈电机仍持续同向转动，主应用停止不能视为实物停转。
全机FD快照和四个候选应用67线程的8秒短时跟踪未捕获新的设备打开；
这一有限窗口只覆盖厂家服务、PatchX后台、压力测试和串口测试应用，不保证其他线程/MCU没有控制。
参考动作发送路径会发送后立即close，因此FD空也不能证明历史动作已停止。
厂家`smdtserver`接口同时承载板控电源与看门狗，保留其进程；停止/去使能协议尚未验证。

随后force-stop了`com.patchx_sys`与`com.smdt.test.basic`。用户仍反馈一直转动，
PatchX后台又出现PID5308，故再对`com.patchx_sys`执行disable-user和force-stop。
后核两PatchX应用均无PID、stopped=true/enabled=3；串口测试无PID、stopped=true，仍保持可启用。
随后用户明确回复“现在好了”，本轮停转按用户现场反馈确认；软件没有独立测量电机运动。
实际最后有效的操作是禁用并停止PatchX后台。此前归因于电机板保持先前命令的假设未被验证，
不能据此确定真实发送线程或MCU语义；电机/接线身份和可靠协议仍待后续适配。
[追加诊断与操作](motor-control-followup.json)记录范围、原始trace身份和最新应用状态；
未发送未知停止命令，未关闭厂家多用途系统服务。
后台应用恢复命令为`pm enable --user 0 com.patchx_sys`，本轮未执行。
