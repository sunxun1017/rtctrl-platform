# 有限共享参数候选 Implementation Plan

> 使用 executing-plans 按步骤完成；本 agent只写此候选目录，不提交或推送。

**Goal:** 闭合实际旧params基线8项合同，保留4项未解决双START/共同STOP红例。

**Architecture:** 显式板profile opt-in选择两端checked ops，card mutex下CPU先预约，
codec随后，沿真实caller完成末段组件后按codec→CPU提交。固定2slots的endpoint
owner与cookie undo负责cache/free/abort；默认空hooks保持原行为。

**Tech Stack:** Linux5.10 C、真实生产函数wrapper、GCC/ASan+UBSan/AArch64 QEMU。

**Spec:** INTERFACE-DESIGN.md；父级DESIGN-v3及旧baseline r2实际收据。

## Global Constraints

- 仅当前单CPU/单codec hifi、48k/S16_LE/2ch、MCLK12288000、TRCM1/bclk64/lrck1。
- 两端显式 `rockchip,checked-shared-params-48k` opt-in；本轮不激活DT。
- 只新私有五源/patch/model；SDK、accepted Image/source、旧seal、guard、板保持。
- 不做Kbuild/Image/module/硬件/TUN/network/commit/push。
- available生产body数不当执行coverage；API模型不当CCF/I2C/PL330/IRQ物理证明。

## Review Focus

- CPU第二向同tuple重用已跳过CCF，原CPU CCF注入不能虚构成仍有负errno。
- codec已commit而CPUcommit失败，abort必须撤销这次codec owner/cache而保留peer。
- 旧rollback --i与末段component失败，checked不能重复free/清peer cache。
- mixed/multi/no-opt-in与voice，在opt-in路由与默认空hooks之间不能误切分支。
- 同substream重复apply、stalecookie与HW_FREE/close/START竞争不能解预约。

## 步骤

1. [ ] 固定五基线源、DESIGN-v3与旧baseline r2的有限普通SHA映射，完成接口自审并交主控。
2. [ ] 主控准确接口接受后才修改五份私有生产副本。先header/core事务与strict/nonopt
   分支，再CPU/codec owner实现，最后machine复用；每段保留firsterrno与empty默认路径。
3. [ ] 从新真实源提取候选body，复用旧params caller模型；注册实际checked ops及新
   helpers，明确synthetic opt-in、probe未执行、codec mute/DMA/PM API边界。
4. [ ] 原8业务合同按正确机制变绿；不同format/rate首共享I/O拒绝、两idle reuse零
   CCF/PLL、最后free cache0、首次I/O dirty、CPUcommit失败codec undo各有限断言。
   保留真实C3 START/rollback；四旧duplex红用真实新params配置前置而不放宽START。
5. [ ] 准备源/model交主控/独立只读审，按门执行host/ASan+UBSan/AArch64QEMU；每次
   原失败保留，新版本修harness，固定业务名单/观察有序标签/完整stdout字节相等。
6. [ ] 只报告源/patch/有限输入、实际结果与未闭合控制/PM/voice范围；不封存大库存，
   不转为Image/板许可。后续整合/ABI/DT由主控另决。
