# RAM boot v2：真实 Android overlay 与 UART shim

范围只在本输出目录的新版本源码/产物，不接硬件，不改原 UART、原 DTBO、v1 冻结包或 PID1。主控负责独立审查与上板。本计划采用 rtctrl-dev、接收审查反馈和测试驱动流程；主控明确禁止 Git/硬件操作及无关项目测试。

## 固定输入与语义

- UART 原输入 162414 B，SHA256 7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1。
- 原 dtbo.img 4194304 B，SHA256 59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d。big-endian header magic d7b7ab1e，total623/header32/entry32/count1/table32/page2048/version0；entry0 offset64/size559，其余尾零。blob SHA256 acf746c91caa230f7958ba2df4e6daf325881e7bce855657aa3b535f440dfec3。
- RAM shim 在原 UART 上仅新增 /__symbols__/chosen="/chosen" 与 /chosen/phandle=0x2f9。原最大 phandle=0x2f8，chosen 没有 handle。打包的是 shim，应用后 blob 只作验证，防止重复 overlay。
- 真实 libfdt apply 后，相对原 UART 全语义差异严格为五项：上述两个新增、chosen/bootargs_ext="androidboot.boot_devices=fe310000.sdhci,fe330000.nandc"、mode-bootloader 5242c301→5242c309、mode-fastboot 5242c309→5242c303。normal5242c300 不变；全部节点/其他属性/已有 phandle 与 status、电源、外设、initrd 均不变。
- 原 memreserve (0xa100000,0x25000)/(0xa200000,0xc8c20) 在 shim 与应用后均保持；不能以此声称现场已处理实际 initrd/DT 目标范围。
- 锁定第三方 kernel scripts/dtc/libfdt 源码逐文件快照、SHA；只在新 build 目录本地编译共享 libfdt，不全局安装。GPL/BSD 双许可版权保留，独立 Python 代码 MIT。
- failure restore 证据必须显示 libfdt 实际失败可能破坏 base magic，备份恢复后严格原字节且错误仍上报；不能将已知 U-Boot 吞 overlay 错误的行为记为成功。

## 执行步骤

1. 先写真实三分支红例：原 UART apply 失败、仅 symbol apply 失败、完整 shim 应成功但尚无实现时仍实际失败。保存工具、源码、输入与结果。
2. 实现有界全树语义解码和真实 libfdt bridge：总长、结构/字符串/reserve、整数溢出、缺节点、phandle 冲突/非法长度与尾部检查。shim 先核锁定输入及 handle 唯一性，再精确新增两个属性，pack 后完整 semantic diff。
3. 实际 apply 锁定 entry0；验证完整五项 diff，保存 before/after 与错误恢复证据。补有价值的真实变异测试；未知差异拒绝。
4. 独立 v2 builder/auditor 绑定新 shim 长度/SHA；9 RSCE DT 与 v2 单 DT 相同 shim，11 原名称/顺序与两 logo 保持。旧 e7a95 Image、native v3 initrd54db/rootfs3a87、官方 AOSP/header/40MiB 尾零约束不变。v1 builder/auditor 与冻结源不动。
5. 候选地址仅主控临时方案 kernel4MiB、DT48MiB、IR64MiB、PACKAGE512MiB；header 保留原元数据、包范围独立。具体 env/搬移/保留区与 64-bit 入口仍需主控现场核验。
6. 完成真实测试和独立解码，冻结新源、工具、产物与证据，交主控独立审查。状态 RAM_ONLY_NOT_FLASH_READY；未执行候选 bootm，不放行正式 flash/USB 恢复。
