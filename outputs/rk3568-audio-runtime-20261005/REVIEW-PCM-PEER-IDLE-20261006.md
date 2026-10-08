# 无START双open检查程序复核

2026-10-06。接受用户态源码、有限syscall模型和静态产物进入下一轮离线包准备。
主控fresh运行与独立只读审查 `/root/battery_dt_audit_1006` 均完成；此程序尚未板验，不产生START许可。

源码 `pcm-peer-idle-v1/pcm-peer-idle.c` SHA
`4edc171fd8bb57c10d844bbfdfa72f83dd090de3f96f143bab8459fd7e22c8d2`。
参数/ABI/身份函数header逐字复用原pcm-config prefix，SHA
`26ae04bc98a5e466bc24a18ab76b5841c9c52a0e265d5610cdedc2d4011536f9`，锁定UAPI SHA138cb9e8…a0447。
显式卡号及两种open/close第一方向组成四顺序；无默认目标卡，无PREPARE/START/frames或控件写。
两个PCM均固定48k/S16_LE/2ch/256×4，严格身份/返回参数/SETUP零指针。
首方向FREE/OPEN/close成功后，核peer仍SETUP零指针，再FREE/OPEN/close另一方向。
正HW_PARAMS异常仍作已配置资源归还，每次FREE/close最多一次，EINTR不重试；保留首错并继续peer清理。

作者实际main在host、ASan+UBSan、AArch64/QEMU各1032/1032；独立逐case catalog、命令exit、
原始模型/操作唯一序号/首errno和清理日志重核吻合。
[主控fresh结果](build/root-pcm-peer-idle-v1/result.json)同样各1032/1032，真实主程序/参数源码不改，
只将复制runner的ROOT/RUNTIME路径深度适配独立输出；所有输入前后SHA相同。
原单端main四顺序host0/4红例说明尚无这个接口，不能当作内核原缺陷复现。

静态生产manifest SHA30e074fd01cbe94bc8e28a20de19698c5492525af469615afc7daaac92331779；
二进制655136B SHA `7693a052b6318ec3e965451fcb94609e97cb48e693715b847b62032cc684e661`，CRC e5c2ba24。
独立ELF确认为ET_EXEC/AArch64、无PT_INTERP/PT_DYNAMIC；真实object22项导入与白名单一致。
9个实际步骤含3个无效参数QEMU exit2，其余0；8原输入与快照SHA相同。
首次production-v1因FORTIFY libc三项__*_chk未列允许集被审计拒绝，失败保留；
按旧helper既有允许集补齐后production-v2通过，未修改生产C源码。

SIGALRM先恢复默认并解除继承屏蔽；三环境真实约5秒/-14验证的是可中断pause模型。
设备不可中断内核等待不保证五秒终止，timer解除后的stdout不在deadline内。
syscall模型和STATUS检查不直接测量内核PM、DMA或共享sysclk缓存；静态ELF不代替板端接口验收。
现有严格guard只用于全部PCM关闭的前后，不能套用于held peer或据此放宽双START。
需要新Image/codec/包身份绑定及独立板端检查后才执行有限四顺序矩阵。
