# 新音频软件离线启动候选

今天已生成独立 RAM 启动候选 [package-v1](package-v1/manifest.json)，完整启动文件、五个声音运行文件、原根文件系统、实际新内核 notes、设备树和构建输入副本均已写好。完整文件读回与新的格式/输入拒绝检查通过；此目录不操作板子、分区、网络或 TUN。

| 产物 | 大小 | SHA256 |
|---|---:|---|
| [boot-raw.img](package-v1/boot-raw.img) | 40,482,816 B | d294173a44addf281ac23c47e440800fa0706aa0752f5ff44159b1670fd3db35 |
| [boot-padded.img](package-v1/boot-padded.img) | 41,943,040 B | 90e663bc12d33026764bf7b95ac6beede816801c6f7c2fb537615f28059dc0b1 |
| [新设备树](dt-v1/audio-shared-params-ram-shim.dtb) | 163,263 B | 85f09184db921d6cf4fe7fac9f209bcd69236085af391a263c830a87ce70449a |
| [配套声音模块](package-v1/runtime/snd-soc-rk817.ko) | 606,536 B | c43e470ccf7219bd344ba9d7315b38599f6b0eafb8a2ea6700eee34de9e13d85 |

填充后启动文件 CRC32 为 `4427a536`，尾部 1,460,224 B 全部为零。内核完整 SHA 为 `e2a5590fbde0a431a1a900c5fc9789d1e607af71a5300010e5431a2927ae3f61`，release 为 `5.10.160-rt89-g9f9e9d18574d-dirty`。原 initramfs 和 rootfs 完整字节保持一致。旧 PID1 的 RCU 内核检查不能作为这份新 Image 的身份；新身份另附 [kernel.notes](package-v1/kernel.notes)。

新树以旧实机音频 shim 为基线，仅在 `/i2s@fe410000` 与 `/i2c@fdd40000/pmic@20/codec` 增加空布尔属性 `rockchip,checked-shared-params-48k`。962 个节点、762 个句柄、全部其他属性和 reservation 保持一致。实际 CPU 源码按寄存器地址、TRCM=1 和禁止属性检查自动选择 checked profile；现树无 calibration/multi-lane/loopback 等排除项。现 simple-card 的 I2S、CPU master 默认、mclk-fs=256，以及 codec 的 12,288,000 Hz 时钟符合固定 48 kHz / S16_LE / 2 通道契约。48 kHz 和格式/通道限制由驱动执行，未伪造为新的 DT 属性。

SHA 锁定的实际 libfdt 已成功应用原 DTBO，完整语义只增加原 bootargs 扩展并修改原两项 reboot 模式。应用结果 [applied-audit-only.dtb](package-v1/applied-audit-only.dtb) 仅供审核；包内仍为覆盖前 shim。原 v2 头地址与系统字段保持，九份 resource DT 和一份 header DT 使用新树，两个原 logo 字节保持一致。临时 RAM 目标区间静态不重叠；旧头编码地址本身仍存在原有交叠，不能当作真实目标地址。实际板上内存、保留区、搬移地址与传输校验需重新核对。

证据在 [包构建执行](package-build-v1.json)、[格式审计](package-v1/audit.json)、[完整 36 文件清单](package-v1/receipt.json)、[完整读回](readback-v1.json) 和 [有限验证执行](finite-verification-v1.json)。9 项新 Image/codec 输入检查、15 项实际包格式/DT 拒绝检查，以及完整配对 DT 差异检查全部通过。旧未改 shim 的配对检查实际失败并保留；输入 gate 的初始失败来自 gate 尚未实现，不冒称为 Linux 驱动业务失败。

本工具逐字绑定实际新 [Image 构建收据](../build/root-audio-integration-v5/full-build-v1/receipt.json) 和 [canonical module 收据](../build/root-audio-integration-v5/canonical-codec-v1/receipt.json)，并检查 37 个已闭合导入、正确的 `snd_soc_rk817` 内部模块名、匹配 vermagic 与 2,020 项 generated 输入的生产者证据。它另行复核有限当前源/header/config/symvers 及全部所选包输入，未再次执行全源/generated 大清单审查。完整软件及独立审查接收证据为 [final-software-v1](../build/root-audio-integration-v5/final-software-v1/receipt.json)，SHA `06f4a1bcc80694893462c3326c9c4bbcc40b5725ede56006306b7b21dce9f0f3`。新增外部审查不会重写这份已生成包。旧 v5 production gate 未用于新候选验收。

主控随后另执行新 [回读 CLI](../build/root-offline-next-audit-v1/receipt.json)，实际退出0、stderr空，39项输入前后保持；36包文件及真实完整overlay一致。独立reviewer对实际包另重算完整SHA/CRC、直接解析组件/RSCE与零padding，并接受上述离线边界，未发现具体阻塞。[总接受记录](../REVIEW-NEXT-AUDIO-SOFTWARE-20261006.md)保存源码、实际构建与新包的范围，包内已生成文件保持原字节。

明天接好外设后，由主控重新核实 RAM 启动条件、live 新 Image/notes 与完整树身份，再验证双向声音传输、IRQ/FIFO 和参数所有权、正常关机/卸载、实际收音发声，以及返回 Android 后保护分区相等。这里的 `board_tested`、`START_authorized`、`full_duplex_passed`、`formal_flash_ready` 均为 false；旧 v5 实机通过不继承给新代码。屏幕、耳机、喇叭和电机未连接的实测，以及电池未知参数和 USB 恢复入口，仍由主控总验收单登记。

需要复现封装时，在项目根目录运行下面的离线命令，并指定未存在的新输出名称；它不会执行板上启动：

```sh
python3 -B outputs/rk3568-audio-runtime-20261005/offline-next-delivery-v1/offline-next.py package --out package-v2
```
