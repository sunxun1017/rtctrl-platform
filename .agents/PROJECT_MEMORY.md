# rtctrl-platform 项目记忆

更新时间：2026-09-18。用于新任务接续工作；不是运行中设备的实时状态。

## 先读哪里

- [项目地图](skills/rtctrl-dev/references/project-map.md)：模块、适配器和构建入口。
- [已验证经验](skills/rtctrl-dev/references/lessons.md)：历史问题、适用条件和失效边界。
- [视频程序说明](../apps/face_recognition/VIDEO.md)：采集、推理、浏览器预览的实际实现。
- [最近缓存与 swap 实验](../outputs/cache-swap-20260912/README.md)：原始数据、对照和限制。
- [上一轮 ftrace 证据](../outputs/ftrace-20260912/)：调度、NEON、模型副本释放。

## 协作偏好

默认中文，先复用已有代码和已验证经验。优化同时观察 CPU、内存、NPU、帧率与丢帧；用 perf/ftrace 等证据定位，不凭百分比猜原因。
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
