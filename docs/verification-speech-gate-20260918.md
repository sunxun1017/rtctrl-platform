# 连续对话静音门控（2026-09-18）

## 原因与修改

原逻辑将所有静音PCM送入RKNN Zipformer，空文字约5秒endpoint后进入thinking/finalize、asr_empty，再0.4秒重开。
因此用户未说话时界面周期进入本地识别，并持续消耗识别推理资源。

新增轻量PCM能量起音门控：去直流RMS，最低24/32768，自适应低电平噪声阈值3倍，最近4帧至少3帧越阈值才触发。
等待阶段不reset/feed/finalize识别器；仅保留最近8帧（正常60ms一帧，即480ms、15360字节）并检测能量。
起音后reset一次、先送缓存再送实时PCM，沿用原来的模型断句。按住说话路径保持即时识别。
假触发后空endpoint直接返回等待，不进入thinking、不调用云端，不关闭/重开麦克风。
等待阶段取消29秒录音截止，检测到起音后才启动最长29秒截止；采集无进展5秒仍失败关闭。
15秒浏览器lease、关闭麦克风和断开保护保持有效。UI等待阶段显示“等待说话”。

门控是声音能量检测，不是语义VAD或唤醒词。持续较大噪声可能触发；不宣称所有噪声环境零推理。
ASR模型保留内存避免重载，仅减少静音期间推理，不宣称降低常驻模型内存或整机NPU归零（视觉仍在运行）。
AEC和麦克风仍在用户开启连续模式时工作；关闭麦克风仍停止实际采集。

## 验证

- host transport：连续60秒零PCM，recognizer exchange调用为0，云端调用为0。
- false onset：空endpoint后只发asr_waiting，无finalize/asr_endpoint/云端调用。
- gate：静音、直流、单帧点击、低电平噪声不触发；起音保留480ms缓存。
- core：等待阶段无识别截止；started只arm一次；lease到期/mute停止采集。
- RV1126B离线门控：60秒零PCM触发0，CPU32.59ms；60秒±10低电平信号触发0，CPU33.58ms。
- 固定Melo语音（非真人录音）原幅度/0.1/0.05分别在0.24/0.24/0.30秒触发，随缓存送入识别。
以上板端门控CPU不包含采集/AEC，不是整机CPU节省百分比。
- release/asan companion各18组通过。真实环境安静麦克风的触发率需另行授权采集验证，不能由零PCM测试替代。

## 部署与回退

部署companion应用，无系统库/固件/模型修改。备份rtctrl-companion-before-speech-gate.tar.gz。
只回退应用apps及manifest后重启companion即可；不覆盖当前service.env和设备设置。
