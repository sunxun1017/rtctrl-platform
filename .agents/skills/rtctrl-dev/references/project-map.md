# 项目地图

下列路径相对仓库根目录。按任务读取，不批量加载全部文档或 third_party。

| 任务 | 优先入口 | 判断重点 |
| --- | --- | --- |
| 模块与公开接口 | `modules/README.md`、`docs/architecture.md`、ADR 0007/0008 | 端口/公开头归属模块；以导出 target 传播依赖 |
| 控制与安全 | `modules/runtime/`、`modules/control/`、`modules/safety/`、ADR 0003 | 实时热路径、租约、失效与安全输出 |
| 执行器与总线 | `adapters/actuator/`、`adapters/transport/`、`adapters/ethercat/`、ADR 0004 | 电机协议与物理链路分离；安全打开与幂等急停 |
| 采集 | `modules/capture/`、`adapters/capture/`、`apps/camera_capture/`、ADR 0006 | 可注入 C 后端、帧生命周期、像素格式转换 |
| 推理 | `modules/inference/`、`adapters/inference/rknn/`（若存在） | 检查真实接线；SDK 所有权、输入输出和失败释放 |
| 产品组合 | `products/README.md`、`apps/`、`docs/adr/0005-product-composition-and-domain-isolation.md` | 控制/视觉域隔离、依赖注入和目标闭包 |
| 板卡/BSP | `platforms/README.md`、`docs/rv1126b.md`、`docs/wsl-and-rk3588.md` | SoC、板卡、sysroot、运行时与驱动匹配 |
| 内核/UAPI | `kernel/README.md`、`include/uapi/`、`docs/language-and-kernel-boundary.md` | ABI、内核构建输入、用户态/内核职责 |
| SDK | `third_party/README.md`、`.gitmodules`、相关 SDK 头文件 | 以锁定版本为准；示例用于理解，不直接当平台接口 |

RKNN 核查先看本地 backend、匹配版本的 `rknn_api.h` 与示例；需要联网时查官方对应版本资料。
确认模型目标 SoC、张量布局/类型/量化、buffer 大小和生命周期、输出释放、context 销毁与并发约束。
这些是核查项，不意味着当前接口已经实现这些能力。

采集与异步推理衔接时，当前采集契约每个句柄最多借用一个帧，release 后指针失效。
不能将借用指针排队后归还 V4L2 buffer；异步消费者需要复制或明确的独立所有权与有界缓冲池。
具体契约与后续变更以 `docs/architecture.md` 和采集接口为准。

公共接口调整遵循 ADR 0008：通过模块 `*_api` target 传播头文件依赖，非内联实现链接实际库，
不新增全局 include 或聚合 target；模块不反向依赖适配器，runtime 不依赖 bridge。
