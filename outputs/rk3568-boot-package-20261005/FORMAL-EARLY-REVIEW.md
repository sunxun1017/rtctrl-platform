# 正式启动的早期 DT 与分区入口

2026-10-05，display_next_steps独立只读部署二进制审查，由主控保存结论。
输入uboot.img完整SHA `4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e`；
地址是部署FIT内U-Boot链接地址，不以公开next-dev源码代替本机事实。
当前v2包仅RAM试验，不可直接用作正式boot包。

FIT自身控制DT14285B之后，board_init `0xa04480→0xa05030`读取板级资源DT；
`0xa050f8`替换gd DT并重建DM。原实际选择RSCE entry6 `rk3568_smdt_3568a_v20.dtb`，
148217B/SHA `83aa4a285dbc8bff3ae3a72a14e371faa54e7598808c4c6ace2834aeb9c9f956`。
CLI在这些步骤之后，已有RAM试验保留了原早期DM，不能证明替换资源后的早期初始化。

原RSCE加v2单Linux DT不能自然实现early/late分离。真实component=4分支 `0xa28b3c`，
`0xa28b54`比较env fdt_addr_r与gd；相等复用，否则`0xa28b5c→0xa0379c`重读RSCE。
v2 DT组件参与SHA1校验，但不替代late资源来源。新的分离机制若有，需要另外实现和验证。

共享DT可先做有限兼容增量：保留Linux首项`rockchip,rk3568-dwcmshc`，追加原
`snps,dwcmshc-sdhci`。当前UART仅两个Rockchip串，部署表没有匹配；部署driver `0xb210d0`、
oftable `0xae93f8`、probe `0xa4f198`识别snps，Linux实际sdhci-of-dwcmshc.c先匹配rk3568。
不能只看控制器基址相同就说早期eMMC仍可用。独立归一化比较eMMC五个CRU clock-ID、
PMIC I2C两个PMUCRU clock-ID及OTG clock/reset-ID相同，PMIC regulators77项电压、
boot-on/always-on/suspend字段相同。保留依赖，不能复制旧数字phandle。

原OTG/host父子okay，当前候选disabled；部署存在dwc3-generic-wrapper、RK3568 USB2 PHY匹配。
恢复早期节点还会使当前Linux内建DWC3 dual-role/XHCI启用，因此须另审USB/PHY/供电闭包，
或准备Linux控制器不启用的新Image；不能仅改status就验收恢复。
用户只确认板上DMO标记断电对地接近0Ω，引脚身份未知；USB恢复仍未证实。
MCU和未知执行器仍可独立保持disabled。

默认地址存在另一实际搬移分支：`0xa04538..54`把text_offset=0的5.10入口由默认280000向下调至200000。
`0xa04968..0xa049c0`读取kernel_addr_r并调用overlap-safe memmove `0xac1f6c`，复制images->os.image_len。
旧Image复制span200000..2325200，header image_size35389440占用至23c0000；4MiB试验没有覆盖它。
可另做fresh默认地址及不手工bootargs覆盖的RAM试验，核包cmdline与最终树；新Image须重读header，
这仍不验证正式早期DM或分区加载。

默认bootcmd为boot_android，handler `0xa08efc→0xa2b85c`读取misc/boot/vbmeta，
还有清BCB命令的条件写分支，不能当只读RAM文件替代入口。可选地址是目的地。
编译ramdisk-ro读物理LBA，无base、capacity0，尚无可用cache模拟介质证明。
原vbmeta NONE、无descriptor、flags2，原日志仍走AVB；不需要据此修改vbmeta或解锁。
trust.img全零，ATF/OP-TEE实际在U-Boot FIT内，trust备份不等于独立恢复固件。

下一步另立共享DT候选、核真实驱动匹配/依赖闭包，并单列默认地址RAM验证。
完整上电候选早期DM和正式分区入口还没有已验证的无持久写入路径。
未操作板、写分区、保存环境或扩展USB恢复结论。

## recovery 路径的新增核实

同日独立检查部署二进制确认：recovery 不会自然保留原 boot 的早期资源 DT。
早期 resource 路径 `0xa077a0→0xa05db0→0xa056f8` 的 mode1选择 recovery。
Android resource 路径 `0xa075b4→0xa06f40`先读boot header，`0xa0700c`解析mode，
mode1在`0xa0701c`释放boot header、`0xa07050`查GPT recovery并在`0xa07060`重读header。
`0xa07110..0xa0719c`由所选包的page/kernel/initrd计算second RSCE；后续板级DT选择、
hash、overlay及gd/DM均来自所选recovery包。因此换recovery也要验证新的早期DM。
正式`boot_android`的`0xa2b974..0xa2b9a8`另选择recovery并进入AVB。

模式来源包括reboot_mode recovery/recovery-key/recovery-usb、misc BCB boot-recovery和
syscon `5242c303`。寄存器复位为normal不等于本轮已缓存mode失效，也不保证自动回Android。
旧2026-10-03 misc空BCB仅是历史证据，不能代表当前状态。
GPT主/备header及entries CRC通过、entries字节一致、16分区有效；无独立resource分区。
recovery为p10，LBA665600..862207，96MiB；boot为40MiB。

主控同日只读备份recovery `100663296`B，完整SHA
`a94f4e7f0180844aa9ec67253276879f7407c9a85d2138c7636d764048890933`，
板端备份前后SHA相同。legacy exec-out在完整二进制后合并86B dd统计，原严格大小检查拒绝的
流与v1 receipt完整保留；v2只提取全SHA匹配的96MiB前缀，再新鲜核原Android及七保护输入。
证据：[完整备份](../rk3568-backup-linux-20261003/recovery-backup-v2.json)。
已有备份不证明USB恢复入口可用，也不放行正式分区替换。
