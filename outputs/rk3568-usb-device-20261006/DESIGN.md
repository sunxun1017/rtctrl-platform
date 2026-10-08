# Linux USB2 peripheral 离线设备树候选

唯一输入是已实际音频 RAM 使用的 applied DT，163285B，SHA `4fb0a44df95a0a9e92216f38404201f118476c52ee8c117352d100eb9106995f`，准确文件为 `outputs/rk3568-audio-runtime-20261005/build/audio-ram-shim-v1/applied-audit-only.dtb`。它是 overlay 后的 Linux 树；本任务不制作共享 U-Boot 树、包或新 kernel/config。

白名单只有7属性：`/usbdrd:status`、`/usbdrd/dwc3@fcc00000:status/dr_mode/maximum-speed/phys/phy-names`、`/usb2-phy@fe8a0000/otg-port:status`。三个 status→okay，子节点 peripheral/high-speed，phys 必须只引用本输入树的 fe8a OTG phandle且按真实 #phy-cells 编码，phy-names 必须唯一 usb2-phy。完整节点、所有其它属性、phandle、reservation、启动CPU/版本字段保持。

combphy0/1、usbhost、其它PHY、供电/FUSB/BQ/chosen全部保持。OTG的 vbus-supply/phy-supply 必须仍 absent；这只是DT条件，不是物理无VBUS。真实5.10 DWC3允许usb3缺失ENODEV→NULL，高速支持；usb2缺失同样可NULL，不能用UDC存在证明PHY可用。PHY probe/ID/resume与regulator fallback仍可能开启VBUS。用户断电测得DMO接地，但它对应哪脚尚未知。

执行顺序：锁定输入/已有USB闭包与源证据；原输入对新contract红例；真实libfdt三次生成；全树白名单及phandle/provider #cells/父节点/clock/reset/GRF/power-domain依赖检查；原/候选DTC解码和往返诊断路径归一化后相同；有意义坏树（旧输入、缺USB2/wrongPHY/host角色/USB3/供电/host/其它PHY/clock/reset/phandle/chosen/reserve/坏头等）拒绝；最后绑定全部SHA并冻结。

若WSL正常启动失败，仅保留native已实际执行的快照/semantic夹具与失败输出，Linux libfdt/DTC结果留空；不重启服务、改TUN或伪造执行结果。本任务不建立PHY分支模型，不进行板/串口/ADB/网络操作，不以离线DT通过批准上板、USB恢复或VBUS状态。
