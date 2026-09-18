# 对话延迟分段与流式播放验收

2026-09-18，正点原子RV1126B实物1GB（约970MiB可见），保持Zipformer RKNN及Melo混合NPU，
Runtime2.3.2、driver0.9.8。无用户麦克风采集，没有改变音色、语速、模型或增益。

## 等待在哪里

固定文字“你好，请用一句话介绍自己。”调用实际千帆三次，原整段TTS链路：

| 阶段 | 本次测量 |
|---|---|
| 千帆请求完整返回 | 1.465–1.562s，中位1.558s |
| 其中代理/TLS建连 | 0.066–0.179s |
| 其中等待响应头 | 1.362–1.460s |
| 返回的21–22字在本地合成 | 3.489–4.542s，中位3.493s |

回复有生成差异，所以这些数据用于定位，不是严格同内容TTS A/B。
[原始数据](performance/voice-latency-20260918/latency-baseline.jsonl)不含密钥或返回文本。
加上先前同版本ASR公开5.6115s样本约1.45s的录音末尾到final等待，短回复体感约数秒属串行积累，
不能把全部等待算成ASR或网络；该ASR数字来自上一轮，不伪装成本轮新测。
实际真人停顿位置不同，断句约1–2s波动，0.96s模型步长仍保留。

Melo内部CPU/NPU虽已并行，但之前仍等待全部batch完成、拼接WAV、CLI返回才播放。
既有perf证据定位CPU前端/flow的SGEMM热点，见[Melo性能记录](verification-melo-performance-20260918.md)。
本轮重点用单调时钟分段追踪证明首音路径等待，没有重复采perf/ftrace或调整CPU/NPU频率。

## 改动

- Melo同一次prefix.generate按原完整batch做decoder和ScaleSilence，再回调PCM；不自行按字切文本。
- worker的tts_stream用JSON头+有界原始PCM，取消/背压/断连及时收尾，累计45s。
- transport直接用本地socket接收音频，取消整WAV落盘与CLI轮询；保留原路径，默认local_tts_streaming=false。
- AudioIO每轮一个aplay，原始44.1kHz采样依次写入，收到end才EOF/drain；不逐块重启、不重采样或Opus编码。
- 默认local_tts_prebuffer_s=2.0，启动前积累足够音频；短回复不足2s则等done。
  初版0.4s“你好”在0.95s就绪，下一批2.24s才来，立即播放会有约0.9s空档，因此没有部署无缓冲版本。
- 帧头/长度/累计时长、队列、读写超时有界；取消后generation隔离，worker当前原生调用返回后合作取消，
  不宣称能立即强杀正在运行的ORT/RKNN线程。
- 状态接口和页面显示识别首字、ASR收尾、千帆、可播放首批、合成全部、播放提交及停录至播放提交。
  指标为软件阶段，首次写播放器管道不等于麦克风测得的扬声器首音。下一轮开始保留上一轮统计。

## 对照结果

同一板端worker，固定短句/长句，各3轮 whole/stream 交替，默认2s启动缓冲：

| 固定文本 | 原整段首批中位 | 流式可播放首批中位 | 提前 |
|---|---:|---:|---:|
| 你好，现在可以连续对话了。 | 2.588s | 2.265s | 0.323s，约12% |
| 你今天过得怎么样？如果有点累，我们就先休息一会儿。等你准备好了，再慢慢跟我说，我会认真听的。 | 6.726s | 2.300s | 4.426s，约66% |

这是TTS阶段首批改善，不是整个对话都提速66%。长句流式全部合成中位6.384s，算力没有减少同等比例，
收益来自后续生成与前段播放重叠。短句已接近单批，因此收益有限。
Melo本身的生成随机性导致不同调用波形/短句时长有小幅差异，不把跨调用波形声称逐字节一致。
相同latent/批次夹具已验证stream PCM拼接与旧输出相同；模型前端与参数保持。
[逐块时间](performance/voice-latency-20260918/latency-buffered.jsonl)中，长句后续块到达时最少仍有约1.24s可播放音频；
本次样本无生产空档，不代表所有噪声/高负载/超长文本的永久无欠载保证。

## 真机播放与边界

真实Core+LocalVoiceTransport+Melo worker+ALSA扬声器，用固定长句回答夹具；ASR输入/云回答由夹具代替，
NoMic.start明确禁止开启麦克风。首批2.374s、首次管道写入等待26.8ms、全部合成6.531s，
播放正常drain并回idle，总墙钟10.575s，audio_error=null，queue_overflows=0，stderr无欠载日志。
[原始结果](performance/voice-latency-20260918/latency-playback.json)。没有用声学回录测真实发声点，也没有代替用户主观听感验收。
第一次独立夹具遗漏ALSA_CONFIG_PATH报Unknown PCM；补与服务相同的asound-rv1126b.conf后通过，非生产配置故障。

release/asan两套各16组companion CTest通过，覆盖协议截断/错误、取消、2s预缓冲、单aplay/drain和PCM一致性。
全仓format-check仍被原有未修改C++文件阻塞；本轮无C++变化。没有变动人脸、Wi-Fi、执行器、自启动。

## 复现和回退

板端空闲时（不打开麦克风/播放/云端）：

```sh
python3 -B deploy/companion/profile-tts-stream.py --config config/companion/board-test.json --rounds 3
```

当前板端local_tts_streaming=true，prebuffer2s。关闭此开关并重启可退回整WAV链路；
原配置board-test-before-latency.json及/userdata/rtctrl-companion-before-latency.tar.gz保留。
