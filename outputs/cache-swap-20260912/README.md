# RV1126B 缓存与 swap：先看有没有发生

前面把重复申请和模型文件副本处理完了，我还想知道：剩下的 CPU 时间，会不会卡在缓存不命中？内存里的 Cached 很大，又是不是应该清缓存、调 swap？这次把这几个容易混在一起的量分开查。

## 先分清我在看哪一种缓存

CPU 的 L1/L2 缓存保存最近访问的数据和指令，miss 后需要从下一层取回来。`free` 里的 Cached 则主要是 Linux 文件页缓存，它们不是同一件事。swap 是匿名页等内存内容的换出空间；它也不等于 CPU 缓存。

这块板运行 Linux 6.1.141，CPU 是 Cortex-A53，应用仍是 native-fp16、RGA direct、MPP 异步 JPEG。没有换模型，没有改登记库，也没有取消 DMA 缓存同步。

## PMU 看到什么

在全程单脸的 20 秒窗口里，把 cycles、instructions、L1D access/refill、L2D access/refill 放在同一个 perf 事件组，运行比例都是 100%，没有轮换计数器。结果如下。

| 指标 | 实测 |
|---|---:|
| IPC，instructions / cycles | 0.495 |
| L1D refill / access | 1.08% |
| L2D refill / access | 32.75% |
| major / minor page faults | 0 / 0 |

这里我记的是 refill 比例，没有把 `100% - 比例` 直接写成应用的精确命中率。A53 的 L1D refill 还包含某些 TLB refill 访问，L2 又是统一缓存。软件预取也可能改变访问计数，不能只追求比例下降。[Arm 对 A53 PMU 事件的说明](https://developer.arm.com/community/arm-community-blogs/b/architectures-and-processors-blog/posts/profile-firmware-with-performance-monitor-unit-in-armv8-a-cpu) 给出了这些口径。

随后单独采 L2D refill 事件，约 1K 个样本，没有丢样本。`selected()` 的 NEON 取数占 Self 13.96%，`detector_letterbox` 占 6.94%。libc 的几个未解析地址也很突出，但没有符号时我不把它们直接认作 memcpy。这个采样给了一个检查入口，还不能把某个采样指令当成唯一原因。

复查命令中的 PID 要换成当前进程；采样会增加开销，不能和未采样窗口直接比较：

```sh
PID=$(cat /userdata/rtctrl-face-video/video.pid)
perf stat -e '{cycles,instructions,armv8_cortex_a53/l1d_cache/,armv8_cortex_a53/l1d_cache_refill/,armv8_cortex_a53/l2d_cache/,armv8_cortex_a53/l2d_cache_refill/}' -p "$PID" -- sleep 20
perf record -e armv8_cortex_a53/l2d_cache_refill/ -c 65536 -g -p "$PID" -o /tmp/cache.data -- sleep 20
perf report -i /tmp/cache.data --stdio --no-children -g none
```

## 在跨步读取前提前取数

960 像素宽的 RGB 输入缩到 320 时，要隔着像素取数据。原有 NEON 算术已经保持与 OpenCV 3.4.5 逐像素一致，这次只在两行源数据上增加有边界检查的预取，提前 288 字节，并覆盖后面的两条缓存线。没有改缩放计算和舍入。

我也试了提前 576 字节，反而不如 288。固定图和 16 张轮换图各跑六轮，每种每轮 300 次：

| 输入 | 原版 CPU 时间/次 | 提前 288 B | 提前 576 B |
|---|---:|---:|---:|
| 同一张图 | 约 2.263 ms | 1.822 ms | 1.900 ms |
| 16 张轮换 | 2.248 ms | 1.817 ms | 1.894 ms |

缩放这一段约省 19%。108 个固定、随机和非连续 ROI 用例与原版像素完全一致。host 和 ASan 的 face_algorithms 测试通过，实际 AArch64 路径另由板端对照覆盖。

第一组整机四轮测试里人脸出现次数差别很大，所以不能把整轮 CPU 差值算成优化收益。补做的两个 20 秒窗口都是 21/21 个状态样本有一张脸：CPU 从 37.568% 到 37.119%，视频从 30.014 到 30.065 FPS。这里只看到约 0.45 个百分点的短测改善，样本不足以保证每次都能复现同样幅度；19% 是缩放函数收益，不是整机收益。CPU 按单核 100% 计。

## swap 这一轮没有可调的瓶颈

`/proc/swaps` 只有表头，SwapTotal、SwapFree、SwapCached 都为 0。MemAvailable 约 656 MiB，Cached 约 490 MiB。20 秒里 pswpin/out、pgscan、pgsteal、allocstall、pgmajfault 的增量全部为 0。板上没有 memory PSI 文件，所以这里没有 PSI 数据。

`vm.swappiness` 虽然是 60，但当前没有启用 swap，不能据此说程序正在频繁换页。MemAvailable 是内核估算的无需换页即可供新应用使用的内存，包含部分可回收缓存；对应本机 SDK 的 `kernel/Documentation/filesystems/proc.rst` 中 MemAvailable 的说明。

我保留现有设置：没有创建 swap 文件，没有启用 zram，没有改 swappiness，也没有执行 drop_caches。当前并不缺内存，额外压缩或磁盘换页不能解决这里的 CPU 取数等待。以后如果 MemAvailable 持续下降，同时出现回收停顿或换页，再单独评估，不能拿 swap 代替泄漏排查。

```sh
cat /proc/swaps
grep -E 'MemAvailable|Cached|Swap' /proc/meminfo
grep -E 'pswp|pgscan|pgsteal|allocstall|pgmajfault' /proc/vmstat
cat /proc/sys/vm/swappiness
```

## 部署后复核

预取版部署后检查 60 秒：有效帧率 30.039 FPS，平均 CPU 35.707%，有脸状态样本 61。完整 CPU、PSS、NPU 和间隔记录保存在下面的原始数据中。这是一分钟检查，不能代替长时间峰值和稳定性测试。

[采样与分析](analysis.json)、[同负载补测](matched-ab/results.json)、[部署后一分钟](final-monitor/summary.json)。模型和登记库校验值保持不变。上一轮见 项目 outputs/ftrace-20260912。

这一分钟 PSS 为 40053–40086 KiB（约 39.1 MiB），NPU 平均 23.75%、频率 800 MHz，DMA-BUF 对象数保持 24。采集序号间断、最新帧覆盖和编码覆盖计数均为 0，流读取没有报错。这些是服务端与本地读流观测，不代表浏览器绘制帧率；NPU 的计算量没有因预取改变。最终一分钟未同时跑硬件 PMU，所以 35.71% 不能直接替代带 PMU 的 A/B 差值。
