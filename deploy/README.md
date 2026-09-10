# 产品部署边界

产品选择使用 RTCTRL_PRODUCT，板卡选择使用 platforms 下的 profile；不在产品代码
硬编码板卡或设备节点。架构与实现状态以 docs/architecture.md 为准。

| 产品 | 入口 | 所有权 |
| --- | --- | --- |
| control-sim | rtctrl_demo | 主线程管理来源/仲裁；I/O 线程独占模拟 HAL |
| vision-node | rtctrl_camera_capture DEVICE [OUTPUT_FILE] | 单句柄所有者管理 V4L2；ISP 由现有板级服务准备 |
| robot-vision | 上述入口及 rtctrl_vision_control_replay EVENTS [--arm] | 回放语义互锁连接模拟控制；尚非生产视觉控制服务 |

安装：cmake --install build/<product> --prefix <staging-directory>。
核心 CMake package 与选中产物一起安装；相机也可在 apps/camera_capture 独立构建。

现有 kernel/systemd 模板继续用于对应硬件部署；本轮不安装或启动任何宿主机服务。
启动默认未武装、不得给重启策略暗中添加 --arm。真实部署的设备权限、CPU/IRQ、
调度门控、独立 watchdog、模型/IQ 兼容版本应由对应板卡验收记录说明。

未来生产 visiond 应在非实时域拥有采集/预处理/推理工作线程与有界缓冲池，另设
控制进程。3A 服务是否独立由 SDK 生命周期决定。进程间只能传经版本检查并完成
本地时钟转换的语义消息；不得直接传 Observation 的内存布局或借用帧指针。
当前未部署该服务，也未实现其网络/IPC adapter。

config/*.toml 目前是意图配置文档，不会自动影响程序。实际运行参数来自 CLI 和
启动前构造的 RuntimeConfig，避免配置文件与执行行为产生假关联。
