# 按影响面验证

先查 `CMakePresets.json`、根和模块 `CMakeLists.txt`、相关测试注册，确认 preset 存在且覆盖修改。
下列命令从仓库根目录执行；按任务选取，不要求每次全部运行。

| 影响面 | 配置、构建、测试 |
| --- | --- |
| 默认控制 | `cmake --preset release` → `cmake --build --preset release -j8` → `ctest --preset release` |
| 无硬件控制闭包 | 同上，preset 换为 `control-sim` |
| 无硬件采集 | 同上，preset 换为 `vision-synthetic` |
| 控制与视觉组合 | 同上，preset 换为 `robot-vision` |
| 23 关节 profile | 同上，preset 换为 `humanoid23` |
| 内存/未定义行为 | 同上，preset 换为 `asan` |
| 并发问题 | 对相关代码选择 `tsan`；核实运行环境支持 |
| C/C++ 格式 | 配置 release 后执行 `cmake --build --preset release --target format-check` |

资源受限时降低 `-j`。可先用 `ctest --preset <name> -N` 确认测试注册，避免零测试假成功。
符合 CONTRIBUTING 的代码提交验证需要 release、asan 和格式检查；额外产品测试按影响面补充。
不要全仓格式化覆盖用户其他修改。

模块/依赖边界变化运行 `python3 scripts/check-architecture.py`；公共接口或安装变化查阅
`scripts/verify-install-and-signal.sh`，第三方版本变化查阅 `scripts/check-third-party.sh`，
先确认脚本的操作范围和本次验证所需环境再执行。

交叉构建可用 `aarch64`、`riscv64` 或板卡 preset，先核实编译器、sysroot 和 SDK。
交叉配置关闭测试的 preset 不能当作运行验收；编译成功仅说明对应输入下的编译/链接结果。
不要因可选 SDK 缺失就向通用模块硬编码本机路径。

`.clangd` 使用 `build/robot-vision/compile_commands.json`；视觉 IDE 问题先核实此数据库及相关源文件是否被收录。
即使配置 robot-vision，也不保证尚未接入 CMake 的新增模块进入数据库。

板端结果须给出板卡/SoC、系统和驱动/SDK 版本、模型/输入、命令、观测结果；
WSL/模拟后端测试不能证明真机 DMA、NPU、摄像头或硬实时性能。
运行涉及真实执行器、设备配置或部署的命令前核实当前任务已有授权和设备对象；测试计划不自动授权带能运行。
遇到环境阻塞，明确失败位置和已完成的其他验证；不要顺带修复与任务无关的在研 CMake。
