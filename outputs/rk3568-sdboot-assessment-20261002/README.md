# RK3568 原机 SD 启动可行性核查（2026-10-02）

2026-10-05 实物信息更新：用户确认这块板子没有 SD 卡座。下面保留此前的软件控制器与
U-Boot 字符串调查；不再以取得 SD 卡作为本机后续步骤。当前路线为 eMMC 普通文件暂存、
串口 U-Boot RAM 启动；正式 eMMC 启动仍需完成恢复入口与启动包验证。

用户当前没有 SD 卡，希望先判断以后能否以 SD 卡启动；本次已连接串口。
对象是 AIoT-3568PQ / 3568A 原机，当前 Android 11、Linux 4.19.232 #49。

## 结论

**以 SD 卡启动有较强的可行性依据，可以沿这条路线准备，但尚未完成插卡或启动验证。**
当前板子的 SD 控制器已启用；原机 U-Boot 分区内包含明确的 SD 启动环境脚本。
这些证据不等于当前 U-Boot 运行环境、实际启动顺序或 SD 卡镜像已经验证。

## 本次实际核查

Windows 重新枚举到 CH340 / COM5，使用 1500000 baud、8N1、无流控、DTR/RTS=false。
先被动读取，再用回车确认 `console:/ $`，通过 `su 0 sh -c` 读取系统资料。
COM5 是本次连接快照，不能沿用旧记录中的 COM6。

1. 当前 SDMMC0 节点 `/sys/firmware/devicetree/base/dwmmc@fe2b0000` 为 `okay`，
   有 `supports-sd`、四位总线、四组 pinctrl 和两路供电引用。
2. 实际存在 `/sys/class/mmc_host/mmc0`，指向 `fe2b0000.dwmmc`。
   当前只枚举到 SDIO 和 eMMC 卡，没有 SD 卡；存在 host 不证明卡槽电气和插卡读写通过。
3. 从 `/dev/block/by-name/uboot`（本次映射为 `/dev/block/mmcblk2p2`）只读提取字符串，
   找到 `U-Boot 2017.09 (Mar 12 2026 - 16:01:04 +0800)`，以及：
   - `boot_targets=mmc1 mmc0 mtd2 mtd1 mtd0 usb0 pxe dhcp`
   - `rkimg_bootdev` 中先判断 `mmc dev 1 && rkimgtest mmc 1`，成功分支打印 `Boot from SDcard`，
     随后是 `mmc dev 0` 分支。
   - `bootcmd` 包含 Android、FIT、Rockchip 镜像启动和后续 distro 扫描；
     同时存在 `extlinux/extlinux.conf` 扫描逻辑。
   - 镜像内 `bootdelay=0`。没有测试能否中断，也没有因此修改启动延时。
4. 当前 Android 内核启用了 MMC、MMC_BLOCK、MMC_DW、MMC_DW_ROCKCHIP 和 eMMC SDHCI 驱动。

以上 U-Boot 内容是**存储分区内的字符串和环境脚本**，不是运行中的 `printenv`。
同样内容出现两次不单独解释为已验证的冗余启动机制。Android 的 `mmc0/1/2` 编号
也不能直接套用到 U-Boot 的 `mmc0/1`。

已校对的摘要见 [serial-evidence.txt](serial-evidence.txt)。每步实际发送命令：

- [当前身份](01-current-state.command.sh)
- [SD host 与内核设备树](02-sd-host-state.command.sh)
- [原 U-Boot 字符串与驱动配置](03-bootloader-strings.command.sh)
- [SD 启动环境脚本](04-sd-boot-policy.command.sh)

原始 `*.output.txt` 与 `*.raw.bin` 只保留本地，由目录 `.gitignore` 排除；
摘要保留查询所得关键原文，去掉串口行编辑回显，不替代原始记录。

## 后续还需确认

- 实物 TF 卡槽及走线、插卡检测、枚举与读卡；没有卡时不能完成这些测试。
- 完整上电日志或 U-Boot 实际命令行中的启动介质、MMC 编号、环境与加载地址。
  不能仅凭镜像内默认脚本保证每次都会优先选择 SD。
- 本板匹配的启动镜像布局、DDR/loader/信任固件、内核和设备树。
  普通复制一个 `Image` 文件不能视为制作完成。
- 仓库现有 [firstboot DTS](../../platforms/rk3568/boards/aiot-3568pq/bsp/rk3568-aiot-3568pq-firstboot.dts)
  仍将 `sdmmc0` 设为 `disabled`；若 Linux 根文件系统放在 SD 上，需要补供电、引脚和控制器配置。
  只在引导阶段从卡加载到 RAM 的 initramfs，是另一种启动验证范围。

下一步先核对实际启动链，随后准备本板专用启动卡；取得 SD 卡后再验证。
现有 [启动准备记录](../rk3568-boot-preparation-20260928/README.md) 中恢复备份未完整回传、
USB 恢复入口未实测的限制仍未解除。

本次没有重启、关机、刷写、保存 U-Boot 环境、改设备树、挂载 SD 或向板端保存脚本；
没有主动采音、采帧或发送 MCU 指令。板子保持原 Android 运行。

## 官方资料解释范围

[U-Boot 官方 Rockchip 文档](https://docs.u-boot.org/en/latest/board/rockchip/rockchip.html)
包含 RK3568 和 SD 启动镜像的构建/写入路线；不单独证明本板适配完成。

[Rockchip rockchip-common.h](https://github.com/rockchip-linux/u-boot/blob/next-dev/include/configs/rockchip-common.h)
把默认 MMC 顺序描述为 SD index 1、eMMC index 0，并定义与本次提取内容相似的脚本。
这是公开代码对脚本含义的解释，不是本机 U-Boot 编号的实测。

[Rockchip boot_rkimg.c](https://github.com/rockchip-linux/u-boot/blob/next-dev/arch/arm/mach-rockchip/boot_rkimg.c)
中启动设备选择可优先采用指定配置或 preloader ATAGS，再走扫描列表；
这是不能把默认 SD 优先脚本直接视为本机实际顺序的一个原因。
公开代码并未锁定为本机厂商编译所用版本。
