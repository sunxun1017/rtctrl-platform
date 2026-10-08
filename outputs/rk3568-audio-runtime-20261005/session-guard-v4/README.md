# 单向声音会话检查辅件（离线 v4）

v4 修正 codec 组件正常 probe 所持 MCLK 引用的阶段归属。固定 AMBA 名沿用 `fe550000.dmac`。
CPU/DMA/STOP/FD/控件门槛保留；clock gate 使用精确三阶段矩阵，不接受任意非零引用。
旧 v1/v2/v3 所有冻结文件在创建前和冻结后逐项核 SHA，不覆盖旧输出。

实际编入 codec 的源码 SHA 为
`72e59ced7af3bc570bafb516459c55a073f80613fb0a9ff1b6192cfa3f7cbc64`：component probe
成功 `clk_prepare_enable(mclk)`，在 component remove `clk_disable_unprepare`，失败正常 unwind。
DT 的 codec mclk 指向 CRU clock419/I2S1_MCLKOUT。两向 OFF 控件只释放各自额外引用，仍保留 probe
这一份；CPU 属性 `mclk_leases=0` 表示 CPU 自己的 lease，不能解释为整个 CCF 链引用数为零。

CCF 实际 provider 与 core 输入已冻结。root 本次只读 `clk_parent` 报告证实
`i2s1_mclkout→i2s1_mclkout_tx→mclk_i2s1_8ch_tx→clk_i2s1_8ch_tx→clk_i2s1_8ch_tx_frac→clk_i2s1_8ch_tx_src→gpll`。
bound 只允许这六节点各 enable/prepare=1、HCLK=1、protect=0，其余九项为零；card-unbound 六项
必须归零而 HCLK=1；cpu-unbound 全十六项归零。各阶段读这六个缓存 parent，必须逐项精确匹配且两次
快照相同。解释 baseline 的 TX parent 改变拒绝，不推测新拓扑、不自动重试适配；闲置 RX/IOE parent
不受此新增拓扑门槛限制，共享 GPLL 引用数不要求为 1。

这些计数是 CCF 总计数，未新增 per-consumer kernel instrumentation。codec 归属依据冻结 source/
module/DT、完整 card probe、三 OFF 控件和人工独占 native 域作有限推论，不宣称直接测到特定 consumer。
card 解绑通过 soc-core 正常 component remove 归还 probe 引用；codec platform driver 仍绑定也不能
推出其 component probe 引用仍在。HCLK 与 PCM DMA channels 仍由 CPU 组件注销释放。

`clock-stage-models/` 使用真实生产 `main→collect` 及 libc 受控缓存数据，288/288×3，包括阶段串用、
十六 clock 每项 extra/missing/2ref/enable/prepare/protect、六 TX parent 改变/读失败。只在 count 与
parent gates 通过后抵达刻意失败的 `/proc/devices` 读取，不运行 FD scan、inspector 或 START。
`clock-stage-red-v3/` 在旧真实生产源三环境重现合法 codec baseline 被拒、bound 缺 codec baseline
却通过 clock gate 的两个红例。`clock-stage-red-v3-test-setup-v1` 保留 fortify `__read_chk` 包装调试
失败记录，不纳入通过数。模型不证明真实 sysfs 收集成功或硬件 STOP。

新增 `canonical-models/` 每环境 13/13：实际生产 C 的 `canonical_device` 和 `main` 使用受控
libc 边界结果，核正确 dmac、错误旧 dma、地址、后缀、前缀、fs magic 和失败路径。`main` 正确
身份用例只越过 canonical 检查，然后在预设 driver identity 失败处退出，不运行 collector。
`canonical-red-v2/` 用旧生产源重现两个身份红例；这不是 fake 目录被真实 sysfs 接受，更不是板测。
链接模型同时包装 `realpath` 和 Ubuntu fortify 的 `__realpath_chk`，避免该调用绕过受控边界。
`canonical-red-v2-test-setup-v1/v2/v3` 保留包装器调试阶段的失败记录；不纳入通过数。

`build/audio-session-guard` 为静态 AArch64 C 工具，供主控在 native PID1 v3 的只读 root/cache
环境中，把已核 SHA 的辅件复制到 RAM 后人工调用。它只检查静止边界；没有 PCM ioctl、
PM get、MMIO、控件写、挂载、解绑、卸载、重启或服务安装。它调用原已冻结的 `alsa-inspect`
两次，仅读取 codec 缓存控件值；不调用 `pcm-config` 或 `pcm-transfer`。

本目录 `models/result.json` 是 **host/ASan+UBSan/AArch64 QEMU 每环境 501/501 的解析器模型**，
不是板测。完整 Image、实际 codec ABI、加载地址/包 SHA/live FDT、声学/电气和 native 返回路径
均未在此验证。`audio_start_allowed=false`、`permits_reboot=false`。

## 源码决定的边界

CPU v10 属性有 14 键，DMA C3 属性有 11 键。检查器要求冻结版本和原输出顺序；缺键、重键、
未知键/版本、额外文本、非规范数字、负 errno、溢出、读失败均拒绝。不能只判断 `ready=1`。

| 边界 | CPU | DMA | 控件及 PCM | HCLK |
|---|---|---|---|---|
| bound：前置/每个 helper 退出后 | ready=1/error=0/owners=0/open=0/STOP=1/stop_reads>0；irq_live=0/irq_drained=1，CPU own mclk_leases=0；configuring/power_transition/shutting_down=0；runtime_status=suspended | ready=1/error=0/STOP=1/stop_reads>0；pm_usage/leases/software/queued/descriptors=0；allocated=主控明确值 | card ID；两向 status/hw_params 均 closed；Playback OFF、MIC OFF、Resume OFF；两次完整 inspector 输出相同 | hclk_lease=1，HCLK enable/prepare=1；codec TX六各1；其他九0；protect=0 |
| card-unbound：主控正常 card/codec 解绑后 | CPU 仍绑定，上述条件相同 | channel 组件仍存在，allocated 仍为主控明确值 | 原 card proc/control 节点必须消失 | HCLK=1；codec TX六及其他九0 |
| cpu-unbound：主控正常 CPU 组件注销后 | driver/lifecycle 属性须消失（设备节点仍存在） | 上述零工作条件相同，allocated=0 | 原 card proc/control 节点仍须消失 | 全部 16 clock enable/prepare/protect=0 |

每个边界都要求全局 `/sys/class/sound/dma_quarantine_bytes` **严格为 `0\n`**，并扫描可见顶层 PID 的 FD 表。
sound 字符设备 major116、OSS major14、`/dev/mem`/`kmem`、UIO 和 `/dev/snd/` 路径均拒绝；
对 sound node/UIO node 的别名也按设备 major 识别。无法枚举进程/FD、FD 在扫描中消失、两次 PID/starttime
集合变化均拒绝。最终两次 CPU/DMA/引用计数/quarantine 快照相同；工具不自动重试。

UIO major 从本次 `/proc/devices` 的 **Character devices** 区域、确切注册名 `uio` 获取，
不固定为 247、不依赖 `/sys/class/uio` 或 node 路径。字符区域必须在前、Block 区域必须有正常
分界，完整表必须规范、范围符合本内核、末尾完整；未知/缺失 header、重复 UIO、UIO 同 major
冲突、溢出、读失败均拒绝。普通 tty4/5 多个 minor range 共用 major 是合法内核输出，允许。
Block 区域的同名 `uio` 不成为字符 major。每次 FD 扫描前后完整表相同，两个会话快照完整表也相同；
任何注册变化拒绝。无 UIO 注册正常接受并明确输出 `AUDIO_UIO_REGISTRATION present=0 major=0`，
不会猜某个动态 major；有注册时按字符 FD 的实际 `st_rdev` 拒绝任意 minor/path/hardlink 别名。

生命周期依据为冻结内核 `drivers/uio/uio.c`：`alloc_chrdev_region(...,"uio")` 预留整个 minor 空间，
`uio_fops.owner` 与 `cdev.owner` 为 `THIS_MODULE`。`fs/char_dev.c` 的 `cdev_get`/`fops_get`
和 `uio_open` 持有 core/provider module 及 device 引用，close/release 归还。`uio_unregister_device`
删除设备/class/minor，不调用 core major cleanup；设备 class 消失、旧 FD 仍存活时，正常生命周期中
core 的 `/proc/devices` 注册仍在，按 rdev 检查仍覆盖这个 FD。强制模块卸载不在本次许可范围。

本次实际完整 Image 的冻结 config SHA 为
`1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912`，明确 `CONFIG_UIO=n`。
UIO 别名是 v1 一般检测宣称中的确切模型缺口，**不写成本板可达故障**。`../session-guard-v2/red-v1/` 用 v1 已冻结的
host/ASan/QEMU 实际模型 ELF 重现 alias 放行，v1 文件/SHA 保持原样；v2 增加动态 major/别名与注册表契约。

CPU 属性是驱动缓存证明；DMA 属性的 `stop_reads` 是已发生的 STOPPED 检查累计，读取属性不会
再次检查硬件或启动 PM。要求非零及 `stop_proven=1` 使用的是驱动维护、在 START/状态改变时失效的
缓存证据，不能把 guard 解释成新鲜 MMIO 测量或独立硬件证明。

真实 `soc-generic-dmaengine-pcm.c` 的注册函数先请求 tx/rx；close 使用 `snd_dmaengine_pcm_close`
保留 `pcm->chan[]`。机器 card 解绑不是 CPU PCM 组件注销，因此仍可持有两个 channel。
仅 `snd_dmaengine_pcm_unregister` 在组件注销后调用 `dmaengine_pcm_release_chan`。
`allocated` 不参与 DMA 的 ready 计算：它允许已停稳但仍分配的 channel，不能误要求 bound/card-unbound
为零，也不能忽略意外多出的 channel。本版按冻结 DT 的 I2S1 `dmas=<&dmac1 2>,<&dmac1 3>`、
dmac1=fe550000 固定设备身份。主控先核本次 live DT 和绑定；ALLOC 明确传入，不从旧板测猜初始值。
如果本次确证仅这两个通道，才把 ALLOC 设为 2；有其他客户端、另一映射或不可解释数量则停止。

v10 probe 对 HCLK 做一次 `clk_prepare_enable`，runtime suspend 只释放 CPU 两向 own MCLK；HCLK 在正常
cleanup/devres 才释放。bound/card-unbound 保留一个 HCLK 引用符合这个实现，超过一个或 MCLK
残留则拒绝，codec probe baseline 按精确三阶段矩阵另行解释。最终 CPU 注销后全部归零。
无引用时保留频率/parent（包括 RX 12.288MHz）不等于仍运行。

此内核 `drivers/clk/clk.c:3018` 的 `clk_summary` 调用 rate-recalc/get_phase，可进入 provider 硬件读。
本工具因此 **不读 clk_summary/clk_rate/phase**，只读 `clk_debug_create_one` 用 `debugfs_create_u32`
发布的 `clk_enable_count`/`clk_prepare_count`/`clk_protect_count` 缓存变量，以及 current_parent_show
发布的六个 TX `core->parent->name` 缓存字符串。它不查频率/phase，不以旧完整 clock equality
作为门槛。每次核 16 个 I2S1 clock 目录并归一化计数，以及本次精确 TX 六链 parent。

现有 inspector 对 Playback 与 MIC 强制 OFF，Resume 仅展示；guard 再要求 Resume Path 存在且
label=OFF。它核 inspector 原始 CARD/LIST/CONTROL/终止标记完整结构、匹配 numid，额外或重复行失败。
任何控件不是 OFF 都拒绝并保留证据；工具不会把它改成 OFF。

## 实机顺序（只供主控按授权人工执行）

1. 主控先完成完整新 Image/codec ABI/启动包/组件输入 SHA 与真实加载地址、live FDT 核查。
   fresh native PID1 v3/root-ready、只读 root/cache、救援及电源条件沿用本次会话的独立门槛。
   检查器不替代这些门槛，也不沿用旧 PID/地址。
2. 从只读 cache 将 guard、原 inspector、transfer 及精确 SHA 辅件清单复制到 RAM。
   native3 的 /tmp 为 8MiB 可执行 tmpfs，/run 为 1MiB 且 MS_NOEXEC。只用 /tmp/audio、/tmp/audio-debug，
   不改 PID1 或 mount flags。四个辅件约 2.6MiB 加小日志可放入 /tmp；40MiB boot 包仅在 U-Boot 内存使用，
   不复制到这个 tmpfs。用真实 BusyBox52 的 `sha256sum -c` 校验完整 SHA，`chmod 0555`；不写 rootfs、不改 PID1 服务。
   主控按现有流程只读挂载 debugfs，例如到已有的 RAM 检查目录；检查器自己不挂载。
   本工具的生产运行不依赖新 BusyBox applet；构建已实际 QEMU 调用该 BusyBox 的 `--list` 核对精确 52 项。
3. 确认本次 card 编号和唯一固定 ID；核 live DT 的 tx/rx controller/request 及 DMA 绑定，
   解释 allocated。停止所有可再次开声卡的客户端，保持本次进程/proc 可见性和人工独占。
   此检查只适用于 fresh native 单线程 PID1、BusyBox 救援 shell、单线程有界 helper、无产品服务。
   本版例子中的 CARD=1、ALLOC=2 必须由本次证据确认后才使用。
4. 人工运行 bound gate，将 stdout/stderr/退出码分别保存在 RAM，以本次唯一阶段文件名记录。
   示例（路径需按本次 RAM staging/debugfs 路径确认）：

   ```sh
   /tmp/audio/audio-session-guard bound 1 \
       /sys/bus/platform/devices/fe410000.i2s \
       /sys/bus/amba/devices/fe550000.dmac \
       2 /tmp/audio/alsa-inspect /tmp/audio-debug/clk \
       > /tmp/audio/pre-playback.stdout 2> /tmp/audio/pre-playback.stderr
   gate_status=$?
   printf '%s\n' "$gate_status" > /tmp/audio/pre-playback.exit
   ```

   只有 exit0、完整 `AUDIO_SESSION_IDLE_VERIFIED stage=bound`，且主控独立门槛全部满足，
   才由主控人工许可单次有界 helper。不要把示例复制成自动 START 脚本。
5. 主控只安排一个方向：固定 S16_LE/48k/2ch/256×4，playback 零样本或 capture 仅统计帧，
   不变路径控件。等待该 helper 真正退出，保留它的退出码及完整日志，随后再人工运行同样 bound gate，
   保存为 post-playback 或 post-capture。helper exit0/STOP/free/close 不代替这个检查。
   前一方向退出后 gate 拒绝，不开始下一方向。下一方向仍需一份新的前置 gate。
6. 两方向/退出边界均满足主控验收后，主控按真实正常路径解绑 card/codec；再调用
   `card-unbound CARD CPU_DEVICE DMA_DEVICE ALLOC DEBUG_CLK_DIR`。此时 retained channels 合理，
   仍要求零工作 owner/软件/desc/lease、STOP 缓存与 quarantine=0。
7. 主控按正常路径注销 CPU 组件（由其 unregister 释放 DMA channels），再调用
   `cpu-unbound CARD CPU_DEVICE DMA_DEVICE DEBUG_CLK_DIR`，要求 allocated=0 和 HCLK 归零。
   guard 不执行上述操作，也不强制卸载。单独模块卸载/card消失不能假设已释放 CPU 通道。
8. 主控正常卸载 `/tmp/audio-debug` 的只读 debugfs 并核成功后，进入后续正常 native 回 RAM、
   七挂载/FD guard 和普通 reboot、fresh Android 七保护输入 SHA。
   必须由主控分别核查。guard 输出永远包含 `reboot_permission=0`，不会发布 reboot 许可。

任何 sticky/未证明 STOP/软件排空未知/quarantine>0、检查失败或不可解释状态，都停止后续 START、
解绑/卸载和 warm reboot/旧 RAM 复用，保留日志供主控按硬件生命周期方案判断。不要靠重试成功
覆盖之前的硬停不确定证据。只读瞬态 EAGAIN/进程变化可在主控解释原因后建立新的完整检查记录。

两次只读快照和无 FD 是观察，不能提供原子内核 admission lock：检查结束到人工 helper 开始之间
仍有竞争窗口。主控必须防止新客户端/服务启动。工具只枚举顶层 PID/fd，不枚举 `/proc/PID/task/TID/fd`，
不能覆盖同进程中不同 `files_struct` 的线程；不宣称全线程 FD 排查或一般产品服务域支持。
proc namespace/hidepid、系统并发、设备销毁以及不可中断内核等待均不能被模型或 SIGALRM 解决。
15秒默认 SIGALRM 会终止 guard，仅限制可调度/可中断的正常进度，**不能证明同步回收 inspector 子进程**。
正常成功时两次 inspector 都已 waitpid/close；任意失败或信号后，主控禁止启流及后续动作，
只读收集 guard/PID1 子进程和相关 FD 证据，等待 PID1 收养/回收 inspector 后再重新建立完整检查。
不能把 guard 已退出、信号期限到了或单次无 FD 当成清理完成。

## 离线复验和冻结

`test-models.py` 实际编译同一个 `guard-parser.h`，在 host、ASan/UBSan、AArch64 QEMU 运行良好、
缺字段、重复、未知、errno、数值溢出/非规范、不稳、控件ON/缺Resume、时钟缺失/多引用及 FD 别名模型。
保留原 440 项及 61 项 UIO 注册/别名/生命周期边界，三个环境每环境 501 项；旧 HCLK-only clock
场景明确移至 card-unbound，原 all-zero 场景移至 cpu-unbound，仅改两行名称/阶段参数。
其中组合用例实际将注册表解析结果传给共享 FD 分类器，覆盖动态 major、无注册、block 分界和读失败；
这些仍是模型，不创建真实 UIO 设备、不尝试 mmap 或读取硬件。
`build-freeze.py` 用严格编译参数构建静态生产 ELF，核 imports/ELF、
无动态依赖、实际 QEMU 参数拒绝和 BusyBox52 清单；不会用有效 CLI 访问宿主设备。
同脚本要求生产 C 仅新增缓存 parent 收集/双快照/证据输出及真实 stage 接线；共享 parser 除
clock_valid 精确矩阵外逐字节相同，model driver 完全相同，原 501 脚本仅改两个阶段标记。
同时核新 clock stage 288×3、canonical13×3、旧 v3 两项红例和已有 v2 固定设备名红例输入。
`build/production-v3-v4.diff` 提供完整窄 diff。`build/v3-binary-delta.json` 保存相对 v3 的逐字节
差异块/尺寸与双端 full SHA；任何 RAM 修补后的身份必须重新核完整 v4 SHA。
差异文件不证明板端应用成功，也不授予 START 或重启许可。

`inputs/` 保存逐字节输入副本；`build/manifest.json` 登记输入及生产 SHA；
`frozen-output-manifest.json` 和 `SHA256SUMS` 覆盖本目录源码、文档、模型输入/输出、生产 ELF
及输入副本。生产辅件只需 `build/audio-session-guard`，主控将它加入独立辅件清单，
不要把宿主模型 driver/Python 或输入源码全部暂存到板上。

本目录不参与项目 CMake，不改公共源码/补丁/冻结输入，不连接板/串口/ADB、不改网络/TUN、
不提交。实机 collector 的系统调用、完整新 Image/driver 暴露接口和实际 idle/START/exit 尚待主控验证。
