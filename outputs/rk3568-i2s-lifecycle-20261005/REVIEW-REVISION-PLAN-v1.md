# v8 审查后的分块修订

保持 driver-source-v8、sealed-v1 及其全部证据输入字节不变。只在此目录新增版本，不触碰原 kernel、硬件、Image、公共 patch 或根 docs。

1. 先把独立审查输入保存到 review-input-v1，验证 source SHA 和 ASan UAF、registered loopback 输出。
2. 新测试必须摘录整段真实 probe，使用记录 devres 反序/真实 malloc/free consumer handles 的边界；模拟 OF、component/PCM/sysfs API，但所有获取、注册、失败分支与跳转来自实际 probe C。先跑 v8 红例。
3. 把 checked clock action 注册移到 HCLK/TX/RX 三个 devm_clk_get 均成功之后、任何 checked clock enable 之前；legacy profile 保留原行为。checked component 使用零 legacy controls 的实际 descriptor，保留 readonly 生命周期接口。
4. ready 发布前外部 startup/prepare/START 拒绝；PM transition 进入外部 admission。同锁撤销 ready/IRQ 再 process synchronize_irq。完整 probe late failure 需在 devres 前完成真实 PM/STOP 清理，保注册首错误；无法停止的 void/退出仍 fail-stop。
5. 执行 inactive set_fmt ticket→runtimeResume→STOP 和 remove shutting_down→runtimeResume→forced STOP 的真实函数嵌套；API 模型明确 PM 核心序列化和异步 put 语义，不在本地模型声称全内核 PM 核心已验证。逐点注入 get/enable/cache/register 错误，回归引用、gate/ready、IRQ 屏障与失败阻止释放。
6. 新版重跑既有五套、完整 probe 新套、实际 DT、实际 Kbuild object；私有 patch replay、原 kernel/ABI和 v8/sealed-v1字节核验后生成新的 sealed-v2。C3/生产 Image/上板独立后续，START 仍禁止。
