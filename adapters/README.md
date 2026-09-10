# 具体适配器

适配器实现模块拥有的端口，由 apps 显式选择。每个适配器的 include 只通过它自身
的 CMake target 提供给装配代码与测试；src 中保存实际系统调用和实现细节。
适配器静态链接到应用，默认不作为模块 package 的公共 API 安装导出。

| 目录 | 职责 | 目标 |
| --- | --- | --- |
| realtime/posix | 单调时钟、等待、Linux 线程配置、内存锁定 | rtctrl_platform_posix |
| transport/serial | 串口及 RS485 系统资源 | rtctrl_transport_serial |
| transport/socketcan | Linux CAN/CAN-FD | rtctrl_transport_can |
| transport/loopback | 无设备字节传输和命令来源 | rtctrl_source_loopback |
| ipc/posix_shm | 创建/映射/销毁 POSIX 共享内存 | rtctrl_ipc_posix |
| actuator/mailbox | mailbox UAPI 编解码和 ioctl HAL | rtctrl_mailbox_codec、rtctrl_hal_mailbox |
| actuator/simulated | 模拟执行器和故障注入 | rtctrl_hal_sim |
| actuator/shared_memory | 将注入的共享 region 适配为执行器 | rtctrl_hal_shm |
| actuator/dynamixel | 将通用执行器命令适配为 Dynamixel 协议 | rtctrl_actuator_dynamixel |
| ethercat/igh | IgH master/domain/PDO/DC 生命周期 | rtctrl_igh_ethercat |
| capture/v4l2 | Linux 多平面 MMAP 相机采集 | rtctrl_vision_v4l2 |
| capture/synthetic | 确定性的无硬件 GRAY8 图像源 | rtctrl_capture_synthetic |

依赖方向为适配器 → 模块。适配器间协作也应显式声明，例如 mailbox HAL 依赖同一
适配器目录的 UAPI codec。通用协议编解码和半双工算法仍在 modules 中，不做重复封装。

realtime/posix 当前包含 Linux 线程扩展，不宣称支持所有 POSIX 操作系统。
simulation 关闭设备适配器后仍使用宿主线程环境，并不等于 RTOS 构建。
