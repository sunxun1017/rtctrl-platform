# 默认目的地址的 RAM 试验

复用已完成 v3 试验的同一40MiB v2包，SHA67f351b8…af37dbe，旧RCU Image和native PID1 v3。
本次只覆盖此前未执行的kernel default搬移分支和header cmdline来源，不声称早期DM/正式AVB通过。

上电后先新鲜核root Android11/4.19.232/ready、七保护输入、cached包及native3 rootfs/initrd
全SHA，host完整包也重新核SHA。串口由主控独占；不改TUN、不回收cache、不写启动分区。
在fresh U-Boot核gd FDT A100000、kernel_addr_r=280000、ramdisk_addr_r=A200000，以及
实际DRAM/reloc/stack/reserved范围；与v3同一fresh早期DM。读取40MiB包至20000000..22800000，
全CRC cab15fb2后才执行。kernel header text_offset0、image_size35389440，实际调整default
destination到200000，占用至23c0000；与FDT A100000..A140000、initrd A200000..A2ed5ab及包互不重叠。

保持kernel/fdt/ramdisk三个默认地址，bootargs不手工覆盖，仅临时设置initrd_high/fdt_high
为全1以保持目的地址。一次bootm20000000，核真实DT选择/hash/overlay、只一次资源读取、
kernel actual加载span和header占用、initrd span、FDT位置及最终/proc/cmdline。
Linux读取native3 PID1实际maps/只读root/cache，进行原有纯软件codec/PTY selftest，
原生返回RAM、独立七挂载guard、普通restart后新鲜核Android七SHA。

最终FDT若只作大小/完整SHA与所需chosen字段读取，则该轮明确不作全树语义验收；
v3全树审核结果不能冒充本轮新树已比对。正常失败先保留流并判明现场状态，不自动重复bootm。
普通reboot是退出路径；没有saveenv/flash/SysRq/音频START或USB恢复操作。
