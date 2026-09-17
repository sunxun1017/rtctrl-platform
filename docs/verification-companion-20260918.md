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
