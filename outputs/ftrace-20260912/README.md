# ftrace、NEON、RKNN模型副本，2026-09-12

基线：上一轮CPU50部署，native FP16/rga-direct/MPP/async，960×712，模型与人员库不变。板端SDK2.3.2、driver0.9.8，NPU800MHz。源码提交与最终二进制见后续提交记录和deployed-manifest.json。

- baseline-trace.txt.gz：20秒function+sched_switch，28259/28259记录，4核无丢失；初次没有逐秒脸数，不能用于同负载NPU比较。schedule→IRQ配对仅为驱动代理，不等于硬件MAC活动时间。
- final-trace.txt.gz：补sched_wakeup，20个状态全单脸，主线程唤醒P95约16us/max123us；3000无重叠配对总4.845s，与24%忙时量级一致。
- ab：四段20秒，状态样本全无脸，旧标量CPU29.365/29.274%，NEON27.863/27.973%，都约30FPS。跨轮单脸CPU不得直接相减。
- resize-neon.txt：108完整letterbox像素相同，标量CPU约2.58ms→NEON2.18ms；保留固定点舍入和ROI边界。
- detector/recognizer-memory.txt：普通flags0初始化查询，SRAM均0。模型内部内存不是应用模型文件副本。
- model-output-check.json：释放文件副本前后，两模型各20次固定合成输入，完整Float32输出有限且字节一致；初始化后持有32MiB+模型文件大小的填充，不保证复用相同地址。
- memory-ab：NEON保留副本PSS48446/47612KiB，释放版39236/39852KiB。人脸样本变化2/1/2/14，不能算CPU收益。
- final-monitor：独立60秒，61/61单脸，CPU37.556%最大39.000%，PSS42054-42074KiB，30.038FPS，NPU24%，缺口覆盖均0。短测不等于长期峰值。

普通rknn_init flags0可在成功后释放model副本，匹配SDK main_video.cc示例；不适用于MODEL_BUFFER_ZERO_COPY等特殊加载模式。没有改模型、调频或关闭缓存同步。降低NPU算术负载仍需模型量化/精度实验，本轮未宣称该收益。

复现脚本具有本次固定板端路径，先核对设备与PID。ftrace_npu_capture.py创建独立instance并清理；ftrace_next_ab.py和ftrace_memory_ab.py会停启视频并恢复optimized入口。分析脚本从work/ftrace-NAME.txt及work/ftrace-NAME-meta.json读取，NAME为baseline或final。把本目录gzip解压到相应work文件、复制metadata后运行 `python3 outputs/ftrace-20260912/ftrace_analyze.py final`。先检查per_cpu丢失与配对重叠。

验证：face host/ASan各30，release/ASan各13；实际ARM像素校验和两模型固定输出比对通过。全仓既有格式失败未改，本轮源文件格式通过。
