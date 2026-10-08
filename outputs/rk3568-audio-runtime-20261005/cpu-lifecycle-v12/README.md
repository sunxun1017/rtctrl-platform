# CPU lifecycle v12：格式配置完成后的 PM 交接

本目录只包含离线候选、真实函数抽取模型、私有 AArch64 Kbuild 对象及冻结证据。没有构建新的完整 Image，没有操作板卡，也不授予 START、刷写或物理声音验收。

## 真实契约与问题

实际 `aiot-3568pq-audio-v2` CPU 为已冻结 v11，SHA `87779ff23367aaaac07e8c980ee98dbdf59a93318e3a2782c52bdb011eb4417c`。`soc_init_pcm_runtime` → `snd_soc_runtime_set_dai_fmt` → CPU `set_fmt` 在成功绑定声卡时调用。CPU probe 自身只持有 HCLK，不持有 MCLK；首次格式配置通过 `pm_runtime_get_sync` 恢复，STOP 的两次真实读回由恢复路径完成。

旧 `set_fmt` 完成四次寄存器写入后，在 `configuring=true` 时调用 `pm_runtime_put`，随后才清除 `configuring`。真实 `pm_runtime_put` 是 `__pm_runtime_idle(RPM_GET_PUT | RPM_ASYNC)`；异步工作可能在函数清 flag 前进入 checked suspend，从而得到 `-EBUSY`。真实 PM core 将设备留在 ACTIVE、清除该临时 core error；没有 use_autosuspend 时 expiration=0，不自动重排这次 idle。`power/control=auto`、usage=0 因而不保证最终 suspended。

旧 Image v1 绑定 codec 后已 STOP1/reads2/IRQ drained/MCLK0/suspended；该记录中没有 PCM 参数配置或释放操作。新 Image v2 同阶段 STOP1/reads2/IRQ live/MCLK1/active，与上述允许发生的时序一致，但没有捕获过去的实际 worker 调度，所以这里不把模型当板端调度追踪。

正常 PCM close 由 ASoC 在 DAI shutdown、simple shutdown 的缓存复位之后执行 component runtime PM put；CPU shutdown 本身不释放 PM/MCLK。v11 的零频率缓存复位和下一次正频率 hw_params 行为保持逐字节不变。

## 窄修正

仅增加一个私有 `bool format_pm_release`，修改 `i2s_checked_set_fmt` 和 `i2s_checked_runtime_suspend`：

- `set_fmt` 在所有格式 MMIO 结束后，锁内发布第一条错误；只有无错误的末阶段才置 `format_pm_release`。
- `configuring` 保持到原来的 out。其他配置、START、startup 和拆除继续沿用原先的拒绝或 failstop 契约。
- checked suspend 只允许该成功末阶段与 `configuring` 共存；仍拒绝 sticky、started、未证明 STOP。IRQ gate、真实 synchronize_irq、cache-only、两份 CPU MCLK 释放及 HCLK保留的操作均逐字节不变。
- 所有已进入配置的出口都在同一锁内清除末阶段和 configuring。PM get 失败仍用 put_noidle 平衡；PM put 负 errno 仍报告并锁存；不会清除 sticky。

PM API 不放入 I2S 自旋锁。异步 callback 可以在格式函数返回后才完成；此时 `power_transition` 继续阻断其他命令。格式返回 0 本身不是 idle 验收，仍需原严格 collector 观察真实稳定 STOP、IRQ drain 和引用矩阵。

拆除若与尚在途的格式函数相遇，仍按原 configuring 条件 failstop。格式函数退出后，拆除通过原 `pm_runtime_disable` 排空回调，再执行串行 STOP/clock 清理；不会在回调尚使用 clock handles 时销毁 devres。

## 验证范围

`format-pm-red-v11-r2` 逐字节抽取旧生产 set_fmt、checked suspend、gate、startup、component START 和 quiesce。在 put 内强制 worker 的红例，三个环境均为 4/5，唯一失败为需要最终 idle 的断言；相同旧函数在 flag 清后执行 worker 则通过。这证明该源码时序可复现，不表示实际 PM core 全部代码已运行。

`format-pm-green-v12-r4` 三环境各 90/90：四个 regmap 失败点、PM get/put errno、first sticky、普通 configuring/started/STOP 门槛、早期与末阶段并发 gate/startup/START/teardown、所有退出 flag、实际 IRQ drain/MCLK 操作调用，以及 pthread callback 横跨格式函数 out 的确定时序。另覆盖 terminal 发布后、suspend 取锁前的新 sticky，以及 get_sync 返回正值的合法语义。模型中的 PM/CCF/regmap/pinctrl/IRQ 是 API 替身；failstop 的 longjmp 仅观察生产拒绝分支，真实 panic 不会返回。拆除的 pm_disable 模型通过 join 实现真实 core 的排空契约，不冒称整个内核并发测试。

`shutdown-green-v12` 和 `params-regression-v12` 复用 v11 完整检查及真实 simple/DAI/codec 函数，三环境分别 48/48、140/140。`verification-tools` 记录了仅 fixture/output 路径变化与 runner 快照补齐；原检查字节不变。

三个环境为 host、ASan+UBSan、静态 AArch64 QEMU。`kbuild-object-v2` 对完整生产候选执行实际 AArch64 Kbuild，使用真实 Image v2 的配置、headers、symvers 和编译器；原 ABI 的 2110 个普通文件及 10 个保护输入都按 SHA 读回保持。这里只编译对象，未链接完整内核。

`format-pm-red-v11` 是第一次模型编译缺少真实常量/helper 的失败记录，不能作为红例证据；`format-pm-green-v12-r2` 是扩展模型累计 failstop 断言错误的失败记录，生产候选未因它变化。两目录保留以便审查。`format-pm-green-v12` 是早期 67/67、r3 是 87/87 模型，最终以 r4 为准。

## 重现与冻结

顺序执行 `prepare-inputs.py`、`test-format-pm.py --red-v11 --output format-pm-red-v11-r2`、`create-candidate.py`、新行为模型、`prepare-verification-tools.py`、两套旧行为回归、`build-object.py`、`seal.py`。脚本只写新目录，已有输出不会覆盖。精确命令和二进制/日志 SHA 位于各 result.json。已有 r4 输出对应增强后的模型，重跑需选择新的输出名。

`seal.py` 核对新候选仅限两函数和一个字段、真实 delta/完整补丁重放、模型执行产物、Kbuild ELF、所有冻结输入、既有 v11 的 2249 文件及其库存/SUM、原源/ABI/包保护输入。`frozen-output-manifest.json` 与 `SHA256SUMS` 封存本目录普通文件；独立审查与新 Image 的自然初始 idle 上板对照由主控完成。
