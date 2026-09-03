# Contributing

提交必须保持核心层与具体板卡、总线和中间件解耦。新能力优先以叶子适配器加入；若必须改变稳定端口，请先新增或更新 ADR。

## 代码格式

C/C++ 和 CMake 代码统一使用 4 个空格缩进，禁止使用制表符。C/C++ 的完整规则以仓库根目录的
`.clang-format` 为准，通用编辑器行为以 `.editorconfig` 为准。提交前应执行：

```bash
cmake --preset release
cmake --build --preset release --target format-check
```

需要自动修正 C/C++ 格式时执行：

```bash
cmake --build --preset release --target format
```

上述目标需要 clang-format 14 或更高版本。

## 构建与测试

```bash
cmake --preset release
cmake --build --preset release -j8
ctest --preset release
cmake --preset asan
cmake --build --preset asan -j8
ctest --preset asan
```

实时热路径不得使用动态分配、锁、文件日志、异常传播和无界阻塞。所有硬件实现必须证明 `open_safe()` 不会使执行器带能，`emergency_stop()` 可重复调用且保持安全。
