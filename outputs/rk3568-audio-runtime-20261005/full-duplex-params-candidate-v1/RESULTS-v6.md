# 共享配置候选的实际有限模型结果

source-v4 五份私有生产源码保持只读审接受版本，source-manifest-v4.json SHA
889c0e25655b29bbda10061b6f0ac569741b892a20cd0316695498442be8037c；
shared-params-private-v4.patch SHA
d54c768b6686169de9606c1c1466fb731d2a1388661ccd2bad280d0bffbcec51。

candidate5 首次实际三 compiler 均 exit1，唯一原因是有限抽取遗漏新 setter 所调用的
旧 rk817_set_dai_fmt 生产体。runs-candidate5 与 execution-cli-v5 完整保留，未执行模型。
新 prepare-model-v6.py 只加入该真实依赖与逐 body 身份映射，未改变生产源码、业务
断言或 warning 策略。prepare-attempt-v6、precheck-v6 实际 exit0。

candidate6 在 host、ASan+UBSan、AArch64 QEMU 三环境实际 compile0、execute1。
execute1 是保留四项旧全双工失败的预期状态，不是全套通过。每环境均为 8/12 业务
合同、122/122 观察、22 个有序 event case groups；三 execute stderr 为空，完整 stdout
字节相等，SHA 为 f8c013770c8c25898c55061ddb25026da10b294d19d6dec5f2b031906dc3f849。
runner 校验全部有序断言 label、业务名称与结果、case 顺序/逐组条数、最终 JSON，
并在执行后重新核输入与 runner 字节。观察次数不等于独立测试数量。

八项 params/cache 合同在两个方向均成立：CPU reuse 路径不再触及原 CCF 错误注入点；
晚 component 错误保留 peer 三 cache；两次 HW_FREE 在最后 params owner 释放时清缓存；
running peer 的不合法重新配置在共享写前拒绝。额外观察覆盖首次错误与 FAULT 保留、
重复/陈旧 commit、CPU commit 错误窗口仍保持预约、cookie 不回绕、runtime init 正 sysclk
的纯值验证、partial/default/voice 分支、late release 半状态及后续 FAULT、首 errno 与真实
free prefix，以及真实 single START/C3 错误回滚。

有限 native_error_boundary_real_HW_FREE 用实际 soc_pcm_hw_params 制造 B 晚失败，再在
显式 ALSA outer API 边界调用真实 soc_pcm_hw_free(B)。它释放恢复后的 B owner，保留 A
owner/cache，并由 A 的真实 prepare、single START、STOP 检查后续能力。pcm_native.c
普通文件 SHA/行引用已锁，完整外层 state-machine 生产函数没有执行；不能将 abort 的
B snapshot 恢复当作用户态最终 B 状态。

仍失败的四项是 sequential_first_0_second_normal_START、
sequential_first_1_second_normal_START、concurrent_two_normal_START_commit_both、
hypothetical_dual_joint_STOP_reaches_global_proof。本轮没有放松旧 START/TRCM 门。

证据入口：runs-candidate6/receipt.json SHA
00a7ed71c9357e75f69183491c9e99dcffc3ae7b30d2dbc1918c5fad1f426ea2；
model-v6/input-manifest.json SHA
1d724f4514139356943fa912fc736fd93c6a5b72675161ded3795766aeddf5f2；
run-model.py SHA e143702ea4de5cf7a7cf5020c6c6f2fcd5178be77ef992cd6f51e10b42dbf46f。
129 个 available body 身份不是执行 coverage；13 个 actual SOURCE 有限映射包括只作
引用旁证的 pcm_native，另有五个 private source。Synthetic profile/实例注册、API
CCF/I2C/DMA/PM/codec mute、errno fixtures 及生产 probe 未执行的边界仍适用。
没有 Kbuild、Image、模块、DT 激活或板测试；系统 PM/manual codec controls 与 PL330
实际异步行为仍由后续独立工作闭合。本目录尚未大规模封存。
