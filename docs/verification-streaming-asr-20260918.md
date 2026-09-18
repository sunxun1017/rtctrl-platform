# RV1126B 流式 ASR 与连续对话验收

2026-09-18，正点原子 RV1126B，实物约970MiB RAM，Linux6.1.141，RKNN runtime2.3.2 / driver0.9.8。
保持已部署的三模型 Zipformer 和 Melo 音色；没有替换系统运行库、改麦增益、录制用户音频或联网调用云端。

## 选择与实现

现有 [Model Zoo Zipformer](https://github.com/airockchip/rknn_model_zoo/tree/main/examples/zipformer)
本来就是流式transducer，旧应用攒完整WAV才冷启动CLI。现在独立常驻native进程持有模型，
OnlineFbank、encoder缓存和decoder历史跨PCM块延续，每轮reset，partial不触发回答。
代码仍以已锁定Model Zoo revision bad6c7334531becaf90a561988519b7bec34d0ab为基础。

[Whisper](https://github.com/airockchip/rknn_model_zoo/tree/main/examples/whisper)虽列出RV1126B，
其20秒固定窗口/逐token解码不适合本次低延迟目标，没有在板上尝试新模型。
[sherpa预转换包](https://k2-fsa.github.io/sherpa/onnx/rknn/models.html)标注RK3588，不能直接用于RV1126B。
本轮证明接线与流式功能，不是新模型准确率排名。

PCM16/16k/mono每60ms通过有界32块队列送入native，绕过本地Opus往返。
每个native请求最多32000bytes、单轮30s、文字4096bytes；协议LE uint32 payload长度+uint8 opcode+payload，
1=PCM、2=finish、3=reset、4=quit。stdout每请求一行JSON，日志只走stderr。
输入等待/输出大小/超时均有界，子进程不继承云密钥。输入队列满直接失败，不悄悄丢字。
finish按真实最终帧数推进，覆盖pending97–102帧时需要两个96帧步长的边界。

有字且连续blank达到1.2s判停顿；实际评估受0.96s模型步长影响，通常约1–2s。
无字5s返回空轮，不发千帆；连续模式稍后开始下一轮。最长应用轮29s强制提交。
这属于停顿端点检测，不含语义标点恢复，不声称理解一句话的语法结束位置。

连续模式需用户显式点击，静音默认不采音。endpoint先通知Core停止采集/提升capture_epoch，
然后final才进文字回答；播放完全drain后延迟0.4s恢复下一轮。静音/中断/断连/失败撤销连续模式。
前端每4s续15s租约，页面隐藏/离开主动静音，控制台失联最迟租约到期静音；不自动重开。
仍为半双工，无AEC/唤醒词/说话自动打断。

## 板端证据

使用Model Zoo公开test.wav（5.6115s），按真实时间送60ms块，附加静音；
[原始结果](performance/streaming-asr-20260918/final-results.json)：

- 热页缓存模型初始化0.315s；初轮曾0.971s，不能当统一冷启动时间。
- 首次partial在1.178s出现；后续约每0.96s更新，完整识别内容与旧CLI一致。
- endpoint落在输入6.84s，finish完成墙钟7.060s，语句末尾正确；不是7秒推理耗时。
- 5s纯静音无文字；reset后重放最终文字完全一致。
- native单线程、RSS峰值17384KiB（约17MiB）；这不含完整NPU DMA/权重内存。
- ASR常驻后页面整机约681–697/970MiB、Melo worker267.3MiB；相近待机未加载ASR约550MiB。
  约130MiB差值含NPU等全局资源，不应宣称只增加17MiB。待机整机CPU约9%、NPU10%、人脸约30FPS。
  非长时间峰值、非有脸并发压力测试。

[应用整合结果](performance/streaming-asr-20260918/integration.json)：真实Core/LocalVoiceTransport/nativeASR/
实际Melo worker，注入公开PCM，Audio假设备不打开麦克风/扬声器；文字回答替换固定夹具，不调用云端。
首个partial约1.20s、采集状态自动停止、只调用一次回答，生成44100Hz/190976bytes音频，
恢复下一轮聆听后静音成功，queue_overflows=0。此证据不是本轮真人语音/云端/声学验收。

release、asan两套各15组companion CTest全部通过；新增12项Python流式生命周期和5项native协议/尾帧边界用例。
交叉构建rknn_zipformer_stream成功，新增C++格式检查通过；全仓format-check仍受原有未改dynamixel等文件阻塞。
浏览器确认“开始连续对话”入口与静音门控；未通过页面启动真实采音。

## 部署、复现与回退

当前board-test启用local_asr_streaming=true（必须live/local/rknn且配置模型根路径）；全局默认false。
程序位于local_speech_root/npu-asr/rknn_zipformer_stream，复用model/{encoder,decoder,joiner}.rknn和vocab.txt。
未增加模型下载。native SHA256: `0797ac3efb4b5d61f530f6f600fb14e21c94a438d2fe82858e44ebffed404f24`。

```sh
cmake --build work/npu-speech/runner/repro-build --target rknn_zipformer_stream -j2
# 将目标程序复制到板卡npu-asr目录；不要复制/替换系统librknnrt。
python3 -B deploy/companion/probe-streaming-asr.py --root /userdata/rtctrl-speech --input /path/to/public.wav
```

probe只读显式WAV，不开启声卡或上传音频，独立常驻ASR之外再运行probe会额外占用一份NPU模型资源。
本轮正式bundle位于/userdata/rtctrl-companion-20260918，旧应用在/userdata/rtctrl-companion-pre-streaming.tar.gz，
旧测试配置board-test-before-streaming.json。只关闭local_asr_streaming并重启即可回原PTT整句ASR，旧CLI仍保留。
未改自启动、Wi-Fi、人脸库、执行器、Melo模型或音色。后续需用户对板载麦克风的断句/噪声场景做主观验收。
