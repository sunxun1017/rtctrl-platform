# 旧 params 调用链基线实际结果

本轮在 host、ASan+UBSan 和 AArch64 QEMU 各实际编译、执行一次 r2 基线。
三次 compile 均 exit0，执行均 exit1（预期业务红）；三组编译/执行 stderr 均空。
每组固定 8 项业务合同均为红，76 次观察断言均通过。76 次观察只有 23 个唯一标签，
包含方向与路径镜像；不能说成 76 个独立测试，也不能说配置问题已经修复。

实际命令、完整 stdout/stderr、二进制与 before/after 输入在 `runs-baselinev2/`。
实际 receipt SHA：669a8d1575f8290862dd599802e722bca43978e543a6e2b9883c82e6536a75bf。
三份完整 stdout 逐字相等，SHA：01c864176cea42a906aea09ae4efb291b5f4a440bae18391903e92c5ae51a227。
独立有限读回还检查了 76 条完整有序观察、8 条有序业务红、22 个有序 transcript 分组，
receipt 位于 `execution-readback-v3/`，SHA：533d0b71fe4b4801c0d376bcb178993bdb28503dfc167e90b647995f5e778f9a。

这些结果明确区分以下行为：

- 健康 peer 运行且第二向同 rate：真实 machine 末段 CPU sysclk 返回 EBUSY，后续
  codec hw_params/PLL、CPU hw_params、component params 不执行；两个 CCF getter 是
  API 查询，不是物理寄存器读取证明。健康不同 rate 保留原 symmetry EINVAL。
- 第二向 CPU hw_params API 错误：失败 CPU DAI 不在真实 `--i` rollback prefix，
  core 清成功 codec 的 rate0，peer CPU rate仍48k；第一错误与 CPU sticky 保留。
- 最后 component `dmaengine_slave_config` API ENOSPC：真实 core 将已成功两 DAI 的
  rate均清0。真实 prepare/单向 PCM START之后，44100 请求因此跳过 rate symmetry；
  machine 的两个 child CCF rate及codec sysclk cache先改为11289600，再被 CPU
  sysclk EBUSY拒绝。候选有限 profile应首共享写前EINVAL；本轮没有该候选实现。
- 两方向都 HW_FREE、然后逐个真实 clean：两次 HW_FREE时active仍2，没有清三cache。
  最新 normalclose归还PM/childclock引用并清sysclk请求，但两DAI配置cache残留。
- START使用真实 PCM/C3 component→DMA API→DAI链；CPU第一个trigger API错误后
  实际前缀rollback保留第一errno、撤销模型DMA GO。第二START仍由CPU component早门
  拒绝且无第二DMA GO。本轮没有全双工START或PL330实机结论。

第一次 `runs-baselinev1/` 三个编译均失败，没有业务执行。根因是旧 mock 的 rtd
num_cpus/codecs 为 int，与真实 unsigned loop在额外严格编译选项下触发 sign-compare。
r2只将mock字段改为实际 unsigned类型，并在新runner窄抑制该warning；生产函数、
合同、旧模型与失败证据全部保持。实际 kernel prior `.soc-pcm.o.cmd`含全局-Werror，
但没有-Wextra/-Wsign-compare；不是“kernel没有-Werror”。读回v2的错误假设已保留，
新v3仅纠正这项旁证，没有重编或重复执行C模型。

runner实际重新核对10个SOURCE映射的before/after；准备审查另核14份source/header，
两种口径独立记录。模型含70继承和20新增可用生产体，仅登记逐字来源与可用性，
不声称90函数全部运行。寄存器、CCF、DMA/PL330、DAPM、PM与mute端点模型边界沿
`README.md`。原四个dualSTART/联合STOP红例保留；未改生产、Kbuild、Image、guard、板。
