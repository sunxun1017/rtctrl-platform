# RV1126B 视频人脸识别

已部署到正点原子板卡 `/userdata/rtctrl-face-video`，当前浏览器地址：

**http://169.254.77.52:8080/**

程序正在后台运行，已登记 `test-person`。模型、人员库与登记图片保存在持久目录；程序未设置开机自启动。板卡 IP 在重启后可能变化，重新用 `ip a` 确认。

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