# RV1126B CPU 50% 目标实测，2026-09-12

单核口径，模型/人员库不变，960×712、约30FPS、native FP16、异步JPEG。基线二进制 `d768237f4a9d70eac73b27ec9bab53ffba882ce18cdba0732eee4d113294c4ed`，最终部署 `59732949714e091979a3849a6af928399fb597e24a6b8188dd44d4f697f9dfb8`。厂商SDK OpenCV3.4.5、RGA1.10.5，板端RKNNRT2.3.2/RKNPU0.9.8。板端RTC不准；间隔用monotonic，日期按主机。

`ab/results.json` 是八段20秒正反向对照：CPU原版101.10/101.05%，缩放87.29/87.09%，直接DMA78.09/77.73%，MPP38.42/37.67%。第二段MPP有一个无脸状态样本，其余均单脸。相机格式在direct阶段切换到单内存NV12并保留；倒序staging支持该格式，最后基线再次复现CPU。不是完全固定的现场画面。

`production-resize.txt` 108完整letterbox用例逐像素一致；`capture-direct.txt` 同20帧BGR一致。`real-jpeg.txt` 是固定实拍BGR的数值结果，没有保存人脸图像。MPP相对原BGR的PSNR39.4584dB，Turbo41.2042dB，硬件预览不等同原JPEG像素。推理在编码之前。

最终MPP改用显式task API修复超时所有权后单独复查，不能把早期简化encode API的错误路径当成已验证。`final-monitor/` 为最终部署60秒：CPU37.839%，每秒采样最大39.001%，30.038FPS，PSS48425–48554KiB，61/61状态单脸，NPU24%，fd30、DMA24/44216320稳定，覆盖/序号缺口均零。不是长期内存或所有场景峰值保证。

`baseline-*`、`final-*` perf报告各独立20秒。最终735样本、0lost，TurboJPEG热点消失，detector_letterbox Self16.87%。这些是CPU样本占比，不是NPU负载。文本仅去掉行尾空白，数值不改。

`allocation-summary.json`、`allocation-trace.txt`：20秒应用heap/GEM分配释放均0；独立4KiB heap正对照各1，trace2/2。`final-stream-check.json`：Windows210张JPEG解码成功，30预热后180计时约29.99FPS，不是浏览器paintFPS。

`protected-hashes-*` 仅SHA256，不含人员库内容。全局DMA增量中的19873792字节是四个已有camera MMAP buffer的EXPBUF可见化，只有MPP两个编码对象3117056字节另计；不可与PSS直接相加。

复现脚本：先确认设备、PID、SDK和已获授权的本地人员库，再运行对应板端脚本。`cpu50_ab.py` 会停启视频，结束恢复optimized入口；`cpu50_deploy.py` 保存备份并带失败回退，属于本次固定部署目录的实验脚本，不是通用安装器。监测和perf分开，`fps30_monitor.py` 只保留数值。没有重新进行此前中止的10分钟测试。

验证：face-video与ASan各30项、默认release/asan各13项通过；匹配SDK交叉构建与实机通过。MPP task mock覆盖排队后超时/空任务、元数据和入队失败、返回任务失败、空/分片输出与重试，真实模拟queued资源销毁。MPP/RGA/JPEG目标显式继承编译和sanitizer选项；全仓格式检查既有失败未改。
