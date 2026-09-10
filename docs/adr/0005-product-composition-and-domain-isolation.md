# ADR-0005：产品装配、运行域隔离与资源所有权

状态：Accepted，2026-09-10。适用于 v0.6。
补充 ADR-0001/0003/0004；替代旧架构中 runtime 拥有 source 线程的安排。

## 问题

控制代码通过接口注入，但 runtime target 同时依赖具体适配器库；命令源线程的
生命周期与实时引擎耦合；bridge 端口未接通；相机仅有全局状态采集程序；
RKAIQ 编译输入可能是旧工作副本，而 manifest 记录的是另一份 SDK。

## 决策

1. 单仓库模块化，端口与适配器，静态链接、显式构造，不引入全局服务注册。
2. 产品 preset 选择功能集合，platform profile 选择硬件和 SDK，两个维度正交。
3. runtime 仅持有 I/O、控制线程。普通应用循环拥有命令源和 TargetArbiter。
4. 唯一目标生产者、唯一快照消费者；每来源独立序列与租约，来源切换不刷新租约。
5. HAL 全生命周期由 I/O 所有者执行。双门控和首条有效命令后才武装。
   disarm 对本实例不可撤销，故障与武装重置通过重建实例完成。
6. 视觉借用帧由句柄/token 约束；失败清理在库内部完成，重连在应用层。
7. 视觉事件经可选互锁只能收回控制权限。跨进程 wire adapter 后续需独立实现。
8. 实际源副本、patch series、命令与产物构成第三方构建证据。
9. 构建闭包、头文件边界、下游安装链接与故障回放进入自动测试。

## 已选择的设计方式

| 问题 | 选择 | 约束 |
| --- | --- | --- |
| 模块依赖 | 端口与适配器 + 构造注入 | 具体实现仅由组合根选择 |
| 算法替换 | Strategy（IController） | 无平台、设备、来源信息 |
| 电机接入 | 协议与链路组合 | 继续使用现有能力校验 |
| 实时数据交换 | 有界 SPSC | 固定生产者/消费者、无阻塞 |
| 多来源输入 | 单所有者优先级仲裁 | 不重写数据生成时间 |
| 生命周期 | 显式状态 + 不可撤销 disarm + 故障锁存 | 不自动重启武装 |
| 相机资源 | 不透明 C handle + borrowed frame | 使用完再归还，无全局状态 |
| 厂商集成 | 新快照 + 有序补丁 + manifest | 不复用未验证实验副本 |

## 接口迁移

v0.6 调整 C++ 源码接口，UAPI 和线协议不变。package 使用 SameMinorVersion，
不把 0.6 宣称为满足 0.5 请求的兼容版本。

```cpp
// 原来：RealtimeEngine(config, platform, hal, controller, source, safety)
rtctrl::runtime::RealtimeEngine engine(config, platform, hal, controller, safety);
rtctrl::bridge::TargetArbiter targets(engine, config.target_validity_ns);
if (!targets.bind(0, source, 0) || !engine.start()) { /* handle startup failure */ }
// 非实时应用循环：
targets.poll(platform.now_ns());
// 停止：
engine.request_stop();
engine.join();
```

移除 RuntimeConfig::source_period_ns；来源轮询周期由应用设置（demo 为 20 ms）。
保留 transport::ICommandSource alias；新代码使用 bridge::ICommandSource。
旧聚合 CMake target 保留，原静态归档文件名不作为 v0.6 兼容契约。
IStateSnapshot 只允许单读取者，并要求检查时间戳。ILifecycleControl 移除未实现的
request_arm，使用启动授权与不可撤销 request_disarm，不提供不完整的动态恢复接口。

相机 CLI 不再强制 2112×1568 NV12；应先通过板级工具设置格式，程序保留协商结果。
可选 OUTPUT_FILE 现在实际保存首帧，并生成 OUTPUT_FILE.json。

RKAIQ 脚本参数 --sdk-root 保留；产物位置改为每次独立 run 目录，终端输出 manifest
路径。旧 work/rkaiq-debug-* 实验副本不被删除或覆盖。--prepare-only 用于只验证源码
准备与补丁；现有 server regression 仍需 SDK。

## 验收

```sh
cmake --preset release && cmake --build --preset release -j8 && ctest --preset release
cmake --preset humanoid23 && cmake --build --preset humanoid23 -j8 && ctest --preset humanoid23
cmake --preset vision-node && cmake --build --preset vision-node -j8 && ctest --preset vision-node
cmake --preset robot-vision && cmake --build --preset robot-vision -j8 && ctest --preset robot-vision
python3 scripts/check-architecture.py
./scripts/verify-install-and-signal.sh
```

新增测试覆盖仲裁、过期、回放、背压、重复启动、调度门控失败、首次反馈/半双工武装握手、延迟武装、终止武装、快照、
视觉失效、相机部分初始化、错误元数据、重复归还、STREAMOFF/QBUF 失败、
厂商副本输入变化和补丁错误基线、安装后的独立消费者链接。

主机测试不能证明板端摄像头长稳、NPU 正确性或实时调度时延；这些按既有板端流程验收。
