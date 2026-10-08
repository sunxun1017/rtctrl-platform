# RK3568 源码 Linux 5.10 首次实机启动

2026-10-04：公开源码构建的 `5.10.160-rt89-g9f9e9d18574d-dirty` 已在 3568A 板上启动，
进入独立 BusyBox 串口 root shell，完成基础驱动与运行内存核对，随后返回原 Android 11 / 4.19.232。
原 `boot/uboot/trust/dtbo/vbmeta` 五个分区完整 SHA-256 与已备份值一致。

此前独立 Linux 使用原 4.19 内核二进制；本次更换为锁定源码、明确配置和补丁构建的内核，
配合重新构建的板级 DTB。原 DDR/loader/BL31 等启动二进制仍保留；整机开源和全部外设迁移尚未完成。
本次是 RAM 首启验证，`board_boot_tested=true`，`deployable=false`，没有接入自动部署或刷机流程。

## 本次改动与输入

首启前发现原候选遗漏高地址 256 MiB `no-map`，且 DRM logo/LUT 仍为零范围。
板级 DTS 已补齐原机保护范围：

| 保护对象 | 地址 | 长度 | 运行核对 |
| --- | --- | --- | --- |
| 高地址 buffer | `0x1f0000000` | `0x10000000` | `no-map` 存在，iomem 显示 reserved |
| loader DRM logo | `0xedf00000` | `0x002f7b00` | reg 原样保留，页对齐范围为 reserved |
| loader DRM cubic LUT | `0xeff00000` | `0x00008000` | reg 原样保留 |

没有复制原树数字 phandle，也没有通过启用显示来恢复这些保留区。
编译后的 DTB 审计新增四项检查，故障注入从 8 项增加到 12 项：缺失 no-map、错误长度、零 logo、零 LUT。
先确认新测试在旧审计实现下失败，再修改审计；新编译 DTB 的 12 项全部通过。

| 输入 | 字节数 | U-Boot 加载地址 | CRC32 |
| --- | ---: | --- | --- |
| 源码 Image | 34,888,192 | `0x00400000` | `7740ca58` |
| 本次 firstboot DTB | 161,378 | `0x03000000` | `8df189f6` |
| 原最小 initramfs | 533,234 | `0x04000000` | `b9718d95` |

Image 沿用[完整构建记录](../rk3568-boot-preparation-20260928/README.md)中的产物，本次没有重新编译 Image。
源码 commit 为 `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`；`dirty` 对应已保存的
[cache/KASAN 包含补丁](../../platforms/rk3568/boards/aiot-3568pq/patches/0001-arm64-cache-kasan-include.patch)，
不能称为未修改原树。配置 SHA、补丁 SHA、全部产物 SHA 与 DTB 源文件 SHA 见 [result.json](result.json)。
旧构建目录的静态 manifest 仍保留当时 `board_boot_tested=false`；实际板测结果另存于本目录。

DTB 实际经过 CPP → DTC → 反编译 → 审计，新板级 DTC 警告为零。复现构建时输出目录必须不存在或为空：

```sh
python3 platforms/rk3568/boards/aiot-3568pq/build-firstboot.py \
  --kernel third_party/linux-rk3588 \
  --dtc .deps/kernel/aiot-3568pq-final/scripts/dtc/dtc \
  --output outputs/rk3568-source-kernel-20261004/private/dtb

python3 platforms/rk3568/boards/aiot-3568pq/test-firstboot-audit.py \
  outputs/rk3568-source-kernel-20261004/private/dtb/rk3568-aiot-3568pq-firstboot.dtb -v
```

## 实际启动顺序与地址依据

1. 重新确认串口、原 Android/root、供电与网络。用户充电后初始电量为 59%；
   Android 仍报告 AC/USB powered=false，不能称为已确认持续外部供电。
2. 电脑重新校验[15 项启动备份](../rk3568-backup-linux-20261003/README.md)，
   原机再次读取五个分区摘要。备份范围不含完整 recovery/super/userdata/oempriv，也未验证裸机刷写恢复。
3. 网络 ADB 传输 Image 和小 DTB；复用板内 initramfs。
   [prepare-android.sh](prepare-android.sh) 校验 SHA 后写入新建的普通 cache 目录，拒绝覆盖已有目录。
4. 重启 Android，仅在 U-Boot 切换阶段中断自动启动；现场确认 U-Boot 2017.09、eMMC `mmc 0`、cache `0:c`。
   查询 bdinfo、分区、加载文件及 FDT；三个文件加载后逐项 CRC 验证。
5. 只修改内存环境/FDT，执行 booti；Linux 完成检查后使用 RAM-only guard，再请求 SysRq 即时复位。
6. 串口确认 Android boot_completed=1、root 可用和五个分区完整 SHA 一致，恢复状态读回后释放串口。

现场 bdinfo 的低地址 RAM 为 `[0x00200000,0x08400000)`，第二 bank 为 `[0x09400000,0xf0000000)`；
U-Boot relocation=`0xedcf3000`、TLB=`0xefff0000`、SP=`0xeb9f85b0`。
Image 头部 `text_offset=0`，内存跨度 `0x021e0000`，加载/最终范围为 `[0x00400000,0x025e0000)`；
不能用文件长度代替含 BSS 的完整跨度。DTB 与 initrd 位于同一低地址 bank 且不重叠。

原 U-Boot 后期 hook 仍输出 `Kernel from 0x00280000 to 0x00400000`，即使本次 ext4load 和 booti 都指定 `400000`。
原二进制静态核查确认日志源地址取自环境 `kernel_addr_r`，复制长度来自镜像结构；本轮未运行采样该长度，
不据这条日志断言完整 Image 实际搬移，也不声称厂家路径完全没有搬移。
最终 Linux iomem 证实内核起始地址为 `0x00400000`；原样消息见 [boot-excerpt.txt](boot-excerpt.txt)。

[load-ram.json](load-ram.json)、[boot-ram.json](boot-ram.json) 是实际串口命令与响应检查记录。
`fdt resize 10000` 后，原两项 memreserve 仍为索引 0/1，新增 DTB 自保留为索引 2；
先匹配原地址/长度，才删除旧 `0xa200000/0xc8c20` 和 `0xa100000/0x25000`，保留 DTB 自保留。
这些是上一份 Android FDT/initrd 的捕获地址；本次 DTB/initrd 已有独立加载范围。
若实际 memreserve 索引或值不同，不能照抄删除命令。

本次命令行：

```text
console=ttyFIQ0 earlycon=uart8250,mmio32,0xfe660000 rdinit=/init ro loglevel=7 panic=10
```

`fdt_high=ffffffffffffffff` 只约束 DTB 搬移，并不关闭厂家 fixup。
实际 U-Boot 添加板级参数，`memory@200000/reg` 被补零至 192 字节；三个有效范围保留，
buffer no-map、logo/LUT 与 initrd 起止地址均已在 Linux 运行树中重新读取。
设备标识在公开摘录中脱敏，完整 raw 仅保留于忽略的 private。

## Linux 实测范围

原样命令与输出见 [linux-runtime-check.txt](linux-runtime-check.txt)。

- `uname -r` 与源码 Image release 一致，PID1 为 `/bin/sh /init`；串口交互正常。
- 挂载只有 rootfs/devtmpfs/proc/sysfs/tmpfs；没有持久化块文件系统挂载。
- eMMC 枚举为 `mmcblk0`，16 个分区可见；未验证 Linux 文件系统读写。
- `0-001c` 绑定 fan53555-regulator、`0-0020` 绑定 rk808。
- `rockchip-iodomain` 绑定 `fdc20000.syscon:io-domains`；初次查询误写 `rockchip-io-domain`，后续已用正确名称核对。
- TSADC/rockchip-thermal 已绑定，soc/gpu 温度约 37.222→36.111℃。
- 最后一次 uptime 为 199.19 秒，仅覆盖短时空闲运行；未测长时稳定性、实时延迟、休眠或业务负载。

PMIC/TCS/IO 域等驱动 probe 会操作硬件寄存器，本次不是零硬件写入。
sysfs `microvolts` 是驱动声明/寄存器 selector 换算，不能当成万用表测量。
尤其 `vcc_ddr=500000` 对应 RK809 DCDC3 selector 表；原树没有 `fb-inner-reg-idxs`/DDR 电压约束，
驱动缺省走外部反馈意图且存在未初始化变量打印，不能推断 DDR 物理电压为 0.5V。
没有为消除日志猜填 DDR 电压或切换内部反馈。

## 已观察到的警告与后续处理

短窗口未匹配 Kernel panic/Oops/BUG/Call trace，不代表无警告或长期可靠。
以下是锁定源码与实际配置分析，修改方案尚未重新构建/上板：

| 日志 | 已确认原因/下一步 |
| --- | --- |
| RGA iommu bind failed | DT 未启用 RGA，但继承 MULTI_RGA=y 的 late_init 仍执行绑定；最小首启配置应去掉该驱动，不能为消除日志启用硬件 |
| SCMI protocol 17/22 not active | 分别是 power-domain/reset，当前 DT 仅描述 clock protocol@14；不能据此断言 BL31 不支持，先去掉本轮不用的 SCMI 子驱动 |
| RK817 battery/charger/codec 无 of_node | RK808 固定 MFD 子设备仍创建；继承 CHARGER_RK817=y 继续 probe。禁用部分主驱动不等于 MFD 子设备完全移除 |
| PMIC 缺反馈属性/随机 inner 打印 | rk808.c 未初始化局部变量，缺属性返回 -22 后打印；先修正错误诊断，保留原机反馈策略，实际反馈电路仍需证据 |
| FIQ/wakeup/NMI 可选 IRQ 缺失 | irq-mode=1 使用常规 IRQ 路径且串口已可用；不盲改 TrustZone/FIQ 模式 |
| regulatory.db 缺失 | 本轮 RAM 包不含该文件，SDIO Wi-Fi 未启用；后续网络阶段补齐来源和版本 |

原样警告摘录见 [boot-excerpt.txt](boot-excerpt.txt)。这些不是外设通过验收的证明。

## 返回原机与当前状态

确认 RAM-only mounts 后请求 `echo b > /proc/sysrq-trigger`；捕获 U-Boot → 原 4.19 内核 → Android11，
boot_completed=1、root shell 可用，五个启动分区 SHA 一致。
这是即时复位验证，未覆盖普通 reboot/device_shutdown、MCU ACK、看门狗交接或物理断电。
本轮 UART0、I²C5/MCU 与运动节点未启用，未发送执行器命令。

Android 最终摘要采样为电量 58%、7536mV，AC/USB powered=false；之后网络诊断期间仍在放电。
printk=`7 4 1 7`、kptr_restrict=2。串口已关闭释放，系统留在原 Android。
返回后网络 ADB 连接超时；串口确认 adbd=running、监听属性5555、wlan0 有 IPv4，
板端路由器 ping 2 次全丢。没有改代理、重复重启或将问题归因于某一个未经验证因素。

## 记录与复核

- [result.json](result.json)：动态实机结果、产物指纹、启动分区与 private 原始证据摘要。
- [record-results.py](record-results.py)：先核对本次实际 raw/产物，再生成结果与脱敏输出；没有 private 输入时不能重跑，不会代替板测。
- [verification.txt](verification.txt)：本次离线复核结果。
- 私有目录：实际 bdinfo、FDT、完整串口流、原机标识与 DTB 构建输出；不随公开材料分发。

没有 saveenv、启动分区刷写、提交或推送。准备阶段在 Android 新建普通文件；Linux 只使用 RAM 根目录。
下一阶段先整理最小内核配置与确定性告警，再将已有源码诊断/持久化用户空间迁移到此源码内核，
按原 Android 基线恢复 Wi-Fi、音频、输入与显示；MCU 查询、应答、停止和电源生命周期独立推进。
