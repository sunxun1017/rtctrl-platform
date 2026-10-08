# RK3568 显示源码接口与正常重启实测

2026-10-05，新源码 Image 配独立 display DTB 在 RAM 启动成功，74 项读取检查全部通过。
屏幕排线已拔下，初始亮度0，全程未写亮度或打开 DRM/FB 设备。
180 条面板初始化命令在真实 DSI host 路径全部返回成功，VP1→DSI0 为720×720、35.5MHz，
framebuffer32bpp/stride2880；GPIO reset解除、enable高，PWM周期25000ns、duty0且enabled。
固定面板的 DRM `connected` 与初始化完成日志均不能代替面板 ACK、画面或电气背光测量。

检查后执行真正的 reboot syscall，经历 device_shutdown、显示关闭、syscore 与硬件重启；
454.881364秒记录 Restarting system，返回 Android11/4.19.232/boot_completed1。
正常重启请求至首个 DDR 交接未捕获 WARNING/BUG/Call trace；启动阶段仍有BSP及显示诊断。
本次返回未使用 SysRq。五启动分区和两份旧rootfs前后七项完整SHA一致，最后电量78%。
这是一次正常重启往返，poweroff、MCU应答/看门狗和电源轨仍未验。

## 输入、构建和复现

- Image：`dafdda0cc331605471c1b24a33cb4f037bf4af79b4145eabf12513dabf4d86a7`，34755072B，CRC6c3715bf。
- DTv5：`650228482eaed6f95d9892fce217f436072d851cc47398696d52b85e08200f70`，166090B，CRC6ea18539。
- initrd：`f0965ceed549acab8d5bd87df8bb831bb06a95d08b5b7bf3c5582045933323ee`，4308268B，CRC74fea1e6。

[PLAN.md](PLAN.md) 记录原720×720时序、180命令/GPIO/PWM和DT严格属性边界。
DT250审计/107个真实坏DTB拒绝；0008真实DSI host函数链 host/ASan/QEMU各254/254。
旧按正返回值等于payload长度的候选被真实host否决，保留红记录且未部署。
锁定commit `9f9e9d18574d0914c0d192a90c3babfe1fd63c95` 的独立clone构建新Image，
原kernel tree和旧已测Image保持；Image-only导出表为实际vmlinux.symvers。
新codec/WLAN模块未加载，不能仅凭同release推断任何其他模块ABI。

`build-image.py`、`build-dtb.py`、`prepare-staging.py` 记录源码、补丁、配置、compiler和产物SHA。
构建与session拒绝覆盖；现有v1–v9均为本轮历史，复现必须选择新revision。
本次实际执行 [runtime-manifest-v9.json](runtime-manifest-v9.json) 的 load/boot/stage/inspect会话；
Android端使用先完整校验upload.sha256、再直接执行prepare-android.sh的路径。
[正常重启工具](../rk3568-normal-reboot-20261005/PLAN.md) 为独立MIT静态程序，真实main host/QEMU共32个边界用例。
请求先核冻结RAM guard和helper完整SHA，守卫失败不调用reboot。

## 收尾与传输中的修正

v1检查会话只匹配COMPLETE，失败也可出现；v2要求VERIFIED与真实EXIT_ZERO。
stage前独立RAM guard、绑定SHA的attempt和stage-rejected分支覆盖早期失败，卸载失败仍拒绝reset。
46个stage/Android/inspect shell fixture、56个guard fixture与72个本地session步骤通过。
v2多行wrapper不能通过真实Windows串口执行器的ASCII预检，v9将可读wrapper单独octal传RAM再校SHA；
独立审查108个Linux/U-Boot步骤，实际stage/inspect均成功退出。

Windows ADB对嵌套多行shlex命令的引号传递失败，普通文件上传完成但cache准备未执行。
随后ADB两次closed，改用已有串口验证完整清单并执行原准备脚本；不改TUN/网络设置。
Live FDT首次超长hex帧截断，4KiB分块仍有一块丢26个hex字符；仅重读该块为四个1KiB片段，
最终168064B的完整SHA与板端 `3d3f6437…dd79b9` 一致。失败流保留，不用宿主DT猜补缺字节。

## 范围与证据

启动有两个overlay Cluster-win1初始化消息、预期loader memory跳过、背光dummy regulator等，
本轮没有通过猜测供电或启用额外硬件消除日志。PWM duty0不是电气验收，GPIO/clock/regulator是软件状态。
只读cache以ro,noload复制至RAM后释放，debugfs也释放，返回守卫核所有mount/loop/modules/FD。
没有刷启动分区、saveenv、电机/MCU命令、声学测试、提交或推送。

[result.json](result.json) 区分板测结果与构建manifest的历史待测标志。
`record-result.py` 从保留原始证据和冻结输入核查生成机器结果；私有原流、完整FDT、地址和标识仅留在忽略目录。
当前已返回Android；下轮重新检查电量、连接和实际进程。
