# 中文TTS连贯性调查（2026-09-18）

用户明确反馈CPU/NPU两版AISHELL3 sid0都像逐字朗读。此前整句数值对齐不代表自然度验收通过。
本轮试听AISHELL3 sid0 speed1.15/noise_scale_w0.35以及Kokoro INT8 sid3后，用户明确表示“两份仍然不自然”。
两者未获认可。用户随后认可Melo完整对话的连贯性，授权继续适配板卡；当前板端已切换Melo混合NPU合成。

## 排查结果

实际前端是一句一次回调，不是逐字合成/音频拼接。#0为上游每音节标准输入，时长对齐区段含有声波形，不能删除或当空白裁剪。
当前metadata没有punctuations，逗号在输入中被忽略；原上游中文前端在逗号分句处加入sil，两者确有差异。
实际tokens仍把“一起”记作i1/qi3、“很好”记作hen3/hao3，未体现相邻音节的上下文变调。
这些证据支持前端/模型韵律存在局限，不证明一个独立参数就是全部根因。
证据与上游链接见performance/tts-naturalness-20260918/aishell3-audit.md。

## 已拒绝候选

此前AISHELL3原始decoder同句5.888s；调整时长噪声0.35、speed1.15后5.248s。这两份试听漏用了应用ScaleSilence后处理，不能代表完整应用输出。快一些不等于连贯，用户未认可。
Kokoro INT8 v1.1-zh sid3(zf_001)，同句3.872375s/24kHz；主机生成3.833s、peakRSS324064KiB。
历史板端另一短句2.93s音频需约38.55s，不能将本轮主机速度当板端速度。用户未认可本轮音色/连贯性。
Kokoro初始化记录Unknown token ❓，测试正文不含该字符；没有据此声称所有标点/词典输入均已覆盖。

## 候选比较边界

先生成整句供主观试听，认可后再验证板端资源。未把候选当生产默认、未在本轮采麦克风或发送文本给新的云服务。
Melo官方sherpa导出脚本将bert/ja_bert输入固定为0，导出版的效果不能直接等同完整原生Melo前端/模型。
来源：https://github.com/k2-fsa/sherpa-onnx/blob/master/scripts/melo-tts/export-onnx.py。
复现试听入口：scripts/speech-npu/tts-audition.py；主机试听与板端实测必须区分，板端结果见下。


## Melo板端适配与部署

用户接受的是sherpa-onnx 1.13.8的Melo FP32完整对话，sid0（模型内部speaker row1）、speed1、44.1kHz。
模型来自csukuangfj/vits-melo-tts-zh_en，HF revision a0d5c6a264c0ef92d70d8661d8cc502d79627cd6，模型/包标注MIT。
模型SHA256 `bf30582eb1b012250a35b1a4a80e7dfbcf8485e7bb9de0d95efbbeef0e4ad86d`。

- CPU前缀保留原sherpa中文前端、jieba词典、date/number/phone FST与随机时长生成。
- NPU仅执行Melo decoder，固定speaker row1、非量化FP16、RKNN Toolkit/Runtime 2.3.2、driver0.9.8。
- prefix输出flatten latent，每批关闭静音处理；NPU固定256帧，224帧核心+两侧16帧上下文，末端多尺度mask。
- 图推导所需halo13，实际取16。随机257/600/1000帧及946帧真实latent拼接，FP32最大误差<7.1e-7。
- 每个完整sherpa批次重建后才执行ScaleSilence(.2)，168组输入与上游C++逐样本一致，不能逐NPU块压缩静音。
- 保留44.1kHz PCM，不转换成8kHz、不经Opus。

### 纠正先前试听的边界

此前AISHELL3 CPU/NPU整句原始decoder试听和调参试听未应用ScaleSilence(.2)。其数值对齐依然有效，
但不能代表完整应用的停顿长度。已向用户说明。被认可的Melo试听通过实际sherpa生成，包含此后处理，
本次适配以该链路为准。模型自然度与算子数值精度是两个不同验收项。

### 正点原子1GB板实测

人脸服务同时运行，NPU800MHz、CPU线程2。以下为固定文字单轮，不含云回答与播放时间，不代表长期分位延迟。

| 链路 | 输出时长 | 生成时间 | 进程峰值RSS |
|---|---:|---:|---:|
| Melo全CPU短句 | 2.901s | 26.486s | 347.8MiB |
| Melo混合NPU短句 | 2.901s | 3.407s | 267.4MiB |
| Melo混合NPU完整对话 | 7.895s | 9.277s | 272.8MiB |

混合初始化约21.3s；热驻留后不逐句重载。NPU256帧decoder含IO约634–635ms（3轮），模型初始化92ms。
RSS不含全部驱动/DMA内存。清理临时模型副本后现场整机可用内存约444MiB，应用语音RSS约271MiB，
人脸约30FPS。/userdata为936MiB分区，剩约113MiB；完整CPU Melo模型留在主机，板端只留前缀和decoder，
原AISHELL3回退模型仍保留。

真实板端8段latent与同输入FP32参考比较：SNR47.76–51.27dB、最大绝对误差<=0.000676，
全部原始及静音处理后长度一致。FP16不保证逐样本相同；最终板载扬声器听感还需用户确认。

### 集成与恢复

配置新增local_tts_kind=melo_npu（Melo仅sid0），health报告tts_backend=rknn、tts_kind=melo_npu。
板端应用已部署；原配置备份board-test-before-melo.json，原应用归档rtctrl-companion-pre-melo-20260918.tar.gz。
回退时停服务、将local_tts_kind改回备份值vits/vits_aishell3后启动，旧模型保留，无需刷机或替换RKNN运行库。
代码默认仍是原模型，便于未装Melo资源的设备运行。melo纯CPU选项需要完整model.onnx，板端当前不安装该文件。

验收：release/asan各10组companion测试通过；新增6组分块/后处理/失败/时长测试；C ABI交叉编译通过；
板端正式worker健康检查与固定文字WAV输出成功（44100Hz、128025帧）；页面显示Melo NPU波形生成。
未连接新Wi-Fi、未安装自启动、未采集额外测试录音。原有千帆文字回答链路不变。

复现脚本：scripts/speech-npu/convert-melo.py、validate-melo-chunks.py、melo_decoder.cc。
数值和性能数据见performance/tts-naturalness-20260918/melo-*.json。
