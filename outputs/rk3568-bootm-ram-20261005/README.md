# 原包与 Linux 包的 RAM bootm 实测

同一v2包又完成默认目的地试验：[50/50现场汇总](default-address-result-v2.json)。
没有手动覆盖bootargs/kernel/fdt/ramdisk地址，仅临时设置两个high限制。
部署U-Boot实际将kernel从280000搬至200000；header image_size35389440，对应有效末端23c0000。
FDT保持gd A100000，initrd A200000；一次资源DT读取与overlay成功，没有重复分配。
Linux cmdline收到包内参数并保留原环境和overlay metadata，完整FDT只取得大小168064与SHA见证，
另核chosen子集；本轮没有完整导出或全树语义验收。
native3自检、原生回RAM、独立guard和普通reboot均通过，原Android七保护SHA一致，电量37→36%。
v1汇总仅因漏识别实际“=>”命令前缀为49/50，原拒绝结果与旧审计源码保持；修正解析后5项回归通过。
仍不证明新早期DT、正式分区启动或USB恢复。

Linux v2包的第二次实际试验（trial-v3）已经完成最终设备树、原生PID1运行与退出、
普通重启和返回Android的[71/71项汇总](linux-candidate-result-v3.json)。
同一40MiB包 SHA `67f351b8…af37dbe`、CRC `cab15fb2`，只将临时FDT目的地恢复到现场gd地址A100000；
kernel4MiB、initrd64MiB，没有保存环境。最终树完整读回163968B，SHA `25cc8ad8…270e2e19`，
独立审查958节点/4891属性，overlay所有目标值保留、761 phandle与168 status保持。
[完整树审查](live-fdt-review-v3.json)和[采集绑定](live-fdt-binding-v3.json)保存实际输入。

原生只读根运行协议/PTY自检exit0并回收自有子进程；自行回RAM、旧根卸载、loop detach和cache卸载，
独立七挂载guard通过，没有手工补链接或改guard。普通重启在1656.913338秒达到Restarting system，
随后DDR和原Android11/4.19.232/root/boot_completed1；七保护输入完整SHA相同，电量62→60%。
请求至首DDR窗口无WARNING/BUG/Call trace/Kernel panic，不能推广到其他诊断或关机。

第一次Linux v2试验（trial-v2）虽进入Linux并返回Android，最终overlay丢失，
[65/71拒绝结果](linux-candidate-result-v2b.json)保持。部署版U-Boot第二次DT读取由不同FDT地址触发，
trial-v3按实际分支避免该读取，详见[分支和失败记录](BOOT-PACKAGE-REVIEW.md)。
两次不完整1KiB串口采集均拒绝，成功采用641个256B或尾部128B片段并核全SHA，不补猜失字。

以上仅证明当前CLI可达、原早期启动输入仍在的RAM试验。正式启动包的早期DT、USB恢复、
声音DMA/生产服务、实物屏幕声音和MCU契约仍有工作；没有flash、saveenv、提交或推送。

2026-10-05，原40MiB包从缓存普通文件加载至 `[0x20000000,0x22800000)`，全包CRC `6e48ba06`。单地址 `bootm 20000000` 已成功进入原 Android11 / Linux4.19.232 / root / boot_completed1；前后五个启动分区及两份旧rootfs完整SHA相同，电量66→66%。[实际汇总26/26](original-result-v2.json) 绑定串口和新鲜Android采集的SHA。

原包由锁定AOSP源码函数重建，逐字节等于原备份。主控另行核26个封存源/证据文件、两完整包字节和CRC，[输入复核](original-input-review-v1.json)。缓存暂存前后可用93604→52640KiB；host与两次板端完整SHA通过，未写启动分区。

新鲜U-Boot2017.09 / Mar12 2026，RAM bank0 `[0x200000,0x8400000)`、bank1 `[0x9400000,0xf0000000)`；reloc=edcf3000、sp=eb9f85b0、TLB=efff0000。package范围避开这些以及实际kernel/initrd/DT、CMA `[0x10000000,0x10800000)`、ramoops低区与高no-map buffer。现场kernel目的地280000，ramdisk a200000，FDT a100000。

这次日志实际证实 SMDT 的单地址 Android RAM hook：`BOOTM: transferring to board Android`，RSCE base2204e000，11个资源条目；按HW6/BOM7选择 `rk3568_smdt_3568a_v20.dtb`，DT SHA1和Android hash通过。内核文件区 `[0x280000,0x2204008)`，initrd `[0xa200000,0xa2c8c20)`，FDT a100000，随后4.19内核启动。header里的10008000/11000000等元数据没有被当作这一轮实际目的地。原Image有效内存范围仍按image_size计算为 `[0x280000,0x22fd000)`，大于文件区。

最初load session预期filesize未写0x而严格拒绝；新session重新核精确`filesize=0x2800000`和完整CRC后才bootm。首次汇总又假定命令独占一行，实际为`=> bootm 20000000`；保留25/26结果及原汇总源，修正为仅允许可选CLI前缀的同一单地址命令，26/26通过。没有覆盖原始流或把错误结果改成成功。

成功仅证明U-Boot CLI已经可达时可以RAM启动这一原包。CLI前仍由原eMMC资源DT初始化PMIC/显示；改boot后可能改变这些早期输入。本板无SD卡座，用户报告OTG“dmo直接接地”，实际USB恢复未确认。因此这项不放行正式flash，不证明裸机恢复、全eMMC差分或Linux候选适配完成。

Linux RAM包在 [离线包目录](../rk3568-boot-package-20261005/README.md) 封存，最新板测见本页开头；原包26项结果保持原范围。TUN保持原样，只用临时源地址绑定用户态ADB转发。
