# 两个启动包的独立审查

2026-10-05，display_next_steps 独立只读审查，主控保存。原freeze29项、候选freeze38项长度/SHA及声明CRC全部一致；四个receipt/manifest与委派SHA一致。原40MiB包逐字节往返正确，两个包header ID/组件SHA1/填充/RSCE条目全路径/偏移/间隙/尾零通过独立解析。候选11名字/顺序与两原logo字节保持，9个RSCE DT和v2单DT都等于锁定UART，Image/initrd/rootfs精确绑定native3。

官方AOSP commit `99894068024224a62595e051d69e748e2499f52e` 的 [mkbootimg.py](https://android.googlesource.com/platform/system/tools/mkbootimg/+/99894068024224a62595e051d69e748e2499f52e/mkbootimg.py) 与 [bootimg.h](https://android.googlesource.com/platform/system/tools/mkbootimg/+/99894068024224a62595e051d69e748e2499f52e/include/bootimg/bootimg.h) 重新取回后与本地锁定源一致，builder真正调用write_header/write_data。不是只重新拼接旧包。原parser39/39、往返42/42、DT解码20/20；候选43/43、原包回归42/42、候选DT解码10/10。候选测试会真实改包且重算ID/资源hash以验证内容拒绝；最早1/38红结果含缺实现，不宣称37个旧语义bug。原freeze源快照保持，当前single-DT profile没有放宽原默认11-DT门槛。

## 部署版 U-Boot 直接二进制依据

输入是原uboot.img完整SHA `4758af21c8f5751cc92166baf7a6e4a79c17d0f87ce9bad64a16af91a125447e`；下列地址为FIT U-Boot链接地址，不能用公共Rockchip参考替代部署版事实。

- 0xa04804单地址Android hook，0xa0486c读kernel_addr_r、减page_size，加载RAM DT/搬移组件/启动；0xa047f0读fdt_addr_r，0xa2961c读ramdisk_addr_r。
- 0xa2991c→0xa297c4按环境内核地址处理RAM header，0xa282d0 getter读取处理后的地址或header之后原Image。原header字面重叠区不是本轮真实目的地；原包实测支持同链路。
- 0xa28ebc..0xa28f94把env bootargs与包cmdline拼接；0xa049d8合并chosen bootargs/bootargs_ext。候选boot前须临时覆盖env为manifest Linux串。UART chosen为console/rdinit=/init ro，没有冲突root/init/panic。fresh env bootargs_ext未定义，旧early FDT的boot_devices元数据不替代Linux串。

初次许可RAM试验的地址条件为kernel4MiB，Image内存范围 `[0x400000,0x25c0000)`；DT48MiB；initrd64MiB；完整包 `[0x20000000,0x22800000)`。DT48MiB已被下述第一次现场试验否定；后续采用新审查地址条件。临时环境不保存，真正地址/选择/Hash/最终cmdline仍需记录。不能从原包26/26推导Linux候选已通过，也不推导正式flash、early DT兼容或USB恢复。

## 新增 Android DT overlay 门槛

原包真实bootm日志还有 `ANDROID: fdt overlay OK`。主控要求独立补核原dtbo表/选中blob在锁定UART上的实际效果，完成前不执行候选bootm。此新增门槛不属于上面已经完成的包格式审查；结果后续单列，避免漏过booti与Android bootm的不同调用链。

新增审查已确认原dtbo不是空表：4MiB完整SHA59b971b4…5c8e57d，单entry0 offset64/size559，blob SHA `acf746c91caa230f7958ba2df4e6daf325881e7bce855657aa3b535f440dfec3`，其余尾零。仅chosen的bootargs_ext和reboot_mode六个mode，无供电/声音/屏幕/MCU/status节点。
但是原UART缺 __symbols__/chosen及chosen phandle，真实overlay需要这两个前提。标准libfdt失败后base magic会失效；进一步exact binary审查已证明本机U-Boot会备份并恢复，不能称损坏会遗留。0xa2b704..0xa2b724 malloc/memcpy备份，0xa2b740调用fdt_overlay_apply(0xaa5b90)，失败0xa2b7a4..0xa2b7b0恢复并打印failed，最终返回0；上层0xa0390c忽略错误。故继续启动不证明overlay成功。

另mode-bootloader从5242c301变5242c309、mode-fastboot从5242c309变5242c303，不能记为完全无语义变化。v1格式审查仍有效，但这个不同于booti的分支阻断其直接bootm验收。实际v1整包只载入/CRC核对，未启动。作者需新RAM专用DT版本、真实overlay离线apply和完整diff审查后重建候选，不覆盖已封存v1。

最小shim新增 __symbols__/chosen=/chosen 和chosen/phandle2f9（原max2f8）；仅symbol仍会NOTFOUND。真实apply对原UART的语义diff只准这两新增属性、bootargs_ext和上述两mode值共5项，其余节点/属性/旧phandle/chosen initrd/bootargs/memreserve保持。原memreserve(a100000,25000)/(a200000,c8c20)也不放宽。独立审查没有现成fdtoverlay，尚未执行apply，此项交v2作者真实红绿后再审。

## v2 独立审查完成

display_next_steps 对新冻结v2只读核验88项文件长度/SHA/声明CRC一致，receipt SHA
5a928d8c…dddfcf73、manifest a7532336…0b6e551；包41943040B/SHA67f351b8…af37dbe/
CRCcab15fb2。13个本地libfdt源与锁定源码一致，真实native直接apply独立复验：原UART及仅symbol
都-1、magic失效后完整backup restore；完整shim返回0，packed字节等于aadaba5c…审计DT。
这证明离线overlay缺口闭合，不假称本地libfdt就是部署版U-Boot的exact source。

独立全树核958节点/4859原属性：shim仅2新增，apply后严格5属性差异，旧phandle/memreserve/
所有status/供电/外设/chosen bootargs与initrd保持，normal5242c300。9RSCE+1v2 DT都等于
pre-overlay shim75c43a4b…61f582，绝非applied审计DT；原11资源名字/顺序和两logo保持，
header ID/资源hash/页块填充/尾零独立通过。实际测试3/3+39/39+45/45+10/10。

审查结论允许本次有界RAM bootm试验；前置为新鲜地址/保留区/临时env和全包CRC，现场必须
记录实际DT选择、overlay OK、目的地和最终cmdline，并检查最终FDT。未覆盖正式flash/saveenv/USB恢复。

## v2 包第一次现场试验：最终 overlay 未落入 Linux FDT

同一冻结 v2 包实测完整载入40MiB，RAM CRC `cab15fb2`，单次 `bootm 20000000`。
内核4MiB、initrd64MiB、FDT48MiB进入native PID1 v3；真实codec/PTY子进程结束并回收，
native return卸载旧根、解绑loop并卸载cache，七项独立RAM检查通过，普通reboot在
505.770366秒发生。随后Android11/4.19.232/boot_completed1/root，七个保护对象完整SHA保持，
电量62%→62%。这些结果只证明启动/退出链能运行，不代表该候选的最终DT通过。

完整live FDT163968B，SHA `6109dda4fa7460be615a9df127ca2fc2c420bc3148a15c5514472fb59228587e`，
161个1KiB片段及两端完整SHA一致。独立解析958节点、相对applied审计DT34项属性变化。
`bootargs_ext`缺失、bootloader/fastboot恢复pre-overlay值，normal保持；所有status保持。
串口先有overlay OK，随后第二次DT资源读取及FDT_DTBO重复分配错误。故首次apply成功
不能证明最终交给内核的树已apply。完整原始日志和含运行身份的diff留在pid1/private。

## 下一次地址修正的部署版直接分支证据

display_next_steps独立核验同一SHA部署版U-Boot及live FDT：首次加载
`0xa047a8→0xa03928→0xa0379c`使用`[x18+192]`的gd FDT，本板fresh为`A100000`。
`0xa29848→0xa29000→0xa283c8`的内核分离/校验路径随后比较地址：
`0xa28b44`取环境fdt_addr_r，`0xa28b50`取gd FDT，`0xa28b54`比较；相等时
`0xa28b58→0xa28b7c`成功并跳过重读，不等才`0xa28b5c→0xa0379c`再次读取/尝试overlay。
因此保持同一v2包，仅将临时fdt_addr_r恢复为fresh gd地址`A100000`进行下一次RAM验证。

地址审查包括内核及header`[3ff800,25c0000)`、initrd`[4000000,40ed5ab)`、
FDT实际工作区`[a100000,a12accc)`并保守检查`[a100000,a140000)`、包`[20000000,22800000)`。
旧A100000/25000 reserve是同一FDT用途，旧initrd`[a200000,a2c8c20)`不冲突；
U-Boot/栈`[eb7f85b0,f0000000)`不冲突。新轮次仍要独立读fresh gd/保留区、全包CRC及临时env，
确认没有第二次DT读取和重复分配，完整最终FDT须含bootargs_ext以及bootloader5242c309、
fastboot5242c303、normal5242c300。不能把进入PID1或单条overlay OK替代这项验收。
# trial-v3 最终闭环

同一v2包、临时FDT A100000已完成[71/71现场汇总](linux-candidate-result-v3.json)。
最终FDT完整163968B/SHA `25cc8ad86242311ee6dacd6a4685cda10f2d569f011b292b5ee2cf8f270e2e19`，
641小片段独立重组，首末板端SHA、实际raw和receipt相同。两次失败1KiB采集保持拒绝。
958节点/4891属性，相对applied审计DT无节点变化，31属性差异由私有身份3、chosen3、
显示handoff18、VOP6、memory尾部零长度项1解释；761 phandle、168 status保持。
chosen symbol/phandle2f9、bootargs_ext、normal c300/bootloader c309/fastboot c303全部保留。
内核setup_machine_fdt按fdt_totalsize独立保留整树，覆盖显式memreserve之后的128B尾部。

协议/PTY自检和自有子进程回收、原生回RAM/卸载/detach、独立七挂载guard、普通restart和新鲜Android
七保护输入完整SHA均通过，电量62→60%。普通restart时间1656.913338秒；请求至首DDR窗口无严重诊断。
第一次65/71拒绝保持，不以第二次成功回写过去结果。本节仅此RAM试验，不放行正式flash或USB恢复。
