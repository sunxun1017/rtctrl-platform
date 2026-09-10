# 已验证项目经验

## 2026-09-10：新增源码不代表构建已覆盖

- 适用条件：在研模块或适配器刚加入目录树，尚未完成产品装配。
- 证据（2026-09-11 更新）：RKNN 已通过 `RTCTRL_ENABLE_RKNN` 接入，`cmake --build --preset robot-vision --target rtctrl_inference_rknn` 成功；独立 SDK 替身测试及其 ASan/UBSan 通过。通用 `modules/inference` 已实现张量描述、大小计算和 Backend 接口，RKNN 通过该接口适配；release/asan 各 12 项、robot-vision 18 项测试通过，包括安装消费和 include-boundaries。
- 结论：对 RKNN 的验证必须先证明 backend 进入实际 target/编译命令；现有 release 或 robot-vision 测试通过不能单独证明它已编译。
- 失效条件：通用模块与真实 SDK/板端验证完成后更新状态；静态库和替身测试不代表已链接 runtime 或完成 NPU 实测。

新增经验沿用日期、适用条件、证据、结论、失效条件。仅保留会改变后续开发决策的信息。

## 2026-09-11：RKNN 普通输入与 native 内存是两种契约

- 适用条件：为 RKNN 实现图像预处理或 DMA-BUF 接入。
- 证据：本地 Toolkit2 User Guide 英文版第 135、158–159 页说明普通 API 输入执行配置的 mean/std；第 69–72 页要求 native 内存匹配 stride/type，RKNNRT API 英文版第 38 页描述缓存同步。
- 结论：普通 `pass_through=0` 的 raw RGB Float32 不能再手工重复模型转换配置中的归一化。native IO 按 `size_with_stride` 分配并保留完整 SDK 属性，不能直接复用稠密 Float32 描述。拥有 DMA fd 或通过宿主替身测试不证明端到端零拷贝。
- 失效条件：SDK 版本、模型预处理或 IO 路径变化时重新核对。代码说明见 `adapters/inference/rknn/readme.md`。
