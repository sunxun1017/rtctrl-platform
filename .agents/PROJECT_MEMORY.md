# rtctrl-platform 项目记忆

更新时间：2026-10-08。用于新任务接续工作；不是运行中设备的实时状态。

## 先读哪里

- 格式门禁（2026-10-08）：原先 53 个第一方源码格式问题已修正，全仓 `format-check` 已通过；release/ASan 各 41 项、人脸 12 项回归通过。此前记录中的格式失败属于修正前的历史状态。
- [RK3568 Android→Linux 当前验收](../platforms/rk3568/boards/aiot-3568pq/ADAPTATION-STATUS.md)：最新v5有限实机通过；完整迁移未完成。源码历史与其它板卡结果分开看。
- [项目地图](skills/rtctrl-dev/references/project-map.md)：模块、适配器和构建入口。
- [已验证经验](skills/rtctrl-dev/references/lessons.md)：历史问题、适用条件和失效边界。
- [Git 管理](skills/git-advanced-workflows/SKILL.md)：项目级 Git skill，覆盖提交、分支、冲突与恢复；
  2026-09-21 从固定上游版本安装并适配，来源和许可证见 [记录](skills/git-advanced-workflows/references/sources.md)。
- [视频程序说明](../apps/face_recognition/VIDEO.md)：采集、推理、浏览器预览的实际实现。
- [最近缓存与 swap 实验](../outputs/cache-swap-20260912/README.md)：原始数据、对照和限制。
- [上一轮 ftrace 证据](../outputs/ftrace-20260912/)：调度、NEON、模型副本释放。

## 协作偏好

默认中文，先复用已有代码和已验证经验。优化同时观察 CPU、内存、NPU、帧率与丢帧；用 perf/ftrace 等证据定位，不凭百分比猜原因。
2026-09-29 用户明确要求脚本（如 sh）按结构分行、便于阅读；具体约定见 [脚本可读性](skills/rtctrl-dev/SKILL.md#脚本可读性)。
后续机器人以Linux为主线，用户明确要求解耦平台化、业务与核心不依赖具体硬件；芯片/板级差异放可替换适配器和配置数据。Linux路线不自动等同采用上游mainline内核。
2026-10-03 用户要求 RK3568 Linux 可公开构建，优先消除厂家定制黑盒；通过接口分析与独立实现替代，继续先 Android 基线再 Linux 对照。
判断依据为实现源码、构建输入与许可证；`.so` 后缀不代表闭源，静态封装预编译实现也不算去掉黑盒。仍需的芯片固件/loader 显式登记。
修改按独立主题分批本地提交，提交说明写清问题、改动、测试条件、实测收益和限制；推送需有当前授权。
实验也整理进用户的 Notebook 音视频项目笔记，采用记笔记者的自然口吻，不写成授课或宣传稿。Notebook 是独立仓库，路径在当前环境确认，不假设其他机器存在。
新登记、修改人脸库及重新开始长时间采样，都先核实本次任务范围；历史请求不当作永久运行授权。

## 已验证的最近状态

平台为正点原子 RV1126B（不是 RV1126），Linux 6.1.141；当时 RKNN runtime 2.3.2、驱动 0.9.8。使用 native-fp16 输入、RGA direct 转换和 MPP 异步 JPEG。启动方式以视频说明与现场脚本为准。

2026-09-12 最后部署的是缓存预取版本，证据在 [manifest](../outputs/cache-swap-20260912/manifest.json)。板卡后来是否重启、运行哪个二进制，需要重新检查，不沿用旧 PID。

| 改动 | 本地提交 | 可复用结论 |
|---|---|---|
| 精确缩放 NEON | e20f64a | 保留 OpenCV 3.4.5 算术与几何约束，108 个板端用例逐像素一致 |
| 释放模型文件副本 | 5dcfe23 | 仅普通 flags=0 加载；特殊零拷贝模型加载不能照搬 |
| ftrace 与内存记录 | 7cf167e | 等待不等于忙碌，NPU busy 百分比不等于算力利用率 |
| 有界源行预取 | 64c931b | 缩放约快 19%，整机单脸带 PMU 短测 CPU 37.568%→37.119%，不能混用 |
| 缓存与 swap 证据 | 2ceac25 | 当时无 swap、无回收压力，因此没有更改 VM 参数 |

最终 60 秒单脸复核：30.039 FPS，平均 CPU 35.707%（单核 100% 口径），PSS 40053–40086 KiB，NPU 平均 23.75% / 800 MHz。采集间断、队列覆盖和读流错误均为零。这个窗口没有同时采硬件 PMU，不能与带 PMU 窗口直接作差；不代表浏览器绘制帧率或长期稳定性。

## 不能忘的实验边界

不要删除必要 DMA 缓存同步来压低 CPU。保留帧和 MPP task 的所有权约束，不能释放仍被硬件或异步消费者持有的缓冲。
比较性能先对齐人脸数、分辨率、模型、读流客户端和追踪开销；不要累加不同轮次收益。PSS 与全局 DMA-BUF 字节数不直接相加。
PMU refill/access 是事件比例，不能直接认作应用精确命中率。缓存预取没有改变 NPU 计算量。
模型进一步优化已暂停；长时间峰值和稳定性尚无本轮结论。需要重新安排测试时先确定场景和时长。

## 新任务接续

先检查 git 状态、当前分支和上述提交是否存在。按实际任务读取代码和对应证据，再核实板卡连接、程序 PID、二进制及模型校验值。旧记录作为基线，不代替现场。
若在新 worktree 工作，确认它包含这份记忆及最新已合并的优化提交。任务结束只更新发生变化的状态，保留短测与未验证项的边界。

## 2026-09-21 帕奇硬件与Linux平台化候选

三页框图明确AIoT-3568PQ/RK3568，GD32F303负责六路TB6612电机；当前只有框图，
原Android设备树后续提供。未连接原机、未生成可部署DTB/镜像。
通用prepare-linux-config.py读取显式JSON；SoC片段与板级外设片段分离，不内置具体硬件或RT策略。
通用collect-linux-hardware.sh只读标准proc/sys/DT资料，有逐项缺失和错误状态。
锁定5.10.160 BSP上93项配置及headers通过、7项驱动对象AArch64交叉编译通过；
release/asan本轮完整各39/39，审查修复后BSP两组各2/2（22+18用例），全仓格式仍有原有失败。
当前缺口包括CAP1188的SPI适配、SH3001、实际屏时序/电源/音频描述符及MCU安全语义。
依据见[板卡说明](../platforms/rk3568/boards/aiot-3568pq/README.md)与
[验证记录](../docs/verification-linux-platform-20260921.md)。另一并行任务负责Android协议codec，
其验证单列于[协议记录](../docs/verification-patchx-protocol-20260921.md)，不把封帧成功视为电机可运行。

并行协议任务已从Android参考commit ed91ef7确认发送封帧，实现独立rtctrl_patchx_codec叶子库：
固定容量编码/流重组、无SoC/设备路径/物理IO依赖，不实现虚假的IActuatorProtocol安全语义。
该任务独立release/asan各40/40通过，最终codec专项复跑通过；新增C++格式检查通过。
MCU真实返回帧/ACK、使能、停止与watchdog仍未确认，没有板端运行或升级操作。

2026-09-21 PC补验（代码提交88bccd4）：真实PosixSerialTransport接PTY发现VMIN=0/VTIME=0空闲read返回0被误判Closed，
改VMIN=1并保留O_NONBLOCK后空闲、碎片双向收发、CRC恢复、关闭/重开及HUP通过。
Host release和ASan/UBSan完整各41/41；GCC11.4构建的AArch64 codec/PTY/Dynamixel经
QEMU user6.2及Ubuntu ARM64运行库执行3/3，无跳过。QEMU的PTY仍由宿主Linux提供，
不证明厂商UART、板级启动、外设或实时性能；未连接真机。命令和证据见
[PC/QEMU验证](../docs/verification-pc-qemu-20260921.md)。

## 2026-09-18 交互终端

新增独立非实时 `apps/companion`，说明见[使用入口](../apps/companion/README.md)、
[验证记录](../docs/verification-companion-20260918.md)及[ADR0009](../docs/adr/0009-companion-nonrealtime-service.md)。
云端语音按住说话、Opus/ALSA、浏览器二维表情、只读人脸状态、错误恢复与打包已实现，
没有修改原有视觉算法或实时核心。默认演示与静音，网络断线不自动恢复采集。
原Android后端本次握手支持24kHz播放；16kHz录音与输出采样率独立配置。
新增56项测试通过、release/asan各16项CTest通过（网络依赖明确安装后单独复验）。
浏览器PC/800×480验收通过；WSL后端静音20秒短测未发音频。
已部署实物1GB板（约970MiB），依赖与后端握手通过；人脸约30FPS并发静音短测通过。
直接16kHz单声道采集出现零DMA进展，48kHz双声道+专用ALSA plug转换后成功上传音频。
实际语音识别/回复仍未通过：realtime/PTT上传101帧无STT，固定文字detect回显+tts.start后45秒无回答或音频；需后端日志。
已补空录音快速报错、realtime尾静音及电平统计，66项测试通过。详见验证记录的板端追加章节。
离线唤醒、AEC、自动打断、LCD和语音运动未实现。
后端地址、网络与板卡状态需重新核实，不沿用短测作为当前可用性保证。

## 2026-09-18 Wi-Fi 配网

新增独立ConnMan适配和控制台“网络设置”，默认wifi_enabled=false；当前板端测试配置明确启用。
开启Wi-Fi、扫描、连接、断开均需显式操作，scan不隐式enable。网络作业独立于语音线程，密码不进argv/日志/应用文件。
ConnMan可按系统机制保存成功认证凭据，应用关闭不撤销daemon已接收的网络操作。
用户本轮要求“先做好功能，暂不连接”：仅真机扫描验收，发现11热点、connected_wifi=0，有线连接保留。
13项网络回归通过，release/asan各17项CTest通过；真实认证/DHCP/重连尚未验收。
安卓侧实际系统配网服务com.patchx_sys不在参考仓库中，Linux实现不假定其内部二维码/蓝牙机制。
证据见[验证记录](../docs/verification-companion-20260918.md)与[使用说明](../apps/companion/README.md)。

## 2026-09-18 产品诊断与服务生命周期

语音增加voice_progress与分阶段超时，tts.start不代表已经收到音频；原后端故障仍未解决。
ConnMan网络状态5秒只读刷新、过期撤销；用户“暂不连接”的限制继续有效。
新增deploy/companion/service-control.py、SERVICE.md与可选S95模板；未安装开机启动项。
有界日志约192KiB、PID身份校验、进程组退出；崩溃不自动重启。
最终99项companion测试通过，release/asan CTest各18/18通过。详见验证记录追加章节。
已在实物执行启动、重复启动、停止、再次启动和重启；最后状态supervisor7090/child7091，
HTTP offline/muted/idle，音频帧0，人脸服务976仍约30FPS。PID仅当时快照，下次重新核实。
板端service.env权限0600；运行目录/run/rtctrl-companion；访问仍依赖临时SSH隧道。
剩余后端闭环、实际Wi-Fi认证（本轮禁止连接）、LCD、离线唤醒/AEC与长时间验收见
[产品检查清单](../docs/companion-readiness.md)。不把本轮宿主测试当作整机量产验收。


Android鉴权复核：板端确实配置了与安卓一致的测试Bearer令牌；但Device-Id使用rtctrl-rv1126b，
不同于MainActivity2初始化SN。Linux hello未发安卓的client_ip/trace_id，未上传云端人脸user_id。
完整绑定/鉴权是否通过仍未知，不能仅凭hello/tts.start把无回答断定为服务端模型故障。
本次未改身份、未连接MQTT、未采音；源码行号及边界见验证记录“Android鉴权对照复核”。


## 2026-09-18 声音与屏幕

新增device.py及/api/device、控制台折叠设置。device_settings_enabled默认false，demo强制不触碰硬件；
当前板端测试配置已明确开启。支持0dB封顶音量、扬声器两开关、0–24dB分档麦增益、10–100%背光。
显式应用、写后读回、失败回滚，不采音/播放测试音，不自动保存重启配置。amixer使用sget/sset simple控件名。
112项companion测试通过，release/asan CTest各19/19通过；真机四项调节/读回后恢复原始值。
当时实际扬声器底层spk switch=off（Speaker=on），没有自动打开；UI如实显示关闭。
最后音量raw191、增益raw8、背光raw200/255；服务静音离线，人脸约30FPS。详见验证记录的声音与屏幕章节。


千帆替代后端探测：用户授权的Key在WSL调用ernie-4.5-turbo-32k成功（固定短句，12tokens）；
ASR dev_pid1537和TTS per5003均明确返回无权限。仅用固定文字/生成静音，未采集用户语音。
密钥未写盘或部署，不记录其值；用户需开通/授权语音能力，才能验证完整替代方案。
原板卡后端未切换；不能把千帆Key直接发给原Android服务器。详见验证记录。


## 2026-09-18 本地中文语音已接通（覆盖上节旧后端状态）

当前board-test为live/local：板端Zipformer INT8 ASR + AISHELL3 VITS sid0 TTS，千帆仅收文字。
公开5.61秒音频端到端跑通：STT2.71秒、LLM5.14秒、首音频事件10.54秒，157帧/9.42秒回复。
模型常驻约346MB，整机约529/970MB；模型目录142MiB。原生8kHz，试听自然度待用户确认。
启动约34秒，健康检查防止过早准备；未采集用户麦克风，本次aplay固定试听exit0。
板扬声器已开启、音量85%，麦增益24dB和背光78%不变。页面本地就绪/麦静音，人脸约30FPS。
用户授权的千帆密钥现仅保存在板端0600 service.env，不入仓库；之前“未部署”已过时。
当前云联网依赖WSL CONNECT代理18080+SSH反向隧道，板时钟本次校正；独立联网和重启时间同步待做。
不连接Wi-Fi限制仍有效；不改图库、不装自启动、不动机械控制。旧Android配置板端备份。
release/asan各21项CTest通过；安装、来源/许可/哈希、限制见deploy/companion/LOCAL-SPEECH.md，
详细实测见docs/verification-companion-20260918.md最新章节。PID与内存均需下次重新核验。


## 2026-09-18 perf与语音资源优化

板载perf确认主要为ONNX SGEMM/线程池；现PCM用NumPy批处理，worker单独MALLOC_ARENA_MAX=2。
local_speech_threads严格1/2，最终2；单线程ASR2.84s/TTS5.68s明显慢于双线程。
修复完成ACK早于busy释放的偶发连续请求失败；10轮20次最终基准全部成功。
热ASR中位1.848s，TTS3.300s/RTF0.6492，多轮workerRSS387.9MiB，空闲CPU近0、推理约200%（单核口径）。
这覆盖上一节“约346MB”的短时资源快照；不把初轮低RSS当长期上限。人脸仍约30FPS。
新增可复现profile-speech.py及页面worker CPU/线程/峰值RSS，进程重启/失败清除统计基线。
release/asan22项CTest通过，最后修复重跑两套9组companion通过；当前150用例有执行证据。
format-check依旧被原有未修改C++格式问题阻塞。原有不连接Wi-Fi、不动人脸图库/执行器的边界未变。
证据见docs/verification-companion-performance-20260918.md及docs/performance/companion-20260918。


## 2026-09-18 本地对话音质对齐

用户对照聊天“音色一”；板端同为sid0。修复本地TTS8k→16k→Opus→PCM的非必要有损路径。
现在PcmAudio持有原始bytes/rate，经Core local-only门控→AudioIO→aplay原生rate→ALSA48k；Android不变。
有界45秒、单个PCM任务、generation中断、EOF等待真实drain（期限考虑缓冲时长），不传临时文件路径。
真机原试听WAV78326PCM字节进入aplay逐字节一致，rate8000，5.174秒完成并回idle，无错误。
155项companion用例有通过证据。用户主观听感仍待重听；电脑和开发板扬声器不能视为相同声学条件。
本地audio_frames_received现在是PCM任务计数而非60ms帧；不套用旧Opus帧数验收。
证据见docs/verification-companion-20260918.md“对话与音色一播放对齐”。


## 2026-09-18 整机资源/NPU与录音路由

已核实ASR/TTS均CPU provider，NPU为独立人脸进程/dev/rknpu，负载10–11%、800MHz。
四核整机CPU空闲约8%，语音推理约50–62%；UI新增整机CPU/NPU，语音200%仍为单核口径。
板载Main Mic为INPUT2/ADCR右ADC；原plug平均左侧闲置通道损失约6dB。
已新增rtctrl_es8389_capture右路录音别名并切现场capture_device，播放别名不改。
PGA厂商驱动实际支持0–42dB，UI解除旧24dB限制，6dB步长；现场暂36dB、数字0dB、ALCoff。
三次短测仅内存统计不留原音频/不上传。增益能放大底噪约4倍，但近距10–20cm语音仍弱，不能声称完全修复。
第一轮右峰值588、平均296.5；第二轮右映射36dB峰194；连续采集证实增益有效，需核实实际麦克风/偏置/硬件。
UI峰值增加dBFS与幅度百分比；0dBFS不是目标，满幅有削波风险。161项companion用例有通过证据。
详细统计及SDK源码/ALSA路由证据见docs/verification-companion-20260918.md最新章节。


## 2026-09-18 实验NPU ASR已接入

用户要求迁移ASR/TTS：原CPU CTC INT8转换被DynamicQuantizeLinear实际阻塞；改用Model Zoo RV1126B Zipformer。
现场local_asr_backend=rknn，代码默认cpu可回退。三个非量化RKNN已上板，TTS仍AISHELL3 sid0 CPU。
5.6115s公开样本CLI含加载中位1.3084s；应用socket单轮1.589s文本正确，随后CPU TTS生成成功。
worker短测RSS172.38MiB、整机358–365MiB，人脸约30FPS（本轮无脸）；非长期/准确率验收。
VITS decoder分拆已转NPU并板测，0.512s波形约5–8ms，相关系数0.999842；整句接缝/试听未验收，未切TTS。
用户重启后手动恢复服务、时钟、临时隧道和音量85%/麦增益36dB/扬声器；未安装自启动或持久混音器保存。
release/asan各9组companion通过。来源/哈希/回退/边界见[验证记录](../docs/verification-speech-npu-20260918.md)。


## 2026-09-18 TTS整句数值验收

两句真实中文经sherpa实际前端捕获单批tokens，用同一latent对比CPU/NPU整句decoder（L100/180）。
3.2/5.76s样本相关系数0.99999446/0.99999714，误差SNR48.92/51.37dB，无削波、长度相同。
整句一次推理无拼接；板端decoder含IO中位31.746/52.991ms，非端到端延迟。
两版回识别一致，长句正确、短句都有同样偏差；不等于主观音质满分。试听WAV已提供。
当前CPU TTS保持，任意长度集成和主观试听仍待验收；见[整句记录](../docs/verification-tts-sentences-20260918.md)。


## 2026-09-18 用户否定现有TTS自然度

用户指出AISHELL3 CPU/NPU整句都逐字吐音、不连贯；先前数值对齐不代表产品音质通过。
进一步试听原sid0 speed1.15/noise0.35与Kokoro INT8 sid3，用户明确“两份仍然不自然”，不得记为已认可候选。
审计确认整句一次生成、#0是上游标准且承载有声内容，不能删除。逗号边界和上下文变调存在前端不足，非已确定唯一根因。
先选用户认可的整句自然度，再评估板端资源与NPU；当前生产TTS未切换。
证据见docs/verification-tts-naturalness-20260918.md。


## 2026-09-18 用户接受Melo，板端已启用混合NPU TTS

此项覆盖上文“当前CPU TTS保持”。用户认可Melo完整对话连贯性，已部署local_tts_kind=melo_npu、sid0。
ASR仍NPU；Melo中文前端/flow在CPU，decoder FP16在NPU，44.1kHz PCM，256bucket/16halo/224core。
短句2.9s声音：CPU26.49s降至混合3.41s；完整对话7.895s声音生成9.28s；进程峰值272.8MiB，不含全部DMA。
8段真实板端latent数值SNR47.76–51.27dB，后处理长度全部对齐；板端扬声器主观听感待用户确认。
先前AISHELL3整句原始decoder及调参试听遗漏ScaleSilence，不代表完整应用输出；已纠正并说明。
本次每个完整sherpa批次才ScaleSilence(.2)，168组上游C++对照逐样本相同。
正式worker健康检查/固定文字输出成功；release/asan各10组companion通过。原模型/配置备份可回退，未改自启动。
依据：[Melo验证记录](../docs/verification-tts-naturalness-20260918.md)。


## 2026-09-18 Melo perf/ftrace优化已验证

在57b0176的Melo基础上，192帧NPU块+禁ORT空转+容量1队列并行CPU前缀/NPU解码。
热3轮中位短句3.352→2.805s、长句9.129→6.573s（-16%/-28%，不含ASR/云/播放）；总CPU秒基本持平。
峰值RSS约271MiB，人脸仍30FPS；模型初始化约21s未变。单线程更慢，保持双线程。
板端decoder.json选192，256模型及旧库/代码备份保留；新ABI含melo_decoder_frames，Python/库必须配套。
8段真实latent及946帧长样本192/256逐样本相同；流水线476084样本与串行完全一致。
ftrace使用独立instance且清理，全局trace不变；nospin早期512KB trace丢事件不作为调度证据，最终2048KB无丢失。
perf在此BSP需等目标退出收尾；复用工具profile-melo.py采用父控制器+独立benchmark子进程，避免附加自身后等待死结。
结论与测量边界见[性能验证](../docs/verification-melo-performance-20260918.md)。


## 2026-09-18 RKNN ASR流式与连续对话

现有Zipformer改常驻native，跨PCM块保留缓存；local_asr_streaming默认false、板端true。
公开5.61s样本首partial1.178s、约0.96s更新、6.84s输入触发端点；空音不发云、reset重放一致。
真实应用接ASR+Melo夹具测试成功，用户麦克风/云端本轮未调用。新增17用例，release/asan各15组通过。
连续模式显式开启，播放drain后恢复；静音/失败/断连撤销，控制台15s租约到期静音。
ASR native RSS约17MiB不含NPU，整机准备后约681/970MiB（未加载ASR约550），人脸约30FPS。
属于停顿断句而非语义标点；仍无AEC/唤醒词/直接说话打断。Melo音色不变。
旧CLI与配置可回退；证据与限制见[流式验收](../docs/verification-streaming-asr-20260918.md)。


## 2026-09-18 对话延迟与流式TTS

固定文字实测千帆1.47–1.56s，TLS/代理0.07–0.18s；回复21–22字原TTS3.49–4.54s，主要为合成等待。
Melo新增原完整batch回调、worker PCM流、单aplay连续写，默认2s预缓冲避免0.4s首片播完等后片的空档。
板端local_tts_streaming=true（全局默认false）；固定长句TTS首批中位6.726→2.300s，短句2.588→2.265s。
并非整体对话提速66%；TTS总生成6.384s仍在，音色/参数/采样率不变。真实固定句扬声器drain完成、无欠载日志。
新增每轮latency_ms及页面分段显示，首次写管道不等于声学首音。release/asan各16组通过。
用户麦克风本轮未开启；证据/回退见[延迟验收](../docs/verification-voice-latency-20260918.md)。

### 2026-09-18 AEC

已接普通Rockchip VQE CPU软件参考AEC，固定16ms缓存延迟，默认关闭、板端纯AEC实验开启。一次明确授权安静声学测试测得21.07dB能量降低，AES25.16dB；未保存/上传录音。真人双讲和自动插话未验收，automatic_barge_in仍false。配置、边界、回退及测量条件见 [AEC记录](../docs/verification-aec-20260918.md)。

真人双讲后续：两轮本地内存测试完成，严格播放重叠12秒中原始固定句完整匹配0、纯AEC1、AES2；证明该次人声可识别地保留，不等于逐字/全部重复无损。AES跨轮波动，配置仍纯AEC；automatic_barge_in仍false。详情见同一AEC验证记录。

### 2026-09-18 连续模式静音资源

已增加前置PCM能量起音门控及480ms缓存，安静等待不送RKNN ASR、不周期finalize，UI显示等待说话；模型仍常驻。不是语义VAD，较强持续噪声可能误触发。lease/静音保护仍有效。验证范围见 [静音门控记录](../docs/verification-speech-gate-20260918.md)。

### 2026-09-18 全双工持续识别

连续模式新增独立ASR listener与回复worker，回答期间实时识别新一句，最多3句排队，等当前播放排空再回应；不自动截断播放。板端启用full_duplex及AEC+AES：纯AEC安静全链路误触发1句，AES安静测试0句；真人15秒测试播放中6次partial、最终完整固定句1次。模型ASR/TTS并行固定输入无错；边界、回退和数据见 [全双工验证](../docs/verification-full-duplex-20260918.md)。上述测试仅本地桩回应，未将测试音频/文字发送云端；真实云端全双工用户体验仍需日常验收。

### 2026-09-18 全双工回声误提交修复

用户实际反馈AES仍会把自己播放的回答识别为新问题，之前单次安静通过不代表可靠防回声。新增播放重叠期文字EchoGuard：近期播放的同句/近似子句标疑，禁止自动排队/云端提交，用户可绑定候选ID确认或忽略。数字回灌真实RKNN+core验证final1被隔离、reply仍1；真实安静一轮未产生回声文字，不能冒称声学问题完全解决。保留full duplex+AES，证据与边界见 [回声保护记录](../docs/verification-echo-guard-20260918.md)。

2026-09-18：千帆SSE按短句与Melo并行，新增首PCM/缓冲计时，见[流式延迟验证](../docs/verification-cloud-stream-20260918.md)。固定问题短测尚无稳定首音频加速；1.2秒缓冲出现470ms供应空档，生产保留2秒，不能宣称已解决高延迟。

2026-09-18：修正控制台window.blur误关闭连续对话；普通失焦仅松开按住说话，真实页面隐藏/pagehide与15秒保活到期仍静音。未主动开启麦克风测试。

## 2026-09-18 统一设备入口

用户明确同意撤下独立8092控制台，统一8080；开启standalone_voice后浏览器关闭/隐藏不再停止连续对话，此授权覆盖早期浏览器租约要求。新服务仍默认静音，错误和主动静音停采音。
8080产品入口包含首页摄像头/表情、设置、状态、日志；人脸原二进制/参数迁到127.0.0.1:8081，未改图库。远端需8位配对，回环/SSH可信，二维码只带地址；不改当前Wi-Fi连接。固定事件/内核摘要有界，不保存对话/录音/密钥，应用日志重启清空。
见[部署与回退](../deploy/companion/PORTAL.md)、[验证记录](../docs/verification-device-portal-20260918.md)。未安装自启动/自动AP，原千帆电脑代理依赖仍在。

2026-09-18：手机访问二维码改按实际无线接口优先选址，不再继承当前网页Host（有线访问曾错误生成有线码）；设置页分别显示无线与有线地址。无无线IPv4时回退已有接口。

2026-09-18：用户再报首次回复被回识别。修复 core 同轮 partial 已命中回声但 final 改写后自动放行：
保留本轮疑似标记至识别结束，沿用确认/忽略；新轮及释放清理，保持全双工。
本地 duplex core 15项通过，release/asan各24组companion通过；后续经用户授权已单文件备份部署并重启。
板端语法/导入/哈希核验通过，语音已准备且静音、无错误，人脸短时约30FPS；未采音，首次声学改善待用户验收。
见[回声保护追加记录](../docs/verification-echo-guard-20260918.md)。

## 2026-09-28 Android RK3568 原机资料已采集

用户要求实际操作并保留命令与输出，已从CH340串口以1500000/8N1读取原机：3568A、Android11、Linux4.19.232 #49，
不同于此前离线5.10.160候选；`su 0`可只读采集。原始FDT151680字节与整包均经板端/主机SHA-256一致性验证；
完整运行树6276条目、内核配置6197行；运行树与原FDT节点属性一致，仅缺FDT头部两项memreserve。
证据入口：[采集记录及命令输出](../outputs/android-board-20260928/README.md)、[设备树分析](../outputs/android-board-20260928/device-tree-review.md)。

运行时确认：DSI720×720；SPI3 CAP1188已绑定/event0；MXC6655已绑定；Bothlent USB声卡8通道16kHz S16_LE采集；
RK809板载声卡存在；UART0为/dev/ttySMT0，不能沿用/dev/ttyS0。DT WiFi声明ap6398s，SDIO02d0:a9bf绑定bcmsdh_sdmmc。
OV5695、Goodix、RJGT102有节点但未见driver绑定；不能据此断言器件未装，也不称其正常。
GD32串口连接/协议、实际WiFi模组料号与摄像头功能仍未核实。
本次只读硬件元数据、板端新增临时采集目录；未刷机、重启、发MCU指令或主动采音/采帧。
完整固件分区、厂商源码、完整上电日志未取得；不将反编译DTS视为已可部署Linux配置。

### 2026-09-28 无原厂 BSP 重建首轮

用户明确原厂BSP不可得，授权在项目内重建。新增AIoT板级firstboot-candidate.json与bsp/源码，使用锁定5.10.160的SoC DTSI，
不包含EVB板级DTSI；原机供电/pinctrl/IO域重建，198项属性与原FDT一致。特别vccio4/6为1.8V，不能照抄EVB3.3V。
FIQ1500000、eMMC52MHz、USB2 host为本轮候选；UART0、显示/CSI2、WiFi、GPU/NPU和DDR调频关闭。
90项配置审计、49项DTB审计、8项错误注入、10个AArch64驱动对象通过；DTC新增板级警告0。
实际SUSPEND=n会触发该BSP eMMC runtime-PM条件编译错误，保留SUSPEND=y、DT休眠节点disabled；不能说系统休眠能力全局关闭。
无Image/initramfs/板测/刷机；manifest仍deployable=false。loader、启动镜像格式/AVB、恢复路径与内存fixup待核实。
入口：[重建说明](../platforms/rk3568/boards/aiot-3568pq/RECONSTRUCTION.md)、[全部命令与验证](../outputs/rk3568-reconstruction-20260928/README.md)。

### 2026-09-28 首次启动产物准备（尚未上板）

已构建5.10.160 ARM64 Image（34888192字节）、最小静态BusyBox initramfs，与首轮DTB组成离线候选。
完整构建需要PREEMPT_RT及保存的cache.h包含顺序补丁；非RT缺migrate_tasks，RT原树有WARN头文件循环。
补丁保存在板目录patches，构建后已反向移除，third_party源码干净。QEMU仅验证ARM64用户态shell，不是内核/板测。
产物摘要、命令、失败/成功输出见[启动准备记录](../outputs/rk3568-boot-preparation-20260928/README.md)。
原boot已校验头部为Android v2，另有second和dtb段；头部地址不视为已确认加载地址。
原boot/uboot/trust/dtbo/vbmeta已复制到板端普通临时文件并打包，但串口丢字节导致整包未回传，不能称恢复备份完成。
串口日志级别曾临时调整并确认恢复7/4/1/7，未重启/刷写。用户明确当前只有串口；USB OTG、恢复入口、完整启动链与首次启动仍待核实。

随后用户明确要求关机并按独立主题分批提交。已执行`su 0 setprop sys.powerctl shutdown`，串口最终确认`reboot: Power down`。
原厂shutdown驱动打印关闭MCU看门狗及写入断电标志的动作；未取得MCU应答或电源测量，不能据此确认写入生效/整板掉电。
MCU与GD32/UART0的对应关系、内核交接时看门狗状态尚未确认，见[电源生命周期适配](../platforms/rk3568/boards/aiot-3568pq/POWER-LIFECYCLE.md)。
关机命令和输出摘要见[启动准备关机记录](../outputs/rk3568-boot-preparation-20260928/README.md)。
Git只保存精选报告/脚本/配置/审计证据；原机标识、二进制产物与原始串口流保留本地，未随提交分发。

2026-09-29：根据原FDT与buses.txt生成[原机设备树框图](../platforms/rk3568/boards/aiot-3568pq/DEVICE-TREE-DIAGRAM.md)。
复核既有证据：I²C5 mcuinf@62 compatible=smdtmcu,STM8S00K3，5-0062已绑定McuCom；此前对MCU接口的表述过于笼统。
该I²C板控节点不与UART0/GD32混同；关机函数源码对应、协议及ACK仍未确认。此次未连接/唤醒板子。

2026-09-29：用户确认PatchX-Android-Main仓库有权限；本地WSL SSH的git ls-remote已成功，默认master及HEAD
为ed91ef7486cdebca00aa32d497f5aa45cb226c0e，与此前协议审计版本一致。旧网页404不能表述为仓库无法访问。
命令和结果见[协议审计补充](../docs/verification-patchx-protocol-20260921.md)，后续远端版本仍需重新查询。

## 2026-10-02 RK3568 原机 SD 启动可行性

用户当前无SD卡、以后会取得，要求先核查SD启动。通过本次重新枚举的CH340/COM5、1500000/8N1
只读核验：原机仍为Android11/4.19.232 #49；SDMMC0 fe2b0000为okay、supports-sd、4bit，实际mmc0 host存在，未枚举SD卡。
只读原uboot分区找到U-Boot2017.09（2026-03-12）版本字符串，以及mmc1→mmc0的默认目标、
rkimg_bootdev的rkimgtest/Boot from SDcard分支和extlinux扫描脚本。
这些是分区内字符串，不是运行中的printenv或SD启动日志；U-Boot编号、实际启动顺序、镜像格式及插卡启动仍待验证。
现有firstboot DTS仍禁用sdmmc0；SD rootfs需要另行补板级配置。可行性较强，但没有SD启动成功结论。
本轮未重启、刷写或改启动配置，原Android继续运行；历史恢复备份与OTG入口缺口未解除。
证据与实际命令见[SD启动核查](../outputs/rk3568-sdboot-assessment-20261002/README.md)。下次重新核验端口与板端状态。

## 2026-10-03 RK3568 原机网络传输已验证

用户授权配网后，本次重新枚举 CH340/COM8，通过串口将原 Android 板连接至电脑同一路由；
网络 ADB 显示 device，root shell、3568A/4.19.232 查询及36644字节内核配置拉取通过，板端/主机 SHA-256一致。
ADB查询时已监听5555，本轮没有更改端口或认证；地址、端口及串口号下次必须重新核实。
原机串口回显和输入标志已核对恢复，printk已确认恢复7/4/1/7。凭据没有保存到项目或采集日志。
当前用户选择复用原4.19内核及配套设备树，先跑最小Linux用户空间；已找到SD卡，但实物卡座仍未确认。
约定路径下的boot-original.img本次不存在，本轮仅验证小文件网络传输；未刷机、重启或操作电机。
本次信号偏弱，尚无大镜像传输或启动/恢复验证。结果与条件见[网络验证记录](../outputs/rk3568-network-20261003/README.md)。

## 2026-10-03 RK3568 启动备份及最小 Linux 板测通过

用户授权备份并尝试Linux；15项启动相关文件已回传电脑、逐项SHA-256验证。包含原boot/uboot/trust/dtbo/vbmeta、
eMMC前4MiB引导区/末尾GPT、boot0/boot1及其他启动元数据。不是完整eMMC备份；recovery/super/userdata/oempriv未备份。
大文件网络传输停滞，关闭TUN后路由核实为WLAN直连，但ADB仍曾离线；最终串口8192字节逐块校验及整包SHA通过。
不能据此把全部失败归因于代理。

实机进入U-Boot2017.09，确认eMMC为mmc0，cache为0:c；先reset返回原Android11，再进行RAM启动。
复用原4.19.232 Image、运行FDT及静态BusyBox initramfs，加载/CRC通过；仅修改内存FDT/环境，未saveenv或刷写启动分区。
已独立启动Linux：PID1为/bin/sh /init，串口命令正常，根目录为最小用户空间，挂载仅rootfs/devtmpfs/proc/sysfs/tmpfs。
确认无持久化块挂载后用SysRq即时重启，返回Android11且sys.boot_completed=1；五个启动分区SHA再次一致。
最终网络ADB root shell可用，串口已释放，printk恢复7/4/1/7，MTU1500。串口号/地址/状态下次必须重新核实。

此结果替代此前“启动备份未回传、未板测”的当前状态，不改变旧记录的历史事实。
未验证完整Linux发行版、全部外设、正常关机/MCU看门狗生命周期或裸机刷写恢复；未发送电机命令。
当前方向仍为原4.19内核上的持久化rootfs与生命周期适配，不将已构建5.10候选视为本次启动内核。
证据入口：[备份与板测记录](../outputs/rk3568-backup-linux-20261003/README.md)、
[机器可读结果](../outputs/rk3568-backup-linux-20261003/boot-result.json)、[脱敏Linux输出](../outputs/rk3568-backup-linux-20261003/linux-runtime-check.txt)。

## 2026-10-03 RK3568 持久化用户空间与 Wi-Fi 固件板测通过

用户要求传输慢时先在原 Android 验证驱动/库基线，再迁移到 Linux，按依赖与小型功能测试逐项推进。
本轮收集驱动绑定、实际固件请求、六个 AArch64 Android 库的 ELF 依赖及现有进程映射；未将映射当作功能验收。
这些 Android/Bionic/HAL 库不能直接作为普通 glibc/musl Linux 的库；后续选 Linux build 时仍需核对原驱动 ABI。

原 4.19.232 Image/FDT 与新静态 BusyBox RAM bootstrap 已实机启动；64 MiB 普通 ext4 文件位于 cache 实验目录，
仅格式化该新文件。PID1 仍在 RAM，镜像用于子进程 chroot，未做 switch_root/自动启动 Linux。
Android 写标记→Linux 读标记并写新标记→完整卸载/普通内核 reboot→Android 只读重挂回读，SHA-256 全部一致。
cache 可能被清理，正式 rootfs 介质和恢复策略尚未确定；文件、端口、地址和状态下次重查。

原 bcmdhd.ko 与两份固件在板内复制、SHA 核对，Linux 固件/NVRAM打开成功、Firmware 7.45.96.150、wlan0 UP/LOWER_UP。
成功方案在 RAM/chroot 两侧提供同一 /vendor 固件路径，用无换行 printf 设置 firmware_class.path；排错和版本边界见证据。
未在独立 Linux 验证路由关联、DHCP/传输；NPU v0.7.2、ISP/声卡及 MCU/输入绑定仅对照枚举，未推理、采集或驱动执行器。

结束时模块、rootfs/cache 挂载和本轮 loop 已释放，普通内核 reboot 返回 Android11、boot_completed=1；
原 boot/uboot/trust/dtbo/vbmeta SHA 再次一致，printk恢复7/4/1/7，网络ADB root可用，串口已释放。
没有 saveenv、刷写启动分区、提交或推送；MCU ACK、看门狗接管与真正关机仍待验证。
入口：[板测与复现说明](../outputs/rk3568-persistent-linux-20261003/README.md)、
[迁移矩阵和验收顺序](../outputs/rk3568-persistent-linux-20261003/MIGRATION.md)、
[机器可读结果](../outputs/rk3568-persistent-linux-20261003/result.json)。

## 2026-10-03 RK3568 厂商黑盒与源码路线审计

已核对参考 Android commit ed91ef7 的串口 Java/Jar：libserial_port 是四项串口包装，
SmdtManagerNew 经 Binder 调用 smdtserver；现有 POSIX 串口与独立 codec 可作为替代入口，实机 MCU 往返/安全语义仍未验。
参考仓库未找到 LICENSE/NOTICE/COPYING，不将原 Jar/二进制或私有参考文件按本仓库 MIT 重新发布。

本轮小文件回传并 SHA 核对原 /system/lib64/libmcuencryption-lib.so，静态发现两个 JNI 接口、/dev/rjgt102 和 ioctl。
现场设备节点不存在，运行 DT 为 okay、驱动目录存在但未绑定；三个现有进程 maps 未匹配该库。
尚未确认实际调用者、业务必要性及设备 ABI，不能认作电机协议；未调用库、未知 ioctl 或执行器。
原二进制与分析参考仅留在忽略的 private 目录，不公开内部密钥数据。
参考 Java 还声明 patchx-face/video_process/speekerid/ovrlip_bridge，仅有预编译库、未找到 C/C++ 实现；列入独立替代清单，未完成算法对照。

默认 CMake 闭包无厂商运行库；完整人脸应用仍只有 RKNN 生产推理后端，CPU 图像转换与测试 Fake 不算 CPU 推理。
RGA/MPP 有源码候选，未匹配本板 ABI；RKAIQ 存在预编译 AE/AWB 回退，RKNN、Wi-Fi 固件、DDR 与 MCU 固件源码缺口单列。
原 4.19 是二进制过渡基线，公开源码 5.10 候选只有构建结果、尚未上板；不改变前阶段板测事实。
本轮只做审计和迁移顺序更新，没有新的替代实现或功能验收，没有重启、刷写、提交或推送。
证据：[审计与后续顺序](../outputs/rk3568-open-source-audit-20261003/README.md)、
[机器可读摘要](../outputs/rk3568-open-source-audit-20261003/audit.json)。

## 2026-10-03 RK3568 独立源码接口对照通过

后续用户授权继续：原 Android 和独立 RAM Linux（原 4.19/FDT）中，同一份静态 AArch64 codec、
POSIX PTY 测试及新独立 C 缓存诊断均通过，返回 Android 后通过串口再次运行一致。
三项用户态程序无厂家 Jar/Binder/JNI/.so 运行依赖；仍调用原内核二进制，不是完整开源内核或电机控制验收。

现场确认 McuCom 为 I²C5/5-0062、字符 10:61；运行 FDT 的 skip-mcu 布尔属性为真。
原 Image 静态分析确认 skip 路径跳过身份/版本/watchdog/线程，寄存器 helper 无总线操作而返回255；
部分上层可能仍打印成功，旧关机日志不能当成实际写入/ACK。
原驱动 open/release 无硬件效果，0xc0 用65字节缓冲返回六个内核缓存字节；新程序 O_RDONLY、单次0xc0，
Android/Linux 均全零，仅是缓存结果。未查询物理MCU，未主动执行原 mcu_tool或下发动作/升级/watchdog/断电请求；
普通reboot仍会经过原内核生命周期回调。
两个约30秒被动窗口无目标I²C事件，UART0/4计数不变；第二次调度正对照10条且零丢失，不能推广为无MCU活动。

Linux 仅临时挂 cache/devpts，独立短命令确认清理和空loop后普通reboot返回Android11/boot_completed=1。
五个启动分区SHA仍一致，printk7/4/1/7、kptr_restrict2、root tracer0/nop、原wifi instance，串口已释放。
实际只读cache挂载为ro，不能排除ext4日志回放；后续脚本改ro,noload但未重新上板验证。
网络ADB未恢复：adbd运行、wlan0有IPv4，但TCP超时及板端路由器ping丢包；下一轮重新核验供电/串口/网络。

新接口事实：[MCU接口说明](../platforms/rk3568/boards/aiot-3568pq/MCU-INTERFACE.md)；
实测、复现脚本和当前边界：[源码对照记录](../outputs/rk3568-mcu-baseline-20261003/README.md)、
[机器摘要](../outputs/rk3568-mcu-baseline-20261003/result.json)。
原二进制/地址符号/反汇编/raw均仅在忽略的private；无提交/推送。
下一阶段仍需源码5.10基础上板、电源生命周期与真实运动反馈，不能盲发命令14当作停止。

## 2026-10-04 RK3568 源码5.10内核首次实机启动通过

用户充电并重新连接后，重新核验串口/Android/root/网络，初始电量59%，AC/USB powered仍为false。
源码Image沿用已记录的5.10.160-rt89-g9f9e9d18574d-dirty：锁定commit加cache/KASAN补丁，未重新编译Image。
本次补齐DTB的高地址256MiB no-map、原loader logo/LUT保留区；重新CPP/DTC/审计，新增四项故障注入，总计12项通过。

Android只写新建普通cache文件，经SHA核对；U-Boot2017.09现场确认mmc0/cache0:c与bdinfo。
Image/新DTB/initramfs逐项加载CRC通过，内存环境/FDT变更后booti进入源码Linux shell。
Image实际头部text_offset=0、内存跨度0x21e0000；手工加载/booti400000，原厂U-Boot仍打印280000→400000搬移消息，
最终iomem确认400000-25dffff；日志源地址取自kernel_addr_r，复制长度未运行采样，不据消息判断完整Image实际搬移。
运行树保留no-map、logo/LUT及新initrd范围，memory reg被U-Boot补零至192字节。

PID1为/bin/sh /init；挂载只有rootfs/devtmpfs/proc/sysfs/tmpfs；eMMC枚举但未挂载Linux块文件系统。
fan53555-regulator/rk808/rockchip-iodomain/rockchip-thermal绑定，温度37.222→36.111℃，uptime199.19秒。
有SCMI17/22、RGA、MFD子节点等警告，短窗口未匹配panic/Oops/BUG/Call trace，不代表长时/实时/全部外设验收。
PMIC缺反馈属性的日志含未初始化变量；vcc_ddr500000为selector表值，不能当物理DDR电压或猜填约束。

RAM-only guard后请求SysRq即时复位，返回Android11/4.19.232，boot_completed=1/root，五个启动分区SHA仍一致。
未saveenv/刷写启动分区/发送运动指令/提交推送；UART0与I²C5/MCU禁用，未验证正常device_shutdown/poweroff/watchdog。
原DDR/loader/trust仍为二进制，不能宣称完全开源整机。结束摘要电量58%，printk7/4/1/7、kptr_restrict2，串口已释放。
返回后网络ADB超时；串口确认adbd运行、wlan0有IPv4，但路由器ping2次全丢。地址/串口/供电下次重查。

最新证据：[源码内核首启](../outputs/rk3568-source-kernel-20261004/README.md)、
[机器摘要](../outputs/rk3568-source-kernel-20261004/result.json)、
[运行读回](../outputs/rk3568-source-kernel-20261004/linux-runtime-check.txt)。
当前5.10状态替代旧“候选未上板”的当前判断，旧构建manifest与各阶段历史结果保留。
下一步收敛最小配置/确定性日志，再迁移源码诊断与持久化用户空间，按Android基线恢复外设并独立验收MCU生命周期。

## 2026-10-04 RK3568 新源码内核与持久化源码用户空间对照通过

重新核验后，网络ADB在准备与返回阶段恢复/root/传输可用，随后再次offline/TCP超时。
最终通过串口确认Android11/4.19.232、boot_completed=1/root、adbd运行、wlan0有IPv4；串口已释放。
结束电量52%，AC/USB powered=false，不能当稳定外部供电证据。运行地址/端口/状态下次重查。

本轮从锁定5.10 commit重新编译Image，新增RK817缺反馈属性的诊断修正；寄存器分支和值不变。
最终配置关闭RK817 charger、multi-RGA、SCMI power-domain/reset客户端，保留SCMI clocks/CRU reset等基础驱动。
Image SHA为b230838582b655f7786564ff21670ab1cd29172488df9c367a77d7005708c260；release与前轮相同，不能据release混用产物。
SCMI17/22及RGA启动警告未再出现，MFD缺of_node等警告仍在；53项DT审计、12项故障注入及诊断失败/成功读取测试通过。

新64MiB普通ext4文件位于独立cache实验目录，原rootfs保留。Android与新源码Linux运行同一codec/PTY静态程序均通过；
Android标记→Linux回读/写标记→清理挂载及loop→SysRq返回Android→只读noload回读，两份SHA一致。
Linux先只读loop/ro,noload验证，再重新RW挂载cache/rootfs做测试；只有完整清理后才RAM-only。
PID1仍在RAM，新rootfs只供chroot，未switch_root/自动启动；无厂商用户库、原4.19模块或物理UART/MCU调用。
五个启动分区完整SHA前后一致，未saveenv/刷写启动分区/电机命令/提交推送。

SysRq复位出现RCU睡眠警告：外层SysRq读锁内 emergency_restart→kmsg_dump→pr_flush→msleep；
调用栈与锁定源码吻合，发生于硬件复位处理前。本次随后成功返回Android，但正常重启/关机/MCU生命周期仍未验证。
下一阶段先处理SysRq/printk上下文与网络稳定性，再做正式rootfs和外设验收，不能把阶段成功当完整机器人移植。
最新入口：[源码用户空间板测](../outputs/rk3568-source-userspace-20261004/README.md)、
[机器结果](../outputs/rk3568-source-userspace-20261004/result.json)、
[复位警告](../outputs/rk3568-source-userspace-20261004/reset-warning.txt)。

## 2026-10-04 RK3568 RCU 日志等待修正与同路径复位板测

已新增第三补丁：pr_flush的may_sleep排除rcu_preempt_depth，普通进程仍睡眠、RCU读侧使用原非睡眠等待。
真实pr_flush/pr_msleep函数测试先在原源码复现失败，补丁后RCU嵌套、普通进展/超时、原子/softirq/早期/零超时等通过。
锁定树API不依赖lockdep；保留原无进展预算重置语义，不能称总等待最多一秒。
新完整Image SHA=e7a95d9fc5a3e87f407145cbadaf0cb2c787c637b2311c4ff551a73f8b8fa457，
配置/DTB/initramfs与上一轮字节相同；release相同仍以SHA区分。第三方源码已恢复干净。
构建入口失败清理也已改为逐项尝试/成功清flag，真实补丁临时树故障与重试测试通过。

新Image已实机启动，PID1仍RAM；cache仅ro,noload挂载并运行相同源码codec/PTY，两者通过。
未执行本轮持久化rootfs写入/chroot。卸载后独立RAM/loop guard通过，SysRq b在83.932秒复位，
完整Linux复位记录未再捕获RCU警告或Call trace，返回Android11/4.19.232、boot_completed=1/root。
只有本次一次复位，板端没有分支计数插桩；普通reboot/关机/MCU/长时/实时性仍未验收。
五个启动分区完整SHA前后一致，没有saveenv/刷写启动分区/运动命令/提交推送。

开始ADB offline但adbd确实监听，网关邻居FAILED且ping全丢；关闭/开启已保存Wi-Fi后重新关联，
ADB root及新Image传输恢复，返回后网络ADB root再次通过。未改认证/密码/代理/路由器或持久网络配置。
收尾串口已释放，printk7/4/1/7、kptr_restrict2，电量45%、AC/USB powered=false。
此检查时ADB可用不代表长期稳定；地址/端口/串口/状态下次重核，原固件缺口仍单列。
入口：[RCU修正板测](../outputs/rk3568-rcu-reset-20261004/README.md)、
[机器结果](../outputs/rk3568-rcu-reset-20261004/result.json)、
[复位摘录](../outputs/rk3568-rcu-reset-20261004/reset-excerpt.txt)。
下一阶段按原Android基线恢复源码Wi-Fi并独立验收，再推进正式rootfs/启动入口和电源生命周期。

## 2026-10-04 RK3568 源码 Wi-Fi 分层板测（部分网络验收）

沿用已板测的RCU修正Image（e7a95d9f...8fa457）和字节相同的完整配置，新增独立Wi-Fi DTS。
SDIO fe2c0000按原机GPIO2_B1 pwrseq/GPIO2_B2 host-wake/PMIC 32kHz时钟恢复；
编译后90项审计、12项故障注入通过。没有猜SDIO电源轨；UART0/I²C5/MCU仍禁用。
同源码bcmdhd模块284项未定义符号在实际vmlinux导出表闭合，实机加载/绑定，SDIO实际148.5MHz。
第四补丁只修模块O=构建头文件路径，构建后第三方源码已恢复干净，没有重新编译Image。

上游wpa_supplicant2.11/libnl3.11.0及独立C helper静态交叉编译；QEMU/PTY失败清理与半行信号测试通过。
最小WPA构建需删update_config行，日志由shell重定向；实际无Android厂商用户库依赖。
两份原机firmware/NVRAM逐项SHA核对，Firmware7.45.96.150，仍保留芯片固件二进制依赖。
首次WPA2-PSK/CCMP COMPLETED、DHCP地址/路由/DNS地址配置和网关ICMP通过。
电脑TCP双向传输未通过：对端ARP未解析、两次连接超时；BSSID限制后仍固件漫游，
直接2.4GHz重连后来出现-87/-86dBm、停在ASSOCIATED及连接失败/断开；未采到明确认证超时原因。
根因未确认，不能认作已稳定联网或全部归因于信号。

ADB准备期间间歇失败，最终helper-only叠加归档通过串口小写hex上传并SHA重读一致。
实测v5为两个gzip/newc流，后者只覆盖helper；新完整归档重建需要重新板测，不能沿用本次SHA。
认证凭据仅RAM、未写宿主日志；收尾确认凭据删除、WPA/helper退出、bcmdhd卸载和wlan0消失。
Linux全程没有块挂载，RAM/loop guard后SysRq返回Android11/4.19.232、boot_completed=1/root；
五个启动分区完整SHA仍一致，printk7/4/1/7、kptr_restrict2，最终网络ADB root可用、串口已释放。
结束电量22%，AC/USB powered=false；网络、地址、端口与供电下次重新核实。
未saveenv/刷写启动分区/操作电机/提交推送；正常reboot/poweroff/MCU、Wi-Fi休眠和长时性未验收。

入口：[源码Wi-Fi实测与构建](../outputs/rk3568-source-wifi-20261004/README.md)、
[机器结果](../outputs/rk3568-source-wifi-20261004/result.json)、
[脱敏读回](../outputs/rk3568-source-wifi-20261004/verification.txt)。
下一步先确认供电和天线/局域网条件，完成ARP和64KiB双向SHA复测，再把相同源码工具纳入正式rootfs；
固件/DDR/loader/trust/MCU源码缺口继续单列。

## 2026-10-04 RK3568 源码网络工具 rootfs 往返通过

新鲜 Android ADB/root 可用，源码 helper 的 64 KiB TCP 双向传输通过，
发送/板端/回传 SHA 一致并清理 RAM 测试服务。此对照不证明旧源码 Linux ARP/TCP 故障已解决。
本轮没有重新进行 Linux 物理 Wi-Fi 认证/联网，五 GHz Android 与此前 Linux 漫游至另一 AP 只作差异证据。

新 64 MiB ext4 普通文件已合并源码 BusyBox/WPA2.11/CLI/helper/codec/PTY/同 Image 的 BCMDHD 模块，
host image SHA=fb998ec342e19d28df0dc7ba1f24171c4f9cb651b4a1150045ed5d3c3c6ba757。
104路径、所有常规及保留 inode uid/gid0、只读e2fsck、静态ELF/QEMU、21项边界测试通过，
实际原 shell cleanup 片段的7项mock失败/重试检查通过；mock测试不是板端故障注入。
无原厂 Android .so、凭据、MCU操作程序；firmware/NVRAM仍为私有本机二进制依赖，许可未确认。

Android4.19私有namespace中RO/noload+完整payload、codec/PTY/WPA版本、RAM/tmp写后完整SHA不变均通过，
独立RW Android marker→独立RO回读。新镜像放独立cache实验目录，旧文件未覆盖。
U-Boot新鲜检查mmc0/cache0:c与内存，沿用 e7a95d9f...8fa457 Image、原Wi-Fi DTB、v5 initramfs，
逐项SHA/CRC及外置检查脚本SHA核验后RAM启动；没有saveenv。
Linux先RO cache/rootfs回读Android marker并同套测试通过，再独立RW写Linux marker、RO回读。
挂载/loop/cache/devpts逐项释放，收尾只有rootfs/devtmpfs/proc/sysfs/tmpfs，PID1仍/bin/sh /init，未switch_root。
SysRq103.129735秒复位，本次源码Linux复位前记录未捕获WARNING/BUG/Call trace，返回Android11/4.19/root/boot_completed1。
五个启动分区完整SHA仍一致，Android RO读回Linux marker和payload；两份测试后镜像回传压缩包并核对解压完整SHA。
after-Android SHA=a67752f777c7c25b8f7aca570dfada72c68b1ef39c295f6bd8ccd207e11523fc；
after-Linux SHA=32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3。
原15项启动备份亦重新校验；仍无完整eMMC/裸机恢复验收，普通reboot/poweroff/MCU/运动与长时性未验收。

WPA/CLI -v在53秒出现CRNG未就绪urandom提示，本轮没有认证，不能写成弱随机认证事件。
实际HW_RANDOM_ROCKCHIP=y且驱动已编入，但旧实测Wi-Fi DTB的rng@fe388000 disabled；
后续独立候选仅打开该节点，先验绑定和getrandom就绪再认证；旧DTB与本轮输入保留。
driver quality=999只为源码声明，不是本机随机质量验收；熵初始化和此前ARP失败都尚未认作修复。
新wifi-rng独立wrapper离线编译完成，DTB SHA=ab0893cea485cb9972d93dfb3eaa61ec955cbf4314a3f0f39c43b418249e8035，
162418字节、104项审计、11项实际DTB故障拒绝、零新增DTC警告。属性差分仅rng/status，保留区相同。
仍未板测、未替代旧文件；新构建器锁定来源并拒绝已有/越界/符号链接输出。

收尾最新实际电量3%，已按用户要求提醒换电池并停下板端操作，电脑端继续准备下一轮候选。
一次性电量提醒已PAUSED避免重复；printk7/4/1/7、kptr_restrict2、串口已释放。
地址/端口/电量/新电池与连接在下次必须重新核实，不沿用本轮值。
未刷启动分区/操作电机/提交推送。入口：[源码工具rootfs](../outputs/rk3568-network-rootfs-20261004/README.md)、
[机器结果](../outputs/rk3568-network-rootfs-20261004/result.json)、
[Linux运行读回](../outputs/rk3568-network-rootfs-20261004/linux-runtime-check.txt)。

## 2026-10-04 RK3568 RNG 与条件性 5GHz TCP 实测通过

用户已换电池；新鲜Android实测62%，复用已验证Image/v5 initramfs，仅启用rng节点的新DTB上板。
三输入长度/CRC与SHA核对，RAM启动；cache只读ro,noload拷贝检查工具后释放。
fe388000.rng实际绑定rockchip-rng，hwrng_current=rockchip；0.749178秒crng init done，
每次认证前及传输后单次getrandom NONBLOCK均成功。质量999只为驱动声明，不是随机统计质量验收。

默认组与仅PM0组均认证COMPLETED、DHCP/网关通过，但均从5220MHz转到2437MHz，
电脑邻居未解析、TCP连接超时。最初config_path模块参数尝试未生效且没有认证，不算PM0对照。
已定位真实BusyBox关闭FEATURE_CMDLINE_MODULE_OPTIONS，把insmod参数变成空串；
该轮FW/NVRAM实际由默认路径选择，不能记成命令行参数生效。
换RAM默认config.txt仅PM=0，5bytes加载/解析成功，ARP/TCP仍失败；
随后仅加band=a（12bytes、band=1），本轮维持5220MHz，同源码helper完成64KiB TCP双向传输。
上传/板端/回传SHA=7daca2095d0438260fa849183dfc67faa459fdf4936e1bc91eec6b281b27e4c2。
电脑ICMP没有回复，但TCP成功；不同AP/信号/时间边界仍在，ARP根因与长时/重连未确认。

独立修正BusyBox已构建，唯一配置语义变化为FEATURE_CMDLINE_MODULE_OPTIONS n→y，
静态AArch64、51 applet/QEMU通过；真实旧/新对象syscall mock红绿及4项参数/回退测试通过，
正式产物无mock、未向主机加载模块。新SHA=514c3fa48e538283aea7881cc7c54c4a77c855db09c05008fef9587f2ac906a1。
仍未板测/未替换既有rootfs或v5；后续独立新版纳入，不能沿用旧板测结果。

各组凭据/WPA/helper/模块/接口/实验配置已清理，收尾只有RAM文件系统且无loop。
两版cleanup各11项mock失败/重试检查通过，v3另经只读审查与实际板测；失败不放行复位。
PID1仍/bin/sh /init，未switch_root；1080.849940秒SysRq返回Android11/root/boot_completed1。
所捕获源码Linuxdmesg没有WARNING/BUG/Call trace；五启动分区完整SHA一致，
既有rootfs文件仍32273043cbc6656612dbf8a2e31866b27080ef26b8ee44b1ad83f91ae6c330a3。
最后实测60%，printk7/4/1/7、kptr_restrict2，网络ADB可用、串口释放；下次地址/电量/连接重查。
未saveenv/刷启动分区/操作电机或MCU/提交推送。普通reboot/poweroff/裸机恢复仍未验收。
入口：[本轮复现](../outputs/rk3568-rng-network-20261004/README.md)、
[机器结果](../outputs/rk3568-rng-network-20261004/result.json)、
[独立BusyBox来源与测试](../outputs/rk3568-rng-network-20261004/busybox-module-options-manifest.json)。
下一步将新BusyBox/RNG门槛和已验证网络顺序纳入独立新版rootfs，先验证板端模块参数，
再推进正式Linux启动入口和外设；firmware/loader/DDR/trust/MCU源码缺口继续单列。

## 2026-10-04 UART0、USB音频元数据及新版RAM用户空间已板测

用户确认只接板子、未接电机。本轮仍复用e7a95d9f...8fa457源码Image；独立UART0 DTB仅改
已板测RNG树的UART0/status，127检查/12真DTB拒绝/零新增warning。
DTB SHA=7be4f96f90e10f1308ba6ecef8a5346d641d1bfbcf8746fbcdb704a2de9491d1，162414bytes。
新版单流RAM initramfs=f0965ceed549acab8d5bd87df8bb831bb06a95d08b5b7bf3c5582045933323ee，4308268bytes。
保留v5最终helper/WPA/模块/FW/init，仅替换新BusyBox并加entropy-check/serial-inspect；
实际新旧applet均52，纠正此前51描述。旧ext4工具rootfs未替换BusyBox。

Linux实机UART0=fdd50000.serial→dw-apb-uart→ttyS0/4:64，console=N，实际GPIO0_C0/C1归uart0；
10秒窗口和收尾tx/rx0。没有物理TTY open/串口帧发送；probe/寄存器诊断不是电气无副作用保证。
USB麦克风8通道/16kHz/S16_LE与Android元数据一致，未录音/验音质/通道意义。
RO cache/RO loop/noload复跑旧rootfs同套codec/PTY/payload/RAMtmp，完整rootfsSHA仍32273043...330a3。
RNG绑定+单次getrandom NONBLOCK通过；新BusyBox真实三module参数经sysfs和本次配置日志通过，
没有认证/TCP复测，不沿用上一轮网络成功当作新版传输验收。

清理v1读取失败空输出可误放行；v2把换行字符串当空参数恢复成功，实机getter0a→0a0a，
均保留失败证据。已按锁定copystring setter单NUL精确恢复0a，v3不改firmware_class.path，
聚合清理失败继续独立资源；18真实脚本mock失败/重试门槛通过且v3实机卸载/配置释放。
收尾只五种RAM fs、无loop/module/测试配置，PID1=/bin/sh /init未switch_root。
704.977365秒SysRq→Android11/root/boot_completed1，源码日志至首DDR未见WARNING/BUG/Call trace。
五启动分区完整SHA/旧rootfsSHA不变，最后电量53%、printk7/4/1/7、kptr2，ADB新鲜返回、COM释放。
地址/电量/端口/机械状态下轮重查；未saveenv/刷启动分区/电机操作/提交推送。

参考commit ed91ef7全168 Java/AIDL/163独立blob已核；缺失114blob只读SSH在内存补取并验对象哈希，
旧partial clone仍缺114。业务动作表已补全该范围，但无真实停止/使能/反馈和厂家UART服务源码。
升级从消息URL到外部files/downloads；当前两个路径ENOENT，没有取得MCU镜像/执行下载升级。
不能把cmd14当急停，FA单位/关节与实物返回帧仍未验证，codec未接生产控制HAL。

当时下一外设为MXC6655加速度计I2C5/@15；错误传播修正与后续真实探测见下一节。
当前Image的SENSOR_DEVICE仍n，外部模块单列；身份/默认OFF尚未验收。不是已证六轴IMU。
CAP1188需SPI实现，RK809功放/codec启用、显示/摄像头/BT与正常电源生命周期仍未验。
证据入口：[本轮复现](../outputs/rk3568-motor-alignment-20261004/README.md)、
[机器结果](../outputs/rk3568-motor-alignment-20261004/result.json)、
[下一外设依赖](../outputs/rk3568-motor-alignment-20261004/NEXT-PERIPHERALS.md)。

## 2026-10-04 MXC6655源码错误传播已修，两套系统身份读取均失败

公开0005修正I2C短传输/读错误、ID/init/probe errno和class创建失败清理；
真实原函数harness72、模块ELF/导入/边界14检查通过，源码生成器发布补丁复用10检查通过。
同已测Image/配置/headers/Module.symvers独立Kbuild构建sensor_dev与mxc6655xa，
仅v1两模块实际加载。v2重建代码对照与source-v2只为host验证，未额外上板；旧源码/ABI/Image未改。
新增DTB只启I2C5/@15及IRQ pinctrl，保留UART0与原GPIO映射；151检查/13真DTB故障拒绝，
760旧phandle和其余旧属性值保持，只有15属性变化，零新增warning。MCU@62继续缺席。

原Android的gsensor驱动symlink虽存在，但没有gsensor输入/节点，原启动日志WHO读取失败；
不能从旧“已绑定”条目推断可用。原Image实际i2c_msg为24byte而标准ARM64为16byte，
离线反汇编审查RK3x路径后构建显式legacy24单WHO工具；仅适用精确原Image/controller。
Linux probe返回-6、不留假绑定，标准WHO工具errno6；Android正确布局工具也ENXIO/rc2。
未测到ID05、初始化、硬件默认OFF、方向或采样，未确定芯片实装/供电/连线根因。
两个模块保留到SysRq，未rmmod/输入open/校准；remove与并发问题仍未修。

最小RAM BusyBox实际52app、没有id/base64；最终脚本与声明依赖经QEMU语法和实机SHA核验。
PID1 comm实际init；exe=/bin/busybox、argv=/bin/sh加/init及ELF SHA才是本轮身份门槛。
cache/debugfs释放、只五种RAM fs、UART0 TX/RX0；16实际guard脚本fixture检查通过。
538.169568秒SysRq返回Android11/4.19.232/root/boot_completed1，源码尾段至DDR无WARNING/BUG/Call trace。
五启动分区/source rootfs本轮前后完整SHA一致；network rootfs本次读回与此前锁定基线一致，
本轮初始raw没有该项。最后读取电量41%，连接/电量/端口下轮重查，COM已释放。
未saveenv/刷启动分区/switch_root/电机或MCU动作/正常poweroff验收/提交推送。

入口：[本轮复现与边界](../outputs/rk3568-accelerometer-20261004/README.md)、
[机器结果](../outputs/rk3568-accelerometer-20261004/result.json)。
下一步实物确认加速度计和供电，或在保留该缺口时独立推进CAP1188 SPI/板载音频；
真实电机反馈、停止/使能/watchdog及整板正常电源生命周期仍未对齐。

## 2026-10-04 CAP1188 SPI源码诊断已上板，身份为00未验收

原Android新采集cap1188_input/八路代码2～9，审查精确原Image14段符号与框架路径；
probe/poll未见身份门槛，raw SPI错误未传播、每轮raw init及同时变化报告路径有问题，摘要公开，镜像/反汇编私有。
框架managed unregister存在，不断言remove必然泄漏；reset GPIO0B6新快照未占用，物理复位未验证。
新CAP DTS只启SPI3/spidev；default/HS均M1且仅CS0，I2C5仍disabled，无MCU/reset/input注册。
同已测Image/ABI不变，151审计/15真实坏DTB拒绝，准确10属性变化、760旧phandle保留、零新增warning。
MIT固定身份工具按官方四字节连续CS帧读FD/FE/FF，host/QEMU各42项通过、错误帧负对照拒绝。
实际消息0→3、errors/timeouts0，但产品/厂商都00、rc1；未取得CAP身份，revision失败时未报告。
SPI无地址ACK，控制器零错误不证明实装/供电/连线；不能直接定性Linux适配失败。
事务后SPI3-hs/M1已实测，CS1/reset仍unclaimed；不重试、不初始化、不注册input，UART0 TX/RX0。

RAM BusyBox实际ls省owner/group，实机前未执行旧身份脚本；修正pos3/4后仅RAM上传脚本/manifest且SHA全部通过。
stage SHA/cp失败曾可能cwd留cache，修正cd /后18实际fixture通过；reset guard25fixture通过，精确52app依赖/语法通过。
post HS检查误当group后缀导致停步，实际function spi3-hs、group spi3m1-pins；显式释放debugfs后返回门槛通过。
349.427961秒SysRq返回Android11/4.19.232/root/boot_completed1；源码日志至首DDR无WARNING/BUG/Call trace。
本轮before/after均包含五启动分区与两份旧rootfs，七项完整SHA相同；不是完整eMMC差分/恢复实测。
最后实测电量30%，ADB连接和COM已释放，下轮重查运行状态；未saveenv/刷启动分区/switch_root/电机动作/提交推送。

入口：[源码、协议、复现与边界](../outputs/rk3568-cap1188-20261004/README.md)、
[机器结果](../outputs/rk3568-cap1188-20261004/result.json)、
[原厂路径摘要](../outputs/rk3568-cap1188-20261004/factory-audit.json)。
CAP及MXC先确认实物与供电；可独立继续RK809板载音频基线/源码适配。整机外设、电机反馈/停止/使能/watchdog和正常电源生命周期仍未对齐。

### 后续RK809音频只读基线与依赖

同轮返回后继续Android元数据：card0 Bothlent USB capture，card1 RK809 playback/capture；
machine rk809-sound，codec driver rk817-codec，CPU fe410000 I2S1，tinymix列表只有两ENUM，
Playback Path=HP_NO_MIC/Capture MIC Path=MIC OFF，未改控件/播放/录音/GPIO。
可信private audio-baseline-v2/details-v3；首个未整体引用sh -c的采集无效，不作证据或公开日志。
原DT speaker GPIO4C4 active-low、hp30/spk12/differential；当前UART DT缺codec/sound，I2S1 disabled，Image RK817 codec n。
ASoC/simplecard/I2S/DMA/PMIC/regmap基础y，现源码有codec和模块入口，但未构建/加载新音频候选。
原routing用的MICBIAS1/IN1P/HPOL/HPOR在此5.10 driver无DAPM widget，直接照搬会在ASoC routes解析阻断声卡。
后续先按已有path controls整理最小候选；probe会配置GPIO/MCLK/reset/GRF，不能把未播放当作无硬件写。
原LDO4/vccio_acodec3.1V always-on供电已有；不凭猜测加regulator。codec部分GPIO/时钟/寄存器失败未传播，后续probe诊断前须修。
音频采集末次电量25%，当时仍在原Android；CAP返回时30%仅是阶段历史，当前状态见下面关机记录。
入口：[音频基线与源码依赖](../outputs/rk3568-cap1188-20261004/NEXT-AUDIO.md)、
[独立元数据结果](../outputs/rk3568-cap1188-20261004/audio-baseline-result.json)。

### 2026-10-04 23:01 用户要求关机：原Android已关闭

关机前重新确认Android11/4.19.232/root/boot_completed1；按用户请求设置sys.powerctl=shutdown，ADB命令返回0。
COM8捕获1119.291578秒`reboot: Power down`，随后ADB状态offline，串口已释放。
当前板卡已关机，下轮需要重新开机并核实连接；25%是关机前最后的电量快照。
证据：CAP输出目录private/shutdown-20261004-230142.json及同名raw.txt。
本次走原Android关机链，不补足源码Linux正常poweroff生命周期的未验收项。

## 2026-10-05 RK809源码声卡接口已RAM实测

用户重新开机并要求根据电量继续；明确没接耳机/喇叭，只验证声卡接口，电机仍未接。
本轮复用e7a95d9f...8fa457源码Image和f0965cee...3323ee RAM initrd，原内核树/配置/ABI保持。
公开0006修正DT GPIO/defer、probe读/reset写/时钟/控件/DAI format错误传播及覆盖的失败清理。
最终借用PMIC原regmap，不新分配或释放；否决child devm action方案的父lookup残留问题。
父RBTREE缓存可能提供chip name/version，日志80/95不作新鲜I2C身份验收。
真实原函数host/QEMU各73项、生成器9项、模块实际ELF故障15项通过；32项导入来自精确Image。
最终driver-source-v5 C SHA=210104c9c6014a50d3486398d081e760e08f3e7fb84fe19cde2119993131bed7。
实际module-v4 SHA=52bf198a33ce42e11f52fdf5cd6bd9be6648dc58f04d3e48810bb4e15ac579f7。

audio DTB=9cf8cc0189239dab2fda0dae0ac3519c20d5b5802900111587695458dc3ab478，163161bytes；
177审计/23实际坏DTB拒绝/29属性变化，760旧phandle及其余属性与保留区保持，零新增DTC警告。
不带此codec缺失widgets的Android routes；I2C5/SPI3/MCU继续禁用。
MIT静态helper host/QEMU各114项，锁定UAPI编译/QEMU布局一致；生产自行SIGALRM5秒，RAM没有timeout。
只CARD_INFO/LIST/INFO/READ，无PCM/控件写；未知控件仅LIST，成功close后输出标记。

实机card1 ID=rockchiprk809co，playback/capture端点，14控件；Playback OFF、Capture MIC OFF、Resume OFF。
最早proc/cards在注册完成前只有USB；后续helper/sysfs/PCM证据确认RK809，不能据早读判失败。
I2S1五pinmux与MCLK12.288MHz通过；gpio148 spk-ctl out hi ACTIVE LOW仅软件状态，未电气测量。
Android helper通用拒绝rc2且原Playback HP_NO_MIC保留，不从generic输出断言确切失败分支。
DMA mask not set来自OF平台配置dev_warn补指针，codec无DMA API；不阻断元数据，也未验证PCM DMA。

cache ro,noload复制后释放，stage18真实shell fixture含cwd负对照、guard31fixture、52app依赖检查通过。
codec模块Live引用1由ASoC card持有，保留到SysRq；收尾无音频FD/loop/网络/持久挂载，PID1仍RAM。
147.271085秒SysRq返回Android11/4.19.232/root/boot_completed1；源码返回段至首DDR未捕获WARNING/BUG/Call trace。
本轮前后五启动分区及两份旧rootfs七项完整SHA一致；不是全eMMC差分或恢复演练。
返回后新鲜电量7%，记录收尾再读5%，无外部电源标志；均为历史快照，下次电量/地址/串口/连接须重查。
串口会话已完成释放；未saveenv/刷启动分区/switch_root/电机MCU操作/提交推送。
未验PCM、音质、功放电平、runtime path/mute/hw_params、suspend/resume、并发卸载及正常Linux关机。
下一阶段先runtime错误传播和PCM能力/DMA/退出验证，再按实物音频设备验通路；整机部署与电机安全契约仍未齐。
入口：[本轮源码与复现](../outputs/rk3568-audio-20261005/README.md)、
[机器结果](../outputs/rk3568-audio-20261005/result.json)。

## 2026-10-05 新电池后的 PCM 参数配置和显示准备

用户要求继续 Android 迁移 Linux 到完成，并保持当前 TUN 设置；明确仅板子连接，
无耳机/喇叭/电机，屏幕排线已拔下，本板无 SD 卡座。实物连接、电量和地址每轮重查。
公开 0007 在 0006 上补 RK817 hw_params/set_sysclk 错误传播及能力一致性；
真实回调 host/QEMU 各 246/246，静态 PCM helper host/QEMU 各 180/180。
锁定旧 Image e7a95d9f…8fa457、模块 c9f76106…add3c 与生产 helper ac76da61…54fa 实际上板；
playback/capture 都完成 S16_LE/48kHz/2ch、256×4、buffer1024 的 REFINE/HW_PARAMS/HW_FREE/close。
SETUP 时 appl_ptr/hw_ptr=0，释放回 OPEN，后来 closed；未调用 PREPARE/START、未传音频帧。
Playback OFF、MIC OFF、Resume OFF、GPIO148 状态保持，runtime 最终 suspended。
16 项时钟检查中三个 inactive RX clock 持久保留 12.288MHz 和一个新 parent，引用计数都 0；
与此版驱动源码一致，不强制改回旧频率。原 whole-clock-equality 的 rejected 结果保留，
独立只读 closed-state 检查通过，不把 DMA bindings 相同写成 descriptor queue 已测为空。
960.295783 秒 SysRq 返回 Android11/4.19.232/boot_completed1，五启动分区和两份旧 rootfs 七 SHA 相同；
返回时电量81%，后续准备阶段新读80%。未验正常 reboot/poweroff、DMA、声学或电气状态。
宿主 release 新鲜 CTest 41/41 通过；该结果不代表板端应用或外设验收。
证据：[PCM 复现与限制](../outputs/rk3568-audio-runtime-20261005/README.md)、
[实测结果](../outputs/rk3568-audio-runtime-20261005/result.json)。

显示 DT v5 default brightness=0，恢复原 720×720/4lane/180条 init 的板级描述；
250 审计和 107 个坏 DTB 拒绝，零新增 DTC warning。公开 0008 检查负 errno 和失败回滚，
真实 DW-DSI host 调用链的 host/ASan/QEMU 各 254/254；正返回值是 host packet.size，不能假设等于 payload。
独立内核 clone 构建 Image dafdda0c…d86a7，DT 65022848…00f70，原 kernel tree 与旧 Image 保持。
仅 Image 构建的导出表为 vmlinux.symvers；不得借旧 Module.symvers 证明新模块 ABI。
后续实际v9会话已经RAM板测：74项接口全部通过，180命令host完成；VP1/DSI0为720×720/35.5MHz，
FB32bpp/stride2880，PWM25000ns/duty0/enabled，reset解除/enable高。软件connected、命令完成和零占空比
不证明面板ACK、实物画面或电气背光。Live FDT168064B完整SHA与板端一致；长流及一个4KiB块丢字节，
纯只读重读成1KiB块后完整校验通过，失败流保留。实际串口执行器拒绝多行命令，wrapper独立octal+SHA修正。
Windows ADB多层quote导致准备失败，改用校验清单后直接prepare脚本；ADB closed期间沿用串口，未动TUN。
本轮真正reboot syscall经过device_shutdown/syscore，454.881364秒Restarting system、DRM VP1关闭后回Android，
新鲜Android11/4.19.232/root/boot_completed1，七SHA一致，电量78%。请求至首DDR无WARNING/BUG/Call trace；
启动BSP、overlay/loader/dummy regulator等诊断保留。本次未SysRq；poweroff/MCU/watchdog/电源轨仍未验。
0009 codec mute负errno/sticky实例故障与OFF/MIC_OFF保持静音已公开，真实函数host/ASan/QEMU各226/226，
生成器/完整串重放22/22；未重建生产module或上板。
0010 ASoC适用mute首错/rollback、HW_FREE尽力清理、do_prepare失败退SETUP已封存；
真实调用链host/ASan/QEMU各198/198，生成器36/36、审计224/224，独立只读review无限定范围阻断。
PL330/DMA生命周期继续处理，禁止先START；DMAC无reset/iram/IOMMU节点，NULL optional reset成功不证明硬停。
STOPPED未确认须隔离实际allocation并禁止控制器再启动，不能仅返回errno后允许ALSA free。
真正root PID1/回RAM v1曾离线host/QEMU各603/603，16MiB只读rootfs和969242B initrd已生成；
独立review发现island exec失败resume漏重exec、同target devpts overmount及pivot后mount门槛绕过，v1暂缓上板，作者补新版本。
boardguard独立BB52红例49/52暴露PID1额外regular/socket FD和重复devpts假放行，已收紧源码，待新清单与复验。
最新主控仅Android只读基线：Android11/4.19.232/root/boot_completed1、电量76%、七SHA仍同；没有暂存PID1或重启。
未刷eMMC、saveenv或提交推送。当前回原Android，地址/电量/连接下次重查。
入口：[显示实测](../outputs/rk3568-display-20261005/README.md)、
[显示机器结果](../outputs/rk3568-display-20261005/result.json)、
[正常重启](../outputs/rk3568-normal-reboot-20261005/README.md)、
[ASoC独立审查](../outputs/rk3568-asoc-errors-20261005/REVIEW.md)、
[音频DMA源码缺口](../outputs/rk3568-audio-runtime-20261005/NEXT-DMA.md)、
[DMA实现方案](../outputs/rk3568-audio-runtime-20261005/PLAN-C.md)、
[PID1离线计划](../outputs/rk3568-pid1-20261005/PLAN.md)。

## 2026-10-05 原生 PID1 v3 实机往返与后续启动包

上一节 PID1 未暂存/仍 v1 的状态已被本节新鲜事实取代。v1 离线拒绝产物保持；
v2 曾完成真实root/卸载，但返回岛缺52 applet链接，需主控手工RAM补链接和修正真实父BB的
FD10 /dev/tty规则才普通reboot，记为人工协助收尾而非完整通过。失败与操作流都保留。
v3 原生创建全部52链接，真实失败注入host/QEMU各855/855，session83/83，独立审查通过。
实际v3 PID1 SHA249cc1cf…76368b，rootfs3a87bd54…fc679d，initrd54db3bb6…81afef，
完整manifest53f8807d…306484/session-v4清单6b71dc13…253dd。载入三个RAM CRC与大小通过；
真PID1 maps07:00/inode45、只读root/cache，协议和PTY纯软件自检exit0且自有子进程回收。
原生返回pivot/旧根卸载/loop detach/cache卸载全部通过；独立guard确认七个RAM挂载，
无手工补链接或改guard。普通reboot165.596432秒Restarting system→DDR→原Android。
请求至首DDR窗口无WARNING/BUG/Call trace/Kernel panic，不扩大到所有启动诊断。
新鲜Android11/4.19.232/root/boot_completed1，七完整SHA前后一致，电量67→67%。
现场只读汇总48/48；Android串口末标记被audit日志穿插而严格拒绝的流保留，后用ADB确认。
当前板卡原Android；临时用户态localhost转发源绑定WLAN，TUN/路由/适配器未改。
用户报告OTG“dmo直接接地”，引脚/测量方法未知，USB恢复未确认；本板无SD卡座。

从cache精确删除三份已备份并完整SHA核对的旧Image，104398336B；保留当前RCU/display
Image及全部rootfs，空间26656→128620KiB（PID1两版暂存前快照）。旧试验需按清单重传Image。
原40MiB Android boot包官方AOSP源码重建逐字节相同已离线冻结；后续内存bootm试验与
Linux RAM候选准备进行中，不作现场执行/正式可flash证明。无启动分区写/saveenv/提交推送。
CPU I2S审查发现实际TRCM1 helper吞错、rk3568空sync-reset、方向refcount及迟到IRQ生命周期
缺口，独立CPU实现与DMA C1/C2/C3进行中。当前仍禁止PCM START；未闭合双向/声学/电气、
PID1生产服务集成、正式迁移/USB恢复和正常poweroff/MCU安全契约。

入口：[PID1实测与v2边界](../outputs/rk3568-pid1-20261005/BOARD-RESULTS.md)、
[48项现场汇总](../outputs/rk3568-pid1-20261005/build/board-native-v3-result-v1/result.json)、
[缓存复用证据](../outputs/rk3568-cache-reuse-20261005/README.md)、
[CPU I2S只读审查](../outputs/rk3568-audio-runtime-20261005/CPU-I2S-AUDIT.md)、
[启动包离线计划](../outputs/rk3568-boot-package-20261005/PLAN.md)。

### 同日原启动包单地址 RAM bootm 已通过

原40MiB重建包与原boot备份逐字节一致，SHA0db7ae12…f21b28/CRC6e48ba06；主控核26个封存文件。
实际cache普通文件stage通过，空间93604→52640KiB；新鲜Uboot kernel280000/FDTA100000/RDA200000、
bank09400000-f0000000，relocEDCF3000/SP EB9F85B0。包20000000..22800000实际完整CRC通过。
单地址bootm真实触发board Android hook，用RAM RSCE base2204e000并选3568a_v20、DT/Android hashOK；
kernel280000..2204008、initrdA200000..A2C8C20、FDT A100000，然后回原Android11/4.19.232/root/boot_completed1。
七完整SHA前后相同，电量66→66%；现场汇总26/26。filesize0x前缀/CLI同一行echo导致的严格拒绝保留。
只证明CLI可达条件下原包RAM启动，不放行修改早期boot/正式flash或USB恢复。
当前原Android，Linux RAM候选离线已封存待独立review/现场地址核实；仍未正式迁移。
证据：[原包RAM bootm](../outputs/rk3568-bootm-ram-20261005/README.md)。

Linux bootm candidate-v1 整40MiB只暂存/载入/CRC c222e39e，未执行；现场前独立新增审查发现
Android hook套原dtbo单entry0(559B)且UART缺 __symbols__/chosen和chosen phandle，会overlay失败；
标准libfdt使base magic失效，本机U-Boot二进制已确认会备份并恢复原base。
overlay还改bootloader01→09、fastboot09→03，normal5242c300保持；无供电/外设/status节点。
因此需新RAM专用DT和实际overlay离线apply/diff/候选v2审查，不从v1包格式通过放行bootm。
v1载入后没有执行，主控用未保存环境的U-Boot reset返回原Android；新鲜Android11/4.19.232/root/
boot_completed1、电量64%、七完整SHA相同，证据private/android-after-unexecuted-v1-reset.json。
进一步核部署版二进制确认overlay失败会恢复完整base备份，不能称失效magic会遗留；成功启动也不证明overlay成功。
v2作者正在以真实libfdt验证最小chosen symbol+phandle修正，再独立审查和板测；尚无v2现场结论。
主控精确回收已有frozen host完整40MiB备份的v1 cache普通文件，原包/native3 rootfs及IR/两Image/
七保护输入完整校验前后通过，空间11676→52640KiB；没有删除其他路径或写启动分区。
脚本和实际receipt见[启动包缓存回收](../outputs/rk3568-bootm-ram-20261005/reclaim-candidate-v1-result.json)。

### 同日 Linux v2 包两次 RAM 启动，第二次最终闭环通过

v2最小shim新增chosen symbol+phandle2f9，真实libfdt离线apply成功且相对原UART严格5项属性差异；
其余外设/status/供电/保留区保持。独立核88个冻结文件，主控再核63个输入文件。v2包40MiB
SHA67f351b8…af37dbe/CRCcab15fb2，cache普通文件暂存完整SHA两次通过，空间52640→11676KiB。
第一次单地址bootm用kernel4MiB/initrd64MiB/FDT48MiB进入native PID1 v3、协议/PTY自测和
native RAM返回、七项guard、普通reboot505.770366秒均通过；原Android七完整SHA相同62→62%。
但完整live FDT163968B/SHA6109dda4…28587e确认overlay不在最终树中：bootargs_ext缺失、两个mode
回到pre-overlay值。一次overlay OK后还有第二次资源DT读取和FDT_DTBO重复分配。
[现场汇总65/71](../outputs/rk3568-bootm-ram-20261005/linux-candidate-result-v2b.json)明确保留拒绝。
初版66/71漏识别带"for existence"的重复分配消息，收紧匹配后65/71；旧结果/源快照保留。

部署版U-Boot实际分支比较env fdt_addr_r和fresh gd FDT，相等跳过第二次读取。独立审查新地址
A100000保守工作区至A140000，与kernel/header/initrd/package/栈无冲突。第二次同一v2包完整CRC
通过，仅临时FDT地址恢复A100000，已进入Linux且没有第二次DT资源读取/重复分配。
第二次最终live FDT163968B/SHA25cc8ad8…270e2e19以641个256B/尾部128B片段完整读回，
独立958节点/4891属性/31已解释差异审查通过，761phandle/168status保持，overlay目标全部保留。
两次1KiB串口读回丢字/末标记均拒绝且保留，不补猜字节。ROOT_READY、codec/PTY exit0并回收，
native回RAM/旧根卸载/loop detach/cache卸载、独立七挂载guard、普通restart均通过；时间戳1656.913338秒，
请求至首DDR无严重诊断。新鲜Android11/4.19.232/root/boot_completed1、七完整SHA相同，电量62→60%。
[第二次71/71汇总](../outputs/rk3568-bootm-ram-20261005/linux-candidate-result-v3.json)已完成；当前原Android。
UART基线解析保留孤立CR，避免universal newline把光标移动造为重复裸1；7项实际/拒绝回归通过。
TUN/路由未改，当前临时源绑定localhost ADB v7实际连接成功、root/11/boot_completed1通过；
地址、进程和当前阶段下次重新确认，不沿用历史PID或地址。
依据：[启动包审查与实际地址分支](../outputs/rk3568-bootm-ram-20261005/BOOT-PACKAGE-REVIEW.md)。

音频CPU v8独立审查发现clock action早于clk_get使devres逆序UAF、legacy controls绕checked门槛。
v9修这两项，但新独立审查发现runtime_resume STOP未确认却释放MCLK、PM core错误锁存/disable_depth模型缺口。
v10源cbd19c1a…77b59修正，独立重跑六套三环境各1447/1447，旧独立模型新增pending/running callback
与remove、永久STOP、同设备重新绑定，三环境各133/133；DT31、实际完整C Kbuild/4220 ABI通过，无确定新阻断。
250证据文件逐项SHA保存，[v10完整独立审查](../outputs/rk3568-audio-runtime-20261005/REVIEW-I2S-v10.md)。
仅继续C3软件合测，尚未生产Image/板端START。独立clean音频源码/配置已准备，未应用moving候选。
DMA C1 v17的PM前ticket和撤掉checked debugfs成立，91/91三环境独立复跑；独立发现WFE/INVALID
拒绝未latch sticky，主控用相同冻结ELF复現并保存精确argv/输出。作者新v18已有修正和95/95，
仍需C2 allocation隔离、C3真实组回滚/全部STOP清理、只读DMA状态及完整生产编译/独立审查。
入口：[CPU v8独立证据](../outputs/rk3568-audio-runtime-20261005/REVIEW-I2S-v8.md)、
[DMA v17独立证据](../outputs/rk3568-audio-runtime-20261005/REVIEW-DMA-C1-v17.md)。
未刷启动分区、saveenv、提交或推送，USB恢复/早期DT正式包/外接屏幕与声音/MCU安全契约仍未验证。

### 同日声音整合准备与 recovery 原始备份

DMA C3 v5独立实际probe IRQ模型暴露IRQ安装早于controller lock/req_done/threads初始化。
真实AMBA wrapper使入口active/PM usage1，pending IRQ进入实际update，host/QEMU -11、ASan1。
十二实际Kbuild对象编译通过，但v5拒绝；完整独立审查未完成，114文件逐项SHA复制保存。
作者正在另立v6初始化/发布/失败清理及连续descriptor块归属修正；仍禁止板端PCM START。
证据：[C3 v5拒绝](../outputs/rk3568-audio-runtime-20261005/REVIEW-DMA-C3-v5.md)。

静态单向pcm-transfer已冻结659736B/SHA2a6c765b…09e2e，实际生产C wrappers三环境各143/143，
固定S16/48k/2ch/256×4、先禁隐式START、显式一次START、播放零样本/采集仅统计，
DROP/HW_FREE/close后延后输出；尚未板上运行，不以helper返回0代替DMA停止/重启门槛。
新的audio RAM pre-overlay shim163204B/SHAc36b140c…b1e8b，codec原phandle2f9保留、chosen2fa；
真实libfdt三次apply及独立完整树检查通过，未打包/上板。新Image及精确ABI codec builder已写，
只完成语法检查，尚无生产Image。旧native3/只读rootfs/IR复用，旧RCU缓存检查不作新Image身份。
cache精确回收计划已核三份host完整备份，实际--check通过；尚未执行删除。

部署U-Boot正式early DM在CLI前重读资源DT；单DT组件和recovery均不自然分离early/late。
eMMC当前候选缺部署driver识别的snps兼容串，USB父子/供电依赖也需闭合；有限离线DT增量进行中。
用户确认板上DMO标记在完全断电时对地近0Ω，仍不确定引脚身份，不能写成已确认D−短路。
只读新增recovery原始备份96MiB/SHAa94f4e7f…890933，板端前后完整SHA相同；legacy exec-out
额外合并86B统计，原拒绝流保留，新提取镜像全SHA匹配。七保护输入相同，当前原Android；
21:28新鲜电量44%，地址/PID/电量下次重查。TUN/路由未改。
入口：[早期DM/recovery证据](../outputs/rk3568-boot-package-20261005/FORMAL-EARLY-REVIEW.md)、
[recovery完整备份](../outputs/rk3568-backup-linux-20261003/recovery-backup-v2.json)、
[声音整合计划](../outputs/rk3568-audio-runtime-20261005/INTEGRATION-PLAN.md)。

### 同日默认地址往返与声音 C3 v8 整合

同一v2包默认目的地实际往返[50/50](../outputs/rk3568-bootm-ram-20261005/default-address-result-v2.json)。
只临时设high限制，不手动覆盖bootargs或目的地；kernel实际280000→200000 relocation、
FDTA100000保持gd、initrdA200000，一次资源读取/overlay成功。native3自检/回RAM/guard/普通重启通过，
原Android七SHA相同。整FDT168064B/SHAaeed58e2…92178a只作大小与完整SHA见证及chosen子集，
没有全树导出/语义审查。旧49/50汇总的CLI前缀解析错误与旧源保留，新5项解析回归通过。

C3 v7首次STOP缓存与poisoned generic-held reopen两项缺口经真实函数夹具复现，旧红例保留。
v8修正，独立只读完整功能审查未发现新阻断，主控另行重新编译/实际执行ready14、open21、CPU链47，
host/ASan+UBSan/QEMU各82/82通过；作者八套各183/183。883冻结文件、250CPU独立文件、
84正式DT离线文件、42包工具准备文件均由主控逐SHA核回。
[v8复核](../outputs/rk3568-audio-runtime-20261005/REVIEW-DMA-C3-v8.md)与
[主控实际复跑](../outputs/rk3568-audio-runtime-20261005/build/c3-v8-root-reexecution-v1/result.json)。

主控已按精确SHA发布公共0011/0012，完整十二补丁应用至专用clean音频checkout后完成Image/modules构建。
新Image34755072B/SHAe48c4295…89955、CRCfb920db9；codec新ABI32imports/2024文件通过，
模块518904B/SHAe0aecc77…7ca80。生产包v2新鲜主控audit通过，40MiB/SHA58e2a96f…74b8b、CRCfe7bd3a1；
合法空日志与Linux release两项工具错误另立v2修正，旧源码/fixture/拒绝保留。板端START仍未完成。首次gate含Windows路径分隔符，在应用补丁前
被Linux拒绝；旧gate与失败收据保持，新POSIX路径gate-v2通过输入校验后才开始构建。
本板仍原Android，TUN/路由未改；旧ADB连接实际closed后只重建本任务用户态源绑定转发v8。
现场地址/电量/PID下次仍需重查，不能沿用本节快照。
eMMC有限兼容串DT离线三次libfdt、21坏树拒绝、Linux真实OF matcher通过；USB完整依赖分析仍未放行恢复。
入口：[正式DT有限改动](../outputs/rk3568-formal-dtb-20261005/README.md)、
[声音整合gate](../outputs/rk3568-audio-runtime-20261005/build/review-gate-v2.json)。

2026-10-05 用户明确结束当日工作并暂停、要求关机。所有开发/板测与独立review推进停止，仅保存交接和
正常关闭开发板；未创建自动继续/自动测试。三份旧cache普通文件实际精确回收59692016B，fresh完整host备份及
保护输入前后SHA通过，cache69972KiB。新启动包/辅件尚未上传，host stage在`aux.sha256` Get-Item失败、
第一次ADB命令前退出；Windows保留名是待核假设，明天先另立清单名修正与复验。
guard v1独立拒绝UIO alias与/run noexec说明；v2作者501×3、1128SHA，动态major与/tmp8MiB修正完成，
v2最终独立复核被暂停中断，不能写为完成或据此自动START。
明天续做入口：[暂停交接与精确产物](../outputs/rk3568-audio-runtime-20261005/HANDOFF-TOMORROW.md)。
原Android正常关机已实际记录MCU driver watchdog/poweroff及kernel Power down；随后COM8消失，
初版读取报Access denied的结果保留，另立observation-v2按raw完整SHA确认。
原Android关机日志含xhci halt -110和invalid GPIO，不称零错误或新Linux关机通过；物理电源轨未测。
任务用户态ADB转发已断开，现场供电、地址、PID、串口均须重新核实。

### 2026-10-06：用户恢复适配，声音新Image实机检查进行中

原Android/root/COM8与WLAN重新核实后，新audio包/辅件普通cache上传全SHA通过，七保护/native缓存前后相同。
fresh U-Boot banks/gd/栈及40MiB包CRCfe7bd3a1通过，单bootm已进入新Image/native3只读root/cache。
该轮已进入Linux；后续两向PCM START/退出/原生回RAM与普通重启已完成，最新状态见下节。
实际DMA规范名fe550000.dmac，
v2 guard写错，v3单字节修正已独立核与RAM全SHA确认。Windows5.1 AUX问题已复现；
stage CRLF/native cache路径错误的拒绝保持，新LF脚本与/.backing-cache复制辅件全SHA通过。
正常codec/card绑定后CPU STOP/IRQ排空与DMA零工作证明出现，三路径OFF/两向closed/单线程FD核回。
v3时钟profile漏算codec probe持有的六TX父链引用，首次bound拒绝；主控未START/解绑/改clock/重启。
v4另立精确阶段预算/cached parent，已完成离线冻结/独立复核与板端完整collector。
电量计/BQ驱动与DT仍在适配，独立发现生命周期缺口，未热启充电。
入口：[当天持续记录](../outputs/rk3568-audio-runtime-20261005/SESSION-20261006.md)。

### 同日声音两向有限传输与正常往返

guard v4 RAM完整SHA87403843…c6f69；各向新鲜pre/post严格guard0，playback/capture各24576帧/一次START，
DROP/HW_FREE/close0。capture全49152样本零，三路径OFF，只有统计；不证明麦克风/扬声器声音。
CPU STOP读取计数2→7→12，DMA9→63→117，sticky/owner/work/PM/lease0，quarantine0。
正常card解绑TX引用0/HCLK1、DMAallocated2；正常codec rmmod与CPU解绑后16时钟引用全0、DMAallocated0/STOP153。
debugfs正常umount，native codec/pty纯软件自检/回收通过，自行回RAM backward63与独立七挂载guard通过。
真实普通restart在2022.492931秒后返回Android；请求至首DDR窗口无WARNING/BUG/Call trace/Kernel panic。
fresh Android11/4.19.232/root/boot_completed1、七保护及native缓存完整SHA相同，当前原Android。
该次记录的source-bound用户态ADB为v10；后续重启会结束单连接转发，地址/PID须重新核实。TUN/路由未改。

close两次均有ASoC CPU sysclk(freq=0) -22诊断，不能写零诊断验收或完整声音适配。
simple-card shutdown合法清零与checked CPU !freq参数拒绝不兼容；源码确认发生在锁/gate/cache写之前，
无硬件/PM操作与sticky设置。下一次非零hw_params重建请求后本次capture经新guard人工许可。
新cpu-lifecycle-v11已离线冻结/独立复核，主控重新编译三环境的4红例/48 shutdown/140 params通过；
旧已测Image/公共0012保持；新Image实机对照的后续结果见下面v3记录。
现场[56项/19文件汇总](../outputs/rk3568-audio-runtime-20261005/build/board-results-20261006-v1/result.json)
标finite_trial_completed=true、full_audio_adaptation_completed=false，全部失败/诊断原流保留。

电量计候选只离线修生命周期，原Android battery16属性已逐项复制，3500/3750与21OCV是原板参数，不是新电池标定。
原DT缺design_max_voltage，Linux charge状态算法可能把缺省0当有效阈值，尚未闭合，禁止据生命周期模型启算法。
外部BQ/FUSB/MCU边界与正式early boot/USB恢复仍独立未完成。

用户同日明确新电池型号、电压和容量暂时未知，后面补填；本轮留空，不猜默认校准值，不重复询问。
电量计sealed-v5仅在RK809 parse新增缺失/零/超signed µV表示范围的早期拒绝及whole-pack mV注释；
独立134文件SHA及旧v4的224文件不变、实际Kbuild32步和作者191/90三环境证据复核通过。
表示上界不是化学阈值，12345只是测试夹具；原16属性DT仍缺字段会被拒绝，算法保持禁用。
入口：[电量计有限参数候选](../outputs/rk3568-power-runtime-20261006/sealed-v5/receipt.json)、
[CPU关闭修复复核](../outputs/rk3568-audio-runtime-20261005/REVIEW-CPU-v11-20261006.md)。
新audio-v2独立源码和原配置准备已完成，13补丁输入3215文件绑定；后续完整Image/codec/板结果见下面v3记录。
WSL launcher再次间歇Wsl/Service/0x8007274c，部分调用未启动脚本；未改TUN/路由或重启服务。

### 同日audio-v3包：关闭修复通过，初始化PM竞态另立修正

完整Image/modules实际构建成功，Image SHA974c6b88…d3620；新codec实际1934项ABI/32 imports闭合，
完整40MiB包SHA5d9e5de3…ff8ab/CRC2506894d经独立离线审计与主控fresh audit、板cache全SHA通过。
只回收一个有host完整备份的旧v2普通cache启动包，七保护/native缓存SHA前后相同；没有刷分区/saveenv。
fresh banks/gd/FDT reservation/全CRC后单bootm，新live /sys/kernel/notes 60B/SHA31152f43…c9682b
与实际vmlinux GNU build ID66eae960…298360一致；不是完整live RAM Image SHA。
完整live FDT168064B/SHAc1cf7fd3…3120a已分块导出/全SHA/独立全树复核：962节点/762phandle保持，
31项bootargs/内存/MAC/显示handoff差异，音频完整属性保持、USB OTG仍disabled、未知新电池算法未加入。
连续大串口dump丢219 hex、4KiB第22块丢170 hex的原流保留；只以8个fresh512B块重取，再核完整SHA，未补猜字节。

首次严格guard拒CPU idle：set_fmt已完成写操作但async pm_runtime_put worker可能先于configuring清除执行，
checked_suspend返回-EBUSY；实际auto/usage0/activekids0/error0/STOP1却持续active/MCLK1/IRQlive。
主控仅做一次正常power/control on→auto诊断性重新请求idle，usage0→1→0，真实checked_suspend成功，
随后完整fresh guard通过。这不是初始化idle验收，也不能算竞态修复。
在此限定前提下两向各24576帧/一次START，DROP/HW_FREE/close0；CPU v11已消除两次旧sysclk关闭-22。
capture三路径OFF、49152样本全零，只留统计；无实物声音验收。
正常card/module/CPU清理、16时钟引用全0/DMAallocated0/quarantine0，native codec/PTY自检/回收、
正常回RAM及七挂载guard、普通restart至首DDR无trace；返回Android11/4.19.232/boot_completed1后
七保护/native完整SHA再次一致。单连接ADB v10结束，新source-bound v11成功，不改网络配置；后续仍fresh核状态。
[v3实机汇总](../outputs/rk3568-audio-runtime-20261005/build/board-results-20261006-v3/result.json)：
64检查/46证据，CPU_v11_close_regression_passed=true，initial_idle_verified_without_diagnostic=false，
full_audio_adaptation_completed=false。

CPU v12仅新增format终结phase及两函数窄修正，作者实际红4/5、绿90/48/140三环境与Kbuild对象已封存，
独立源码审无阻断，主控fresh重编译与新Image/无诊断initial-idle对照尚在继续。
新aiot-3568pq-audio-v3源码/原配置已独立准备，尚未patch/Image；原source与旧Image/公共0012保持。
电量计v5主控fresh重编译191红/绿三环境实际通过，旧224/新134文件保持；算法继续禁用，不猜电池参数。
eMMC bridge v3独立157文件/41输入通过，真实新包pre-overlay上仅追加snps兼容串，实际apply后与旧post候选逐字相同；
[pre-overlay候选](../outputs/rk3568-formal-dtb-20261005/sealed-v3/receipt.json)仍不证明早期DM/eMMC I/O/正式分区启动。
USB2 peripheral候选也只离线审查；DMO身份/恢复接口及无SD卡座的实物边界未改变。

同日CPU v12主控fresh重编译红5(4通过)/format90/sysclk48/params140三环境完成，独立初始/补充freeze及真实对象审查通过，
actual v2 ABI数为2020；旧README2110更正保存在独立post-freeze-review-v1。
新gate-v4的5761绑定、14补丁实际重放、完整Image/modules与codec实际ABI审查通过。
Image965acb13…381fe/CRC91dd4a19，codec d62205da…0ecbf7/1934ABI/32imports，原source/config与算法禁用保持。
新notes60B/59373c55…370af/GNU121dee3f…815b9f已从actual vmlinux只读取证，尚未板核。
package-v4主控fresh audit通过：40MiB/eb2da84a…3afe6/CRC50c2904d，最终seal/独立包审与自然初始化实机仍继续。
当前板重新只读核root0/Android11/4.19.232/boot_completed1，cache23948KiB；源绑定v11连接有效，后续仍fresh核。
入口：[最新CPU复核](../outputs/rk3568-audio-runtime-20261005/REVIEW-CPU-v12-20261006.md)、
[新整合](../outputs/rk3568-audio-runtime-20261005/build/integration-v3/manifest.json)、
[主控新包审计](../outputs/rk3568-audio-package-20261005/build/audit-root-v4/receipt.json)。
当前驱动明确single-running-direction，独立确认第二START拒绝；双open/peer关闭诊断与共享TRCM/codec/DMA fault还需联合契约，
不能从两向分别成功推广全双工；新guard/包仍不自动授予START。

第四轮v4-r2封存独立25SUM/295外部普通输入通过；旧内容指纹785普通+7负fixture目标内容保持，
历史link target身份没有旧绑定，不把792全称ordinary。上传准备两个schema拒绝均在任何板动作前，
显式核新seal/bundle/sidecar与原source逐字相同后host准备通过，manifest127e1285…4092f。
板上旧v3单个40MiB普通cache包精确回收（host备份/保护SHA先后核），新v4七输入上传全SHA通过。
fresh U-Boot banks/gd/reserve与整包CRC50c2904d后单RAM bootm已进新Linux/native3。
actual notes60B/59373c55…370af/GNU121dee3f…815b9f与新vmlinux一致；完整liveFDT168064B/93dfe8b5…79c2a0
严格分块读回/缺块fresh补采/全SHA与独立全树复核通过。和v3的header、962节点/4915属性/762phandle/reserve相同，
3202不同字节只在未使用尾部；完整身份仍使用新SHA。eMMC/MMC与只读cache读取正常，原early DM保持。
新CPU v12首次codec观察已自行suspended/自有MCLK0/IRQ排空，fresh initial guard0，未执行power/control诊断。
playback/capture各24576帧/一次START、DROP/HW_FREE/close0，旧sysclk -22消失，pre/post严格guard均0。
三路径OFF、capture49152样本全零；播放raw有一处合并残行，能完整辨认94条WRITE，不能称逐笔I/O日志完整。
正常card解绑/codec卸载/CPU解绑后16时钟enable/prepare/protect全0、DMAallocated0/quarantine0。
native codec/PTY自检/回收、回RAM backward63/卸载旧根与cache/loop detach、独立guard、普通restart通过；
747.877323秒请求至首DDR窗口无严重trace。fresh返回Android11/4.19.232/root/boot_completed1、
七保护和三项native缓存完整SHA相同，当前原Android。
[v4实机汇总](../outputs/rk3568-audio-runtime-20261005/build/board-results-20261006-v4/result.json)：
109证据检查/45文件，initial_idle_verified_without_diagnostic=true、v11关闭/v12初始idle回归通过，
full_audio_adaptation_completed=false。失败的Android串口IPv4交错原流保留，文件保护校验使用fresh独立ADB。
旧v11用户态转发实际仍持有stale连接；只断开本任务ADB端点后旧进程正常结束，新source-bound v12连接通过。
地址、PID和电量仍须下次重核；没有flash/saveenv/TUN/网络配置修改。
全双工只读调查已保存：[剩余契约与真实链](../outputs/rk3568-audio-runtime-20261005/build/full-duplex-review-v1/README.md)。

### 同日公共补丁与 ASoC 并发清理候选

已验证的 CPU v11/v12 修正正式登记为 public 0013/0014；旧0001–0012和原冻结保持。
固定SDK重放14补丁后89423项tracked源尺寸/SHA/executable/symlink模式与actual Image-v3一致。
新鲜实际built-in单对象与实机对象的.text、15个alloc节、保留重定位的反汇编及GNU strip-debug整体字节相同；
未strip差异只在3项调试节。旧obj-m对象不相同、首次缺flex/bison失败均保留，不能混用证据。
主控197普通文件/198SUM/42外部引用审计与独立只读审查通过；没有新完整Image或新的板操作。
入口：[公共整合](../outputs/rk3568-audio-runtime-20261005/public-integration-v1/README.md)、
[独立审查记录](../outputs/rk3568-audio-runtime-20261005/public-integration-v1/independent-review-v1.json)。

真实ASoC caller-chain模型已复现startup失败unlock→重新锁清理窗口的单指针marker覆盖，
以及锁外PM mark_pm被其他get/put覆盖导致引用漏还。主控fresh v4为24业务红例/68观察通过×3环境；
作者后补并冻结v5为25业务红例/76观察通过×3，不能把红例称适配通过，也不能混用计数。
当前候选仅修持锁失败清理、get本调用prefix自回滚、PCM/compressed caller双归还及同DAI peer共享sysclk保留。
PM回调仍锁外、接口/结构不变、CPU v12/C3及双START拒绝保持；voice sibling缓存与泛型pinctrl在途窗口不在保证范围。
入口：[主控真实红例](../outputs/rk3568-audio-runtime-20261005/build/root-asoc-baseline-v4-v1/result.json)、
[最新冻结基线](../outputs/rk3568-audio-runtime-20261005/full-duplex-contract-v1/sealed-v1/receipt.json)、
[设计与验证边界](../docs/superpowers/specs/2026-10-06-rk3568-asoc-open-rollback-design.md)。
新ASoC候选和无START双open用户态检查器已完成离线实现；最新封存与整合状态见下一段。
当前板仍以上述第四轮原Android返回记录为最后硬件状态；新的运行状态须fresh核实。

### 同日ASoC持锁回滚与peer-idle候选离线接受

主控fresh v5基线实际重编译为25业务红例/76观察通过×3，和最终冻结一致。
四源候选真实模型由红0/25变为绿21/25，110边界观察（74唯一标签）×3保持通过；
主控独立新编译六次与完整原始输出一致。四项双方向START/共同STOP红例保持，不能称全双工通过。
持锁失败清理、每次PM取得引用的本调用归还、两个caller避免重复fullput以及同DAI peer请求保留已离线接受。
实际四源Kbuild通过；compressed只手动两宏预处理分支，未由Kconfig生成或验证ABI，正式板配置仍禁用。
[核心封存](../outputs/rk3568-audio-runtime-20261005/asoc-open-rollback-v1/sealed-v1/receipt.json)
4357普通/4358SUM/8488外部普通+4单列SDK内部link经独立及主控fresh全SHA核回。
[主控回归](../outputs/rk3568-audio-runtime-20261005/build/root-asoc-candidate-v2/result.json)和
[接受边界](../outputs/rk3568-audio-runtime-20261005/REVIEW-ASOC-OPEN-ROLLBACK-20261006.md)保持。

无START双open检查器实际源码/host、ASan+UBSan和AArch64 QEMU的1032项每环境回归通过；
主控fresh独立编译复跑一致，真实静态AArch64产物655136B/SHA7693a052…4e661。
仅执行配置、状态、逐个HW_FREE/close，没有PREPARE/START/音频I/O。
SIGALRM只覆盖可中断设备调用，解除alarm后的stdout和D态等待不保证5秒。
[主控检查器回归](../outputs/rk3568-audio-runtime-20261005/build/root-pcm-peer-idle-v1/result.json)及
[检查器接受边界](../outputs/rk3568-audio-runtime-20261005/REVIEW-PCM-PEER-IDLE-20261006.md)已保存。
新独立audio-v4源码/原配置准备完成；新gate-v5绑定18831普通输入，独立审查接受后完整Image/modules实际exit0。
public14+privateASoC1共15次check/apply；89423完整tracked源按public基线+四源delta逐尺寸/SHA/模式核回，
全审查输入、原配置与原SDK前后保持。Image34755072B/SHA48b9958d…048595/CRC6908ddc6，
manifest8df52584…7aa33a；actualnotes60B/SHAa2008d93…b6436/GNU51e22386…0de907从actual vmlinux提取，
原ELF全SHA前后相同；尚未板核。codec/包/本轮板验继续。
[新完整构建](../outputs/rk3568-audio-runtime-20261005/build/integration-v4/manifest.json)、
[新构建身份](../outputs/rk3568-audio-runtime-20261005/build/live-image-v4-id/identity.json)。
peer seal主控fresh18771archive/source/18773SUM/9337external全核回，未重复模型；
[主控封存回核](../outputs/rk3568-audio-runtime-20261005/build/root-peer-idle-seal-audit-v1.json)。
新只读ADB重新确认root0/4.19.232/Android11/boot_completed1，未切换板系统。
电池算法、USB peripheral和early eMMC候选没有合入；TUN设置保持。

新codec实际build-v2已完成，模块519072B/SHAaa594a46…476171、manifest32241d1d…eb8e3c。
作者五实际命令0/stderr空，32U imports同时对应actual Module/vmlinux symvers，vermagic一致；
MODVERSIONS=n且实际无__versions，不称CRC runtime版本证明。root fresh新三只读ELF/nm审计与独立直接解析接受。
完整current actual generated ABI2020普通与root快照/影子一致；SOURCE6360普通+4文件link+13DTC目录link
的完整键、模式、字节/SHA或linktext对Image89423选集匹配，原有限输入前后及audit后保持。
DTC13目录target只核内部普通目录和祖先、不遍历内容；原SDKlink文本同步核，未知或错型仍拒绝。
初次build-v1在输入inventory拒绝未登记目录link，steps=[]/未compiler/make，失败保持；最终30preflight有限helper通过。
generated快照为Image完成后/precodec current旁证，不是编译当时签名全ABI。
[实际module](../outputs/rk3568-audio-runtime-20261005/codec-image-v4-v1/build-v2/manifest.json)、
[主控fresh审计](../outputs/rk3568-audio-runtime-20261005/build/root-codec-image-v4-audit-v1/receipt.json)、
[接受边界](../outputs/rk3568-audio-runtime-20261005/REVIEW-CODEC-IMAGE-v4-20261006.md)。
codec封存及v5包工具审查继续；没有加载新module或本轮板验。

codec最新owned指纹封存已完成并获独立只读接受：2255普通/2256SUM/10429外部普通+30typedlinks，
完整SHA、尺寸、Linux模式和有限link文本/target类型均0错，不递归DTC目录target。
[封存receipt](../outputs/rk3568-audio-runtime-20261005/codec-image-v4-v1/sealed-v1/receipt.json)
SHA90739568…60046e；这是live owned inventory，不是额外全字节archive。
[独立封存审查](../outputs/rk3568-audio-runtime-20261005/build/codec-image-v4-seal-independent-review-v1.json)。
v5启动包尚在工具审查，本轮板验未开始。主控fresh只读ADB重新核实原Android/root0/4.19.232/11/boot1，
七项保护及三项native输入全SHA与上一轮相同；cache可用21416KiB，需按新包实际大小安排已备份旧boot文件的有限回收。
[本轮启动前保护证据](../outputs/rk3568-audio-runtime-20261005/build/android-before-audio-v5-protection.json)。

v5 actual启动包已完成生产、作者audit、主控新CLI-r2审核并获独立只读接受。
41普通候选文件、26source快照、五runtime sidecars/精确SUM、40MiB padded86d835f6…23b4dd/CRCce635dcf，
1460224B全零尾核回。root41候选+core/gate共43前后全等；两actual audit receipt确定性内容相同，
独立执行日志分别保留，首次absolute gate入口拒绝不计成功。原源码public14+private1/当前2020ABI边界保持。
[最终离线接受](../outputs/rk3568-audio-package-20261005/REVIEW-production-v5-20261006.md)、
[root实际新审核](../outputs/rk3568-audio-package-20261005/build/audit-root-cli-v5-r2/result.json)。
v5最终seal尚在--check及schema复核。新三个板准备工具仅完成有限模型和步骤生成设计；
正式board-audio-v5/live-audio-v5尚未生成，未回收旧cache镜像/上传/切换系统/发本轮START。

2026-10-06 v5包最终seal0178b394…69ea18已完成并获独立有限复核：30copied tools/32 frozen/33SUM、13121外部普通与30typed SDK links。只复制工具源码，实际bundle作为全SHA外部引用；[root seal独立复核](../outputs/rk3568-audio-package-20261005/build/seal-independent-review-v5.json)。随后仅回收已备份且全SHA匹配的旧v4单个cache boot文件，新v5八普通输入45172454B上传并逐SHA核回，7保护+3native输入前后保持。一次ext4load完整40MiB/CRCce635dcf、一次RAM bootm，新Image-v4原生PID1就绪；未flash/saveenv/改TUN。新live notes60B/a2008d93…b6436与PID1 249cc1cf…d76368b板核一致，新live FDT168064B/ddb3fe03…692d15完整UART导出，全属性/保留区与旧v4相同。before dmesg29854B/52a97676…b84ff4完整回核（一次缺1024B仅重读原块256×4，失败raw保留），没有WARN/BUG/trace/panic/ASoC error。当前Linux rescue，aux已复制RAM，尚未load新codec或START；全迁移仍未完成。
[实际新包上传](../outputs/rk3568-audio-runtime-20261005/build/audio-stage-v5.json)、[完整live FDT导出](../outputs/rk3568-audio-runtime-20261005/build/board-exports-v5/live-fdt-hex-extraction.json)、[主控DT语义回核](../outputs/rk3568-audio-runtime-20261005/build/root-live-fdt-v5-audit/root-semantic-analysis.json)。

2026-10-06 v5 RAM实机回归和正常Android返回已实际完成：四无START peer顺序各34OP/exit0/stderr空，14完整strictguards；两单向各24576frames/98304B、oneSTART/正常DROP/FREE/CLOSE，OFFcapture全零仅数据传输证据。正常card/module/CPU卸载后DMA allocated0/quarantine0/16音频clock均0；native codec/pty0、RAM return63及ordinary reboot正常。新Android返回receipt actualcompleted=true/5commands0，七保护+三native全SHA保持；重启后的task bridge重新连接，未改TUN。原wc wrapper、丢hex块、ADB closed与collector1024-only失败均保留，未重跑peer；collector窄r2待独立审核后的actualmain，不能将其写成成功。[本轮详细记录](../outputs/rk3568-audio-runtime-20261005/SESSION-20261006.md)、[新Android返回](../outputs/rk3568-audio-runtime-20261005/build/audio-return-v5-r2.json)、[完整原捕获输入](../outputs/rk3568-audio-runtime-20261005/build/board-trial-v5-inputs-r2.json)。当前板原Android；全适配未完成，shared params旧实现8业务红已三环境复现，[结果说明](../outputs/rk3568-audio-runtime-20261005/full-duplex-params-baseline-v1/RESULTS-v2.md)；新有限候选仅设计/模型阶段，四dualSTART/jointSTOP旧红不变。

2026-10-06 v5正式collector-r3实际一次exit0/stderr空，result SHA8d504646…99550a；190有限输入前后/当前全SHA一致，主控独立回读63原导出、14guards、4×34peer、两96笔/98304B IO与5个Android return commands0。原attempt1/2退出1均保留，只修完整256块兼容及合法return自动phase4+显式status phase4的精确有序解析；未重跑板程序。源码窄修各获独立只读审查。[正式结果](../outputs/rk3568-audio-runtime-20261005/build/board-results-20261006-v5-r3/result.json)、[主控回读](../outputs/rk3568-audio-runtime-20261005/build/root-board-results-v5-r3-review.json)。当前板保持原Android（状态只对fresh返回receipt时刻有效）；shared params五文件私有候选实现中，四dualSTART/共同STOP红与物理声音/显示/供电参数/正式恢复边界不变。子agent工具不能继续创建旧agent回合时，主控按已审源码/显式descriptor完成offline入口，没有扩大板权限。

参数事务以外的控件/PM真实caller只读边界已保存：[有限共享IO旁路调查](../outputs/rk3568-audio-runtime-20261005/build/codec-shared-io-boundary-v1/README.md)。原RK817没有codec DAPM事件；manual power/path与systemPM会触碰共享状态，部分int回调被void wrapper忽略。主控核实际注册点已更正CPU结论：checked_component没有controls，generic source-select/loopback等只在legacy实例注册；checked同时排除PPM。原报告错误字节和更正依据单列保存。这是后续软件整合缺口，不是新模型/实机通过。

新声音软件已离线收口：params v4、CPU TRCM v3、DMA v5、controls/terminal v5统一新头与PM首sticky/owner门。CPU/DMA接缝三环境12/12合同+100/100观察/19case，DMA37/37，terminal1471/1471；主控实际合PM CPU回归三环境通过。独立源码和追加真实Image/模块绑定审查未见具体阻塞。完整audio-v5 Image/modules实际0，89423 tracked源前后同，對已接受audio-v4恰好11文件差异，私有增量在副本实际check/apply0并逐字等。Image34755072/e2a5590f…ae3f61；最终canonical模块606536/c43e470c…e13d85，内部snd_soc_rk817，37imports闭合实际两symvers、2020generated前后同；首次rk817_codec.ko仅中间产物。MODVERSIONS=n，文件等待5000ms不作整个shutdown硬时限。

新配对CPU/codec bool DT与40MiB离线RAM候选已实际构建，padded90e663bc…59dc0b1/CRC4427a536。主控fresh CLI完整36文件与真实overlay/零padding核回，39有限输入前后同。没有新板操作，用户明天接外设；硬件仍以上轮fresh Android返回证据为准，运行状态须重核。电池参数后补/算法禁用、DMO引脚不明与USB恢复、正式启动及物理声音/显示/全平台关机仍未闭合，TUN保持。入口：[软件推进](../outputs/rk3568-audio-runtime-20261005/SOFTWARE-PROGRESS-20261006.md)、[新离线交付](../outputs/rk3568-audio-runtime-20261005/offline-next-delivery-v1/README.md)、[下一次实测](../outputs/rk3568-audio-runtime-20261005/NEXT-HARDWARE-VALIDATION.md)。完整迁移未完成。

## 2026-10-07 更换带外设的 RK3568 板

新板网络ADB连接、root/Android11/4.19.232#49已实际确认；型号3568A、约4GB/64GB。
原fingerprint/内核配置与旧板相同；完整FDT760节点/4756属性只8项设备标识/MAC/启动计数差异，
bootargs仅serialno/cid/cpuid变化，全部其余属性与保留区相同，支持复用现有板级配置。
八个启动/恢复分区161480704B已完整本机备份，前/本机/后SHA一致；七份与旧manifest全等。
固定SHA静态BusyBox、codec与PTY自检已在新板实际exit0；八分区与boot_id后核保持。
本轮只有网络ADB、未见调试串口；原CONFIG_KEXEC未启用，保持Android，未切内核或打开电机物理UART。
新板原系统枚举720×720屏/RK809/USB音频/CAP1188/McuCom，不继承旧板实物验收结论。
现有audio-v5候选两完整文件SHA/CRC核回，未部署/启动；接调试串口和验证返回链后继续RAM迁移。
[本轮检查与继续入口](../outputs/rk3568-newboard-20261007/README.md)、
[完整摘要](../outputs/rk3568-newboard-20261007/fdt-comparison.json)。地址/设备状态下轮重新核实。

同日用户报告新板持续控制电机并要求关闭进程：com.patchx_main原PID1967在force-stop后被重新拉起为4422，
随后pm disable-user再force-stop，至少20秒后pidof无进程、stopped=true/enabled=3。
应用/数据保留、com.patchx_sys保留、Android仍运行；未打开电机UART或发送动作/停止命令。
当前主应用为disabled-user；恢复命令pm enable --user 0 com.patchx_main未执行，实物停止待用户反馈。
[停止证据](../outputs/rk3568-newboard-20261007/motor-process-stop.json)。PID和当前进程状态下次重核。

用户随后明确反馈电机在主应用停止后仍持续同向转动。短时FD/四候选67线程8秒trace未捕获新设备打开，
仅有限诊断，不证明MCU停止或全系统无控制；实际安全停止协议仍缺。保留厂家多用途smdtserver。
再force-stop PatchX后台与串口测试后用户仍反馈转动，后台重启为5308；现亦disable-user后台再force-stop。
两PatchX应用已fresh核无PID/stoppedtrue/enabled3；串口测试无PID/stoppedtrue/仍enabled0。
最后禁用后台后用户明确回复“现在好了”，本轮停转由用户现场确认；未独立测量运动。
保持两PatchX应用禁用，应用/数据保留；具体电机接线和真实发送线程/停止协议仍未确认。
[追加诊断/最新应用状态](../outputs/rk3568-newboard-20261007/motor-control-followup.json)，
后台恢复命令pm enable --user 0 com.patchx_sys未执行；仍需下次fresh核。


## 2026-10-08：按主题提交并同步 RK3568 工作分支

用户本次明确授权分批提交并推到远程；此授权对应本轮项目保存，不是持续后台推送授权。
操作分支为 `codex/rk3568-platform`，远程为 `origin` 同名分支。起点 `29c5956`，
相对远端 main 有 26 个既有未推提交；保留历史，普通 push，不改写或合入 main。
本轮源码/工具的九个批次已推送，并实查远端头与本地
`bda88eed9ceb06b6015240b8d6e1af58d5ed1cef` 一致；本条及状态文档作为最后一批同步。
当前远端头、运行状态和输入条件仍应在下一任务重新核实。

检查覆盖 release/ASan 各 41 项、人脸 12 项、八组 DT 正向 1103 项与对应故障检查，
14 份补丁的有限顺序重放、下一版离线音频包 24 项输入/格式测试及脚本解析。
全仓格式检查的 53 个失败文件均能在起点版本复现；本次四个人脸文件单独通过。
备份镜像、原机数据、复制内核和编译/运行子树留本地；作者入口、有限证据与许可明确的小输入已保存。
本轮没有板卡动作，也没有把离线候选写成新板硬件验收；未提交 Notebook 或另一个 RKAIQ worktree。
空白清理范围过大及封存输入的核回结果见证据记录，不能把未记录原 SHA 的两个历史工具称作原字节恢复。

证据：[同步与验证记录](../outputs/rk3568-git-sync-20261008/README.md)，
[有限检查结果](../outputs/rk3568-git-sync-20261008/verification.json)。


## 2026-10-08：修正全仓格式门禁

用户紧接项目保存要求修正刚才报告的格式问题，按仓库现有规则处理。
起点为 `b77369b`，工作区干净；使用 clang-format 18.1.8 和既有 CMake `format` 目标，
只修改与原失败清单精确一致的 53 个第一方 C/C++ 文件。
没有改 `.clang-format`、格式目标范围或实验封存输入；采用既有 4 空格、85 列、无制表符规则。

实际 `cmake --build --preset release --target format-check` 和 `git diff --check` 均通过；
release、ASan/UBSan 构建及测试各 41/41，face-video 构建与人脸专项 12/12 通过。
独立审查核对 token、宏、预处理条件和字符串：仅长字符串拆为值相同的相邻字面量，
三处 include 排序保持条件块及依赖；无运行行为或公开契约变化。
这是此前同一交付的格式补修，独立提交并同步到原 `codex/rk3568-platform` 分支；
下一任务仍须查询实际 Git 引用，不把本条视为持续推送授权。
没有重编内核/IgH SDK，也没有板端操作；纯格式检查不扩展任何硬件验收结论。
