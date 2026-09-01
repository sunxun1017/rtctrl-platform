# Contributing

提交必须保持核心层与具体板卡、总线和中间件解耦。新能力优先以叶子适配器加入；若必须改变稳定端口，请先新增或更新 ADR。

```bash
cmake --preset release
cmake --build --preset release -j8
ctest --preset release
cmake --preset asan
cmake --build --preset asan -j8
ctest --preset asan
```

实时热路径不得使用动态分配、锁、文件日志、异常传播和无界阻塞。所有硬件实现必须证明 `open_safe()` 不会使执行器带能，`emergency_stop()` 可重复调用且保持安全。
