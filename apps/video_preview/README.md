# RV1126B 独立摄像头预览

此应用只做摄像头采集、缩放、JPEG 编码和 HTTP 预览，不加载模型、不登记人脸，
不链接原有识别程序。Python 3 标准库即可运行；板端需有 GStreamer 和相应插件。

硬件路径：V4L2 DMA-BUF → 单帧可丢弃队列 → 编码器内置 RGA 缩放 → MPP JPEG →
独立二进制管道 → 最新 JPEG → HTTP MJPEG。原始 NV12 不进入 Python。
缩放仍会写目标缓冲区，压缩包管道及网络仍有拷贝，不能称整个链路零拷贝。
最多 8 个 HTTP 客户端，socket 超时 2 秒；网络发送不占用最新帧锁。
服务不落盘摄像头画面；仅输出运行日志。没有鉴权和 TLS，沿用开发板直连预览用途。

## 运行

先停止占用同一视频节点的程序。已验证板端 `/dev/video31` 为 2112×1568 NV12，
输出 960×712，JPEG quality 参数 75。其他固件需通过 `v4l2-ctl` 核对尺寸和节点。

```sh
cd /userdata/rtctrl-video-preview
python3 preview.py --device /dev/video31 --mode hardware --port 8080
```

浏览器访问 `http://板卡IP:8080/`；Ctrl+C 停止。后台运行可使用：

```sh
nohup python3 preview.py > server.log 2>&1 < /dev/null &
echo $! > preview.pid
```

停止前先用 `ps -p "$(cat preview.pid)" -o args=` 核对仍是本目录的预览进程，
再执行 `kill -TERM "$(cat preview.pid)"`。程序会关闭编码器并释放摄像头；未设置开机启动。

`--mode software` 使用 mmap、软件 videoscale 和 jpegenc，仅供独立预览对照。
`--duration 20` 自动停止；`--width`、`--height`、`--input-width`、`--input-height`
可调整尺寸，要求为偶数。`--help` 查看全部参数。

接口：`/`、`/stream.mjpg`、`/snapshot.jpg`、`/status.json`。
状态 `encoded_frame_age_ms` 是收到编码包后的帧龄，不是摄像头到屏幕延迟。
连续 5 秒没有 JPEG 或编码器结束时，服务报错并退出，不持续显示假运行状态。

## 板端对比（2026-09-12）

正点原子 RV1126B，OV13850，Linux 6.1.141；GStreamer 1.24.11、rockchipmpp 插件
1.14.4，RGA 日志版本 1.10.5。同摄像头、2112×1568 NV12 输入、960×712 输出、
quality=75，每个模式启动预热超过 60 帧，再采样 20 秒；一个本地 MJPEG 消费者。
这是软件/硬件独立预览对比，不是识别程序性能对比，也不是只改变拷贝次数的实验。

| 指标 | 软件缩放/JPEG | DMA-BUF + RGA + MPP |
| --- | ---: | ---: |
| 输出 FPS | 18.86 | 30.06 |
| Python + GStreamer CPU（100%=一核） | 105.52% | 32.55% |
| 合计 RSS | 30,284 KB | 40,432 KB |
| 管线平均延迟 | 68.95 ms | 13.29 ms |
| 管线 P95 延迟 | 83.61 ms | 13.65 ms |
| 延迟样本数（丢弃最初 3 秒） | 390 | 582 |
| 平均 JPEG 大小 | 67,362 B | 48,945 B |

不同编码器的 quality=75 不保证相同视觉质量；截图已检查可正常显示，未做客观画质评测。
硬件方案 RSS 较高。测试为短时结果，未覆盖长时间运行和拥塞网络。
管线延迟来自 [GStreamer latency tracer](https://gstreamer.freedesktop.org/documentation/coretracers/latency.html)，
范围为 v4l2src 输出至 fdsink，不含传感器/驱动缓冲、HTTP 和浏览器渲染。
SDK 与板端 debug 均确认 `using RGA converted buffer` 路径；未把所有内部缓冲假定为零拷贝。

## 复测和故障排查

先停止预览释放摄像头，然后在板端运行：

```sh
python3 benchmark.py --seconds 20 --output benchmark
```

结果和 trace 在 `benchmark/`，`--analyze-only` 只重新统计现有结果，不打开摄像头。
CPU 为预览 Python 与其 GStreamer 子进程，不包括基准消费者及内核后台工作。
benchmark 使用端口 8081，测试时应确保空闲。硬件链路排查可设置
`GST_DEBUG=mppenc:6,mpp:6`；不要在正式性能采样时开启大量编码器 debug 日志。

主机验证：

```sh
python3 -m unittest discover -s apps/video_preview -v
python3 -m py_compile apps/video_preview/preview.py apps/video_preview/benchmark.py
```

本次 6 项测试覆盖分片/合并 JPEG、段内伪结束标记、大小限制、HTTP 最新帧、慢请求
释放槽位及线程启动失败清理。此应用直接由 Python 执行，不涉及 CMake/C++ 目标。
