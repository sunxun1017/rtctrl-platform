# Full duplex contract baseline Implementation Plan

> **For agentic workers:** 本轮仅按已授权范围执行离线契约与基线红例；生产实现须主控审查后另立候选。若后续执行生产计划，使用 executing-plans 或主控委派的 subagent 流程。

**Goal:** 将冻结 v12 的共享关闭和双 START 边界变成可复现、可审查的真实 caller-chain 证据。

**Architecture:** 复制锁定实际普通源码和既有 shim/extractor到本目录，逐函数SHA绑定；真实 caller dispatch决定顺序，显式 kernel API model只提供依赖。

**Tech Stack:** Linux 5.10 C、gcc/pthread、ASan+UBSan、静态AArch64/QEMU、Python记录。

**Spec:** DESIGN.md。

## Global Constraints

- 仅新增本目录，无生产源码/公共patch/guard/旧冻结/板/网络修改。
- CPU输入必须为已冻结v12，SHA7b56bad38b5824b6fdbfb30c735f79f6134f3dd67c87975144598fb31a553141。
- 相同S16_LE/48000/2ch/TRCM1；red表示契约尚未实现，不能转述为全双工通过。
- 每个编译/运行实际argv、exit、stdout/stderr与ELF哈希；失败attempt保留。

## Review Focus

- 两open后关闭一方向，真实deactivate/DAI shutdown/simple shutdown次序与非sticky诊断。
- secondSTART早拒绝时平台DMA未GO；竞争双方先GO时仅失败方向prefix回滚。
- codec sysclk(0)先于CPU拒绝，会改变共享cache，不能只验证CPU cache。
- hypothetical双started状态的每方向STOP不闭合，不把人为状态当实际可达。
- PM/IRQ/codecDAPM/PL330只列边界；本模型未覆盖则不能宣称通过。

## Task 1: 锁定设计与真实输入

- [x] 写DESIGN.md/PLAN.md。
- [x] 复制普通输入、校验原review SHA，抽取真实函数并记录SHA。

## Task 2: Caller-chain基线红例

- [x] 构造双open/peer idle及running单close、sequential secondSTART、pthread concurrent START、codec失败prefix rollback。
- [x] 断言目标契约失败且真实观察匹配；基线不修改，expected failure必须精确列名。
- [x] 模型辅助失败与契约red分开，编译/ASan错误不得当成业务red。

## Task 3: 三环境及交接

- [x] 实际运行host、ASan+UBSan、AArch64 QEMU，绑定输入/真函数/输出/ELF。
- [x] 更新README限制、下一步分段顺序与receipt，不宣布生产/硬件完成。
- [x] 发主控设计与红例review；本轮不commit/push。主控随后授权另立生产目录，本基线保持。
