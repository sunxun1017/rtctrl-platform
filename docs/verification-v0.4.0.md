# v0.4.0 验证记录

日期：2026-09-01  
事实输入：本人 `yidong/new_yidong_robot` 的 `sx_text` 分支，提交 `8e7ecc7`  
构建环境：Ubuntu 22.04 WSL2，G++ 11.4.0，CMake 3.22.1，Ninja 1.10.1

## 已通过

| 配置 | 结果 | 重点 |
|---|---|---|
| `release`，6 关节 | 构建成功，CTest 1/1 通过 | 64 字节 ControlLink V2、共享内存/策略/旧功能回归 |
| `humanoid23` | 构建成功，CTest 1/1 通过 | 23 关节全核心实例化，132 字节帧，三 master 拓扑 |
| `asan` | 构建成功，CTest 1/1 通过 | ASan/UBSan 无报告 |
| 安装与信号脚本 | 通过 | 新增 `rtctrl_ipc`、headers、CMake targets 均导出；SIGTERM 安全退出 |

新增测试覆盖：

- 共享内存 magic/version/size/joint-count 校验；
- POSIX owner 使用 `O_EXCL` 创建、独立 client 映射、owner 精确 unlink；
- 命令/反馈双向一致快照和 10,000 轮并发 generation 一致性；
- `SharedMemoryHal` 打开时强制失能、无反馈拒绝 arm、反馈种子后 arm、急停直切 enable；
- 23 个逻辑关节与 23 个物理 EtherCAT 槽位的一一映射及电机标定；
- hybrid impedance 的 position/velocity/effort/kp/kd 契约；
- base action + delta-action、clip、scale、logical remap、joint limit 和 NaN 拒绝。

一次 `humanoid23` 1 秒仿真得到 1005 个 I/O 样本和 202 个 control 样本，故障未锁存；这是 WSL 功能证据，不是目标板实时验收数据。

## 尚未通过／环境限制

GCC ThreadSanitizer 目标在 WSL2 中构建成功，但启动测试进程即由 TSan runtime 报错：

```text
FATAL: ThreadSanitizer: unexpected memory mapping
```

该错误发生在测试代码执行前，属于当前 WSL 地址空间映射兼容性问题。因此不能声明 TSan 通过。仓库保留 `tsan` preset，并在原生 Ubuntu GitHub CI 中运行；发布前仍需取得原生 Linux TSan 结果。

真实 EtherCAT、并联踝机构变换、RK3588 PREEMPT_RT、NearLink 模组与端到端 command→actuator 时延仍属于板端阶段，当前代码和简历不应表述为已完成真机验收。
