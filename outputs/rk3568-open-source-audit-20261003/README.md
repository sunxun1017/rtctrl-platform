# RK3568 Linux 源码与厂商黑盒审计

最新实测补充：2026-10-04已重新编译公开5.10内核并启动；同一独立源码codec/PTY程序在Android和
源码Linux文件rootfs中均通过，持久化标记返回Android后回读一致。
后续RCU判断已修正，新Image一次同路径SysRq复位未再出现警告；已保存Wi-Fi重连后ADB/root/传输恢复，
长期网络稳定性、完整生命周期及真实执行器仍未验收。
见[源码用户空间记录](../rk3568-source-userspace-20261004/README.md)与
[RCU修正对照](../rk3568-rcu-reset-20261004/README.md)；以下2026-10-03审计和audit.json保留历史边界。

2026-10-03：用户要求最终 Linux 可公开构建，优先移除厂家定制黑盒；继续采用
“原 Android 功能基线 → 独立 Linux 对照”的顺序，控制传输量。
本轮完成静态接口、实际构建依赖及源码候选审计，没有运行未知 JNI/ioctl、发送电机命令或重启。

开源判定看实现源码、构建输入和许可证，不看 `.so` 后缀。自行编译的共享库可以开源；
将预编译算法装进 `.a`、内核模块或另一份 `.so`，仍然保留黑盒。
本报告记录替代入口与缺口，不代表所有替代实现已完成或功能已经一致。

## 厂家定制部分：先替换实际接口

Android 参考仓库锁定 commit `ed91ef7486cdebca00aa32d497f5aa45cb226c0e`。
本地相关 Java、Jar 与该提交按忽略 CRLF 的 Git diff 一致；该仓库没有找到 LICENSE/NOTICE/COPYING。
它用于理解协议和行为，不将其中原文件作为本项目 MIT 源码重新发布。

| 对象 | 本轮证据 | Linux 处理及未验证项 |
| --- | --- | --- |
| `libserial_port.so` | 参考库 ELF32 ARM，4820 字节；Java 仅声明 open/close/write/read，导入 termios/read/write 等 | 现有 `PosixSerialTransport` 可替代传输包装层；PTY/QEMU 已验，原板 UART 与 MCU 往返仍待验 |
| `smdt.jar` / `smdtserver` | `SmdtManagerNew.dev_*Uart` 经 `ISmdtManagerNew` Binder 调用服务；不是公开的底层 C/JNI 实现 | Linux 直接使用串口和独立协议库；逐项确认服务原来额外负责的配置、生命周期与错误语义 |
| GD32 动作协议 | 已有独立 `rtctrl_patchx_codec`；发送封帧、长度和 CRC16 有参考证据 | ACK、单位、限位、使能、停止与 watchdog 尚不明确，不能把编码成功等同于运动可用 |
| I²C `McuCom` | 原机 `i2c5-0062`，兼容串 `smdtmcu,STM8S00K3`；独立 Linux 已枚举原驱动 | 与动作 UART 分开；原 `mcuinf.c` 对应源码未取得，需核清电源/看门狗契约后重写适配 |
| GD32/STM8 固件 | 目前只有接口和板级证据，没有对应固件源码 | Linux 主机侧开源不自动意味着 MCU 内部固件开源；固件重建另列后续工作 |
| `libmcuencryption-lib.so` | 本轮只回传 74864 字节；两个 JNI 导出；静态发现 `/dev/rjgt102`、`open(O_RDWR)` 和 `ioctl(fd,0,buf)` | 当前必要性未知，不能凭名字关联电机；先确认调用者、实际设备与用途，再决定是否需要替代 |
| `patchx-face` / `video_process` | 参考 Java 分别提供人脸初始化/检测/特征及视频包装；只有 32 位库，没有对应 C/C++ 源码 | 现有人脸预处理、对齐和匹配代码可复用，模型执行与原行为对照仍缺；不直接依赖原包装库 |
| `speekerid` | 参考 `SpeekerID` 声明模型初始化、特征及比较接口，未找到实现源码 | 单独定义声纹输入、预处理与特征契约；现有语音助手不等于声纹算法替代 |
| `ovrlip_bridge` | 参考 `OVRLipSyncJNI` 声明初始化/处理/释放接口，未找到桥接实现源码 | 区分桥接代码和底层口型算法；独立实现输出与动画接口，不由“库存在”认定可开源 |

已有实现与验证入口：
[串口适配器](../../adapters/transport/serial/src/posix_serial_transport.cpp)、
[协议验收](../../docs/verification-patchx-protocol-20260921.md)、
[PTY/QEMU 验证](../../docs/verification-pc-qemu-20260921.md)、
[电源生命周期](../../platforms/rk3568/boards/aiot-3568pq/POWER-LIFECYCLE.md)。

### `libmcuencryption-lib.so` 的具体观察

ELF64 AArch64，依赖 `liblog.so/libm.so/libdl.so/libc.so`，板端与本地 SHA-256 一致：
`326431c4ac33548ba48f87078abbd936c11c1e177f5e4e07d7ca9f6fc9de126d`。
导出 `Java_android_app_smdt_utill_McuJNIUtils_getEncryptionResult` 和 `getCustomerResult`。
前者反汇编显示会打开上述设备、调用 ioctl，并检查返回缓冲的状态；这只能证明代码含有硬件交互。
未调用它，也未取得相应设备 ABI，不能由静态分析宣称已完成兼容实现。

原 Android 快照中 `/dev/rjgt102` 不存在，运行树节点 `i2c@fe5c0000/rjgt102@68` 为 `okay`，
驱动目录存在但没有设备绑定。system_server、com.patchx_sys、com.patchx_main 的当时 maps
均未匹配此库、`libserial_port` 或 `libsmdt`。这不证明未来或其他进程不会加载。
参考 Jar 未包含 McuJNIUtils，其 `custom_getEncryptionResult(int)` 只是 Binder 封装，
尚不能与这个板上 JNI 库建立调用关联。

原参考应用主 ABI 为 armeabi-v7a，现场 main 应用同样为 armeabi-v7a，sys 应用为 arm64-v8a；
参考串口库与现场 64 位 JNI 库是不同对象。原二进制、参考仓库和反汇编只放在忽略的 `private/`；
不将内部密钥数据写入公开证据。接口分析用于独立实现所需功能，不用固定“成功”返回值代替实际硬件行为。
机器可读摘要见 [audit.json](audit.json)。

参考源码定位（相对于参考仓库的 `PatchX-Android-Main-C/app/`）：
`src/main/java/com/wcy/testserial/SerialPortUtil.java:10`、
`src/main/java/com/patchx_main/patchx/manage/DeviceManager.java:344`、
`src/main/java/com/patchx_main/patchx/manage/UpdateManager.java:240`。
普通动作走 ttySMT0/115200/8N1，升级走 ttySMT4，不能混用。
原弱 ACK 只查第五字节；`DeviceManager` 中 60 秒下发命令 14 的方法未发现调用，
部分版本/电量值为硬编码，不用于 Linux 的真实遥测验收。
人脸、视频、声纹、口型接口分别位于 `FaceEngine`、`ImageProcessing`、`SpeekerID`、`OVRLipSyncJNI`；
本轮仅确定声明和缺少源码，没有复现其算法或数值输出。

## 芯片相关依赖：源码候选与实际边界

| 组件 | 可以采用的源码路线 | 当前限制 |
| --- | --- | --- |
| 内核/设备树 | 已锁定 5.10.160 源码、板级 DTS、配置和构建补丁 | 5.10 Image/DTB 只完成构建，未上板；现阶段实机用原 4.19.232 二进制，未取得对应完整源码 |
| RGA | 本地 SDK 有 `core/`、`im2d_api/src/` 与 Apache-2.0 COPYING，可从源码构建 | 多平台源码候选，尚未匹配原 4.19 RGA2 驱动；官方 GitHub 的预编译发行本身不是完整实现源码 |
| MPP | 官方仓库有 codec/HAL/OSAL 源码，可编译 Linux 版本 | 需核对原驱动 ioctl、分配器与版本；具体文件许可分别记录，未做 RK3568 编解码板测 |
| 相机/ISP | V4L2 采集已有实现；USB UVC 可先走标准接口 | Bayer→ISP 需要实际 sensor/media 拓扑和调校；本地 RKAIQ 缺 AE/AWB 实现，CMake 回退到预编译 `.a`，重新编译外层仍有黑盒 |
| 推理 | 增加真实的开源 CPU 模型执行后端，并确认模型输入/输出及原始模型来源 | 当前生产后端只有 RKNN；CPU 图像转换/后处理和测试 Fake 都不能替代模型执行；RKNN runtime/Toolkit 尚非完整开源实现 |
| Wi-Fi | 主机驱动有公开源码，关联/DHCP可用 Linux 网络组件 | 现有实测是原 ko/固件复用；驱动源码重建、Linux 关联/传输未验。芯片固件许可与源码另记 |
| 启动链 | U-Boot 与 TF-A 有源码，当前 TF-A 已提供 RK3568 平台 | 官方 RK3568 构建仍使用 rkbin DDR TPL；原 BL32/TEE 服务需求与替换可行性未核清 |

本地多平台源码候选来自 RV1126B SDK，不移用该板的功能验收：

| 候选 | commit | 已确认内容 |
| --- | --- | --- |
| `external/linux-rga` | `03499e8f2a5f5143812000b24e9c4140e231acf4` | API 1.10.5，实现源码与 COPYING |
| `external/mpp` | `15bf88a0455f6a49426b793ca3b9e1f8e4b7ffb9` | CHANGELOG 1.0.11，Linux/Android 构建差异 |
| `external/camera_engine_rkaiq` | `91dee445c13770279e3ee90cd82bd278c5306f85` | v6.0x32.0、rk356x/ISP21 选项及 AE/AWB 预编译回退 |

源码候选见[重建设备树](../../platforms/rk3568/boards/aiot-3568pq/RECONSTRUCTION.md)与
[内核构建记录](../rk3568-boot-preparation-20260928/README.md)；原库 ABI 见
[ELF 元数据](../rk3568-persistent-linux-20261003/elf-metadata.json)。

上游资料（本轮核查）：

- [RGA 官方接口与 RGA2 兼容说明](https://github.com/airockchip/librga#readme)。
- [MPP 源码](https://github.com/rockchip-linux/mpp)及[具体文件许可](https://github.com/rockchip-linux/mpp/blob/develop/mpp/mpp.c)。
- [RKAIQ 官方源码/库分支说明](https://github.com/rockchip-toybrick/camera_engine_rkaiq)。
- [RKNN SDK 许可](https://github.com/airockchip/rknn-toolkit2/blob/master/LICENSE)与[内核驱动源码](https://github.com/rockchip-linux/kernel/blob/develop-4.19/drivers/rknpu/rknpu_drv.c)。
- [bcmdhd 源码](https://github.com/rockchip-linux/kernel/blob/develop-4.19/drivers/net/wireless/rockchip_wlan/rkwifi/bcmdhd/dhd_linux.c)。
- [U-Boot RK3568 构建](https://docs.u-boot.org/en/latest/board/rockchip/rockchip.html)、[TF-A RK3568 平台](https://github.com/ARM-software/arm-trusted-firmware/blob/master/plat/rockchip/rk3568/platform.mk)、[rkbin 许可](https://github.com/rockchip-linux/rkbin/blob/master/LICENSE)。
- [OP-TEE Rockchip 平台](https://github.com/OP-TEE/optee_os/blob/master/core/arch/arm/plat-rockchip/conf.mk)，未锁定原 RK3568 BL32 对应实现。

[社区 RK3568 开源 NPU 实验](https://github.com/iav/rk3568-npu)作者报告在 ODROID-M1 上用
7.2-rc7 内核、局部驱动修改和特定 Mesa/Teflon 分支运行模型，无需 librknnrt。
该项目仍记录算子、舍入和链式执行限制；可作为独立研究路线，不能当成原 4.19 或本板的可用后端。

## 实际 CMake 依赖

默认 development 构建关闭视觉/RKNN/IgH，已有 release Ninja 链接记录未发现这些厂商运行库。
`modules/inference` 当前只有抽象接口和 tensor 实现；人脸 CLI 直接构造 RknnBackend。
`--frame-converter cpu` 只切换像素转换，不取消 RKNN 模型执行。

严格无厂商依赖的完整应用还需解决两处构建接线：

- `apps/face_recognition/CMakeLists.txt` 自动发现并链接 RGA/MPP；运行时选 CPU/OpenCV 不保证编译时不链接它们。
- `tests/CMakeLists.txt` 在 SDK 头可见时自动加入 RKNN mock 测试；它不链接真实 runtime，但仍使用 SDK 头。

现有标准接口包括 POSIX 串口、SocketCAN、V4L2 多平面采集和 companion 的 ALSA 工具调用。
V4L2 当前要求多平面 capture，不保证任意单平面 UVC 直接可用；本板录放音、采帧没有完成验收。
本轮未改应用/CMake，也没有用无关测试代替以上缺口。

## 接下来按这个顺序推进

1. 厂商接口先做功能清单：UART 配置/收发、MCU 只读查询、错误返回、关机/watchdog；每项记录 Android 的实际行为。
   确认哪些 Binder/JNI 是必需功能，哪些只是原应用包装；无需的组件不进入 Linux 装配。
2. 用已有串口与 codec 做 Linux 同输入对照；电机 ACK/限位/停止含义确认后再测动作。
   对确实缺少源码的接口，记录可观察契约并独立实现，公开代码不依赖原 Jar/.so。
3. 同时准备 RGA/MPP 的源码构建和合成输入基线；相机先查拓扑，避免先引入带预编译算法的 AIQ。
4. 定义真正的开源推理基线：CPU 模型执行、可取得的原始模型、输出误差和性能；RKNN 可作为显式可选扩展，不能承担无黑盒版本的必需功能。
5. 原 4.19 继续作为对照工具；公开系统转到源码可重建内核，并分阶段验收板级电源、启动和外设。
   发布清单分别列出代码、模型、配置和仍需的固件/loader，附来源、版本、许可证与构建步骤。

验收以行为一致为目标：固定输入、返回/输出、时序、错误与断线恢复逐项对照。
替换人脸/声纹模型后，特征向量和阈值可能变化；需验证或迁移原特征库，不能默认跨模型兼容。
当前没有新的厂商库替代板测结果，也没有“破解成功”或“完全开源整机”的结论。

## 后续实测更新：独立源码程序已跨系统通过

上文保留本次审计时的状态。随后授权继续完成了
[MCU 被动基线与源码对照](../rk3568-mcu-baseline-20261003/README.md)：同一静态 codec、
POSIX PTY 测试和新独立 MCU 缓存诊断在 Android/独立 Linux 中通过，不依赖厂家用户态库。
该缓存路径仍调用原内核驱动，没有取得真实 MCU 查询/ACK，也没有运动或电源生命周期验收。
原驱动 `skip-mcu` 分支及 65 字节缓存 ABI 见
[接口说明](../../platforms/rk3568/boards/aiot-3568pq/MCU-INTERFACE.md)。
此时的 5.10 候选尚未上板；各阶段的实际内核、挂载限制与收尾状态以对应记录为准。

## 2026-10-04 更新：源码内核已实机启动

锁定源码与明确补丁构建的5.10.160-rt89已经配合重建DTB进入独立RAM shell，
完成基础供电/IO域/温度绑定和内存保留区核对，再返回原Android，五个启动分区SHA不变。
这推进了上面第5项源码内核路线；原4.19继续保留作功能对照，不再把当前5.10状态写为只有离线构建。

本次没有运行厂家.so/Jar或业务服务；保留原DDR/loader/BL31等二进制，也没有完成电机、网络、音频、显示和推理验收。
动态结果与原始证据摘要见[源码内核首启记录](../rk3568-source-kernel-20261004/README.md)。
本目录audit.json仍是2026-10-03静态审计时的历史快照；最新板测结果独立保存。
