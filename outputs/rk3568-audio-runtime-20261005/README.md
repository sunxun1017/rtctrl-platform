# RK809 PCM 参数与关闭状态板测（2026-10-05）

源码 Linux 5.10 上，播放、采集两个方向的 S16_LE/48kHz/双通道参数配置、释放和关闭已通过。
没有 PREPARE/START、PCM 帧读写、录音或试听；DMA 调用只配置 slave，不提交传输。
结果见 [result.json](result.json) 与 [参数摘要](pcm-configuration.txt)。原始捕获含设备标识，保留在忽略的 private/。

本轮使用原已测 Image `e7a95d9f…` 与精确 ABI，新增外部 codec 补丁0007和静态 MIT PCM工具。
补丁在寄存器操作前校验 stream/rate/format，传播 hw_params 与四个数字时钟重启函数的首个负errno；
不改成功寄存器顺序、延时或父PMIC regmap所有权，删除未实现的 S20_3LE 能力声明。
真实函数 host/QEMU各246/246，probe回归73/73；模块32项导入与原Image闭合。
工具 host/QEMU各180/180，严格CARD_INFO/PCM INFO身份兼容动态minor，5秒SIGALRM覆盖打开、配置、释放和关闭。

板端只有板子，用户确认没有外接耳机、喇叭、电机，屏幕排线也已拔下；仍枚举到原USB UAC设备。
卡号动态定位为1，14控件始终OFF/MIC OFF/Resume OFF。两个PCM先SETUP且appl_ptr/hw_ptr为0，
HW_FREE后OPEN，关闭后status/hw_params均closed、I2S runtime suspended，guard扫描无音频FD/工具进程。
GPIO148保持spk-ctl out hi ACTIVE LOW；TX/RX DMA绑定保持dma1chan2/3。软件诊断不代替电气测量。

两次拒绝证据保留：第一轮最小BusyBox不接受sleep0.1，尚未打开PCM即退出；修为整数1并增加实际参数检查。
第二轮两向PCM均通过，但原脚本要求整份时钟快照逐字相等而拒绝。源码确认TRCM=1的HW_PARAMS
将接收三项时钟配置为12.288MHz，HW_FREE/runtime_suspend不恢复rate/parent；三项引用计数均恢复0。
只有clk_rx直接父由rx_src改rx_frac，其余父关系不变。新只读收尾严格检查所选16项名称、行序、计数、
精确频率例外和树深度，24/24实际shell故障检查；补读新鲜控件/GPIO/DMA并通过FD guard。
原pcm-rejected不改写，单列closed-state-verified；没有重试PCM或写时钟。DMA摘要只证明绑定，没有直接观察描述符队列。

串口只读收尾第一次生成器误将转义编码为NUL，SHA门槛拒绝，脚本没有执行。
修正为保存的编码器并用精确BusyBox printf逐字节往返后才重传；失败capture与新证据均保留。

模块保留到RAM-only SysRq复位，960.295783秒返回Android11/4.19.232、boot_completed=1；
Linux返回段无新增RCU警告/Call trace。五启动分区与两份旧rootfs完整SHA均不变，电量87%→81%。
TUN设置保持原状，未刷启动分区、saveenv、普通reboot/poweroff或电机动作。

复现入口为 test-runtime.py、build-codec.py、test-pcm-config.py、build-pcm-config.py；
新增版本须选择未使用目录。prepare-staging.py --revision vN只准备新普通文件和会话，
完整原interface脚本仍保留严格旧时钟门槛；其失败不是完整阶段成功，新收尾需独立review并重新取当前状态。
verify-clock-profile.sh是这份精确Image/板测参数的检查器，不适用于任意声卡、频率或不同clock树。

剩余音频工作是PREPARE/unmute errno、路径OFF的实际静音语义、DMA传输与退出同步、功放电气和接回实物后的声音验收。
本轮参数通过不能代替这些验收，也不能把PMIC RBTREE缓存的OFF视为硬件已关闭。
