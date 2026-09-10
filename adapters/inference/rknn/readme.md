# rknn

你返回的输入缓冲

你要知道返回的长度才行

```c
struct MutableBufferView {
    void* data;
    std::size_t size_bytes;
};

// index 用来选择模型的第几个输入。
MutableBufferView get_input_buffer(std::size_t index);
```

你哪怕输入一个长度也不行，应该是返回一个长度比较好，这样是有由他决定，你是其他的 data 类型都不合适，就是这个 void *，返回地址，比较好

## 当前输入准备契约

`prepare_input_data(data, size_bytes, index)` 逐个复制输入到 backend 的私有缓冲区。
它不调用 RKNN，不做 resize、重采样、归一化或类型转换。调用者提供的是准备好的张量。
本版固定对外使用 IEEE Float32、紧密连续布局；`input_spec(index)` 描述这个对外表示，
不是模型的原生量化类型。布局沿用查询的 NCHW/NHWC/Undefined，Undefined 不代表 NHWC。
只接受原生 Float32/Float16/UInt8/Int8 的模型输入，其他类型显式拒绝，避免整数 token 等语义被浮点化。
不提供动态 shape 切换和 stride/零拷贝输入；模型预处理语义和板端转换正确性仍需验证。

```cpp
rknn::RknnBackend backend(model_path); // 失败抛异常，在非实时初始化阶段创建
// a、b 都是符合各自 spec.shape/layout 的 float 数组。
bool a_ready = backend.prepare_input_data(a.data(), a.size() * sizeof(float), 0);
bool b_ready = backend.prepare_input_data(b.data(), b.size() * sizeof(float), 1);
if (a_ready && b_ready) {
    bool submitted = backend.run();
    // submitted 包含执行、获取和复制所有输出成功。
    if (submitted) { const auto& values = backend.output_data(0); /* 使用 values */ }
}
```

`run()` 要求全部输入 ready，然后将完整描述数组一次传给 `rknn_inputs_set`，成功后执行
`rknn_run`。SDK 按 `type=FLOAT32, pass_through=0` 处理输入转换。每次提交尝试后清空
ready，即使 SDK 失败也须重新准备所有输入；缺少输入时不调用 SDK，也不清空已有输入。
无效 index 返回 false；有效 index 的空指针/错误大小会清除该输入 ready，避免使用旧数据。
size 参数不能验证源内存的实际长度或类型，调用者必须保证可读范围和 Float32 表示。

也可 `get_input_buffer(index)` 直接写入 `float` 元素，然后 `commit_input(index)`。
获取视图会清除该输入 ready；commit 是调用者对已完整填充的声明，不能自动检测漏写。
视图借用到 backend 销毁为止，不允许在 run 期间或其他线程修改，不允许释放。
输入描述在初始化后缓存，查询越界抛 `std::out_of_range`。backend 不可复制或移动。

`output_spec(index)` 返回输出形状，`output_data(index)` 返回 backend 拥有的稠密 Float32 向量。
每次 run 尝试均使旧输出无效；仅成功后可读。SDK 输出在复制后通过 `rknn_outputs_release`
释放，包括复制失败路径。测试使用 SDK 替身，不证明 NPU、量化转换或模型精度。

可选应用通过 `runtime_loader.cpp` 动态加载板端 `librknnrt.so`；可用环境变量
`RTCTRL_RKNN_RUNTIME` 指定库路径。普通库消费者也可以直接链接匹配的 SDK runtime。

## 原生内存基础

`native_memory.hpp` 提供独立 `NativeMemory` RAII 类，支持 RKNN 自有内存和 DMA-BUF fd 导入。
调用者必须查询当前 context 的 native attr；分配按 `size_with_stride`，不能用逻辑字节数代替。
其类型、布局、量化和 stride 全部保留 SDK 描述，不套用普通 Backend 的 Float32 契约。
`bind()` 调用 `rknn_set_io_mem`，`sync()` 显式执行缓存同步；二者返回 SDK 错误码供调用者检查。
context、导入 fd 和映射必须比该对象活得更久；对象销毁后禁止继续使用原绑定执行。

这只是原生内存管理基础，目前静态图片 CLI 仍使用普通复制接口。摄像头 DMA-BUF 导出、
RGA 转换、原生输出解包和实际缓存一致性尚未接通或上板验证，不能称为端到端零拷贝。

普通输入 mean/std 证据：本地 `third_party/rknn-toolkit/doc` 的 RKNN Toolkit2 User Guide
英文版第 135、158–159 页。原生内存/stride 见第 69–72 页；mem_sync 见 RKNNRT API
英文版第 38 页。更换 SDK 版本后需重新核对。

宿主机契约测试（独立构建，不需要 RKNN runtime）：

```bash
cmake -S adapters/inference/rknn/tests -B build/rknn-contract
cmake --build build/rknn-contract
ctest --test-dir build/rknn-contract --output-on-failure
```

## 通用模块接入

张量类型和 `Backend` 接口现在归 `modules/inference`。`RknnBackend` 实现该接口，
原来的 `RknnBackend::TensorSpec` 等名字作为别名保留。上层可只包含
`rtctrl/inference/backend.hpp` 并接收 `rtctrl::inference::Backend&`；模型创建与 SDK 选择
由应用装配层处理。调用非内联 `TensorSpec::byte_size()` 必须链接 `rtctrl_inference`，
仅包含接口可链接 `rtctrl_inference_api`；RKNN target 已 PUBLIC 链接通用库。

```cpp
bool submit(rtctrl::inference::Backend& backend,
            const void* data, std::size_t bytes, std::size_t index) {
    return backend.prepare_input_data(data, bytes, index);
}
```

通用层支持 UInt8/Int8/Float32 描述，并不要求所有后端使用 Float32。
RKNN 当前的固定 Float32 提交策略仍是适配器自身的限制。
