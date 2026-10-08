# C3 ASoC trigger cleanup

输入冻结 B `rk3568-asoc-errors-20261005/driver-source-v2` 与 C2 分配 guard。
板端 START 仍禁止；CPU I2S 的单向 ownership / sticky 来自独立 0012，不声称全双工。

锁定 `soc_pcm_trigger` 对 START 顺序是 link→component group→DAI group。
两个 group 真 helper 遇首成员错误即返回，没有前缀信息，单改外层无法精确回滚。
保持公开签名：START/RESUME/PAUSE_RELEASE 失败在 helper 内仅 STOP 已尝试的
前缀，包括可能部分执行的失败成员；不 STOP 后续未执行成员。外层回滚此前完成的
group 和已执行 link，不重复回滚失败 group。rollback 返回不能覆盖原始首错。
STOP/SUSPEND/PAUSE_PUSH 在两 group 内继续所有成员，外层也继续全部 group/link，
保存第一个负 errno；原成功顺序与 direct DMA-before-CPU 不变。

失败启动的 STOP 是原子 best effort；真正软件排空/硬件 STOPPED 证明在下一
process prepare/hw_free/close/allocator guard，由 checked provider 实现。PCM core
drop/close 的 void/忽略 errno 不构成释放许可；C2 真 ownership quarantine/fail-stop
仍必须执行。RESUME/PAUSE_RELEASE 部分失败按 STOP 退出，不能声称自动恢复旧运行态。
无 callback 跳过；实际 callback 的负 ENOTSUPP 保持错误，不改 void hw_free ABI。

真实函数链红绿：link/组原函数与实际 ret wrapper、soc_pcm_trigger、generic trigger、
DMA PCM trigger/submit/direct issue、checked guard和 core allocator/release。
分别注入 link、每个 component、每个 DAI 首错，包含 DMA 已启动后 CPU 失败、
失败成员部分执行、rollback 错误、CPU STOP 首错仍 DMA cleanup、无 callback和成功序。
记录 source/ABI/harness/binary/stdio SHA；最终串 0001–0010 + 本候选精确重放并拒绝篡改。
生产完整 ABI 编译、只读 DMA 状态证据、硬件单向 START 验收尚待完成。
