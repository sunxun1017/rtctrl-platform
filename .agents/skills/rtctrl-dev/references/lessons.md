# 已验证项目经验

## 2026-09-10：新增源码不代表构建已覆盖

- 适用条件：在研模块或适配器刚加入目录树，尚未完成产品装配。
- 证据（2026-09-11 更新）：RKNN 已通过 `RTCTRL_ENABLE_RKNN` 接入，`cmake --build --preset robot-vision --target rtctrl_inference_rknn` 成功；独立 SDK 替身测试及其 ASan/UBSan 通过。通用 `modules/inference` 已实现张量描述、大小计算和 Backend 接口，RKNN 通过该接口适配；release/asan 各 12 项、robot-vision 18 项测试通过，包括安装消费和 include-boundaries。
- 结论：对 RKNN 的验证必须先证明 backend 进入实际 target/编译命令；现有 release 或 robot-vision 测试通过不能单独证明它已编译。
- 失效条件：通用模块与真实 SDK/板端验证完成后更新状态；静态库和替身测试不代表已链接 runtime 或完成 NPU 实测。

新增经验沿用日期、适用条件、证据、结论、失效条件。仅保留会改变后续开发决策的信息。

## 2026-09-11：RKNN 普通输入与 native 内存是两种契约

- 适用条件：为 RKNN 实现图像预处理或 DMA-BUF 接入。
- 证据：本地 Toolkit2 User Guide 英文版第 135、158–159 页说明普通 API 输入执行配置的 mean/std；第 69–72 页要求 native 内存匹配 stride/type，RKNNRT API 英文版第 38 页描述缓存同步。
- 结论：普通 `pass_through=0` 的 raw RGB Float32 不能再手工重复模型转换配置中的归一化。native IO 按 `size_with_stride` 分配并保留完整 SDK 属性，不能直接复用稠密 Float32 描述。拥有 DMA fd 或通过宿主替身测试不证明端到端零拷贝。
- 失效条件：SDK 版本、模型预处理或 IO 路径变化时重新核对。代码说明见 `adapters/inference/rknn/readme.md`。


## 2026-09-12：视频识别与 fortified poll 测试

- 适用条件：视频识别复用 V4L2 采集、或 ASan 构建中使用系统调用 mock。
- 证据：face-video 与 face-video ASan/UBSan 各 24 项通过；RV1126B 实机连续识别与浏览器 MJPEG 预览、停止重启已验证，见 `apps/face_recognition/VIDEO.md`。
- 结论：帧归还前完成自有 BGR 转换，异步推理只保留最新待处理帧；NV12 的 full/limited 和 BT.601/709 应依据元数据或显式配置，不能默认 OpenCV 限幅转换。空人员库输出 unknown；等待单人登记时检测上限至少为 2。
- 测试结论：glibc fortified 构建可能调用 `__poll_chk` 而非 `poll`，mock 须同时包装这两个符号，否则伪造 fd 进入真实 poll 导致错误失败；不要以关闭 sanitizer 处理。
- 失效条件：采集 API、glibc/toolchain、颜色元数据或 BSP 变化时重验。

## 2026-09-12：RV1126B 独立硬件视频预览

- 适用条件：仅采集、缩放、编码、浏览器预览的独立应用。
- 证据：`apps/video_preview/README.md` 的板端对比；`gst-inspect-1.0 mppjpegenc` 支持 width/height/max-pending，debug 确认 `using RGA converted buffer`。
- 结论：该 BSP 可使用 V4L2 DMA-BUF、编码器内置 RGA 缩放、MPP JPEG；不需要把原始 NV12 转成 CPU BGR 再编码。不能把硬件缩放或编码包零拷贝属性描述为整个 HTTP 链路零拷贝。
- 实现注意：厂商库可能向 stdout 写诊断，二进制视频使用独立 FD；板端可缺少 `/proc/PID/task/PID/children`，性能工具用 `/proc/PID/stat` 的父进程字段定位子进程。
- 失效条件：BSP、插件构建选项、采集格式或尺寸变化时重验；独立预览的结果不代表其他处理应用性能。

## 2026-09-12：MPP 池复用与输入零拷贝要分别验证

适用条件：RV1126B 独立 GStreamer 摄像头预览，当前 SDK rockchipmpp 插件。
证据：`outputs/MPP缓冲复用实测.md`、`outputs/mpp-reuse/` 中的 OFF/ON 计数、重复测量和输入探测日志。
allocator 的 cacheable 控制内部 MPP 池保留，不改变 CPU cache 属性。预热后 heap 分配归零，
仍不能证明无映射、无复制；这次两块 GstMemory 输入实际走 RGA 虚拟地址路径。
手工构建需保留 SDK 的 `-fvisibility=hidden`，否则同名 `mpp_enc_debug` 符号可冲突。
换 SDK、输入布局或构建方式后重新验证；不要据此跳过 DMA 同步或默认启用实验插件。

## 2026-09-12：推理优化按同输入、同二进制分层对照

适用条件：RV1126B 的 RetinaFace/MobileFaceNet 视频应用，当前配套 OpenCV 与 RKNN runtime。
证据：`outputs/npu-20260912/` 的 API 配对、perf Self、颜色转换和 JPEG 编码日志。
`inputs_set` 墙钟包含 SDK 内部路径，不能全部归为 NPU 核心执行或某一种类型转换。
显式 UInt8 需匹配实际像素值域、布局与字节缓冲，并保留普通 Float32 默认契约。
这次查表在 x86 一致、ARM 因 FMA 舍入差 1；保留舍入后又比原式慢约 2%，因此未采用。
固定输入下板上 TurboJPEG 编码比配套 OpenCV JPEG 更快，压缩输出仍复制成独立对象供 HTTP 持有。
后续复用的是 perf 定位、正确性检查与单变量对照的方法，不应强行沿用某个“零拷贝”或查表方案。
换工具链、模型、编码库、颜色元数据或输入布局后重验；短对照与提前停止的采样不能当长时间稳定性结果。


## 2026-09-12：三十帧人脸视频的瓶颈迁移

- `outputs/fps30-20260912/`：先拆分V4L2序号缺口、待识别覆盖、待编码覆盖；`dropped`原本仅代表latest槽覆盖，不能当驱动丢帧。发布FPS不等于浏览器绘制FPS。
- CPU颜色转换43ms经RGA staging约9ms后CPU下降但FPS仍受下游限制；native输入按验证模型mean/std填FP16并同步，JPEG异步后单脸达到30FPS。复用的是定位/对照/回退方法，不把旧GStreamer插件直接搬入不同管线。
- 原生FP16的恒等AFFINE属性仍需明确归一化；只按shape或直接写raw FP16会错。输出逐值对照和模型指纹约束先于启用，换模型/SDK后重新验证。
- 新perf显示submit热点后，外提类型/布局分支，所有类型布局及ROI逐值一致，再用无人脸A/B确认CPU下降。不要把微基准几十倍当整链提速，也不要把不同人脸数的CPU/Self直接相减。
- 单分钟稳定和短A/B只能覆盖当时负载；被用户停止的长期采样不能写成完成。


## 2026-09-12：30 FPS 下继续降低人脸视频 CPU

- 适用：已验证RV1126B、OpenCV3.4.5、960宽预览、native两模型；证据 `outputs/cpu50-20260912/README.md`。
- 精确缩放特例、单内存camera DMA直接导入、MPP JPEG分别对照，单脸CPU约101→87→78→38%，保留30FPS。前两项逐像素一致；硬件JPEG像素不同且在推理后，不宣称等画质。
- EXPBUF会让已有MMAP缓冲进入bufinfo统计；核对exporter/大小/对象数和SDK get_dmabuf源码，再解释全局DMA增量。PSS与DMA不可直接相加。
- MPP简单put/get在超时后所有权可能已转移；显式task enqueue/pop划分责任，mock需模拟SDK真正释放queued资源。poll成功可能为正任务数量，只有负值报错。当前noncacheable路径不代表未来cacheable也无需同步。
- sanitizer缓存开关不证明每个目标都已插桩；核对实际编译与最终链接选项，特别是只链接OpenCV的独立适配器/测试。
- 失效边界：换模型/输入几何/OpenCV/SDK或改cacheable需重新验证；短测与每秒峰值不替代长时/多脸/微秒级峰值测试。


## 2026-09-12：ftrace忙时与RKNN模型文件副本

- 证据：outputs/ftrace-20260912/；任务占用load不同于MAC利用率，先同步记录脸数、FPS、频率和trace丢失。无脸10%与单脸24%不能当优化前后。
- function+sched_switch不足以分离睡眠与唤醒排队；补sched_wakeup→switch-in，当前单脸主线程P95约16us，无明显绑核依据。无job ID的schedule→IRQ配对只适用观察到无重叠的窗口。
- 匹配SDK2.3.2普通rknn_init flags0初始化后可释放文件副本；两模型各20次合成输入完整输出字节一致，单脸PSS约47.4→41.1MiB。特殊MODEL_BUFFER_ZERO_COPY等模式必须重审生命周期，不能复制此结论。
- 当前实际MEM_SIZE查询total/free SRAM均0，不根据头文件宏盲开SRAM。NEON固定点缩放逐像素一致，整机无脸CPU29.32→27.92%；没有NPU算术负载降低结论。


## 2026-09-18：云端音频参数与会话隔离
适用：companion协议v1适配。原Android后端hello返回Opus 24kHz，客户端上传仍16kHz；
录音与播放参数必须独立协商，不能因Android源码编码常量为16kHz而固定解码采样率。
协议缺少turn ID时，停止播放队列不等于隔离迟到回复；当前打断重建连接，
录音使用独立capture_epoch。证据见[验证记录](../../../../docs/verification-companion-20260918.md)
与tests/test_companion.py、tests/test_companion_audio.py。后端支持可靠轮次ID后可重新评估连接策略。
