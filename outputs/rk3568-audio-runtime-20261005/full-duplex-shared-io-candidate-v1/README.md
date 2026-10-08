# 私有 codec 外围 I/O / PM 候选

终端生命周期追加候选现为 [source-v5](source-v5/)，对 source-v3 的补丁见
[terminal-private-v5.patch](terminal-private-v5.patch)，准确锁、file drain、FAULT
lease 与本次 1471 项真实红绿模型见 [TERMINAL-DESIGN-v5.md](TERMINAL-DESIGN-v5.md)。
此前 source-v3 和 1111 项结果原样保留；下文记录第一阶段，不代替新增终端边界。

第一阶段稳定源为 [source-v3](source-v3/)，仅 codec、CPU runtime_suspend、ASoC card PM
三源产生增量。可整合补丁：[shared-io-private-v3.patch](shared-io-private-v3.patch)，
25084B，SHA256 `3c49c2ee31c715dae321d9e499977382c40347ec02c2c9d2e848287525a9606a`。
[源身份](source-manifest-v3.json) SHA256
`9c279d2b79415fa4f11e163c723542bde9fead432aa56e29358a80140ab06036`。
设计与准确边界见 [INTERFACE-DESIGN.md](INTERFACE-DESIGN.md)。

## 已实现

- checked 三个 manual controls 在 params_lock 内验证范围、同值、pending/owner 与
  sticky error；同值完全无 I/O，变值有预约或 params-owner 时 EBUSY。
- checked 完整路由/power helpers 每笔 clock/I/O 保存首 errno，目标 path 与成功
  lease 计数后发布；不确定物理改变保持旧 path/counter 与 params_error。新实际
  MCLK 引用用两槽 retained_clock 保存，不冒称回滚。
- checked mute 拒 voice，使用独立 open 身份；unmute 要本向 params-owner，正常
  post-HW_FREE mute 可清理。capture 每次本向 shutdown 执行 bit6 masked pulse，
  两笔错误均检查、第一错误 sticky，不写 peer 的 DAC/PLL/rate 位。
- card 任意新 hook（含 partial）在 suspend/freeze 的 wait/D3hot/mute 前及
  hibernate poweroff 的 flush/DAPM 前返回 EOPNOTSUPP。CPU runtime_suspend 在
  pending/owner 时锁内首门 EBUSY。CONFIG_PM_SLEEP=n 的 poweroff 仍可编译。

未修改 CPU controls：v12 checked_component 没有控件，probe 实际选择它；八个
generic enum 与 loopback 是 legacy 接线，PPM 被 checked profile 排除。原调查
README 中这部分结论由主 agent 在原证据目录纠正，本目录不覆盖该任务的文件。

## 实际离线验证

最终旧 [model-old-v4](model-old-v4/manifest.json) / [runs-old-v3](runs-old-v3/receipt.json)：
1111 个检查中 25 通过、1086 业务红，三个环境一致，实际程序 exit1 正是预期红。
最终新 [model-new-v4](model-new-v4/manifest.json) / [runs-new-v3](runs-new-v3/receipt.json)：
host、ASan+UBSan、AArch64 static QEMU 各 1111/1111，实际编译/执行 exit0、stderr
为空，三个完整 stdout 字节相同。模型 manifest SHA256
`e788f94a1a3ed0b0c45d8a2acc2953113ec51de7cedc66f5019c09c563114db0`。

模型从实际 source 提取 36 个完整函数、power arrays、codec priv/shared state 与
实际 ops 注册；只有 kernel primitive API 是有限模拟边界。覆盖每条已枚举路由的
每笔 enable/OFF I/O 失败、active 路由切换失败、clock 获取失败、真实 lease、mute
open/owner/pending、本向 shutdown 首错与 DAC mask、六 partial hooks×四 DAI 的
两个 card PM 入口、CPU runtime 预约门。每笔 primitive 使用真实 pthread trylock
观察锁已持有；本轮没有多线程压力测试、I2C/CCF/GPIO/DAPM/PL330 物理执行。

另以保留实际 CONFIG_PM_SLEEP 相对位置的有限 source 切片，实际 host 编译并执行
低功耗禁用分支：`CARD_NO_PM_SLEEP -95 0`，exit0。切片省略其它 resume/late sections，
不是完整 SDK Kconfig/Kbuild 或 ABI 证明。

[有限最终核对](final-audit-v1.json) 32/32：六原输入当前 SHA 保持，三个增量及 patch
精确，八个 legacy 路由/power/mute/shutdown 函数逐字不变，模型 source/file 身份在
每轮执行前后保持。`git diff --no-index --check` 无 whitespace 诊断；其 exit1 表示
私有 source 与 baseline 存在预期差异。

## 保留失败和版本

首次 [runs-old-v1](runs-old-v1/receipt.json) 三环境实际编译因 primitive 缺 BIT 宏失败，
原 stderr 保留；补模型 API 后才取得业务红。早期 runs-old-v2/new-v1 为 1099 检查，
后来增加 actual retained 记录、active 路径与 shutdown 双 errno 检查到 1111。
source-v1 的 PM 谓词在 CONFIG_PM_SLEEP 内仅是工作草案；自审后移到外层。
source-v2 也由后续 getter 全读锁覆盖的 source-v3 替代。历史没有覆盖或删除。

## 尚未证明

没有 Kbuild、Image、模块、DT、板操作或 START。四个旧 dual START/共同 STOP 红例
保持，由参数整链模型另行运行；本窄模型不复制这四项，也不称其已修复。
source-v5 已补健康 terminal 的 file drain、实际 refs 归还和已知 FAULT/retained
硬失败保持资源；联合 FAULT/quiesce、系统级其它 device PM、resume 与物理恢复
仍需后续联合契约。void shutdown 的 sticky
错误不等同 close 返回错误。这里的通过不授权全双工 START 或完整迁移验收。

主 agent 负责独立最终审核、与参数补丁合并和实际 Kbuild/Image；本目录没有修改
公共补丁、SDK、旧 Image/seal、DT 或仓库项目记忆。
