# RK3568 DMA / PL330 生命周期 C 阶段

2026-10-05，当前候选为 `driver-source-c3-v8`。本目录的 C1/C2/C3 及 CPU v10 软件合测与真实 Kbuild 对象编译已完成；完整独立功能审查、最终 Image、外置 codec 模块 ABI 与实机 AXI 停稳验证仍由主控继续。

当前 `published=false`、`deployable=false`、`board_tested=false`、`image_built=false`。没有写入公共 0011，没有连接板卡或执行 PCM START，也没有提交或推送。

冻结交接入口是 [C3-review-v2/receipt.json](C3-review-v2/receipt.json)，SHA256：
`97011370d4a66b385ab3855fa9cf2f2cf4c857728a1f969902f5e8dd9b10e975`。
收据列出 883 份冻结文件的完整 SHA，包括源码、补丁、manifest、原始输入、完整串重放、测试夹具与 ELF、编译/执行 argv、stdout/stderr、配置与十二份真实 `.o.cmd`。本目录旧版本和拒绝证据保留。

## 当前候选与修正

- `driver-source-c3-v7` 已将连续 descriptor block 定义和 failstop prototype 移到使用前。相对 v6 没有改函数体；v6 的 production-v8 声明错误日志保留。
- v8 完整 controller STOP proof 开始时撤销旧缓存，仅所有 channel 和 manager 成功后在 controller lock 内调用真实 `pl330_capture_stop_locked`。初始 probe 的真实 AMBA wrapper 退出且 PM usage=0 后，首次只读状态为 ready=1；部分 manager STOP 失败没有写入成功缓存、没有发布 reader/DMA/IRQ。
- 新 optional `device_check_open` 与 `dmaengine_check_open` 提供 cached readonly admission。PL330 在 controller lock 内读取 sticky errno 和关闭/休眠门槛，不做 MMIO、PM、STOP 或资源操作。DMA PCM open 在分配 prtd/token 前返回负 errno；缺少 callback 的 checked provider 返回 `-EOPNOTSUPP`，没有 checked callback 的旧 provider 维持原 open 契约。

v8 PL330 源 SHA256 为 `ac40d2e3c41116667f2ef147b1f644c9782d26cd8f1597628afa67bd50f93b16`；完整 C 增量补丁 SHA256 为 `c2f973b6f96620b1ac307e5fa5e0632f5430a12a7accbb54cc95088c772b519c`。

## 验证

host、ASan+UBSan（保留 leak 检查）、static AArch64 QEMU，每个环境八套共 183/183 通过。

| 冻结测试目录 | 每环境用例 |
| --- | ---: |
| pl330-c3-order2-tests-green-v2 | 67 |
| pl330-c3-hw-tests-green-v3 | 17 |
| pl330-debugfs-tests-green-v6 | 2 |
| dma-admission-tests-green-v6 | 9 |
| trigger-cpu-open-tests-green-v1 | 47 |
| dma-pcm-open-tests-green-v1 | 21 |
| core-lifecycle-tests-green-v4 | 6 |
| pl330-ready2-tests-green-v2 | 14 |

初始 ready 的新红例在 v7 三环境各 13/14，唯一失败是首次读到 ready=0、stop_proven=0、stop_reads=0。永久 KILL 超时→quarantine→close 后，同一 generic-held channel 的重新 open 原来返回 0；新 open 测试在 v7 三环境各 19/21，新版本各 21/21。

[production-v10/result.json](production-v10/result.json) 证明真实原内核 commit `9f9e9d18574d0914c0d192a90c3babfe1fd63c95` 前后 clean。公开 0001–0010、v8 C 增量与接受的 CPU v10 十二份补丁严格重放，结果与候选全文件 SHA 一致；上下文和补丁哈希篡改均拒绝。十二个实际 arm64 Kbuild 对象编译通过，配置、实际 make argv、输出和各对象 `.cmd` 都已冻结。主控可从 `production-v10/source` 构建完整 Image；本线程只编译对象。

C1 新夹具修正了空平台仍持有 fake descriptor owner、IRQ 注册计数和丢失的 block metadata teardown；意外 panic 直接失败退出，避免旧 setjmp 被复用后无限输出。旧 C1 中断目录、原 830789045B 诊断流、ASan fixture leak 拒绝和 obsolete memory fixture 缺 module ABI 的失败均保留。大流留在原路径，完整 SHA 和大小登记在新收据，未反复复制。

## 支持范围与剩余工作

本轮 PCM 支持链用 `prtd.operations` 持有 prep/submit（包括拒绝后的 giveback）到最后返回，process quiesce 等待 operations=0 后才 close/unregister/release。裸 DMA 客户在自己 tx_submit 仍运行时交还最后 channel 引用不属于该范围；本轮没有为这种调用扩展接口。

寄存器/PM/调度是 kernel API 边界模型，软件测试不能证明真实 AXI 停止、IOMMU、电气状态、lockdep/KASAN 或 watchdog/reset 后的总线安全。主控仍须完成整组独立功能审查、最终 Image/link 和精确 codec ABI，再决定实机单向 START、FD 关闭/注销和 CPU+DMA ready/零 quarantine 的验收。不能仅凭本包的绿结果开放板端 START。
