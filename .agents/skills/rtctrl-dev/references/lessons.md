# 已验证项目经验

## 2026-09-21：Linux非阻塞tty的空闲不等于EOF

适用于当前PosixSerialTransport的Linux非规范tty：VMIN=0、VTIME=0时，空闲read可能返回0，
与现有map_result的Closed语义冲突。本轮PTY先复现失败，改VMIN=1且保留O_NONBLOCK后，
空闲得到EAGAIN/WouldBlock，真实挂断仍为Closed/Error；原生及ARM64 QEMU user用例均通过。
证据：[PC/QEMU验证](../../../../docs/verification-pc-qemu-20260921.md)。
QEMU系统调用使用宿主Linux，此结论不外推其他OS或目标厂商UART，换内核/tty驱动需复核；
不把所有零字节读取改为WouldBlock来掩盖EOF。

## 2026-09-21：候选内核配置需要检查解析结果和输出边界

适用于平台数据驱动的BSP配置：片段中的请求可能被Kconfig依赖消除；本轮实际遇到
BT_HCIUART_BCM缺serdev、ROCKCHIP_RGA2与MULTI_RGA互斥。先运行olddefconfig再逐项比对。
Kbuild还会解释路径及KCONFIG输出环境变量，argv列表本身不能约束下游写入；当前通用工具
限制路径字符、清理覆盖变量并固定子进程cwd到输出目录。环境污染/只读cwd实测通过。
证据：[平台验证](../../../../docs/verification-linux-platform-20260921.md)。
换内核版本需重新核对Kconfig和构建系统；配置/对象编译不代表板级接线或启动通过。

## 2026-09-10：新增源码不代表构建已覆盖

- 适用条件：在研模块或适配器刚加入目录树，尚未完成产品装配。
- 证据（2026-09-11 更新）：RKNN 已通过 `RTCTRL_ENABLE_RKNN` 接入，`cmake --build --preset robot-vision --target rtctrl_inference_rknn` 成功；独立 SDK 替身测试及其 ASan/UBSan 通过。通用 `modules/inference` 已实现张量描述、大小计算和 Backend 接口，RKNN 通过该接口适配；release/asan 各 12 项、robot-vision 18 项测试通过，包括安装消费和 include-boundaries。
- 结论：对 RKNN 的验证必须先证明 backend 进入实际 target/编译命令；现有 release 或 robot-vision 测试通过不能单独证明它已编译。
- 失效条件：通用模块与真实 SDK/板端验证完成后更新状态；静态库和替身测试不代表已链接 runtime 或完成 NPU 实测。

新增经验沿用日期、适用条件、证据、结论、失效条件。仅保留会改变后续开发决策的信息。

## 2026-09-11：RKNN 普通输入与 native 内存是两种契约

- 适用条件：为 RKNN 实现图像预处理或 DMA-BUF 接入。
- 证据：本地 Toolkit2 User Guide 英文版第 135、158–159 页说明普通 API 输入执行配置的 mean/std；第 69–72 页要求 native 内存匹配 stride/type，RKNNRT API 英文版第 38 页描述缓存同步。
- 结论：普通 `pass_through=0` 的 raw RGB Float32 不能再手工重复模型转换配置中的归一化。native IO 按 `size_with_stride` 分配并保留完整 SDK 属性，不能直接复用稠密 Float32 描述。拥有 DMA fd 或通过宿主替身测试不证明端到端零拷贝。
- 失效条件：SDK 版本、模型预处理或 IO 路径变化时重新核对。代码说明见 `adapters/inference/rknn/readme.md`。


## 2026-09-12：视频识别与 fortified poll 测试

- 适用条件：视频识别复用 V4L2 采集、或 ASan 构建中使用系统调用 mock。
- 证据：face-video 与 face-video ASan/UBSan 各 24 项通过；RV1126B 实机连续识别与浏览器 MJPEG 预览、停止重启已验证，见 `apps/face_recognition/VIDEO.md`。
- 结论：帧归还前完成自有 BGR 转换，异步推理只保留最新待处理帧；NV12 的 full/limited 和 BT.601/709 应依据元数据或显式配置，不能默认 OpenCV 限幅转换。空人员库输出 unknown；等待单人登记时检测上限至少为 2。
- 测试结论：glibc fortified 构建可能调用 `__poll_chk` 而非 `poll`，mock 须同时包装这两个符号，否则伪造 fd 进入真实 poll 导致错误失败；不要以关闭 sanitizer 处理。
- 失效条件：采集 API、glibc/toolchain、颜色元数据或 BSP 变化时重验。

## 2026-09-12：RV1126B 独立硬件视频预览

- 适用条件：仅采集、缩放、编码、浏览器预览的独立应用。
- 证据：`apps/video_preview/README.md` 的板端对比；`gst-inspect-1.0 mppjpegenc` 支持 width/height/max-pending，debug 确认 `using RGA converted buffer`。
- 结论：该 BSP 可使用 V4L2 DMA-BUF、编码器内置 RGA 缩放、MPP JPEG；不需要把原始 NV12 转成 CPU BGR 再编码。不能把硬件缩放或编码包零拷贝属性描述为整个 HTTP 链路零拷贝。
- 实现注意：厂商库可能向 stdout 写诊断，二进制视频使用独立 FD；板端可缺少 `/proc/PID/task/PID/children`，性能工具用 `/proc/PID/stat` 的父进程字段定位子进程。
- 失效条件：BSP、插件构建选项、采集格式或尺寸变化时重验；独立预览的结果不代表其他处理应用性能。

## 2026-09-12：MPP 池复用与输入零拷贝要分别验证

适用条件：RV1126B 独立 GStreamer 摄像头预览，当前 SDK rockchipmpp 插件。
证据：`outputs/MPP缓冲复用实测.md`、`outputs/mpp-reuse/` 中的 OFF/ON 计数、重复测量和输入探测日志。
allocator 的 cacheable 控制内部 MPP 池保留，不改变 CPU cache 属性。预热后 heap 分配归零，
仍不能证明无映射、无复制；这次两块 GstMemory 输入实际走 RGA 虚拟地址路径。
手工构建需保留 SDK 的 `-fvisibility=hidden`，否则同名 `mpp_enc_debug` 符号可冲突。
换 SDK、输入布局或构建方式后重新验证；不要据此跳过 DMA 同步或默认启用实验插件。

## 2026-09-12：推理优化按同输入、同二进制分层对照

适用条件：RV1126B 的 RetinaFace/MobileFaceNet 视频应用，当前配套 OpenCV 与 RKNN runtime。
证据：`outputs/npu-20260912/` 的 API 配对、perf Self、颜色转换和 JPEG 编码日志。
`inputs_set` 墙钟包含 SDK 内部路径，不能全部归为 NPU 核心执行或某一种类型转换。
显式 UInt8 需匹配实际像素值域、布局与字节缓冲，并保留普通 Float32 默认契约。
这次查表在 x86 一致、ARM 因 FMA 舍入差 1；保留舍入后又比原式慢约 2%，因此未采用。
固定输入下板上 TurboJPEG 编码比配套 OpenCV JPEG 更快，压缩输出仍复制成独立对象供 HTTP 持有。
后续复用的是 perf 定位、正确性检查与单变量对照的方法，不应强行沿用某个“零拷贝”或查表方案。
换工具链、模型、编码库、颜色元数据或输入布局后重验；短对照与提前停止的采样不能当长时间稳定性结果。


## 2026-09-12：三十帧人脸视频的瓶颈迁移

- `outputs/fps30-20260912/`：先拆分V4L2序号缺口、待识别覆盖、待编码覆盖；`dropped`原本仅代表latest槽覆盖，不能当驱动丢帧。发布FPS不等于浏览器绘制FPS。
- CPU颜色转换43ms经RGA staging约9ms后CPU下降但FPS仍受下游限制；native输入按验证模型mean/std填FP16并同步，JPEG异步后单脸达到30FPS。复用的是定位/对照/回退方法，不把旧GStreamer插件直接搬入不同管线。
- 原生FP16的恒等AFFINE属性仍需明确归一化；只按shape或直接写raw FP16会错。输出逐值对照和模型指纹约束先于启用，换模型/SDK后重新验证。
- 新perf显示submit热点后，外提类型/布局分支，所有类型布局及ROI逐值一致，再用无人脸A/B确认CPU下降。不要把微基准几十倍当整链提速，也不要把不同人脸数的CPU/Self直接相减。
- 单分钟稳定和短A/B只能覆盖当时负载；被用户停止的长期采样不能写成完成。


## 2026-09-12：30 FPS 下继续降低人脸视频 CPU

- 适用：已验证RV1126B、OpenCV3.4.5、960宽预览、native两模型；证据 `outputs/cpu50-20260912/README.md`。
- 精确缩放特例、单内存camera DMA直接导入、MPP JPEG分别对照，单脸CPU约101→87→78→38%，保留30FPS。前两项逐像素一致；硬件JPEG像素不同且在推理后，不宣称等画质。
- EXPBUF会让已有MMAP缓冲进入bufinfo统计；核对exporter/大小/对象数和SDK get_dmabuf源码，再解释全局DMA增量。PSS与DMA不可直接相加。
- MPP简单put/get在超时后所有权可能已转移；显式task enqueue/pop划分责任，mock需模拟SDK真正释放queued资源。poll成功可能为正任务数量，只有负值报错。当前noncacheable路径不代表未来cacheable也无需同步。
- sanitizer缓存开关不证明每个目标都已插桩；核对实际编译与最终链接选项，特别是只链接OpenCV的独立适配器/测试。
- 失效边界：换模型/输入几何/OpenCV/SDK或改cacheable需重新验证；短测与每秒峰值不替代长时/多脸/微秒级峰值测试。


## 2026-09-12：ftrace忙时与RKNN模型文件副本

- 证据：outputs/ftrace-20260912/；任务占用load不同于MAC利用率，先同步记录脸数、FPS、频率和trace丢失。无脸10%与单脸24%不能当优化前后。
- function+sched_switch不足以分离睡眠与唤醒排队；补sched_wakeup→switch-in，当前单脸主线程P95约16us，无明显绑核依据。无job ID的schedule→IRQ配对只适用观察到无重叠的窗口。
- 匹配SDK2.3.2普通rknn_init flags0初始化后可释放文件副本；两模型各20次合成输入完整输出字节一致，单脸PSS约47.4→41.1MiB。特殊MODEL_BUFFER_ZERO_COPY等模式必须重审生命周期，不能复制此结论。
- 当前实际MEM_SIZE查询total/free SRAM均0，不根据头文件宏盲开SRAM。NEON固定点缩放逐像素一致，整机无脸CPU29.32→27.92%；没有NPU算术负载降低结论。


## 2026-09-18：云端音频参数与会话隔离
适用：companion协议v1适配。原Android后端hello返回Opus 24kHz，客户端上传仍16kHz；
录音与播放参数必须独立协商，不能因Android源码编码常量为16kHz而固定解码采样率。
协议缺少turn ID时，停止播放队列不等于隔离迟到回复；当前打断重建连接，
录音使用独立capture_epoch。证据见[验证记录](../../../../docs/verification-companion-20260918.md)
与tests/test_companion.py、tests/test_companion_audio.py。后端支持可靠轮次ID后可重新评估连接策略。

## 2026-09-18：ES8389采样与后端验收分层

适用当前ALIENTEK RV1126B Linux6.1.141现场。直接16kHz/mono录音出现RUNNING但hw_ptr=0、零字节；
48kHz/stereo正常，专用ALSA plug可转为16kHz/mono。配置只通过进程ALSA_CONFIG_PATH启用，
不能据此断言SoC不支持16kHz；更换BSP/声卡/时钟需复核。amixer默认可能走软件设备，硬件控制需明确-c0。
原Android后端realtime与manual停止机制不同，尾静音是协议适配，不应延长真实采集。
上传帧、STT、TTS音频、ALSA硬件运行、用户听见是不同验收层；hello成功不代表ASR/LLM/TTS正常。
证据：[板端记录](../../../../docs/verification-companion-20260918.md)。


## 2026-09-18 语音worker完成与资源测量

适用于当前Python Unix socket ASR/TTS worker：成功ACK必须在释放串行busy后发送，否则下一请求可能偶发busy。
连续10轮公开样本及确定性测试验证修复。CPU监控需包括模型子进程；按(PID,starttime)重置/proc差分，单核100%口径允许超过100。
模型RSS随预热/长度增长，初次加载快照不是长期上限；线程数和arena策略应由板端perf及多轮RTF/RSS验证，不套用主机结论。
证据：docs/verification-companion-performance-20260918.md。模型、runtime、allocator或进程架构变化时需重新验证。


## 2026-09-18 本地TTS播放一致性

本地生成WAV无须套用网络语音的Opus链路。以同一WAV比对进入aplay的实际PCM字节及rate，
区分软件损失与扬声器听感；不要用不同次VITS生成波形当作严格相等基线。
异步播放须持有有界bytes而非即将删除的临时路径，完成以EOF后的播放器drain为准；
超时覆盖管道剩余音频时长，不能假设所有Linux管道都是8KiB而固定3秒。
适用当前ALSA非实时AudioIO；改格式/播放器/缓冲策略后重验。证据见verification-companion-20260918.md最新章节。


### 2026-09-18 RV1126B语音NPU迁移边界

CPU ONNX INT8不等于RKNN INT8：当前CTC DynamicQuantizeLinear在Toolkit2 2.3.2 build失败；
官方RV1126B Zipformer FP模型可转换并板测。模型替换必须重验文本，CLI计时必须区分加载与应用IPC，
主进程RSS不含独立runner/NPU DMA。VITS decoder可拆但局部相关性不能代替整句音质验收。
证据：docs/verification-speech-npu-20260918.md。模型、SDK或运行库变化后重新验证。

### 2026-09-18 流式回声保护的同轮状态

流式 ASR 的 final 可能改写已命中的 partial；仅隐藏 partial 不足以阻止最终自动提交。
当前全双工将已命中的疑似回声保留至本轮结束，使用显式确认，下一轮和释放必须清理。
证据：docs/verification-echo-guard-20260918.md、test_companion_duplex_core.py。
这不证明声学 AEC 有效；从未匹配的回声仍可漏判，真实重复设备话可能需确认。
识别事件边界或确认策略改变时重验。

## 2026-10-03：原厂 MCU 缓存、成功日志和实际总线行为分开验收

适用原 RK3568 4.19.232、Image SHA 和 McuCom ABI 均匹配本次证据的诊断；换驱动必须重审。
本次独立缓存程序在 Android/独立 Linux 均通过，但 skip-mcu 分支不访问总线、helper 返回255，
部分成功日志仍可能出现；0xc0只复制内核缓存，不能算实际MCU查询或看门狗状态。
私有ftrace instance加自身调度正对照、丢失统计和逐项清理，得到的是有界窗口而非物理无活动结论。
ext4 的 ro 挂载仍可能回放日志；后续诊断脚本改 ro,noload，哈希校验拒绝不一致数据，
修正版本尚未板测，不能回写成已验证的历史结果。
证据：[MCU源码对照](../../../../outputs/rk3568-mcu-baseline-20261003/README.md)及
[接口说明](../../../../platforms/rk3568/boards/aiot-3568pq/MCU-INTERFACE.md)。

## 2026-10-04：ARM64 首启加载范围与原厂 FDT fixup 需运行读回

适用本RK3568原U-Boot2017.09和已锁定源码5.10 Image/DTB，换启动固件或Image需重查。
加载地址按实际ARM64头部text_offset和含BSS的image_size规划，不能用文件长度或Android boot header代替。
本次手工加载/booti400000，原厂仍打印kernel_addr_r280000到400000搬移消息，复制长度未运行采样；
不据消息判断完整Image搬移，最终iomem才证明运行范围。
fdt_high全1不关闭厂家fixup；运行memory reg补零到192字节，DTB自保留、原no-map和logo/LUT须分别读回。
编译后审计与四项故障注入已覆盖保留区遗漏；短时shell通过不证明普通关机、硬实时或长时稳定。
PMIC microvolts为驱动selector换算，外部反馈DDR500000不代表物理轨电压，不能为日志猜改电压。
证据：[源码内核实机记录](../../../../outputs/rk3568-source-kernel-20261004/README.md)。

## 2026-10-04：RT SysRq 日志刷新与持久化 chroot 分阶段核验

适用锁定RK3568 5.10.160-rt89树及本轮RAM bootstrap，换内核/printk实现或用户空间后重查。
本轮SysRq b实际栈在外层RCU读锁内经kmsg_dump/pr_flush进入msleep，触发调度警告后仍返回Android。
成功复位不能代替上下文正确性或正常关机验收；无日志积压的旧窗口不证明同一路径安全。
定位时检查所有调用者持锁状态，不能只检查pr_flush位于kmsg_dump自身读锁之前。
后续最小修正用rcu_preempt_depth排除主动睡眠，原函数回归先失败后通过，新Image同SysRq路径一次复位无告警。
该API在本锁定PREEMPT_RCU树不依赖lockdep；不使用关闭DEBUG_LOCK_ALLOC时恒真的rcu_read_lock_held，
也不使用RT中恒0的sched_rcu_preempt_depth。无进展预算可随进展重置，不将1000ms写成全局墙钟上限。

Android私有namespace与独立Linux中chroot PTY测试都需要显式提供/dev/pts；仅bind /dev不保证已有子挂载跟随。
普通ext4文件先只读loop加ro,noload验SHA，再完整清理后重新RW挂载、同步及清理；RW阶段会写底层cache。
本轮该顺序已板测并在Android回读标记通过；旧轮ro而未noload的历史结果不回写。
证据：[源码用户空间往返](../../../../outputs/rk3568-source-userspace-20261004/README.md)、
[复位栈](../../../../outputs/rk3568-source-userspace-20261004/reset-warning.txt)。
修正及一次板测：[RCU日志等待对照](../../../../outputs/rk3568-rcu-reset-20261004/README.md)。

## 2026-10-04：源码 Wi-Fi 模块、最小 WPA 和无线传输分层确认

适用锁定RK3568 5.10.160-rt89树的BCMDHD O=构建及本次WPA2-PSK工具；换源码/配置后重新核实。
BCMDHD的$(src)在O=构建中可能为相对路径，头文件-I需按srctree解析；
单独保留原BCMDHD_ROOT/DHD_COMPILED语义，不能把一个绝对路径同时当包含目录和发布版本字符串。
同release不保证模块匹配：本次完整配置字节相同、实际Image SHA相同、284项UND在vmlinux导出表闭合后才上板。
当前模块debug段仍有构建路径，源码可重建不等于产物已完全脱敏或跨机器逐字节一致。

本次wpa_supplicant2.11的CONFIG_NO_CONFIG_WRITE=y也删除update_config解析，helper标准输出需在启动前适配；
没有CONFIG_DEBUG_FILE时不能用-f。真实QEMU解析、板端认证和DHCP验证该构建，不推广为所有WPA版本的规则。
静态glibc链接的NSS警告仍单列；数值地址通信成功不代表域名/TLS兼容性已验收。
认证/DHCP/网关与电脑ARP/TCP是不同层次：本次前者成功，后者未过，信号差和固件漫游只作观察而非已确定根因。
两次串口批量Base64内容被转成小写；原因未定位。小写hex方案经完整SHA重读通过，不能据此判定所有串口Base64都不可用。
工具等待超时后检查完整capture与独立SHA读回，区分早返回和真实损坏。

证据：[源码Wi-Fi对照](../../../../outputs/rk3568-source-wifi-20261004/README.md)与最终source/input/effective-member SHA记录。
新的归档、无线条件、固件、编译选项或传输路径均须重新验证，历史地址/PID/关联状态不能当当前可用性保证。

## 2026-10-04：源码 rootfs 的文件属主、RAM 临时目录与随机数入口

适用本 RK3568 锁定 5.10 和离线 ext4 文件/chroot 流程；换生成器或随机数实现后重查。
mkfs.ext4 -d 会保留宿主 staging 文件属主，不能仅看目录或生成时用户推断 rootfs uid/gid0；
本次逐项修正并用 debugfs 核对常规/链接/目录及保留 inode，实际非root inode篡改会被审计拒绝。
chroot只读根并不能保证临时认证/DNS/日志在RAM；本次显式bind RAM/tmp，实际写probe后完整image SHA不变，
运行目录内部链接也逐项核对。loop所有权和每个已释放mount flag独立跟踪；失败后只重试剩余项。

WPA -v也可能读取urandom；本次53秒提示CRNG未就绪，但未进行认证，不能写成弱随机认证事件。
HW_RANDOM_ROCKCHIP已编入而DT的rng disabled，说明检查配置不能代替驱动绑定与CRNG就绪检查。
本锁定random.c的getrandom NONBLOCK以EAGAIN区分未就绪，普通getrandom和/dev/random读取等待就绪；
下一次认证前须直接确认接口就绪，不能用固定等待或单看entropy_avail替代。
证据：[源码 rootfs 往返与源码调查](../../../../outputs/rk3568-network-rootfs-20261004/README.md)。

## 2026-10-04：BusyBox 模块参数与条件性 Wi-Fi 传输

适用本轮BusyBox1.36.1最小配置及锁定BCMDHD源码；更换工具、配置或固件后重查。
FEATURE_CMDLINE_MODULE_OPTIONS=n会把普通insmod的命令行模块参数展开为空字符串。
命令返回成功、模块存在不证明参数生效；本次两项可读参数仍为默认值，配置路径也为默认。
真实旧/新BusyBox对象重链接到不转发的syscall mock，观察旧版丢参数、新版传递及finit→init回退；
仅开启该选项的新正式构建与QEMU通过，尚不能代替新版本板测。

DHD_REQUEST_FW_PATH启用时，固件请求路径会转basename；本轮使用启动RAM根/lib/firmware/config.txt。
仅PM=0的5byte配置解析成功而电脑ARP/TCP未过；随后只加band=a（5GHz only，非band=1字符串），
实测保持5220MHz并通过64KiB三端SHA传输。roam_off=1原本就是默认，重复写它不形成新行为对照。
频段限制通过不等于ARP根因确认，成功配置也未证明重连/休眠/长时网络可用。

清理函数放进if !调用时，不能指望set-e自动终止函数内部步骤。
本次真实shell mock red删除readlink显式return后发生误kill；显式守卫拒绝它，并继续独立资源清理。
证据：[RNG与网络分层记录](../../../../outputs/rk3568-rng-network-20261004/README.md)、
[BusyBox构建与实际对象测试](../../../../outputs/rk3568-rng-network-20261004/busybox-module-options-manifest.json)。

## 2026-10-04：串口枚举与RAM收尾的错误读取边界

适用本板锁定5.10 DW8250/N_TTY及已检查的kernel/params.c string参数，不推广为所有设备接口。
物理TTY即使O_RDONLY/只做tcgetattr也会startup；默认N_TTY ECHO可自动TX。
枚举只读sysfs/proc、实际console/pinmux及短计数窗口；probe和寄存器诊断仍可能改硬件状态。
本轮ttySMT0→ttyS0按fdd50000/driver/of_node/4:64核对，未打开物理串口；PTY通过不证明电机停止或反馈。

`test -z "$(command)"`不能检查command读取成功：本轮losetup失败7、grep失败2空输出仍被旧门槛接受。
收尾先显式成功赋值读取，再检查内容；非RAM挂载/读取失败/资源残留拒绝。18真实脚本mock与实机门槛通过。
此copystring setter直接strcpy输入，getter追加换行；写换行“恢复空串”实测getter0a→0a0a，
命令替换会删除尾换行掩盖失配。仅该已确认参数用单NUL恢复并验原字节；最终脚本避免无必要的参数改写。
新BusyBox模块参数已实机验证；实际旧/新applet集合均52，此前51为计数描述错误。
证据：[UART0和新版RAM实测](../../../../outputs/rk3568-motor-alignment-20261004/README.md)。

## 2026-10-04：传感器绑定、厂商I2C布局与RAM工具身份

适用锁定RK3568传感器框架及精确原Android Image/RK3x路径；更换Image/控制器须重新核验ABI。
原sensor_register_device吞probe errno会留下驱动symlink；实际WHO读取失败且无input。
修正短传输/读错误和probe传播后，Linux -ENXIO不再产生假绑定；两系统均未验收ID05。
驱动绑定、节点存在、模块insmod成功各自不能代替身份/初始化/输出验收。

原Image的i2c_msg stride实际24，标准ARM64为16；内核版本号不能证明厂商UAPI布局。
按实际反汇编确认字段偏移和控制器使用路径后，才使用显式且固定地址的专用布局。
本次尾部8byte语义未知，只在精确审查路径上清零；ENXIO不证明器件缺席或特定硬件故障。

最小工具集按实际BusyBox binary的applet集合检查，而非默认发行版经验。
本RAM版本没有id/base64，须在模块加载前核验依赖、上传后SHA和脚本退出状态。
PID1 comm实测init，不能假设执行sh时comm必为sh；本轮核验exe/argv/ELF SHA。
证据：[源码修正、ABI与两系统实测](../../../../outputs/rk3568-accelerometer-20261004/README.md)。

## 2026-10-04：CAP1188 SPI身份、HS pinctrl与RAM失败清理

适用本次锁定BSP/原Image与CAP1188；其他芯片与SPI协议不能照搬。
CAP1188不是通用regmap SPI帧，官方连续CS身份读为7d/reg/7f/7f，最后字节有效；
每个身份寄存器独立SET ADDRESS，SPI_IOC_MESSAGE返回字节数而非transfer个数。
原厂input注册无已证身份门槛；实机messages3/errors0仍读产品/厂商00，SPI零错误不是器件ACK。
身份/输入/复位/事件单列，00根因须供电与波形，不固化成“芯片缺席”或“Linux驱动坏了”。

spi-rockchip按父时钟选high_speed，低事务速率也可能切换；normal/HS均须核对原板引脚。
本次实机HS由function spi3-hs标识，group仍叫spi3m1-pins；不能臆测节点名后缀。
精确最小BusyBox的ls省owner/group，major/minor为第3/4列；不同工具构建必须重新核对，非通用Linux列数规则。

退出清理不能让cwd留在即将umount的目录内；校验或部分cp失败尤其要测试。
本次真实脚本fixture复现旧cwd清理失败，先cd /后18项通过；仅成功路径释放不覆盖失败路径。
一次性身份尝试用原子mkdir占位，失败结果也不自动重试；残留mount/FD/loop/module与读取错误拒绝返回门槛。
证据：[SPI源码诊断与实机拒绝结果](../../../../outputs/rk3568-cap1188-20261004/README.md)。

## 2026-10-05：ASoC子设备的regmap所有权与接口验收

适用本RK3568锁定5.10 RK808/RK817 MFD与codec；换ASoC/regmap实现须重查生命周期。
regmap_init_i2c的设备查找devres可以挂在父I2C设备，child上的devm action仅释放map可能留下父lookup。
本轮独立负对照复现该残留；最终借用原PMIC map、不分配/释放，component只解除自身关联，32导入闭合。
不能以component_exit_regmap替代“detach”，它会释放map；父RBTREE缓存也使chip日志不等于新鲜总线身份。
ASoC component自身probe失败后不保证调用其remove，覆盖的失败路径要在probe内释放时钟/mutex/指针。

控件INFO/READ可只返回软件缓存，OFF不是电气静音验收；未打开PCM仍有probe GPIO/MCLK/reset写。
卡注册异步，首次proc/cards缺卡要和后续身份/PCM/sysfs证据一起解释，不将一条早读当最终失败。
卡号/numid须动态匹配，未知controls仅LIST；生产helper自行5秒SIGALRM，不能假定最小BusyBox有timeout。
module引用1可能来自已注册card，不等于打开PCM；本轮以无音频FD+exact module/ref与成功快照做返回门槛，
模块保留到SysRq，未据此验收rmmod或正常关机。OF的codec DMA mask dev_warn也不证明PCM DMA成败。
证据：[RK809源码、错误路径与接口实测](../../../../outputs/rk3568-audio-20261005/README.md)。

## 2026-10-05：PCM 配置、持久时钟状态和精确工具行为

适用锁定 RK3568 5.10 I2S TRCM1 与本轮最小 BusyBox；换驱动/工具后重查。
HW_PARAMS 改 rate/parent，而 runtime_suspend 只 disable/unprepare；不能把关闭后
时钟文本不完全相同直接认作引用泄漏。逐行核对预期持久配置、enable/prepare/protect、
控件、runtime 与 FD；本轮三个 inactive RX clock 保留 12.288MHz，16行的引用均恢复。
DMA debugfs 只有 client bindings，不证明 descriptor 队列、callback 或电气静音。
PCM OPEN/REFINE/HW_PARAMS/HW_FREE 成功不能代替 PREPARE/START/声音验收；
后者会进不同 mute/DAPM/DMA 路径，错误传播和异步释放需另查。

本最小 BusyBox 的 sleep 不支持小数，不能只经宿主 shell -n 判断依赖可用。
实际目标 binary 参数测试与上板失败证据都确认整数 sleep1 可用、小数0.1拒绝。
PowerShell→WSL 内联 Python 的反斜杠层次曾把串口 octal escape 变成 NUL；
保存生产源、验证命令 ASCII 及目标 printf round-trip，再用完整 SHA 拒绝损坏内容。
证据：[PCM 配置与独立关闭核验](../../../../outputs/rk3568-audio-runtime-20261005/README.md)。

## 2026-10-05：真实 DSI host 返回值与串口执行边界

适用锁定 DW-DSI host 与本轮 Windows 串口执行器；换 host 或 transport 重新验证。
DSI short packet返回packet.size=4，long返回4+payload；不假设正返回等于payload长度。
早期fake边界绿色在真实host链失败，最终只传播负errno；host全序列完成不证明面板ACK。
固定panel的connected也不是检测实物，PWM enabled+duty0不是电气熄灭。

shell检查结束marker可在exit1前出现；生产session须等待真实exit0后独立marker。
stage早期失败也必须已有独立RAM guard与固定attempt，不能依赖可能未复制完成的返回脚本。
本轮本地shell可以执行多行wrapper，而实际串口执行器明确只接受单行ASCII；
保持多行可读脚本，单独传RAM+SHA后单行调用，验证必须覆盖真实执行器预检。
长串口流实测丢字节，按小片段读回、长度/完整板端SHA核对，不从宿主输入猜补。
证据：[显示候选与实测](../../../../outputs/rk3568-display-20261005/README.md)。
本次正常reboot通过的是特定RAM内核/连接条件下device_shutdown往返，不推广为poweroff/MCU/电源轨已验。

## 2026-10-05：PID1 返回岛、实际 exec 与 BusyBox job control

适用本板锁定原生 PID1 与最小 BusyBox1.36.1（52 applets，SH_STANDALONE未启用）；换工具配置或监督器后重查。
切根后的 exec 失败恢复测试须在新进程加载保存的实际状态，不能用同一进程残留 globals 代替；
exec 失败的 resume 要重新身份核验并重试 exec。真实内核还需单独验证 mount/loop/console。
返回岛只有 BusyBox ELF 不足以让 shell 的 PATH 找到 applets；在切换前建立精确白名单 symlink，
逐条失败注入须拒绝 READY/exec。v2 实机返回后 sha256sum not found，v3 原生建52链接完整往返通过。

BusyBox交互 job-control 父shell可持 FD10 /dev/tty（字符5:0），guard自身FD10却是脚本regular file。
不能泛化允许所有用户进程TTY/regular FD；要核 parent/PPid1、pgrp/session、精确ELF SHA、
FD号/目标/fstat类型与major/minor，PID1仍只准console0/1/2。九种fixture与真正RAM guard验证通过。
不能把native监督器自己的READY单独当收尾证明：独立核mount、loop、module、未知process/FD后再普通reboot，
每次绑定封存产物SHA与实际串口证据；构建时未板测manifest保持，现场另写结果。
证据：[PID1 v3实测及v2人工协助边界](../../../../outputs/rk3568-pid1-20261005/BOARD-RESULTS.md)。

## 2026-10-05：Android bootm 的最终树与部署版地址分支

适用本板锁定U-Boot SHA4758af21…125447e和Linux v2 RAM包；换启动器/包/早期DT后重新核查。
overlay OK只证明当次apply，不能证明内核最终采用该树。实际第一次试验随后重读资源DT，
最终bootargs_ext缺失、mode退回；完整树SHA/语义审查明确拒绝，即使Linux运行与返回都成功。
部署二进制比较env fdt_addr_r与fresh gd FDT，相等跳过第二次读。第二次只恢复临时A100000，
最终整树958节点/4891属性及overlay保留、native往返与Android七SHA完成71/71。
这不推广为通用U-Boot地址约定或正式boot_android/AVB/USB恢复证明；CLI前早期输入另核。
UART丢字只缩小片段并核总长/完整板端SHA，失败原流保留拒绝，不由输入补猜。
证据：[两次试验与部署分支](../../../../outputs/rk3568-bootm-ram-20261005/BOOT-PACKAGE-REVIEW.md)、
[第二次完整汇总](../../../../outputs/rk3568-bootm-ram-20261005/linux-candidate-result-v3.json)。

## 2026-10-06：ASoC 初始化与 async runtime PM 的终结阶段

适用本板锁定 5.10.160 I2S checked lifecycle 与 PM 核心；换核心、异步策略或调用顺序须重查。
set_fmt 中 pm_runtime_put 是异步请求，worker 可能在原 out 清 configuring 前执行。
checked_suspend 返回 -EBUSY 后核心恢复 ACTIVE 并清错误，无 autosuspend expiration 时未自动重试；
实际 usage0、auto、activekids0 和 error0 不能证明 suspended 或时钟引用已释放。
正常 power/control on→auto 可诊断性重请求 idle，但不能据此宣称自然初始化验收或放宽 guard。
新增成功终结 phase 仅在全部 MMIO 完成并发布 first sticky 后允许 suspend；其他配置/START/销毁限制保持。
旧代码红例、新 format/pthread 90 项与关闭/参数 48/140 三环境 fresh 编译通过；新完整Image/精确ABI codec
进入第四轮RAM试验后，首次自然suspended/自有MCLK0/IRQ排空与严格guard0通过，未执行PM on→auto诊断。
两向分别有限传输、关闭、正常解绑与回Android保护SHA核回通过；不外推全双工、物理声音或正式刷机。
播放raw存在一处合并残行，仅94条WRITE可完整辨认；保留summary/START/退出/guard证据和日志完整性限制。
证据：[第四轮实际对照](../../../../outputs/rk3568-audio-runtime-20261005/build/board-results-20261006-v4/result.json)。

ASoC 合法 shutdown 会提交 sysclk0；在已 STOP/IRQ 排空且两 substream 空时只清请求缓存，
下次参数配置要求重新提交正频率。v11 实机旧 close -22 消失，不能推广为声音或全双工验收。
证据：[v3 板结果与诊断边界](../../../../outputs/rk3568-audio-runtime-20261005/build/board-results-20261006-v3/result.json)、
[v12 源码和 fresh 模型复核](../../../../outputs/rk3568-audio-runtime-20261005/REVIEW-CPU-v12-20261006.md)。

## 2026-10-06：ASoC失败事务与PM引用的真实归属

适用锁定5.10.160 ASoC调用链，尤其正常close与尚未activate的失败startup并发。
active数为零不证明没有在途startup资源；生产单指针mark_open/startup/module不能用理想化每方向标记替代。
原失败路径unlock后再clean重锁的窗口，真实函数模型复现peer close覆盖标记、child-clock和CPU指针漏清。
持锁startup清理也不自动修复锁外PM get/put单指针mark_pm，必须分别验证本调用取得和归还的每个引用。
get_sync返回错误仍先增加usage；-EACCES按原ASoC语义接受且也持引用。失败prefix自回滚后，
所有caller的get失败路径不得再fullput，包含实际Image未启用但共享源接口的compressed分支。
同device不同component出现多次时，不能将引用按device去重；保持每次取得一次归还。

主控真实57函数fresh三环境复现24业务红例/68观察；后补作者25/76基线已独立版本冻结。
主控后续fresh v5为25红/76观察×3；四源候选真实68/70函数模型红0/25、绿21/25，
110观察（74唯一标签）×3由主控fresh重编译核等。实际Kbuild与独立/主控全量seal核回后离线源码接受。
四项双向START/共同STOP失败保持；PM core、CCF、调度等边界仍是显式API模型，尚未本候选板验。
PM平衡不等于callback排空/remove许可，同DAI active门不推广RK817 voice共享缓存或泛型pinctrl在途安全。
证据：[主控红例](../../../../outputs/rk3568-audio-runtime-20261005/build/root-asoc-baseline-v4-v1/result.json)、
[设计和实际调用者边界](../../../../docs/superpowers/specs/2026-10-06-rk3568-asoc-open-rollback-design.md)。

实现证据：[主控候选复跑](../../../../outputs/rk3568-audio-runtime-20261005/build/root-asoc-candidate-v2/result.json)、
[离线接受边界](../../../../outputs/rk3568-audio-runtime-20261005/REVIEW-ASOC-OPEN-ROLLBACK-20261006.md)。
compressed两宏手动源码分支检查不能推广为Kconfig生成或压缩ABI证明。

## 2026-10-06：完整Image之后的外部模块输入闭合

适用锁定SDK9f9e9d18574d与本轮audio-v4；换SDK、配置、编译器或选集后重新取证。
源码inventory文件的SHA已锁，不等于当前参与编译的headers/scripts已匹配；必须核固定选集的完整键集合、
模式、字节数和SHA，missing/extra文件也拒绝。prepared-inputs不能覆盖固定codec C/H的mandatory锁。
本轮用Image89423 tracked库存对SOURCE6360普通+4文件link+13DTC目录link逐项闭合。
目录link只接受已核SDK路径/文本/内部普通target及祖先，不递归target，也不把它们算普通文件。
用is_file过滤链接会漏目录link；但不能因SDK目录link合法而放宽普通包输入的祖先检查。

完成Image后立即保存current generated ABI有限全量旁证，模块用私有影子make、原输入前后核等。
本轮2020普通文件/模式/尺寸/SHA与root文件快照相同；文件快照未复制空目录时不要用目录全等替代文件集合证明。
这是Image完成后的current旁证，不是编译当时签名全ABI。MODVERSIONS=n时实际无__versions，
imports/vermagic/精确源码头文件核回不宣称运行时CRC校验或安全卸载。
原源码的共享ASoC helper实现变化没有改变公开结构/接口，也仍须用新Image的实际两symvers重新审模块。
证据：[本轮实际模块与边界](../../../../outputs/rk3568-audio-runtime-20261005/REVIEW-CODEC-IMAGE-v4-20261006.md)。

## 2026-10-06：Windows读取WSL时的普通文件门

适用于从PowerShell读取本项目的WSL UNC路径、核备份和缓存输入。实查SDK符号链接的LinkType可为空而
Attributes含ReparsePoint；普通目录的LinkType又可显示HardLink。不能仅靠LinkType判定符号链接，
也不能把目录HardLink标签直接视为目录链接。逐文件和每层目录（含workspace root）检查ReparsePoint，
并核叶文件/祖先目录类型；PS provider属性与原生DirectoryInfo对象也应区分。
新reclaim/stage两个实际函数的普通备份接受和真实SDK符号链接拒绝已通过，首次目录假阳性保留。
证据：[有限host门回归](../../../../outputs/rk3568-audio-runtime-20261005/build/root-stage-host-preflight-v5/result.json)。
这不取代Linux端lstat、完整SHA和固定板路径检查，也不授予递归删除或刷机。

## 2026-10-06：精简板端shell的工具与原始结果恢复

适用：当前RK3568 RAM native rootfs的BusyBox1.36.1 shell。实际PATH里base64和wc不可调用，host/Ubuntu具备命令不证明该板shell可调用；未核全部compiled applet，不扩大为所有BusyBox构建结论。首peer程序真实返回0且生成完整34OP后，wrapper的wc计数失败；只补postguard和读回原stdio，不能为了外围检查重跑设备程序。原stdout/stderr/exit均用板stat/fullSHA与完整hex帧导出。一次1024B块失字只重读该真实范围四个256B块，缺口/重叠不一致拒绝，不补猜字节；正式collector须接受实际有限分块协议。

证据：[本轮实机记录](../../../../outputs/rk3568-audio-runtime-20261005/SESSION-20261006.md)、[原捕获输入](../../../../outputs/rk3568-audio-runtime-20261005/build/board-trial-v5-inputs-r2.json)。失效条件：rootfs工具/PATH或传输协议改变后重新探测，不能把本轮缺命令固化为通用Linux限制。

## 2026-10-06：ASoC终端清理要覆盖完整文件关闭

适用固定5.10.160 BSP及本次checked codec。实际soc_pcm_clean_locked先DAI shutdown，
再component.close；shared_open/owner清空不证明后者已结束。实际core cleanup先
snd_card_disconnect_sync等待files_list清空，再执行component.remove。process shutdown
helper沿既有unregister的client_mutex稳定借用，文件等待期间不能持card->mutex，
因为实际DPCM close还需该锁；codec私锁也应先释放。文件等待的超时只约束该段，
现有disconnect、delayed-work flush及card free不可冒称同样有界。
真实函数有限模型与actual Image/新canonical module构建已通过，尚无新实机关机证明。
SDK/文件生命周期、caller锁或profile改变时重新审查；不能推广为所有声卡或平台的排空保证。
证据：[终端设计](../../../../outputs/rk3568-audio-runtime-20261005/full-duplex-shared-io-candidate-v1/TERMINAL-DESIGN-v5.md)、
[最终软件记录](../../../../outputs/rk3568-audio-runtime-20261005/SOFTWARE-PROGRESS-20261006.md)。
