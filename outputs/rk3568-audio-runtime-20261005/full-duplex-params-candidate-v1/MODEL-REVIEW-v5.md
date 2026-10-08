# 真实参数 caller 模型 v5 待执行清单

本版沿用稳定 source-v4 五源；旧 MODEL-REVIEW-v4、model-v1..v4 及失败记录均保留。
model-v5/input-manifest.json SHA 为
55c3ee069255df8a23d64d13f3d5d08f5169cb863a6ea8a3e2313b453bd68931。
run-model.py SHA 为
e143702ea4de5cf7a7cf5020c6c6f2fcd5178be77ef992cd6f51e10b42dbf46f。

prepare-attempt-v5 与 precheck-v5 的实际命令均 exit0；当前尚未执行 compiler。
只读门核 13 个 actual SOURCE 普通文件有限映射、5 个 private 源和 128 个
available body 身份。第 13 个 SOURCE 是 sound/core/pcm_native.c 的普通文件
SHA/字节与行引用旁证，并未执行该文件完整外层生产函数；128 也不是执行 coverage。

固定验收为 12 个业务行（8 个 params/cache 合同预期绿、4 个原双 START/共同 STOP
合同预期红）、122 次完整有序观察、22 个完整有序 event case groups。runner
同时校验全部 label/case 顺序、每组事件条数、逐行结果与最终 summary，并在真正执行
后比较三个环境完整 stdout 字节；当前只能称这些检查已准备，不能称三环境已通过。

新增有限 case native_error_boundary_real_HW_FREE 记录实际 pcm_native.c 的
hw_params 调用与错误后 hw_free 调用位置。测试先通过真实 soc_pcm_hw_params 配置 A、B，
在 B 重配置时注入晚 component ENOSPC，再以明确的外层 API 边界调用真实
soc_pcm_hw_free(B)。它必须释放失败方向 B 的恢复 owner，同时保留 A 的 owner 与三项
cache；随后实际 A prepare、单方向 START、STOP 仍可进行。
事务 abort 恢复的软件 B snapshot 并不等于用户态错误返回后的最终 B 状态。
测试没有以手写清 cache/owner 代替 hw_free，也没有称完整 ALSA outer body 已执行。

其余关键病例及 API wrapper/probe/IRQ/PM 边界沿用 MODEL-REVIEW-v4。实例注册和
48k/master/TRCM profile 仍是显式 synthetic，生产 probe 未执行；codec mute、CCF、
I2C、DMA/PL330、DAPM 与 component/link errno fixture 仍在模型边界内。
本阶段没有 Kbuild、Image、模块、DT 激活或硬件执行，也不放行第二方向 START。
