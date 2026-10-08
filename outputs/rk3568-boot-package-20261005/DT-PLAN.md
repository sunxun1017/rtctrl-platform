# 两个 DT 域与 RAM 候选裁决

1. 早期域：已部署 U-Boot 在进入 CLI 前从 eMMC boot 资源读取 DT，使用它初始化 PMIC/显示。只加载 RAM 包不会改变这个阶段的输入。原 boot 与所有原备份保持只读。
2. Linux 域：公开 Rockchip U-Boot commit 1c535d65b8509f388d09e49fb6961f49fda35a1d 的 rockchip_ram_read_dtb_file 使用 page + ALIGN(kernel) + ALIGN(ramdisk) 找到 Android second，再建立资源列表；rockchip_read_dtb_file 从资源选 DT、校 hash 并做 fixup；android_image_get_fdt 返回 fdt_addr_r。该代码显示可行路径，但不是定制 SMDT 二进制的逐函数证明。
3. RAM 候选：保留全部原 RSCE 名称，9 个 DT payload 都是冻结 UART DT，两张 logo 保留原字节，条目 SHA1 与 offset 重建。Android v2 dtb 字段为同一 UART DT。无论 RAM 包资源选择哪一个原 DT 名称，其 Linux DT blob 一致；不能据此断言部署 U-Boot 没有其它修正。
4. 候选只包含旧 RCU Image 与 native PID1 v3 initrd，第一轮无 display/PCM/WLAN/MCU START。主控依据日志确认实际传入 DT、PID1 ROOT_READY、软件测试及原生 RAM_READY 清理，再正常回 Android。
5. 正式 eMMC 包仍缺早期 UART DT 与 U-Boot PMIC/显示兼容证据、定制 U-Boot 精确选择源码/反汇编证据及可用 USB 恢复。RAM 成功不足以解除这些前提。本候选必须标为不可正式 flash。

地址核算必须把完整 40 MiB 包范围、ARM64 Image 头 image_size、实际目标 DTB/initrd 及 U-Boot 保留空间一并检查。原 header 地址本身可能互相重叠，不能套用成可用 Linux 地址。候选可记录离线范围推算；最终执行地址及重定位行为由主控现场核实。
