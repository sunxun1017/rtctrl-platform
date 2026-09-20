# PC 串口与 ARM64 QEMU 用户态验证

日期：2026-09-21。用户建议在没有原板时继续用 PC/QEMU 验证；本轮补上实际 Linux
tty 收发路径和 ARM64 二进制执行，不把交叉编译成功当作运行成功。
此前纯协议工作见 [PatchX 协议记录](verification-patchx-protocol-20260921.md)。

## 验证层次

| 方法 | 本轮能验证 | 不能由此证明 |
| --- | --- | --- |
| x86_64 原生 codec + ASan/UBSan | 字节格式、边界、错误处理、内存/未定义行为检查 | 原机串口及 MCU 行为 |
| POSIX PTY + 实际 `PosixSerialTransport` | Linux tty 打开、双向字节收发、空闲、碎片、坏 CRC 恢复、关闭/重开和挂断 | 波特率的电气时序、RS485 方向、DMA、引脚与电平 |
| AArch64 GCC + QEMU Linux user + ARM64 运行库 | 真正 AArch64 ELF 中的 codec/串口调用执行，以及 CTest emulator 接线 | ARM 内核启动、RK3568 外设/设备树、板端 SDK ABI、硬实时与性能 |

本次使用 QEMU **用户态**，没有运行 `qemu-system-aarch64` 或客体内核。
系统调用由模拟器转换并交给宿主 Linux；因此 QEMU 下 PTY 仍然来自 WSL 宿主内核。
模式说明依据 [QEMU 官方用户态文档](https://www.qemu.org/docs/master/user/main.html)。
没有模拟 RK3568、GD32、电机、摄像头、音频 codec、NPU 或传感器。

## PC 验证发现并修复的缺陷

新增 `rtctrl_patchx_pty_test` 使用 `posix_openpt/grantpt/unlockpt/ptsname` 创建隔离 PTY，
只能打开它生成的 slave 路径；没有外部设备参数，不会向实物发送动作。
测试链接真实 `rtctrl_transport_serial`，不是 loopback 替身。

修改前测试在第一轮空闲读取失败：

```text
FAIL: idle open tty is WouldBlock, not a disconnected device
```

原适配器设置 `VMIN=0, VTIME=0`，此时空闲 `read()` 可以返回 0；`map_result()` 把 0
解释为 `Closed`，导致正常连接被误认为断开。
修复只把 Linux tty 的 `VMIN` 改为 1，保留 `O_NONBLOCK` 和 `VTIME=0`。
本机内核空闲返回 `EAGAIN → WouldBlock`，真实 PTY 挂断仍为 `Closed/Error`。
没有把所有零字节读取简单改为 `WouldBlock`，因此没有掩盖真正 EOF。

该解释与 [Linux termios 手册](https://man7.org/linux/man-pages/man3/termios.3.html)
的非规范模式说明一致；POSIX 不保证所有系统同样处理 `O_NONBLOCK` 与 VMIN，本适配器
在 CMake 中本就限定 Linux，不能由此次结果外推到其他操作系统。

测试还验证：打开不主动发包、独立字节向量的完整 TX、逐字节 RX、两个连续帧中损坏 CRC
的过滤与恢复、读取排空后保持空闲、显式关闭撤销两个方向 I/O、重开并清理 parser 后无旧帧、
关闭 master 导致真实挂断。PTY 创建失败是测试失败，没有静默跳过；CTest 总超时 10 秒。
注入的接收数据仅是测试夹具，仍未确认 MCU 实际返回帧/ACK/运动完成语义。

## 可复现环境与命令

宿主：Ubuntu 22.04 / x86_64 WSL2，Linux `6.18.33.2-microsoft-standard-WSL2`，
GCC 与 AArch64 GCC 11.4.0，CMake 3.22.1。
QEMU 6.2.0，Ubuntu 包版本 `1:6.2+dfsg-2ubuntu6.31`。
从配置的官方 Ubuntu 软件源下载 `qemu-user-static`，仅解包到忽略目录 `.deps/qemu-user/root`，
未 sudo 安装、未注册 binfmt、未修改系统启动或连接设备。

所用 amd64 deb SHA256：
`2d22939f98f2ee8b84c5cc53b01082a4a937cfc7b4a8aa432788b9eaf4a14a41`。
模拟器本身是静态 x86_64 ELF，被测程序是动态 AArch64 ELF。
`-L /usr/aarch64-linux-gnu` 指向 Ubuntu ARM64 运行库，不是原板 BSP rootfs。

在仓库根执行（也可以把模拟器路径替换为系统已安装的 `qemu-aarch64` 绝对路径）：

```sh
pc_qemu="$PWD/.deps/qemu-user/root/usr/bin/qemu-aarch64-static"
cmake -S . -B build/patchx-qemu-agent -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE=cmake/toolchains/linux-cross.cmake \
  -DCMAKE_SYSTEM_PROCESSOR=aarch64 \
  -DRTCTRL_TARGET_TRIPLE=aarch64-linux-gnu \
  -DRTCTRL_BUILD_TESTS=ON -DRTCTRL_ENABLE_SERIAL=ON \
  -DRTCTRL_ENABLE_FORMAT_TARGETS=OFF \
  "-DCMAKE_CROSSCOMPILING_EMULATOR=$pc_qemu;-L;/usr/aarch64-linux-gnu"
cmake --build build/patchx-qemu-agent --target \
  rtctrl_patchx_codec_test rtctrl_patchx_pty_test rtctrl_dynamixel_test -j4
aarch64-linux-gnu-readelf -h build/patchx-qemu-agent/rtctrl_patchx_pty_test
ctest --test-dir build/patchx-qemu-agent \
  -R '^rtctrl_(patchx_codec|patchx_pty|dynamixel)_test$' -V --output-on-failure
```

必须在 CTest 输出中看到实际 QEMU 命令，并确认测试数量与退出状态。
此目录只构建上述三项，不声称整个项目测试集已经交叉运行。

宿主仍使用独立 `build/patchx-release`、`build/patchx-asan` 全量构建和 CTest；
新 PTY 测试仅在 `RTCTRL_ENABLE_SERIAL=ON` 时注册，不给纯仿真产品引入串口依赖。
最终结果：

| 验证 | 结果 |
| --- | --- |
| 宿主 Release 完整 build + CTest | 41/41，57.18 秒 |
| 宿主 ASan/UBSan 完整 build + CTest | 41/41，57.53 秒 |
| ARM64/QEMU：codec、PTY、Dynamixel | 初轮 3/3，0.09 秒，无跳过；主 agent 最终复配、构建和整组三项复跑 3/3，0.10 秒 |
| `readelf -h` 与 CTest `-V` | 三个测试均为 AArch64 ELF，三个实际命令均带 QEMU 及指定 `-L` |
| QEMU `-strace` PTY | 实际打开 `/dev/ptmx` 和生成的 `/dev/pts/*`，执行 termios、收发和重开，退出 0 |
| 架构检查、`git diff --check` | 通过 |
| 新 PTY 测试 clang-format 18.1.8 | 通过；本轮全仓 `format-check` 仍失败于既有格式问题，原始输出在 `build/patchx-release/pc-format.log` |
| 独立只读审查 | 未发现此次 VMIN 修复的阻塞、安全或测试可靠性回归 |

0.09 秒只是本次测试运行耗时，不是板端性能或串口实时性指标。

本机原始证据在 `build/patchx-qemu-agent/` 的环境、构建、ELF 和 CTest 日志，以及
`build/patchx-{release,asan}/pc-ctest.log`。这些目录是忽略的本机产物，复现命令和边界保存在本文。
