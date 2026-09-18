# RV1126B Melo perf / ftrace优化（2026-09-18）

在用户已认可的Melo音色上降低板端合成延迟。最终仍使用原模型权重、sid0、44.1kHz PCM与完整批次静音处理。
ASR、人脸模型、云端协议未改。用户授权本地优化与部署，未采集麦克风、未上传音频、未连接新Wi-Fi。

## 测量条件与边界

正点原子RV1126B，实际1GB，aarch64 Linux6.1.141，板载perf6.1.118，RKNN Runtime2.3.2/driver0.9.8，sherpa1.13.8。
人脸服务保持运行，CPU2线程基线；不改CPU亲和性、调频器、实时优先级、全局分配器或系统RKNN库。
固定两段公开文字，每组先预热，常规3轮取中位；单线程2轮；最终正式代码另复验1轮。
以下时延只计合成，不含模型首次加载、ASR、云回答、播放。随机时长噪声保留，短句长度略有波动。
原始本地实验目录work/melo-perf/board；提交的紧凑证据在performance/melo-perf-20260918。

## perf与ftrace结论

基线49Hz cycles采样无丢失：MlasSgemmKernelAdd51.44%、MlasSgemmKernelZero14.73%、
ThreadPool WorkerLoop10.04%、SGEMM packing7.08%。CPU主要在Melo前缀的矩阵运算，后处理只有约0.02/0.04秒。
离线prefix审计全部10430节点都被输出引用；ORT已优化为3623节点，没有可直接删除的遗留decoder分支。
固定batch1没有稳定收益，不部署此候选。

基线ftrace独立instance记录3537个调度事件，无丢失；主线程与ORT线程的runnable等待合计0.212秒。
未发现调度争抢占主导，因此没有盲目绑核或提高实时优先级。最终流水线2048KiB/core记录40499事件，无丢失，
两条被观测线程runnable累计约0.846秒。ftrace只追踪启动时TID，不含随后创建的decoder线程，不能视为全进程等待占比。
中途nospin/192的512KiB/core trace发生覆盖，明确标记lost_events=true，不使用其调度时长作结论。
所有instance结束后删除；global current_tracer=nop和tracing_on=1保持原值，没有改全局trace配置。

早期实验把perf附加到自身，板载perf写出数据后仍等待目标退出，收尾超时被终止，因此perf总墙钟含约10秒清理等待。
应用内wall/cpu计时不含这段；不将perf窗口总墙钟当合成延迟。perf report在目标退出后再读取，使用已保存无丢样本数据。
复用工具改为父控制器监测独立模型子进程，子进程结束后perf自然收尾；异常仍有明确超时和清理记录。

## 实测对照

| 方案 | 短句wall秒 | 长句wall秒 | 短句CPU秒 | 长句CPU秒 |
|---|---:|---:|---:|---:|
| 基线256块、串行、双线程 | 3.3521 | 9.1289 | 4.4026 | 11.3835 |
| 仅禁用ORT空转 | 3.3873 | 9.2490 | 3.9548 | 10.1336 |
| 192块、禁空转、串行 | 3.0854 | 8.3074 | 3.9594 | 10.0906 |
| 192块、禁空转、单线程 | 4.5763 | 12.1343 | 3.6313 | 9.2936 |
| 192块、禁空转、CPU/NPU流水线 | 2.8048 | 6.5730 | 4.2819 | 11.3009 |

最终三轮中位相比基线：短句wall降低16.3%，长句降低28.0%。长句7.895秒音频的RTF约0.833。
最终正式集成代码单轮复验为2.744/6.394秒，单列而不替代三轮中位。
流水线总CPU秒与基线接近，瞬时CPU百分比可能更高；主要收益是完成更快，不能声称CPU功耗下降28%。
只禁空转可省约10%CPU秒但略增时延；最终保留双线程，单线程明显变慢。

## 实现与音频对齐

1. decoder从固定256帧改为可选192/256帧。板端decoder.json明确选择192；保留256文件便于回退。
   NPU decoder每块含IO约0.638秒降为0.482秒。编译内部内存35012.5KB降至26259.4KB，减少25%，
   权重28243.8KB不变。这是编译工作区数据，不等于整机或RSS减少25%。
2. 短于一个bucket的latent只调用一次NPU。长句使用16帧halo，192对应核心160帧；最终拼接严格保留原样本数。
3. packaged melo-cpu.conf关闭ORT intra/inter空转，只影响此Melo前缀Session。
4. 单decoder线程和容量1队列，让CPU准备下一批时NPU解码上一批。callback先复制Sherpa借用buffer，保持输出顺序。
   单context始终串行；完整批次后才ScaleSilence。失败停止producer，返回前join，不留仍使用context的线程。
   最坏同时持有consumer/queue/待入队三份latent约9.2MB，输出仍限制45秒，单批不超过4000帧。

FP32候选192与精确decoder：随机100/150、8真实latent与946帧跨块输入，最大误差3.61e-7。
真实板端192与原256：同样8段及946帧长输入，原始/后处理长度一致、逐样本差值为0。
流水线再用8段固定latent、复用后覆盖producer缓冲进行验证：476084个44.1kHz样本与串行完全相同。
这些测试证明改动未改变已测输入的波形，不替代广泛语料和长时间稳定性验收。

峰值RSS：基线269.1MiB，流水线270.9MiB，基本持平；不含全部NPU DMA内存。
首次加载约21秒仍未改善。人脸服务仍约30FPS；没有宣称所有120字回复都满足固定响应上限。

## 验证与复现

release/asan各12组companion通过；随后新增的控制器组及ftrace组在两套构建中通过（当前13组均有通过证据）。新增192边界、流水线顺序/复制/满队列错误退出、ftrace隔离/丢事件/清理测试。
C ABI重新交叉编译、格式化限定本次文件、git diff --check通过。

停止交互语音服务后执行：

```sh
python3 deploy/companion/profile-melo.py --root /userdata/rtctrl-speech \
  --output /tmp/melo-profile-new --rounds 3 --perf --ftrace
perf report --stdio -i /tmp/melo-profile-new/perf.data
```

脚本拒绝在已有speech_worker时加载第二套模型；不录音、不调用云、不播放。
回退192选择：把decoder.json改为{"model":"decoder-masked-256.rknn"}并重启语音服务。
完整回退：旧melo_npu Python和旧libmelo_decoder备份仍在板，或部署57b0176对应包并恢复原256选择。
新Python需配套含melo_decoder_frames符号的库，不可只替换其中一项。


最终常驻worker socket实测：重启后首句3.520秒，随后三次2.957/2.955/2.961秒，输出44.1kHz。
与隔离模型热基准的2.805秒口径不同，包含CLI/Unix socket/WAV写入与服务并存开销；未把隔离模型数当整轮对话响应。
新版perf父子收尾机制另在板端3秒固定CPU子进程上验证：child=0，perf stat/record均exit0，warnings为空。
控制器改造后未再次停止线上服务重跑整套Melo perf；模型性能数据来自上面的已测流程，工具收尾另行验证。
