# PatchX Android 协议与 Linux 并行适配记录

日期：2026-09-21。对应“帕奇硬件框图”Linux 平台化工作，和 RK3568 内核配置任务并行。
本记录只覆盖 Android MCU 协议审计与离线 codec。内核、板级总线、设备树接线由另一任务维护。

## 来源及能复用的部分

参考仓库：`git@github.com:patchx-team/PatchX-Android-Main.git`。
本次读取本地副本，HEAD 为 `ed91ef7486cdebca00aa32d497f5aa45cb226c0e`，提交日期 2025-10-28。
2026-09-21 访问公开 GitHub 页面返回 404；不据此判定仓库删除或私有，也没有重新拉取证明远端最新状态。

以下路径均相对于该参考仓库的 `PatchX-Android-Main-C/app/src/main/java/`。
外层工程没有找到第二套 MCU 字节协议，不能把两个目录当成两份互相验证的固件实现。

| 证据 | 已确认事实 |
| --- | --- |
| `com/patchx_main/patchx/util/ComProtocol.java:45–84` | 完整发送格式、长度、CRC 和端序 |
| 同文件 `:87–90` | 所谓 ACK 仅检查长度至少 5 和第 5 字节等于命令 |
| `com/wcy/testserial/FirmwareUpgradeManager.java:137–198` | 升级发送器同样封帧；块大小最多 256 字节 |
| 同文件 `:201–205` | 升级 ACK 同样没有全帧/状态/序号验证 |
| `com/patchx_main/patchx/manage/DeviceManager.java:344–426` | 原始角度及普通动作发送、串口参数和未启用的周期任务 |
| 同文件 `:112–115` | 版本 `1.0.0` 和电量 `72` 为硬编码，不能当遥测格式 |
| `com/patchx_main/patchx/manage/UpdateManager.java:241` | 升级使用另一串口路径 |

下列 SHA256 对应实际读取的本地文件（CRLF 换行），不是 Git 提交 blob 的 hash。
两份文件均已用忽略行尾差异的 Git diff 确认与提交内容一致。
`ComProtocol.java` SHA256：
`aea566ca53f604af784063e6c15c2b20c24dd49bce0ce3b0361db3bfae34ae38`。
`FirmwareUpgradeManager.java` SHA256：
`6520d8dafe3f644934be6de4546d36aa152e2890e2b7e952d22413319326e371`。

## 发送帧与命令

```text
FF FF | body_length_be16 | command | data... | crc_be16 | 55 AA
body_length = 1 + data_length
wire_length = body_length + 8
CRC16/Modbus: init FFFF, reflected polynomial A001, no final XOR
CRC input: the two length bytes + command + data
```

CRC 高字节先。DATA 原样复制且没有转义。普通帧没有序号、设备 ID、时间戳或物理单位。
Android 发送器未限制最大长度，本实现显式拒绝超过本地固定容量的输入，不复制截断行为。

| 命令 | 源码已确认的载荷 | 尚未确认 |
| --- | --- | --- |
| 普通动作 | 空载荷，body length 为 1 | 完整动作含义表、机械限位、执行状态 |
| `FA` | `angle & FFFF` 的 BE16 原值 | MCU 单位、正负方向、零点及对应关节 |
| `DE` | 固件总字节数 BE32 | 原机升级状态机及完整 ACK |
| `DF` | 从 1 开始的包序号 BE16 + 块长度 BE16 + 数据 | 超时/重试幂等性、刷写完成及版本确认 |

固件块格式仅用来确定容量和测试字节编码，**没有实现刷写/升级执行器**。

普通串口代码为 `/dev/ttySMT0`、115200、8 数据位、1 停止位、parity=0、flow_ctrl=0；
升级代码却使用 `/dev/ttySMT4`。这些是 Android 原路径，不能直接映射到新 Linux 的 tty 名称或 UART 引脚。
`smdt.jar` 仅提供 Binder 转发；`SerialPortUtil.java` 是 JNI 声明，不能从中确认内核驱动及短读写语义。

## 不能用原实现证明的部分

- `resp.length >= 5 && resp[4] == cmd` 会把 `00 00 00 00 DE` 当 ACK；不能表示设备确认或运动完成。
- cmd 14 的注释说“复位”，但它同时出现在随机表情动作集合。没有依据把它写成急停或去使能。
- “60 秒无发送则发 14”的 `startCheckTask()` 只有定义，没有发现调用；不是已实现的 MCU watchdog。
- 普通发送是 open → send → close → 注册 receive，未检查 `sendResult`，回调只打印大小。
  不能由此复原可靠的 MCU 接收协议。
- 未找到电池、关节位置、IMU、触摸或其余传感器的串口解码器。

因此本轮完成纯 codec，并未宣称硬件框图上的全部外设可用。现有 SI 控制端口、安全 HAL、
实时域保持原契约；不构造虚假的位置反馈、arm 或 safe-stop。

## Linux 实现与构建

见 [适配器使用说明](../adapters/actuator/patchx/README.md) 和
[头文件](../adapters/actuator/patchx/include/rtctrl/adapters/patchx/patchx_codec.hpp)。

新增 `rtctrl_patchx_codec` 叶子库和 `rtctrl_patchx_codec_test` CTest；由 `adapters/CMakeLists.txt`
接入，测试在适配器自己的子目录注册，不修改共享 `tests/CMakeLists.txt`。
业务核心无需依赖该库。编解码与设备路径、SoC、Android/厂商 SDK 完全分开。

260 字节载荷容量是 Linux 实现选择，不是 MCU 上限；固定缓存 538 字节。
Stream parser 支持碎片、合帧、长度/CRC/尾部验证和坏帧恢复；这属于本轮新增能力，
没有把 Android 的弱 ACK 检查移植成接收确认。暂以已确认发送格式作为离线解析输入。

无硬件 I/O、无发包命令行工具、无 MCU 升级操作、无部署或运行设备改变。

## 验证证据

专项测试先在空实现上失败，确认缺失编码/解析会被测试捕获，再实现并通过。
使用独立计算的字节向量，不仅比较编码器与其自身解码器：

```text
cmd 01: FF FF 00 01 01 90 B1 55 AA
FA raw 1234: FF FF 00 03 FA 12 34 02 09 55 AA
DF block 1, data 00 01 FE FF:
FF FF 00 09 DF 00 01 00 04 00 01 FE FF 1E BA 55 AA
```

向量依据源码公式推导，CRC 标准检查串 `123456789 → 4B37`；没有把它们称为实物抓包。
测试包含全部两片拆分位置、逐字节 IByteTransport loopback、合帧、损坏数据/CRC/帧尾、CRC 字节交换、
零长度/过长、两帧最大容量、载荷内分隔符、溢出原子拒绝、空指针、重连/字节间超时 reset。
看起来有效但未收齐的长度必须等待调用方超时；不能跳过它把合法载荷内部误识别成新帧。

本机 Ubuntu 22.04 / GCC 11.4.0，独立目录避免与内核任务共享构建状态：

| 验证 | 结果与范围 |
| --- | --- |
| `cmake -S . -B build/patchx-release -G Ninja -DCMAKE_BUILD_TYPE=Release`、完整 build、`ctest --test-dir build/patchx-release --output-on-failure` | 40/40 通过，57.75 秒 |
| `cmake -S . -B build/patchx-asan -G Ninja -DCMAKE_BUILD_TYPE=Debug -DRTCTRL_ENABLE_SANITIZERS=ON`、完整 build、对应 CTest | 40/40 通过，58.32 秒 |
| 最后仅格式化并补充嵌入分隔符向量、自引用编码和弱 ACK 拒绝测试后，重新构建并运行两套 `rtctrl_patchx_codec_test` | 两套均通过；生产逻辑未改变 |
| `python3 scripts/check-architecture.py` | 34 个模块公开头、49 个源码/头文件边界通过 |
| clang-format 18.1.8 对本次三个 C++ 文件 `--dry-run --Werror` | 通过 |
| 全仓 `format-check` | 失败于任务外既有文件，包括 `tests/test_main.cpp`；未全仓格式化或覆盖别人的修改 |
| 独立只读审查 | 未发现当前 codec 正确性/内存边界问题；明确调用方超时和接收语义未验证边界 |

完整 CTest 包含并行任务当时已接入的两个 Linux 工具测试；不代替该任务后续修改的复验。
原始本机日志位于上述两个构建目录 `Testing/Temporary/LastTest.log`（后续专项 CTest 会覆盖该文件），
完整运行摘要另保留在各构建目录的 `full-ctest.log`。这些不是板端、串口或机械验收结果。

## 后续硬件验收输入

取得原设备树和 MCU 资料后，确认实际 UART 接线/tty、串口抓包中的返回帧格式、ACK 状态与序号、
动作表/单位/限位、可靠停止/去使能、失联保护和启动无动作保证。
在这些契约明确前，此库可用于离线回放与诊断，不能自动接入 `IActuatorProtocol` 驱动真机。
