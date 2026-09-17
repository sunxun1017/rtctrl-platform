# RV1126B 交互终端

独立非实时进程，为已有视觉与控制平台增加云端语音、二维表情和中文控制台。
适用目标为正点原子 RV1126B、1GB RAM / 8GB eMMC。不会打开摄像头、修改人脸库或直接驱动执行器。
Python 只负责编排、HTTP 与小块音频传输；Opus 在原生库、ALSA 在独立子进程中执行，不进入实时控制线程。

## 功能与边界

- 手动连接；默认静音。显式取消静音并按住说话才启动**板端麦克风**；浏览器不采集电脑麦克风。
- 16kHz PCM16 单声道录音，60ms Opus 上传；根据 hello 协商 16/24/48kHz 回复播放。
- 松开结束、最长录音限制、响应超时、静音、打断；播放期间不录音。
- 识别文字、回复文字、情绪与二维动画；界面完全本地，无 CDN。
- 读取既有人脸服务 `/status.json`；帧计数停滞或失联时撤销显示结果，不重新占用摄像头。
- 后台错误可见，队列有界；断线停止音频，用户显式重连，不后台重开麦克风。
- 协议没有可靠的轮次 ID，因此打断会发送 abort 并重建连接，隔离旧回复；可能丢失后端会话上下文。
- 设备控制仍由现有 control/actuator 产品负责。本服务忽略云端机械动作请求，不能用未经标定的人脸匹配武装设备。
- **尚未实现**离线唤醒词、AEC、全双工自动打断、本地 LCD/framebuffer 渲染、语音到运动指令映射。二维表情当前在浏览器中显示；板载屏幕需另接轻量显示端，不能据此假定板上 Chromium 的资源够用。

## 立即运行演示

在仓库根目录：
```sh
python3 -m apps.companion --config config/companion/demo.json
```
打开 http://127.0.0.1:8090/ 。连接 → 开启麦克风 → 按住说话 → 松开，查看演示状态。
**演示模式不打开声卡、不连接语音后端、不产生真实声音。**
Ctrl+C 或 SIGTERM 正常释放进程。它不是开机自启动服务。

## 原 Android 后端

`config/companion/rv1126b.json` 使用 Android C 工程当前配置：
`ws://118.196.28.154:8060/`。2026-09-18 初始 WSL 握手返回
Opus/24kHz/mono/60ms；后续板端已上传录音，但完整识别/回答未通过，固定文字测试也未收到回复音频（详见验证记录）。另一个旧地址 `ws://118.31.173.231:8260`
本次连接失败。服务可用性可能变化，握手不是语音或设备授权完整验收。

令牌使用环境变量，配置与状态接口不存放令牌。原仓库使用测试令牌，开发验证可：
```sh
export RTCTRL_VOICE_TOKEN=test-token
```
生产替换为运营方分配的令牌；`device_id` 应改为已登记的设备标识。
原后端为明文 ws，因此此配置显式允许；支持时改 wss 并关闭 `allow_insecure_ws`。
不能从协议推定服务器保存策略或机械控制权限。

## 实际音频模式

需要 Python 3（含 SSL）、alsa-utils 的 arecord/aplay、libopus、websocket-client 1.8.0。
依赖是否存在以板上 doctor 为准，不凭 BSP defconfig 推定已安装。

```sh
python3 -m pip install --target .deps/companion-python -r apps/companion/requirements.txt
export PYTHONPATH="$PWD/.deps/companion-python"
python3 -m apps.companion --config config/companion/rv1126b.json --doctor
python3 -m apps.companion --config config/companion/rv1126b.json --probe
python3 -m apps.companion --config config/companion/rv1126b.json
```

doctor 只检查依赖，不打开麦克风；probe 只做握手并校验 session/audio 格式。
按板上的 `arecord -l` / `aplay -l` 修改 capture_device / playback_device。
本版要求 ALSA 能提供 16kHz 单声道；原始多通道阵列需要先由板级音频适配/算法输出单声道，
不能把 8 通道数据直接当单通道发送。

服务只绑定 loopback；远程通过 SSH 隧道访问（端口保持一致）：
```sh
ssh -N -L 8090:127.0.0.1:8090 USER@BOARD
```
电脑浏览器打开 http://127.0.0.1:8090/ 。此服务默认不暴露局域网写接口，不提供公网认证网关。

## 打包与启动

```sh
python3 scripts/package-companion.py --python-deps .deps/companion-python
```
生成 build/companion/rtctrl-companion.tar.gz，包含程序、网页、配置、依赖、启动脚本、
README 和 SHA256 manifest；不包含环境令牌、录音、人脸库或模型。
将包解压到板端独立目录，设置环境变量后：
```sh
sh run-companion.sh config/companion/rv1126b.json --doctor
sh run-companion.sh config/companion/rv1126b.json
```
启动脚本不设置 FIFO、不修改系统、不装驱动。不自动停掉已有视觉进程。
可选 systemd 模板在 deploy/companion；Buildroot 未启用 systemd 时使用厂家的进程管理机制，
不要直接安装该模板。

## 资源与验收

事件队列最多48项；每条文本64KiB、音频4KiB，播放队列默认16包；视觉响应64KiB。
音频设备读取/写入有超时，最大录音默认30秒，响应默认45秒。
CPU 指标是**本服务进程**单核100%口径，不包含 arecord/aplay 和人脸服务；
RSS 也不等于整机内存或 DMA 预算。页面另显示系统 MemAvailable 推算的内存占用。
播放结束使用样本时长估算及尾音余量，不是 ALSA 硬件游标确认。

宿主回归：
```sh
PYTHONPATH=.deps/companion-python python3 -m unittest discover -s tests -p 'test_companion*.py' -v
```
完整 transport 集成测试需要固定依赖；未安装时相关测试明确 skip。
测试含真实本地 WebSocket Upgrade/分片限制和真实 libopus（主机具备时），其余声卡用替身。
CTest 默认注册六组 companion 测试；Python应用不由 C++ 编译器构建。

上板验收仍需：实际声卡录放、真实语音往返、与视觉并发的峰值内存/CPU、30分钟运行及网络中断恢复。
不能把宿主测试或后端 hello 当成这些验收已完成。

## ALIENTEK ES8389 板端配置

2026-09-18 的实物板在直接16kHz单声道采集时无DMA进展；48kHz双声道采集正常。
此为该固件现场现象，不代表所有RV1126B不支持16kHz。专用plug配置固定硬件48kHz双声道，
应用仍上传16kHz单声道，下行按协商24kHz解码后由ALSA转换。使用前核实card0确为ES8389：

```sh
export ALSA_CONFIG_PATH="$PWD/deploy/companion/asound-rv1126b.conf"
```

将配置中的capture_device与playback_device均设为rtctrl_es8389。
不覆盖系统asound.conf；此环境变量只影响本进程及其录放音子进程。
板载麦克风使用Main Mic/AMIC；现场ADCL/ADCR PGA从0调整至8（24dB），spk switch从off调整至on，
未使用alsactl store持久化；其他板卡需根据实际输入、电平和音量确认。

原Android C后端配置使用listen_mode=realtime。松手立即停止真实采集，发送1.2秒合成静音让后端VAD结束一句话；
manual模式仍发送listen.stop。两种模式均在没有上传完整采样帧时立即报错，避免空录音进入等待。
metrics.capture_peak_amplitude显示当前轮16位采样峰值，仅用于排障，不保留录音，也不是语音识别置信度。

## Wi-Fi 配网

安卓参考仓库的ProvisionClient通过AIDL读取独立系统应用com.patchx_sys的配网信息，
DeviceManager把重置Wi-Fi请求发给该应用；本仓库没有其ProvisionService实现。
Linux版本使用板上已有ConnMan，不依赖安卓系统服务，不启动第二个wpa_supplicant。

仅在有ConnMan与connmanctl的设备中将配置wifi_enabled设为true，默认关闭。
控制台展开“网络设置”，网卡关闭时先主动点击“开启 Wi-Fi”，再扫描并选择已发现的开放网络或个人密码网络，输入密码连接。
开启Wi-Fi后ConnMan可能自动重连系统已保存的网络；扫描本身不隐式开启网卡。
扫描可能需要约30秒，连接最多45秒；后台任务不会阻塞语音状态机。
只管理Wi-Fi服务，网线继续保留。隐藏网络和企业认证暂不支持。
密码只经本机HTTP/SSH隧道送到ConnMan交互代理，不放入命令行参数、不写应用日志或浏览器存储；
ConnMan会按系统机制保存成功连接的凭据用于重连。当前断开功能不等于删除系统已保存凭据。
不要将控制台直接暴露到公网。API沿用loopback、同源写入、有限请求大小与并发限制。

2026-09-18实物检查：ConnMan和wpa_supplicant已由系统启动，Wi-Fi初始关闭；启用后能扫描附近热点。
按用户要求本轮不连接网络；密码认证、DHCP和重连仅完成模拟回归，尚未真机验收。

## 运行状态诊断

语音页面区分等待识别、等待回答、等待语音音频和接收音频。
tts.start只证明后端进入回复阶段，不代表收到声音或扬声器发声；对应阶段超时会给出具体提示。
网络设置展开时，GET状态最多每5秒触发一次有界只读ConnMan查询，不会自动启用、扫描或连接网络。
查询失败会撤销旧的连接/IP显示并标记过期；正常后台刷新不打断页面操作。
其他进程改变网络后，无需重扫热点也能看到当前连接变化。

部署与剩余验收见[产品检查清单](../../docs/companion-readiness.md)。

服务的显式启动、停止、重启与可选 Buildroot 启动模板见[服务管理](../../deploy/companion/SERVICE.md)。


## 声音与屏幕

真机配置显式设置 `device_settings_enabled: true` 后，可在控制台展开“声音与屏幕”。
默认关闭，演示模式始终不控制宿主硬件。该功能独立于云端语音连接。

- 播放音量：0–100%，映射 ES8389 DACL/DACR 的 0–191 范围，最高0dB，不启用额外数字增益。
- 扬声器：同时控制 Speaker 与 spk switch；与页面麦克风静音相互独立。
- 麦克风增益：0、6、12、18、24dB，同时调整左右PGA，不启动录音或改变输入路由。
- 屏幕背光：10–100%，读取当前backlight的最大值换算，避免误设全黑。

修改后需显式应用并读取设备返回值；失败会提示，设备不支持的项禁用。
配置适用于本次已核实的ALIENTEK RV1126B/ES8389控制名，不自动推广到其他声卡。
设置仅作用于当前系统，不写入alsactl持久配置、不承诺重启保持；服务启动不会自动改写设置。
API为同源 `GET /api/device` 和 `POST /api/device`，不接受任意命令、声卡名或文件路径。
