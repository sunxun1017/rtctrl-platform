# RV1126B 语音 NPU 实测（2026-09-18）

## 范围与最终部署

正点原子实物 1GB，MemTotal约970MiB；不是规划中的2GB。Toolkit2和板端Runtime均2.3.2，驱动0.9.8。
现有RKNN库未替换，人脸模型/图库未改，Wi-Fi未连接。自动测试使用公开音频，不主动采集麦克风。
现场配置local_asr_backend=rknn，ASR使用独立Zipformer进程；TTS继续AISHELL3 sid0 CPU和原生PCM播放。
代码默认cpu，修改配置并重启可回退；CPU模型保留。未推送远端。

## 原模型转换与替代路线

原CTC INT8在固定输入[1,600,80]/[1]下load成功，build实际报错：
DynamicQuantizeLinear('/encoder_embed/Reshape_output_0_QuantizeLinear') will cause the graph to be a dynamic graph。
它不是RKNN可直接接收的INT8格式。
改用瑞芯微Model Zoo明确列出RV1126B支持的Zipformer中英模型，encoder/decoder/joiner
均target_platform=rv1126b、do_quantization=False转换成功。输入特征与greedy解码仍CPU。
模型并非原CTC的等价加速，短样本正确不等于完整中文准确率通过。
来源与哈希见 [manifest](performance/npu-speech-20260918/asr-models.json)。
工具见 [scripts](../scripts/speech-npu/README.md)。

## ASR板测

官方test.wav与现用模型公开0.wav本轮输出同一预期句子：
“对我做了介绍那么我想说的是大家如果对我的研究感兴趣呢”。原音频5.6115秒。
重启前推理875.816ms；重启恢复人脸后，三轮独立进程：

| 轮次 | 含加载wall秒 | 推理链路毫秒 |
|---|---:|---:|
| 0 | 1.3267 | 876.492 |
| 1 | 1.3084 | 869.891 |
| 2 | 1.3072 | 864.729 |

三轮exit0且文本正确。maxrss 17652KiB仅进程RSS，不含NPU DMA。
官方日志RTF用补零后的5.841秒，不能直接与原5.6115秒比较。
以本轮CLI中位1.3084秒比历史CPU热中位1.848秒约缩短29%，不同架构模型且不是同轮严格A/B。
应用实际Unix socket接口另测ASR成功1.589秒，不能把CLI时间宣称整个应用延迟。
紧接TTS成功4.313秒，生成107508字节WAV；只验证生成不播放。
health返回asr_backend=rknn、tts_backend=cpu、ready=true、busy=false。
短测后worker RSS172.38MiB、整机使用358–365MiB；历史CPU多轮worker387.9MiB不能作为同条件节省比例。
人脸约29.7–30.1FPS，短测画面无脸；未完成多人/长期并发验收。

## TTS局部分拆实验

VITS全图含随机采样及动态长度，未部署整图NPU。抽取decoder114节点，保留speaker embedding。
同一latent在原图/抽取ONNX对比9984样本最大/平均绝对误差均0。
L16输入[1,96,16]+[1,256,1] -> [1,1,4096]，8kHz为0.512秒波形。
非量化RKNN约4.6MiB，板端warm一次后5轮io+run毫秒5.744/8.473/5.771/5.264/5.175。
对相同输入ONNX参考：输出全有限；最大绝对误差0.000206996，RMSE0.0000570032，
SNR34.6799dB，相关系数0.999842。模型与参考信息见performance/npu-speech-20260918。
这是合成token数学夹具，不是自然语句试听。整句分桶/分块边界、接缝与端到端收益未验证，
因此保留原CPU TTS，不宣称完成TTS迁移或音质完全相同。

## 重启恢复与回归

用户重启使服务停止、系统时间退回2021年，PGA归零、扬声器关闭。
恢复时间、人脸/语音服务与8092/18080临时SSH隧道，恢复音量85%、PGA36dB和扬声器开启。
右ADC capture别名仍存在；未录制新音频，近距麦克风信号偏弱根因仍未解决。
未安装开机启动、未保存永久混音器配置。当前云回答仍依赖主机代理与隧道。
release/asan各9组companion CTest通过；新增worker测试覆盖成功、超时、错误退出、无结果、超量输出和仅加载TTS。
两个C++ runner用SDK交叉编译通过；只格式化新增C++，原仓库无关format-check故障不纳入本次修复。
页面已显示ASR NPU/CPU前后处理、TTS CPU，并明确主进程统计不含临时识别进程。

## 后续验收

扩大真实中文/噪声测试集；核验长期NPU争用、进程重启与取消回收；优化模型常驻以消除每轮加载。
TTS下一步需完整句固定latent对照与分块边界方案，通过试听后才能切换。
麦克风硬件电平和掉电启动/时钟/联网持久化是另外的未完成项。


页面实际交互观察：用户试说后显示“你好能听到我说话吗”，峰值2637/32768（-21.9dBFS）。
该单次观察不替代此前弱信号问题的系统验收。随后千帆失败，定位到主机CONNECT代理未运行；
重新以持久PTY启动后，板端经隧道TLS请求得到预期未鉴权401，网络/TLS恢复。
随后通过既有LocalVoiceTransport发送固定文字测试（不含用户录音），千帆鉴权成功并在1.57秒返回5字符回答。
