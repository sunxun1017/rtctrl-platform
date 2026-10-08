# Linux USB2 peripheral 离线候选

准确输入为已实测音频 Linux overlay 后的 `outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/applied-audit-only.dtb`，163285B/SHA `4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f`。这是 Linux 树，本任务不制作共享 U-Boot 树或恢复/刷写包。

`build/usb2-peripheral-v2/usb2-peripheral-1.dtb` 是真实锁定 libfdt 三次生成的同一结果，163303B/SHA `facc02a3157fffd52a5459c911ee962293848223c9eef86b05491a2e61e1dc10`。完整962节点/4887属性/762 phandle比较通过，只有7属性变化：usbdrd父、DWC3子和fe8a OTG port的status→okay；子dr_mode→peripheral、maximum-speed→high-speed、phys仅本树OTG0x28、phy-names仅usb2-phy。OTG #phy-cells为0。

真实 provider-cell 依赖审计闭包39节点，clock/reset/GRF/PMUGRF/power-domain15及PM QoS/supply/父节点等引用可解析；DWC3只有fe8a OTG USB2引用，必需路径在DT status层可用。所有其它节点、属性、phandle、reservation、启动CPU/版本字段保持，combphy、usbhost、其它PHY、供电、FUSB/BQ/chosen均未改。OTG vbus-supply/phy-supply继续absent。

原输入对新contract实际拒绝；29个真实二进制坏树全部拒绝，覆盖缺/错/未知PHY、旧双PHY、额外参数、错误名称/role/speed、三status、combphy/host/其它PHY、两supply、clock/reset/phandle/chosen/GPIO/provider #cells、reservation和坏FDT。Windows native另有22个纯semantic坏夹具，不混称DTB生成或DTC试验。

四次实际DTC（原/候选解码和往返）exit0，往返全语义保持。解码diagnostics路径归一化后逐字相同，各2699B警告。encode仅归一化源路径/行列后，完整诊断串只删除以下一行，其余内容、类别、节点、顺序保持，没有新增/改写：

`Warning (phys_property): /usbdrd/dwc3@fcc00000:phys: cell 1 is not a phandle reference`

这是反编译DTS用数字而不是符号引用造成的旧USB3 cell1警告；候选删除了该引用。初版要求encode全部相同而被拒绝，`build/usb2-peripheral-v1/failed.json`及完整原流保持；父任务明确认可v2仅允许这一个精确删减。没有静音类别，也没有修改诊断消息来伪装完全相同。

17份输入/旧USB闭包/真实5.10源码/原配置/实际工具均锁定SHA。native准备和Linux真实libfdt/DTC/负例分别记录；本任务Linux调用实际成功，但没有更改TUN、路由或WSL服务。没有写新PHY模型、kernel/config/公共patch、音频包或任何板/串口/ADB/网络操作。

accepted_for_board=false、usb_recovery_verified=false、physical_no_vbus_verified=false。DWC3允许缺usb3-phy为NULL，也允许缺usb2-phy为NULL，所以UDC不能证明PHY。DT supply absent不是物理无VBUS；PHY probe/ID/resume和regulator fallback仍可能开VBUS，DMO脚标识仍未知。配置与闭包检查不证明驱动probe、PHY lifecycle、电气连线、真正USB枚举/恢复、部署U-Boot或正式迁移。

复跑使用新的basename输出：`python3 outputs/rk3568-usb-device-20261006/build-candidate-v2.py --name independent-next`。旧结果和拒绝不覆盖；父任务另行决定最终整合与板测。
