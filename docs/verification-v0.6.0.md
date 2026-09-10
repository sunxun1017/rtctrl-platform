# v0.6 架构重构验证记录

日期：2026-09-10。环境：当前 Linux 开发主机，GNU C/C++ 11.4.0。
本记录对应工作区架构变更，不代表目标板或生产视觉产品验收。

## 已通过

| 构建/检查 | 结果 |
| --- | --- |
| release（6 关节） | 构建成功，8/8 CTest 通过 |
| humanoid23 | 构建成功，8/8 CTest 通过 |
| control-sim | 构建成功，8/8 CTest 通过 |
| vision-node | 构建成功，4/4 CTest 通过 |
| robot-vision | 构建成功，10/10 CTest 通过 |
| Debug + robot-vision + ASan/UBSan | 构建成功，10/10 CTest 通过，halt_on_error=1 |
| apps/camera_capture 独立 C 构建 | 成功，--help 正常 |
| 安装导出及 SIGTERM 安全退出 | verify-install-and-signal.sh 通过 |
| CMake 依赖门禁反向检查 | 临时项目让 runtime 依赖 forbidden_adapter，配置按预期失败 |
| 核心头文件依赖扫描 | 通过 |
| 本轮改动的 C/C++ 格式检查 | 18 个文件通过 |
| git diff --check | 通过 |

每个产品的 package-consumer 测试执行实际安装，再由独立下游 CMake 项目
find_package(rtctrl 0.6) 并链接。视觉库以 C 消费者链接，不依赖控制库。

新增架构测试覆盖优先级与来源序列重映射、不刷新缓存期限、重放/NaN 拒绝、背压重试、
视觉 Active/会话错误/超时与不可自动恢复、重复启动、调度门控失败、无目标不武装、
首次反馈驱动控制命令、半双工 arm 后先读再写、快照读取与解除武装后停止输出。

相机使用包装系统调用的假驱动测试，覆盖部分 mmap 失败、元数据长度错误、借用 token、
重复归还、QBUF 失败以及 STREAMOFF 失败时继续清理。
厂商准备流程使用隔离 fixture 验证原输入不变、补丁顺序、输入变动影响 hash、错误基线失败。

## 未通过/未完成的验证

- **TSan 执行受当前环境限制。** 构建成功，但 rtctrl_tests 与 rtctrl_architecture_test
  均在测试执行前报 `FATAL: ThreadSanitizer: unexpected memory mapping`。
  同一编译器构建的空 `int main() { return 0; }` TSan 程序也以相同错误退出 66。
  因此不能宣称已经通过数据竞争检测；未为绕过它修改系统设置或禁用检测。
- **全仓 format-check 仍失败。** 报错来自 59 个本轮未改动文件；本轮改动文件无报错。
  用 HEAD 版本的 mailbox UAPI 头复核也存在相同格式错误。本轮未批量格式化这些文件。
- **没有板端验证。** 未验证真实相机采集、长期运行、ISP/NPU 负载与控制时延；
  SocketCAN 的现有测试结果也不替代真实 CAN 总线验收。
- **没有实际 SDK 编译。** RKAIQ 准备流程通过 fixture 回归，但未在本轮重新构建厂商库或 server。
- **生产视觉能力不属于已完成实现。** 当前具备采集库、语义契约、互锁与模拟回放；
  RKNN 推理、完整 visiond、跨进程观测编解码/时钟转换及自动恢复仍按产品需求实现。

## 重现入口

```sh
cmake --preset robot-vision
cmake --build --preset robot-vision -j8
ctest --preset robot-vision
./build/robot-vision/rtctrl_vision_control_replay tests/fixtures/vision-events.txt --arm

cmake -S . -B build/architecture-asan -G Ninja \
  -DCMAKE_BUILD_TYPE=Debug -DRTCTRL_PRODUCT=robot-vision -DRTCTRL_ENABLE_SANITIZERS=ON
cmake --build build/architecture-asan -j8
ASAN_OPTIONS=halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 \
  ctest --test-dir build/architecture-asan --output-on-failure
```

架构说明见 architecture.md；C++ 接口迁移见 ADR-0005。mailbox ioctl/UAPI、设备树 binding、
ControlLink 线协议保持原 ABI。用户已有的 .gitmodules 和 RKNN 子模块工作区改动予以保留。
