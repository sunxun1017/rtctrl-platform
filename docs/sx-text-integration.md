# `sx_text` 精华迁移说明

事实来源：`/home/sx/projects/yidong/new_yidong_robot`，分支 `sx_text`，审计时提交 `8e7ecc7`。本轮没有修改原仓库，也没有复制 ROS 节点、vendor SDK、模型文件或第三方二进制。

## 提炼结果

| `sx_text` 中的成熟设计 | 当前平台中的实现 | 改造点 |
|---|---|---|
| 23 关节 logical order 与三 EtherCAT master wiring | `profiles/yidong23_topology.hpp` | 路由与电机标定留在叶子 profile；编译期验证物理槽位、逻辑关节、协议均一一匹配 |
| L0 无 ROS 实时进程与 ros2_control HAL 的共享内存双环 | `ipc/shared_motor_abi.hpp`、`SharedMemoryHal` | ABI 增加 magic、region size、joint count、生成号、采样时间、命令截止时间；映射所有权与 HAL 分离 |
| configure 时不使能、activate 前用反馈位置种子、独立 enable 线 | runtime 启动先 `read()` 再 `arm()` | 无新鲜反馈或存在 L0 fault 时拒绝使能；emergency stop 先切 enable 再发布零增益保持帧 |
| `JointCommand(position, velocity, effort, kp, kd)` 混合阻抗契约 | `model::CommandFrame` 与共享内存命令 | safety 同时验证 effort、kp、kd；模拟 HAL 也遵循相同混合阻抗语义 |
| RL action clip、scale、default pose、logical remap | `PolicyActionMapper` | 改为固定容量、无异常、无动态分配；加入 base action + delta-action 残差及关节限位 |
| ROS QoS 统一配置、ROS 仅在上层 | 架构边界与后续 bridge 入口 | 本阶段不引入 ROS；未来 adapter 只能消费稳定快照和命令端口，DDS 不进入 1 kHz L0 热路径 |

## 有意没有机械迁移的部分

- `runtime_state_adapter` 中实时访问共享状态的 mutex 没有带入；周期数据通路保持单写单读、有界重试。
- ROS 2 lifecycle、publisher、executor 和 controller_manager 不进入核心库，只保留其安全生命周期语义。
- 并联踝 Eigen/Levenberg–Marquardt 求解器尚未移植。它需要把迭代上限、失败回退、奇异 Jacobian、最坏执行时间和真机标定单独验收后，才能作为 L0 mechanism adapter 合入。
- ONNX Runtime 不进入 `rtctrl_control`；目前只提供可测试的 action 边界。推理 session、线程池和模型加载属于非实时初始化与可选 backend。

## 可验证边界

默认 profile 和 23 关节 profile 都运行同一测试集。测试覆盖共享内存 ABI、一致快照、先反馈后使能、L0 enable 急停、拓扑映射、混合阻抗和 delta-action 映射；23 关节 ControlLink V2 集成演示应报告 `wire_bytes=132`。
