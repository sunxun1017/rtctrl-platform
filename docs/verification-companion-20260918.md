# RV1126B 交互终端实现与验证记录

日期：2026-09-18。

## 实现

新增 apps/companion 独立非实时应用，复用现有人脸 /status.json，提供中文浏览器控制台、
二维表情、按住说话、Opus/ALSA音频、云端WebSocket会话、手动打断、静音、超时、错误恢复、
资源状态、依赖检查与部署打包。默认演示、静音，声卡仅在用户开始说话时打开。
Python事件队列48项、输出队列16包、文本64KiB/音频4KiB/人脸响应64KiB限制。
网络适配器锁定websocket-client 1.8.0，校验版本、TLS、帧长度、分片累计和ping/pong。
打断通过新连接隔离旧回复；capture_epoch隔离前一轮录音回调。
未修改现有人脸算法、模型、人员库或实时控制核心。

原Android C工程后端 ws://118.196.28.154:8060/ 返回24kHz输出；上传保持16kHz。
配置保留此地址，测试令牌通过环境变量传入，不保存真实凭据。
旧地址 ws://118.31.173.231:8260 本次未连通。

## 实际验证

- 完整新增测试：56/56通过（core/config/monitor/HTTP/打包21，audio15，transport20）。
- 使用本地安装的固定网络依赖运行全部测试，无依赖跳过：
  PYTHONPATH=work/companion-python python3 -m unittest discover -s tests -p 'test_companion*.py' -q
- release、asan配置/构建通过，CTest各16/16通过。transport在显式绝对PYTHONPATH下额外复验通过，
  确保没有将缺依赖时的skip当成完整网络验证。Python测试本身不被C++ ASan插桩。
- 真实libopus16k编码→16/24/48k解码往返通过；不使用真实声卡。
- 真实127.0.0.1 WebSocket Upgrade、masked消息、二进制、ping/pong、黑洞连接、
  错误pong与超大帧头拒绝通过。
- 外部后端probe握手通过；完整core静音连接20秒后仍connected=true、muted=true，
  audio_frames_sent=0，正常释放。该WSL进程peak RSS 20584KiB，仅为空闲短测。
- 浏览器手动走通演示连接、启用、按住/松开及回复；PC和800×480截图检查，
  小屏主控按钮均首屏可见。
- python打包生成自包含tar.gz；解包后demo doctor测试通过；含固定Python依赖，
  不含模型、人脸库、录音、环境令牌。
- check-architecture.py通过；git diff --check通过。
- 全仓format-check仍失败于既有C++格式差异，例如products/yidong23/.../topology.hpp、
  tests/test_main.cpp等，本次无C++源码修改，未全仓重排。

## 尚未验证或实现

已部署到目标板，依赖doctor及后端握手通过；实际录放音结果见下方追加记录。
真实语音识别/回复内容、实物扬声器、长时间稳定性、与人脸并发资源/温升尚未验收。
离线唤醒词、AEC/全双工自动打断、本地LCD渲染、云端语音到运动意图映射没有实现。
界面展示这些边界；现有控制产品继续独立工作，云端消息不会直接武装执行器。
本次是可测试和打包的交互功能集成，不是整机量产验收完成。

使用步骤见[应用说明](../apps/companion/README.md)，架构见[ADR0009](adr/0009-companion-nonrealtime-service.md)。

## 板端部署与录音排障

实物ALIENTEK RV1126B，Linux6.1.141/aarch64/Buildroot2024.02，MemTotal约970MiB，无swap；
产品预算的2GB不是这块实物板的容量。程序部署至独立目录，未刷机、未修改模型或人脸库。
Python3.11、libopus、ALSA、SSL与固定websocket依赖可用。仅网线直连时原后端直连失败，
通过临时反向SSH隧道完成hello，输出24kHz；本地8092转发板端8092，非本机演示。
现有视觉程序以native-fp16/RGA direct/MPP async启动，沿用现有图库，绑定loopback。
并发静音15秒4次采样：companion RSS24.66MiB，进程CPU0.96–1.07%，人脸FPS29.90–30.14；
全机MemTotal-MemAvailable约194–201MiB。无上传音频；该数据不是有声对话或长时压力测试。

用户长按后无回复，初始上行0帧。独立arecord使用plughw:0,0/16kHz/mono/S16_LE，5秒无数据，
ALSA显示RUNNING但hw_ptr=0；硬件48kHz/stereo约1秒获得167936字节，hw_ptr42016。
专用plug固定48kHz/stereo，转换为应用16kHz/mono约1秒获得27520字节。
24kHz播放经同一plug转换为48kHz/stereo，静音PCM测试aplay退出0，尚不等于确认扬声器实际发声。
首次修复后用户PTT成功上传74帧，但仍无STT；另一轮44帧也无STT。
原Android使用realtime连续上传，未使用manual结束；新增协议兼容路径及空录音防护。
麦克风原模拟增益0dB，现场调至24dB；扬声器底层开关原off，调至on。
仅采样统计不保存录音；实际语音往返与扬声器听感尚需继续验证。

本轮兼容模式验证：用户一次PTT的捕获峰值223/32768，上行含尾静音共101帧，45秒内无STT或回复，
正确进入超时错误。信号偏弱，尚不能证明有效人声已被后端接受。
独立固定文字detect对照（不采麦克风）收到STT回显与tts.start，45.2秒内0音频帧、无回答文本或tts.stop。
这说明当前端到端阻塞不止板卡录音；未取得后端日志，不能确定ASR/LLM/TTS/账号配置中哪项异常。
新增空录音、realtime尾静音、提前TTS、清理隔离及电平统计回归后共66项测试通过；
release/asan CTest各16项通过。无C++改动，全仓格式基线问题同上。

## Wi-Fi 配网功能

安卓侧证据：ProvisionClient显式绑定com.patchx_sys.provision.ProvisionService，
IProvisionService仅定义getWifiProvision返回info/expireAt；DeviceManager的ACTION_UNBIND携带needReSetWifi。
该系统应用实现不在参考仓库内，不能据主应用推定具体二维码、蓝牙或热点配网流程。

板端可见wlan0/wlan1，ConnMan与wpa_supplicant系统进程运行，connmanctl可用，nmcli不可用。
Wi-Fi初始Powered=False。enable wifi后第一次scan返回No carrier，随后scan成功并列出热点。
Linux功能以ConnMan适配、异步任务和折叠控制台入口实现，默认wifi_enabled=false，板端明确启用。
按用户最新要求，只验收扫描，不提交任何网络密码、不连接任何热点。真实认证/DHCP/重连留待之后验收。

Wi-Fi验收结果：13项网络单测通过（包含真实本地PTY替身、输出超限与子进程回收），HTTP新增同源与异步派发测试通过。
release/asan重新配置、构建通过，CTest各17/17通过。浏览器真机8092操作扫描完成，显示11个热点，
API busy=false/status=idle/error为空，connected_wifi=0；eth0仍为192.168.50.2/24。
页面布局检查通过，网络区展开且密码为空，未点击连接或断开。Wi-Fi包SHA256：
e14f37a3bd6bd43238e5fa4cdd50fa29b318b24b5230df6dd9cd8d17b265339a，板端manifest逐文件验证通过。

## 状态诊断与服务管理追加验收

语音状态现在区分录音、等待识别、等待回答、等待语音数据及实际收音频；tts.start不再被当作已有声音。
分阶段超时带具体原因，迟到的STT不会把已接收音频状态退回。没有重新录音或重试原后端。
Wi-Fi最多每5秒发起一次只读ConnMan状态刷新；超时或过期撤销连接/IP显示，后台刷新不隐式开启、扫描或连接。
新增service-control.py及可选S95模板；PID身份核验、独立进程组、有界退出和日志轮转通过测试。
日志3份、每份64KiB；崩溃不会自动重启。不安装启动项、不重启板卡。

最终99项companion测试通过（32.914秒）；release/asan配置及构建成功，CTest各18/18通过
（40.28/40.56秒）。其中包含9项真实子进程服务管理测试和20项网络测试。
浏览器真机页面检查：语音默认未连接/静音，网络区只读刷新显示11个热点，没有连接任何热点。

部署包SHA256为8ba00703c237489d28bf306b12a1364a0e5f3a561ee23a8703518f7f6d87cab6，传输后校验一致。
板端目录/userdata/rtctrl-companion-20260918；service.env权限0600，运行状态位于/run/rtctrl-companion。
原手动进程被正常停止；实际执行start、重复start、stop、start和restart均通过。
重复start保留同一child PID；stop后status返回未运行；最后restart后supervisor PID7090、child PID7091。
HTTP就绪复核：offline、muted=true、voice_progress=idle、收发音频帧均0；人脸服务PID976仍运行、29.9842FPS。
该快照companion RSS22.03MiB、全机已用约200MiB，不作为持续或有声负载性能结论。
当前访问依赖SSH正反向隧道，关闭隧道后控制台/云端路径需重新建立；开机恢复与长期运行未验收。
剩余工作及依赖见[产品检查清单](companion-readiness.md)。

## Android鉴权对照复核

对照参考仓库嵌套PatchX-Android-Main-C，而非顶层旧版：AndroidManifest.xml:76、84-85的launcher为MainActivity2。
以下Java路径相对app/src/main/java/com/patchx_main/patchx/：
- manage/WebSocketManager.java:68-75、147-150：固定测试Bearer令牌，Device-Id取UnifiedRobotState.getSn()，Client-Id固定，Protocol-Version=1。
- MainActivity2.java:136：初始化硬编码设备身份。不是WebSocketManager内未使用的DEVICE_ID常量。
- manage/WebSocketManager.java:239-258：hello还有client_ip和trace_id，Linux当前未发这两项。
- manage/WebSocketManager.java:626-647：listen/start使用session_id和realtime，Linux基本字段一致。
- manage/WebSocketManager.java:461-467、552-560及voice/WakeUpController.java:113：人脸ID大于0时发送updateUserId；不是通用登录换取token流程，Linux未上传该云端用户身份。

本次只读核实板端配置和环境文件：令牌存在且与安卓测试令牌相同（未输出令牌），Client-Id相同，listen_mode=realtime；
但Linux Device-Id为rtctrl-rv1126b，并非安卓启动时初始化的SN。没有切换身份、连接MQTT或重新录音。
现有语音WS代码未发现从Wi-Fi配网领取令牌或另发模型API密钥的流程；MQTT设备管理使用独立连接。
结论：不是简单漏传Bearer令牌；设备绑定/设备配置是否必要、hello额外字段及用户身份是否影响此后端，仍需服务端证据或受控对照。
此前固定文字回显和tts.start、45秒无回答/音频，仅证明处理进入回复阶段，不能证明完整鉴权和模型调用成功。
不能把未得到完整回复直接确定为服务端模型故障，也不能认定更换密钥或设备ID就能修复。

## 声音与屏幕设置真机验收

新增DeviceManager和同源/api/device，配置device_settings_enabled默认false；demo模式强制不启用硬件控制。
控制台新增折叠面板，支持音量、扬声器、麦克风增益、背光，必须显式应用，不采音或播放测试音。
板卡实测amixer sget/sset适用；cget name=DACL不适用，不能混淆simple mixer与原始control名称。
音量DACL/DACR限制raw0–191（最高0dB），增益ADCL/ADCR PGA仅0/6/12/18/24dB，背光10–100%。
默认构造和刷新不写硬件；操作串行、250ms单进程超时、8KiB输出上限、失败回滚并核对；不保存重启配置。
页面允许原有0%背光恢复到受限范围，非枚举实际增益只作读值显示；过期操作错误能在成功刷新后恢复。

112项companion测试通过（33.496秒）；release与ASan配置、构建成功，CTest各19/19通过（41.14/41.18秒）。
新增12项设备适配器测试覆盖默认无写入、类型/边界拒绝、双通道失败恢复、静默写失败、超时与输出限制。
新增HTTP设备接口同源与禁用测试；UI Node VM覆盖草稿保留、忙碌/错误、回读、0%背光和非枚举增益。

部署包SHA256：df21fbbfa43d1a35d6eda20d1d0d6204a0cd6018d6325c77b3b10ed7e0c07211。
传输哈希一致，板端manifest60文件全部匹配；独立bundle配置明确开启device_settings_enabled，服务重启正常。
初始实际值：DACL/DACR=191，Speaker=on、spk switch=off，ADCL/ADCR PGA=8（24dB），backlight=200/255。
因此API显示音量100%、扬声器关闭、增益24dB、亮度78%。API音量百分比以0dB上限归一化，不是amixer原生百分比。
实际HTTP测试：音量50→100%、增益18→24dB、亮度70%、扬声器开→关，逐项读回正确。
finally按原始值精确恢复（包括Speaker=on、spk switch=off和背光raw200，避免百分比四舍五入误差）。
复核offline/muted=true/voice_progress=idle，音频收发帧0，人脸约29.86FPS。
浏览器8092已展开声音与屏幕，四项读数正确、窄屏无横向遮挡；未连接Wi-Fi，未修改后端鉴权身份。
控制读回不等于扬声器听感或实际屏幕观感验收，未实现LCD界面渲染/开机保存。
