# Android → 原内核 Linux：迁移与验收顺序

当前目标是复用原 4.19.232 内核和配套运行设备树，先建立可读写的 Linux 用户空间。
驱动绑定、动态库依赖、实际功能分别验收；本轮没有把“文件存在/已加载”写成“功能通过”。

2026-10-03 后续要求：最终系统应可公开重建，优先消除厂家定制黑盒。
下表保留原 4.19 对照路线；涉及库的下一步优先选择完整实现源码及独立替代，
不把取得 Linux 版预编译库当作开源完成。最新顺序和缺口见[源码审计](../rk3568-open-source-audit-20261003/README.md)。

| 项目 | Android 基线 | 本轮独立 Linux | 下一项验收 |
| --- | --- | --- | --- |
| 用户空间/存储 | 同一静态 AArch64 BusyBox 在 chroot 运行；标记卸载重挂后一致 | 64 MiB ext4 文件供 chroot 使用；Android/Linux 标记往返与 SHA 一致 | 选择正式 rootfs 介质，设计真正的 PID1/root 切换 |
| Wi-Fi | 实际加载 bcmdhd；SDIO function 1/2 绑定 bcmsdh_sdmmc；固件 7.45.96.150 | 原 ko 载入；两份原固件读取成功；wlan0 为 UP/LOWER_UP；卸载模块成功 | 准备 Linux wpa_supplicant，再验证关联、DHCP、双向小文件和持续传输 |
| NPU | renderD129 对应 fde40000.npu；Android 已有 librknnrt 进程映射 | renderD129 绑定 RKNPU，driver v0.7.2，load 0% | 先在 Android 跑可重复的小模型基线，再选与该驱动兼容的 Linux runtime；核对输出与性能 |
| RGA | Android librga 实际进程映射；库依赖图形 HAL/HIDL | 本轮只保留原内核，未做 RGA 任务 | Android 合成图像基线 → 匹配 Linux librga → 校验逐像素结果 |
| MPP | Android libmpp 实际进程映射，ELF 依赖 liblog 等 | 未做编解码功能测试 | 小文件 Android 解码/编码基线 → 对应 Linux MPP → 输出与设备错误核对 |
| ISP/相机 | rkisp 子设备及 video4–12 枚举；librkaiq 的 Android 依赖已检查 | 同组 ISP/DPHY/video 节点出现，未采帧 | 先核实传感器/media 拓扑及原 IQ 配置；Android 固定输入/光照基线，再做 Linux 采集 |
| 音频 | Bothlent UAC Dongle、rk809-codec 两张声卡 | 同样两张声卡枚举 | Android 确认声卡/路由/格式后，Linux 分别验证录音和播放 |
| MCU/输入 | I²C5-0062=McuCom；5-0015=gsensor_mxc6655；SPI3.0=cap1188 | 三项绑定相同；ttySMT0 节点存在 | 先核对 MCU/GD32 接口与协议；只读查询之后才安排授权的执行器测试 |
| 电源生命周期 | 原厂 Android 重启回到系统 | 本轮完成清理后走普通内核 reboot；整板掉电/看门狗尚无测量结论 | 明确 MCU ACK、看门狗接管、异常退出与真正关机策略 |

## `.so` 的复用边界

[elf-metadata.json](elf-metadata.json) 只读取 ELF 头、动态依赖表和模块元数据，没有回传整份 vendor 分区。
六个对象都是 AArch64；以下路径来自原 Android：

| 库 | 代表性依赖 | 普通 Linux 的处理 |
| --- | --- | --- |
| `/vendor/lib64/librknnrt.so` | liblog.so、libstdc++.so、libc.so | 换对应 Linux build，并核对 NPU 驱动 ABI；模型运行另验 |
| `/system/lib64/librknn_api_android.so` | liblog.so、libc.so、libdl.so | 不因文件名判断是否 JNI；需核对导出接口和 Linux 版本 |
| `/vendor/lib64/librga.so`、`/system/lib64/librga.so` | libhidlbase、graphics.mapper@4.0、libui、libc++ | 依赖 Android 图形栈，需 Linux librga 和正确的缓冲接口 |
| `/vendor/lib64/libmpp.so` | liblog.so、libstdc++.so、libc.so | 选与原 MPP 驱动接口匹配的 Linux build |
| `/vendor/lib64/librkaiq.so` | libutils.so、libcutils.so、liblog.so | 需要 Linux AIQ、板级 IQ 数据及配套 ISP 驱动 |

这些是 Android/Bionic 环境中的对象，不能直接视为 glibc/musl 动态库。
本轮没有盲目 dlopen，也没有把进程映射证据当作推理、编解码或采集正确性证明。
原 ko 的 vermagic 为 `4.19.232 SMP preempt mod_unload modversions aarch64`，本轮使用完全相同的原内核；
以后换内核时，不能继续用这一份 ko 的本次成功结论。

## 控制传输量

先收集节点、绑定、正在加载的模块、实际固件请求、ELF 依赖和最小功能基线。
只有下一项测试需要的模块、固件、runtime、配置和测试输入才进入迁移清单。
板内已有文件优先板内复制；每个文件以 SHA-256 核对，避免反复传输整份 Android 系统。
