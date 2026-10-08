# USB 恢复依赖的离线核查

本轮没有修改任何 USB status、供电、GPIO、PHY，也没有操作板卡。用户仅报告板上 `DMO` 标记在完全断电时对地接近 0Ω；该标记对应哪个脚尚未确认，不能据此确定 USB D− 短路，或验收 USB 恢复可用。

输入是原实际 RSCE entry6 `rk3568_smdt_3568a_v20.dtb`，148217B，SHA `83aa4a285dbc8bff3ae3a72a14e371faa54e7598808c4c6ace2834aeb9c9f956`；候选是本目录 `build/emmc-v1/audio-emmc-compatible.dtb`，163181B，SHA `cb3028a4dab33596532557ef59ea8fc99d1517c2474f2816900238ce53cdd279`。

`audit-usb-closure.py` 按每个 provider 的真实 `#clock-cells`、`#reset-cells`、`#phy-cells`、`#power-domain-cells` 解数组，解析 supply、GRF、PMUGRF、父节点及适用的 GPIO/pinctrl 引用，并由 domain15 参数定位 `pd_pipe@15` 描述，继续解析其 clock 和八个 PM QoS 节点。最新实际结果为原树 42 个节点、候选 41 个节点；这组被解析的图引用全部能解析到节点。依赖图和完整归一化差异保存在 `build/usb-closure-v3/`。v1 未纳入 PMUGRF，v2 尚未展开 domain 子节点，都保留为旧证据，不作最终闭包依据。解析到节点不证明其驱动已探测，图的 status 判断也不证明电气状态。

| 路径 | 原 Android | 当前候选 | 依赖和后续条件 |
|---|---|---|---|
| `/usbdrd`、`/usbdrd/dwc3@fcc00000` | 父子均 okay；otg | 父子均 disabled；仍为 otg | CRU clock ID166/167/165/127、reset148、power-domain15 相同；子节点同时引用 USB2 OTG PHY 和 combphy0(USB3 type4) |
| `/usb2-phy@fe8a0000/otg-port` | okay，vbus-supply 指向原 OTG regulator | disabled，无 vbus-supply | PHY 父节点、PMUCRU clock19、USB GRF 仍在且 okay；供电节点和引用须单独恢复/审核 |
| `/phy@fe820000` | okay | disabled | combphy0 是当前 DWC3 `usb3-phy`；clocks PMU31/CRU380/127、reset452/453、PIPE GRF、PHY GRF 均归一化相同 |
| `/vcc5v0-otg-regulator` | 5V fixed；vin-supply→vcc5v0-usb | 整个节点缺失 | 原树没有 GPIO 字段，也没有 boot-on/always-on；不能自行添加一个猜测的输出脚或沿用旧数字 phandle |
| `/usbhost`、`/usbhost/dwc3@fd000000` | 父子均 okay；host | 父子均 disabled；仍为 host | CRU169/170/168/127、reset149、domain15 相同；USB2 引用 fe8a host-port、USB3 引用 combphy1 |
| `/phy@fe830000` | okay | disabled | combphy1 clocks PMU34/CRU381/127、reset454/455、GRF 依赖相同 |
| `/usb2-phy@fe8a0000/host-port` | okay，phy-supply→host regulator | 相同 | 已存在，供电图闭合到 vcc5v0-usb→dc-12v；只是 DT 描述，未做本轮电压测量 |
| `/usb@fd800000`、`/usb@fd840000` | EHCI/OHCI okay | 仍 okay | 两者引用 fe8b otg-port，当前该 PHY port disabled，因此不能把这两节点 okay 视为链已经可用 |
| `/usb2-phy@fe8b0000/otg-port` | okay，phy-supply→host regulator | disabled，无 phy-supply | USB2 第一对 EHCI/OHCI 若恢复，需一并恢复对应 port 和原 supply 引用 |
| `/usb@fd880000`、`/usb@fd8c0000` | EHCI/OHCI okay | 仍 okay | 引用 fe8b host-port，该 port 保持 okay 和原 host supply；未据此验收实际接口 |

原供电链的 `vcc5v0-host-regulator`、`vcc5v0-usb`、`dc-12v` 在候选仍存在；电压、boot-on/always-on 及归一化 supply 关系相同。旧 phandle 与新树 phandle 不同，图按 provider 路径和参数比较，不能直接复制旧数值。

Linux 实际源码与当前 `.deps/kernel/aiot-3568pq-audio-v1/.config` 表明以下驱动均内建：DWC3/DUAL_ROLE、DWC3_OF_SIMPLE、XHCI_PLATFORM、EHCI/OHCI_PLATFORM、PHY_ROCKCHIP_INNO_USB2、PHY_ROCKCHIP_NANENG_COMBO_PHY、CPU_RK3568。

`drivers/usb/dwc3/dwc3-of-simple.c:173` 的表通过父节点第二项 `rockchip,rk3399-dwc3` 匹配；probe 在打开父时钟后 `of_platform_populate` 创建子节点。`dwc3-rockchip-inno.c` 的表只有 rk3328，它虽然内建，但不是这里两节点的匹配对象。`drivers/usb/dwc3/core.c` 的 `snps,dwc3` 表匹配子节点，实际会取得并初始化 `usb2-phy` 与 `usb3-phy`，之后按 role 创建 host/gadget。不能把设备树上的 `quirk-skip-phy-init` 理解为整个 DWC3 不碰 PHY：该属性由 `drivers/usb/host/xhci-plat.c:363` 消费，控制 HCD core 的 PHY 管理；DWC3 core 仍调用 PHY 初始化/供电。

USB2 PHY 表在 `drivers/phy/rockchip/phy-rockchip-inno-usb2.c:4118` 的 CPU_RK3568 分支识别 `rockchip,rk3568-usb2phy`；它会用 GRF、phyclk，遍历可用子节点并创建 PHY。OTG port 的 `vbus` regulator 在该文件2152附近取得，设备角色路径会关闭 VBUS，host/ID 状态路径可能打开 VBUS；没有 supply 时并不等价于电源没有驱动能力。普通 `phy-supply` 则由通用 `drivers/phy/phy-core.c:901` 取得。NANENG combphy 在相应源文件1291表匹配 RK3568，使用三个时钟、两个 reset 和两个 GRF；当前候选关闭的两个 combphy 不能只靠开启控制器绕过。

这些供电操作是源码中的 regulator 调用；原 OTG fixed regulator 没有 GPIO 控制字段，不能从调用成功断言实际 VBUS 已被关闭。PIPE domain15 的 clock127、八个 PM QoS 路径和 MMIO reg 在两树归一化相同；这也不代替实际 domain 电源切换测试。源文件、当前配置和带行号范围的摘录已保存于 `build/usb-source-v1/`。

部署 U-Boot 已确认的 dwc3-generic-wrapper、RK3568 USB2 PHY 匹配及早期 DM 来源沿用主控 `../rk3568-boot-package-20261005/FORMAL-EARLY-REVIEW.md`，本任务没有重复完整二进制分析。USB3 combphy 的本机 U-Boot 实际调用分支、恢复命令是否采用 USB2-only/跳过 USB3 PHY，不在该既有结论中；须再核具体恢复路径，不能用公开 U-Boot 源码当作本机事实。

继续恢复时可分开以下最小明确范围，尚未生成启用候选：

1. 若保持当前 OTG 两 PHY 描述，须开启 `/usbdrd` 父、DWC3 子、fe8a OTG port 和 combphy0；恢复原 OTG 5V regulator 的已知字段，以新树可用 phandle 接上 vin-supply/vbus-supply。保持 role/quirk/供电行为不变并不自动保证安全，先核实际接口的 VBUS/ID、驱动 lifecycle 和部署 U-Boot 恢复路径，再真实验证。
2. USB device 恢复不要求同时开启 USB3 host、两组 EHCI/OHCI 或 combphy1。若决定 USB2-only，应另审改变 `phys`/`phy-names`/`maximum-speed` 与部署 U-Boot 取 PHY 方式，不能在这一候选中顺带推断可删 USB3 依赖。
3. 若另需完整恢复原 host 描述，USB3 host 的父子/combphy1 三个 disabled 状态需配套；第一对 USB2 EHCI/OHCI 要恢复 fe8b OTG port 和原 host supply；这些与 device 恢复分项验收。
4. 当前 Image 的驱动是内建的；共享 DT 打开早期 U-Boot节点，也会激活 Linux 对应链。若需先只验证早期恢复，应先准备并审核不启用这些 Linux 驱动的独立 Image，或明确、可验证的 early/late 分离机制。原 RSCE 加单个 late DT 不能天然分离，既有实机证据已确认。

候选缺少原 Type-C FUSB302 节点的板级描述；它没有出现在当前 DWC3/PHY 的直接 phandle 图中，本任务不把它擅自纳入恢复必要条件，也不假定真实连接器和角色检测已确认。没有 SD 卡座、未知 DMO 引脚、尚未演练的 USB 恢复，都仍限制正式迁移验收。eMMC 的一次兼容串追加不补齐这些条件。
