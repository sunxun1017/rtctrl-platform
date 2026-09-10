# v0.7 验证记录

日期：2026-09-10。环境：本机 Linux，主机编译器；未连接目标板相机。

| 配置 | 结果 |
| --- | --- |
| robot-vision | 14/14 通过 |
| control-sim，关闭四项原生控制适配器 | 6/6 通过 |
| vision-synthetic，关闭 V4L2 | 6/6 通过 |
| release | 8/8 通过 |
| humanoid23 | 8/8 通过 |
| Debug robot-vision，ASan + UBSan（build/decouple-asan） | 14/14 通过 |

上述 CTest 包含对应配置的安装包外部消费者验证和架构边界检查。
采集测试覆盖注入后端、描述符复制、失败清理、帧借用与 token 重映射、
V4L2 包装系统调用、颜色元数据转换，以及共用 CLI 的真实 synthetic 文件输出。

另外核对 compile_commands.json：control-sim 不含 mailbox、POSIX 共享内存映射、
原生串口、SocketCAN 源码；vision-synthetic 不含 V4L2 源码。
CMake 依赖闭包检查与递归 include 检查通过。

独立 C 工程验证：

```sh
cmake -S apps/camera_capture -B build/capture-generic -G Ninja \
  -DCMAKE_SYSTEM_NAME=Generic -DRTCTRL_ENABLE_V4L2=OFF
cmake --build build/capture-generic
./build/capture-generic/rtctrl_camera_synthetic
```

结果为 `frames=70 corrupt=0 dropped=0 status=ok`。这里仍使用主机编译器和 C 库，
证明采集核心及 synthetic 构建不需要 Linux 采集头文件或 C++，不代表完成 RTOS 移植。

本次修改的 19 个 C/C++ 文件通过 clang-format，git diff --check 通过。
全仓 format-check 仍因 58 个未修改文件的既有格式问题失败，未批量改写这些文件。

尚未验证真实相机流、目标板 SDK 构建和板端实时性；线程运行环境仍保留现有
C++/POSIX 依赖。接口迁移与限制见 [ADR-0006](adr/0006-injectable-capture-and-adapter-capabilities.md)。
