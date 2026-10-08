# CAP1188 SPI：源码身份工具已上板，硬件身份未通过

2026-10-04，在保留加速度计缺口的情况下，独立推进触摸外设。原 Android 有 `cap1188_input`
八路按键接口；新源码 Linux 使用独立 SPI 设备树和 MIT 身份工具，真实执行三次身份事务。
产品号与厂商号均返回 `0x00`，不符合 CAP1188，停止初始化。未注册触摸输入或验证事件。
已经返回 Android 11/4.19.232/root；五个启动分区和两份已有 Linux rootfs 的完整 SHA 前后一致。
CAP返回收尾时实测电量30%，串口已释放。后续音频只读采集时为25%；当前连接和供电下轮重新检查。

机器结果见 [result.json](result.json)，厂商路径的有界静态结论见 [factory-audit.json](factory-audit.json)。
本轮只验证 SPI 控制器诊断通路与真实拒绝身份的结果；未形成可部署的整机 Linux。

## 为什么不把原 Android 的输入节点当作成功

原系统的 SPI3.0 绑定 `cap1188`，输入名称为 `cap1188_input`，key 位图 `3fc` 对应代码2～9。
新采集的 pinmux 显示 GPIO0_B6（设备树中的 reset）仍未被占用，SPI消息计数正常增加。
这说明软件接口注册了，并不能单独证明芯片响应、复位波形或触摸数据正确。

对精确原 Image 的14段符号及相关框架路径做了离线审查，原镜像与所选范围的反汇编/数据导出仅保存在私有证据中。
这里发布可核对的行为摘要，不把反汇编当作完整原厂源码：

| 审查到的路径 | 对开源重写的影响 |
| --- | --- |
| 配置100ms polling；八路映射代码2～9 | 保留可观察接口，触摸语义还需实物事件对照 |
| 每轮调用 init；十个两字节 raw SPI pair | 名称与数值不能证明它们是有效寄存器写，不能直接照抄 |
| raw read 分成两次 spi_sync，spi_sync返回码被忽略 | 新工具采用官方帧并传播错误、短传输 |
| 审查到的 probe/poll 未见 FD/FE 身份校验 | 必须先读身份，不能以驱动链接或 input 注册验收 |
| 同时变化时审查到的报告路径只发最后一个通道 | 后续驱动需逐位报告，尚未进行同时触摸实测 |
| remove 只打印、静态 g_spi 未清；框架存在 managed unregister/同步取消 polling | 不据此断言必然内存泄漏；卸载和并发仍须单独验证 |

厂商 reset 静态路径为输出0、等待100ms、置1、等待100ms、置0，input 注册先于 reset。
当前 Android GPIO 未占用，不能声称实物已经执行该序列。本轮没有解绑 Android 驱动或直接读其 SPI ID。

## 官方 SPI 协议与本轮工具

身份读取依据 [Microchip CAP1188 DS00001620C，§4.6、图4-7](https://ww1.microchip.com/downloads/aemDocuments/documents/OTH/ProductDocuments/DataSheets/00001620C.pdf)。
采用四线 SPI、mode3、8bit、MSB first、100kHz。每个寄存器使用一次连续 CS 的四字节事务：

```text
TX: 7D  register  7F  7F
RX: --  --        --  value
```

只取第四个返回字节。分别读取 FD（产品号，应为50）、FE（厂商号，应为5D）、FF（版本）。
版本变化不作为拒绝依据；本轮身份不符时没有输出版本值，不能把它填成00。
每个寄存器独立 SET ADDRESS，无扫描、重试、配置写、reset、Main Control 写或触摸状态读取。
通信可以影响硬件状态，不把“读身份”描述成完全无电气影响。

[cap1188-inspect.c](cap1188-inspect.c) 为 MIT 源码，固定打开 `/dev/spidev3.0`，核验字符设备 major153。
运行脚本再对照 sysfs 与节点的实际 major/minor；模式不符、短传输或系统调用错误立即停止。
`SPI_IOC_MESSAGE` 必须返回4字节；成功标记只在 close 成功后输出。
静态 AArch64 ELF 无 INTERP/NEEDED，646296 bytes，SHA：

```text
81c5cc528e9d22994e3230722fe050c8f866dce18715de86a422bd52081f34ff
```

本诊断不依赖厂家定制 `.so`。这不表示整板固件和所有业务依赖已经开源替换。
锁定树现有 cap11xx.c 是 I²C实现；通用 regmap SPI 的帧不符合上述协议。
后续需补独立 SPI transport、八路默认值/volatile 表、受控事件采样与清理流程，不能直接换 compatible。
本次源码 Linux Image 的 CONFIG_VT=y，注册 keyboard input 可能触发自动 open/poll；未来需明确采样门槛，
不能用“用户没有打开 event 节点”作为驱动未运行的证明。

## 设备树、构建与验证边界

新 DTS：`platforms/rk3568/boards/aiot-3568pq/bsp/rk3568-aiot-3568pq-cap1188-spi.dts`。
复用已板测 UART/RNG/Wi-Fi 基线及同一源码 Image、配置、ABI；本轮没有重建 Image 或加载外部模块。
锁定 kernel commit `9f9e9d18574d0914c0d192a90c3babfe1fd63c95`，源码树保持 clean。

SPI3 default 和 high_speed 都指向 M1：CLK GPIO4_C2、MOSI C3、MISO C5、CS0 C6，只有一个片选。
HS配置保留原板 pull-up/drive-strength1。仅启 SPI3 和 spidev 诊断子节点，使用此 BSP 实际支持的
`rockchip,spidev`；不虚构其他芯片 compatible。I²C5继续禁用，无 MCU、reset、IRQ或input注册属性。
控制器按父时钟选择 HS pinctrl，即使事务仅100kHz也可能切换；实际三次事务后已观察 `spi3-hs` 的 M1组。

最终 DTB v3：162562 bytes，CRC32 `2bc429db`，SHA：

```text
fdc469fc60abbb203bfa585232dfe9f0501c87340c534401183263ebc866acd4
```

保留760个旧 phandle、memreserve 和既有节点顺序；准确10个属性变化，151项审计、15个真实编译
坏DTB拒绝，零新增 DTC warning。`num-cs` 为原属性2→1，不是新属性。
v1为故意宽松审计的负对照；v2暴露继承审计恢复 num-cs 的分类错误；v3修正后通过并唯一上板。
这些失败没有执行板上写入或芯片操作。

| 验证 | 实际结果 | 证明边界 |
| --- | --- | --- |
| 身份 helper 主机 wrapper | 42项通过 | 真实 C 源码的帧、ABI、配置门槛、错误/close路径 |
| AArch64 QEMU wrapper | 42项通过 | ARM64编译/执行与模拟设备调用；不是物理SPI测试 |
| 错误第四 opcode 负对照 | 真实事务被 EPROTO拒绝 | 证明测试识别错误帧；不是42个独立生产缺陷 |
| 实际 stage 脚本 fixture | 18项通过 | ro,noload 参数、SHA/部分复制失败、退出清理与门槛 |
| stage旧cwd负对照 | 校验失败时逻辑挂载残留被复现 | 修正先 cd / 再 umount；未进行真实失败挂载试验 |
| 实际 reset guard fixture | 25项通过 | 非RAM挂载/loop/module、残留SPI/input/UART FD、进程及读取失败拒绝 |
| 精确 RAM BusyBox | 52 applets、依赖与语法通过 | 声明依赖检查，不是完整shell静态分析 |

host-checks-v1 因验证器使用错误 auditor 路径失败；修正路径及fixture字段名后 v2通过，
实机 ls 布局修正后的最终文件由 v3再次绑定验证。这属于验证器错误，不是芯片事务失败。

## 本次实机顺序与结果

1. Android 新采集输入接口、GPIO/pinmux及七份完整SHA；新目录普通 cache/data 文件暂存并读回SHA。
2. U-Boot重新检查启动链，从cache加载旧Image、新DTB、旧RAM initramfs；三段CRC一致。
   只在RAM清理两条旧Android initrd保留条目、设置临时bootargs，未saveenv或刷启动分区。
3. RAM PID1实际为 BusyBox `/bin/sh /init`，核验 exe/argv/ELF SHA。
   cache仅 `ro,noload` 挂载，复制输入到RAM、再校验并释放；debugfs也在读取后释放。
4. SPI3.0绑定spidev，设备号153:0；默认M1、CS1/reset未占用；输入仅有RK805电源键。
   最小 BusyBox 的 ls没有owner/group列，旧身份脚本的4/5列门槛会提前拒绝。
   未执行旧脚本或SPI事务；v2仅在RAM修正为实测3/4列，五份payload重新SHA全部通过。
5. 单次身份尝试使用原子mkdir占位；helper实际读取FD/FE/FF，返回产品00、厂商00、rc1。
   messages 0→3，errors/timeouts均0；UART0 TX/RX始终0，未碰电机/MCU。
6. 事务后M1 HS路径已确认。首次检查期望把HS误当组名后缀而失败，实际为function `spi3-hs`、group
   `spi3m1-pins`；停止后续步骤、显式释放debugfs，再通过返回门槛。没有重读身份或追加初始化。
7. 无module/loop/非RAM挂载、无helper/network进程或相关FD后，于349.427961秒SysRq返回原Android。
   捕获到首次DDR前的源码日志未见 WARNING/BUG/Call trace。Android11/4.19.232/root/boot_completed1通过。

SPI没有类似I²C地址应答的机制，消息完成和控制器零错误不能证明CAP1188存在。
全零可能与器件实装、供电、reset/接口模式、CS/MISO连线等有关；本轮未做电压或波形测量，未确定根因。
不能将“Android接口存在、Linux读00”直接定性为Linux驱动移植失败，也不能据此断言芯片未装。

五个启动分区 boot/uboot/trust/dtbo/vbmeta 与旧source/network rootfs前后完整SHA一致，
本轮两份raw均包含七项。这不是完整eMMC差分，也没有实测备份恢复。
新cache/data普通诊断文件保留；未switch_root、正常poweroff验收、提交或推送。

## 复现入口

在具备锁定源码、旧Image/ABI和UART基线的全新输出目录中执行：

```sh
python3 outputs/rk3568-cap1188-20261004/build-dtb.py --revision v3
python3 outputs/rk3568-cap1188-20261004/test-cap1188-inspect.py --label red-v2 --wrong-baseline
# 上条是故意错误帧的负对照，预期非零；确认其失败后再运行下面各条。
python3 outputs/rk3568-cap1188-20261004/test-cap1188-inspect.py --label green-v3
python3 outputs/rk3568-cap1188-20261004/test-cap1188-inspect.py --label green-v4 --aarch64-qemu
python3 outputs/rk3568-cap1188-20261004/build-inspect.py
python3 outputs/rk3568-cap1188-20261004/test-linux-stage.py
python3 outputs/rk3568-cap1188-20261004/test-return-guard.py
python3 outputs/rk3568-cap1188-20261004/check-runtime-commands.py
```

构建和记录目录拒绝覆盖；本机这些目录已经存在，不要原样重跑生成器或删除证据。
已有产物可用未使用的revision执行 `verify-host.py --revision v4`，增加独立核验记录。
它需要本轮已生成的runtime/stage manifest，并不产生新板测。
`record-result.py` 读取本轮私有raw证据与最终v3检查，核对前后指纹及身份拒绝，不能在新机器凭空验收硬件。

串口过程保留在 load-ram/boot-ram/linux-stage/runtime-v2/linux-enumeration/linux-identity/
linux-after-identity/return-android JSON 与实际脚本中。首次post检查失败的清理见
release-after-debugfs.json；已经修正的post JSON用于未来重查，不能冒称本次原始session直接通过。
这些是本机固定地址、端口、文件指纹的有界实验，不是通用自动刷机程序；新板重新核验各项再生成运行计划。

## 下一外设

CAP1188先核实触摸器件是否在当前连接的板/小板上，测供电、接口模式和SPI波形，再取得有效身份。
身份通过后才做八路配置、逐通道事件、触摸对照和完整采样/清理生命周期。
加速度计两系统ENXIO的缺口保留。可独立推进板载RK809音频的Android基线、codec/DAI/功放供电适配，
USB麦克风此前仅枚举；显示、摄像头、BT以及电机真实反馈、停止/使能/watchdog、正常电源生命周期仍未对齐。

后续只读音频基线与最小适配依赖已经归档到 [NEXT-AUDIO.md](NEXT-AUDIO.md)。
Android本次能注册RK809 PCM并读两个path controls，Linux现Image尚未编译codec；
原routing与锁定驱动DAPM节点不匹配，已定位源码失败路径，未生成新音频候选或进行播放/录音。
