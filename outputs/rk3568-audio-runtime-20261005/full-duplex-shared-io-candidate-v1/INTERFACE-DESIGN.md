# Codec 外围共享 I/O 与有限系统 PM 候选

2026-10-06。私有增量基线是 params `source-v4` 五源，manifest
`889c0e25655b29bbda10061b6f0ac569741b892a20cd0316695498442be8037c`。
新增 `soc-core.c` 来自 accepted audio-v4 SDK 的同一普通源文件。默认未 opt-in 的
codec path/power body 保持；不修改 SDK、公共补丁、旧封存、DT、Image、板或 guard。

## 锁与控制

复用 component `params_lock`，外层可以是 card pcm_mutex 或 controls_rwsem；两者
不反向获取。checked control getters/puts、set_fmt、mute 与本向 shutdown 在该锁内。
必要 MCLK 操作取已有 clk_lock，顺序仅 params_lock -> clk_lock。无新全局 ABI。

三个 manual controls 先验证枚举范围，然后在锁内检查同值；同值即使 sticky FAULT
仍返回 0，完全不作 GPIO、寄存器或 clock I/O，不表示恢复。变值优先 pending/任一
params-owner 返回 EBUSY，再返回已存 params_error；两门均在首 I/O 前。resume flag
只在门通过后发布。原 control 不是 DAPM event，不新增 DAPM callback。

checked path helper 保留原路由与 power 序列的实际操作，每个有返回值的 clock/I/O
都检查负 errno，首错即停。目标 path 与成功 lease 计数仅整段成功后发布。启用
MCLK 失败在任何 codec I/O 前返回 errno，不发布 path、counter 或 retained lease。
OFF->ON 已真实取得临时 MCLK、随后 I/O 失败时固定两槽 retained_clock 记录该真实
引用，保持原 path/counter 并 latch params_error；不能 disable 冒称恢复。ON->OFF
先执行 power I/O，只有全部成功才释放本向 lease、发布 OFF；失败保持原 lease。
没有物理回滚、盲目重放或软件 success cache 冒充已恢复。

## PCM 正常方向清理

checked mute 明确拒 voice/非法方向。独立 startup `shared_open[stream]` 认证本向
open，pending 拒 EBUSY。unmute 另外要求 params-owner 与本向非空 open 相同，并
拒 params_error/mute_io_error。mute 允许 post-HW_FREE 本向 owner 已清除，执行
原有限安全清理并保存真实第一 errno。现有 mute_stream 无 substream 参数，本轮
保证真实 ASoC caller 范围，不能泛称任意直接调用者身份可认证。

shutdown 在同一锁内直接调用 `_locked` owner 释放，不递归取得 params_lock。
只接受匹配的本向 open；capture 每次正常本向关闭执行 bit6 masked pulse，即使
playback peer 保持 open。两个 update_bits 均检查，首错 sticky；第二笔仍作有限
清除尝试。mask 不能改变 DAC 位，不写 PLL/rate/全局 clock。void shutdown 不能把
错误传播成 close errno；正常关闭清本向 open，保留 peer 与 sticky FAULT。

set_fmt 保持 v4 的有限精确 profile 门与 mutex；同成功值无 I/O，变值 pending/owner
前拒。现 hifi prepare 无 codec callback，正常 unmute 走真实 mute_stream。

## PM 首副作用前拒绝

card 纯谓词遍历所有 rtd/DAI，用 `snd_soc_dai_hw_params_any` 检查任一新 hook，partial
也算受管。snd_soc_suspend 在 instantiated 判断之后、snd_power_wait/D3hot/mute
之前返回 EOPNOTSUPP；freeze 同入口。snd_soc_poweroff 在 instantiated 之后、flush
与 DAPM 之前同门，覆盖 hibernate poweroff。默认空 hook 卡保持原完整 body。
ordinary reboot/halt/poweroff 的 device_shutdown 不经过这两个 dev_pm_ops 门。

CPU checked runtime_suspend 在 CPU 锁内最早检查 shared_enabled 且 pending/任一
params-owner，EBUSY 时无 state、MMIO、cache、clock mutation。无 owner 的初始化
format_pm_release 仍可执行原流程。不修改 CPU controls：v12 checked_component
没有 controls，probe 实际选择它；generic enum/loopback 仅 legacy，PPM 被 checked
profile 排除。

## 验证与保留边界

先提取真实函数/数组/类型/注册到窄 C harness，再旧红/新绿；模拟仅替换 kernel
primitive API（I2C/CCF/GPIO/PM 等），保存每笔调用、返回、成功软件字段及 lease。
生产函数字节和有限普通输入 manifest 前后核对。每笔 primitive 通过真实 pthread
mutex trylock 观察 params_lock 已持有，验证控制/格式/mute/pulse 的锁边界；本轮没有
线程竞态压力测试，不把这些锁观察称为完整并发证明。

四个旧 dual START/共同 STOP 红例保持。终端 remove/强制 unbind、retained lease
安全最终归还、联合故障/quiesce 与物理恢复仍需联合契约；本候选不能授权 START
或宣称全部软件/整机迁移完成。系统级其它 device PM 与 resume 物理副作用也不由
card 首门证明。本任务不运行 Kbuild/Image/模块/DT 或板端操作。
