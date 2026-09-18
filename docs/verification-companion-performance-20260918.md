# RV1126B 语音性能与资源优化（2026-09-18）

## 条件与方法

ALIENTEK RV1126B，实际1GB（MemTotal 992844KiB），aarch64 Linux6.1.141/Buildroot、Python3.11、系统NumPy1.25、sherpa-onnx1.13.8。
Zipformer CTC small中文INT8 + AISHELL3 VITS sid0，模型不变，人脸服务始终运行。
公开5.61秒16kHz WAV与固定合成句，未主动录制用户麦克风、未调用云端、未播放测试音。
每组第0轮单列预热，热结果取后续中位数。通过worker Unix socket测识别/合成，包括文件IPC，不包括云端与播放时间。

工具：板载perf stat、perf record（cycles/49Hz）、/proc/PID/stat/status；最终脚本用SO_PEERCRED验证模型PID，输出不含识别内容。
原始证据在[companion-20260918](performance/companion-20260918/)。
`rtctrl-bench-before/profile`为旧版已常驻进程；`after2/after1`为优化后双/单线程4轮；
`final`为发现忙状态竞态而中断的试验，不能算通过；`verified`为修复后完整10轮。
旧版进程有此前历史请求，内存对比不是严格相同冷启动实验，因此不宣称固定节省百分比。

## perf发现

- 旧版cycles采样：MlasSgemmKernelAdd24.89%、MlasSgemmKernelZero22.37%，合计47.26%。
- ONNX ThreadPool WorkerLoop10.22%，S8S8 Neon6.63%，SGEMM packing5.90%，ConvIm2Col4.93%。
- 旧版4轮perf：42.406CPU秒 / 22.164墙钟秒，约1.91核；不是网络或磁盘为主的瓶颈。
- 空闲3秒只消耗1.59ms task-clock，没有证据支持改轮询周期或高频强制释放模型。

## 变更与验证

1. PCM识别输入及合成输出改NumPy批处理，减少Python float对象和逐样本循环；保持小端、截断、饱和规则，拒绝NaN/Inf。
2. worker专属MALLOC_ARENA_MAX=2，限制glibc arena数量；不改全局分配器、不改人脸或声卡线程。不是RSS硬上限。
3. 推理线程配置严格1或2，默认2；实测单线程变慢，最终恢复双线程。
4. 修复worker先发送成功再释放busy的竞态。快速ASR→TTS请求原先偶发busy；现在先释放再确认，增加确定性回归测试。
5. 页面显示语音进程CPU、线程数、实时/峰值RSS；CPU以单核100%计。监控检测PID/starttime变化及退出，避免陈旧值。
6. 增加有界profile-speech.py、测试依赖说明，便于后续换模型重复测量。没有强制杀模型、添加swap、调整频率、改变NPU人脸服务或安装开机项。

| 组别 | 热ASR中位秒 | 热TTS中位秒 | 观察到的RSS |
|---|---:|---:|---:|
| 旧版双线程，4轮 | 1.879 | 3.513 | 末轮399.3MiB |
| 初次优化双线程，4轮 | 1.845 | 3.509 | 末轮363.2MiB |
| 优化单线程，4轮 | 2.843 | 5.684 | 末轮385.7MiB |
| 最终双线程，10轮 | 1.848 | 3.300 | 末轮/峰值387.9MiB |

最终20次请求全部成功：热ASR范围1.8285–1.8689秒；TTS范围3.1726–3.6093秒，RTF中位0.6492。
VITS输出时长有随机波动；本次不把同一句话的一次墙钟差异当确定的模型加速比例。
最终perf104.823CPU秒/52.786墙钟秒，约1.99核。最后两轮RSS约397052–397204KiB；
短测没有失控增长，但不足以证明长时间无泄漏。页面推理时约199%CPU、空闲0%，人脸29.8–30.2FPS附近。

另测纯转换内核（7次中位）：15秒PCM→float，旧147.858ms、新3.134ms；10秒float32→PCM，旧1979.375ms、新3.453ms。
这是构造数组的局部微基准，不是完整模型或整轮对话提速倍数。数值测试穷举PCM16范围，并对10006个浮点样本比较旧/新输出。

## 交付与限制

板端应用包SHA256：0a5c5c2b1c2d944321680d99e3a10b2209f6c01d38bd4933cce6eaf4f976d6b0；35个manifest文件验证通过。
随后仅文档/测试补充，无板端运行逻辑变化。保留现场board-test配置、旧模型及私有环境文件。
页面已恢复本地语音就绪。用户随后主动试说，页面出现识别文字和本地合成状态；本记录不保存会话内容。

release/asan完整CTest各22/22通过；最后busy修复后两套companion各9/9通过，另新增配置用例单独39/39通过。
合计当前150项companion用例有执行证据。SocketCAN没有vcan仍按原约定跳过，不属于本次语音验证。
format-check仍被既有未改动C++格式问题阻塞；本次没有改C++或全仓格式化。git diff --check通过。

对话首音频仍受云端响应和完整句合成影响；这次优化未改变云协议、音色或音质。
模型RSS会随输入长度增长，后续需要最长15秒录音、120字回复及数小时温升/内存稳定性测试。
本次采用真实perf证据保留双线程，未为了较低CPU数字牺牲约一半交互速度。
