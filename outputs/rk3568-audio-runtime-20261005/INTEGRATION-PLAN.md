# 声音内存合测的整合

以独立clean源码/已测配置为基底，0001–0010与已独立通过CPU v10保持冻结输入。
DMA C1/C2/C3含只读状态最后封存，再整组独立审查和全源精确重放；通过后由主控发布0011/0012、
构建完整Image和本Image的实际导出符号/生成头。外部RK817 codec仅使用该新Image ABI与0006/0007/0009，
不能沿用旧模块。完整Image/模块仍是离线产物；新的上板证据独立保存。

复用未改native PID1 v3、只读rootfs和initramfs。它保留旧RCU缓存文件的固定核查，
不是新Image身份来源；新Image由实际RAM bootm完整包SHA/CRC、组件输入SHA、真实加载地址/大小证明。
不改PID1生命周期或启动服务。另将新codec、inspection/transfer helpers和多行session/guard脚本
从只读cache复制到RAM，逐项全SHA后人工受控调用；未知卡/状态/FD/错误直接拒绝启流。

下一轮只启用此前已测的audio DT和最小chosen overlay shim，仍保持MCU/未知传感器禁用、屏幕断开。
先核驱动/card/控件OFF、单向独占FD、CPU/DMA ready/sticky/真实STOPPED与软件排空快照、
quarantine=0、时钟引用和正常codec解绑卸载路径，再许可单个有界helper。
playback写零样本，capture只统计帧；两方向分开，固定S16_LE/48k/2ch/256×4，不改变路径控件。
helper自己的正常exit不替代驱动停稳证明，软截止不保证不可中断内核等待能退出。

任何硬停不确定或软件排空fail-stop保持禁止warm reboot/旧RAM复用。正常成功后独立核
CPU/DMA零owner/零software user/STOP证明与零quarantine、无音频FD；正常解除codec绑定/card、
卸载模块，再核native原生回RAM与七挂载guard。之后才普通reboot并新鲜核Android七保护输入SHA。
无flash/saveenv/强制卸载/MCU指令。正式启动器的早期DT/AVB与USB恢复仍另行调查。

cache空间按完整host备份及fresh root/ready、普通文件身份/全SHA精确回收，保留原RCU/native3/v2包和七保护输入。
只回收实际需要的旧试验文件，旧试验再运行须按其完整清单重传；不递归清理。
