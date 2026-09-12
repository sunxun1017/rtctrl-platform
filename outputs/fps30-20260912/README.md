# 2026-09-12 RV1126B 三十帧对照

板卡：正点原子RV1126B，Linux6.1.141，RKNNRT2.3.2/RKNPU0.9.8，RGA1.10.5，TurboJPEG2.1.5。
图像2112×1568 NV12M→960×712 BGR；BT601 full，JPEG quality75；既有RetinaFace320和MobileFaceNet112，原人员库未改。

- `native-summary.json`：生产backend固定输入、两模型各30对，全部输出max_abs_error0。
- `rga-camera.txt`、`rga-face-compare.json`：同帧转换与模型对照；只保留数值，原图/embedding未归档。
- `rga-ab/`：同二进制CPU/RGA四轮20秒，每轮前4秒预热；`rga-ab-results.json`为汇总副本。
- `final-ab/`：同二进制六轮20秒，普通/native输入与同步/异步编码反向对照。
- `final-monitor/`：正式部署后的60秒检查，随后才运行perf，因此该段未受perf采样影响。
- `final-perf*`：随后各20秒record/stat，99Hz cpu-clock，Self/callgraph与原始数据。统计线程CPU，不能当作NPU利用率。

正式三十帧二进制SHA256：`cc67af9f1af7fa6a2a52f27a34c8c56ae4c261293f5db84b01e9fc21cc4e7670`。
部署后一分钟：30.0398识别/发布FPS，61/61样本有一张脸，序号缺口/识别覆盖/编码覆盖全0；PSS56431～56463KiB，FD18不变，CPU均值117.49%（单核100%）。
这不是十分钟或长期稳定性结果。板端日历不准，所有区间用monotonic；另有一个本地持续MJPEG读者及可能的浏览器连接。

模型哈希与归一化契约见应用native-fp16入口；临时脚本路径代表当次实验环境，重放前核对当前PID/程序及板端目录。
`fps30_*_ab.py`会在finally恢复之前的普通UInt8/TurboJPEG入口，不要当成正式启动脚本直接常驻运行。
编译完整程序参见../../apps/face_recognition/VIDEO.md；RGA独立工具编译需要同SDK的OpenCV/RGA库，native对照工具链接当前backend和runtime_loader。

perf重放命令（先用video.pid和/proc/PID/exe确认当前进程）：

```sh
perf record -e cpu-clock -F 99 -g -p "$PID" -o /tmp/preview.data -- sleep 20
perf report --stdio --no-children --percent-limit 1 -i /tmp/preview.data
perf stat -e task-clock,context-switches,cpu-migrations,page-faults -p "$PID" -- sleep 20
```

采样文件与符号报告对应上面的二进制；升级后二进制发生变化，不能拿新程序的地址解释旧perf.data。


## 再次perf后的输入循环优化

`copy-ab/` 的final代表6f7b4e0三十帧版本，copy代表仅把submit类型/布局分支移到循环外的版本。四轮各20秒，前3轮21/21样本无人脸；最后旧版有1/21样本出现人脸，故无脸CPU对照用case0与case1/2。
case0旧CPU102.0008%，新两轮平均91.2454%，约下降10.54%，各轮发布/识别均30.015FPS左右。
128个微基准批次覆盖112/320、Float32/UInt8、NHWC/NCHW、连续/ROI，全部写入逐值一致；`submit-summary.json`概括当前模型使用的UInt8 NHWC连续输入。
`copy-monitor/` 是部署后20秒无人脸验证；`copy-perf*`为随后20秒独立perf。与前一轮有脸perf负载不同，不直接相减Self百分比。
新二进制SHA256：`d768237f4a9d70eac73b27ec9bab53ffba882ce18cdba0732eee4d113294c4ed`。
`network-preview.json`是Windows端连续读取并解码180张JPEG，约30FPS，无原图保存；这也不等于Edge绘制帧率。
