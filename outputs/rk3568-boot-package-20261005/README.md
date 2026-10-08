# RK3568 boot 包离线证据

原始 boot 备份为 Android header v2，page 2048，header 1660。官方 AOSP android-11.0.0_r1 工具重建 raw 40019968 B 后零填充到 41943040 B，与原文件逐字节一致。完整包 SHA256 为 0db7ae12eebf0f3819e5fb72d9291abb4f12222084d87348a6a95a6a00f21b28，CRC32 为 6e48ba06；raw CRC32 4446cdb6。现场只能使用完整包大小校验，不能用 raw CRC 替代。

原包 second 是 4491776 B RSCE，含 9 个 DTB 与两张各 1555254 B 的 logo。每条资源 SHA1 均独立验证。v2 dtb 字段是 1650869 B 的 11 个连续完整 FDT，不是运行 FDT 的 151680 B。全部项的 SHA、偏移、model、compatible 位于冻结 audit.json。历史 HW_ID=6/BOM_ID=7 选择 RSCE rk3568_smdt_3568a_v20.dtb；该 blob 匹配 concat 第 3 个，不是第 0 个。Android dtb_idx=0 不能证明 v2 第零 DT 的选择。

公开工具与原包往返来源为 AOSP commit 99894068024224a62595e051d69e748e2499f52e。来源文件及许可见 source-lock.json。Rockchip 公共 U-Boot 仅用于理解双 DT 域，不能代替部署中的定制 SMDT U-Boot 源码。

先前 CLI 出现前 U-Boot 已从原启动分区的资源 DT 初始化 PMIC/显示。主控已同意只做 RAM 候选：eMMC boot 原包不变；候选 RSCE 保留原 11 名称、两 logo 字节，全部 9 DTB 换同一锁定 UART DT 并重算 hash/offset；候选 v2 DT 字段也为单个 UART DT。这样消除 RAM 包内部资源选择歧义，但不证明刷入后早期初始化兼容。禁止将本候选用于正式 flash；USB 恢复仍未确认。

候选固定旧 RCU Image SHA256 e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457、162414 B UART DT、972203 B native PID1 production-v3 initrd SHA256 54db3bb6fa94dd1570a306aa90e3caa6ae5ed7bb6b93d96afcae0c5f8881afef。v2 返回岛缺 applet 的历史包不再作为候选输入。候选 root 位于固定 /cache/rtctrl-pid1-20261005-v3/rootfs-pid1.ext4。

复现原包：从仓库根运行 python3 -B outputs/rk3568-boot-package-20261005/build-roundtrip.py --out outputs/rk3568-boot-package-20261005/build/新的唯一目录。测试入口 test-boot-package.py 同样需要新 --out；加 --audit-only 执行 39 项解析测试，不加执行 42 项含真实官方 roundtrip 的测试。所有输出拒绝覆盖。

此目录仅离线生成与审计，不接板、不运行 bootm、不写分区、不 saveenv。原包 RAM 清单仅含单地址 bootm PACKAGE_ADDR。header 中地址是原包元数据，不能作为 RAM 加载方案；主控必须据新鲜 bdinfo、保留范围和实际 U-Boot 搬移行为核包、Image 内存范围、initrd、DTB 地址。

候选的 raw 为 40478720 B、RSCE 为 4582400 B，填充至 41943040 B；所有组件页填充、资源块填充及完整包尾部均审计为零。ARM64 Image 文件 34755072 B，实际头 image_size 为 35389440 B，text_offset=0；在已测 booti 0x400000 时内存终点 0x25c0000。主控暂定包范围为 [0x20000000,0x22800000)，但实际 bootm 目的地与入口仍待现场核实。

候选保留原 header kernel=0x10008000、ramdisk=0x11000000、second=0x10f00000、tags=0x10000100、dtb=0x11f00000。这些字段若当字面目标，会互相重叠；manifest 明确列出交集，并标记 actual_destinations_verified=false。历史 kernel_addr_r=0x280000/fdt_addr_r=0xa100000/ramdisk_addr_r=0xa200000 仅是历史信息，不冒作 fresh 环境。

候选复现入口为 build-ram-candidate.py --out 新目录，严格审计入口 audit-ram-candidate.py --package 完整包 --out 新目录，验证入口 test-ram-candidate.py --out 新目录。原默认 audit-boot.py 会拒绝候选的单 DT 字段。原包冻结的 source-snapshot 保留扩展前审计源码，可独立复核历史字节。
