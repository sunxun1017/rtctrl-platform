# RV1126B 视频人脸识别

正点原子板卡部署目录为 `/userdata/rtctrl-face-video`。本次直连固定地址：

**http://192.168.50.2:8080/**

模型、已有人员库与登记图片保存在持久目录；程序未设置开机自启动。旧的链路本地动态 IP 记录只适用于此前环境，当前使用固定直连地址；其他网络用 `ip a` 确认。

## 板端启动与停止

```sh
cd /userdata/rtctrl-face-video
sh stop-video.sh
sh start-video.sh 0.5
```

`0.5` 是这次演示使用的余弦阈值，没有经过陌生人/误识率标定。启动脚本要求显式给出阈值。默认读取已有 `gallery.json`；文件不存在时仅检测并显示 unknown。

补录同一人或登记其他人时，先停止程序，再运行：

```sh
sh stop-video.sh
sh start-video.sh 0.5 test-person
```

镜头中保持只有被登记者，正脸、无遮挡、光照稳定，约保持 8 秒。程序每隔至少 1 秒录入一个样本，默认 5 个；检测到多张脸时等待。样本追加到人员库，不自动覆盖原样本。可在 `video.log` 中确认 `sample 5/5`。不要同时运行多个登记程序。

若摄像头节点或端口变化，可以显式指定：

```sh
CAMERA_DEVICE=/dev/video31 PREVIEW_PORT=8080 PREVIEW_WIDTH=960 sh start-video.sh 0.5
```

`PREVIEW_WIDTH` 控制处理/预览图宽度，保留宽高比例；当前 2112×1568 输入缩至 960×712。默认 YUV 转换显式选择 BT.601/full，与本次板卡抓拍测试一致；其他相机应根据实际配置通过 `YUV_MATRIX`、`YUV_RANGE` 设置，不能通用套用。

## 浏览器与数据接口

- `/`：实时画面、检测框、关键点、姓名/unknown、相似度、FPS、耗时和待处理帧丢弃统计。
- `/stream.mjpg`：MJPEG 视频流。
- `/snapshot.jpg`：最新带标注 JPEG。
- `/status.json`：最新结构化识别结果。

此预览面向电脑与板卡直连或可信局域网，无登录和 TLS；不要直接映射到公网。最多同时处理 4 个 HTTP 连接，包括浏览器视频流与状态请求。浏览器预览只读，登记通过板端命令完成。

## 实机验证（2026-09-12）

平台：ATK-DLRV1126B、Linux 6.1.141、64 位 Buildroot，板端 RKNN Runtime 2.3.2、NPU driver 0.9.8，OV13850。

- 连续采集、NPU 检测、五点对齐、512 维特征提取、人员匹配和浏览器 MJPEG 预览已跑通。
- 补录完成后，日志中的 20 个抽样有脸帧均匹配到 test-person，相似度 0.7345–0.9587；这不是独立准确率评测，也不代表陌生人拒识率。
- 上述有脸日志样本平均 10.68 FPS，检测与特征/匹配平均 41.79 ms。FPS 包含主循环的 JPEG/发布开销及等待；不是纯 NPU FPS。
- 出队后至处理结束耗时约 84–126 ms，不包含传感器曝光、驱动排队、网络与浏览器显示延迟。
- 连续运行约 1 分 45 秒时 RSS 约 52 MB；这不是长时间内存泄漏测试。
- SIGTERM 正常停止后可重新启动，已有人员库能重新加载；应用未改固件、ISP 参数或板端运行库。

采集线程独占相机，在归还借用帧前转换为自有 BGR；推理只取最新待处理帧，旧帧可主动丢弃。慢浏览器不阻塞推理。当前是 CPU 像素转换/预处理和 JPEG 编码，不是端到端零拷贝。

## 2026-09-12 的输入与编码优化

`--input-type float32|uint8` 默认仍为 Float32。只有确认模型使用 0～255 RGB 像素、
并完成输出对照后才选择 UInt8。本次两个现有模型的 50 对确定性输入输出完全一致；
这不代表其他模型可以忽略归一化或直接改输入类型。

输入直接填写 backend 借用缓冲后 commit，输出用预分配 Float32 存储；不属于 native IO 零拷贝。
`--jpeg-encoder opencv|turbojpeg` 可选择系统 TurboJPEG，默认 OpenCV。头文件与构建要求见
[JPEG_ENCODER.md](JPEG_ENCODER.md)。系统缺少所需运行库或符号时明确报错，不自动换编码器。

在已构建 TurboJPEG 支持的部署包中，显式启用本轮组合：

```sh
sh stop-video.sh
RKNN_INPUT_TYPE=uint8 PREVIEW_JPEG_ENCODER=turbojpeg sh start-video.sh 0.5
```

不设置这两个环境变量即保留 Float32/OpenCV。脚本仍读取已有人员库，未改变登记规则。
`encode_ms` 只统计编码及独立输出复制；`processing_ms` 仍不含 JPEG，二者都不是浏览器端到端延迟。

perf、API 配对、颜色转换未采用实验和视频短对照原始数据保存于 `outputs/npu-20260912/`。
本轮八次 20 秒视频短测中，Float32/OpenCV 均值 11.48 FPS，UInt8/TurboJPEG 19.43 FPS；
CPU 单核口径均值约 194.27% → 188.87%，每帧 CPU 时间约 169.19 → 97.18 ms。
画面的人脸负载会变化，主要收益来自 JPEG，不能把独立 API 收益直接叠加为总 FPS。
部署后仍读取已有人员库，未新增登记。
本轮原计划的十分钟测试已按要求在约 386 秒停止，最终组合不能记为十分钟稳定性通过。

## 项目构建与测试

在 WSL 的项目目录中：

```sh
cmake --preset face-video
cmake --build --preset face-video -j4
ctest --preset face-video

scripts/face-recognition/build_rv1126b.sh /path/to/atk_dlrv1126b_linux6.1_sdk build/face-video-rv1126b
```

新目标：`rtctrl_face_video`。可用 `--help` 查看所有参数，支持限定运行时间/帧数以及 `--enroll-samples`。

验证结果：face-video 24/24、face-video ASan/UBSan 24/24、默认 release 13/13、默认 asan 13/13。补齐了原 V4L2 mock 对 glibc fortified `__poll_chk` 的包装，以便 sanitizer 测试正确拦截 poll；生产采集逻辑和用户已有 DMA-BUF 修改均保留。

代码入口为 `apps/face_recognition/video_main.cpp`、`video_frame.cpp`、`preview_server.cpp`。启动/停止脚本在 `scripts/face-recognition`。

新增视频源文件的 clang-format 检查通过，`git diff --check` 通过；全仓库 format-check 仍报告其他既有代码的格式差异，未进行全仓重排。

## 30 FPS 路径（2026-09-12）

新增三个显式选项，旧默认不变：`--frame-converter rga`、`--input-type native-fp16`、`--jpeg-mode async`。
板端已验证组合的启动入口：

```sh
cd /userdata/rtctrl-face-video
sh stop-video.sh
sh start-optimized-video.sh 0.5
```

这一阶段的 `start-optimized-video.sh` 启用 staging RGA、native FP16、TurboJPEG 和异步编码；后续硬件组合见末节，阈值仍由调用者传入。
native 模式只接受这次验证的两份模型 SHA256，使用转换时的 RGB mean/std。其他模型会拒绝启动，不能按形状猜归一化。
该输入路径仍显式同步缓存，不使用禁用 flush 的标志。

RGA 先把单/双平面 NV12/NV21 拷入可复用 staging，复用 import handle，同步转换后返回独立 BGR。
它不是摄像头到模型的全链路零拷贝。插值与 CPU 最近邻不同：同一张实拍图的人脸框 IoU 0.984752、embedding cosine 0.981797，不能当作准确率验证。
异步编码只保留一个待编码帧；图像和结果 JSON 一起交给编码线程，慢消费者不形成无限队列。

页面区分采集、识别、发布 FPS。`dropped` 保持兼容，等于 `latest_overwrites`，不是驱动丢帧。
`capture_sequence_gaps` 是预热后 V4L2 序号前向缺口；`encode_overwrites` 是等待编码时被新帧替换的数量。
`capture_convert_ms` 包含 staging、RGA 和独立输出复制；`processing_ms` 不含编码。
`ready_age_ms` 从用户态 DQBUF 返回计到 JPEG 完成，未覆盖曝光、驱动排队、网络和浏览器显示。
`publish_fps` 与 `published` 表示服务器发布，不是 Edge 实际绘制帧率。

同一二进制、RGA 输入、TurboJPEG、单人脸的反向对照：UInt8 同步 17.36 FPS，native 同步 24.06 FPS，native 异步两轮 30.02 FPS。
两轮异步采样各 20 秒，21/21 状态样本有人脸，三种缺口/覆盖均为 0。不同轮次画面仍可能变化。
详细数据在 `outputs/fps30-20260912/`，一分钟部署后检查与 perf 复查单独记录，不替代长期压力测试。

交叉构建时沿用厂家 SDK，并显式配置可选依赖：

```sh
cmake -S . -B build/face-video-rv1126b \
  -DRTCTRL_RGA_INCLUDE_DIR="$SDK/external/rknpu2/examples/3rdparty/rga/include" \
  -DRTCTRL_RGA_LIBRARY="$SDK/external/rknpu2/examples/3rdparty/rga/libs/Linux/gcc-aarch64/librga.so" \
  -DRTCTRL_TURBOJPEG_INCLUDE_DIR="$TURBOJPEG_HEADERS"
cmake --build build/face-video-rv1126b --target rtctrl_face_video -j4
```

此命令接在前文交叉工具链配置后，`SDK`、`TURBOJPEG_HEADERS` 指向匹配的本地依赖；没有相应依赖时普通路径仍可构建。
回退可停止后执行 `RKNN_INPUT_TYPE=uint8 PREVIEW_JPEG_ENCODER=turbojpeg PREVIEW_FRAME_CONVERTER=cpu PREVIEW_JPEG_MODE=sync sh start-video.sh 0.5`。


再次perf后，submit的类型/布局分支移到像素循环外，RGB逐值结果保持一致。
UInt8 NHWC 320输入微基准3530.75→98.69μs，112输入426.25→11.90μs；完整无人脸视频30FPS下CPU102.00%→91.25%（两轮新版本均值）。
这轮无脸结果不能当成单脸CPU；单脸三十帧验证见上一批。新版本部署后20秒约30.016FPS，电脑端180张JPEG全部解码成功。

## CPU 50% 以下的硬件组合（2026-09-12）

`start-optimized-video.sh` 现选择 native FP16、rga-direct、MPP JPEG、异步编码，显式请求相机 2112×1568 单内存 NV12；预览仍为 960×712。`CAMERA_WIDTH`、`CAMERA_HEIGHT` 可共同覆盖相机尺寸，必须先验证对应设备。普通 `start-video.sh` 的默认仍不变。

新增 `--frame-converter rga-direct --capture-width 2112 --capture-height 1568` 与 `--jpeg-encoder mpp`。前者只接受可完整导出的单平面 NV12/NV21，缓存 import handle 并验证 fd 身份，RGA 同步完成后才归还相机帧；独立 BGR 输出仍保留。S_FMT 格式选择会在退出后留在设备上，staging 回退支持该 NV12 格式。

MPP 通过匹配 SDK 的 RGA 和 MPP 库链接，采用非 cacheable DRM 输入/输出缓冲、固定 BGR staging、显式 task 所有权与独立 JPEG 返回值。尺寸/质量变化时重建会话；目前只支持偶数图像尺寸与质量 1–99。未来改为 cacheable 缓冲时，必须重新核对 advanced API 的输出同步，不能沿用当前假设。1000 ms poll 超时不代表驱动异常下整个析构有硬性一秒上限。

在前文交叉构建配置后增加：

```sh
cmake -S . -B build/face-video-rv1126b \
  -DRTCTRL_MPP_INCLUDE_DIR="$SDK/external/rknpu2/examples/3rdparty/mpp/include/rockchip" \
  -DRTCTRL_MPP_LIBRARY="$SDK/external/rknpu2/examples/3rdparty/mpp/Linux/aarch64/librockchip_mpp.so"
cmake --build build/face-video-rv1126b --target rtctrl_face_video -j4
```

同场景八段正反向对照，每段 20 秒：原版约 101% 单核 CPU，精确缩放约 87%，直接 DMA 约 78%，MPP 约 38%，都约 30 FPS。缩放和直接 DMA 固定输入逐像素相同；MPP JPEG 解码像素不同，实拍固定图 PSNR 41.20→39.46 dB，不是完全相同的画质，但编码发生在推理之后。没有修改模型、人员库或系统运行库。

部署后一分钟全单脸：CPU 平均 37.839%、每秒最大 39.001%，处理/发布约 30.038 FPS，PSS 约 47.3–47.4 MiB，NPU 24%/800 MHz，三种缺口/覆盖均零。DMA-BUF 新可见的四块摄像头缓冲不是新增图像页；MPP 另占约 2.97 MiB DMA，不能把 PSS 和全局 DMA 相加。20 秒 ftrace 未见应用重复申请/释放 heap/GEM 缓冲，正对照有效。

电脑端 30 帧预热后连续解码 180 张约 29.99 FPS；不是 Edge 绘制帧率。此次短测不能替代十分钟或长期峰值测试。完整配置、样本、质量与 perf 证据见 [CPU 优化记录](../../outputs/cpu50-20260912/README.md)。

只回退 JPEG：停止后设置 `RKNN_INPUT_TYPE=native-fp16 PREVIEW_FRAME_CONVERTER=rga-direct CAMERA_WIDTH=2112 CAMERA_HEIGHT=1568 PREVIEW_JPEG_ENCODER=turbojpeg PREVIEW_JPEG_MODE=async sh start-video.sh 0.5`。回退直接 DMA：清除 CAMERA_WIDTH/HEIGHT，converter 改为 rga。
