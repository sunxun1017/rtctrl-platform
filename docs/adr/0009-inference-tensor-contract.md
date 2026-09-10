# ADR-0009：推理张量契约与同步后端

## 背景

inference 草稿仍保留 camera 回调和不存在的 inference.h；RKNN 自行定义的
TensorSpec 令上层必须包含适配器才能描述输入。项目需要通用且可测试的推理输入契约。

## 决策

- `modules/inference` 拥有 C++17 TensorType、TensorLayout、TensorSpec、MutableTensorView
  及 Backend 虚接口；不包含 SDK 或视觉/音频语义。已有草稿是 `.hpp`，采用项目允许的 C++ 端口。
- `rtctrl_inference_api` 提供头文件；`rtctrl_inference` 实现带溢出检查的张量大小计算，
  通过已有模块机制安装导出。模块可用于所有产品，是否装配具体后端由应用决定。
- Backend 是同步、单线程拥有的接口，先逐个准备，后无参 run。模型创建是具体适配器职责，
  不将文件路径强加给其他后端。借用输入内存后需显式 commit，源数据复制接口返回后可释放源。
- RKNN 实现此接口，保留原嵌套类型名字作为通用类型别名，保持现有调用方式可用；
  其 SDK 句柄和 Float32 输入转换策略仍归适配器，通用模块不强制所有后端使用 Float32。
- 输出能力通过 `output_count/output_spec/output_data` 查询，默认零输出保持输入型替身兼容。
  当前输出是稠密 Float32 向量，数据借用仅到下一次 run 尝试或销毁；执行前和失败后禁止读取。
  RKNN 在同步 run 中获取、复制并释放 SDK 输出；run 成功包含输出获取成功。
  不定义异步调度，不把此接口作为稳定二进制插件 ABI。
- 静态人脸识别应用拥有检测解码、对齐、特征匹配和人员库；这些视觉语义不进入 inference 模块。
  普通 RKNN 输入由 SDK 执行转换时配置的 mean/std；应用传原始 RGB Float32，避免重复归一化。

## 验证

模块测试用无 SDK 的替身检查多输入接口和张量大小边界；RKNN 替身测试通过 Backend 引用调用
真实适配器。安装消费检查验证公共头的独立可用性，架构检查防止模块反向依赖适配器。
板端库链接、格式转换、精度和时延不由宿主机测试证明。
