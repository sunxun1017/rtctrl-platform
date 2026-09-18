# 连续对话全双工（2026-09-18）

## 行为与边界

full_duplex默认false，需live/local streaming ASR + AEC。板端实验配置启用full_duplex及aec_enable_aes。
用户开启连续对话后，麦克风→AEC→声音门控→独立ASR listener持续运行，和云端文字回复/TTS/playback并行。
页面独立显示input_state、听到的新一句next_transcript、待回应数量。
识别完整一句后，若正在回答则进入最多3句的文本队列；当前生产线程完成且ALSA播放排空后才回应下一句。
输入与输出状态分离；回答时不会pause_capture或改变capture_epoch，不再需要等播完才说话。
这里的全双工指同时录放与识别，不会自动截断当前回答；automatic_barge_in仍false。
超过3句待回复明确报错并关闭会话，不悄悄覆盖用户的话。单句最长29秒，PCM队列32帧。
lease超时、静音、断连停止全部采集并清空排队；旧generation事件不可复活会话。
公开stop动作在全双工下映射mute，避免listener结束但UI假待机。

## 验证

release/asan各20个companion测试组通过；core7项及transport6项覆盖：
播放期间PCM仍送识别、partial不覆盖当前回复、producer_done和playback drain双条件、队列上限、静音/晚到消息围栏、
独立listener与回复worker、完成回调可立即再dispatch、安静不跑ASR、取消关闭native、29秒边界。

真实板测试使用scripts/audio-aec/duplex_probe.py，替换云端回复为固定公开PCM，不调用云端，用户授权后采集。
没有保存/上传麦克风PCM或识别全文，只输出聚合计数及固定测试短句匹配。

1. 纯AEC、安静10秒：4次partial、1个final且在播放中发生，误触发第2个本地测试reply。说明此前21dB消回声并不足以防自问自答。
2. AEC+AES、安静10秒：partial0、final0，仅初始固定reply；通过本次安静防误触发观察。
3. 用户未赶上的一轮无输出，不作双讲通过证据。
4. 后续10秒双讲：onset2、partial4、final0，窗口内未完成断句，不能算完整流程通过。
5. 用户确认配合的15秒双讲：onset2、partial9，其中6次在播放期间；首次partial在播放后2.332秒；
   固定12字句最佳距离0，final1、完整匹配1、reply_requests2。final发生于播放结束后，但播放期间已实时识别。
   errors为空，AEC后峰值1748，结束后实际关闭采集。第2个reply为本地桩，不把它冒称千帆端到端回答验收。

基于此次安静及双讲结果，板端改为AEC+AES。仍不能保证所有摆位/音量/远场环境无回声误识别或逐字无损；
此前AES跨轮表现有差异，不覆盖长期连续运行或多用户背景交谈。

## NPU并行负载（无麦克风、无播放）

scripts/audio-aec/duplex_load_probe.py：7.8948125秒固定公开WAV按60ms节奏送独立ASR，
同时既有Unix socket TTS生成固定公开短句，只计字节不保存PCM、不访问云端。
132个ASR帧；exchange p95=159.97ms、max=729.70ms（模型积累一窗口才解码，非每帧都耗时这么久）；
TTS首块2.935s、总2.957s、256098字节、2块；errors=[]。
单次最慢交换低于32帧约1.92秒队列容量，但不替代长期压力测试。

## 部署/回退

应用包部署，系统库/固件/模型不变。备份rtctrl-companion-before-duplex.tar.gz及board-test-before-duplex.json。
禁用full_duplex可恢复半双工连续模式；恢复旧配置也会恢复纯AEC。需要重启伴随服务。
完成交付保持麦克风关闭；用户开启麦克风和连续对话后再进行日常交流。
