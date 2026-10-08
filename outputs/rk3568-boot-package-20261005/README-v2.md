# 仅供 RAM 的 Android boot v2 候选修正

v1 包格式与 hash 审查仍有效，但原 DTBO 的 entry0 非空且需要 chosen fixup；原 UART 缺 symbol/phandle。v1 只暂存/load/CRC，未执行 bootm，不能视为候选启动成功。原启动分区、UART、DTBO 和所有 v1 冻结字节保持不变。

新 shim 162457 B，SHA256 75c43a4b217f10dbbbc8ca953124f33e3e548f8fa9994d3c70cde8743261f582，CRC32 cca67eaf。在原 UART 上只新增 /__symbols__/chosen="/chosen" 和 /chosen/phandle=0x2f9；原最高 handle0x2f8，各现有 handle 不变。打包 pre-overlay shim，由 U-Boot 的 Android 分支应用原 overlay 一次；applied-once-audit-only.dtb 不得打入包。

原 DTBO 4MiB SHA256 59b971b4300092de56164904d6a1747276eb569acfc31c09dda6569aa5c8e57d。entry0 offset64/size559/blob SHA256 acf746c91caa230f7958ba2df4e6daf325881e7bce855657aa3b535f440dfec3。真正 libfdt apply 的应用后 DT 162538 B，SHA256 aadaba5cd92f3e4850d304fc122f327720bcaa06f715271784532a603150a9f7。完整 958 节点/4859 原属性逐项比对，恰五项差异：两个 shim 属性、chosen bootargs_ext、mode-bootloader5242c301→5242c309、mode-fastboot5242c309→5242c303。normal5242c300、其他节点/属性/已有 phandle/status/供电/外设/initrd 不变。原 memreserve (a100000,25000)/(a200000,c8c20) 均保留。

红例使用实际编译的 libfdt：原 UART 和仅 symbol 均返回 -1 NOTFOUND、base magic 被置为 ffffffff；备份完整 buffer 的实际 memcpy 恢复保留错误码。完整 shim 后实际 apply 返回0。测试另覆盖 native phandle overflow(-17)、第二 fragment 缺 fixup 的真实失败与恢复，不返回假成功 tree。部署 U-Boot 的备份/恢复/吞错结论由主控二进制审查另记录；这里不冒作 exact libfdt 二进制一致。

本地工具从逐文件 SHA 锁定的 kernel scripts/dtc/libfdt 源快照编译，gcc11.4、gnu11/O2/PIC/shared/Wall/Wextra/Werror，binary45696 B SHA256 03c8661fb005cd967c768332622c6aed6415dbcdce31939de26933e61b388a18。版权与 BSD-2-Clause 许可均保存，不全局安装。最早 c11 reproducer 的 strnlen 声明 warning 保留；生产工具采用 gnu11 且 Werror 编译无 warning。

v2 包继续使用旧 e7a95 RCU Image、native PID1 v3 initrd54db/rootfs3a87。9 RSCE DT 和 v2 单 DT 均为锁定 shim，保留原11名称/顺序与两 logo 原字节；官方 AOSP 工具、原 header 元数据、完整40MiB零填充约束不变。v1 auditor 的原 UART SHA 门槛未放宽，v2 独立 auditor 会重新真实应用包内 shim 并验证五项完整差异。

复现：build-libfdt-v2.py --out 新目录（标准冻结路径 build/libfdt-v2），build-uart-shim-v2.py --out 新目录（标准 build/uart-shim-v2），build-ram-candidate-v2.py --out 新目录；所有目录拒绝覆盖。严格审计入口 audit-ram-candidate-v2.py --package 完整包 --out 新目录。测试入口 test-uart-shim-v2.py、test-shim-boundaries-v2.py、test-ram-candidate-v2.py，各以新 --out 保存证据。

临时 RAM 计划由主控提供：kernel4MiB/DT48MiB/initrd64MiB/PACKAGE512MiB，完整包范围 [0x20000000,0x22800000)，Image实际内存35389440 B。header字面目标仍有重叠，不作为实际搬移证明。新鲜环境、保留区、搬移、64位入口与候选 bootm 尚未验证。本包 RAM_ONLY_NOT_FLASH_READY；原包26/26板测和Android七SHA不变不解除早期DT/USB恢复/正式flash边界。
