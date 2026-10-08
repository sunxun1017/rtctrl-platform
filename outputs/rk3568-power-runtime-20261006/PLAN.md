# RK809 电量计生命周期离线硬化计划

> For agentic workers: execute this supplied independent subtask inline with rtctrl-dev and the existing migration authorization. No new user approval flow.

**Goal:** 固定 RK817/RK809 电量计对象、IRQ、timer 和 work 的归属、发布及回收，建立可独立审查的离线候选。

**Architecture:** 电量计对象与 devres 归属 platform device。完整初始化异步设施，power supply、非 devm IRQ 和诊断全部成功后最后注册 cleanup action，再发布 timer/monitor。lifecycle mutex 串行化 stop/PM，spinlock 状态门串行化发布与重新排队；同步等待在 spinlock 外。

**Spec:** 本任务父 agent 指令以及原 `drivers/power/supply/rk817_battery.c`、MFD、Kconfig、原板 DT。范围仅本目录；不更改声音产物、共享记忆、TUN、板子或充电器。

## 约束与审查重点

- 原算法和原板容量/OCV 含义保持；新电池没有标定。燃料计会写寄存器，不称只读采集器。
- BATTERY_RK817 专用离线配置可启用；CHARGER_RK817/BQ/FUSB 不启用，不创建板测启动包。
- 明确失败路径必须无异步回调留下；devm owner 必须为 pdev，不能在 child 失败/解绑时留在父 I2C。
- timer、monitor、calib、resume 在 pending/running/requeue 与停止交错时不得越过状态门；同步 cancel 必须在锁外。
- IRQ 仅在完整 power supply 注册后安装，错误必须上报，已安装 IRQ 必须在设备对象释放前同步回收。
- DT OCV 长度、容量、采样电阻、RK809 分压分母和校准基线拒绝无效值；寄存器读错误不可当成有效校准。
- 模型只证明生产 C 的所建 wrapper 行为，实际 Kbuild 证明 ABI 编译；两者不证明电量精度、充电/供电或硬件解绑。

## Task 1: 冻结与红例

- [x] 锁定原驱动、MFD、power-supply/devres/workqueue/wakelock 实现、配置和 DT，记录 SHA。
- [x] 抽取真实 probe/work/timer/IRQ/PM 函数到 C wrapper，模拟依赖注入；旧函数实际执行失败分支，保存 red。
- [x] 保存最小设计和清理次序，不扩展 3000 行燃料计算算法。

## Task 2: 生命周期与有限输入修复

- [x] 候选复制原驱动；pdev owner/赋值、WQ NULL、初始化-before-publication、IRQ错误传播。
- [x] 增加 stop/remove/shutdown/devm 回收；suspend 排空已入回调，resume 在有效状态下恢复并保留暂停插拔事件。
- [x] 限定 DT 和 calibration 校验，production wrapper 旧红→候选绿，host/ASan+UBSan/QEMU 执行。

## Task 3: 编译与冻结

- [x] 本目录另立干净源和 Kconfig/O 输出，实际 Kbuild 驱动对象，记录编译命令、对象和配置 SHA。
- [x] 另立 patch、全部源/模型/结果 manifest，报告硬件和算法未验证范围。
- [ ] 父 agent 独立复核，后续算法兼容收敛后另行决定整合；本任务不作板测放行。

## 清理次序

正常停止持 lifecycle mutex，设置 permanent stopped，关闭发布门；free_irq 同步释放两个非 devm threaded IRQ；del_timer_sync；cancel_work_sync(resume)；cancel_delayed_work_sync(monitor/calib)；destroy_workqueue；wake_lock_destroy。全部在 pdev memory/fields/power supply 的 devres 回收前完成；state spinlock 仅用于发布门，不覆盖同步等待。并发 stop 重入由 lifecycle mutex 串行化，幂等。

probe 失败在 WQ 之前无异步设施；WQ 成功后所有 work/timer/wake 初始化完成，后续失败主动 goto err_stop，不能依赖早期 cleanup action。PS 与非 devm IRQ 全部成功且可选 DBG 寄存器诊断无 I/O 错误后，最后登记 cleanup action，再发布 timer/monitor。action 注册失败自动 stop。部分 IRQ 失败即时释放先前 IRQ；尚未发布 work/timer。devres_release_all 会先把所有节点移至 todo，因此 action 内不能 devm_free_irq；两个 IRQ 均仅由统一 stop 和局部 IRQ 失败路径拥有。

suspend 持 lifecycle mutex，设置 suspended，state lock 外 synchronize_irq 两个已入场 IRQ，再 drain timer/三类 work，随后读取后续状态，不销毁设施；resume 串行化解除 suspended，队列 resume 并恢复 timer。stop 永久状态优先，resume 不复活。sticky I/O 错误保留 errno、禁止后续寄存器写入/有效属性/重排，PM 不以 exit0 冒充读到有效数据。

v4 的 IRQ 在 paused/首次发布前仍缓存最新事件并递增受 state lock 保护的事件序号，暂缓 PS 通知。probe/resume 读取 PLUG_IN_STS 前后比较事件序号；寄存器读取不能覆盖期间新到的 IRQ 缓存。恢复运行时发布延后通知。synchronize_irq 排空调用前已入场 handler，后续 paused handler 只更新单独的插拔缓存，不读取硬件、不发布 work。此项不声称所有测量是同一时刻快照或硬件事件顺序已验证。

## 下一阶段阻断

当前 parser 仍允许原 DT 缺失 design_max_voltage 并留下0，真实 charge-status 算法可能在正电流<500时提前返回 CHARGE_FINISH。get_charge_status 在当前 wrapper 为 stub0，116/90 检查不覆盖该算法。后续整合必须拒绝未闭合此参数的 DT，不能以本候选启动 gauge 算法；需由原 Android/BQ 参数证据解决兼容问题，不能猜测新电池标定值。
