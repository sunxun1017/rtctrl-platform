# RK809 电量计离线生命周期候选 v4

当前成果是可独立复核的源码、生产 C 函数模型、实际 Kbuild 对象和单节点 DT 候选。没有创建启动 Image、上传模块、操作板子、开启 BQ/RK817 charger/FUSB、刷机或改网络。整个安卓迁移仍未完成。

生产源：`candidate-v4/drivers/power/supply/rk817_battery.c`，SHA `60214a61168143700b06e9f2aad08697ef6be6f2181d9b8a427336aa10709efc`。
局部 patch：`candidate-v4/rk817-lifecycle-review.patch`，SHA `49adf6d5a0393d3434cfa24be68b9707b30d013efdb39cadd23db1403f352e3d`；未发布公共补丁编号。

修改覆盖 pdev 对象/devres 归属、正确赋 pdev、WQ NULL、失败返回、完整异步初始化、PS/IRQ/诊断成功后才发布、统一 remove/shutdown/action 回收。IRQ 用 request_threaded_irq/free_irq，由 stop 唯一拥有，避免 release_all 已把 devres IRQ 节点移到 todo 后 action 二次释放的问题。stop/remove/shutdown 与 PM 使用 lifecycle mutex，发布/requeue 使用 state spinlock；同步等待在 state lock 外。

停止先永久关闭门，再同步 free IRQ、del_timer_sync、join resume/monitor/calib、销毁 WQ/wake；并发停止幂等。suspend 同步已入场 IRQ 并排空 timer/三类 work，保留 owner；resume 永不复活 permanent stop。IRQ 在暂停和初次发布前缓存事件，仅延后 PS 通知；probe/resume 用事件序号避免 I2C 读取覆盖期间已到的新事件。排空已入场回调保护生命周期，后续暂停 IRQ 仍可更新插拔缓存，因此不声称所有电量缓存被冻结或来自同一时刻。

有限校验包括 OCV 长度 2..255/正值/递增/int 表示、容量整数算术范围、采样 10/20mΩ、monitor 乘法、RK809 分压分母、校准基线顺序和 ADC/分压乘加范围。读/写错误成为 sticky errno：legacy byte composition 不再左移负 errno；后续硬件写、有效属性和异步重排停止。错误不会撤销之前已成功的 PMIC 写入，也不是硬件事务回滚。RTC NULL/读取/校验错误正常归还引用，缺失 RTC 不制造巨大的睡眠间隔。

## 实际验证

- `build/green-v4/result.json`：抽取真实 production struct 与 32 个相关函数，host、ASan+UBSan、AArch64/QEMU 各 **116/116**，stderr 空。依赖 wrapper 包含完整原板 21 个 OCV 值和 14 个 scalar cell；注册失败、WQ NULL、partial IRQ、action reset、detached-todo devres、remove/shutdown/PM、校准/RTC/输入异常和暂停/初始发布插拔事件均有实际执行断言。
- `build/threaded-green-v4/result.json`：真实 callback/stop/PM 函数运行在 pthread，依赖 cancel/free/synchronize API 用真实 join；monitor、resume、timer、threaded IRQ 与 remove/shutdown/suspend 十二类交错，各环境 **90/90**，stderr 空。running callback 退出前 owner 保留，gate 阻止重排，后续 devres 回收幂等。
- `build/kbuild-v5/manifest.json`：独立 clean checkout/配置/O，12 个既有基线补丁和本候选精确应用，32 步 exit0；实际 `drivers/power/supply/rk817_battery.o`，source/配置/.cmd/ELF/nm 已保存。对象 SHA `40206d37b74a67a8b8012b2aaebcfed94be12bd9c23cb09b87a44f09f875d92d`。配置 SHA `f79826d4993b1fe236094af2da4df0d91ea4cc93459df710c66c602c132a93c9`；只有 BATTERY_RK817 n→y 与原配置 BQ24735 y→n，其它 charger 原 n 保持，未动已冻结音频构建。
- `build/dtb-v2/result.json`：真实锁定 libfdt 三次确定性复制 **原板的一个 battery 节点及全部 16 属性**；候选 163743 B/SHA `b44e479e8d346e866f2fef86704215354b7b7bc521c7f2ce43c6de50e7400684`。既有音频 DT 为基线，所有其它节点/属性/phandle/reservation/启动 CPU 与版本字段保持，未增加 BQ/FUSB。DTC exit0，warning 2699 B。`verification-native-v1.json` 重新比较三文件的完整语义，并以 SHA 绑定的既有同基线/同 DTC 诊断确认 warning 字节相同；这一步未新执行 DTC，不能称零 warning。

## 红例与版本边界

`build/red-v5` 为最初真实旧驱动红运行：各 80 项/53 失败，UBSan 复现 pdev NULL 与负 errno 左移。`build/review-red-v1` 保存 devres IRQ owner/getter/表示范围缺口，`build/debug-red-v2` 保存 DBG 开启时发布后读失败，各四红。`build/threaded-pause-red-v2` 使旧 pause 的 running IRQ 未排空稳定为三环境各一红，`build/plug-cache-red-v3` 三环境各四红。旧 source、ELF、结果和拒绝保持；早期 wrapper 构建错误及已知 cache/kasan include 的首次 Kbuild 失败也保留。最终源码及现有 wrapper 依赖绑定在 seal 中。

早期 `threaded-v3` 的 54 项只覆盖 monitor/resume 交错；后来的 90 项增加 timer/IRQ。不能把旧 54 项说成覆盖了后来的四类 callback。

## 未覆盖及部署限制

这是燃料计驱动，会写 GG/ADC/coulomb/SOC/calibration 寄存器；不是只读 collector。没有电量精度、采样电阻实物确认、充电/放电曲线、PMIC 错误后的实物状态、IRQ/MFD 硬件时序、真正 suspend/resume/remove/shutdown 板测。pthread 模型不实现内核调度器、regmap IRQ 硬件或完整数值算法；没有压力/TSan 或全 Image/modules 运行。

原 DT 的 3500 mAh、3750 qmax、7000..8212 mV OCV、10 mΩ 和 140/20 分压均为 **原板配置**，用户新电池没有标定。原16项没有 `design_max_voltage`；当前 Linux parser 仍允许缺省0，而原 charge-status 算法在正电流<500时可能提早报告 CHARGE_FINISH。当前模型 `get_charge_status` 为 stub0，116/90 绿例不覆盖这段算法。这项充电模式兼容是下一步启用电量计算法的明确阻断，未来整合必须拒绝未闭合该参数的 DT；不能凭空添加8400或宣称充电策略正确。当前 DT 候选只能用于后续限定验证设计，不构成部署放行。

`rk817_bat_internal_calib` 原真实函数开头直接 return，本候选保持；周期 timer/work 的生命周期受控，不等于周期校准算法工作。未来启用该旧死代码须重新验证。其它约3000行 fuel gauge 算法、静态 SOC 缓存跨设备语义和外部 power-supply 引用搜索未整体重写/证明。保留有效输入算法和容量参数含义，不把生命周期检查当作完整功能适配。

父 agent 完成独立复核后再判断下一阶段候选 Image 与板测；本目录 seal 不授权启动、充电、解绑、重启或刷机。
