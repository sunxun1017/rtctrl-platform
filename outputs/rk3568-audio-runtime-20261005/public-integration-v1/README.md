# 音频 CPU v11/v12 的正式增量补丁

本目录把已经审查、构建并用于主控实机 RAM 音频试验的两份冻结 delta 转成正式新增 public patch。原 `0001`–`0012`、v11/v12 封存、实际 Image 私有 source/ABI 和其他协作者文件均保留；没有提交、推送、写正式闪存或操作设备。

| 输入/输出 | SHA256 |
|---|---|
| 新 `0013-i2s-sysclk-shutdown-reset.patch` | `271c64830b1332736cf8e48bc0778c9703b43f53e83aef6a7806fbcc6e682653` |
| 新 `0014-i2s-format-runtime-pm.patch` | `694dc4bc8b03056d65252699293245fae902c325554e2cba609d611d4f07f607` |
| v11 原始 delta | `dd31e7208c71bdc7dac8b41c8d82f9e2702f77c743a80214044d8b28e5422437` |
| v12 原始 delta | `64957ca517417c02dbb7c2a52306bb3020f5b2b730cdf636a0f60fbd950a078c` |
| 最终完整 CPU 源码 | `7b56bad38b5824b6fdbfb30c735f79f6134f3dd67c87975144598fb31a553141` |
| 已测试 Image v3 | `965acb13577032b2f0a44f13508b6a97947398e223a6eab6d04f86d9c7d381fe` |

SDK 固定为 `third_party/linux-rk3588` 的 `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`。正式顺序为已有 public `0001`–`0012`，再应用 `0013`、`0014`。旧 public `0011`/`0012` 分别与实际 Image 14 补丁链的冻结 C3/v10 输入逐字节相同；新两份只增加 Subject、说明和 `diff --git` 行，完整 unified-diff 原始字节保持不变。`prepare-patches.py` 校验这项对应关系，不覆盖已有文件。

`0013` 修复 simple-card 关闭时合法 `set_sysclk(0)` 请求的误拒：原 gate 继续执行，零请求额外要求 STOP、IRQ drained、两路无 substream，然后仅清共享 TRCM 请求缓存；不进行 clock/PM/MMIO 操作、不释放 codec 基础引用、不清 sticky error。下一次 checked `hw_params` 必须先取得新的正频率请求。

`0014` 修复格式设置末尾异步 PM worker 的初始空闲竞争：所有 format MMIO 完成、先发布 first error，成功后才发布私有 terminal handoff；`configuring` 始终保护在途函数，其他操作和 teardown 的门槛保持。checked suspend 仍检查 sticky error、START/STOP，保留原 IRQ drain、缓存隔离和 MCLK 释放硬件流程。所有格式出口在同一锁下清 handoff；严格 guard 的 sysfs 格式不变。

两份 delta 共涉及四个生产函数：`rockchip_i2s_tdm_set_sysclk`、`i2s_checked_hw_params`、`i2s_checked_runtime_suspend`、`i2s_checked_set_fmt`，以及一个私有状态字段。验证同时比较四函数抽取字节和完整 CPU 文件，不能仅凭局部片段推断其余源相同。

## 执行与封存

以下入口只做本地离线工作。`verify` 的输出必须是本目录下尚不存在的直接子目录；它从本地固定 SDK 建立新的临时 clone，逐一实际运行 14 次 `git apply --check` 和 14 次应用，不改原 SDK/实际私有源。实际完成 **89423 个 Git tracked 源文件**的 SHA256、尺寸和 executable/symlink 模式比较，完整 diff/status 相同，只有同样的 23 个源文件相对固定 SDK 改动；同时保存全 CPU 源、四函数、全源库存和 actual ABI 库存。

```sh
python3 -B outputs/rk3568-audio-runtime-20261005/public-integration-v1/prepare-patches.py
python3 -B outputs/rk3568-audio-runtime-20261005/public-integration-v1/verify-public-series.py
python3 -B outputs/rk3568-audio-runtime-20261005/public-integration-v1/verify-builtin-object.py
python3 -B outputs/rk3568-audio-runtime-20261005/public-integration-v1/freeze-evidence.py
```

首先实际运行外部 `obj-m` 单对象 Kbuild，613320 B，SHA `9434e5364ef182592244451879e454ee9ff54626a5042d3599d043214cca6cac`。它带 `-DMODULE` 和不同 MODNAME，与 Image built-in 有真实代码/9 个 alloc 节差异，只保留为完整 C 文件能通过 actual v3 ABI 的旁证，不把它等同于实机对象。

随后在 public SDK replay 上，以新的 O=输出目录直接执行实际 built-in 目标 `make sound/soc/rockchip/rockchip_i2s_tdm.o`，使用复制且前后完整核对的 **2020 个 actual v3 ABI 输入**、完全相同 `.config` 和 GCC 11.4.0。`builtin-object-v2` 实际 exit 0，没有 `-DMODULE`，MODNAME/MODFILE 与实机内建方式一致。首次 `builtin-object-v1` 因只使用系统 PATH 缺 flex/bison，停在 syncconfig；失败记录保留。v2 按实际 Image builder，仅在本地子进程前置既有 `.deps/host-tools/bin`，记录 flex/bison/m4 SHA，无安装/服务变更。

新 built-in 对象 614440 B，SHA `695244526389addf07b1a82a5149c95230444b43314b7ae9bc2a73015f3e77d2`；actual Image-v3 原对象 613448 B，SHA `f1e0b2853592ec3b2eac590e9f35c5e85677fb408a0c859f1a62a420f2a8e717`。原对象仅只读并复制到新目录，未覆盖。ELF 比较证明 `.text`、**全部15个 alloc 节的字节/尺寸/flags**相同；仅移除文件名 banner 后的 `objdump -dr` 全文相同，指令、标签和正常重定位标记均保留；GNU `objcopy --strip-debug` 后**整个对象逐字节相同**。未 strip 原件的差异仅 `.debug_line_str`、`.rela.debug_info`、`.rela.debug_line`，所以新的 built-in 对象可以明确限定为调试信息差异；这项结论不套用于旧 obj-m 对象。

所有对象均检查为 ELF64 LE AArch64 ET_REL。原 SDK/实际 source/ABI、旧冻结文件与全部原 public patch 均读回校验；本任务没有重新构建完整 Image。

本任务不重复先前已经由主控新鲜执行的行为模型；其四套 `root-v12-*-v1/result.json` 和最终 review-note 被 SHA 绑定。既有模型包括真实旧 v11 格式竞争红例 4/5、新 v12 format 90/90、sysclk 48/48、params 140/140，各 host、ASan+UBSan、静态 AArch64 QEMU 三环境。PM/regmap/CCF/IRQ API 模型与物理时序的区别仍保持。

验证/封存的实际结果以执行生成的 `verification-v1/receipt.json`（SHA `8ea1b85795dd79ff13248d7d2f230eddef8c088ee77b06629eaae61ceac04bf6`）、`verification-v1/kbuild/result.json`、`builtin-object-v2/receipt.json` 和 `sealed-evidence-v1/receipt.json` 为准。freeze 复制工具、14 份 patch、两类对象执行日志/收据、ELF 比较、首次准备失败、全 CPU 源和库存/对象；`work` 下 SDK clone、shadow ABI 与 Git 元数据是临时缓存，不计入证据归档。既有 Image、root 模型和板端 raw 日志保留为完整 SHA 引用，并在封存前重新核对；不宣称这些外部原件的全部字节也已复制入此 thin seal。

上面的默认输出已经执行过，独立复跑应分别指定新的 `--out`；built-in 的 `--verification` 指向本次新 public replay 输出，freeze 的 `--verification`/`--builtin` 指向这两份新记录。禁止在旧完成输出目录原地复跑或覆盖。

## 已有板端证据的边界

主控使用上述 Image v3、包 v4 和严格 guard v4 实际验证：正常 card/codec 绑定后自然 initial idle 通过，无 on→auto 诊断性恢复；单独 playback/capture 各传输 24576 帧、各一次 START，DROP/HW_FREE/close 全零返回，前后严格 guard 通过；随后正常 card/codec/CPU 卸载，CPU-unbound 的 16 clock 全零、DMA allocated 0、quarantine 0。原始证据是 `outputs/rk3568-pid1-20261005/private/audio-v4-{pre-playback,playback,post-playback,pre-capture,capture,post-capture,card-unbound-guard,cpu-unbound-guard}-20261006-v1.raw.txt`，本任务只读取和绑定这些已完成记录。

板上只有板子，未连接耳机、喇叭、电机，屏幕排线已拔；三个 codec controls 均 OFF，capture 的 49152 个样本全零。这里验证 PCM/DMA/CPU 生命周期、关闭及卸载，不构成物理声音、麦克风、全双工、长期并发、正式 Linux flash 或整机迁移完成的验收。下一步正式构建入口采用这两份新 public patch 时，应新建输入身份/构建记录；旧 Image/包/封存不会改写成新的补丁身份。
