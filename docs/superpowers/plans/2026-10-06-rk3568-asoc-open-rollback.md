# RK3568 ASoC open rollback Implementation Plan

> **For agentic workers:** 采用主控委派的subagent流程执行本候选；每段以真实红绿和独立审查验收。
> 用户已要求持续完成迁移；本地候选和验证在既有授权范围内。不自动commit/push/flash。

**Goal:** 打开失败资源逐次归还，同DAI peer存在时关闭不清共享sysclk请求。

**Architecture:** 先修ASoC失败startup事务和PM局部取得prefix，再修simple-card peer门。
CPU v12/C3硬件生命周期和双START拒绝保持；各段可独立通过回归和代码审查。

**Tech Stack:** 锁定Linux5.10.160、C、GCC11.4.0、pthread/ASan+UBSan、AArch64/QEMU、Kbuild。

**Spec:** [设计](../specs/2026-10-06-rk3568-asoc-open-rollback-design.md)。

## Global Constraints

- 固定SDK9f9e9d18574d0914c0d192a90c3babfe1fd63c95，加正式0001–0014和精确SHA。
- 仅新增独立候选和输入/结果目录，不覆盖已实机源、旧冻结、Image或板测试许可。
- 保留first open errno、原正常close排序、C3清理/quarantine、CPU sticky/STOP/IRQ门。
- PM callbacks和pinctrl不移入pcm_mutex；helper签名和component结构不变。
- 不启用压缩音频，不新增双START许可，不操作板子、TUN或系统服务。

## Review Focus

- 失败open与peer最后close的真实单指针marker覆盖；不能以理想化shim掩盖。
- get部分失败自清理后caller再fullput的双释放；PCM和compressed分支均核。
- -EACCES/返回1仍有引用，以及两个component共享同device的重复引用。
- 同DAI peer门不覆盖RK817另一voice DAI，共享缓存范围不能扩大。
- PMusage不是remove/drain证明，default-only不外推泛型pinctrl并发安全。

## Task 1: 锁定实际PM红例

**Files:** `outputs/rk3568-audio-runtime-20261005/full-duplex-contract-v1/` 的新版本目录。

**Interfaces:** 消费已绑定v12/C3 source，生成版本自带input-manifest、真实函数SHA、旧/新红例和执行收据。

- [ ] 保存已有model-v3/runs-v2的manifest、生成器、runner及fixture快照，旧20红例结果保持。
- [ ] 抽取实际get/put及PCM/compressed错误分支，用full-get/partial-get与peer close交错复现PM漏还。
- [ ] 对host、ASan+UBSan、AArch64/QEMU实际编译执行；业务red和编译/工具错误分开。

## Task 2: startup事务与PM取得归属

**Files:** 新 `outputs/rk3568-audio-runtime-20261005/asoc-open-rollback-v1/source/` 下的
`sound/soc/soc-pcm.c`、`soc-component.c`、`soc-compress.c`，以及本候选的测试/记录。

**Interfaces:** 私有clean_locked/post_unlock拆分；现有get/put签名不变。

- [ ] 先断言失败startup归还child clocks、撤CPU指针、原errno不变，full/partial PM引用各一次归还。
- [ ] 实现持锁失败清理、local-prefix PM rollback和caller get-failure分支；保留正常close排序。
- [ ] 执行三环境真实红绿，覆盖所有失败prefix、-EACCES、返回1及共享device引用，旧单方向回归保持。
- [ ] 独立review真实源码/调度切点；失败记录保留，按发现另立新候选版本。

## Task 3: 同DAI共享请求保留

**Files:** 新候选 `sound/soc/generic/simple-card-utils.c`，测试复用真正runtime/DAI计数。

**Interfaces:** 原shutdown签名；真实active数决定两次sysclk0是否执行，child-clock归还不跳过。

- [ ] 两open、关一向断言CPU/codec缓存保持且没有新关闭诊断；最后close缓存归零。
- [ ] 只加CPU/codec都inactive门，CPU零请求门不放松。
- [ ] 同DAI peer-idle、failed-open rollback、各失败prefix与最终关闭三环境回归。
- [ ] 明确peer-running/第二START仍由既有门拒绝，不能将此段称全双工适配通过。

## Task 4: 真实编译、封存和整合门

**Files:** 候选新Kbuild输出/receipt、封存库存/完整SHA；正式patch仅在独立审查后新增。

**Interfaces:** 消费固定源和config；生成实际built-in对象、精确patch及完整源码manifest。

- [ ] 新鲜编译实际soc-pcm.o、soc-component.o、simple-card-utils.o与compressed错误分支目标；记录argv/日志。
- [ ] 主控fresh重跑关键suite，独立复核源码、对象参与构建及完整SHA。
- [ ] 再准备新完整Image/匹配codec和包；旧Image、freeze与已完成v4板测结果保持。
- [ ] 后续有限实机另设计双open/单close矩阵，前后严格guard和正常返回；本计划本身不授予START。
